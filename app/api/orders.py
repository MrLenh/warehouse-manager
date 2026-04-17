import asyncio
import csv
import io
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.order import OrderPriority, OrderStatus
from app.models.user import User
from app.schemas.order import AddressUpdate, BuyLabelRequest, OrderCreate, OrderOut, OrderStatusUpdate, OrderUpdate
from easypost.errors import EasyPostError

from app.services import auth_service, order_service, shipping_service
from app.services.webhook_service import (
    EVENT_ORDER_CANCELLED,
    EVENT_ORDER_CREATED,
    EVENT_ORDER_LABEL_PURCHASED,
    EVENT_ORDER_STATUS_CHANGED,
    EVENT_ORDER_UPDATED,
    send_webhook,
)

from app.models.picking import PickItem, PickingList, PickingListStatus

router = APIRouter(prefix="/orders", tags=["Orders"])

ORDER_CSV_COLUMNS = [
    "order_name", "shop_name", "customer_name", "customer_email", "customer_phone",
    "ship_to_name", "ship_to_street1", "ship_to_street2",
    "ship_to_city", "ship_to_state", "ship_to_zip", "ship_to_country",
    "carrier", "service",
    "sku", "name", "item_name", "quantity", "notes",
    "shipping_cost", "tracking_number", "tracking_url", "easypost_shipment_id", "label_url",
]

EXPORT_CSV_COLUMNS = [
    "order_number", "order_name", "status", "shop_name",
    "customer_name", "customer_email", "customer_phone",
    "ship_to_name", "ship_to_street1", "ship_to_street2",
    "ship_to_city", "ship_to_state", "ship_to_zip", "ship_to_country",
    "carrier", "service",
    "sku", "variant_sku", "name", "item_name", "quantity", "unit_price",
    "processing_fee", "shipping_cost", "total_price",
    "tracking_number", "tracking_url", "easypost_shipment_id", "label_url",
    "notes", "created_at",
]


def _fire_webhook(order, event_type=EVENT_ORDER_UPDATED):
    """Run async webhook in background."""
    asyncio.run(send_webhook(order, event_type=event_type))


def _enrich_order(order, db: Session) -> dict:
    """Add picking_list_id/picking_number to order output."""
    data = OrderOut.model_validate(order).model_dump()
    pick_item = (
        db.query(PickItem)
        .join(PickingList)
        .filter(
            PickItem.order_id == order.id,
            PickingList.status.in_([PickingListStatus.ACTIVE, PickingListStatus.PROCESSING]),
        )
        .first()
    )
    if pick_item:
        pl = db.query(PickingList).filter(PickingList.id == pick_item.picking_list_id).first()
        if pl:
            data["picking_list_id"] = pl.id
            data["picking_number"] = pl.picking_number
    return data


