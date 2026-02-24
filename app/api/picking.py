import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.picking import PickingListCreate, PickingListOut, ScanResult
from app.services import picking_service
from app.services.qr_service import _get_font, QR_SIZE, LABEL_WIDTH, PADDING

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
    """Export all QR codes for a picking list as a printable PDF (5x7 inch pages)."""
    import qrcode
    from PIL import Image, ImageDraw

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    if not pl.items:
        raise HTTPException(400, "No items in picking list")

    # 5x7 inches at 300 DPI
    DPI = 300
    PAGE_W = int(5 * DPI)   # 1500
    PAGE_H = int(7 * DPI)   # 2100
    QR_LABEL_SIZE = 800
    MARGIN = 100

    font_title = _get_font(48)
    font_sku = _get_font(56)
    font_name = _get_font(36)
    font_detail = _get_font(28)
    font_qr_code = _get_font(24)

    pages = []
    for item in pl.items:
        # Generate QR code
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        qr.add_data(item.qr_code)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_img = qr_img.resize((QR_LABEL_SIZE, QR_LABEL_SIZE), Image.NEAREST)

        # Create page
        page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        draw = ImageDraw.Draw(page)

        # Center QR code horizontally, place near top
        qr_x = (PAGE_W - QR_LABEL_SIZE) // 2
        qr_y = MARGIN + 60
        page.paste(qr_img, (qr_x, qr_y))

        # Text below QR
        text_y = qr_y + QR_LABEL_SIZE + 40

        # SKU (large, bold)
        _draw_centered(draw, item.sku, font_sku, PAGE_W, text_y, "#000000")
        text_y += 70

        # Product name
        name_display = item.product_name[:35] + "..." if len(item.product_name) > 35 else item.product_name
        _draw_centered(draw, name_display, font_name, PAGE_W, text_y, "#333333")
        text_y += 50

        # Variant
        if item.variant_label:
            _draw_centered(draw, item.variant_label, font_detail, PAGE_W, text_y, "#555555")
            text_y += 40

        # Sequence / unit number
        _draw_centered(draw, f"Unit #{item.sequence}", font_detail, PAGE_W, text_y, "#667eea")
        text_y += 50

        # QR code string (for manual entry)
        _draw_centered(draw, item.qr_code, font_qr_code, PAGE_W, text_y, "#888888")
        text_y += 40

        # Order info at bottom
        from app.models.order import Order
        order = db.query(Order).filter(Order.id == item.order_id).first()
        if order:
            order_info = f"Order: {order.order_number}"
            if order.order_name:
                order_info += f" ({order.order_name})"
            _draw_centered(draw, order_info, font_detail, PAGE_W, text_y, "#888888")
            text_y += 36
            _draw_centered(draw, order.customer_name, font_detail, PAGE_W, text_y, "#888888")

        # Border
        draw.rectangle([(20, 20), (PAGE_W - 21, PAGE_H - 21)], outline="#cccccc", width=2)

        # Picking list number at top
        _draw_centered(draw, pl.picking_number, font_qr_code, PAGE_W, 30, "#aaaaaa")

        pages.append(page)

    if not pages:
        raise HTTPException(400, "No labels generated")

    # Save as multi-page PDF
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=DPI)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename=picking-{pl.picking_number}.pdf"
    })


def _draw_centered(draw, text: str, font, page_w: int, y: int, color: str):
    """Draw text centered horizontally on the page."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (page_w - tw) // 2
    draw.text((x, y), text, fill=color, font=font)
