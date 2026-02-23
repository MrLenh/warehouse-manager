import os

import qrcode
from sqlalchemy.orm import Session

from app.config import settings
from app.models.inventory_log import InventoryLog
from app.models.product import Product
from app.schemas.product import InventoryAdjust, ProductCreate, ProductUpdate


def _generate_qr_code(product: Product) -> str:
    os.makedirs(settings.QR_CODE_DIR, exist_ok=True)
    data = f"SKU:{product.sku}|ID:{product.id}|NAME:{product.name}"
    img = qrcode.make(data)
    path = os.path.join(settings.QR_CODE_DIR, f"{product.sku}.png")
    img.save(path)
    return path


def create_product(db: Session, data: ProductCreate) -> Product:
    product = Product(
        sku=data.sku,
        name=data.name,
        description=data.description,
        category=data.category,
        weight_oz=data.weight_oz,
        price=data.price,
        quantity=data.quantity,
        location=data.location,
    )
    db.add(product)
    db.flush()

    product.qr_code_path = _generate_qr_code(product)

    if data.quantity > 0:
        log = InventoryLog(
            product_id=product.id,
            change=data.quantity,
            reason="inbound",
            balance_after=data.quantity,
            note="Initial stock on product creation",
        )
        db.add(log)

    db.commit()
    db.refresh(product)
    return product


def get_product(db: Session, product_id: str) -> Product | None:
    return db.query(Product).filter(Product.id == product_id).first()


def get_product_by_sku(db: Session, sku: str) -> Product | None:
    return db.query(Product).filter(Product.sku == sku).first()


def list_products(db: Session, skip: int = 0, limit: int = 100, category: str | None = None) -> list[Product]:
    q = db.query(Product)
    if category:
        q = q.filter(Product.category == category)
    return q.offset(skip).limit(limit).all()


def update_product(db: Session, product_id: str, data: ProductUpdate) -> Product | None:
    product = get_product(db, product_id)
    if not product:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


def adjust_inventory(db: Session, product_id: str, data: InventoryAdjust) -> Product | None:
    product = get_product(db, product_id)
    if not product:
        return None
    new_qty = product.quantity + data.quantity
    if new_qty < 0:
        raise ValueError(f"Insufficient stock. Current: {product.quantity}, requested change: {data.quantity}")
    product.quantity = new_qty
    log = InventoryLog(
        product_id=product.id,
        change=data.quantity,
        reason=data.reason,
        balance_after=new_qty,
        note=data.note,
    )
    db.add(log)
    db.commit()
    db.refresh(product)
    return product


def get_inventory_logs(db: Session, product_id: str) -> list[InventoryLog]:
    return (
        db.query(InventoryLog)
        .filter(InventoryLog.product_id == product_id)
        .order_by(InventoryLog.created_at.desc())
        .all()
    )


def get_low_stock(db: Session, threshold: int = 5) -> list[Product]:
    return db.query(Product).filter(Product.quantity <= threshold).all()
