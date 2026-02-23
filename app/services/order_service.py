import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.inventory_log import InventoryLog
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.schemas.order import OrderCreate, OrderStatusUpdate


def _generate_order_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6].upper()
    return f"ORD-{ts}-{short}"


def _add_status_history(order: Order, status: str, note: str = "") -> None:
    history = json.loads(order.status_history) if order.status_history else []
    history.append({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": note,
    })
    order.status_history = json.dumps(history)


def create_order(db: Session, data: OrderCreate) -> Order:
    order = Order(
        order_number=_generate_order_number(),
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        ship_to_name=data.ship_to.name,
        ship_to_street1=data.ship_to.street1,
        ship_to_street2=data.ship_to.street2,
        ship_to_city=data.ship_to.city,
        ship_to_state=data.ship_to.state,
        ship_to_zip=data.ship_to.zip,
        ship_to_country=data.ship_to.country,
        webhook_url=data.webhook_url,
        notes=data.notes,
        status=OrderStatus.PENDING,
    )

    if data.ship_from:
        order.ship_from_name = data.ship_from.name
        order.ship_from_street1 = data.ship_from.street1
        order.ship_from_city = data.ship_from.city
        order.ship_from_state = data.ship_from.state
        order.ship_from_zip = data.ship_from.zip
        order.ship_from_country = data.ship_from.country

    db.add(order)
    db.flush()

    total_items = 0
    for item_data in data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if not product:
            raise ValueError(f"Product {item_data.product_id} not found")
        if product.quantity < item_data.quantity:
            raise ValueError(f"Insufficient stock for {product.sku}. Available: {product.quantity}")

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            sku=product.sku,
            product_name=product.name,
            quantity=item_data.quantity,
            unit_price=product.price,
        )
        db.add(order_item)

        # Deduct inventory
        product.quantity -= item_data.quantity
        log = InventoryLog(
            product_id=product.id,
            change=-item_data.quantity,
            reason="order",
            reference_id=order.id,
            balance_after=product.quantity,
            note=f"Reserved for order {order.order_number}",
        )
        db.add(log)
        total_items += item_data.quantity

    # Calculate processing fee
    order.processing_fee = total_items * settings.PROCESSING_FEE_PER_ITEM
    order.total_price = order.processing_fee  # shipping added when label purchased

    _add_status_history(order, OrderStatus.PENDING, "Order created")

    db.commit()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: str) -> Order | None:
    return db.query(Order).filter(Order.id == order_id).first()


def get_order_by_number(db: Session, order_number: str) -> Order | None:
    return db.query(Order).filter(Order.order_number == order_number).first()


def list_orders(
    db: Session, skip: int = 0, limit: int = 100, status: OrderStatus | None = None
) -> list[Order]:
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    return q.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


def update_order_status(db: Session, order_id: str, data: OrderStatusUpdate) -> Order | None:
    order = get_order(db, order_id)
    if not order:
        return None
    order.status = data.status
    _add_status_history(order, data.status.value, data.note)
    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order_id: str) -> Order | None:
    order = get_order(db, order_id)
    if not order:
        return None
    if order.status in (OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED):
        raise ValueError(f"Cannot cancel order in {order.status} status")

    # Restore inventory
    for item in order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product:
            product.quantity += item.quantity
            log = InventoryLog(
                product_id=product.id,
                change=item.quantity,
                reason="order_cancelled",
                reference_id=order.id,
                balance_after=product.quantity,
                note=f"Restored from cancelled order {order.order_number}",
            )
            db.add(log)

    order.status = OrderStatus.CANCELLED
    _add_status_history(order, OrderStatus.CANCELLED, "Order cancelled")
    db.commit()
    db.refresh(order)
    return order
