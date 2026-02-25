import json
import logging

import httpx

from app.config import settings
from app.models.order import Order

logger = logging.getLogger(__name__)


def _build_payload(order: Order) -> dict:
    return {
        "event": "order_update",
        "order_number": order.order_number,
        "status": order.status if isinstance(order.status, str) else order.status.value,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "pricing": {
            "shipping_cost": order.shipping_cost,
            "processing_fee": order.processing_fee,
            "total_price": order.total_price,
        },
        "tracking": {
            "tracking_number": order.tracking_number,
            "tracking_status": order.tracking_status,
            "tracking_url": order.tracking_url,
            "carrier_label_url": order.label_url,
        },
        "status_history": json.loads(order.status_history) if order.status_history else [],
    }


async def send_webhook(order: Order) -> list[dict]:
    """Send order update to all configured webhook URLs + order-specific URL."""
    urls: list[str] = []

    # Global webhook URLs
    if settings.WEBHOOK_URLS:
        urls.extend(u.strip() for u in settings.WEBHOOK_URLS.split(",") if u.strip())

    # Per-order webhook URL
    if order.webhook_url:
        urls.append(order.webhook_url)

    if not urls:
        return []

    payload = _build_payload(order)
    results = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in urls:
            try:
                resp = await client.post(url, json=payload)
                results.append({"url": url, "status": resp.status_code, "success": resp.is_success})
            except Exception as e:
                logger.error(f"Webhook failed for {url}: {e}")
                results.append({"url": url, "status": 0, "success": False, "error": str(e)})

    return results


def send_webhook_sync(order: Order) -> list[dict]:
    """Synchronous version of webhook sender."""
    urls: list[str] = []

    if settings.WEBHOOK_URLS:
        urls.extend(u.strip() for u in settings.WEBHOOK_URLS.split(",") if u.strip())

    if order.webhook_url:
        urls.append(order.webhook_url)

    if not urls:
        return []

    payload = _build_payload(order)
    results = []

    with httpx.Client(timeout=10.0) as client:
        for url in urls:
            try:
                resp = client.post(url, json=payload)
                results.append({"url": url, "status": resp.status_code, "success": resp.is_success})
            except Exception as e:
                logger.error(f"Webhook failed for {url}: {e}")
                results.append({"url": url, "status": 0, "success": False, "error": str(e)})

    return results
