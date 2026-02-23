from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import order_service
from app.services.webhook_service import send_webhook_sync

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


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
def easypost_webhook(payload: dict):
    """
    Receive EasyPost tracking webhook events.
    Configure this URL in EasyPost dashboard: POST /api/v1/webhooks/easypost
    """
    event_type = payload.get("description", "")
    result = payload.get("result", {})
    tracking_code = result.get("tracking_code", "")

    return {
        "received": True,
        "event": event_type,
        "tracking_code": tracking_code,
    }
