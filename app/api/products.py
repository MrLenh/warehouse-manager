import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.product import (
    InventoryAdjust,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    VariantCreate,
    VariantInventoryAdjust,
    VariantOut,
    VariantUpdate,
)
from app.services import product_service
from app.services.qr_service import generate_bulk_qr_page, generate_qr_label, generate_variant_qr

router = APIRouter(prefix="/products", tags=["Products"])

CSV_COLUMNS = [
    "sku", "name", "description", "category", "weight_oz", "length_in", "width_in", "height_in",
    "price", "quantity", "location", "variant_sku", "attributes", "price_override",
    "weight_oz_override", "length_in_override", "width_in_override", "height_in_override",
]


@router.post("", response_model=ProductOut, status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    existing = product_service.get_product_by_sku(db, data.sku)
    if existing:
        raise HTTPException(400, f"Product with SKU {data.sku} already exists")
    return product_service.create_product(db, data)


@router.get("", response_model=list[ProductOut])
def list_products(skip: int = 0, limit: int = 100, category: str | None = None, db: Session = Depends(get_db)):
    return product_service.list_products(db, skip=skip, limit=limit, category=category)


@router.get("/low-stock", response_model=list[ProductOut])
def low_stock(threshold: int = 5, db: Session = Depends(get_db)):
    return product_service.get_low_stock(db, threshold)


@router.get("/import-template")
def download_import_template():
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Header
    writer.writerow(CSV_COLUMNS)
    # Product row (no variant)
    writer.writerow(["SP-001", "San pham A", "Mo ta SP A", "Dien tu", "16", "10", "8", "6", "29.99", "100", "A-01-01", "", "", "", "", "", "", ""])
    # Product with variants - parent row
    writer.writerow(["SP-002", "San pham B (co variant)", "Mo ta SP B", "Thoi trang", "12", "8", "6", "4", "49.99", "0", "B-01-01", "", "", "", "", "", "", ""])
    # Variant rows for SP-002
    writer.writerow(["SP-002", "", "", "", "", "", "", "", "", "30", "B-01-01", "SP-002-RED-M", '{"color":"Red","size":"M"}', "51.99", "14", "9", "7", "5"])
    writer.writerow(["SP-002", "", "", "", "", "", "", "", "", "20", "B-01-02", "SP-002-RED-L", '{"color":"Red","size":"L"}', "53.99", "16", "10", "8", "5"])
    writer.writerow(["SP-002", "", "", "", "", "", "", "", "", "15", "B-02-01", "SP-002-BLUE-M", '{"color":"Blue","size":"M"}', "0", "0", "0", "0", "0"])
    # Another simple product
    writer.writerow(["SP-003", "San pham C", "", "Gia dung", "8", "5", "5", "3", "15.00", "200", "C-01-01", "", "", "", "", "", "", ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=product_import_template.csv"},
    )


@router.post("/import")
def import_products(file: UploadFile, db: Session = Depends(get_db)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    created = 0
    updated = 0
    variants_created = 0
    variants_updated = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):
        sku = (row.get("sku") or "").strip()
        variant_sku = (row.get("variant_sku") or "").strip()

        if not sku:
            errors.append({"row": row_num, "error": "SKU is required"})
            continue

        # --- Variant row ---
        if variant_sku:
            try:
                parent = product_service.get_product_by_sku(db, sku)
                if not parent:
                    errors.append({"row": row_num, "sku": sku, "error": f"Parent product {sku} not found"})
                    continue

                attrs_raw = (row.get("attributes") or "").strip()
                attrs = {}
                if attrs_raw:
                    attrs = json.loads(attrs_raw)

                existing_variant = product_service.get_variant_by_sku(db, variant_sku)
                if existing_variant:
                    update_data = VariantUpdate(
                        attributes=attrs if attrs else None,
                        price_override=float(row.get("price_override") or 0) or None,
                        weight_oz_override=float(row.get("weight_oz_override") or 0) or None,
                        length_in_override=float(row.get("length_in_override") or 0) or None,
                        width_in_override=float(row.get("width_in_override") or 0) or None,
                        height_in_override=float(row.get("height_in_override") or 0) or None,
                        location=(row.get("location") or "").strip() or None,
                    )
                    product_service.update_variant(db, existing_variant.id, update_data)
                    variants_updated += 1
                else:
                    v_data = VariantCreate(
                        variant_sku=variant_sku,
                        attributes=attrs,
                        price_override=float(row.get("price_override") or 0),
                        weight_oz_override=float(row.get("weight_oz_override") or 0),
                        length_in_override=float(row.get("length_in_override") or 0),
                        width_in_override=float(row.get("width_in_override") or 0),
                        height_in_override=float(row.get("height_in_override") or 0),
                        quantity=int(row.get("quantity") or 0),
                        location=(row.get("location") or "").strip(),
                    )
                    product_service.create_variant(db, parent.id, v_data)
                    variants_created += 1
            except (ValueError, TypeError) as e:
                errors.append({"row": row_num, "sku": sku, "variant_sku": variant_sku, "error": str(e)})
            continue

        # --- Product row ---
        try:
            data = ProductCreate(
                sku=sku,
                name=(row.get("name") or "").strip(),
                description=(row.get("description") or "").strip(),
                category=(row.get("category") or "").strip(),
                weight_oz=float(row.get("weight_oz") or 0),
                length_in=float(row.get("length_in") or 0),
                width_in=float(row.get("width_in") or 0),
                height_in=float(row.get("height_in") or 0),
                price=float(row.get("price") or 0),
                quantity=int(row.get("quantity") or 0),
                location=(row.get("location") or "").strip(),
            )
        except (ValueError, TypeError) as e:
            errors.append({"row": row_num, "sku": sku, "error": str(e)})
            continue

        existing = product_service.get_product_by_sku(db, sku)
        if existing:
            update_data = ProductUpdate(
                name=data.name or None,
                description=data.description or None,
                category=data.category or None,
                weight_oz=data.weight_oz or None,
                length_in=data.length_in or None,
                width_in=data.width_in or None,
                height_in=data.height_in or None,
                price=data.price or None,
                location=data.location or None,
            )
            product_service.update_product(db, existing.id, update_data)
            updated += 1
        else:
            product_service.create_product(db, data)
            created += 1

    return {"created": created, "updated": updated, "variants_created": variants_created, "variants_updated": variants_updated, "errors": errors}


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: str, data: ProductUpdate, db: Session = Depends(get_db)):
    product = product_service.update_product(db, product_id, data)
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@router.post("/{product_id}/inventory", response_model=ProductOut)
def adjust_inventory(product_id: str, data: InventoryAdjust, db: Session = Depends(get_db)):
    try:
        product = product_service.adjust_inventory(db, product_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@router.get("/{product_id}/inventory-logs")
def inventory_logs(product_id: str, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    logs = product_service.get_inventory_logs(db, product_id)
    return [
        {
            "id": log.id,
            "change": log.change,
            "reason": log.reason,
            "reference_id": log.reference_id,
            "balance_after": log.balance_after,
            "note": log.note,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.post("/{product_id}/generate-qr")
def generate_qr(product_id: str, db: Session = Depends(get_db)):
    """Generate and save QR code for a product that doesn't have one."""
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    from app.services.qr_service import generate_product_qr
    path = generate_product_qr(product)
    product.qr_code_path = path
    db.commit()
    db.refresh(product)
    return {"qr_code_path": path}


@router.get("/{product_id}/qrcode")
def get_qrcode(product_id: str, db: Session = Depends(get_db)):
    """Get QR code label for a product (regenerated on-the-fly with styled label)."""
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    img_bytes = generate_qr_label(
        sku=product.sku,
        name=product.name,
        product_id=product.id,
        location=product.location,
        price=product.price,
    )
    return Response(content=img_bytes, media_type="image/png")


@router.get("/{product_id}/qrcode/bulk")
def get_bulk_qrcode(product_id: str, db: Session = Depends(get_db)):
    """Get a printable sheet with QR labels for product + all variants."""
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    img_bytes = generate_bulk_qr_page(product, product.variants)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/variants/{variant_id}/qrcode")
def get_variant_qrcode(variant_id: str, db: Session = Depends(get_db)):
    """Get QR code label for a specific variant."""
    variant = product_service.get_variant(db, variant_id)
    if not variant:
        raise HTTPException(404, "Variant not found")
    product = product_service.get_product(db, variant.product_id)
    img_bytes = generate_variant_qr(variant, product)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/qr/lookup")
def qr_lookup(sku: str = Query(..., description="SKU or variant_sku from QR scan"), db: Session = Depends(get_db)):
    """Lookup product/variant by SKU (for QR scan)."""
    # Try variant first
    variant = product_service.get_variant_by_sku(db, sku)
    if variant:
        product = product_service.get_product(db, variant.product_id)
        return {
            "type": "variant",
            "product_id": product.id,
            "variant_id": variant.id,
            "sku": product.sku,
            "variant_sku": variant.variant_sku,
            "name": product.name,
            "price": variant.effective_price,
            "quantity": variant.quantity,
            "location": variant.location or product.location,
        }
    # Try product
    product = product_service.get_product_by_sku(db, sku)
    if product:
        return {
            "type": "product",
            "product_id": product.id,
            "variant_id": "",
            "sku": product.sku,
            "variant_sku": "",
            "name": product.name,
            "price": product.price,
            "quantity": product.quantity,
            "location": product.location,
        }
    raise HTTPException(404, f"No product or variant found with SKU: {sku}")


# --- Variant endpoints ---

@router.post("/{product_id}/variants", response_model=VariantOut, status_code=201)
def create_variant(product_id: str, data: VariantCreate, db: Session = Depends(get_db)):
    try:
        variant = product_service.create_variant(db, product_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not variant:
        raise HTTPException(404, "Product not found")
    return variant


@router.get("/{product_id}/variants", response_model=list[VariantOut])
def list_variants(product_id: str, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product.variants


@router.patch("/variants/{variant_id}", response_model=VariantOut)
def update_variant(variant_id: str, data: VariantUpdate, db: Session = Depends(get_db)):
    variant = product_service.update_variant(db, variant_id, data)
    if not variant:
        raise HTTPException(404, "Variant not found")
    return variant


@router.delete("/variants/{variant_id}", status_code=204)
def delete_variant(variant_id: str, db: Session = Depends(get_db)):
    if not product_service.delete_variant(db, variant_id):
        raise HTTPException(404, "Variant not found")


@router.post("/variants/{variant_id}/inventory", response_model=VariantOut)
def adjust_variant_inventory(variant_id: str, data: VariantInventoryAdjust, db: Session = Depends(get_db)):
    try:
        variant = product_service.adjust_variant_inventory(db, variant_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not variant:
        raise HTTPException(404, "Variant not found")
    return variant
