"""Customer portal API — endpoints scoped to the logged-in customer."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.order import Order, OrderItem
from app.models.product import Product, Variant
from app.models.stock_request import StockRequest, StockRequestStatus
from app.models.user import User
from app.schemas.order import AddressInput, OrderCreate, OrderItemCreate, OrderOut
from app.schemas.stock_request import StockRequestCreate, StockRequestItemCreate, StockRequestOut
from app.services import auth_service, order_service, product_service, stock_request_service

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

    # Orders by customer_id or customer_name match
    orders = (
        db.query(Order)
        .filter(
            (Order.customer_id == customer.id)
            | (sa_func.lower(Order.customer_name) == customer.name.lower().strip())
        )
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
    q: str = "",
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = _require_customer(user, db)
    query = db.query(Order).filter(
        (Order.customer_id == customer.id)
        | (sa_func.lower(Order.customer_name) == customer.name.lower().strip())
    )
    if status:
        query = query.filter(Order.status == status)
    if q:
        search = f"%{q}%"
        query = query.filter(
            Order.order_number.ilike(search)
            | Order.order_name.ilike(search)
            | Order.shop_name.ilike(search)
            | Order.tracking_number.ilike(search)
        )
    total = query.count()
    orders = query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "orders": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "order_name": o.order_name or "",
                "shop_name": o.shop_name or "",
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


# ---------------------------------------------------------------------------
# CSV import orders
# ---------------------------------------------------------------------------

PORTAL_CSV_COLUMNS = [
    "order_name", "shop_name", "customer_email", "customer_phone",
    "ship_to_name", "ship_to_street1", "ship_to_street2",
    "ship_to_city", "ship_to_state", "ship_to_zip", "ship_to_country",
    "carrier", "service",
    "sku", "item_name", "quantity", "notes",
]


@router.get("/orders/import-template")
def download_import_template(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """CSV template — customer_name column is removed (auto-filled)."""
    from fastapi.responses import StreamingResponse

    _require_customer(user, db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(PORTAL_CSV_COLUMNS)
    writer.writerow([
        "Order A", "Shop ABC", "a@email.com", "0901234567",
        "Nguyen Van A", "123 Le Loi", "", "Ho Chi Minh", "HCM", "70000", "US",
        "", "",
        "SP-001", "San pham A", "2", "Giao buoi sang",
    ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=order_import_template.csv"},
    )


@router.post("/orders/import")
def import_orders(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import orders via CSV. customer_name is locked to the logged-in customer."""
    customer = _require_customer(user, db)

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    try:
        content = file.file.read().decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(400, f"Cannot read CSV file: {e}")
    reader = csv.DictReader(io.StringIO(content))

    order_groups: dict[str, dict] = {}
    group_order: list[str] = []
    errors: list[dict] = []
    auto_counter = 0

    for row_num, row in enumerate(reader, start=2):
        order_name = (row.get("order_name") or "").strip()
        shop_name = (row.get("shop_name") or "").strip()
        sku = (row.get("sku") or "").strip()
        if not sku:
            errors.append({"row": row_num, "error": "SKU is required"})
            continue

        try:
            quantity = int(row.get("quantity") or 1)
        except (ValueError, TypeError):
            errors.append({"row": row_num, "error": f"Invalid quantity '{row.get('quantity')}'"})
            continue
        if quantity < 1:
            quantity = 1

        if not order_name:
            auto_counter += 1
            order_name = f"__auto_{auto_counter}_row{row_num}"

        ship_to_name = (row.get("ship_to_name") or "").strip() or customer.name

        if order_name not in order_groups:
            order_groups[order_name] = {
                "customer_name": customer.name,
                "shop_name": shop_name,
                "customer_email": (row.get("customer_email") or "").strip() or customer.email,
                "customer_phone": (row.get("customer_phone") or "").strip() or customer.phone,
                "ship_to_name": ship_to_name,
                "ship_to_street1": (row.get("ship_to_street1") or "").strip(),
                "ship_to_street2": (row.get("ship_to_street2") or "").strip(),
                "ship_to_city": (row.get("ship_to_city") or "").strip(),
                "ship_to_state": (row.get("ship_to_state") or "").strip(),
                "ship_to_zip": (row.get("ship_to_zip") or "").strip(),
                "ship_to_country": (row.get("ship_to_country") or "").strip() or "US",
                "carrier": (row.get("carrier") or "").strip(),
                "service": (row.get("service") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
                "display_order_name": (row.get("order_name") or "").strip(),
                "items": [],
            }
            group_order.append(order_name)

        order_groups[order_name]["items"].append({
            "sku": sku,
            "item_name": (row.get("item_name") or "").strip(),
            "quantity": quantity,
            "row": row_num,
        })

    # Pre-check duplicate order_names
    display_names = [order_groups[k]["display_order_name"] for k in group_order if order_groups[k]["display_order_name"]]
    if display_names:
        existing = db.query(Order.order_name).filter(Order.order_name.in_(display_names)).all()
        existing_set = {o.order_name for o in existing}
        for dn in existing_set:
            errors.append({"order_name": dn, "error": f"Order name '{dn}' already exists"})
        group_order = [k for k in group_order if order_groups[k]["display_order_name"] not in existing_set]

    created = 0
    created_details: list[dict] = []

    for key in group_order:
        group = order_groups[key]
        resolved_items = []
        has_error = False
        for item in group["items"]:
            sku_val = item["sku"]
            row_num = item["row"]
            variant = product_service.get_variant_by_sku(db, sku_val)
            if variant:
                resolved_items.append({"product_id": variant.product_id, "variant_id": variant.id, "quantity": item["quantity"], "item_name": item.get("item_name", "")})
                continue
            product = product_service.get_product_by_sku(db, sku_val)
            if product:
                if product.variants and len(product.variants) > 0:
                    errors.append({"row": row_num, "sku": sku_val, "error": f"Product '{sku_val}' has variants. Use variant_sku."})
                    has_error = True
                    break
                resolved_items.append({"product_id": product.id, "variant_id": "", "quantity": item["quantity"], "item_name": item.get("item_name", "")})
                continue
            errors.append({"row": row_num, "sku": sku_val, "error": f"SKU '{sku_val}' not found"})
            has_error = True
            break

        if has_error or not resolved_items:
            continue

        order_data = OrderCreate(
            order_name=group["display_order_name"],
            customer_name=customer.name,
            shop_name=group["shop_name"],
            customer_email=group["customer_email"],
            customer_phone=group["customer_phone"],
            ship_to=AddressInput(
                name=group["ship_to_name"],
                street1=group["ship_to_street1"],
                city=group["ship_to_city"],
                state=group["ship_to_state"],
                zip=group["ship_to_zip"],
                country=group["ship_to_country"],
            ),
            items=[OrderItemCreate(product_id=ri["product_id"], variant_id=ri["variant_id"], quantity=ri["quantity"], item_name=ri.get("item_name", "")) for ri in resolved_items],
            carrier=group["carrier"],
            service=group["service"],
            notes=group["notes"],
        )

        try:
            order_service.create_order(db, order_data)
            created += 1
            created_details.append({"order_name": group["display_order_name"] or key, "items": len(resolved_items)})
        except ValueError as e:
            errors.append({"order_name": group["display_order_name"] or key, "error": str(e)})

    return {"created": created, "created_details": created_details, "errors": errors}


@router.get("/orders/{order_id}")
def get_order(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = _require_customer(user, db)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.customer_id != customer.id and order.customer_name.lower().strip() != customer.name.lower().strip():
        raise HTTPException(403, "Access denied")
    return {
        "id": order.id,
        "order_number": order.order_number,
        "order_name": order.order_name or "",
        "shop_name": order.shop_name or "",
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
    category: str = "",
    location: str = "",
    stock: str = "",
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = _require_customer(user, db)
    query = db.query(Product).filter(
        (Product.customer_id == customer.id) | (Product.customer_id.is_(None))
    )
    if q:
        query = query.filter(
            Product.name.ilike(f"%{q}%") | Product.sku.ilike(f"%{q}%")
        )
    if category:
        query = query.filter(Product.category == category)
    if location:
        query = query.filter(Product.location == location)
    total = query.count()
    products = query.order_by(Product.name).offset(skip).limit(limit).all()

    results = []
    for p in products:
        variant_stock = sum(v.quantity for v in p.variants)
        total_stock = p.quantity + variant_stock
        if stock == "low" and total_stock > 5:
            continue
        if stock == "out" and total_stock > 0:
            continue
        if stock == "in" and total_stock <= 0:
            continue
        results.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "image_url": p.image_url or "",
            "quantity": p.quantity,
            "variant_count": len(p.variants),
            "total_stock": total_stock,
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

    # Return filter options for the frontend
    all_products = db.query(Product).filter(
        (Product.customer_id == customer.id) | (Product.customer_id.is_(None))
    ).all()
    categories = sorted({p.category for p in all_products if p.category})
    locations = sorted({p.location for p in all_products if p.location})

    return {"total": len(results), "products": results, "categories": categories, "locations": locations}


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
                "shop_name": o.shop_name or "",
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "item_count": sum(i.quantity for i in o.items),
                "shipping_cost": o.shipping_cost,
                "created_at": o.created_at.isoformat() if o.created_at else "",
            }
            for o in inv.orders
        ],
    }


