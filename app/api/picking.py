import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.picking import PickingListCreate, PickingListOut, ScanResult
from app.services import picking_service
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
def create_picking_list(data: PickingListCreate, db: Session = Depends(get_db)):
    try:
        pl = picking_service.create_picking_list(db, data.order_ids)
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
def scan_qr(qr_code: str, db: Session = Depends(get_db)):
    result = picking_service.scan_pick_item(db, qr_code)
    return result


@router.get("/{picking_list_id}/qrcodes")
def export_qrcodes(picking_list_id: str, db: Session = Depends(get_db)):
    """Export all QR codes for a picking list as a printable PDF (2x1 inch labels)."""
    from app.models.order import Order

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    if not pl.items:
        raise HTTPException(400, "No items in picking list")

    # Cache order info to avoid repeated queries
    order_cache = {}
    pages = []

    for item in pl.items:
        # Get order info
        if item.order_id not in order_cache:
            order = db.query(Order).filter(Order.id == item.order_id).first()
            order_cache[item.order_id] = order

        order = order_cache[item.order_id]

        # Build text lines for right side
        lines = [
            ("20", item.sku, "#000000"),
            ("12", item.product_name, "#333333"),
        ]
        if item.variant_label:
            lines.append(("10", item.variant_label, "#555555"))
        lines.append(("10", f"#{item.sequence} | {item.qr_code}", "#888888"))
        if order:
            order_label = order.order_number
            if order.order_name:
                order_label += f" ({order.order_name})"
            lines.append(("9", order_label, "#888888"))

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
