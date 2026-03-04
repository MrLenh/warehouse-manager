import json
import logging

import httpx
from sqlalchemy import func as sa_func

from app.config import settings
from app.models.order import Order

logger = logging.getLogger(__name__)


def _build_payload(order: Order) -> dict:
    return {
        "event": "order_update",
        "order_number": order.order_number,
        "order_name": order.order_name or "",
        "status": order.status if isinstance(order.status, str) else order.status.value,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "shop_name": order.shop_name or "",
        "pricing": {
            "shipping_cost": order.shipping_cost,
            "processing_fee": order.processing_fee,
            "total_price": order.total_price,
        },
        "tracking": {
            "tracking_number": order.tracking_number,
            "tracking_status": order.tracking_status,
            "tracking_url": order.tracking_url,
            "carrier": order.carrier or "",
            "service": order.service or "",
            "carrier_label_url": order.label_url,
        },
        "shipping_address": {
            "name": order.ship_to_name or "",
            "street1": order.ship_to_street1 or "",
            "street2": order.ship_to_street2 or "",
            "city": order.ship_to_city or "",
            "state": order.ship_to_state or "",
            "zip": order.ship_to_zip or "",
            "country": order.ship_to_country or "",
        },
        "status_history": json.loads(order.status_history) if order.status_history else [],
    }


def _resolve_customer_webhook_url(order: Order) -> str:
    """Look up customer webhook_url by matching order.customer_name to customers table."""
    from app.database import SessionLocal
    from app.models.customer import Customer

    try:
        db = SessionLocal()
        customer = None
        if order.customer_id:
            customer = db.query(Customer).filter(Customer.id == order.customer_id).first()
        if not customer:
            customer = (
                db.query(Customer)
                .filter(sa_func.lower(Customer.name) == order.customer_name.lower().strip())
                .first()
            )
        if customer and customer.webhook_url:
            return customer.webhook_url.strip()
    except Exception as e:
        logger.error(f"Failed to resolve customer webhook URL: {e}")
    finally:
        db.close()
    return ""


def _collect_webhook_urls(order: Order) -> list[str]:
    """Collect all webhook URLs: global + per-order + customer-level."""
    urls: list[str] = []

    # Global webhook URLs
    if settings.WEBHOOK_URLS:
        urls.extend(u.strip() for u in settings.WEBHOOK_URLS.split(",") if u.strip())

    # Per-order webhook URL
    if order.webhook_url:
        urls.append(order.webhook_url.strip())

    # Customer-level webhook URL
    customer_url = _resolve_customer_webhook_url(order)
    if customer_url and customer_url not in urls:
        urls.append(customer_url)

    return urls


async def send_webhook(order: Order) -> list[dict]:
    """Send order update to all configured webhook URLs + order-specific URL + customer URL."""
    urls = _collect_webhook_urls(order)

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
    urls = _collect_webhook_urls(order)

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
