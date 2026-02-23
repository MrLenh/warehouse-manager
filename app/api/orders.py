import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.order import OrderStatus
from app.schemas.order import BuyLabelRequest, OrderCreate, OrderOut, OrderStatusUpdate
from app.services import order_service, shipping_service
from app.services.webhook_service import send_webhook

router = APIRouter(prefix="/orders", tags=["Orders"])


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
