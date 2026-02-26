import asyncio
import csv
import io

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.order import OrderStatus
from app.models.user import User
from app.schemas.order import BuyLabelRequest, OrderCreate, OrderOut, OrderStatusUpdate
from app.services import auth_service, order_service, shipping_service
from app.services.webhook_service import send_webhook

router = APIRouter(prefix="/orders", tags=["Orders"])

ORDER_CSV_COLUMNS = [
    "order_name", "customer_name", "customer_email", "customer_phone",
    "ship_to_name", "ship_to_street1", "ship_to_street2",
    "ship_to_city", "ship_to_state", "ship_to_zip", "ship_to_country",
    "carrier", "service",
    "sku", "item_name", "quantity", "notes",
]


def _fire_webhook(order):
    """Run async webhook in background."""
    asyncio.run(send_webhook(order))


@router.post("", response_model=OrderOut, status_code=201)
def create_order(data: OrderCreate, request: Request, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        order = order_service.create_order(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    auth_service.log_activity(db, user.id, user.username, "create_order", detail=f"Order {order.order_number}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order)
    return order


@router.get("", response_model=list[OrderOut])
def list_orders(skip: int = 0, limit: int = 100, status: OrderStatus | None = None, db: Session = Depends(get_db)):
    return order_service.list_orders(db, skip=skip, limit=limit, status=status)


@router.get("/import-template")
def download_order_import_template():
    """Download CSV template for order import. Use variant_sku or product sku in the sku column."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(ORDER_CSV_COLUMNS)
    # Order 1: single item, USPS GroundAdvantage (default)
    writer.writerow([
        "Don hang A", "Nguyen Van A", "a@email.com", "0901234567",
        "Nguyen Van A", "123 Le Loi", "", "Ho Chi Minh", "HCM", "70000", "US",
        "", "",
        "SP-001", "San pham A", "2", "Giao buoi sang",
    ])
    # Order 2: multiple items, UPS Ground
    writer.writerow([
        "Don hang B", "Tran Thi B", "b@email.com", "0912345678",
        "Tran Thi B", "456 Hai Ba Trung", "Phong 302", "Ha Noi", "HN", "10000", "US",
        "UPS", "Ground",
        "SP-002-RED-M", "San pham B - Red M", "1", "Can boc qua",
    ])
    # Order 2: additional item row - only needs sku + quantity (same order_name)
    writer.writerow([
        "Don hang B", "", "", "",
        "", "", "", "", "", "", "",
        "", "",
        "SP-003", "San pham C", "3", "",
    ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=order_import_template.csv"},
    )


@router.post("/import")
def import_orders(file: UploadFile, db: Session = Depends(get_db)):
    """Import orders from CSV. The sku column accepts variant_sku or product sku."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    try:
        content = file.file.read().decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(400, f"Cannot read CSV file: {e}")
    reader = csv.DictReader(io.StringIO(content))

    # Group rows by order key (order_name or auto-generated)
    order_groups: dict[str, dict] = {}
    group_order: list[str] = []  # preserve insertion order
    errors = []
    auto_order_counter = 0

    for row_num, row in enumerate(reader, start=2):
        order_name = (row.get("order_name") or "").strip()
        customer_name = (row.get("customer_name") or "").strip()
        ship_to_name = (row.get("ship_to_name") or "").strip()
        sku = (row.get("sku") or "").strip()

        if not sku:
            errors.append({"row": row_num, "error": "SKU is required"})
            continue

        quantity = int(row.get("quantity") or 1)
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
                errors.append({"row": row_num, "error": "customer_name or ship_to_name is required"})
                continue
            order_groups[order_name] = {
                "customer_name": customer_name,
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
                "items": [],
            }
            group_order.append(order_name)

        item_name = (row.get("item_name") or "").strip()

        order_groups[order_name]["items"].append({
            "sku": sku,
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
                    "sku": sku_val,
                })
                continue

            # Try product sku
            product = product_service.get_product_by_sku(db, sku_val)
            if product:
                # If product has variants, user must specify variant_sku
                if product.variants and len(product.variants) > 0:
                    errors.append({
                        "row": row_num,
                        "sku": sku_val,
                        "error": f"Product '{sku_val}' has variants. Please use variant_sku instead.",
                    })
                    has_error = True
                    break
                resolved_items.append({
                    "product_id": product.id,
                    "variant_id": "",
                    "quantity": item["quantity"],
                    "resolved_name": csv_item_name or product.name,
                    "sku": sku_val,
                })
                continue

            errors.append({"row": row_num, "sku": sku_val, "error": f"SKU '{sku_val}' not found"})
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
            customer_email=group["customer_email"],
            customer_phone=group["customer_phone"],
            ship_to=AddressInput(
                name=group["ship_to_name"] or group["customer_name"],
                street1=group["ship_to_street1"],
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
                )
                for ri in resolved_items
            ],
            carrier=group["carrier"],
            service=group["service"],
            notes=group["notes"],
        )

        try:
            order_service.create_order(db, order_data)
            created += 1
            created_details.append({
                "order_name": display_name or order_name,
                "items": [
                    {"sku": ri["sku"], "item_name": ri["resolved_name"], "quantity": ri["quantity"]}
                    for ri in resolved_items
                ],
            })
        except ValueError as e:
            errors.append({"order_name": order_name, "error": str(e)})

    return {"created": created, "created_details": created_details, "errors": errors}


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.get("/by-number/{order_number}", response_model=OrderOut)
def get_order_by_number(order_number: str, db: Session = Depends(get_db)):
    order = order_service.get_order_by_number(db, order_number)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.patch("/{order_id}/status", response_model=OrderOut)
def update_status(
    order_id: str,
    data: OrderStatusUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = order_service.update_order_status(db, order_id, data)
    if not order:
        raise HTTPException(404, "Order not found")

    # Check if batch should transition to done (all orders drop_off)
    if data.status == OrderStatus.DROP_OFF:
        from app.services.picking_service import check_batch_done
        check_batch_done(db, order_id)

    auth_service.log_activity(db, user.id, user.username, "update_order_status", detail=f"{order.order_number} → {data.status}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order)
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
    background_tasks.add_task(_fire_webhook, order)
    return order


@router.delete("/{order_id}", status_code=204)
def delete_order(order_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Permanently delete an order. Admin only."""
    if user.role != "admin":
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
    auth_service.log_activity(db, user.id, user.username, "buy_label", detail=f"{order.order_number} {data.carrier} {data.service}", ip=request.client.host if request.client else "")
    background_tasks.add_task(_fire_webhook, order)
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
