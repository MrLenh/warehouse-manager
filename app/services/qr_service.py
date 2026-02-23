import io
import json
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

# Label layout constants
QR_SIZE = 300
LABEL_WIDTH = 400
PADDING = 16


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
    variant_sku: str = "",
    variant_label: str = "",
    location: str = "",
    price: float = 0.0,
) -> bytes:
    """Generate a QR code label image with text info below. Returns PNG bytes."""
    # QR data - structured for scanning
    qr_data = f"SKU:{variant_sku or sku}|ID:{product_id}"
    if variant_sku:
        qr_data += f"|VARIANT:{variant_sku}"

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE), Image.NEAREST)

    # Build text lines
    font_big = _get_font(22)
    font_med = _get_font(16)
    font_sm = _get_font(13)

    lines = []
    display_sku = variant_sku or sku
    lines.append(("sku", display_sku))
    # Truncate name if too long
    display_name = name if len(name) <= 30 else name[:27] + "..."
    lines.append(("name", display_name))
    if variant_label:
        lines.append(("variant", variant_label))
    if location:
        lines.append(("location", f"Loc: {location}"))
    if price > 0:
        lines.append(("price", f"${price:.2f}"))

    # Calculate text block height
    line_height = {"sku": 28, "name": 22, "variant": 20, "location": 18, "price": 18}
    text_height = sum(line_height.get(t, 20) for t, _ in lines) + PADDING

    # Create final image
    total_height = QR_SIZE + text_height + PADDING * 2
    img = Image.new("RGB", (LABEL_WIDTH, total_height), "white")

    # Paste QR centered
    qr_x = (LABEL_WIDTH - QR_SIZE) // 2
    img.paste(qr_img, (qr_x, PADDING))

    # Draw text
    draw = ImageDraw.Draw(img)
    y = QR_SIZE + PADDING + 8

    for line_type, text in lines:
        if line_type == "sku":
            font = font_big
        elif line_type == "name":
            font = font_med
        else:
            font = font_sm

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (LABEL_WIDTH - tw) // 2
        color = "#333333" if line_type != "price" else "#667eea"
        draw.text((x, y), text, fill=color, font=font)
        y += line_height.get(line_type, 20)

    # Draw border
    draw.rectangle([(0, 0), (LABEL_WIDTH - 1, total_height - 1)], outline="#cccccc", width=1)

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
        variant_sku=variant.variant_sku,
        variant_label=variant_label,
        location=variant.location or product.location,
        price=price,
    )


def generate_bulk_qr_page(product, variants: list) -> bytes:
    """Generate a printable page with QR labels for product + all variants.
    Returns PNG bytes of a multi-label sheet.
    """
    labels = []

    # Product label (if no variants, or as header)
    product_bytes = generate_qr_label(
        sku=product.sku,
        name=product.name,
        product_id=product.id,
        location=product.location,
        price=product.price,
    )
    labels.append(Image.open(io.BytesIO(product_bytes)))

    # Variant labels
    for v in variants:
        v_bytes = generate_variant_qr(v, product)
        labels.append(Image.open(io.BytesIO(v_bytes)))

    if not labels:
        return product_bytes

    # Layout: 2 columns
    cols = 2
    rows_count = (len(labels) + cols - 1) // cols
    gap = 12

    label_w = labels[0].width
    label_h = max(l.height for l in labels)

    page_w = cols * label_w + (cols + 1) * gap
    page_h = rows_count * label_h + (rows_count + 1) * gap

    page = Image.new("RGB", (page_w, page_h), "white")

    for idx, label_img in enumerate(labels):
        col = idx % cols
        row = idx // cols
        x = gap + col * (label_w + gap)
        y = gap + row * (label_h + gap)
        page.paste(label_img, (x, y))

    buf = io.BytesIO()
    page.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
