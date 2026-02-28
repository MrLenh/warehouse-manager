import io
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.picking import PickingListCreate, PickingListOut, ScanResult
from app.services import auth_service, picking_service
from app.services.qr_service import _draw_label_2x1, DPI

router = APIRouter(prefix="/picking-lists", tags=["picking"])


def _to_picking_list_out(pl) -> dict:
    """Convert PickingList model to dict with computed fields."""
    total = len(pl.items)
    picked = sum(1 for i in pl.items if i.picked)
    order_ids = set(i.order_id for i in pl.items)
    return {
        "id": pl.id,
        "picking_number": pl.picking_number,
        "status": pl.status,
        "assigned_to": pl.assigned_to,
        "created_at": pl.created_at,
        "updated_at": pl.updated_at,
        "items": pl.items,
        "total_items": total,
        "picked_items": picked,
        "order_count": len(order_ids),
    }


@router.post("", response_model=PickingListOut)
def create_picking_list(data: PickingListCreate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        pl = picking_service.create_picking_list(db, data.order_ids)
        auth_service.log_activity(db, user.id, user.username, "create_batch", detail=f"{pl.picking_number} ({len(data.order_ids)} orders)", ip=request.client.host if request.client else "")
        return _to_picking_list_out(pl)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("", response_model=list[PickingListOut])
def list_picking_lists(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    pls = picking_service.list_picking_lists(db, skip, limit)
    return [_to_picking_list_out(pl) for pl in pls]


@router.get("/{picking_list_id}", response_model=PickingListOut)
def get_picking_list(picking_list_id: str, db: Session = Depends(get_db)):
    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")
    return _to_picking_list_out(pl)


@router.get("/{picking_list_id}/progress")
def get_progress(picking_list_id: str, db: Session = Depends(get_db)):
    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")
    return picking_service.get_picking_list_progress(db, picking_list_id)


@router.post("/scan", response_model=ScanResult)
def scan_qr(qr_code: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = picking_service.scan_pick_item(db, qr_code, username=user.username)
    except Exception as e:
        raise HTTPException(400, f"Scan error: {e}")
    if result["success"]:
        auth_service.log_activity(db, user.id, user.username, "scan", detail=f"{qr_code} → {result.get('order_number','')} ({result.get('order_picked',0)}/{result.get('order_total',0)})", ip=request.client.host if request.client else "")
    return result


@router.delete("/{picking_list_id}")
def delete_picking_list(picking_list_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a picking list and release all orders (unpack entire batch)."""
    try:
        result = picking_service.delete_picking_list(db, picking_list_id)
        auth_service.log_activity(db, user.id, user.username, "delete_batch", detail=f"{result['orders_released']} orders released", ip=request.client.host if request.client else "")
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{picking_list_id}/archive")
def archive_picking_list(picking_list_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Archive a picking list. Only empty or done batches can be archived."""
    from app.models.picking import PickingListStatus
    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")
    if pl.status == PickingListStatus.ARCHIVED:
        raise HTTPException(400, "Already archived")
    order_count = len(set(i.order_id for i in pl.items))
    if order_count > 0 and pl.status not in (PickingListStatus.DONE,):
        raise HTTPException(400, "Only empty or done batches can be archived")
    pl.status = PickingListStatus.ARCHIVED
    db.commit()
    auth_service.log_activity(db, user.id, user.username, "archive_batch", detail=pl.picking_number, ip=request.client.host if request.client else "")
    return {"archived": pl.id, "picking_number": pl.picking_number}


@router.delete("/{picking_list_id}/orders/{order_id}")
def remove_order_from_picking_list(picking_list_id: str, order_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove a single order from a picking list (unpack from batch)."""
    try:
        result = picking_service.remove_order_from_picking_list(db, picking_list_id, order_id)
        auth_service.log_activity(db, user.id, user.username, "unpack_order", detail=f"Removed order {order_id}", ip=request.client.host if request.client else "")
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{picking_list_id}/label")
def export_picking_list_label(picking_list_id: str, db: Session = Depends(get_db)):
    """Export a QR label for the picking list itself (links to mobile summary page)."""
    from app.services.qr_service import generate_picking_list_qr

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    order_count = len(set(i.order_id for i in pl.items))
    item_count = len(pl.items)
    png_bytes = generate_picking_list_qr(pl, order_count=order_count, item_count=item_count)

    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png", headers={
        "Content-Disposition": f"inline; filename=label-{pl.picking_number}.png"
    })


@router.get("/{picking_list_id}/summary")
def get_picking_summary(picking_list_id: str, db: Session = Depends(get_db)):
    """Public JSON summary for mobile picking page. Also transitions ACTIVE → PROCESSING."""
    from app.models.picking import PickingListStatus

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    # Auto-transition ACTIVE → PROCESSING when summary is viewed (scanned)
    if pl.status == PickingListStatus.ACTIVE:
        pl.status = PickingListStatus.PROCESSING
        db.commit()
        db.refresh(pl)

    progress = picking_service.get_picking_list_progress(db, picking_list_id)
    total_items = len(pl.items)
    picked_items = sum(1 for i in pl.items if i.picked)

    return {
        "picking_number": pl.picking_number,
        "status": pl.status if isinstance(pl.status, str) else pl.status.value,
        "assigned_to": pl.assigned_to,
        "total_items": total_items,
        "picked_items": picked_items,
        "order_count": len(progress),
        "orders": progress,
    }


@router.get("/{picking_list_id}/qrcodes")
def export_qrcodes(
    picking_list_id: str,
    db: Session = Depends(get_db),
    sku: str | None = Query(None, description="Filter labels by SKU"),
):
    """Export QR codes for a picking list as a printable PDF (2x1 inch labels), sorted by SKU."""
    from app.models.order import Order

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    if not pl.items:
        raise HTTPException(400, "No items in picking list")

    items = pl.items
    if sku:
        items = [i for i in items if i.sku == sku]
        if not items:
            raise HTTPException(404, f"No items found for SKU: {sku}")

    # Sort items by SKU then sequence for faster label sticking
    sorted_items = sorted(items, key=lambda i: (i.sku, i.variant_label or "", i.sequence))

    # Cache order info to avoid repeated queries
    order_cache = {}
    pages = []

    for item in sorted_items:
        # Get order info
        if item.order_id not in order_cache:
            order = db.query(Order).filter(Order.id == item.order_id).first()
            order_cache[item.order_id] = order

        order = order_cache[item.order_id]

        # Build text lines for right side
        lines = [
            ("36", item.sku, "#000000"),
            ("26", item.product_name, "#333333"),
        ]
        if item.variant_label:
            lines.append(("20", item.variant_label, "#555555"))
        lines.append(("20", f"#{item.sequence} | {item.qr_code}", "#888888"))
        if order:
            order_label = order.order_number
            if order.order_name:
                order_label += f" ({order.order_name})"
            lines.append(("18", order_label, "#888888"))

        label_img = _draw_label_2x1(item.qr_code, lines)
        pages.append(label_img)

    if not pages:
        raise HTTPException(400, "No labels generated")

    # Save as multi-page PDF
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=DPI)
    buf.seek(0)
    fname = f"picking-{pl.picking_number}"
    if sku:
        fname += f"-{sku}"
    return StreamingResponse(buf, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename={fname}.pdf"
    })


@router.get("/{picking_list_id}/picking-summary")
def export_picking_summary(picking_list_id: str, db: Session = Depends(get_db)):
    """Export A4 picking summary as printable HTML table — crisp text, optimized for print."""
    from html import escape

    from fastapi.responses import HTMLResponse

    from app.models.product import Product, Variant

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    if not pl.items:
        raise HTTPException(400, "No items in picking list")

    # Aggregate by (sku, variant_label)
    sku_map: dict[str, dict] = {}
    for item in pl.items:
        key = item.sku
        if key not in sku_map:
            sku_map[key] = {
                "sku": item.sku,
                "product_name": item.product_name,
                "variant_label": item.variant_label,
                "product_id": item.product_id,
                "qty": 0,
            }
        sku_map[key]["qty"] += 1

    # Fetch product/variant info for location + image
    product_cache: dict[str, Product] = {}
    variant_cache: dict[str, Variant | None] = {}
    rows = sorted(sku_map.values(), key=lambda r: r["sku"])

    for row in rows:
        pid = row["product_id"]
        if pid not in product_cache:
            product_cache[pid] = db.query(Product).filter(Product.id == pid).first()
        product = product_cache[pid]

        location = ""
        image_url = ""
        if product:
            image_url = product.image_url or ""
            location = product.location or ""
            if row["sku"] != product.sku:
                cache_key = row["sku"]
                if cache_key not in variant_cache:
                    variant_cache[cache_key] = db.query(Variant).filter(
                        Variant.product_id == pid, Variant.variant_sku == row["sku"]
                    ).first()
                variant = variant_cache[cache_key]
                if variant and variant.location:
                    location = variant.location

        row["location"] = location
        row["image_url"] = image_url

    total_units = sum(r["qty"] for r in rows)

    # Build HTML table rows
    table_rows = ""
    for i, row in enumerate(rows):
        img_html = ""
        if row["image_url"]:
            img_html = f'<img src="{escape(row["image_url"])}" class="thumb">'
        else:
            img_html = '<div class="thumb-placeholder"></div>'

        table_rows += f"""<tr>
            <td class="num">{i + 1}</td>
            <td class="img-cell">{img_html}</td>
            <td class="sku">{escape(row["sku"])}</td>
            <td class="product">{escape(row["product_name"])}</td>
            <td class="variant">{escape(row["variant_label"] or "—")}</td>
            <td class="qty">{row["qty"]}</td>
            <td class="location">{escape(row["location"] or "—")}</td>
            <td class="check"></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Picking Summary — {escape(pl.picking_number)}</title>
<style>
@page {{
    size: A4;
    margin: 12mm 10mm;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, 'Segoe UI', Arial, Helvetica, sans-serif;
    font-size: 14px;
    color: #111;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}

.header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 3px solid #333;
}}
.header h1 {{
    font-size: 22px;
    font-weight: 700;
}}
.header .meta {{
    font-size: 13px;
    color: #555;
    text-align: right;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    page-break-inside: auto;
}}
thead {{
    display: table-header-group;
}}
tr {{
    page-break-inside: avoid;
}}
th {{
    background: #333;
    color: #fff;
    font-weight: 600;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 6px;
    text-align: left;
    border: 1px solid #333;
}}
td {{
    padding: 6px;
    border: 1px solid #ccc;
    vertical-align: middle;
    font-size: 14px;
}}
tr:nth-child(even) {{
    background: #f7f7f7;
}}

.num {{
    width: 30px;
    text-align: center;
    color: #888;
    font-size: 12px;
}}
.img-cell {{
    width: 48px;
    text-align: center;
    padding: 3px;
}}
.thumb {{
    width: 42px;
    height: 42px;
    object-fit: cover;
    border-radius: 4px;
    border: 1px solid #ddd;
}}
.thumb-placeholder {{
    width: 42px;
    height: 42px;
    background: #f0f0f0;
    border-radius: 4px;
    border: 1px solid #e8e8e8;
    margin: 0 auto;
}}
.sku {{
    font-weight: 700;
    font-size: 15px;
    white-space: nowrap;
}}
.product {{
    max-width: 200px;
}}
.variant {{
    color: #555;
    font-size: 13px;
}}
.qty {{
    text-align: center;
    font-weight: 800;
    font-size: 20px;
    width: 55px;
    color: #111;
}}
.location {{
    font-size: 13px;
    color: #333;
}}
.check {{
    width: 40px;
    text-align: center;
}}
.check-box {{
    display: inline-block;
    width: 18px;
    height: 18px;
    border: 2px solid #999;
    border-radius: 3px;
}}

.footer {{
    margin-top: 16px;
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #888;
    border-top: 1px solid #ccc;
    padding-top: 6px;
}}

/* Print button — hidden in print */
.print-bar {{
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: #333;
    color: #fff;
    padding: 10px 20px;
    display: flex;
    align-items: center;
    gap: 16px;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,.3);
}}
.print-bar button {{
    background: #667eea;
    color: #fff;
    border: none;
    padding: 8px 24px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
}}
.print-bar button:hover {{
    background: #5a6fd6;
}}
body {{ padding-top: 52px; }}

@media print {{
    .print-bar {{ display: none !important; }}
    body {{ padding-top: 0; }}
}}
</style>
</head>
<body>

<div class="print-bar">
    <button onclick="window.print()">Print</button>
    <span>{escape(pl.picking_number)} — {len(rows)} SKUs, {total_units} units</span>
</div>

<div class="header">
    <h1>Picking Summary — {escape(pl.picking_number)}</h1>
    <div class="meta">
        {len(rows)} SKUs &nbsp;|&nbsp; {total_units} total units<br>
        {pl.created_at.strftime("%Y-%m-%d %H:%M") if pl.created_at else ""}
    </div>
</div>

<table>
    <thead>
        <tr>
            <th>#</th>
            <th>Img</th>
            <th>SKU</th>
            <th>Product</th>
            <th>Variant</th>
            <th style="text-align:center">Qty</th>
            <th>Location</th>
            <th style="text-align:center">&#10003;</th>
        </tr>
    </thead>
    <tbody>
        {table_rows}
    </tbody>
</table>

<div class="footer">
    <span>{escape(pl.picking_number)}</span>
    <span>{len(rows)} SKUs, {total_units} units</span>
</div>

</body>
</html>"""

    return HTMLResponse(content=html)
