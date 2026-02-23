import easypost
from sqlalchemy.orm import Session

from app.config import settings
from app.models.order import Order, OrderStatus
from app.services.order_service import _add_status_history


def _get_client() -> easypost.EasyPostClient:
    if not settings.EASYPOST_API_KEY:
        raise RuntimeError("EASYPOST_API_KEY not configured")
    return easypost.EasyPostClient(settings.EASYPOST_API_KEY)


def buy_label(db: Session, order_id: str, carrier: str = "USPS", service: str = "Priority") -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Order not found")
    if order.easypost_shipment_id and order.label_url:
        raise ValueError("Label already purchased for this order")

    client = _get_client()

    total_weight_oz = sum(item.quantity * 8.0 for item in order.items)  # default 8oz per item

    shipment = client.shipment.create(
        from_address={
            "name": order.ship_from_name,
            "street1": order.ship_from_street1,
            "city": order.ship_from_city,
            "state": order.ship_from_state,
            "zip": order.ship_from_zip,
            "country": order.ship_from_country,
        },
        to_address={
            "name": order.ship_to_name,
            "street1": order.ship_to_street1,
            "street2": order.ship_to_street2,
            "city": order.ship_to_city,
            "state": order.ship_to_state,
            "zip": order.ship_to_zip,
            "country": order.ship_to_country,
        },
        parcel={
            "weight": total_weight_oz,
        },
    )

    # Find matching rate
    selected_rate = None
    for rate in shipment.rates:
        if rate.carrier == carrier and rate.service == service:
            selected_rate = rate
            break

    if not selected_rate:
        # Fallback: pick the lowest rate
        selected_rate = shipment.lowest_rate()

    bought = client.shipment.buy(shipment.id, rate=selected_rate)

    order.easypost_shipment_id = bought.id
    order.tracking_number = bought.tracking_code or ""
    order.tracking_url = bought.tracker.public_url if bought.tracker else ""
    order.label_url = bought.postage_label.label_url if bought.postage_label else ""
    order.shipping_cost = float(selected_rate.rate)
    order.total_price = order.processing_fee + order.shipping_cost
    order.status = OrderStatus.LABEL_PURCHASED

    _add_status_history(order, OrderStatus.LABEL_PURCHASED, f"Label purchased via {carrier} {service}")

    db.commit()
    db.refresh(order)
    return order


def get_rates(order_id: str, db: Session) -> list[dict]:
    """Get shipping rates without purchasing."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Order not found")

    client = _get_client()
    total_weight_oz = sum(item.quantity * 8.0 for item in order.items)

    shipment = client.shipment.create(
        from_address={
            "name": order.ship_from_name,
            "street1": order.ship_from_street1,
            "city": order.ship_from_city,
            "state": order.ship_from_state,
            "zip": order.ship_from_zip,
            "country": order.ship_from_country,
        },
        to_address={
            "name": order.ship_to_name,
            "street1": order.ship_to_street1,
            "street2": order.ship_to_street2,
            "city": order.ship_to_city,
            "state": order.ship_to_state,
            "zip": order.ship_to_zip,
            "country": order.ship_to_country,
        },
        parcel={
            "weight": total_weight_oz,
        },
    )

    return [
        {
            "carrier": r.carrier,
            "service": r.service,
            "rate": r.rate,
            "currency": r.currency,
            "delivery_days": r.delivery_days,
        }
        for r in shipment.rates
    ]
