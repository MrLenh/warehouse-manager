"""Custom job service: execute user-defined jobs that scan orders and update status based on tracking."""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.custom_job import CustomJob
from app.models.order import Order, OrderStatus
from app.services.order_service import _add_status_history

logger = logging.getLogger(__name__)

# Map tracking status strings to webhook event types
_TRACKING_EVENT_MAP = {
    "shipped": "order.shipped",
    "in_transit": "order.in_transit",
    "delivered": "order.delivered",
}


def execute_custom_job(db: Session, job: CustomJob) -> dict:
    """Run a custom job: query orders by source statuses, check tracking, transition to target."""
    import easypost

    source_statuses = json.loads(job.source_statuses) if job.source_statuses else []
    tracking_conditions = json.loads(job.tracking_conditions) if job.tracking_conditions else []
    target_status = job.target_status

    if not source_statuses:
        return {"skipped": True, "reason": "no_source_statuses"}

    if not settings.EASYPOST_API_KEY:
        logger.warning("Custom job '%s' skipped: EASYPOST_API_KEY not configured", job.name)
        return {"skipped": True, "reason": "no_api_key"}

    client = easypost.EasyPostClient(settings.EASYPOST_API_KEY)

    # Build query filters
    status_enums = []
    for s in source_statuses:
        try:
            status_enums.append(OrderStatus(s))
        except ValueError:
            logger.warning("Invalid source status '%s' in job '%s'", s, job.name)

    if not status_enums:
        return {"skipped": True, "reason": "no_valid_source_statuses"}

    query = db.query(Order).filter(Order.status.in_(status_enums))
    if job.require_tracking_number:
        query = query.filter(Order.tracking_number != "")

    orders = query.all()

    if not orders:
        logger.info("Custom job '%s': no orders to check", job.name)
        # Still save log entry for no-orders run
        import json as _json
        from app.models.custom_job import CustomJobLog
        db.add(CustomJobLog(job_id=job.id, job_name=job.name, status="success", checked=0, updated=0, errors=0, details="[]"))
        db.commit()
        return {"checked": 0, "updated": 0, "skipped": 0, "errors": 0, "details": [], "timestamp": datetime.now(timezone.utc).isoformat(), "revert_snapshots": []}

    logger.info("Custom job '%s': found %d orders to check (source=%s, conditions=%s, target=%s)",
                job.name, len(orders), source_statuses, tracking_conditions, target_status)

    checked = 0
    updated = 0
    errors = 0
    skipped = 0
    details = []
    revert_snapshots = []

    for order in orders:
        try:
            logger.info("  [%s] Checking %s (status=%s, tracking=%s, carrier=%s)",
                        job.name, order.order_number,
                        order.status.value if hasattr(order.status, 'value') else order.status,
                        order.tracking_number or 'NONE', order.carrier or 'NONE')

            snapshot_before = {
                "order_id": order.id,
                "order_number": order.order_number,
                "old_order_status": order.status.value if hasattr(order.status, "value") else order.status,
                "old_tracking_status": order.tracking_status or "",
                "old_tracking_url": order.tracking_url or "",
                "old_status_history": order.status_history,
            }

            # Retrieve tracker from EasyPost
            try:
                if order.easypost_shipment_id:
                    logger.info("    Retrieving shipment %s", order.easypost_shipment_id)
                    shipment = client.shipment.retrieve(order.easypost_shipment_id)
                    tracker = shipment.tracker if shipment.tracker else None
                else:
                    # Try without carrier first (auto-detect), fallback with carrier
                    logger.info("    Creating tracker for %s (auto-detect carrier)", order.tracking_number)
                    try:
                        tracker = client.tracker.create(
                            tracking_code=order.tracking_number,
                        )
                    except Exception:
                        logger.info("    Auto-detect failed, retrying with carrier=%s", order.carrier or "USPS")
                        tracker = client.tracker.create(
                            tracking_code=order.tracking_number,
                            carrier=order.carrier or "USPS",
                        )
            except Exception as track_err:
                err_msg = str(track_err)
                logger.warning("Tracking lookup skipped for %s: %s", order.order_number, err_msg)
                details.append({
                    "order_number": order.order_number,
                    "tracking": order.tracking_number,
                    "action": "skipped",
                    "reason": err_msg[:200],
                })
                skipped += 1
                checked += 1
                continue

            if not tracker:
                logger.info("    No tracker returned for %s — skipping", order.order_number)
                checked += 1
                continue

            tracking_status = tracker.status or ""
            status_detail = tracker.status_detail or ""
            public_url = tracker.public_url or ""

            logger.info("    Tracker result: tracking_status=%s, detail=%s", tracking_status, status_detail)

            old_tracking = order.tracking_status or ""
            order.tracking_status = tracking_status
            if public_url:
                order.tracking_url = public_url

            order_updated = False

            # Check if tracking status matches any condition
            if tracking_conditions:
                matches = tracking_status in tracking_conditions
            else:
                # No conditions = any tracking activity triggers transition
                matches = bool(tracking_status)

            if matches:
                logger.info("    MATCH: tracking_status '%s' matches conditions %s → transitioning to '%s'",
                            tracking_status, tracking_conditions or 'ANY', target_status)
                try:
                    new_status = OrderStatus(target_status)
                except ValueError:
                    logger.error("Invalid target status '%s' in job '%s'", target_status, job.name)
                    checked += 1
                    continue

                current = order.status.value if hasattr(order.status, "value") else order.status
                if current != new_status.value:
                    order.status = new_status
                    _add_status_history(
                        order, new_status,
                        f"Custom job '{job.name}': tracking {tracking_status} ({status_detail})",
                    )
                    order_updated = True
                    logger.info("    ORDER UPDATED: %s %s → %s", order.order_number, current, new_status.value)
                else:
                    logger.info("    Already at target status '%s' — no change", current)
            else:
                logger.info("    NO MATCH: tracking_status '%s' not in conditions %s — skipping",
                            tracking_status, tracking_conditions)

            if order_updated or old_tracking != tracking_status:
                # Commit this order's changes immediately
                db.commit()
                logger.info("    Committed changes for %s", order.order_number)

                updated += 1
                details.append({
                    "order_number": order.order_number,
                    "tracking": order.tracking_number,
                    "old_status": old_tracking,
                    "new_status": tracking_status,
                    "order_status": order.status.value if hasattr(order.status, "value") else order.status,
                })
                revert_snapshots.append(snapshot_before)

                # Fire webhook (after commit so data is persisted)
                try:
                    from app.services.webhook_service import (
                        EVENT_ORDER_STATUS_CHANGED,
                        send_webhook_sync,
                    )
                    evt = _TRACKING_EVENT_MAP.get(target_status, EVENT_ORDER_STATUS_CHANGED)
                    send_webhook_sync(order, event_type=evt)
                except Exception as e:
                    logger.error("Webhook failed for %s: %s", order.order_number, e)

            checked += 1

        except Exception as e:
            err_msg = str(e)
            logger.error("Custom job '%s' check failed for %s: %s", job.name, order.order_number, err_msg)
            db.rollback()  # Rollback any partial changes for this order
            details.append({
                "order_number": order.order_number,
                "tracking": order.tracking_number if order else "",
                "action": "error",
                "reason": err_msg[:200],
            })
            errors += 1
            checked += 1

    # Save execution log (no need for bulk commit since each order was committed individually)

    # Save execution log
    import json as _json
    from app.models.custom_job import CustomJobLog
    log_entry = CustomJobLog(
        job_id=job.id,
        job_name=job.name,
        status="success" if errors == 0 else "error",
        checked=checked,
        updated=updated,
        errors=errors,
        details=_json.dumps(details, default=str),
        error_message=f"skipped={skipped}" if skipped > 0 else "",
    )
    db.add(log_entry)
    db.commit()

    logger.info("Custom job '%s' done: checked=%d updated=%d skipped=%d errors=%d", job.name, checked, updated, skipped, errors)
    return {
        "checked": checked,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "revert_snapshots": revert_snapshots,
    }


