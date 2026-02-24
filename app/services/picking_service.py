import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.order import Order, OrderItem, OrderStatus
from app.models.picking import PickingList, PickingListStatus, PickItem


def _generate_picking_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = uuid.uuid4().hex[:6].upper()
    return f"PL-{ts}-{rand}"


def create_picking_list(db: Session, order_ids: list[str]) -> PickingList:
    """Create a picking list from selected orders. Generates one PickItem per unit (qty=1)."""
    orders = db.query(Order).filter(Order.id.in_(order_ids)).all()
    if not orders:
        raise ValueError("No valid orders found")

    # Only pending orders can be added to a batch
    non_pending = [o for o in orders if o.status != OrderStatus.PENDING]
    if non_pending:
        names = ", ".join(f"{o.order_number} ({o.status})" for o in non_pending)
        raise ValueError(f"Only pending orders can be batched: {names}")

    # Check if any order is already in an active batch
    already_in_batch = (
        db.query(PickItem.order_id)
        .join(PickingList)
        .filter(
            PickItem.order_id.in_(order_ids),
            PickingList.status.in_([PickingListStatus.ACTIVE, PickingListStatus.PROCESSING]),
        )
        .distinct()
        .all()
    )
    if already_in_batch:
        dupe_ids = {row[0] for row in already_in_batch}
        dupe_orders = [o for o in orders if o.id in dupe_ids]
        names = ", ".join(o.order_number for o in dupe_orders)
        raise ValueError(f"Orders already in an active batch: {names}")

    picking_list = PickingList(
        picking_number=_generate_picking_number(),
    )
    db.add(picking_list)
    db.flush()  # get the id

    for order in orders:
        for item in order.items:
            # Create one PickItem per unit
            for seq in range(1, item.quantity + 1):
                qr_code = f"PICK-{uuid.uuid4().hex[:8].upper()}"
                pick_item = PickItem(
                    picking_list_id=picking_list.id,
                    order_id=order.id,
                    order_item_id=item.id,
                    product_id=item.product_id,
                    sku=item.variant_sku or item.sku,
                    product_name=item.product_name,
                    variant_label=item.variant_label,
                    sequence=seq,
                    qr_code=qr_code,
                )
                db.add(pick_item)

    # Move orders to processing
    for order in orders:
        order.status = OrderStatus.PROCESSING

    db.commit()
    db.refresh(picking_list)
    return picking_list


def get_picking_list(db: Session, picking_list_id: str) -> PickingList | None:
    return db.query(PickingList).filter(PickingList.id == picking_list_id).first()


def list_picking_lists(db: Session, skip: int = 0, limit: int = 100) -> list[PickingList]:
    return db.query(PickingList).order_by(PickingList.created_at.desc()).offset(skip).limit(limit).all()


def scan_pick_item(db: Session, qr_code: str) -> dict:
    """Scan a QR code to mark item as picked. Returns scan result info."""
    pick_item = db.query(PickItem).filter(PickItem.qr_code == qr_code).first()
    if not pick_item:
        return {"success": False, "message": "QR code not found", "pick_item": None}

    if pick_item.picked:
        return {
            "success": False,
            "message": f"Already picked at {pick_item.picked_at.strftime('%H:%M:%S') if pick_item.picked_at else 'unknown'}",
            "pick_item": pick_item,
        }

    # Mark as picked
    pick_item.picked = True
    pick_item.picked_at = datetime.now(timezone.utc)

    # Transition batch to processing on first scan
    picking_list = db.query(PickingList).filter(PickingList.id == pick_item.picking_list_id).first()
    if picking_list and picking_list.status == PickingListStatus.ACTIVE:
        picking_list.status = PickingListStatus.PROCESSING

    # Check order progress in this picking list
    order_items = db.query(PickItem).filter(
        PickItem.picking_list_id == pick_item.picking_list_id,
        PickItem.order_id == pick_item.order_id,
    ).all()
    order_total = len(order_items)
    order_picked = sum(1 for i in order_items if i.picked)

    # Get order info and update order status
    order = db.query(Order).filter(Order.id == pick_item.order_id).first()
    order_number = order.order_number if order else ""

    if order:
        if order_picked >= order_total:
            # All items scanned → packed
            order.status = OrderStatus.PACKED
        elif order.status == OrderStatus.PROCESSING:
            # First scan for this order → packing
            order.status = OrderStatus.PACKING

    db.commit()
    db.refresh(pick_item)

    return {
        "success": True,
        "message": f"Picked: {pick_item.product_name} ({pick_item.sku})" + (f" [{pick_item.variant_label}]" if pick_item.variant_label else "") + f" #{pick_item.sequence}",
        "pick_item": pick_item,
        "order_id": pick_item.order_id,
        "order_number": order_number,
        "order_picked": order_picked,
        "order_total": order_total,
        "order_complete": order_picked >= order_total,
    }


