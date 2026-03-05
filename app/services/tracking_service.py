"""Tracking service: poll EasyPost for tracking updates on drop_off/shipped orders."""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.order import Order, OrderStatus
from app.services.order_service import _add_status_history

logger = logging.getLogger(__name__)

# EasyPost tracking status -> order status mapping (same as webhook handler)
_TRACKING_TO_ORDER_STATUS = {
    "in_transit": OrderStatus.IN_TRANSIT,
    "out_for_delivery": OrderStatus.IN_TRANSIT,
    "delivered": OrderStatus.DELIVERED,
}

_PRE_SHIPPED = {OrderStatus.LABEL_PURCHASED, OrderStatus.DROP_OFF}


def check_tracking_updates(db: Session) -> dict:
    """Query EasyPost for tracking updates on all drop_off/shipped/in_transit orders with a tracking number."""
    import easypost

    if not settings.EASYPOST_API_KEY:
        logger.warning("Tracking job skipped: EASYPOST_API_KEY not configured")
        return {"skipped": True, "reason": "no_api_key"}

    client = easypost.EasyPostClient(settings.EASYPOST_API_KEY)

    orders = (
        db.query(Order)
        .filter(
            Order.tracking_number != "",
            Order.status.in_([
                OrderStatus.DROP_OFF,
                OrderStatus.SHIPPED,
                OrderStatus.IN_TRANSIT,
            ]),
        )
        .all()
    )

    if not orders:
        logger.info("Tracking job: no orders to check")
        return {"checked": 0, "updated": 0}

    checked = 0
    updated = 0
    errors = 0
    details = []

    for order in orders:
        try:
            # Retrieve tracker from EasyPost by shipment
            if order.easypost_shipment_id:
                shipment = client.shipment.retrieve(order.easypost_shipment_id)
                tracker = shipment.tracker if shipment.tracker else None
            else:
                # Create/retrieve tracker by tracking number and carrier
                tracker = client.tracker.create(
                    tracking_code=order.tracking_number,
                    carrier=order.carrier or "USPS",
                )

            if not tracker:
                checked += 1
                continue

            tracking_status = tracker.status or ""
            status_detail = tracker.status_detail or ""
            public_url = tracker.public_url or ""

            old_tracking = order.tracking_status or ""
            order.tracking_status = tracking_status
            if public_url:
                order.tracking_url = public_url

            order_updated = False

            # Transition pre-shipped -> SHIPPED
            if order.status in _PRE_SHIPPED and tracking_status:
                order.status = OrderStatus.SHIPPED
                _add_status_history(
                    order, OrderStatus.SHIPPED,
                    f"Tracking job: first scan ({tracking_status}: {status_detail})",
                )
                order_updated = True

            # Apply target status
            new_status = _TRACKING_TO_ORDER_STATUS.get(tracking_status)
            current = order.status if isinstance(order.status, str) else order.status.value
            if new_status and current != new_status.value:
                order.status = new_status
                _add_status_history(
                    order, new_status,
                    f"Tracking job: {tracking_status} ({status_detail})",
                )
                order_updated = True

            if order_updated or old_tracking != tracking_status:
                updated += 1
                details.append({
                    "order_number": order.order_number,
                    "tracking": order.tracking_number,
                    "old_status": old_tracking,
                    "new_status": tracking_status,
                    "order_status": order.status.value if hasattr(order.status, "value") else order.status,
                })

                # Fire outgoing webhook
                try:
                    from app.services.webhook_service import send_webhook_sync
                    send_webhook_sync(order)
                except Exception as e:
                    logger.error("Webhook failed for %s: %s", order.order_number, e)

            checked += 1

        except Exception as e:
            logger.error("Tracking check failed for %s (%s): %s", order.order_number, order.tracking_number, e)
            errors += 1
            checked += 1

    db.commit()

    logger.info("Tracking job done: checked=%d updated=%d errors=%d", checked, updated, errors)
    return {
        "checked": checked,
        "updated": updated,
        "errors": errors,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
