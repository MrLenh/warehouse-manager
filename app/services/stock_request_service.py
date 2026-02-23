import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.inventory_log import InventoryLog
from app.models.product import Product, Variant
from app.models.stock_request import StockRequest, StockRequestItem, StockRequestStatus
from app.schemas.stock_request import StockRequestCreate, StockRequestReceive


def _generate_request_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6].upper()
    return f"SR-{ts}-{short}"


def create_stock_request(db: Session, data: StockRequestCreate) -> StockRequest:
    sr = StockRequest(
        request_number=_generate_request_number(),
        supplier=data.supplier,
        notes=data.notes,
        status=StockRequestStatus.PENDING,
    )
    db.add(sr)
    db.flush()

    for item_data in data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if not product:
            raise ValueError(f"Product {item_data.product_id} not found")

        variant_label = ""
        sku = product.sku
        if item_data.variant_id:
            variant = db.query(Variant).filter(
                Variant.id == item_data.variant_id,
                Variant.product_id == product.id,
            ).first()
            if not variant:
                raise ValueError(f"Variant {item_data.variant_id} not found")
            sku = variant.variant_sku
            attrs = json.loads(variant.attributes) if isinstance(variant.attributes, str) else variant.attributes
            variant_label = " / ".join(attrs.values()) if attrs else ""

        item = StockRequestItem(
            stock_request_id=sr.id,
            product_id=product.id,
            variant_id=item_data.variant_id,
            sku=sku,
            product_name=product.name,
            variant_label=variant_label,
            quantity_requested=item_data.quantity_requested,
            unit_cost=item_data.unit_cost,
        )
        db.add(item)

    db.commit()
    db.refresh(sr)
    return sr


def get_stock_request(db: Session, sr_id: str) -> StockRequest | None:
    return db.query(StockRequest).filter(StockRequest.id == sr_id).first()


def list_stock_requests(
    db: Session, skip: int = 0, limit: int = 100, status: StockRequestStatus | None = None
) -> list[StockRequest]:
    q = db.query(StockRequest)
    if status:
        q = q.filter(StockRequest.status == status)
    return q.order_by(StockRequest.created_at.desc()).offset(skip).limit(limit).all()


def approve_stock_request(db: Session, sr_id: str) -> StockRequest | None:
    sr = get_stock_request(db, sr_id)
    if not sr:
        return None
    if sr.status != StockRequestStatus.PENDING:
        raise ValueError(f"Cannot approve stock request in '{sr.status}' status")
    sr.status = StockRequestStatus.APPROVED
    db.commit()
    db.refresh(sr)
    return sr


def start_receiving(db: Session, sr_id: str) -> StockRequest | None:
    sr = get_stock_request(db, sr_id)
    if not sr:
        return None
    if sr.status != StockRequestStatus.APPROVED:
        raise ValueError(f"Cannot start receiving for stock request in '{sr.status}' status")
    sr.status = StockRequestStatus.RECEIVING
    db.commit()
    db.refresh(sr)
    return sr


def receive_items(db: Session, sr_id: str, data: StockRequestReceive) -> StockRequest | None:
    """Record actual received quantities and add stock to inventory."""
    sr = get_stock_request(db, sr_id)
    if not sr:
        return None
    if sr.status not in (StockRequestStatus.APPROVED, StockRequestStatus.RECEIVING):
        raise ValueError(f"Cannot receive items for stock request in '{sr.status}' status")

    sr.status = StockRequestStatus.RECEIVING

    item_map = {item.id: item for item in sr.items}

    for recv in data.items:
        item = item_map.get(recv.item_id)
        if not item:
            raise ValueError(f"Stock request item {recv.item_id} not found")
        if recv.quantity_received < 0:
            raise ValueError("Received quantity cannot be negative")

        item.quantity_received = recv.quantity_received

        # Add received quantity to inventory
        if recv.quantity_received > 0:
            if item.variant_id:
                variant = db.query(Variant).filter(Variant.id == item.variant_id).first()
                if variant:
                    variant.quantity += recv.quantity_received
                    balance = variant.quantity
                else:
                    balance = recv.quantity_received
            else:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    product.quantity += recv.quantity_received
                    balance = product.quantity
                else:
                    balance = recv.quantity_received

            log = InventoryLog(
                product_id=item.product_id,
                change=recv.quantity_received,
                reason="stock_request",
                reference_id=sr.id,
                balance_after=balance,
                note=f"[SR {sr.request_number}] Received {recv.quantity_received}"
                + (f" for variant {item.variant_label}" if item.variant_label else ""),
            )
            db.add(log)

    db.commit()
    db.refresh(sr)
    return sr


def complete_stock_request(db: Session, sr_id: str) -> StockRequest | None:
    sr = get_stock_request(db, sr_id)
    if not sr:
        return None
    if sr.status != StockRequestStatus.RECEIVING:
        raise ValueError(f"Cannot complete stock request in '{sr.status}' status")
    sr.status = StockRequestStatus.COMPLETED
    db.commit()
    db.refresh(sr)
    return sr


def cancel_stock_request(db: Session, sr_id: str) -> StockRequest | None:
    sr = get_stock_request(db, sr_id)
    if not sr:
        return None
    if sr.status in (StockRequestStatus.COMPLETED, StockRequestStatus.CANCELLED):
        raise ValueError(f"Cannot cancel stock request in '{sr.status}' status")
    sr.status = StockRequestStatus.CANCELLED
    db.commit()
    db.refresh(sr)
    return sr