@router.get("/invoices/{invoice_id}/export")
def export_portal_invoice_csv(
    invoice_id: str,
    shop_name: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export invoice as CSV for portal customer. Optionally filter by shop_name."""
    from fastapi.responses import StreamingResponse

    customer = _require_customer(user, db)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.customer_id == customer.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    orders = inv.orders
    if shop_name:
        orders = [o for o in orders if (o.shop_name or "").lower() == shop_name.lower().strip()]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "invoice_number", "order_number", "order_name", "shop_name",
        "status", "item_count", "shipping_cost", "processing_fee", "total_price", "created_at",
        "sku", "product_name", "variant_label", "quantity", "unit_price",
    ])
    for o in orders:
        for item in o.items:
            writer.writerow([
                inv.invoice_number,
                o.order_number,
                o.order_name or "",
                o.shop_name or "",
                o.status.value if hasattr(o.status, "value") else str(o.status),
                sum(i.quantity for i in o.items),
                o.shipping_cost,
                o.processing_fee,
                o.total_price,
                o.created_at.isoformat() if o.created_at else "",
                item.sku,
                item.product_name,
                item.variant_label or "",
                item.quantity,
                item.unit_price,
            ])

    buf.seek(0)
    filename = f"{inv.invoice_number}"
    if shop_name:
        filename += f"_{shop_name}"
    filename += ".csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Create orders (manual / API)
# ---------------------------------------------------------------------------


@router.post("/orders", status_code=201)
def create_portal_order(
    data: OrderCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Customer creates an order. customer_name is forced to their own name."""
    customer = _require_customer(user, db)
    # Override customer_name — customer cannot impersonate
    data.customer_name = customer.name
    data.customer_email = data.customer_email or customer.email
    data.customer_phone = data.customer_phone or customer.phone
    try:
        order = order_service.create_order(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    auth_service.log_activity(
        db, user.id, user.username, "create_order",
        detail=f"Portal: {order.order_number}",
        ip=request.client.host if request.client else "",
    )
    return {
        "id": order.id,
        "order_number": order.order_number,
        "order_name": order.order_name or "",
        "shop_name": order.shop_name or "",
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "item_count": sum(i.quantity for i in order.items),
        "total_price": order.total_price,
    }


# ---------------------------------------------------------------------------
# Stock requests
# ---------------------------------------------------------------------------


@router.get("/stock-requests")
def list_stock_requests(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List stock requests that contain products owned by this customer."""
    customer = _require_customer(user, db)
    my_product_ids = {
        p.id for p in db.query(Product.id).filter(
            (Product.customer_id == customer.id) | (Product.customer_id.is_(None))
        ).all()
    }
    from app.models.stock_request import StockRequestItem
    sr_ids = {
        row.stock_request_id for row in
        db.query(StockRequestItem.stock_request_id)
        .filter(StockRequestItem.product_id.in_(my_product_ids))
        .distinct()
        .all()
    } if my_product_ids else set()

    query = db.query(StockRequest).filter(StockRequest.id.in_(sr_ids)) if sr_ids else db.query(StockRequest).filter(False)
    total = query.count()
    reqs = query.order_by(StockRequest.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "stock_requests": [
            {
                "id": sr.id,
                "request_number": sr.request_number,
                "supplier": sr.supplier,
                "status": sr.status.value if hasattr(sr.status, "value") else str(sr.status),
                "notes": sr.notes,
                "item_count": len(sr.items),
                "total_qty": sum(i.quantity_requested for i in sr.items),
                "created_at": sr.created_at.isoformat() if sr.created_at else "",
                "items": [
                    {
                        "id": i.id,
                        "sku": i.sku,
                        "product_name": i.product_name,
                        "variant_label": i.variant_label,
                        "quantity_requested": i.quantity_requested,
                        "quantity_received": i.quantity_received,
                    }
                    for i in sr.items
                ],
            }
            for sr in reqs
        ],
    }


@router.post("/stock-requests", status_code=201)
def create_stock_request(
    data: StockRequestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Customer creates a stock request for their products."""
    customer = _require_customer(user, db)
    for item in data.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(400, f"Product not found: {item.product_id}")
        if product.customer_id is not None and product.customer_id != customer.id:
            raise HTTPException(403, f"Product {product.sku} does not belong to you")
    try:
        sr = stock_request_service.create_stock_request(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "id": sr.id,
        "request_number": sr.request_number,
        "status": sr.status.value if hasattr(sr.status, "value") else str(sr.status),
        "item_count": len(sr.items),
    }
