import csv
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
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

router = APIRouter(prefix="/products", tags=["Products"])

CSV_COLUMNS = ["sku", "name", "description", "category", "weight_oz", "length_in", "width_in", "height_in", "price", "quantity", "location"]


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
    writer.writerow(CSV_COLUMNS)
    writer.writerow(["SP-001", "San pham mau", "Mo ta", "Dien tu", "16", "10", "8", "6", "29.99", "100", "A-01-01"])
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
    errors = []

    for row_num, row in enumerate(reader, start=2):
        sku = (row.get("sku") or "").strip()
        if not sku:
            errors.append({"row": row_num, "error": "SKU is required"})
            continue

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

    return {"created": created, "updated": updated, "errors": errors}


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


@router.get("/{product_id}/qrcode")
def get_qrcode(product_id: str, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not product.qr_code_path:
        raise HTTPException(404, "QR code not generated")
    return FileResponse(product.qr_code_path, media_type="image/png")


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
