import json

from sqlalchemy.orm import Session

from app.models.inventory_log import InventoryLog
from app.models.product import Product, Variant
from app.schemas.product import (
    InventoryAdjust,
    ProductCreate,
    ProductUpdate,
    VariantCreate,
    VariantInventoryAdjust,
    VariantUpdate,
)
from app.services.qr_service import generate_product_qr


def _generate_qr_code(product: Product) -> str:
    return generate_product_qr(product)


def create_product(db: Session, data: ProductCreate) -> Product:
    product = Product(
        sku=data.sku,
        name=data.name,
        description=data.description,
        category=data.category,
        weight_oz=data.weight_oz,
        length_in=data.length_in,
        width_in=data.width_in,
        height_in=data.height_in,
        price=data.price,
        quantity=data.quantity,
        location=data.location,
        option_types=json.dumps(data.option_types),
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

    # Create variants if provided
    for v_data in data.variants:
        variant = Variant(
            product_id=product.id,
            variant_sku=v_data.variant_sku,
            attributes=json.dumps(v_data.attributes),
            price_override=v_data.price_override,
            weight_oz_override=v_data.weight_oz_override,
            length_in_override=v_data.length_in_override,
            width_in_override=v_data.width_in_override,
            height_in_override=v_data.height_in_override,
            quantity=v_data.quantity,
            location=v_data.location or product.location,
        )
        db.add(variant)

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
    update_data = data.model_dump(exclude_unset=True)
    if "option_types" in update_data:
        update_data["option_types"] = json.dumps(update_data["option_types"])
    for field, value in update_data.items():
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


# --- Variant service ---

def create_variant(db: Session, product_id: str, data: VariantCreate) -> Variant | None:
    product = get_product(db, product_id)
    if not product:
        return None
    existing = db.query(Variant).filter(Variant.variant_sku == data.variant_sku).first()
    if existing:
        raise ValueError(f"Variant SKU {data.variant_sku} already exists")
    variant = Variant(
        product_id=product_id,
        variant_sku=data.variant_sku,
        attributes=json.dumps(data.attributes),
        price_override=data.price_override,
        weight_oz_override=data.weight_oz_override,
        length_in_override=data.length_in_override,
        width_in_override=data.width_in_override,
        height_in_override=data.height_in_override,
        quantity=data.quantity,
        location=data.location or product.location,
    )
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


def get_variant(db: Session, variant_id: str) -> Variant | None:
    return db.query(Variant).filter(Variant.id == variant_id).first()


def get_variant_by_sku(db: Session, variant_sku: str) -> Variant | None:
    return db.query(Variant).filter(Variant.variant_sku == variant_sku).first()


def update_variant(db: Session, variant_id: str, data: VariantUpdate) -> Variant | None:
    variant = get_variant(db, variant_id)
    if not variant:
        return None
    update_data = data.model_dump(exclude_unset=True)
    if "attributes" in update_data:
        update_data["attributes"] = json.dumps(update_data["attributes"])
    for field, value in update_data.items():
        setattr(variant, field, value)
    db.commit()
    db.refresh(variant)
    return variant


def delete_variant(db: Session, variant_id: str) -> bool:
    variant = get_variant(db, variant_id)
    if not variant:
        return False
    db.delete(variant)
    db.commit()
    return True


def adjust_variant_inventory(db: Session, variant_id: str, data: VariantInventoryAdjust) -> Variant | None:
    variant = get_variant(db, variant_id)
    if not variant:
        return None
    new_qty = variant.quantity + data.quantity
    if new_qty < 0:
        raise ValueError(f"Insufficient stock. Current: {variant.quantity}, requested change: {data.quantity}")
    variant.quantity = new_qty
    log = InventoryLog(
        product_id=variant.product_id,
        change=data.quantity,
        reason=data.reason,
        balance_after=new_qty,
        note=f"[Variant {variant.variant_sku}] {data.note}",
    )
    db.add(log)
    db.commit()
    db.refresh(variant)
    return variant
