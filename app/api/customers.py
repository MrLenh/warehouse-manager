from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.order import Order
from app.models.user import User
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate
from app.schemas.invoice import InvoiceCreate, InvoiceOrderOut, InvoiceOut, InvoicePreview, InvoiceStatusUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_invoiceable_orders(db: Session, customer: Customer, date_to: date) -> list[Order]:
    """Find orders matching customer name, created up to date_to, not yet invoiced."""
    end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)
    return (
        db.query(Order)
        .filter(
            sa_func.lower(Order.customer_name) == customer.name.lower().strip(),
            Order.created_at <= end,
            Order.invoice_id.is_(None),
        )
        .order_by(Order.created_at)
        .all()
    )


def _build_order_out(o: Order) -> InvoiceOrderOut:
    return InvoiceOrderOut(
        id=o.id,
        order_number=o.order_number,
        order_name=o.order_name or "",
        customer_name=o.customer_name,
        status=o.status.value if hasattr(o.status, "value") else str(o.status),
        item_count=sum(i.quantity for i in o.items),
        shipping_cost=o.shipping_cost,
        processing_fee=o.processing_fee,
        total_price=o.total_price,
        created_at=o.created_at,
    )


def _calc_totals(orders: list[Order], processing_fee_unit: float, stocking_fee_unit: float, discount: float = 0.0):
    order_count = len(orders)
    item_count = sum(sum(i.quantity for i in o.items) for o in orders)
    processing_fee_total = round(processing_fee_unit * item_count, 2)
    shipping_fee_total = round(sum(o.shipping_cost for o in orders), 2)
    stocking_fee_total = round(stocking_fee_unit * item_count, 2)
    subtotal = processing_fee_total + shipping_fee_total + stocking_fee_total
    total_price = round(max(0, subtotal - discount), 2)
    return {
        "order_count": order_count,
        "item_count": item_count,
        "processing_fee_unit": processing_fee_unit,
        "processing_fee_total": processing_fee_total,
        "shipping_fee_total": shipping_fee_total,
        "stocking_fee_unit": stocking_fee_unit,
        "stocking_fee_total": stocking_fee_total,
        "discount": round(discount, 2),
        "total_price": total_price,
    }


def _invoice_to_out(inv: Invoice, customer: Customer | None, orders: list[Order]) -> InvoiceOut:
    return InvoiceOut(
        id=inv.id,
        invoice_number=inv.invoice_number,
        invoice_name=inv.invoice_name,
        customer_id=inv.customer_id,
        customer_name=customer.name if customer else "",
        date_to=inv.date_to,
        status=inv.status or "new",
        order_count=inv.order_count,
        item_count=inv.item_count,
        processing_fee_unit=inv.processing_fee_unit,
        processing_fee_total=inv.processing_fee_total,
        shipping_fee_total=inv.shipping_fee_total,
        stocking_fee_unit=inv.stocking_fee_unit,
        stocking_fee_total=inv.stocking_fee_total,
        discount=inv.discount,
        total_price=inv.total_price,
        notes=inv.notes,
        orders=[_build_order_out(o) for o in orders],
        created_at=inv.created_at,
        updated_at=inv.updated_at,
    )


# ---------------------------------------------------------------------------
# Invoice endpoints (MUST be before /{customer_id} to avoid path conflict)
# ---------------------------------------------------------------------------


@router.get("/invoices/preview")
def preview_invoice(
    customer_id: str,
    date_to: date,
    processing_fee_unit: float | None = None,
    stocking_fee_unit: float | None = None,
    discount: float = 0.0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview what an invoice would contain (without creating it)."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Customer not found")

    pfu = processing_fee_unit if processing_fee_unit is not None else settings.PROCESSING_FEE_PER_ITEM
    sfu = stocking_fee_unit if stocking_fee_unit is not None else settings.STOCKING_FEE_PER_ITEM

    orders = _find_invoiceable_orders(db, customer, date_to)
    totals = _calc_totals(orders, pfu, sfu, discount)
    return InvoicePreview(**totals, orders=[_build_order_out(o) for o in orders])