def revert_custom_job(db: Session, snapshots: list[dict]) -> dict:
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
    return {
        "reverted": reverted,
        "errors": errors,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --- CRUD helpers ---

def list_custom_jobs(db: Session) -> list[CustomJob]:
    return db.query(CustomJob).order_by(CustomJob.created_at.desc()).all()


def get_custom_job(db: Session, job_id: str) -> CustomJob | None:
    return db.query(CustomJob).filter(CustomJob.id == job_id).first()


def create_custom_job(db: Session, data: dict) -> CustomJob:
    job = CustomJob(
        name=data["name"],
        description=data.get("description", ""),
        source_statuses=json.dumps(data.get("source_statuses", [])),
        tracking_conditions=json.dumps(data.get("tracking_conditions", [])),
        target_status=data.get("target_status", "shipped"),
        require_tracking_number=data.get("require_tracking_number", True),
        interval_minutes=data.get("interval_minutes", 30),
        enabled=data.get("enabled", True),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_custom_job(db: Session, job_id: str, data: dict) -> CustomJob:
    job = db.query(CustomJob).filter(CustomJob.id == job_id).first()
    if not job:
        raise ValueError("Custom job not found")

    if "name" in data:
        job.name = data["name"]
    if "description" in data:
        job.description = data["description"]
    if "source_statuses" in data:
        job.source_statuses = json.dumps(data["source_statuses"])
    if "tracking_conditions" in data:
        job.tracking_conditions = json.dumps(data["tracking_conditions"])
    if "target_status" in data:
        job.target_status = data["target_status"]
    if "require_tracking_number" in data:
        job.require_tracking_number = data["require_tracking_number"]
    if "interval_minutes" in data:
        job.interval_minutes = data["interval_minutes"]
    if "enabled" in data:
        job.enabled = data["enabled"]

    db.commit()
    db.refresh(job)
    return job


def delete_custom_job(db: Session, job_id: str) -> bool:
    job = db.query(CustomJob).filter(CustomJob.id == job_id).first()
    if not job:
        return False
    db.delete(job)
    db.commit()
    return True


def job_to_dict(job: CustomJob) -> dict:
    """Serialize a CustomJob to a dict for API responses."""
    return {
        "id": job.id,
        "name": job.name,
        "description": job.description,
        "source_statuses": json.loads(job.source_statuses) if job.source_statuses else [],
        "tracking_conditions": json.loads(job.tracking_conditions) if job.tracking_conditions else [],
        "target_status": job.target_status,
        "require_tracking_number": job.require_tracking_number,
        "interval_minutes": job.interval_minutes,
        "enabled": job.enabled,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
