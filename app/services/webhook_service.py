import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import func as sa_func

from app.config import settings
from app.models.order import Order

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event types (follows Stripe/Shopify convention: resource.action)
# ---------------------------------------------------------------------------
EVENT_ORDER_CREATED = "order.created"
EVENT_ORDER_UPDATED = "order.updated"
EVENT_ORDER_CANCELLED = "order.cancelled"
EVENT_ORDER_STATUS_CHANGED = "order.status_changed"
EVENT_ORDER_LABEL_PURCHASED = "order.label_purchased"
EVENT_ORDER_SHIPPED = "order.shipped"
EVENT_ORDER_IN_TRANSIT = "order.in_transit"
EVENT_ORDER_DELIVERED = "order.delivered"
EVENT_TRACKING_UPDATED = "tracking.updated"

# Available fields for custom webhook payload.
# Each key maps to a (label, resolver) where resolver takes (order, item) and returns the value.
# Item may be None for order-level-only payloads.
AVAILABLE_WEBHOOK_FIELDS = {
    "id": ("Line Item ID", lambda o, i: i.id[1:] if i and i.id and i.id.startswith("N") else (i.id if i else "")),
    "order_number": ("Order Number", lambda o, i: o.order_number or ""),
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
    "name": ("Item Name", lambda o, i: i.name if i else ""),
    "product_name": ("Product Name", lambda o, i: i.product_name if i else ""),
    "variant_label": ("Variant", lambda o, i: i.variant_label if i else ""),
    "variant_sku": ("Variant SKU", lambda o, i: i.variant_sku if i else ""),
    "quantity": ("Quantity", lambda o, i: i.quantity if i else 0),
    "unit_price": ("Unit Price", lambda o, i: i.unit_price if i else 0.0),
    "product_cost": ("Product Cost", lambda o, i: i.product_cost if i else 0.0),
}

# Fields that require line-item iteration
ITEM_LEVEL_FIELDS = {"id", "sku", "name", "product_name", "variant_label", "variant_sku", "quantity", "unit_price", "product_cost"}

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [1, 2, 4]  # exponential backoff


