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
    """Export all QR codes for a picking list as a printable PNG page."""
    import qrcode
    from PIL import Image, ImageDraw

    pl = picking_service.get_picking_list(db, picking_list_id)
    if not pl:
        raise HTTPException(404, "Picking list not found")

    if not pl.items:
        raise HTTPException(400, "No items in picking list")

    font_big = _get_font(18)
    font_med = _get_font(14)
    font_sm = _get_font(11)

    labels = []
    for item in pl.items:
        # Generate QR for each pick item
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
        qr.add_data(item.qr_code)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_size = 200
        qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)

        # Build label
        label_w = 260
        lines = [
            ("big", item.sku),
            ("med", item.product_name[:25] + "..." if len(item.product_name) > 25 else item.product_name),
        ]
        if item.variant_label:
            lines.append(("sm", item.variant_label))
        lines.append(("sm", f"#{item.sequence} | {item.qr_code}"))

        line_h = {"big": 24, "med": 20, "sm": 16}
        text_h = sum(line_h[t] for t, _ in lines) + 8
        total_h = qr_size + text_h + 24

        img = Image.new("RGB", (label_w, total_h), "white")
        qr_x = (label_w - qr_size) // 2
        img.paste(qr_img, (qr_x, 8))

        draw = ImageDraw.Draw(img)
        y = qr_size + 12
        for lt, text in lines:
            font = {"big": font_big, "med": font_med, "sm": font_sm}[lt]
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            x = (label_w - tw) // 2
            draw.text((x, y), text, fill="#333", font=font)
            y += line_h[lt]

        draw.rectangle([(0, 0), (label_w - 1, total_h - 1)], outline="#ccc", width=1)
        labels.append(img)

    if not labels:
        raise HTTPException(400, "No labels generated")

    # Layout: 3 columns
    cols = 3
    gap = 8
    rows_count = (len(labels) + cols - 1) // cols
    lw = labels[0].width
    lh = max(l.height for l in labels)
    page_w = cols * lw + (cols + 1) * gap
    page_h = rows_count * lh + (rows_count + 1) * gap

    page = Image.new("RGB", (page_w, page_h), "white")
    for idx, label in enumerate(labels):
        col = idx % cols
        row = idx // cols
        x = gap + col * (lw + gap)
        y = gap + row * (lh + gap)
        page.paste(label, (x, y))

    buf = io.BytesIO()
    page.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={
        "Content-Disposition": f"inline; filename=picking-{pl.picking_number}.png"
    })
