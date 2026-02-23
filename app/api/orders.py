import asyncio
import csv
import io

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.order import OrderStatus
from app.schemas.order import BuyLabelRequest, OrderCreate, OrderOut, OrderStatusUpdate
from app.services import order_service, shipping_service
from app.services.webhook_service import send_webhook

router = APIRouter(prefix="/orders", tags=["Orders"])

ORDER_CSV_COLUMNS = [
    "order_name", "customer_name", "customer_email", "customer_phone",
    "ship_to_name", "ship_to_street1", "ship_to_street2",
    "ship_to_city", "ship_to_state", "ship_to_zip", "ship_to_country",
    "sku", "item_name", "quantity", "notes",
]


def _fire_webhook(order):
    """Run async webhook in background."""
    asyncio.run(send_webhook(order))


@router.post("", response_model=OrderOut, status_code=201)
def create_order(data: OrderCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        order = order_service.create_order(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
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
    # Order 1: single item using product SKU (no variants)
    writer.writerow([
        "Don hang A", "Nguyen Van A", "a@email.com", "0901234567",
        "Nguyen Van A", "123 Le Loi", "", "Ho Chi Minh", "HCM", "70000", "VN",
        "SP-001", "San pham A", "2", "Giao buoi sang",
    ])
    # Order 2: multiple items - first row has full info
    writer.writerow([
        "Don hang B", "Tran Thi B", "b@email.com", "0912345678",
        "Tran Thi B", "456 Hai Ba Trung", "Phong 302", "Ha Noi", "HN", "10000", "VN",
        "SP-002-RED-M", "San pham B - Red M", "1", "Can boc qua",
    ])
    # Order 2: additional item row - only needs sku + quantity (same order_name)
    writer.writerow([
        "Don hang B", "", "", "",
        "", "", "", "", "", "", "",
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

    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    # Group rows by order_name
    order_groups: dict[str, dict] = {}
    group_order: list[str] = []  # preserve insertion order
    errors = []

    for row_num, row in enumerate(reader, start=2):
        order_name = (row.get("order_name") or "").strip()
        customer_name = (row.get("customer_name") or "").strip()
        sku = (row.get("sku") or "").strip()

        if not sku:
            errors.append({"row": row_num, "error": "SKU is required"})
            continue

        quantity = int(row.get("quantity") or 1)
        if quantity < 1:
            quantity = 1

        if not order_name:
            errors.append({"row": row_num, "error": "order_name is required"})
            continue

        if order_name not in order_groups:
            if not customer_name:
                errors.append({"row": row_num, "error": f"First row of order '{order_name}' must have customer_name"})
                continue
            order_groups[order_name] = {
                "customer_name": customer_name,
                "customer_email": (row.get("customer_email") or "").strip(),
                "customer_phone": (row.get("customer_phone") or "").strip(),
                "ship_to_name": (row.get("ship_to_name") or "").strip(),
                "ship_to_street1": (row.get("ship_to_street1") or "").strip(),
                "ship_to_street2": (row.get("ship_to_street2") or "").strip(),
                "ship_to_city": (row.get("ship_to_city") or "").strip(),
                "ship_to_state": (row.get("ship_to_state") or "").strip(),
                "ship_to_zip": (row.get("ship_to_zip") or "").strip(),
                "ship_to_country": (row.get("ship_to_country") or "").strip() or "US",
                "notes": (row.get("notes") or "").strip(),
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
    from app.services import product_service

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

        order_data = OrderCreate(
            order_name=order_name,
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
            notes=group["notes"],
        )

        try:
            order_service.create_order(db, order_data)
            created += 1
            created_details.append({
                "order_name": order_name,
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    order = order_service.update_order_status(db, order_id, data)
    if not order:
        raise HTTPException(404, "Order not found")
    background_tasks.add_task(_fire_webhook, order)
    return order


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        order = order_service.cancel_order(db, order_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not order:
        raise HTTPException(404, "Order not found")
    background_tasks.add_task(_fire_webhook, order)
    return order


@router.post("/{order_id}/buy-label", response_model=OrderOut)
def buy_label(
    order_id: str,
    data: BuyLabelRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        order = shipping_service.buy_label(db, order_id, carrier=data.carrier, service=data.service)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    background_tasks.add_task(_fire_webhook, order)
    return order


@router.get("/{order_id}/rates")
def get_rates(order_id: str, db: Session = Depends(get_db)):
    try:
        rates = shipping_service.get_rates(order_id, db)
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