# ---------------------------------------------------------------------------
# HMAC-SHA256 Signature (follows Stripe/GitHub/Shopify standard)
# ---------------------------------------------------------------------------
def _compute_signature(payload_bytes: bytes, timestamp: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature over 'timestamp.payload'."""
    signed_content = f"{timestamp}.".encode() + payload_bytes
    return hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()


def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """Verify incoming webhook signature. Header format: 't=<timestamp>,v1=<sig>'."""
    if not signature_header or not secret:
        return False
    parts = {}
    for part in signature_header.split(","):
        key, _, value = part.partition("=")
        parts[key.strip()] = value.strip()
    timestamp = parts.get("t", "")
    expected_sig = parts.get("v1", "")
    if not timestamp or not expected_sig:
        return False
    computed = _compute_signature(payload_bytes, timestamp, secret)
    return hmac.compare_digest(computed, expected_sig)


# ---------------------------------------------------------------------------
# Standard event envelope (follows Stripe event object pattern)
# ---------------------------------------------------------------------------
def _build_event_envelope(event_type: str, order: Order, data: dict) -> dict:
    """Wrap payload in a standard event envelope with id, type, timestamp."""
    return {
        "id": f"evt_{uuid.uuid4().hex}",
        "object": "event",
        "type": event_type,
        "api_version": "2024-01-01",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "data": {
            "object": data,
        },
    }


def _build_order_data(order: Order) -> dict:
    """Build the order data object for the webhook payload."""
    items = []
    if hasattr(order, "items") and order.items:
        for item in order.items:
            items.append({
                "id": item.id,
                "sku": item.sku,
                "variant_sku": item.variant_sku or "",
                "variant_label": item.variant_label or "",
                "name": item.name or "",
                "product_name": item.product_name or "",
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "product_cost": item.product_cost,
            })

    status_val = order.status if isinstance(order.status, str) else order.status.value

    return {
        "object": "order",
        "id": order.id,
        "order_number": order.order_number,
        "order_name": order.order_name or "",
        "status": status_val,
        "customer": {
            "name": order.customer_name,
            "email": order.customer_email,
            "phone": getattr(order, "customer_phone", "") or "",
        },
        "shop_name": order.shop_name or "",
        "shipping_address": {
            "name": order.ship_to_name or "",
            "line1": order.ship_to_street1 or "",
            "line2": order.ship_to_street2 or "",
            "city": order.ship_to_city or "",
            "state": order.ship_to_state or "",
            "postal_code": order.ship_to_zip or "",
            "country": order.ship_to_country or "",
        },
        "shipping": {
            "carrier": order.carrier or "",
            "service": order.service or "",
            "tracking_number": order.tracking_number or "",
            "tracking_status": order.tracking_status or "",
            "tracking_url": order.tracking_url or "",
            "label_url": order.label_url or "",
        },
        "amount": {
            "shipping": order.shipping_cost,
            "processing_fee": order.processing_fee,
            "total": order.total_price,
            "currency": "usd",
        },
        "items": items,
        "metadata": {
            "status_history": json.loads(order.status_history) if order.status_history else [],
        },
        "created_at": order.created_at.isoformat() + "Z" if order.created_at else None,
        "updated_at": order.updated_at.isoformat() + "Z" if order.updated_at else None,
    }


def _build_payload(order: Order, event_type: str = EVENT_ORDER_UPDATED) -> dict:
    """Build standard webhook payload with event envelope."""
    order_data = _build_order_data(order)
    return _build_event_envelope(event_type, order, order_data)


def _build_custom_payloads(order: Order, fields: list[str], event_type: str = EVENT_ORDER_UPDATED) -> list[dict]:
    """Build a single custom payload with only the selected fields, wrapped in the default event envelope.

    If any item-level field is selected, all line items are included in an 'items' array
    within the single payload. Order-level fields remain at the top level.
    """
    valid_fields = [f for f in fields if f in AVAILABLE_WEBHOOK_FIELDS]
    if not valid_fields:
        return [_build_payload(order, event_type)]

    has_item_fields = any(f in ITEM_LEVEL_FIELDS for f in valid_fields)
    order_level_fields = [f for f in valid_fields if f not in ITEM_LEVEL_FIELDS]
    item_level_fields = [f for f in valid_fields if f in ITEM_LEVEL_FIELDS]

    # Build order-level data
    data = {}
    for field in order_level_fields:
        resolver = AVAILABLE_WEBHOOK_FIELDS[field][1]
        data[field] = resolver(order, None)

    # Build items array if item-level fields are selected
    if has_item_fields and hasattr(order, "items") and order.items:
        items_list = []
        for item in order.items:
            item_data = {}
            for field in item_level_fields:
                resolver = AVAILABLE_WEBHOOK_FIELDS[field][1]
                item_data[field] = resolver(order, item)
            items_list.append(item_data)
        data["items"] = items_list
    elif has_item_fields:
        # No items on order, include empty array
        data["items"] = []

    return [_build_event_envelope(event_type, order, data)]


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


# ---------------------------------------------------------------------------
# HTTP delivery with signature headers and retry
# ---------------------------------------------------------------------------
def _build_headers(payload_bytes: bytes) -> dict[str, str]:
    """Build standard webhook HTTP headers with HMAC signature."""
    webhook_id = f"msg_{uuid.uuid4().hex}"
    timestamp = str(int(time.time()))

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "WarehouseManager-Webhook/1.0",
        "X-Webhook-Id": webhook_id,
        "X-Webhook-Timestamp": timestamp,
    }

    if settings.WEBHOOK_SECRET:
        signature = _compute_signature(payload_bytes, timestamp, settings.WEBHOOK_SECRET)
        headers["X-Webhook-Signature"] = f"t={timestamp},v1={signature}"

    return headers


async def _deliver_async(client: httpx.AsyncClient, url: str, payload: dict) -> dict:
    """Deliver a webhook with retry and exponential backoff."""
    payload_bytes = json.dumps(payload, default=str).encode()
    headers = _build_headers(payload_bytes)

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.post(url, content=payload_bytes, headers=headers)
            if resp.is_success:
                return {"url": url, "status": resp.status_code, "success": True, "attempt": attempt + 1}
            # 4xx = don't retry (client error), 5xx = retry
            if 400 <= resp.status_code < 500:
                return {"url": url, "status": resp.status_code, "success": False, "attempt": attempt + 1}
            last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)

        # Backoff before retry
        if attempt < MAX_RETRIES:
            await _async_sleep(RETRY_BACKOFF_SECONDS[attempt])

    logger.error(f"Webhook delivery failed after {MAX_RETRIES + 1} attempts for {url}: {last_error}")
    return {"url": url, "status": 0, "success": False, "error": last_error, "attempt": MAX_RETRIES + 1}


async def _async_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)


def _deliver_sync(client: httpx.Client, url: str, payload: dict) -> dict:
    """Deliver a webhook synchronously with retry and exponential backoff."""
    payload_bytes = json.dumps(payload, default=str).encode()
    headers = _build_headers(payload_bytes)

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.post(url, content=payload_bytes, headers=headers)
            if resp.is_success:
                return {"url": url, "status": resp.status_code, "success": True, "attempt": attempt + 1}
            if 400 <= resp.status_code < 500:
                return {"url": url, "status": resp.status_code, "success": False, "attempt": attempt + 1}
            last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS[attempt])

    logger.error(f"Webhook delivery failed after {MAX_RETRIES + 1} attempts for {url}: {last_error}")
    return {"url": url, "status": 0, "success": False, "error": last_error, "attempt": MAX_RETRIES + 1}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def send_webhook(order: Order, event_type: str = EVENT_ORDER_UPDATED) -> list[dict]:
    """Send order update to all configured webhook URLs + order-specific URL + customer URL."""
    general_urls = _collect_webhook_urls(order)
    customer_url, customer_fields = _resolve_customer_webhook(order)

    if not general_urls and not customer_url:
        return []

    default_payload = _build_payload(order, event_type)
    results = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Send default payload to global + per-order URLs
        for url in general_urls:
            result = await _deliver_async(client, url, default_payload)
            results.append(result)

        # Send to customer webhook URL (with custom payload if configured)
        if customer_url and customer_url not in general_urls:
            if customer_fields:
                payloads = _build_custom_payloads(order, customer_fields, event_type)
                for payload in payloads:
                    result = await _deliver_async(client, customer_url, payload)
                    results.append(result)
            else:
                result = await _deliver_async(client, customer_url, default_payload)
                results.append(result)

    return results


def send_webhook_sync(order: Order, event_type: str = EVENT_ORDER_UPDATED) -> list[dict]:
    """Synchronous version of webhook sender."""
    general_urls = _collect_webhook_urls(order)
    customer_url, customer_fields = _resolve_customer_webhook(order)

    if not general_urls and not customer_url:
        return []

    default_payload = _build_payload(order, event_type)
    results = []

    with httpx.Client(timeout=10.0) as client:
        # Send default payload to global + per-order URLs
        for url in general_urls:
            result = _deliver_sync(client, url, default_payload)
            results.append(result)

        # Send to customer webhook URL (with custom payload if configured)
        if customer_url and customer_url not in general_urls:
            if customer_fields:
                payloads = _build_custom_payloads(order, customer_fields, event_type)
                for payload in payloads:
                    result = _deliver_sync(client, customer_url, payload)
                    results.append(result)
            else:
                result = _deliver_sync(client, customer_url, default_payload)
                results.append(result)

    return results
