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
    revert_snapshots = []  # Save previous states for revert

    for order in orders:
        try:
            # Save snapshot before any changes
            snapshot_before = {
                "order_id": order.id,
                "order_number": order.order_number,
                "old_order_status": order.status.value if hasattr(order.status, "value") else order.status,
                "old_tracking_status": order.tracking_status or "",
                "old_tracking_url": order.tracking_url or "",
                "old_status_history": order.status_history,
            }

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
                # Only save revert snapshot for orders that were actually changed
                revert_snapshots.append(snapshot_before)

                # Fire outgoing webhook with proper event type
                try:
                    from app.services.webhook_service import (
                        EVENT_ORDER_DELIVERED,
                        EVENT_ORDER_IN_TRANSIT,
                        EVENT_ORDER_SHIPPED,
                        EVENT_TRACKING_UPDATED,
                        send_webhook_sync,
                    )
                    evt = EVENT_TRACKING_UPDATED
                    if new_status == OrderStatus.DELIVERED:
                        evt = EVENT_ORDER_DELIVERED
                    elif new_status == OrderStatus.IN_TRANSIT:
                        evt = EVENT_ORDER_IN_TRANSIT
                    elif order_updated and order.status == OrderStatus.SHIPPED:
                        evt = EVENT_ORDER_SHIPPED
                    send_webhook_sync(order, event_type=evt)
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
        "revert_snapshots": revert_snapshots,
    }


def revert_tracking_updates(db: Session, snapshots: list[dict]) -> dict:
    """Revert orders to their previous states using saved snapshots."""
    reverted = 0
    errors = 0
    details = []

    for snap in snapshots:
        try:
            order = db.query(Order).filter(Order.id == snap["order_id"]).first()
            if not order:
                errors += 1
                continue

            old_status = order.status.value if hasattr(order.status, "value") else order.status
            order.status = snap["old_order_status"]
            order.tracking_status = snap["old_tracking_status"]
            order.tracking_url = snap["old_tracking_url"]
            order.status_history = snap["old_status_history"]

            _add_status_history(
                order, snap["old_order_status"],
                f"Reverted by admin (was {old_status})",
            )

            reverted += 1
            details.append({
                "order_number": snap["order_number"],
                "reverted_to": snap["old_order_status"],
            })
        except Exception as e:
            logger.error("Revert failed for order %s: %s", snap.get("order_number"), e)
            errors += 1

    db.commit()
    logger.info("Revert done: reverted=%d errors=%d", reverted, errors)
    return {
        "reverted": reverted,
        "errors": errors,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
