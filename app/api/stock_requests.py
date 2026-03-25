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
from app.services.qr_service import generate_box_labels_pdf, generate_stock_request_qr

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


@router.get("/{sr_id}/qrcode")
def get_stock_request_qrcode(sr_id: str, db: Session = Depends(get_db)):
    """Generate a QR code linking to the mobile receiving page."""
    sr = stock_request_service.get_stock_request(db, sr_id)
    if not sr:
        raise HTTPException(404, "Stock request not found")
    png_bytes = generate_stock_request_qr(sr.id, sr.request_number)
    return Response(content=png_bytes, media_type="image/png")


@router.post("/scan-box/{barcode}", response_model=BoxScanResult)
def scan_box_barcode(barcode: str, db: Session = Depends(get_db)):
    """Scan a box barcode to mark it as received. Returns box and item info."""
    result = stock_request_service.scan_box_barcode(db, barcode)
    return result


@router.get("/{sr_id}/print-checklist")
def print_checklist(sr_id: str, db: Session = Depends(get_db)):
    """Printable product checklist for stock request receiving with box barcodes."""
    from html import escape

    from fastapi.responses import HTMLResponse

    sr = stock_request_service.get_stock_request(db, sr_id)
    if not sr:
        raise HTTPException(404, "Stock request not found")

    # Build product rows with box barcodes
    product_rows = ""
    box_barcode_sections = ""
    total_qty = 0
    total_boxes = 0

    for idx, item in enumerate(sr.items):
        total_qty += item.quantity_requested
        total_boxes += item.box_count

        product_rows += f"""<tr>
            <td class="num">{idx + 1}</td>
            <td class="sku">{escape(item.sku)}</td>
            <td class="product">{escape(item.product_name)}</td>
            <td class="variant">{escape(item.variant_label or '—')}</td>
            <td class="qty">{item.quantity_requested}</td>
            <td class="boxes">{item.box_count}</td>
            <td class="cost">${item.unit_cost:.2f}</td>
            <td class="check"></td>
        </tr>"""

        # Box barcode section for this product
        if item.boxes:
            box_barcode_sections += f"""
            <div class="box-section">
                <div class="box-section-header">
                    <strong>{escape(item.sku)}</strong> — {escape(item.product_name)}
                    {(' (' + escape(item.variant_label) + ')') if item.variant_label else ''}
                    <span class="box-count">{len(item.boxes)} boxes</span>
                </div>
                <div class="box-grid">"""
            for box in sorted(item.boxes, key=lambda b: b.sequence):
                box_barcode_sections += f"""
                    <div class="box-card">
                        <div class="box-label">Box #{box.sequence}</div>
                        <svg class="barcode" data-barcode="{escape(box.barcode)}"></svg>
                        <div class="box-barcode-text">{escape(box.barcode)}</div>
                        <div class="box-sku">{escape(item.sku)}</div>
                        <div class="box-check">☐ Received</div>
                    </div>"""
            box_barcode_sections += """
                </div>
            </div>"""

    created = sr.created_at.strftime("%Y-%m-%d %H:%M") if sr.created_at else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Stock Request Checklist — {escape(sr.request_number)}</title>
<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.6/dist/JsBarcode.all.min.js"></script>
<style>
@page {{
    size: A4;
    margin: 10mm 10mm;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, 'Segoe UI', Arial, Helvetica, sans-serif;
    font-size: 13px;
    color: #111;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    padding: 16px;
}}

.header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2px solid #333;
    padding-bottom: 12px;
    margin-bottom: 16px;
}}
.header h1 {{
    font-size: 20px;
    font-weight: 700;
}}
.header .subtitle {{
    font-size: 13px;
    color: #666;
    margin-top: 2px;
}}
.header .meta {{
    text-align: right;
    font-size: 12px;
    color: #555;
    line-height: 1.6;
}}

.info-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
    gap: 8px;
    margin-bottom: 16px;
    padding: 10px;
    background: #f8f9fa;
    border-radius: 6px;
    border: 1px solid #e0e0e0;
}}
.info-item .label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #888;
    font-weight: 600;
}}
.info-item .value {{
    font-size: 13px;
    font-weight: 600;
    color: #222;
}}

