import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.models.inventory_log import InventoryLog
from app.models.product import Product, Variant
from app.models.stock_batch import StockBatch
from app.models.stock_request import StockRequest, StockRequestBox, StockRequestItem, StockRequestStatus
from app.schemas.stock_request import StockRequestCreate, StockRequestReceive, StockRequestTrackingUpdate


def _generate_request_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6].upper()
    return f"SR-{ts}-{short}"


def _create_boxes_for_item(db: Session, item: StockRequestItem, box_count: int) -> None:
    """Create box records with unique barcodes for a stock request item."""
    for seq in range(1, box_count + 1):
        box = StockRequestBox(
            stock_request_item_id=item.id,
            sequence=seq,
        )
        db.add(box)


def create_stock_request(db: Session, data: StockRequestCreate) -> StockRequest:
    sr = StockRequest(
        request_number=_generate_request_number(),
        supplier=data.supplier,
        ship_from=data.ship_from,
        tracking_id=data.tracking_id,
        carrier=data.carrier,
        notes=data.notes,
        status=StockRequestStatus.COMPLETED if data.auto_receive else StockRequestStatus.PENDING,
    )
    db.add(sr)
    db.flush()

    products_to_recalculate: set[tuple[str, str]] = set()

    for item_data in data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if not product:
            raise ValueError(f"Product {item_data.product_id} not found")

        variant = None
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
            quantity_received=item_data.quantity_requested if data.auto_receive else 0,
            unit_cost=item_data.unit_cost,
            box_count=item_data.box_count,
        )
        db.add(item)
        db.flush()

        # Create boxes with barcodes
        if item_data.box_count > 0:
            _create_boxes_for_item(db, item, item_data.box_count)

        # Auto-receive: update inventory, create FIFO batch, log
        if data.auto_receive and item_data.quantity_requested > 0:
            qty = item_data.quantity_requested
            if variant:
                variant.quantity += qty
                balance = variant.quantity
            else:
                product.quantity += qty
                balance = product.quantity

            batch = StockBatch(
                product_id=product.id,
                variant_id=item_data.variant_id or "",
                stock_request_id=sr.id,
                unit_cost=item_data.unit_cost,
                quantity_received=qty,
                quantity_remaining=qty,
            )
            db.add(batch)
            products_to_recalculate.add((product.id, item_data.variant_id or ""))

            log = InventoryLog(
                product_id=product.id,
                change=qty,
                reason="stock_request",
                reference_id=sr.id,
                balance_after=balance,
                note=f"[SR {sr.request_number}] Auto-received {qty}"
                + (f" for variant {variant_label}" if variant_label else ""),
            )
            db.add(log)

            # Mark all boxes as received if auto-receive
            if item_data.box_count > 0:
                for box in item.boxes:
                    box.received = True
                    box.received_at = datetime.now(timezone.utc)

    # Recalculate prices based on FIFO weighted average
    if products_to_recalculate:
        db.flush()
        for product_id, variant_id in products_to_recalculate:
            _recalculate_price_from_batches(db, product_id, variant_id)

    db.commit()
    db.refresh(sr)
    return sr


def get_stock_request(db: Session, sr_id: str) -> StockRequest | None:
    return (
        db.query(StockRequest)
        .options(joinedload(StockRequest.items).joinedload(StockRequestItem.boxes))
        .filter(StockRequest.id == sr_id)
        .first()
    )


def list_stock_requests(
    db: Session, skip: int = 0, limit: int = 100, status: StockRequestStatus | None = None
) -> list[StockRequest]:
    q = db.query(StockRequest).options(
        joinedload(StockRequest.items).joinedload(StockRequestItem.boxes)
    )
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


def update_tracking(db: Session, sr_id: str, data: StockRequestTrackingUpdate) -> StockRequest | None:
    sr = get_stock_request(db, sr_id)
    if not sr:
        return None
    if data.tracking_id:
        sr.tracking_id = data.tracking_id
    if data.carrier:
        sr.carrier = data.carrier
    db.commit()
    db.refresh(sr)
    return sr


