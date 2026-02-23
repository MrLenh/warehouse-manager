from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inventory_log import InventoryLog
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product


def inventory_summary(db: Session) -> dict:
    products = db.query(Product).all()
    total_products = len(products)
    total_units = sum(p.quantity for p in products)
    total_value = sum(p.quantity * p.price for p in products)
    low_stock = [p for p in products if p.quantity <= 5]

    return {
        "total_products": total_products,
        "total_units_in_stock": total_units,
        "total_inventory_value": round(total_value, 2),
        "low_stock_count": len(low_stock),
        "low_stock_items": [
            {"sku": p.sku, "name": p.name, "quantity": p.quantity} for p in low_stock
        ],
        "by_category": _group_by_category(products),
    }


def _group_by_category(products: list[Product]) -> list[dict]:
    cats: dict[str, dict] = {}
    for p in products:
        cat = p.category or "Uncategorized"
        if cat not in cats:
            cats[cat] = {"category": cat, "product_count": 0, "total_units": 0, "total_value": 0.0}
        cats[cat]["product_count"] += 1
        cats[cat]["total_units"] += p.quantity
        cats[cat]["total_value"] += p.quantity * p.price
    for v in cats.values():
        v["total_value"] = round(v["total_value"], 2)
    return list(cats.values())


def order_summary(db: Session, start_date: datetime | None = None, end_date: datetime | None = None) -> dict:
    q = db.query(Order)
    if start_date:
        q = q.filter(Order.created_at >= start_date)
    if end_date:
        q = q.filter(Order.created_at <= end_date)

    orders = q.all()
    total = len(orders)
    by_status: dict[str, int] = {}
    total_revenue = 0.0
    total_shipping = 0.0
    total_processing = 0.0

    for o in orders:
        status_val = o.status if isinstance(o.status, str) else o.status.value
        by_status[status_val] = by_status.get(status_val, 0) + 1
        total_revenue += o.total_price
        total_shipping += o.shipping_cost
        total_processing += o.processing_fee

    return {
        "total_orders": total,
        "orders_by_status": by_status,
        "total_revenue": round(total_revenue, 2),
        "total_shipping_cost": round(total_shipping, 2),
        "total_processing_fees": round(total_processing, 2),
        "date_range": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
    }


def top_products(db: Session, limit: int = 10) -> list[dict]:
    results = (
        db.query(
            OrderItem.product_id,
            OrderItem.sku,
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("total_sold"),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label("total_revenue"),
        )
        .group_by(OrderItem.product_id, OrderItem.sku, OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "product_id": r.product_id,
            "sku": r.sku,
            "name": r.product_name,
            "total_sold": int(r.total_sold),
            "total_revenue": round(float(r.total_revenue), 2),
        }
        for r in results
    ]


def inventory_movement(db: Session, product_id: str | None = None, limit: int = 50) -> list[dict]:
    q = db.query(InventoryLog)
    if product_id:
        q = q.filter(InventoryLog.product_id == product_id)
    logs = q.order_by(InventoryLog.created_at.desc()).limit(limit).all()

    return [
        {
            "id": log.id,
            "product_id": log.product_id,
            "change": log.change,
            "reason": log.reason,
            "reference_id": log.reference_id,
            "balance_after": log.balance_after,
            "note": log.note,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
