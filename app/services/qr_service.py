import io
import json
import os

import barcode
import qrcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

# Label layout constants — 2x1 inch at 600 DPI for crisp thermal printing
DPI = 600
SCALE = 2  # internal render scale vs original 300 DPI design
LABEL_W = int(2 * DPI)   # 1200
LABEL_H = int(1 * DPI)   # 600
PADDING = 20


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try system fonts, fallback to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _draw_label_2x1(
    barcode_data: str,
    lines: list[tuple[str, str, str]],
    show_border: bool = False,
) -> Image.Image:
    """Create a 2x1 inch label: text on top, Code128 barcode on bottom.

    Args:
        barcode_data: data to encode in barcode (Code128)
        lines: list of (font_size, text, color) tuples
        show_border: whether to draw a border around the label
    Returns:
        PIL Image
    """
    # Create label
    img = Image.new("RGB", (LABEL_W, LABEL_H), "white")
    draw = ImageDraw.Draw(img)
    text_area_w = LABEL_W - 2 * PADDING

    # Draw text lines at the top
    y = PADDING
    for font_size_str, text, color in lines:
        sz = int(font_size_str) * SCALE
        font = _get_font(sz)
        # Truncate if too wide
        while text and draw.textbbox((0, 0), text, font=font)[2] > text_area_w and len(text) > 3:
            text = text[:-4] + "..."
        draw.text((PADDING, y), text, fill="black", font=font)
        line_h = sz + max(6 * SCALE, sz // 4)
        y += line_h

    # Generate barcode (Code128) at label DPI for pixel-perfect bars
    code = barcode.get('code128', barcode_data, writer=ImageWriter())
    barcode_buf = io.BytesIO()
    code.write(barcode_buf, options={
        'write_text': False,
        'module_height': 10,       # mm — tall bars for reliable scanning
        'module_width': 0.24,      # mm — ~5.7px per module at 600 DPI
        'quiet_zone': 2,           # mm — proper quiet zones for scanner
        'dpi': DPI,                # render at label DPI (600)
    })
    barcode_buf.seek(0)
    barcode_img = Image.open(barcode_buf).convert("RGB")

    # Place barcode in remaining space at bottom
    barcode_top = y + PADDING // 2
    available_h = LABEL_H - barcode_top - PADDING
    if available_h < 80:
        available_h = 80
        barcode_top = LABEL_H - available_h - PADDING

    # Preserve original bar widths — only stretch height, center horizontally
    barcode_target_w = LABEL_W - 2 * PADDING
    orig_w = barcode_img.width
    if orig_w > barcode_target_w:
        # Too wide — scale down proportionally
        barcode_img = barcode_img.resize((barcode_target_w, available_h), Image.NEAREST)
        x_offset = PADDING
    else:
        # Fits — stretch height only, center horizontally (preserves bar width ratios)
        barcode_img = barcode_img.resize((orig_w, available_h), Image.NEAREST)
        x_offset = PADDING + (barcode_target_w - orig_w) // 2
    img.paste(barcode_img, (x_offset, barcode_top))

    # Border
    if show_border:
        draw.rectangle([(0, 0), (LABEL_W - 1, LABEL_H - 1)], outline="#cccccc", width=SCALE)

    # Convert to 1-bit monochrome — eliminates anti-aliasing blur on thermal printers
    img = img.convert("1", dither=Image.Dither.NONE).convert("RGB")

    return img


def generate_qr_label(
    sku: str,
    name: str,
    product_id: str,
    variant_id: str = "",
    variant_sku: str = "",
    variant_label: str = "",
    location: str = "",
    price: float = 0.0,
) -> bytes:
    """Generate a 2x1 inch barcode label. Text on top, barcode on bottom. Returns PNG bytes."""
    display_sku = variant_sku or sku
    barcode_data = display_sku

    lines = [
        ("34", display_sku, "#000000"),
        ("24", name, "#000000"),
    ]
    if variant_label:
        lines.append(("20", variant_label, "#333333"))
    if location:
        lines.append(("18", f"Loc: {location}", "#333333"))
    if price > 0:
        lines.append(("20", f"${price:.2f}", "#000000"))

    img = _draw_label_2x1(barcode_data, lines)

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(DPI, DPI))
    buf.seek(0)
    return buf.getvalue()


def generate_product_qr(product) -> str:
    """Generate and save barcode for a product. Returns file path."""
    os.makedirs(settings.QR_CODE_DIR, exist_ok=True)
    img_bytes = generate_qr_label(
        sku=product.sku,
        name=product.name,
        product_id=product.id,
        location=product.location,
        price=product.price,
    )
    path = os.path.join(settings.QR_CODE_DIR, f"{product.sku}.png")
    with open(path, "wb") as f:
        f.write(img_bytes)
    return path


