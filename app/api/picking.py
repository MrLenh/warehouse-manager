import io
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.picking import PickingListCreate, PickingListOut, ScanResult
from app.services import auth_service, picking_service
from app.services.qr_service import _get_font, _draw_label_2x1, DPI, LABEL_W, LABEL_H

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
        result = picking_service.scan_pick_item(db, qr_code)
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


@router.delete("/{picking_list_id}/orders/{order_id}")
def remove_order_from_picking_list(picking_list_id: str, order_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove a single order from a picking list (unpack from batch)."""
    try:
        result = picking_service.remove_order_from_picking_list(db, picking_list_id, order_id)
        auth_service.log_activity(db, user.id, user.username, "unpack_order", detail=f"Removed order {order_id}", ip=request.client.host if request.client else "")
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{picking_list_id}/qrcodes")
def export_qrcodes(picking_list_id: str, db: Session = Depends(get_db)):
    """Export all QR codes for a picking list as a printable PDF (2x1 inch labels), sorted by SKU."""
    from app.models.order import Order

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    if not pl.items:
        raise HTTPException(400, "No items in picking list")

    # Sort items by SKU then sequence for faster label sticking
    sorted_items = sorted(pl.items, key=lambda i: (i.sku, i.variant_label or "", i.sequence))

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
    return StreamingResponse(buf, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename=picking-{pl.picking_number}.pdf"
    })


@router.get("/{picking_list_id}/picking-summary")
def export_picking_summary(picking_list_id: str, db: Session = Depends(get_db)):
    """Export A4 picking summary PDF — aggregated SKU quantities with thumbnail, location."""
    from PIL import Image, ImageDraw

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

        # Find variant by variant_sku matching row["sku"]
        location = ""
        image_url = ""
        if product:
            image_url = product.image_url or ""
            location = product.location or ""
            # Check if this SKU is a variant SKU
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

    # --- Generate A4 PDF with table ---
    A4_W, A4_H = 2480, 3508  # A4 at 300 DPI
    MARGIN = 120
    ROW_H = 100
    HEADER_H = 140
    THUMB_SIZE = 70
    COL_WIDTHS = [100, 400, 600, 400, 150, 490]  # thumbnail, sku, product, variant, qty, location
    TABLE_W = sum(COL_WIDTHS)

    font_h = _get_font(36)
    font_b = _get_font(32)
    font_title = _get_font(52)
    font_small = _get_font(28)

    pages = []
    rows_per_page = (A4_H - MARGIN * 2 - HEADER_H - 80) // ROW_H

    for page_idx in range(0, len(rows), rows_per_page):
        page_rows = rows[page_idx:page_idx + rows_per_page]
        img = Image.new("RGB", (A4_W, A4_H), "white")
        draw = ImageDraw.Draw(img)

        # Title
        y = MARGIN
        draw.text((MARGIN, y), f"Picking Summary - {pl.picking_number}", fill="#000", font=font_title)
        draw.text((MARGIN, y + 58), f"{len(rows)} SKUs, {sum(r['qty'] for r in rows)} total units", fill="#888", font=font_small)
        if page_idx > 0:
            draw.text((A4_W - MARGIN - 300, y), f"Page {page_idx // rows_per_page + 1}", fill="#888", font=font_small)
        y += HEADER_H

        # Table header
        headers = ["", "SKU", "Product Name", "Variant", "Qty", "Location"]
        x = MARGIN
        draw.rectangle([(MARGIN, y), (MARGIN + TABLE_W, y + ROW_H)], fill="#f0f0f0")
        for i, h in enumerate(headers):
            draw.text((x + 12, y + 30), h, fill="#333", font=font_h)
            x += COL_WIDTHS[i]
        draw.line([(MARGIN, y + ROW_H), (MARGIN + TABLE_W, y + ROW_H)], fill="#ccc", width=2)
        y += ROW_H

        # Table rows
        for row in page_rows:
            x = MARGIN

            # Thumbnail placeholder
            thumb_x = x + (COL_WIDTHS[0] - THUMB_SIZE) // 2
            thumb_y = y + (ROW_H - THUMB_SIZE) // 2
            draw.rectangle([(thumb_x, thumb_y), (thumb_x + THUMB_SIZE, thumb_y + THUMB_SIZE)],
                           fill="#f5f5f5", outline="#ddd")

            # Try to load thumbnail from URL if it's a local path
            if row["image_url"]:
                try:
                    img_path = row["image_url"]
                    if img_path.startswith("/"):
                        # Try relative to static dir
                        for base in ["app/static", "."]:
                            full = os.path.join(base, img_path.lstrip("/"))
                            if os.path.exists(full):
                                img_path = full
                                break
                    if os.path.exists(img_path):
                        thumb = Image.open(img_path).convert("RGB")
                        thumb = thumb.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                        img.paste(thumb, (thumb_x, thumb_y))
                except Exception:
                    pass

            x += COL_WIDTHS[0]

            # SKU
            draw.text((x + 12, y + 32), row["sku"], fill="#000", font=font_b)
            x += COL_WIDTHS[1]

            # Product name (truncate if needed)
            name = row["product_name"]
            while name and draw.textbbox((0, 0), name, font=font_b)[2] > COL_WIDTHS[2] - 24:
                name = name[:-4] + "..."
            draw.text((x + 12, y + 32), name, fill="#333", font=font_b)
            x += COL_WIDTHS[2]

            # Variant
            draw.text((x + 12, y + 32), row["variant_label"] or "-", fill="#555", font=font_b)
            x += COL_WIDTHS[3]

            # Qty (bold, larger)
            qty_font = _get_font(40)
            draw.text((x + 12, y + 28), str(row["qty"]), fill="#000", font=qty_font)
            x += COL_WIDTHS[4]

            # Location
            loc = row["location"] or "-"
            draw.text((x + 12, y + 32), loc, fill="#555", font=font_b)

            # Row border
            draw.line([(MARGIN, y + ROW_H), (MARGIN + TABLE_W, y + ROW_H)], fill="#e8e8e8", width=1)
            y += ROW_H

        # Table outer border
        table_bottom = MARGIN + HEADER_H + ROW_H * (len(page_rows) + 1)
        draw.rectangle([(MARGIN, MARGIN + HEADER_H), (MARGIN + TABLE_W, table_bottom)], outline="#ccc", width=2)

        pages.append(img)

    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=300)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename=picking-summary-{pl.picking_number}.pdf"
    })
