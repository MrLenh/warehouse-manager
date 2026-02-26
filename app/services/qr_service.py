import io
import json
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

# Label layout constants — 2x1 inch at 300 DPI
DPI = 300
LABEL_W = int(2 * DPI)   # 600
LABEL_H = int(1 * DPI)   # 300
QR_SIZE = LABEL_H - 20   # 280, nearly full height with small margin
PADDING = 10


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


def _draw_label_2x1(qr_data: str, lines: list[tuple[str, str, str]]) -> Image.Image:
    """Create a 2x1 inch label: QR on left, text info on right.

    Args:
        qr_data: data to encode in QR code
        lines: list of (font_size, text, color) tuples
    Returns:
        PIL Image
    """
    # Generate QR code
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE), Image.NEAREST)

    # Create label
    img = Image.new("RGB", (LABEL_W, LABEL_H), "white")
    draw = ImageDraw.Draw(img)

    # QR on left, vertically centered
    qr_x = PADDING
    qr_y = (LABEL_H - QR_SIZE) // 2
    img.paste(qr_img, (qr_x, qr_y))

    # Text on right side
    text_x = PADDING + QR_SIZE + PADDING
    text_area_w = LABEL_W - text_x - PADDING

    # Calculate total text height to vertically center
    total_text_h = 0
    rendered_lines = []
    for font_size_str, text, color in lines:
        sz = int(font_size_str)
        font = _get_font(sz)
        # Truncate if too wide
        while text and draw.textbbox((0, 0), text, font=font)[2] > text_area_w and len(text) > 3:
            text = text[:-4] + "..."
        line_h = sz + max(6, sz // 4)
        rendered_lines.append((font, text, color, line_h))
        total_text_h += line_h

    y = max(PADDING, (LABEL_H - total_text_h) // 2)

    for font, text, color, line_h in rendered_lines:
        draw.text((text_x, y), text, fill=color, font=font)
        y += line_h

    # Border
    draw.rectangle([(0, 0), (LABEL_W - 1, LABEL_H - 1)], outline="#cccccc", width=1)

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
    """Generate a 2x1 inch QR code label. QR left, info right. Returns PNG bytes."""
    base = settings.BASE_URL.rstrip("/")
    qr_data = f"{base}/product/{product_id}"
    if variant_id:
        qr_data += f"?variant={variant_id}"

    display_sku = variant_sku or sku
    lines = [
        ("38", display_sku, "#000000"),
        ("28", name, "#333333"),
    ]
    if variant_label:
        lines.append(("22", variant_label, "#555555"))
    if location:
        lines.append(("20", f"Loc: {location}", "#888888"))
    if price > 0:
        lines.append(("24", f"${price:.2f}", "#667eea"))

    img = _draw_label_2x1(qr_data, lines)

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(DPI, DPI))
    buf.seek(0)
    return buf.getvalue()


def generate_product_qr(product) -> str:
    """Generate and save QR code for a product. Returns file path."""
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
    """Generate QR label for a variant. Returns PNG bytes."""
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


def generate_order_qr(order) -> bytes:
    """Generate a 2x1 inch QR label for an order. Returns PNG bytes."""
    base = settings.BASE_URL.rstrip("/")
    qr_data = f"{base}/order/{order.id}"

    lines = [
        ("40", order.order_number, "#000000"),
    ]
    if order.order_name:
        lines.append(("28", order.order_name, "#333333"))
    lines.append(("24", order.customer_name, "#555555"))
    lines.append(("22", f"Items: {len(order.items)}", "#888888"))
    status_str = order.status.upper() if isinstance(order.status, str) else order.status.value.upper()
    lines.append(("22", status_str, "#667eea"))

    img = _draw_label_2x1(qr_data, lines)

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(DPI, DPI))
    buf.seek(0)
    return buf.getvalue()


def generate_bulk_qr_page(product, variants: list) -> bytes:
    """Generate a printable PDF with 2x1 inch QR labels, one per page.
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
