import json
import logging

import httpx
from sqlalchemy import func as sa_func

from app.config import settings
from app.models.order import Order

logger = logging.getLogger(__name__)

# Available fields for custom webhook payload.
# Each key maps to a (label, resolver) where resolver takes (order, item) and returns the value.
# Item may be None for order-level-only payloads.
AVAILABLE_WEBHOOK_FIELDS = {
    "id": ("Line Item ID", lambda o, i: i.id if i else ""),
    "order_number": ("Order Number", lambda o, i: o.order_number),
    "order_name": ("Order Name", lambda o, i: o.order_name or ""),
    "status": ("Order Status", lambda o, i: o.status if isinstance(o.status, str) else o.status.value),
    "customer_name": ("Customer Name", lambda o, i: o.customer_name),
    "customer_email": ("Customer Email", lambda o, i: o.customer_email),
    "shop_name": ("Shop Name", lambda o, i: o.shop_name or ""),
    "carrier_code": ("Carrier Code", lambda o, i: o.carrier or ""),
    "service": ("Shipping Service", lambda o, i: o.service or ""),
    "tracking_number": ("Tracking Number", lambda o, i: o.tracking_number),
    "tracking_url": ("Tracking URL", lambda o, i: o.tracking_url),
    "tracking_status": ("Tracking Status", lambda o, i: o.tracking_status),
    "shipping_cost": ("Shipping Cost", lambda o, i: o.shipping_cost),
    "base_cost": ("Base Cost (Processing Fee)", lambda o, i: o.processing_fee),
    "total_price": ("Total Price", lambda o, i: o.total_price),
    "sku": ("SKU", lambda o, i: i.sku if i else ""),
    "product_name": ("Product Name", lambda o, i: i.product_name if i else ""),
    "variant_label": ("Variant", lambda o, i: i.variant_label if i else ""),
    "quantity": ("Quantity", lambda o, i: i.quantity if i else 0),
    "unit_price": ("Unit Price", lambda o, i: i.unit_price if i else 0.0),
}

# Fields that require line-item iteration
ITEM_LEVEL_FIELDS = {"id", "sku", "product_name", "variant_label", "quantity", "unit_price"}


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


def _build_custom_payloads(order: Order, fields: list[str]) -> list[dict]:
    """Build custom flat payload(s) with only the selected fields.

    If any item-level field is selected, returns one payload per line item.
    Otherwise returns a single payload for the order.
    """
    valid_fields = [f for f in fields if f in AVAILABLE_WEBHOOK_FIELDS]
    if not valid_fields:
        return [_build_payload(order)]

    has_item_fields = any(f in ITEM_LEVEL_FIELDS for f in valid_fields)

    if has_item_fields and hasattr(order, "items") and order.items:
        payloads = []
        for item in order.items:
            payload = {}
            for field in valid_fields:
                resolver = AVAILABLE_WEBHOOK_FIELDS[field][1]
                payload[field] = resolver(order, item)
            payloads.append(payload)
        return payloads
    else:
        payload = {}
        for field in valid_fields:
            resolver = AVAILABLE_WEBHOOK_FIELDS[field][1]
            payload[field] = resolver(order, None)
        return [payload]


def _resolve_customer_webhook(order: Order) -> tuple[str, list[str]]:
    """Look up customer webhook_url and payload fields by matching order to customers table.

    Returns (webhook_url, payload_fields_list).
    """
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
        if customer:
            url = (customer.webhook_url or "").strip()
            fields_json = customer.webhook_payload_fields or ""
            fields = []
            if fields_json:
                try:
                    fields = json.loads(fields_json)
                except (json.JSONDecodeError, TypeError):
                    fields = []
            return url, fields
    except Exception as e:
        logger.error(f"Failed to resolve customer webhook: {e}")
    finally:
        db.close()
    return "", []


def _collect_webhook_urls(order: Order) -> list[str]:
    """Collect all webhook URLs: global + per-order (NOT customer-level, handled separately)."""
    urls: list[str] = []

    # Global webhook URLs
    if settings.WEBHOOK_URLS:
        urls.extend(u.strip() for u in settings.WEBHOOK_URLS.split(",") if u.strip())

    # Per-order webhook URL
    if order.webhook_url:
        urls.append(order.webhook_url.strip())

    return urls


async def send_webhook(order: Order) -> list[dict]:
    """Send order update to all configured webhook URLs + order-specific URL + customer URL."""
    general_urls = _collect_webhook_urls(order)
    customer_url, customer_fields = _resolve_customer_webhook(order)

    if not general_urls and not customer_url:
        return []

    default_payload = _build_payload(order)
    results = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Send default payload to global + per-order URLs
        for url in general_urls:
            try:
                resp = await client.post(url, json=default_payload)
                results.append({"url": url, "status": resp.status_code, "success": resp.is_success})
            except Exception as e:
                logger.error(f"Webhook failed for {url}: {e}")
                results.append({"url": url, "status": 0, "success": False, "error": str(e)})

        # Send to customer webhook URL (with custom payload if configured)
        if customer_url and customer_url not in general_urls:
            if customer_fields:
                payloads = _build_custom_payloads(order, customer_fields)
                for payload in payloads:
                    try:
                        resp = await client.post(customer_url, json=payload)
                        results.append({"url": customer_url, "status": resp.status_code, "success": resp.is_success})
                    except Exception as e:
                        logger.error(f"Webhook failed for {customer_url}: {e}")
                        results.append({"url": customer_url, "status": 0, "success": False, "error": str(e)})
            else:
                try:
                    resp = await client.post(customer_url, json=default_payload)
                    results.append({"url": customer_url, "status": resp.status_code, "success": resp.is_success})
                except Exception as e:
                    logger.error(f"Webhook failed for {customer_url}: {e}")
                    results.append({"url": customer_url, "status": 0, "success": False, "error": str(e)})

    return results


def send_webhook_sync(order: Order) -> list[dict]:
    """Synchronous version of webhook sender."""
    general_urls = _collect_webhook_urls(order)
    customer_url, customer_fields = _resolve_customer_webhook(order)

    if not general_urls and not customer_url:
        return []

    default_payload = _build_payload(order)
    results = []

    with httpx.Client(timeout=10.0) as client:
        # Send default payload to global + per-order URLs
        for url in general_urls:
            try:
                resp = client.post(url, json=default_payload)
                results.append({"url": url, "status": resp.status_code, "success": resp.is_success})
            except Exception as e:
                logger.error(f"Webhook failed for {url}: {e}")
                results.append({"url": url, "status": 0, "success": False, "error": str(e)})

        # Send to customer webhook URL (with custom payload if configured)
        if customer_url and customer_url not in general_urls:
            if customer_fields:
                payloads = _build_custom_payloads(order, customer_fields)
                for payload in payloads:
                    try:
                        resp = client.post(customer_url, json=payload)
                        results.append({"url": customer_url, "status": resp.status_code, "success": resp.is_success})
                    except Exception as e:
                        logger.error(f"Webhook failed for {customer_url}: {e}")
                        results.append({"url": customer_url, "status": 0, "success": False, "error": str(e)})
            else:
                try:
                    resp = client.post(customer_url, json=default_payload)
                    results.append({"url": customer_url, "status": resp.status_code, "success": resp.is_success})
                except Exception as e:
                    logger.error(f"Webhook failed for {customer_url}: {e}")
                    results.append({"url": customer_url, "status": 0, "success": False, "error": str(e)})

    return results