@router.post("", response_model=OrderOut, status_code=201)
def create_order(data: OrderCreate, request: Request, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        order = order_service.create_order(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    auth_service.log_activity(db, user.id, user.username, "create_order", detail=f"Order {order.order_number}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order, EVENT_ORDER_CREATED)
    return order


@router.get("")
def list_orders(skip: int = 0, limit: int = 50, status: str | None = None, search: str | None = None, sku: str | None = None, priority: str | None = None, db: Session = Depends(get_db)):
    parsed_priority = OrderPriority(priority) if priority else None
    if status and "," in status:
        statuses_list = [OrderStatus(s.strip()) for s in status.split(",") if s.strip()]
        result = order_service.list_orders(db, skip=skip, limit=limit, statuses=statuses_list, search=search, sku=sku, priority=parsed_priority)
    else:
        single_status = OrderStatus(status) if status else None
        result = order_service.list_orders(db, skip=skip, limit=limit, status=single_status, search=search, sku=sku, priority=parsed_priority)
    return {
        "total": result["total"],
        "status_counts": result.get("status_counts", {}),
        "orders": [OrderOut.model_validate(o).model_dump() for o in result["orders"]],
    }


@router.get("/skus")
def list_order_skus(status: str | None = None, db: Session = Depends(get_db)):
    """Return distinct variant SKUs from orders, optionally filtered by order status."""
    if status and "," in status:
        statuses_list = [OrderStatus(s.strip()) for s in status.split(",") if s.strip()]
        return order_service.list_order_skus(db, statuses=statuses_list)
    single_status = OrderStatus(status) if status else None
    return order_service.list_order_skus(db, status=single_status)


@router.get("/export")
def export_orders(
    status: str | None = None,
    statuses: str | None = Query(None, description="Comma-separated statuses, e.g. pending,confirmed,processing"),
    search: str | None = None,
    shop_name: str | None = None,
    date_from: str | None = Query(None, description="Start date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """Export orders as CSV with optional filters (status, statuses, search, shop_name, date range).
    Use `statuses` param for multiple statuses: ?statuses=pending,confirmed,processing
    Or use `status` with comma-separated values: ?status=pending,confirmed,processing
    """
    # Parse multiple statuses from either param
    parsed_statuses = None
    valid_values = {s.value for s in OrderStatus}
    if statuses:
        raw_list = [s.strip() for s in statuses.split(",") if s.strip()]
        invalid = [s for s in raw_list if s not in valid_values]
        if invalid:
            raise HTTPException(400, f"Invalid status(es): {', '.join(invalid)}. Valid: {', '.join(valid_values)}")
        parsed_statuses = [OrderStatus(s) for s in raw_list]
    elif status and "," in status:
        raw_list = [s.strip() for s in status.split(",") if s.strip()]
        invalid = [s for s in raw_list if s not in valid_values]
        if invalid:
            raise HTTPException(400, f"Invalid status(es): {', '.join(invalid)}. Valid: {', '.join(valid_values)}")
        parsed_statuses = [OrderStatus(s) for s in raw_list]

    single_status = OrderStatus(status) if status and "," not in status else None
    orders = order_service.list_orders(db, skip=0, limit=0, status=single_status, search=search, statuses=parsed_statuses)["orders"]

    # Additional filters
    if shop_name:
        shop_lower = shop_name.strip().lower()
        orders = [o for o in orders if o.shop_name.lower() == shop_lower]
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            orders = [o for o in orders if o.created_at >= dt_from]
        except ValueError:
            raise HTTPException(400, "date_from must be YYYY-MM-DD")
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            orders = [o for o in orders if o.created_at <= dt_to]
        except ValueError:
            raise HTTPException(400, "date_to must be YYYY-MM-DD")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_CSV_COLUMNS)

    for order in orders:
        if not order.items:
            # Order with no items (shouldn't happen, but handle gracefully)
            writer.writerow([
                order.order_number, order.order_name, order.status, order.shop_name,
                order.customer_name, order.customer_email, order.customer_phone,
                order.ship_to_name, order.ship_to_street1, order.ship_to_street2,
                order.ship_to_city, order.ship_to_state, order.ship_to_zip, order.ship_to_country,
                order.carrier, order.service,
                "", "", "", "", "", "",
                order.processing_fee, order.shipping_cost, order.total_price,
                order.tracking_number, order.tracking_url, order.easypost_shipment_id, order.label_url,
                order.notes, order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
            ])
        else:
            for i, item in enumerate(order.items):
                writer.writerow([
                    order.order_number if i == 0 else "",
                    order.order_name if i == 0 else "",
                    order.status if i == 0 else "",
                    order.shop_name if i == 0 else "",
                    order.customer_name if i == 0 else "",
                    order.customer_email if i == 0 else "",
                    order.customer_phone if i == 0 else "",
                    order.ship_to_name if i == 0 else "",
                    order.ship_to_street1 if i == 0 else "",
                    order.ship_to_street2 if i == 0 else "",
                    order.ship_to_city if i == 0 else "",
                    order.ship_to_state if i == 0 else "",
                    order.ship_to_zip if i == 0 else "",
                    order.ship_to_country if i == 0 else "",
                    order.carrier if i == 0 else "",
                    order.service if i == 0 else "",
                    item.sku, item.variant_sku, item.name, item.product_name, item.quantity, item.unit_price,
                    order.processing_fee if i == 0 else "",
                    order.shipping_cost if i == 0 else "",
                    order.total_price if i == 0 else "",
                    order.tracking_number if i == 0 else "",
                    order.tracking_url if i == 0 else "",
                    order.easypost_shipment_id if i == 0 else "",
                    order.label_url if i == 0 else "",
                    order.notes if i == 0 else "",
                    order.created_at.strftime("%Y-%m-%d %H:%M:%S") if i == 0 and order.created_at else "",
                ])

    buf.seek(0)
    filename = "orders_export"
    if parsed_statuses:
        filename += "_" + "_".join(s.value for s in parsed_statuses)
    elif status:
        filename += f"_{status.value}"
    if shop_name:
        filename += f"_{shop_name.strip()}"
    filename += ".csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/import-template")
def download_order_import_template():
    """Download CSV template for order import. Use variant_sku or product sku in the sku column."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(ORDER_CSV_COLUMNS)
    # Order 1: single item, no shipping info yet
    writer.writerow([
        "Don hang A", "Shop ABC", "Nguyen Van A", "a@email.com", "0901234567",
        "Nguyen Van A", "123 Le Loi", "", "Ho Chi Minh", "HCM", "70000", "US",
        "", "",
        "SP-001", "Ten item A", "San pham A", "2", "Giao buoi sang",
        "", "", "", "", "",
    ])
    # Order 2: multiple items with full shipping info
    writer.writerow([
        "Don hang B", "Shop XYZ", "Tran Thi B", "b@email.com", "0912345678",
        "Tran Thi B", "456 Hai Ba Trung", "Phong 302", "Ha Noi", "HN", "10000", "US",
        "UPS", "Ground",
        "SP-002-RED-M", "Ten item B", "San pham B - Red M", "1", "Can boc qua",
        "8.50", "1Z999AA10123456784", "https://track.ups.com/1Z999AA10123456784", "shp_abc123", "https://labels.example.com/label.pdf",
    ])
    # Order 2: additional item row - only needs sku + quantity (same order_name)
    writer.writerow([
        "Don hang B", "", "", "", "",
        "", "", "", "", "", "", "",
        "", "",
        "SP-003", "Ten item C", "San pham C", "3", "",
        "", "", "", "", "",
    ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=order_import_template.csv"},
    )


@router.post("/import")
def import_orders(file: UploadFile, status: str = Form(""), db: Session = Depends(get_db)):
    """Import orders from CSV. The sku column accepts variant_sku or product sku.
    Optional status form field sets initial order status (default: confirmed)."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    try:
        content = file.file.read().decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(400, f"Cannot read CSV file: {e}")
    reader = csv.DictReader(io.StringIO(content))

    # Validate status override
    import_status = status.strip() if status else ""
    if import_status:
        valid_statuses = [s.value for s in OrderStatus]
        if import_status not in valid_statuses:
            raise HTTPException(400, f"Invalid status '{import_status}'. Valid: {', '.join(valid_statuses)}")

    # Group rows by order key (order_name or auto-generated)
    order_groups: dict[str, dict] = {}
    group_order: list[str] = []  # preserve insertion order
    errors = []
    auto_order_counter = 0

    for row_num, row in enumerate(reader, start=2):
        order_name = (row.get("order_name") or "").strip()
        shop_name = (row.get("shop_name") or "").strip()
        customer_name = (row.get("customer_name") or "").strip()
        ship_to_name = (row.get("ship_to_name") or "").strip()
        sku = (row.get("sku") or "").strip()

        if not sku:
            errors.append({"row": row_num, "order_name": order_name or "(no name)", "error": "SKU is required"})
            continue

        try:
            quantity = int(row.get("quantity") or 1)
        except (ValueError, TypeError):
            errors.append({"row": row_num, "order_name": order_name or "(no name)", "error": f"Invalid quantity '{row.get('quantity')}'"})
            continue
        if quantity < 1:
            quantity = 1

        # Auto-generate order_name if empty (each row without order_name = new order)
        if not order_name:
            auto_order_counter += 1
            order_name = f"__auto_{auto_order_counter}_row{row_num}"

        # customer_name & ship_to_name default to each other
        if not customer_name and ship_to_name:
            customer_name = ship_to_name
        if not ship_to_name and customer_name:
            ship_to_name = customer_name

        if order_name not in order_groups:
            if not customer_name:
                errors.append({"row": row_num, "order_name": order_name or "(no name)", "sku": sku, "error": "customer_name or ship_to_name is required"})
                continue

            # Parse shipping_cost (float, default 0)
            raw_shipping_cost = (row.get("shipping_cost") or "").strip()
            try:
                parsed_shipping_cost = float(raw_shipping_cost) if raw_shipping_cost else 0.0
            except ValueError:
                parsed_shipping_cost = 0.0

            order_groups[order_name] = {
                "customer_name": customer_name,
                "shop_name": shop_name,
                "customer_email": (row.get("customer_email") or "").strip(),
                "customer_phone": (row.get("customer_phone") or "").strip(),
                "ship_to_name": ship_to_name or customer_name,
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
                "shipping_cost": parsed_shipping_cost,
                "tracking_number": (row.get("tracking_number") or "").strip(),
                "tracking_url": (row.get("tracking_url") or "").strip(),
                "easypost_shipment_id": (row.get("easypost_shipment_id") or "").strip(),
                "label_url": (row.get("label_url") or "").strip(),
                "items": [],
            }
            group_order.append(order_name)

        item_name = (row.get("item_name") or "").strip()
        item_display_name = (row.get("name") or "").strip()

        order_groups[order_name]["items"].append({
            "sku": sku,
            "name": item_display_name,
            "item_name": item_name,
            "quantity": quantity,
            "row": row_num,
        })
        # Append notes from additional rows
        extra_notes = (row.get("notes") or "").strip()
        if extra_notes and order_name in order_groups:
            existing_notes = order_groups[order_name]["notes"]
            if existing_notes and extra_notes not in existing_notes:
                order_groups[order_name]["notes"] = existing_notes + "; " + extra_notes
            elif not existing_notes:
                order_groups[order_name]["notes"] = extra_notes

    # Process each order group
    from app.models.order import Order
    from app.services import product_service

    # Pre-check duplicate order_names against DB
    display_names = [order_groups[k]["display_order_name"] for k in group_order if order_groups[k]["display_order_name"]]
    if display_names:
        existing_orders = db.query(Order.order_name).filter(Order.order_name.in_(display_names)).all()
        existing_names = {o.order_name for o in existing_orders}
        for dup_name in existing_names:
            errors.append({"order_name": dup_name, "error": f"Order name '{dup_name}' already exists in database"})
        # Remove duplicates from processing
        group_order = [k for k in group_order if order_groups[k]["display_order_name"] not in existing_names]

    created = 0
    created_details = []
    for order_name in group_order:
        group = order_groups[order_name]

        # Resolve SKUs to product_id / variant_id
        resolved_items = []
        has_error = False
        for item in group["items"]:
            sku_val = item["sku"]
            csv_item_name = item["item_name"]
            csv_name = item["name"]
            row_num = item["row"]

            # Try variant_sku first
            variant = product_service.get_variant_by_sku(db, sku_val)
            if variant:
                product = product_service.get_product(db, variant.product_id)
                resolved_name = csv_item_name or f"{product.name} ({variant.variant_sku})"
                resolved_items.append({
                    "product_id": variant.product_id,
                    "variant_id": variant.id,
                    "quantity": item["quantity"],
                    "resolved_name": resolved_name,
                    "item_name": csv_item_name,
                    "name": csv_name,
                    "sku": sku_val,
                })
                continue

            # Try product sku
            product = product_service.get_product_by_sku(db, sku_val)
            if product:
                # If product has variants, user must specify variant_sku
                if product.variants and len(product.variants) > 0:
                    variant_skus = ", ".join(v.variant_sku for v in product.variants[:5])
                    more = f" ... (+{len(product.variants)-5})" if len(product.variants) > 5 else ""
                    errors.append({
                        "row": row_num,
                        "order_name": group.get("display_order_name") or order_name,
                        "sku": sku_val,
                        "error": f"Product '{sku_val}' has variants. Please use variant_sku instead. Available: {variant_skus}{more}",
                    })
                    has_error = True
                    break
                resolved_items.append({
                    "product_id": product.id,
                    "variant_id": "",
                    "quantity": item["quantity"],
                    "resolved_name": csv_item_name or product.name,
                    "item_name": csv_item_name,
                    "name": csv_name,
                    "sku": sku_val,
                })
                continue

            errors.append({"row": row_num, "order_name": group.get("display_order_name") or order_name, "sku": sku_val, "error": f"SKU '{sku_val}' not found"})
            has_error = True
            break

        if has_error or not resolved_items:
            continue

        # Build OrderCreate
        from app.schemas.order import AddressInput, OrderCreate, OrderItemCreate

        display_name = group["display_order_name"]
        order_data = OrderCreate(
            order_name=display_name,
            customer_name=group["customer_name"],
            shop_name=group["shop_name"],
            customer_email=group["customer_email"],
            customer_phone=group["customer_phone"],
            ship_to=AddressInput(
                name=group["ship_to_name"] or group["customer_name"],
                street1=group["ship_to_street1"],
                street2=group["ship_to_street2"],
                city=group["ship_to_city"],
                state=group["ship_to_state"],
                zip=group["ship_to_zip"],
                country=group["ship_to_country"],
            ),
            items=[
                OrderItemCreate(
                    product_id=ri["product_id"],
                    variant_id=ri["variant_id"],
                    quantity=ri["quantity"],
                    name=ri["name"],
                    item_name=ri["item_name"],
                )
                for ri in resolved_items
            ],
            carrier=group["carrier"],
            service=group["service"],
            notes=group["notes"],
            status=import_status or None,
        )

        try:
            order = order_service.create_order(db, order_data)

            # Apply shipping info from CSV if provided
            shipping_cost = group.get("shipping_cost", 0.0)
            tracking_number = group.get("tracking_number", "")
            tracking_url = group.get("tracking_url", "")
            easypost_shipment_id = group.get("easypost_shipment_id", "")
            label_url = group.get("label_url", "")

            if shipping_cost or tracking_number or easypost_shipment_id or label_url:
                if shipping_cost:
                    order.shipping_cost = shipping_cost
                    order.total_price = order.total_price + shipping_cost
                if tracking_number:
                    order.tracking_number = tracking_number
                if tracking_url:
                    order.tracking_url = tracking_url
                if easypost_shipment_id:
                    order.easypost_shipment_id = easypost_shipment_id
                if label_url:
                    order.label_url = label_url
                db.commit()
                db.refresh(order)

            created += 1
            created_details.append({
                "order_name": display_name or order_name,
                "items": [
                    {"sku": ri["sku"], "item_name": ri["resolved_name"], "quantity": ri["quantity"]}
                    for ri in resolved_items
                ],
            })
        except ValueError as e:
            skus = ", ".join(ri["sku"] for ri in resolved_items)
            errors.append({"order_name": display_name or order_name, "sku": skus, "error": str(e)})

    return {"created": created, "created_details": created_details, "errors": errors}


LABEL_PURCHASED_CSV_COLUMNS = [
    "order_name", "customer_name", "ship_to_name",
    "ship_to_street1", "ship_to_street2", "ship_to_city", "ship_to_state", "ship_to_zip", "ship_to_country",
    "carrier", "service",
    "sku", "name", "item_name", "quantity",
    "tracking_number", "label_url", "shipping_cost", "notes",
]


@router.get("/import-label-purchased-template")
def download_label_purchased_template():
    """Download CSV template for importing orders with label already purchased."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LABEL_PURCHASED_CSV_COLUMNS)
    writer.writerow([
        "Order A", "Nguyen Van A", "Nguyen Van A",
        "123 Le Loi", "", "Ho Chi Minh", "HCM", "70000", "US",
        "USPS", "GroundAdvantage",
        "SP-001", "San pham A", "2",
        "9400111899223100001", "https://labels.example.com/label1.pdf", "5.50", "",
    ])
    writer.writerow([
        "Order B", "Nguyen Van A", "Tran Thi B",
        "456 Hai Ba Trung", "Phong 302", "Ha Noi", "HN", "10000", "US",
        "UPS", "Ground",
        "SP-002-RED-M", "San pham B", "1",
        "1Z999AA10123456784", "https://labels.example.com/label2.pdf", "8.50", "Fragile",
    ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=import_label_purchased_template.csv"},
    )


@router.post("/import-label-purchased")
def import_label_purchased(
    file: UploadFile,
    customer_id: str = Form(""),
    db: Session = Depends(get_db),
):
    """Import orders with label already purchased for a specific customer.
    All imported orders get status=label_purchased and are linked to the customer."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    # Validate customer
    from app.models.customer import Customer
    customer = None
    if customer_id:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(400, f"Customer not found: {customer_id}")

    try:
        content = file.file.read().decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(400, f"Cannot read CSV file: {e}")
    reader = csv.DictReader(io.StringIO(content))

    order_groups: dict[str, dict] = {}
    group_order: list[str] = []
    errors = []
    auto_counter = 0

    for row_num, row in enumerate(reader, start=2):
        order_name = (row.get("order_name") or "").strip()
        customer_name = (row.get("customer_name") or "").strip()
        ship_to_name = (row.get("ship_to_name") or "").strip()
        sku = (row.get("sku") or "").strip()
        tracking_number = (row.get("tracking_number") or "").strip()

        if not sku:
            errors.append({"row": row_num, "order_name": order_name or "(no name)", "error": "SKU is required"})
            continue

        if not tracking_number and order_name not in order_groups:
            errors.append({"row": row_num, "order_name": order_name or "(no name)", "error": "tracking_number is required for label_purchased orders"})
            continue

        try:
            quantity = int(row.get("quantity") or 1)
        except (ValueError, TypeError):
            errors.append({"row": row_num, "order_name": order_name or "(no name)", "error": f"Invalid quantity '{row.get('quantity')}'"})
            continue
        if quantity < 1:
            quantity = 1

        if not order_name:
            auto_counter += 1
            order_name = f"__auto_{auto_counter}_row{row_num}"

        # Use customer name from DB if available, fallback to CSV
        effective_customer_name = customer.name if customer else customer_name
        if not effective_customer_name and ship_to_name:
            effective_customer_name = ship_to_name
        if not ship_to_name and effective_customer_name:
            ship_to_name = effective_customer_name

        if order_name not in order_groups:
            if not effective_customer_name:
                errors.append({"row": row_num, "order_name": order_name or "(no name)", "error": "customer_name or ship_to_name is required"})
                continue

            raw_cost = (row.get("shipping_cost") or "").strip()
            try:
                shipping_cost = float(raw_cost) if raw_cost else 0.0
            except ValueError:
                shipping_cost = 0.0

            order_groups[order_name] = {
                "customer_name": effective_customer_name,
                "ship_to_name": ship_to_name or effective_customer_name,
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
                "shipping_cost": shipping_cost,
                "tracking_number": tracking_number,
                "label_url": (row.get("label_url") or "").strip(),
                "items": [],
            }
            group_order.append(order_name)

        item_name = (row.get("item_name") or "").strip()
        item_display_name = (row.get("name") or "").strip()
        order_groups[order_name]["items"].append({
            "sku": sku,
            "name": item_display_name,
            "item_name": item_name,
            "quantity": quantity,
            "row": row_num,
        })

    # Process each order group
    from app.models.order import Order
    from app.services import product_service

    # Pre-check duplicate order_names
    display_names = [order_groups[k]["display_order_name"] for k in group_order if order_groups[k]["display_order_name"]]
    if display_names:
        existing = db.query(Order.order_name).filter(Order.order_name.in_(display_names)).all()
        existing_names = {o.order_name for o in existing}
        for dup in existing_names:
            errors.append({"order_name": dup, "error": f"Order name '{dup}' already exists"})
        group_order = [k for k in group_order if order_groups[k]["display_order_name"] not in existing_names]

    created = 0
    created_details = []

    for order_name in group_order:
        group = order_groups[order_name]

        # Resolve SKUs
        resolved_items = []
        has_error = False
        for item in group["items"]:
            sku_val = item["sku"]
            row_num = item["row"]

            variant = product_service.get_variant_by_sku(db, sku_val)
            if variant:
                product = product_service.get_product(db, variant.product_id)
                resolved_items.append({
                    "product_id": variant.product_id,
                    "variant_id": variant.id,
                    "quantity": item["quantity"],
                    "resolved_name": item["item_name"] or f"{product.name} ({variant.variant_sku})",
                    "item_name": item["item_name"],
                    "name": item.get("name", ""),
                    "sku": sku_val,
                })
                continue

            product = product_service.get_product_by_sku(db, sku_val)
            if product:
                if product.variants and len(product.variants) > 0:
                    variant_skus = ", ".join(v.variant_sku for v in product.variants[:5])
                    more = f" ... (+{len(product.variants)-5})" if len(product.variants) > 5 else ""
                    errors.append({"row": row_num, "order_name": group["display_order_name"] or order_name, "sku": sku_val, "error": f"Product has variants, use variant_sku: {variant_skus}{more}"})
                    has_error = True
                    break
                resolved_items.append({
                    "product_id": product.id,
                    "variant_id": "",
                    "quantity": item["quantity"],
                    "resolved_name": item["item_name"] or product.name,
                    "item_name": item["item_name"],
                    "name": item.get("name", ""),
                    "sku": sku_val,
                })
                continue

            errors.append({"row": row_num, "order_name": group["display_order_name"] or order_name, "sku": sku_val, "error": f"SKU '{sku_val}' not found"})
            has_error = True
            break

        if has_error or not resolved_items:
            continue

        from app.schemas.order import AddressInput, OrderCreate, OrderItemCreate

        display_name = group["display_order_name"]
        order_data = OrderCreate(
            order_name=display_name,
            customer_name=group["customer_name"],
            shop_name="",
            customer_email="",
            customer_phone="",
            ship_to=AddressInput(
                name=group["ship_to_name"] or group["customer_name"],
                street1=group["ship_to_street1"],
                street2=group["ship_to_street2"],
                city=group["ship_to_city"],
                state=group["ship_to_state"],
                zip=group["ship_to_zip"],
                country=group["ship_to_country"],
            ),
            items=[
                OrderItemCreate(
                    product_id=ri["product_id"],
                    variant_id=ri["variant_id"],
                    quantity=ri["quantity"],
                    name=ri.get("name", ""),
                    item_name=ri["item_name"],
                )
                for ri in resolved_items
            ],
            carrier=group["carrier"],
            service=group["service"],
            notes=group["notes"],
            status="label_purchased",
        )

        try:
            order = order_service.create_order(db, order_data)
            # Set label/tracking info
            order.tracking_number = group["tracking_number"]
            order.label_url = group["label_url"]
            if group["shipping_cost"]:
                order.shipping_cost = group["shipping_cost"]
                order.total_price = order.total_price + group["shipping_cost"]
            if customer:
                order.customer_id = customer.id
            db.commit()
            db.refresh(order)

            created += 1
            created_details.append({
                "order_name": display_name or order_name,
                "tracking_number": group["tracking_number"],
                "items": [
                    {"sku": ri["sku"], "item_name": ri["resolved_name"], "quantity": ri["quantity"]}
                    for ri in resolved_items
                ],
            })
        except ValueError as e:
            skus = ", ".join(ri["sku"] for ri in resolved_items)
            errors.append({"order_name": display_name or order_name, "sku": skus, "error": str(e)})

    return {"created": created, "created_details": created_details, "errors": errors}


@router.get("/update-names-template")
def download_update_names_template(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """Download CSV template for updating item names. Optionally filter by order status."""
    from app.models.order import Order, OrderItem
    query = db.query(Order)
    if status:
        if "," in status:
            query = query.filter(Order.status.in_([s.strip() for s in status.split(",")]))
        else:
            query = query.filter(Order.status == status)
    orders = query.order_by(Order.created_at.desc()).limit(500).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["order_number", "order_name", "sku", "variant_sku", "product_name", "name"])
    for o in orders:
        for item in o.items:
            writer.writerow([
                o.order_number,
                o.order_name or "",
                item.sku,
                item.variant_sku or "",
                item.product_name or "",
                item.name or "",
            ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=update_item_names.csv"},
    )


@router.post("/update-names")
def update_item_names(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update item names from CSV. CSV must have columns: order_number, sku, name."""
    from app.models.order import Order, OrderItem

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    try:
        content = file.file.read().decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(400, f"Cannot read CSV: {e}")

    reader = csv.DictReader(io.StringIO(content))
    updated = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):
        order_number = (row.get("order_number") or "").strip()
        sku = (row.get("sku") or "").strip()
        name = (row.get("name") or "").strip()

        if not order_number or not sku:
            continue
        if not name:
            continue

        order = db.query(Order).filter(Order.order_number == order_number).first()
        if not order:
            errors.append({"row": row_num, "error": f"Order '{order_number}' not found"})
            continue

        matched = False
        for item in order.items:
            if item.sku == sku or item.variant_sku == sku:
                item.name = name
                matched = True
                updated += 1
                break

        if not matched:
            errors.append({"row": row_num, "error": f"SKU '{sku}' not found in order '{order_number}'"})

    db.commit()
    return {"updated": updated, "errors": errors}


@router.post("/merge-by-name")
def merge_orders_by_name(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Merge all orders that share the same order_name into a single order per name."""
    result = order_service.merge_orders_by_name(db)
    if result["merged"] > 0:
        auth_service.log_activity(db, user.id, user.username, "merge_orders", detail=f"Merged {result['merged']} groups", ip=request.client.host if request.client else "")
    return result


@router.get("/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return _enrich_order(order, db)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: str,
    data: OrderUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update order fields (name, customer info, address, items name/quantity)."""
    try:
        order = order_service.update_order(db, order_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not order:
        raise HTTPException(404, "Order not found")
    auth_service.log_activity(db, user.id, user.username, "update_order", detail=order.order_number, ip=request.client.host if request.client else "")
    return _enrich_order(order, db)


@router.get("/by-number/{order_number}")
def get_order_by_number(order_number: str, db: Session = Depends(get_db)):
    order = order_service.get_order_by_number(db, order_number)
    if not order:
        raise HTTPException(404, "Order not found")
    return _enrich_order(order, db)


@router.get("/by-tracking/{tracking_number}")
def get_order_by_tracking(tracking_number: str, db: Session = Depends(get_db)):
    order = order_service.get_order_by_tracking(db, tracking_number)
    if not order:
        raise HTTPException(404, "Order not found")
    return _enrich_order(order, db)


@router.patch("/{order_id}/status", response_model=OrderOut)
def update_status(
    order_id: str,
    data: OrderStatusUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.status == OrderStatus.PENDING and user.role == "staff":
        raise HTTPException(403, "Staff cannot set orders to pending")
    order = order_service.update_order_status(db, order_id, data)
    if not order:
        raise HTTPException(404, "Order not found")

    # Check if batch should transition to done (all orders drop_off/shipped/on_hold)
    if data.status in (OrderStatus.DROP_OFF, OrderStatus.ON_HOLD):
        from app.services.picking_service import check_batch_done
        check_batch_done(db, order_id)

    auth_service.log_activity(db, user.id, user.username, "update_order_status", detail=f"{order.order_number} → {data.status}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order, EVENT_ORDER_STATUS_CHANGED)
    return order


@router.post("/{order_id}/reprocess", response_model=OrderOut)
def reprocess_order(
    order_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-process a drop_off order. In-batch orders go back to processing; others go to confirmed/label_purchased."""
    try:
        order = order_service.reprocess_order(db, order_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not order:
        raise HTTPException(404, "Order not found")
    auth_service.log_activity(db, user.id, user.username, "reprocess_order", detail=f"{order.order_number} → {order.status}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order, EVENT_ORDER_STATUS_CHANGED)
    return order


@router.post("/{order_id}/open", response_model=OrderOut)
def open_order(
    order_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Open a pending/cancelled order. In-batch → processing, has tracking → label_purchased, otherwise → confirmed."""
    if user.role == "staff":
        raise HTTPException(403, "Staff cannot open pending orders")
    try:
        order = order_service.open_order(db, order_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not order:
        raise HTTPException(404, "Order not found")
    auth_service.log_activity(db, user.id, user.username, "open_order", detail=f"{order.order_number} → {order.status}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order, EVENT_ORDER_STATUS_CHANGED)
    return order


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: str, request: Request, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        order = order_service.cancel_order(db, order_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not order:
        raise HTTPException(404, "Order not found")
    auth_service.log_activity(db, user.id, user.username, "cancel_order", detail=order.order_number, ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order, EVENT_ORDER_CANCELLED)
    return order


@router.delete("/{order_id}", status_code=204)
def delete_order(order_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Permanently delete an order. Admin only."""
    if user.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    order_number = order.order_number
    if not order_service.delete_order(db, order_id):
        raise HTTPException(500, "Failed to delete order")
    auth_service.log_activity(db, user.id, user.username, "delete_order", detail=order_number, ip=request.client.host if request.client else "")


@router.get("/{order_id}/parcel-info")
def parcel_info(order_id: str, db: Session = Depends(get_db)):
    try:
        info = shipping_service.get_parcel_info(order_id, db)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return info


@router.patch("/{order_id}/address", response_model=OrderOut)
def update_address(
    order_id: str,
    data: AddressUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update shipping address. Only allowed before label is purchased."""
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.label_url or order.easypost_shipment_id:
        raise HTTPException(400, "Cannot change address after label is purchased. Cancel and re-create the order.")

    if data.name is not None:
        order.ship_to_name = data.name
    if data.street1 is not None:
        order.ship_to_street1 = data.street1
    if data.street2 is not None:
        order.ship_to_street2 = data.street2
    if data.city is not None:
        order.ship_to_city = data.city
    if data.state is not None:
        order.ship_to_state = data.state
    if data.zip is not None:
        order.ship_to_zip = data.zip
    if data.country is not None:
        order.ship_to_country = data.country

    db.commit()
    db.refresh(order)
    auth_service.log_activity(db, user.id, user.username, "update_address", detail=order.order_number, ip=request.client.host if request.client else "")
    return order


@router.post("/{order_id}/buy-label", response_model=OrderOut)
def buy_label(
    order_id: str,
    data: BuyLabelRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    parcel_override = None
    if data.weight_oz > 0:
        parcel_override = {"weight": data.weight_oz}
        if data.length_in > 0 and data.width_in > 0 and data.height_in > 0:
            parcel_override["length"] = data.length_in
            parcel_override["width"] = data.width_in
            parcel_override["height"] = data.height_in
    try:
        order = shipping_service.buy_label(db, order_id, carrier=data.carrier, service=data.service,
                                           parcel_override=parcel_override)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except EasyPostError as e:
        raise HTTPException(400, f"Shipping API error: {e}")
    auth_service.log_activity(db, user.id, user.username, "buy_label", detail=f"{order.order_number} {data.carrier} {data.service}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order, EVENT_ORDER_LABEL_PURCHASED)
    return order


@router.post("/{order_id}/rebuy-label", response_model=OrderOut)
def rebuy_label(
    order_id: str,
    data: BuyLabelRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-buy label: refund existing label and purchase a new one. Admin only."""
    if user.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    parcel_override = None
    if data.weight_oz > 0:
        parcel_override = {"weight": data.weight_oz}
        if data.length_in > 0 and data.width_in > 0 and data.height_in > 0:
            parcel_override["length"] = data.length_in
            parcel_override["width"] = data.width_in
            parcel_override["height"] = data.height_in
    try:
        order = shipping_service.rebuy_label(db, order_id, carrier=data.carrier, service=data.service,
                                              parcel_override=parcel_override)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except EasyPostError as e:
        raise HTTPException(400, f"Shipping API error: {e}")
    auth_service.log_activity(db, user.id, user.username, "rebuy_label", detail=f"{order.order_number} {data.carrier} {data.service}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order, EVENT_ORDER_LABEL_PURCHASED)
    return order


@router.get("/{order_id}/rates")
def get_rates(order_id: str, weight_oz: float = 0, length_in: float = 0,
              width_in: float = 0, height_in: float = 0, db: Session = Depends(get_db)):
    parcel_override = None
    if weight_oz > 0:
        parcel_override = {"weight": weight_oz}
        if length_in > 0 and width_in > 0 and height_in > 0:
            parcel_override["length"] = length_in
            parcel_override["width"] = width_in
            parcel_override["height"] = height_in
    try:
        rates = shipping_service.get_rates(order_id, db, parcel_override=parcel_override)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except EasyPostError as e:
        raise HTTPException(400, f"Shipping API error: {e}")
    return {"rates": rates}


@router.get("/{order_id}/price-breakdown")
def price_breakdown(order_id: str, db: Session = Depends(get_db)):
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    items_detail = []
    for item in order.items:
        items_detail.append({
            "sku": item.sku,
            "product_name": item.product_name,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "subtotal": round(item.quantity * item.unit_price, 2),
        })
    total_items = sum(i.quantity for i in order.items)
    return {
        "order_number": order.order_number,
        "items": items_detail,
        "items_subtotal": round(sum(i.quantity * i.unit_price for i in order.items), 2),
        "processing_fee": order.processing_fee,
        "processing_fee_detail": f"{total_items} items x $0.50",
        "shipping_cost": order.shipping_cost,
        "total_price": order.total_price,
    }


@router.get("/{order_id}/qrcode")
def get_order_qrcode(order_id: str, db: Session = Depends(get_db)):
    """Get QR code label for an order (for picking/packing)."""
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    from app.services.qr_service import generate_order_qr
    img_bytes = generate_order_qr(order)
    return Response(content=img_bytes, media_type="image/png")
