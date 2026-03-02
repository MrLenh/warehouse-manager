"""Customer portal API — read-only endpoints scoped to the logged-in customer."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.order import Order, OrderItem
from app.models.product import Product, Variant
from app.models.user import User

router = APIRouter(prefix="/portal", tags=["customer-portal"])


def _require_customer(user: User, db: Session) -> Customer:
    """Ensure user is a customer and return their Customer record."""
    if user.role != "customer" or not user.customer_id:
        raise HTTPException(403, "Customer portal access only")
    customer = db.query(Customer).filter(Customer.id == user.customer_id).first()
    if not customer:
        raise HTTPException(404, "Customer record not found")
    return customer


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = _require_customer(user, db)

    # Orders by customer_name match
    orders = (
        db.query(Order)
        .filter(sa_func.lower(Order.customer_name) == customer.name.lower().strip())
        .all()
    )
    total_orders = len(orders)
    active_orders = sum(
        1 for o in orders if o.status not in ("delivered", "cancelled")
    )

    # Products owned by customer
    product_count = db.query(Product).filter(Product.customer_id == customer.id).count()

    # Total inventory (sum of product qty + variant qty)
    products = db.query(Product).filter(Product.customer_id == customer.id).all()
    total_stock = sum(p.quantity for p in products)
    for p in products:
        total_stock += sum(v.quantity for v in p.variants)

    # Invoices
    invoices = db.query(Invoice).filter(Invoice.customer_id == customer.id).all()
    unpaid = sum(1 for inv in invoices if inv.status in ("new", "requested"))
    total_invoiced = sum(inv.total_price for inv in invoices)

    return {
        "customer_name": customer.name,
        "company": customer.company,
        "total_orders": total_orders,
        "active_orders": active_orders,
        "product_count": product_count,
        "total_stock": total_stock,
        "invoice_count": len(invoices),
        "unpaid_invoices": unpaid,
        "total_invoiced": round(total_invoiced, 2),
    }


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@router.get("/orders")
def list_orders(
    status: str = "",
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = _require_customer(user, db)
    query = db.query(Order).filter(
        sa_func.lower(Order.customer_name) == customer.name.lower().strip()
    )
    if status:
        query = query.filter(Order.status == status)
    total = query.count()
    orders = query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "orders": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "order_name": o.order_name or "",
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "item_count": sum(i.quantity for i in o.items),
                "tracking_number": o.tracking_number or "",
                "tracking_url": o.tracking_url or "",
                "shipping_cost": o.shipping_cost,
                "total_price": o.total_price,
                "created_at": o.created_at.isoformat() if o.created_at else "",
            }
            for o in orders
        ],
    }


@router.get("/orders/{order_id}")
def get_order(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = _require_customer(user, db)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.customer_name.lower().strip() != customer.name.lower().strip():
        raise HTTPException(403, "Access denied")
    return {
        "id": order.id,
        "order_number": order.order_number,
        "order_name": order.order_name or "",
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "tracking_number": order.tracking_number or "",
        "tracking_url": order.tracking_url or "",
        "shipping_cost": order.shipping_cost,
        "processing_fee": order.processing_fee,
        "total_price": order.total_price,
        "created_at": order.created_at.isoformat() if order.created_at else "",
        "items": [
            {
                "sku": i.sku,
                "product_name": i.product_name,
                "variant_label": i.variant_label or "",
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "image_url": i.image_url,
            }
            for i in order.items
        ],
    }


# ---------------------------------------------------------------------------
# Inventory (products owned by customer)
# ---------------------------------------------------------------------------


@router.get("/products")
def list_products(
    q: str = "",
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = _require_customer(user, db)
    query = db.query(Product).filter(Product.customer_id == customer.id)
    if q:
        query = query.filter(
            Product.name.ilike(f"%{q}%") | Product.sku.ilike(f"%{q}%")
        )
    total = query.count()
    products = query.order_by(Product.name).offset(skip).limit(limit).all()

    results = []
    for p in products:
        variant_stock = sum(v.quantity for v in p.variants)
        results.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "image_url": p.image_url or "",
            "quantity": p.quantity,
            "variant_count": len(p.variants),
            "total_stock": p.quantity + variant_stock,
            "location": p.location,
            "variants": [
                {
                    "id": v.id,
                    "variant_sku": v.variant_sku,
                    "attributes": v.attributes,
                    "quantity": v.quantity,
                    "location": v.location,
                }
                for v in p.variants
            ],
        })
    return {"total": total, "products": results}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


@router.get("/invoices")
def list_invoices(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = _require_customer(user, db)
    query = db.query(Invoice).filter(Invoice.customer_id == customer.id)
    total = query.count()
    invoices = query.order_by(Invoice.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "invoices": [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "invoice_name": inv.invoice_name,
                "status": inv.status or "new",
                "date_to": inv.date_to.isoformat() if inv.date_to else "",
                "order_count": inv.order_count,
                "item_count": inv.item_count,
                "shipping_fee_total": inv.shipping_fee_total,
                "processing_fee_total": inv.processing_fee_total,
                "stocking_fee_total": inv.stocking_fee_total,
                "discount": inv.discount,
                "total_price": inv.total_price,
                "created_at": inv.created_at.isoformat() if inv.created_at else "",
            }
            for inv in invoices
        ],
    }


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = _require_customer(user, db)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.customer_id == customer.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "invoice_name": inv.invoice_name,
        "status": inv.status or "new",
        "date_to": inv.date_to.isoformat() if inv.date_to else "",
        "order_count": inv.order_count,
        "item_count": inv.item_count,
        "processing_fee_unit": inv.processing_fee_unit,
        "processing_fee_total": inv.processing_fee_total,
        "shipping_fee_total": inv.shipping_fee_total,
        "stocking_fee_unit": inv.stocking_fee_unit,
        "stocking_fee_total": inv.stocking_fee_total,
        "discount": inv.discount,
        "total_price": inv.total_price,
        "notes": inv.notes,
        "created_at": inv.created_at.isoformat() if inv.created_at else "",
        "orders": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "order_name": o.order_name or "",
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "item_count": sum(i.quantity for i in o.items),
                "shipping_cost": o.shipping_cost,
                "created_at": o.created_at.isoformat() if o.created_at else "",
            }
            for o in inv.orders
        ],
    }
