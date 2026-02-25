import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.order import Order, OrderStatus
from app.services import order_service
from app.services.order_service import _add_status_history
from app.services.webhook_service import send_webhook_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# EasyPost tracking status → internal order status mapping
_TRACKING_TO_ORDER_STATUS = {
    "in_transit": OrderStatus.IN_TRANSIT,
    "delivered": OrderStatus.DELIVERED,
}


@router.post("/{order_id}/send")
def trigger_webhook(order_id: str, db: Session = Depends(get_db)):
    """Manually trigger webhook for an order."""
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    results = send_webhook_sync(order)
    if not results:
        return {"message": "No webhook URLs configured for this order"}
    return {"results": results}


@router.post("/easypost")
async def easypost_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive EasyPost tracking webhook events.
    Configure this URL in EasyPost dashboard: POST /api/v1/webhooks/easypost

    Handles tracker.created and tracker.updated events to auto-update
    order tracking_status and order status (in_transit, delivered).
    """
    try:
        payload = await request.json()
    except Exception:
        return {"received": False, "error": "Invalid JSON"}

    event_type = payload.get("description", "")
    result = payload.get("result", {})
    tracking_code = result.get("tracking_code", "")
    tracking_status = result.get("status", "")
    status_detail = result.get("status_detail", "")

    logger.info("EasyPost webhook: event=%s tracking=%s status=%s", event_type, tracking_code, tracking_status)

    if not tracking_code:
        return {"received": True, "event": event_type, "action": "no_tracking_code"}

    # Find order by tracking number
    order = db.query(Order).filter(Order.tracking_number == tracking_code).first()
    if not order:
        logger.warning("EasyPost webhook: no order found for tracking_code=%s", tracking_code)
        return {"received": True, "event": event_type, "action": "order_not_found", "tracking_code": tracking_code}

    # Update tracking status
    old_tracking_status = order.tracking_status or ""
    order.tracking_status = tracking_status

    # Update public tracking URL if provided
    public_url = result.get("public_url", "")
    if public_url:
        order.tracking_url = public_url

    # Auto-update order status based on tracking status
    new_order_status = _TRACKING_TO_ORDER_STATUS.get(tracking_status)
    order_status_updated = False
    if new_order_status:
        current = order.status if isinstance(order.status, str) else order.status.value
        new_val = new_order_status.value
        if current != new_val:
            order.status = new_order_status
            _add_status_history(order, new_order_status, f"Auto-updated from EasyPost tracking: {tracking_status} ({status_detail})")
            order_status_updated = True

    db.commit()
    db.refresh(order)

    # Fire outgoing webhook to customer
    if order_status_updated or old_tracking_status != tracking_status:
        try:
            send_webhook_sync(order)
        except Exception as e:
            logger.error("Failed to send outgoing webhook for order %s: %s", order.order_number, e)

    return {
        "received": True,
        "event": event_type,
        "tracking_code": tracking_code,
        "tracking_status": tracking_status,
        "order_number": order.order_number,
        "order_status_updated": order_status_updated,
    }
