import json

from sqlalchemy.orm import Session

from app.models.inventory_log import InventoryLog
from app.models.product import Product, Variant
from app.models.stock_batch import StockBatch
from app.schemas.product import (
    InventoryAdjust,
    ProductCreate,
    ProductUpdate,
    VariantCreate,
    VariantInventoryAdjust,
    VariantUpdate,
)
from app.services.qr_service import generate_product_qr


def _consume_fifo_for_loss(db: Session, product_id: str, variant_id: str, quantity: int) -> float:
    """Consume FIFO from batches and return the total cost of consumed units (for loss/adjustment)."""
    batches = (
        db.query(StockBatch)
        .filter(
            StockBatch.product_id == product_id,
            StockBatch.variant_id == (variant_id or ""),
            StockBatch.quantity_remaining > 0,
        )
        .order_by(StockBatch.created_at.asc())
        .all()
    )
    remaining = quantity
    total_cost = 0.0
    for batch in batches:
        if remaining <= 0:
            break
        consume = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= consume
        total_cost += consume * batch.unit_cost
        remaining -= consume
    return round(total_cost, 2)


def _recalculate_price_from_batches(db: Session, product_id: str, variant_id: str = "") -> None:
    """Recalculate product/variant price as weighted average cost from remaining batches."""
    batches = (
        db.query(StockBatch)
        .filter(
            StockBatch.product_id == product_id,
            StockBatch.variant_id == (variant_id or ""),
            StockBatch.quantity_remaining > 0,
        )
        .all()
    )
    if not batches:
        return
    total_qty = sum(b.quantity_remaining for b in batches)
    total_cost = sum(b.quantity_remaining * b.unit_cost for b in batches)
    if total_qty == 0:
        return
    weighted_avg = round(total_cost / total_qty, 2)
    if variant_id:
        variant = db.query(Variant).filter(Variant.id == variant_id).first()
        if variant:
            variant.price_override = weighted_avg
    else:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            product.price = weighted_avg


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
        image_url=data.image_url,
        option_types=json.dumps(data.option_types),
        customer_id=data.customer_id,
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


def adjust_inventory(db: Session, product_id: str, data: InventoryAdjust, adjusted_by: str = "") -> Product | None:
    """Adjust inventory with proper FIFO batch tracking.

    - reason='inbound': creates a new StockBatch with provided unit_cost (or current price)
    - reason='adjustment' (qty < 0): consumes FIFO from batches, records loss cost
    - reason='adjustment' (qty > 0): creates a new StockBatch (treated as found stock)
    """
    product = get_product(db, product_id)
    if not product:
        return None

    new_qty = product.quantity + data.quantity
    if new_qty < 0:
        raise ValueError(f"Insufficient stock. Current: {product.quantity}, requested change: {data.quantity}")

    cost_amount = 0.0
    is_inbound = data.reason == "inbound" or (data.reason == "adjustment" and data.quantity > 0)
    is_loss = data.reason == "adjustment" and data.quantity < 0

    if is_inbound and data.quantity > 0:
        # Need a unit_cost — use provided value or fall back to current product price
        unit_cost = data.unit_cost if data.unit_cost is not None else product.price
        if unit_cost < 0:
            raise ValueError("unit_cost cannot be negative")
        # Create a new StockBatch (no stock_request linked, use a sentinel reference)
        batch = StockBatch(
            product_id=product.id,
            variant_id="",
            stock_request_id=None,
            source=("inbound" if data.reason == "inbound" else "adjustment"),  # not from a stock request
            unit_cost=unit_cost,
            quantity_received=data.quantity,
            quantity_remaining=data.quantity,
        )
        db.add(batch)
        cost_amount = round(data.quantity * unit_cost, 2)
    elif is_loss:
        # Consume FIFO and record total cost of loss
        cost_amount = _consume_fifo_for_loss(db, product.id, "", -data.quantity)

    product.quantity = new_qty

    gap = data.quantity if data.reason == "adjustment" else 0
    log = InventoryLog(
        product_id=product.id,
        change=data.quantity,
        reason=data.reason,
        balance_after=new_qty,
        gap=gap,
        cost_amount=cost_amount,
        adjusted_by=adjusted_by,
        note=data.note,
    )
    db.add(log)
    db.flush()
    # Recalculate weighted average after batch changes
    _recalculate_price_from_batches(db, product.id, "")
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