def delete_picking_list(db: Session, picking_list_id: str) -> dict:
    """Delete a picking list and all its pick items (unpack entire batch). Only active batches."""
    pl = db.query(PickingList).filter(PickingList.id == picking_list_id).first()
    if not pl:
        raise ValueError("Picking list not found")

    if pl.status != PickingListStatus.ACTIVE:
        raise ValueError(f"Can only delete active batches (current: {pl.status})")

    order_ids = set(i.order_id for i in pl.items)
    item_count = len(pl.items)

    # Reset orders back to pending
    for order_id in order_ids:
        order = db.query(Order).filter(Order.id == order_id).first()
        if order and order.status in (OrderStatus.PROCESSING, OrderStatus.PACKING, OrderStatus.PACKED):
            order.status = OrderStatus.PENDING

    # Delete picking list (cascade deletes pick items)
    db.delete(pl)
    db.commit()

    return {
        "deleted_picking_list": picking_list_id,
        "orders_released": len(order_ids),
        "items_removed": item_count,
    }


def remove_order_from_picking_list(db: Session, picking_list_id: str, order_id: str) -> dict:
    """Remove a single order from a picking list (unpack order from batch). Only active batches."""
    pl = db.query(PickingList).filter(PickingList.id == picking_list_id).first()
    if not pl:
        raise ValueError("Picking list not found")

    if pl.status != PickingListStatus.ACTIVE:
        raise ValueError(f"Can only unpack orders from active batches (current: {pl.status})")

    items_to_remove = db.query(PickItem).filter(
        PickItem.picking_list_id == picking_list_id,
        PickItem.order_id == order_id,
    ).all()

    if not items_to_remove:
        raise ValueError("Order not found in this picking list")

    removed_count = len(items_to_remove)
    for item in items_to_remove:
        db.delete(item)

    # Reset order status back to pending
    order = db.query(Order).filter(Order.id == order_id).first()
    if order and order.status in (OrderStatus.PROCESSING, OrderStatus.PACKING, OrderStatus.PACKED):
        order.status = OrderStatus.PENDING

    db.commit()

    # Check if picking list is now empty
    remaining = db.query(PickItem).filter(PickItem.picking_list_id == picking_list_id).count()
    if remaining == 0:
        db.delete(pl)
        db.commit()
        return {
            "order_id": order_id,
            "items_removed": removed_count,
            "picking_list_deleted": True,
        }

    return {
        "order_id": order_id,
        "items_removed": removed_count,
        "picking_list_deleted": False,
    }


def get_picking_list_progress(db: Session, picking_list_id: str) -> list[dict]:
    """Get per-order progress for a picking list."""
    items = db.query(PickItem).filter(PickItem.picking_list_id == picking_list_id).all()
    if not items:
        return []

    # Group by order
    orders_map: dict[str, dict] = {}
    for item in items:
        if item.order_id not in orders_map:
            order = db.query(Order).filter(Order.id == item.order_id).first()
            orders_map[item.order_id] = {
                "order_id": item.order_id,
                "order_number": order.order_number if order else "",
                "order_name": order.order_name if order else "",
                "customer_name": order.customer_name if order else "",
                "order_status": order.status if order else "",
                "label_url": order.label_url if order else "",
                "tracking_number": order.tracking_number if order else "",
                "total": 0,
                "picked": 0,
                "items": [],
            }
        orders_map[item.order_id]["total"] += 1
        if item.picked:
            orders_map[item.order_id]["picked"] += 1
        orders_map[item.order_id]["items"].append({
            "id": item.id,
            "sku": item.sku,
            "product_name": item.product_name,
            "variant_label": item.variant_label,
            "sequence": item.sequence,
            "qr_code": item.qr_code,
            "picked": item.picked,
            "picked_at": item.picked_at.isoformat() if item.picked_at else None,
        })

    return list(orders_map.values())


def check_batch_done(db: Session, order_id: str) -> None:
    """Check if all orders in the batch are drop_off; if so, mark batch as done."""
    # Find the batch this order belongs to
    pick_item = (
        db.query(PickItem)
        .join(PickingList)
        .filter(
            PickItem.order_id == order_id,
            PickingList.status == PickingListStatus.PROCESSING,
        )
        .first()
    )
    if not pick_item:
        return

    pl = db.query(PickingList).filter(PickingList.id == pick_item.picking_list_id).first()
    if not pl:
        return

    # Get all unique order IDs in this batch
    batch_order_ids = {
        row[0] for row in
        db.query(PickItem.order_id).filter(PickItem.picking_list_id == pl.id).distinct().all()
    }

    # Check if all orders are drop_off (or later)
    drop_off_statuses = {OrderStatus.DROP_OFF, OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED}
    all_done = True
    for oid in batch_order_ids:
        order = db.query(Order).filter(Order.id == oid).first()
        if not order or order.status not in drop_off_statuses:
            all_done = False
            break

    if all_done:
        pl.status = PickingListStatus.DONE
        db.commit()
