import io

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
    result = picking_service.scan_pick_item(db, qr_code)
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
