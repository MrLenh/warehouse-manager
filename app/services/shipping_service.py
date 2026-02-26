import easypost
from sqlalchemy.orm import Session

from app.config import settings
from app.models.order import Order, OrderStatus
from app.models.product import Product, Variant
from app.services.order_service import _add_status_history


def _get_client() -> easypost.EasyPostClient:
    if not settings.EASYPOST_API_KEY:
        raise RuntimeError("EASYPOST_API_KEY not configured")
    return easypost.EasyPostClient(settings.EASYPOST_API_KEY)


def _calc_parcel(order: Order, db: Session) -> dict:
    """Calculate parcel weight and dimensions from product data."""
    total_weight_oz = 0.0
    max_length = 0.0
    max_width = 0.0
    total_height = 0.0

    for item in order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        variant = db.query(Variant).filter(Variant.id == item.variant_id).first() if item.variant_id else None

        w = (variant.effective_weight_oz if variant else (product.weight_oz if product else 0)) or 0
        total_weight_oz += (w if w > 0 else 8.0) * item.quantity

        l = variant.effective_length_in if variant else (product.length_in if product else 0)
        wi = variant.effective_width_in if variant else (product.width_in if product else 0)
        h = variant.effective_height_in if variant else (product.height_in if product else 0)
        max_length = max(max_length, l)
        max_width = max(max_width, wi)
        total_height += h * item.quantity

    parcel = {"weight": round(total_weight_oz, 2)}
    if max_length > 0 and max_width > 0 and total_height > 0:
        parcel["length"] = round(max_length, 2)
        parcel["width"] = round(max_width, 2)
        parcel["height"] = round(total_height, 2)

    return parcel


def _find_rate(rates, carrier: str, service: str):
    """Find a matching rate with progressive fallback:
    1. Exact carrier + service match
    2. Case-insensitive carrier + service match
    3. Carrier match + service partial/contains match
    4. Cheapest rate for the requested carrier
    5. Overall cheapest rate
    """
    if not rates:
        return None

    # 1. Exact match
    for r in rates:
        if r.carrier == carrier and r.service == service:
            return r

    # 2. Case-insensitive match
    c_lower = carrier.lower()
    s_lower = service.lower()
    for r in rates:
        if r.carrier.lower() == c_lower and r.service.lower() == s_lower:
            return r

    # 3. Carrier match + service contains (e.g. "First" matches "FirstClassPackageInternationalService")
    for r in rates:
        if r.carrier.lower() == c_lower and (s_lower in r.service.lower() or r.service.lower() in s_lower):
            return r

    # 4. Cheapest for requested carrier
    carrier_rates = [r for r in rates if r.carrier.lower() == c_lower]
    if carrier_rates:
        return min(carrier_rates, key=lambda r: float(r.rate))

    # 5. Overall cheapest
    return min(rates, key=lambda r: float(r.rate))


def _get_from_address(order: Order) -> dict:
    """Get ship-from address: order's address if set, otherwise warehouse config."""
    # Use order's ship_from if it has a street address
    if order.ship_from_street1:
        return {
            "name": order.ship_from_name,
            "street1": order.ship_from_street1,
            "city": order.ship_from_city,
            "state": order.ship_from_state,
            "zip": order.ship_from_zip,
            "country": order.ship_from_country,
        }

    # Fallback to warehouse config
    if not settings.WAREHOUSE_STREET1:
        raise ValueError(
            "Chua cau hinh dia chi kho (warehouse). "
            "Vui long set WAREHOUSE_STREET1, WAREHOUSE_CITY, WAREHOUSE_STATE, WAREHOUSE_ZIP trong .env "
            "hoac nhap dia chi gui hang khi tao don."
        )

    return {
        "name": settings.WAREHOUSE_NAME,
        "street1": settings.WAREHOUSE_STREET1,
        "city": settings.WAREHOUSE_CITY,
        "state": settings.WAREHOUSE_STATE,
        "zip": settings.WAREHOUSE_ZIP,
        "country": settings.WAREHOUSE_COUNTRY,
    }