@router.post("/invoices", status_code=201)
def create_invoice(
    body: InvoiceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == body.customer_id).first()
    if not customer:
        raise HTTPException(404, "Customer not found")

    pfu = body.processing_fee_unit if body.processing_fee_unit is not None else settings.PROCESSING_FEE_PER_ITEM
    sfu = body.stocking_fee_unit if body.stocking_fee_unit is not None else settings.STOCKING_FEE_PER_ITEM

    orders = _find_invoiceable_orders(db, customer, body.date_to)
    if not orders:
        raise HTTPException(400, "No invoiceable orders found for this customer and date range")

    totals = _calc_totals(orders, pfu, sfu, body.discount)

    # Generate invoice number: INV-0001, INV-0002 …
    last = db.query(Invoice).order_by(Invoice.created_at.desc()).first()
    seq = 1
    if last and last.invoice_number.startswith("INV-"):
        try:
            seq = int(last.invoice_number.split("-")[1]) + 1
        except (IndexError, ValueError):
            pass
    inv_number = f"INV-{seq:04d}"

    inv = Invoice(
        invoice_number=inv_number,
        invoice_name=body.invoice_name,
        customer_id=body.customer_id,
        date_to=body.date_to,
        status="new",
        notes=body.notes,
        **totals,
    )
    db.add(inv)
    db.flush()

    # Link orders to invoice (mark as invoiced)
    for o in orders:
        o.invoice_id = inv.id
    db.commit()
    db.refresh(inv)

    return _invoice_to_out(inv, customer, orders)


@router.get("/invoices")
def list_invoices(
    customer_id: str = "",
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Invoice)
    if customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    total = query.count()
    invoices = query.order_by(Invoice.created_at.desc()).offset(skip).limit(limit).all()

    results = []
    for inv in invoices:
        customer = db.query(Customer).filter(Customer.id == inv.customer_id).first()
        results.append(_invoice_to_out(inv, customer, inv.orders))
    return {"total": total, "invoices": results}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    customer = db.query(Customer).filter(Customer.id == inv.customer_id).first()
    return _invoice_to_out(inv, customer, inv.orders)


@router.patch("/invoices/{invoice_id}/status")
def update_invoice_status(
    invoice_id: str,
    body: InvoiceStatusUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    allowed = {"new", "requested", "paid", "cancel"}
    if body.status not in allowed:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(sorted(allowed))}")
    inv.status = body.status
    db.commit()
    db.refresh(inv)
    customer = db.query(Customer).filter(Customer.id == inv.customer_id).first()
    return _invoice_to_out(inv, customer, inv.orders)


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    # Only allow delete for new or requested invoices
    if inv.status in ("paid", "cancel"):
        raise HTTPException(400, f"Cannot delete invoice with status '{inv.status}'")
    # Release orders back to un-invoiced
    for o in inv.orders:
        o.invoice_id = None
    db.delete(inv)
    db.commit()


# ---------------------------------------------------------------------------
# Customers CRUD
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
def create_customer(body: CustomerCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = Customer(name=body.name, email=body.email, phone=body.phone, company=body.company, notes=body.notes)
    db.add(c)
    db.commit()
    db.refresh(c)
    return CustomerOut.model_validate(c)


@router.get("")
def list_customers(
    q: str = "",
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Customer)
    if q:
        query = query.filter(
            Customer.name.ilike(f"%{q}%")
            | Customer.email.ilike(f"%{q}%")
            | Customer.company.ilike(f"%{q}%")
        )
    total = query.count()
    customers = query.order_by(Customer.name).offset(skip).limit(limit).all()
    return {"total": total, "customers": [CustomerOut.model_validate(c) for c in customers]}


@router.get("/{customer_id}")
def get_customer(customer_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Customer).filter(Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    return CustomerOut.model_validate(c)


@router.patch("/{customer_id}")
def update_customer(
    customer_id: str,
    body: CustomerUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).filter(Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(c, field, val)
    db.commit()
    db.refresh(c)
    return CustomerOut.model_validate(c)


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Customer).filter(Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    if db.query(Invoice).filter(Invoice.customer_id == customer_id).count():
        raise HTTPException(400, "Cannot delete customer with existing invoices")
    db.delete(c)
    db.commit()