def scan_box_barcode(db: Session, barcode: str) -> dict:
    """Scan a box barcode to mark it as received. Returns scan result info."""
    box = db.query(StockRequestBox).filter(StockRequestBox.barcode == barcode).first()
    if not box:
        return {
            "success": False,
            "message": f"Box barcode '{barcode}' not found",
        }

    item = db.query(StockRequestItem).filter(StockRequestItem.id == box.stock_request_item_id).first()
    if not item:
        return {
            "success": False,
            "message": "Stock request item not found for this box",
        }

    sr = db.query(StockRequest).filter(StockRequest.id == item.stock_request_id).first()
    if not sr:
        return {
            "success": False,
            "message": "Stock request not found",
        }

    if sr.status not in (StockRequestStatus.APPROVED, StockRequestStatus.RECEIVING):
        return {
            "success": False,
            "message": f"Stock request is in '{sr.status}' status, cannot receive boxes",
        }

    if box.received:
        boxes_received = sum(1 for b in item.boxes if b.received)
        return {
            "success": False,
            "message": f"Box #{box.sequence} already scanned/received",
            "box": box,
            "item_id": item.id,
            "sku": item.sku,
            "product_name": item.product_name,
            "boxes_received": boxes_received,
            "boxes_total": item.box_count,
            "all_boxes_received": boxes_received >= item.box_count,
        }

    # Mark box as received
    box.received = True
    box.received_at = datetime.now(timezone.utc)

    # Transition SR to RECEIVING if it was APPROVED
    if sr.status == StockRequestStatus.APPROVED:
        sr.status = StockRequestStatus.RECEIVING

    db.commit()
    db.refresh(box)
    db.refresh(item)

    boxes_received = sum(1 for b in item.boxes if b.received)
    all_received = boxes_received >= item.box_count

    return {
        "success": True,
        "message": f"Box #{box.sequence} received for {item.product_name} ({item.sku}). "
                   f"{boxes_received}/{item.box_count} boxes received.",
        "box": box,
        "item_id": item.id,
        "sku": item.sku,
        "product_name": item.product_name,
        "boxes_received": boxes_received,
        "boxes_total": item.box_count,
        "all_boxes_received": all_received,
    }


def _recalculate_price_from_batches(db: Session, product_id: str, variant_id: str = "") -> None:
    """Recalculate product/variant price as weighted average cost from remaining FIFO batches."""
    batches = (
        db.query(StockBatch)
        .filter(
            StockBatch.product_id == product_id,
            StockBatch.variant_id == (variant_id or ""),
            StockBatch.quantity_remaining > 0,
        )
        .all()
    )
    if not batches:
        return

    total_qty = sum(b.quantity_remaining for b in batches)
    total_cost = sum(b.quantity_remaining * b.unit_cost for b in batches)
    if total_qty == 0:
        return

    weighted_avg = round(total_cost / total_qty, 2)

    if variant_id:
        variant = db.query(Variant).filter(Variant.id == variant_id).first()
        if variant:
            variant.price_override = weighted_avg
    else:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            product.price = weighted_avg


def receive_items(db: Session, sr_id: str, data: StockRequestReceive) -> StockRequest | None:
    """Record actual received quantities and add stock to inventory."""
    sr = get_stock_request(db, sr_id)
    if not sr:
        return None
    if sr.status not in (StockRequestStatus.APPROVED, StockRequestStatus.RECEIVING):
        raise ValueError(f"Cannot receive items for stock request in '{sr.status}' status")

    sr.status = StockRequestStatus.RECEIVING

    item_map = {item.id: item for item in sr.items}
    products_to_recalculate: set[tuple[str, str]] = set()

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

            # Create stock batch for FIFO tracking
            batch = StockBatch(
                product_id=item.product_id,
                variant_id=item.variant_id or "",
                stock_request_id=sr.id,
                unit_cost=item.unit_cost,
                quantity_received=recv.quantity_received,
                quantity_remaining=recv.quantity_received,
            )
            db.add(batch)
            products_to_recalculate.add((item.product_id, item.variant_id or ""))

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

    # Recalculate prices based on FIFO weighted average
    db.flush()
    for product_id, variant_id in products_to_recalculate:
        _recalculate_price_from_batches(db, product_id, variant_id)

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
