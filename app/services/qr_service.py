import io
import json
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

# Label layout constants — 5x7 inch at 300 DPI
DPI = 300
PAGE_W = int(5 * DPI)   # 1500
PAGE_H = int(7 * DPI)   # 2100
QR_SIZE = 800
LABEL_WIDTH = PAGE_W
PADDING = 80


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
    """Generate a QR code label image with text info below. Returns PNG bytes."""
    # QR data = URL to product detail page
    base = settings.BASE_URL.rstrip("/")
    qr_data = f"{base}/product/{product_id}"
    if variant_id:
        qr_data += f"?variant={variant_id}"

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE), Image.NEAREST)

    # Build text lines — sized for 5x7 inch print
    font_big = _get_font(56)
    font_med = _get_font(36)
    font_sm = _get_font(28)

    lines = []
    display_sku = variant_sku or sku
    lines.append(("sku", display_sku))
    display_name = name if len(name) <= 35 else name[:32] + "..."
    lines.append(("name", display_name))
    if variant_label:
        lines.append(("variant", variant_label))
    if location:
        lines.append(("location", f"Loc: {location}"))
    if price > 0:
        lines.append(("price", f"${price:.2f}"))

    # Calculate text block height
    line_height = {"sku": 70, "name": 50, "variant": 42, "location": 38, "price": 38}
    text_height = sum(line_height.get(t, 42) for t, _ in lines) + PADDING

    # Create 5x7 inch page
    img = Image.new("RGB", (PAGE_W, PAGE_H), "white")

    # Paste QR centered near top
    qr_x = (PAGE_W - QR_SIZE) // 2
    qr_y = PADDING + 20
    img.paste(qr_img, (qr_x, qr_y))

    # Draw text below QR
    draw = ImageDraw.Draw(img)
    y = qr_y + QR_SIZE + 40

    for line_type, text in lines:
        if line_type == "sku":
            font = font_big
        elif line_type == "name":
            font = font_med
        else:
            font = font_sm

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (PAGE_W - tw) // 2
        color = "#333333" if line_type != "price" else "#667eea"
        draw.text((x, y), text, fill=color, font=font)
        y += line_height.get(line_type, 42)

    # Draw border
    draw.rectangle([(20, 20), (PAGE_W - 21, PAGE_H - 21)], outline="#cccccc", width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
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
    """Generate a QR code label for an order (for picking/packing). Returns PNG bytes."""
    base = settings.BASE_URL.rstrip("/")
    qr_data = f"{base}/order/{order.id}"

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE), Image.NEAREST)

    font_big = _get_font(56)
    font_med = _get_font(36)
    font_sm = _get_font(28)

    lines = []
    lines.append(("sku", order.order_number))
    if order.order_name:
        display_name = order.order_name if len(order.order_name) <= 35 else order.order_name[:32] + "..."
        lines.append(("name", display_name))
    lines.append(("variant", order.customer_name))
    lines.append(("location", f"Items: {len(order.items)}"))
    lines.append(("price", order.status.upper() if isinstance(order.status, str) else order.status.value.upper()))

    line_height = {"sku": 70, "name": 50, "variant": 42, "location": 38, "price": 38}
    text_height = sum(line_height.get(t, 42) for t, _ in lines) + PADDING

    img = Image.new("RGB", (PAGE_W, PAGE_H), "white")

    qr_x = (PAGE_W - QR_SIZE) // 2
    qr_y = PADDING + 20
    img.paste(qr_img, (qr_x, qr_y))

    draw = ImageDraw.Draw(img)
    y = qr_y + QR_SIZE + 40

    for line_type, text in lines:
        if line_type == "sku":
            font = font_big
        elif line_type == "name":
            font = font_med
        else:
            font = font_sm

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (PAGE_W - tw) // 2
        color = "#333333" if line_type != "price" else "#667eea"
        draw.text((x, y), text, fill=color, font=font)
        y += line_height.get(line_type, 42)

    draw.rectangle([(20, 20), (PAGE_W - 21, PAGE_H - 21)], outline="#cccccc", width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def generate_bulk_qr_page(product, variants: list) -> bytes:
    """Generate a printable PDF with QR labels (5x7 inch pages, one per page).
    Returns PDF bytes.
    """
    pages = []

    # Product label
    product_bytes = generate_qr_label(
        sku=product.sku,
        name=product.name,
        product_id=product.id,
        location=product.location,
        price=product.price,
    )
    pages.append(Image.open(io.BytesIO(product_bytes)))

    # Variant labels
    for v in variants:
        v_bytes = generate_variant_qr(v, product)
        pages.append(Image.open(io.BytesIO(v_bytes)))

    if not pages:
        return product_bytes

    # Single label → return PNG
    if len(pages) == 1:
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG")
        buf.seek(0)
        return buf.getvalue()

    # Multiple labels → return PDF (one label per 5x7 page)
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=DPI)
    buf.seek(0)
    return buf.getvalue()
