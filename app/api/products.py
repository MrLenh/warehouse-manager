from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.product import InventoryAdjust, ProductCreate, ProductOut, ProductUpdate
from app.services import product_service

router = APIRouter(prefix="/products", tags=["Products"])


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