h2 {{
    font-size: 15px;
    margin: 20px 0 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid #ddd;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 16px;
    font-size: 12px;
}}
th {{
    background: #f0f0f0;
    font-weight: 600;
    text-align: left;
    padding: 6px 8px;
    border: 1px solid #ddd;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}}
td {{
    padding: 5px 8px;
    border: 1px solid #ddd;
    vertical-align: middle;
}}
tr:nth-child(even) {{
    background: #fafafa;
}}
.num {{ width: 30px; text-align: center; color: #999; }}
.sku {{ font-weight: 600; font-family: monospace; font-size: 12px; }}
.qty, .boxes {{ text-align: center; font-weight: 700; }}
.cost {{ text-align: right; }}
.check {{
    width: 50px;
    text-align: center;
    font-size: 18px;
}}
.check::after {{
    content: '☐';
}}

.totals-row {{
    font-weight: 700;
    background: #e8f4fd !important;
}}

/* Box barcode sections */
.box-section {{
    page-break-inside: avoid;
    margin-bottom: 16px;
}}
.box-section-header {{
    background: #f0f0f0;
    padding: 6px 10px;
    border-radius: 4px 4px 0 0;
    border: 1px solid #ddd;
    border-bottom: none;
    font-size: 12px;
}}
.box-section-header .box-count {{
    float: right;
    color: #666;
    font-weight: 400;
}}
.box-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0;
    border: 1px solid #ddd;
}}
.box-card {{
    padding: 8px;
    text-align: center;
    border-right: 1px solid #eee;
    border-bottom: 1px solid #eee;
    page-break-inside: avoid;
}}
.box-card:nth-child(3n) {{
    border-right: none;
}}
.box-label {{
    font-size: 10px;
    font-weight: 700;
    color: #666;
    text-transform: uppercase;
    margin-bottom: 2px;
}}
.barcode {{
    display: block;
    margin: 0 auto;
    max-width: 100%;
    height: 40px;
}}
.box-barcode-text {{
    font-family: monospace;
    font-size: 9px;
    color: #333;
    margin-top: 1px;
}}
.box-sku {{
    font-size: 9px;
    color: #888;
}}
.box-check {{
    font-size: 11px;
    margin-top: 2px;
    color: #555;
}}

.notes {{
    margin-top: 20px;
    padding: 12px;
    border: 1px dashed #ccc;
    border-radius: 6px;
    min-height: 60px;
}}
.notes-title {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #888;
    font-weight: 600;
    margin-bottom: 4px;
}}

.signature-area {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 40px;
    margin-top: 30px;
}}
.sig-block {{
    border-top: 1px solid #333;
    padding-top: 4px;
    font-size: 11px;
    color: #666;
}}

