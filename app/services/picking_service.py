import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.order import Order, OrderItem
from app.models.picking import PickingList, PickItem


def _generate_picking_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = uuid.uuid4().hex[:6].upper()
    return f"PL-{ts}-{rand}"


def create_picking_list(db: Session, order_ids: list[str]) -> PickingList:
    """Create a picking list from selected orders. Generates one PickItem per unit (qty=1)."""
    orders = db.query(Order).filter(Order.id.in_(order_ids)).all()
    if not orders:
        raise ValueError("No valid orders found")

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
    db.commit()
    db.refresh(pick_item)

    # Check order progress in this picking list
    order_items = db.query(PickItem).filter(
        PickItem.picking_list_id == pick_item.picking_list_id,
        PickItem.order_id == pick_item.order_id,
    ).all()
    order_total = len(order_items)
    order_picked = sum(1 for i in order_items if i.picked)

    # Get order info
    order = db.query(Order).filter(Order.id == pick_item.order_id).first()
    order_number = order.order_number if order else ""

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