def _create_shipment(client, order: Order, db: Session, parcel_override: dict | None = None):
    """Create EasyPost shipment for an order."""
    parcel = parcel_override if parcel_override else _calc_parcel(order, db)
    from_addr = _get_from_address(order)

    # Validate to_address has required fields
    if not order.ship_to_street1 or not order.ship_to_zip:
        raise ValueError("Dia chi nguoi nhan thieu street hoac zip code.")

    return client.shipment.create(
        from_address=from_addr,
        to_address={
            "name": order.ship_to_name,
            "street1": order.ship_to_street1,
            "street2": order.ship_to_street2,
            "city": order.ship_to_city,
            "state": order.ship_to_state,
            "zip": order.ship_to_zip,
            "country": order.ship_to_country,
        },
        parcel=parcel,
    )


def buy_label(db: Session, order_id: str, carrier: str = "", service: str = "",
              parcel_override: dict | None = None) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Order not found")
    if order.easypost_shipment_id and order.label_url:
        raise ValueError("Label already purchased for this order")

    # Resolve carrier/service: request param > order setting > config default
    carrier = carrier or order.carrier or settings.DEFAULT_CARRIER
    service = service or order.service or settings.DEFAULT_SERVICE

    client = _get_client()
    shipment = _create_shipment(client, order, db, parcel_override=parcel_override)

    if not shipment.rates:
        raise ValueError("No shipping rates available. Check addresses and parcel dimensions.")

    selected_rate = _find_rate(shipment.rates, carrier, service)
    if not selected_rate:
        available = ", ".join(f"{r.carrier} {r.service} (${r.rate})" for r in shipment.rates)
        raise ValueError(f"No rate found for {carrier} {service}. Available: {available}")

    bought = client.shipment.buy(shipment.id, rate=selected_rate)

    order.carrier = selected_rate.carrier
    order.service = selected_rate.service
    order.easypost_shipment_id = bought.id
    order.tracking_number = bought.tracking_code or ""
    order.tracking_url = bought.tracker.public_url if bought.tracker else ""
    order.label_url = bought.postage_label.label_url if bought.postage_label else ""
    order.shipping_cost = float(selected_rate.rate)
    items_subtotal = sum(i.quantity * i.unit_price for i in order.items)
    order.total_price = items_subtotal + order.processing_fee + order.shipping_cost
    order.status = OrderStatus.LABEL_PURCHASED

    _add_status_history(
        order, OrderStatus.LABEL_PURCHASED,
        f"Label purchased via {selected_rate.carrier} {selected_rate.service} (${selected_rate.rate})",
    )

    db.commit()
    db.refresh(order)
    return order


def refund_shipment(db: Session, order: Order) -> str:
    """Request EasyPost refund for a purchased label. Returns refund status."""
    if not order.easypost_shipment_id:
        raise ValueError("No shipment to refund")

    client = _get_client()
    result = client.shipment.refund(order.easypost_shipment_id)

    refund_status = getattr(result, "refund_status", "") or "submitted"
    order.label_url = ""
    order.tracking_number = ""
    order.tracking_url = ""
    order.tracking_status = ""
    order.shipping_cost = 0.0
    # Recalculate total without shipping
    items_subtotal = sum(i.quantity * i.unit_price for i in order.items)
    order.total_price = items_subtotal + order.processing_fee

    db.commit()
    db.refresh(order)
    return refund_status


def get_parcel_info(order_id: str, db: Session) -> dict:
    """Get calculated parcel weight and dimensions for an order."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Order not found")
    return _calc_parcel(order, db)


def get_rates(order_id: str, db: Session, parcel_override: dict | None = None) -> list[dict]:
    """Get shipping rates without purchasing."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Order not found")

    client = _get_client()
    shipment = _create_shipment(client, order, db, parcel_override=parcel_override)

    return sorted(
        [
            {
                "carrier": r.carrier,
                "service": r.service,
                "rate": r.rate,
                "currency": r.currency,
                "delivery_days": r.delivery_days,
            }
            for r in shipment.rates
        ],
        key=lambda x: float(x["rate"]),
    )