def generate_variant_qr(variant, product) -> bytes:
    """Generate barcode label for a variant. Returns PNG bytes."""
    attrs = json.loads(variant.attributes) if isinstance(variant.attributes, str) else (variant.attributes or {})
    variant_label = " / ".join(attrs.values()) if attrs else ""
    price = variant.price_override if variant.price_override > 0 else product.price

    return generate_qr_label(
        sku=product.sku,
        name=product.name,
        product_id=product.id,
        variant_id=variant.id,
        variant_sku=variant.variant_sku,
        variant_label=variant_label,
        location=variant.location or product.location,
        price=price,
    )


def generate_picking_list_qr(picking_list, order_count: int = 0, item_count: int = 0) -> bytes:
    """Generate a 2x1 inch barcode label for a picking list. Returns PNG bytes."""
    barcode_data = picking_list.picking_number

    lines = [
        ("34", picking_list.picking_number, "#000000"),
        ("24", f"{order_count} orders, {item_count} items", "#000000"),
        ("20", picking_list.status.upper() if isinstance(picking_list.status, str) else picking_list.status.value.upper(), "#333333"),
    ]

    img = _draw_label_2x1(barcode_data, lines)

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(DPI, DPI))
    buf.seek(0)
    return buf.getvalue()


def generate_order_qr(order) -> bytes:
    """Generate a 2x1 inch barcode label for an order. Returns PNG bytes."""
    barcode_data = order.order_number

    lines = [
        ("34", order.order_number, "#000000"),
    ]
    if order.order_name:
        lines.append(("24", order.order_name, "#000000"))
    lines.append(("20", order.customer_name, "#333333"))
    lines.append(("18", f"Items: {len(order.items)}", "#333333"))
    status_str = order.status.upper() if isinstance(order.status, str) else order.status.value.upper()
    lines.append(("18", status_str, "#333333"))

    img = _draw_label_2x1(barcode_data, lines)

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(DPI, DPI))
    buf.seek(0)
    return buf.getvalue()


def generate_box_barcode_label(barcode_data: str, sku: str, product_name: str, variant_label: str, box_seq: int, box_total: int) -> Image.Image:
    """Generate a 2x1 inch barcode label for a stock request box."""
    lines = [
        ("30", barcode_data, "#000000"),
        ("22", f"{sku} - {product_name}", "#000000"),
    ]
    if variant_label:
        lines.append(("18", variant_label, "#333333"))
    lines.append(("18", f"Box {box_seq}/{box_total}", "#333333"))

    return _draw_label_2x1(barcode_data, lines)


def generate_box_labels_pdf(boxes_info: list[dict]) -> bytes:
    """Generate a PDF with barcode labels for all boxes. Each box gets one label page.

    boxes_info: list of dicts with keys: barcode, sku, product_name, variant_label, sequence, box_total
    Returns PDF bytes (or PNG if single label).
    """
    pages = []
    for info in boxes_info:
        img = generate_box_barcode_label(
            barcode_data=info["barcode"],
            sku=info["sku"],
            product_name=info["product_name"],
            variant_label=info.get("variant_label", ""),
            box_seq=info["sequence"],
            box_total=info["box_total"],
        )
        pages.append(img)

    if not pages:
        return b""

    if len(pages) == 1:
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG", dpi=(DPI, DPI))
        buf.seek(0)
        return buf.getvalue()

    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=DPI)
    buf.seek(0)
    return buf.getvalue()


def generate_stock_request_qr(sr_id: str, request_number: str) -> bytes:
    """Generate a QR code image encoding the mobile receiving URL. Returns PNG bytes."""
    base = settings.BASE_URL.rstrip("/")
    url = f"{base}/receiving/{sr_id}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Add label text below QR code
    font = _get_font(28)
    label = request_number
    text_bbox = font.getbbox(label)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    qr_w, qr_h = img.size
    canvas = Image.new("RGB", (qr_w, qr_h + text_h + 16), "white")
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text(((qr_w - text_w) // 2, qr_h + 4), label, fill="black", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def generate_bulk_qr_page(product, variants: list) -> bytes:
    """Generate a printable PDF with 2x1 inch barcode labels, one per page.
    Returns PDF bytes (or PNG if single label).
    """
    pages = []

    product_bytes = generate_qr_label(
        sku=product.sku,
        name=product.name,
        product_id=product.id,
        location=product.location,
        price=product.price,
    )
    pages.append(Image.open(io.BytesIO(product_bytes)))

    for v in variants:
        v_bytes = generate_variant_qr(v, product)
        pages.append(Image.open(io.BytesIO(v_bytes)))

    if not pages:
        return product_bytes

    if len(pages) == 1:
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG", dpi=(DPI, DPI))
        buf.seek(0)
        return buf.getvalue()

    # Multiple labels → PDF
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=DPI)
    buf.seek(0)
    return buf.getvalue()