def delete_product(db: Session, product_id: str) -> dict:
    """Delete a product and all related records (variants, batches, logs).
    Cannot delete if referenced by orders or active stock requests."""
    from app.models.order import OrderItem
    from app.models.stock_request import StockRequest, StockRequestItem, StockRequestStatus
    from app.models.stock_batch import StockBatch
    from app.models.inventory_log import InventoryLog

    product = get_product(db, product_id)
    if not product:
        return {"deleted": False, "error": "Product not found"}

    # Check references in orders
    order_count = db.query(OrderItem).filter(OrderItem.product_id == product_id).count()
    if order_count > 0:
        return {"deleted": False, "error": f"Cannot delete: product is used in {order_count} order item(s)"}

    # Check active stock requests
    active_sr = (
        db.query(StockRequestItem)
        .join(StockRequest)
        .filter(
            StockRequestItem.product_id == product_id,
            StockRequest.status.in_([
                StockRequestStatus.DRAFT,
                StockRequestStatus.PENDING,
                StockRequestStatus.APPROVED,
                StockRequestStatus.RECEIVING,
            ]),
        )
        .count()
    )
    if active_sr > 0:
        return {"deleted": False, "error": f"Cannot delete: product is in {active_sr} active stock request(s)"}

    # Delete related records
    db.query(StockBatch).filter(StockBatch.product_id == product_id).delete()
    db.query(InventoryLog).filter(InventoryLog.product_id == product_id).delete()
    # Stock request items from completed/cancelled SRs
    db.query(StockRequestItem).filter(StockRequestItem.product_id == product_id).delete()

    db.delete(product)
    db.commit()
    return {"deleted": True, "product_id": product_id}


def adjust_variant_inventory(db: Session, variant_id: str, data: VariantInventoryAdjust, adjusted_by: str = "") -> Variant | None:
    """Adjust variant inventory with proper FIFO batch tracking. See adjust_inventory."""
    variant = get_variant(db, variant_id)
    if not variant:
        return None

    new_qty = variant.quantity + data.quantity
    if new_qty < 0:
        raise ValueError(f"Insufficient stock. Current: {variant.quantity}, requested change: {data.quantity}")

    cost_amount = 0.0
    is_inbound = data.reason == "inbound" or (data.reason == "adjustment" and data.quantity > 0)
    is_loss = data.reason == "adjustment" and data.quantity < 0

    if is_inbound and data.quantity > 0:
        unit_cost = data.unit_cost if data.unit_cost is not None else variant.effective_price
        if unit_cost < 0:
            raise ValueError("unit_cost cannot be negative")
        batch = StockBatch(
            product_id=variant.product_id,
            variant_id=variant.id,
            stock_request_id=None,
            source=("inbound" if data.reason == "inbound" else "adjustment"),
            unit_cost=unit_cost,
            quantity_received=data.quantity,
            quantity_remaining=data.quantity,
        )
        db.add(batch)
        cost_amount = round(data.quantity * unit_cost, 2)
    elif is_loss:
        cost_amount = _consume_fifo_for_loss(db, variant.product_id, variant.id, -data.quantity)

    variant.quantity = new_qty

    gap = data.quantity if data.reason == "adjustment" else 0
    log = InventoryLog(
        product_id=variant.product_id,
        change=data.quantity,
        reason=data.reason,
        balance_after=new_qty,
        gap=gap,
        cost_amount=cost_amount,
        adjusted_by=adjusted_by,
        note=f"[Variant {variant.variant_sku}] {data.note}",
    )
    db.add(log)
    db.flush()
    _recalculate_price_from_batches(db, variant.product_id, variant.id)
    db.commit()
    db.refresh(variant)
    return variant