/* Print controls */
.print-bar {{
    position: fixed;
    top: 0; left: 0; right: 0;
    background: #333;
    color: #fff;
    padding: 10px 20px;
    display: flex;
    gap: 10px;
    align-items: center;
    z-index: 1000;
}}
.print-bar button {{
    padding: 6px 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    background: #667eea;
    color: #fff;
}}
.print-bar button:hover {{ background: #5a6fd6; }}
.print-bar span {{ font-size: 13px; }}
@media print {{
    .print-bar {{ display: none !important; }}
    body {{ padding: 0; }}
}}
</style>
</head>
<body>
<div class="print-bar">
    <button onclick="window.print()">Print Checklist</button>
    <span>Stock Request: {escape(sr.request_number)}</span>
</div>

<div class="header" style="margin-top:50px">
    <div>
        <h1>Stock Request Checklist</h1>
        <div class="subtitle">Receiving & Inspection Form</div>
    </div>
    <div class="meta">
        <div><strong>{escape(sr.request_number)}</strong></div>
        <div>Date: {created}</div>
        <div>Printed: <script>document.write(new Date().toLocaleString('en-US'))</script></div>
    </div>
</div>

<div class="info-grid">
    <div class="info-item"><div class="label">Supplier</div><div class="value">{escape(sr.supplier or '—')}</div></div>
    <div class="info-item"><div class="label">Ship From</div><div class="value">{escape(sr.ship_from or '—')}</div></div>
    <div class="info-item"><div class="label">Tracking</div><div class="value">{escape(sr.tracking_id or '—')}</div></div>
    <div class="info-item"><div class="label">Status</div><div class="value">{escape(sr.status.value if hasattr(sr.status, 'value') else str(sr.status))}</div></div>
</div>

<h2>Product Checklist ({len(sr.items)} SKUs, {total_qty} units, {total_boxes} boxes)</h2>
<table>
    <thead>
        <tr>
            <th>#</th>
            <th>SKU</th>
            <th>Product Name</th>
            <th>Variant</th>
            <th>Qty</th>
            <th>Boxes</th>
            <th>Unit Cost</th>
            <th>✓</th>
        </tr>
    </thead>
    <tbody>
        {product_rows}
        <tr class="totals-row">
            <td colspan="4" style="text-align:right">TOTAL</td>
            <td class="qty">{total_qty}</td>
            <td class="boxes">{total_boxes}</td>
            <td colspan="2"></td>
        </tr>
    </tbody>
</table>

{"<h2>Box Barcodes</h2>" + box_barcode_sections if box_barcode_sections else ""}

<div class="notes">
    <div class="notes-title">Notes</div>
    {escape(sr.notes) if sr.notes else ''}
</div>

<div class="signature-area">
    <div class="sig-block">Received by: _________________________ &nbsp; Date: ___________</div>
    <div class="sig-block">Inspected by: _________________________ &nbsp; Date: ___________</div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {{
    document.querySelectorAll('.barcode').forEach(function(svg) {{
        var code = svg.getAttribute('data-barcode');
        if (code) {{
            JsBarcode(svg, code, {{
                format: 'CODE128',
                width: 1.2,
                height: 35,
                displayValue: false,
                margin: 2,
            }});
        }}
    }});
}});
</script>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.get("/{sr_id}/print-box-labels")
def print_box_labels(sr_id: str, db: Session = Depends(get_db)):
    """Printable box barcode labels (sticker format) for sticking on boxes."""
    from html import escape

    from fastapi.responses import HTMLResponse

    sr = stock_request_service.get_stock_request(db, sr_id)
    if not sr:
        raise HTTPException(404, "Stock request not found")

    # Build label cards
    label_cards = ""
    total_boxes = 0
    for item in sr.items:
        if not item.boxes:
            continue
        for box in sorted(item.boxes, key=lambda b: b.sequence):
            total_boxes += 1
            label_cards += f"""
            <div class="label-card">
                <div class="label-header">{escape(sr.request_number)}</div>
                <div class="label-sku">{escape(item.sku)}</div>
                <div class="label-product">{escape(item.product_name)}{(' - ' + escape(item.variant_label)) if item.variant_label else ''}</div>
                <svg class="barcode" data-barcode="{escape(box.barcode)}"></svg>
                <div class="label-barcode-text">{escape(box.barcode)}</div>
                <div class="label-box-info">Box #{box.sequence} of {item.box_count} | Qty: {item.quantity_requested}</div>
            </div>"""

    if not label_cards:
        label_cards = '<p style="padding:40px;text-align:center;color:#999">No boxes found. Create stock request items with box_count &gt; 0.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Box Labels — {escape(sr.request_number)}</title>
<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.6/dist/JsBarcode.all.min.js"></script>
<style>
@page {{
    size: A4;
    margin: 8mm;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, 'Segoe UI', Arial, Helvetica, sans-serif;
    font-size: 12px;
    color: #111;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    padding: 16px;
}}

.print-bar {{
    position: fixed;
    top: 0; left: 0; right: 0;
    background: #333;
    color: #fff;
    padding: 10px 20px;
    display: flex;
    gap: 10px;
    align-items: center;
    z-index: 1000;
}}
.print-bar button {{
    padding: 6px 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    background: #667eea;
    color: #fff;
}}
.print-bar button:hover {{ background: #5a6fd6; }}
.print-bar span {{ font-size: 13px; }}

.labels-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-top: 50px;
}}

.label-card {{
    border: 2px dashed #aaa;
    border-radius: 6px;
    padding: 10px 8px;
    text-align: center;
    page-break-inside: avoid;
    min-height: 140px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}}
.label-header {{
    font-size: 8px;
    color: #999;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 2px;
}}
.label-sku {{
    font-size: 14px;
    font-weight: 700;
    font-family: monospace;
    margin-bottom: 1px;
}}
.label-product {{
    font-size: 10px;
    color: #555;
    margin-bottom: 4px;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.barcode {{
    display: block;
    margin: 0 auto;
    max-width: 100%;
    height: 45px;
}}
.label-barcode-text {{
    font-family: monospace;
    font-size: 9px;
    color: #333;
    margin-top: 1px;
}}
.label-box-info {{
    font-size: 9px;
    color: #888;
    margin-top: 3px;
}}

@media print {{
    .print-bar {{ display: none !important; }}
    body {{ padding: 0; }}
    .labels-grid {{ margin-top: 0; }}
    .label-card {{ border-color: #666; }}
}}
</style>
</head>
<body>
<div class="print-bar">
    <button onclick="window.print()">Print Box Labels</button>
    <span>{escape(sr.request_number)} — {total_boxes} box labels</span>
</div>

<div class="labels-grid">
    {label_cards}
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {{
    document.querySelectorAll('.barcode').forEach(function(svg) {{
        var code = svg.getAttribute('data-barcode');
        if (code) {{
            JsBarcode(svg, code, {{
                format: 'CODE128',
                width: 1.5,
                height: 40,
                displayValue: false,
                margin: 2,
            }});
        }}
    }});
}});
</script>
</body>
</html>"""

    return HTMLResponse(content=html)
