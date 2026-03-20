from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock_request import StockRequestStatus
from app.schemas.stock_request import (
    BoxScanResult,
    StockRequestCreate,
    StockRequestOut,
    StockRequestReceive,
    StockRequestTrackingUpdate,
)
from app.services import stock_request_service
from app.services.qr_service import generate_box_labels_pdf

router = APIRouter(prefix="/stock-requests", tags=["Stock Requests"])


@router.post("", response_model=StockRequestOut, status_code=201)
def create_stock_request(data: StockRequestCreate, db: Session = Depends(get_db)):
    try:
        return stock_request_service.create_stock_request(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("", response_model=list[StockRequestOut])
def list_stock_requests(
    skip: int = 0,
    limit: int = 100,
    status: StockRequestStatus | None = None,
    db: Session = Depends(get_db),
):
    return stock_request_service.list_stock_requests(db, skip=skip, limit=limit, status=status)


@router.get("/{sr_id}", response_model=StockRequestOut)
def get_stock_request(sr_id: str, db: Session = Depends(get_db)):
    sr = stock_request_service.get_stock_request(db, sr_id)
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/approve", response_model=StockRequestOut)
def approve_stock_request(sr_id: str, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.approve_stock_request(db, sr_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/receive", response_model=StockRequestOut)
def receive_items(sr_id: str, data: StockRequestReceive, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.receive_items(db, sr_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/complete", response_model=StockRequestOut)
def complete_stock_request(sr_id: str, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.complete_stock_request(db, sr_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/cancel", response_model=StockRequestOut)
def cancel_stock_request(sr_id: str, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.cancel_stock_request(db, sr_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.patch("/{sr_id}/tracking", response_model=StockRequestOut)
def update_tracking(sr_id: str, data: StockRequestTrackingUpdate, db: Session = Depends(get_db)):
    """Update tracking ID and carrier for a stock request shipment."""
    sr = stock_request_service.update_tracking(db, sr_id, data)
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.get("/{sr_id}/checklist", response_class=HTMLResponse)
def print_checklist(sr_id: str, db: Session = Depends(get_db)):
    """Generate a printable product check list for a stock request."""
    sr = stock_request_service.get_stock_request(db, sr_id)
    if not sr:
        raise HTTPException(404, "Stock request not found")

    rows = ""
    for idx, item in enumerate(sr.items, 1):
        variant_info = f" ({item.variant_label})" if item.variant_label else ""
        boxes_info = f"{item.box_count} box(es)" if item.box_count > 0 else "-"
        rows += f"""<tr>
            <td style="text-align:center;width:40px"><input type="checkbox"></td>
            <td style="text-align:center">{idx}</td>
            <td>{item.sku}</td>
            <td>{item.product_name}{variant_info}</td>
            <td style="text-align:center">{item.quantity_requested}</td>
            <td style="text-align:center;width:100px"></td>
            <td style="text-align:right">${item.unit_cost:.2f}</td>
            <td style="text-align:center">{boxes_info}</td>
            <td style="width:120px"></td>
        </tr>"""

    total_qty = sum(i.quantity_requested for i in sr.items)
    total_boxes = sum(i.box_count for i in sr.items)
    total_cost = sum(i.quantity_requested * i.unit_cost for i in sr.items)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Check List - {sr.request_number}</title>
<style>
  @media print {{ @page {{ margin: 15mm; }} }}
  body {{ font-family: Arial, sans-serif; font-size: 13px; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 12px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ border: 1px solid #ccc; padding: 8px 10px; font-size: 12px; }}
  th {{ background: #f5f5f5; font-weight: 600; text-align: left; }}
  .footer {{ margin-top: 30px; display: flex; gap: 40px; }}
  .footer .sig {{ border-top: 1px solid #333; width: 200px; padding-top: 4px; font-size: 12px; text-align: center; }}
  .totals {{ font-weight: 600; background: #fafafa; }}
  @media screen {{ .no-print {{ display: block; text-align: center; margin-bottom: 16px; }}
    .no-print button {{ padding: 8px 24px; font-size: 14px; cursor: pointer; }} }}
  @media print {{ .no-print {{ display: none; }} }}
</style></head><body>
<div class="no-print"><button onclick="window.print()">Print</button></div>
<h1>Receiving Check List</h1>
<div class="meta">
  <strong>Request:</strong> {sr.request_number} &nbsp;|&nbsp;
  <strong>Supplier:</strong> {sr.supplier or '-'} &nbsp;|&nbsp;
  <strong>Ship From:</strong> {sr.ship_from or '-'} &nbsp;|&nbsp;
  <strong>Status:</strong> {sr.status}
</div>
{f'<div class="meta"><strong>Tracking:</strong> {sr.tracking_id} ({sr.carrier})</div>' if sr.tracking_id else ''}
{f'<div class="meta"><strong>Notes:</strong> {sr.notes}</div>' if sr.notes else ''}
<table>
  <thead><tr>
    <th style="text-align:center;width:40px">&#10003;</th>
    <th style="text-align:center;width:30px">#</th>
    <th>SKU</th><th>Product</th>
    <th style="text-align:center">Requested</th>
    <th style="text-align:center;width:100px">Actual Qty</th>
    <th style="text-align:right">Unit Cost</th>
    <th style="text-align:center">Boxes</th>
    <th style="width:120px">Notes</th>
  </tr></thead>
  <tbody>{rows}</tbody>
  <tfoot><tr class="totals">
    <td colspan="4" style="text-align:right">Totals</td>
    <td style="text-align:center">{total_qty}</td>
    <td></td>
    <td style="text-align:right">${total_cost:.2f}</td>
    <td style="text-align:center">{total_boxes}</td>
    <td></td>
  </tr></tfoot>
</table>
<div class="footer">
  <div><div class="sig">Received By</div></div>
  <div><div class="sig">Date</div></div>
  <div><div class="sig">Verified By</div></div>
</div>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/{sr_id}/box-labels")
def print_box_labels(sr_id: str, db: Session = Depends(get_db)):
    """Generate printable barcode labels for all boxes in a stock request."""
    sr = stock_request_service.get_stock_request(db, sr_id)
    if not sr:
        raise HTTPException(404, "Stock request not found")

    boxes_info = []
    for item in sr.items:
        for box in item.boxes:
            boxes_info.append({
                "barcode": box.barcode,
                "sku": item.sku,
                "product_name": item.product_name,
                "variant_label": item.variant_label,
                "sequence": box.sequence,
                "box_total": item.box_count,
            })

    if not boxes_info:
        raise HTTPException(404, "No boxes found for this stock request")

    pdf_bytes = generate_box_labels_pdf(boxes_info)

    if len(boxes_info) == 1:
        return Response(content=pdf_bytes, media_type="image/png",
                        headers={"Content-Disposition": f"inline; filename=box-labels-{sr.request_number}.png"})
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=box-labels-{sr.request_number}.pdf"})


@router.post("/scan-box/{barcode}", response_model=BoxScanResult)
def scan_box_barcode(barcode: str, db: Session = Depends(get_db)):
    """Scan a box barcode to mark it as received. Returns box and item info."""
    result = stock_request_service.scan_box_barcode(db, barcode)
    return result
