import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.inventory_log import InventoryLog
from app.models.stock_batch import StockBatch
from sqlalchemy import func as sa_func

from app.models.customer import Customer
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, Variant
from app.schemas.order import OrderCreate, OrderStatusUpdate, OrderUpdate


def _generate_order_number() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6].upper()
    return f"ORD-{ts}-{short}"


def _consume_batches_fifo(db: Session, product_id: str, variant_id: str, quantity: int) -> None:
    """Consume stock from oldest batches first (FIFO)."""
    batches = (
        db.query(StockBatch)
        .filter(
            StockBatch.product_id == product_id,
            StockBatch.variant_id == (variant_id or ""),
            StockBatch.quantity_remaining > 0,
        )
        .order_by(StockBatch.created_at.asc())
        .all()
    )
    remaining = quantity
    for batch in batches:
        if remaining <= 0:
            break
        consume = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= consume
        remaining -= consume


def _restore_batches_fifo(db: Session, product_id: str, variant_id: str, quantity: int) -> None:
    """Restore stock to newest batches first (reverse FIFO) on order cancellation."""
    batches = (
        db.query(StockBatch)
        .filter(
            StockBatch.product_id == product_id,
            StockBatch.variant_id == (variant_id or ""),
        )
        .order_by(StockBatch.created_at.desc())
        .all()
    )
    remaining = quantity
    for batch in batches:
        if remaining <= 0:
            break
        can_restore = batch.quantity_received - batch.quantity_remaining
        restore = min(can_restore, remaining)
        batch.quantity_remaining += restore
        remaining -= restore


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


def _add_status_history(order: Order, status: str, note: str = "") -> None:
    history = json.loads(order.status_history) if order.status_history else []
    history.append({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": note,
    })
    order.status_history = json.dumps(history)


def create_order(db: Session, data: OrderCreate) -> Order:
    # Check duplicate order_name
    if data.order_name:
        existing = db.query(Order).filter(Order.order_name == data.order_name).first()
        if existing:
            raise ValueError(f"Order name '{data.order_name}' already exists (order {existing.order_number})")

    # Auto-map customer by name (case-insensitive)
    matched_customer = (
        db.query(Customer)
        .filter(sa_func.lower(Customer.name) == data.customer_name.strip().lower())
        .first()
    )

    order = Order(
        order_number=_generate_order_number(),
        order_name=data.order_name,
        customer_name=data.customer_name,
        customer_id=matched_customer.id if matched_customer else None,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        shop_name=data.shop_name,
        ship_to_name=data.ship_to.name,
        ship_to_street1=data.ship_to.street1,
        ship_to_street2=data.ship_to.street2,
        ship_to_city=data.ship_to.city,
        ship_to_state=data.ship_to.state,
        ship_to_zip=data.ship_to.zip,
        ship_to_country=data.ship_to.country,
        carrier=data.carrier or settings.DEFAULT_CARRIER,
        service=data.service or settings.DEFAULT_SERVICE,
        webhook_url=data.webhook_url,
        notes=data.notes,
        status=OrderStatus(data.status) if data.status else OrderStatus.CONFIRMED,
    )

    if data.ship_from:
        order.ship_from_name = data.ship_from.name
        order.ship_from_street1 = data.ship_from.street1
        order.ship_from_city = data.ship_from.city
        order.ship_from_state = data.ship_from.state
        order.ship_from_zip = data.ship_from.zip
        order.ship_from_country = data.ship_from.country
    elif settings.WAREHOUSE_STREET1:
        # Use warehouse config as default ship_from
        order.ship_from_name = settings.WAREHOUSE_NAME
        order.ship_from_street1 = settings.WAREHOUSE_STREET1
        order.ship_from_city = settings.WAREHOUSE_CITY
        order.ship_from_state = settings.WAREHOUSE_STATE
        order.ship_from_zip = settings.WAREHOUSE_ZIP
        order.ship_from_country = settings.WAREHOUSE_COUNTRY

    db.add(order)
    db.flush()

    total_items = 0
    items_subtotal = 0.0
    for item_data in data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if not product:
            raise ValueError(f"Product {item_data.product_id} not found")

        variant = None
        variant_label = ""
        if item_data.variant_id:
            variant = db.query(Variant).filter(
                Variant.id == item_data.variant_id,
                Variant.product_id == product.id,
            ).first()
            if not variant:
                raise ValueError(f"Variant {item_data.variant_id} not found for product {product.sku}")
            if variant.quantity <= 0:
                raise ValueError(f"Variant {variant.variant_sku} is out of stock")
            if variant.quantity < item_data.quantity:
                raise ValueError(f"Insufficient stock for variant {variant.variant_sku}. Available: {variant.quantity}")
            # Build variant label from attributes
            attrs = json.loads(variant.attributes) if isinstance(variant.attributes, str) else variant.attributes
            variant_label = " / ".join(attrs.values()) if attrs else ""
        else:
            if product.quantity <= 0:
                raise ValueError(f"Product {product.sku} is out of stock")
            if product.quantity < item_data.quantity:
                raise ValueError(f"Insufficient stock for {product.sku}. Available: {product.quantity}")

        # Determine price: variant override > product price
        unit_price = product.price
        if variant and variant.price_override > 0:
            unit_price = variant.price_override

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            variant_id=variant.id if variant else "",
            sku=product.sku,
            variant_sku=variant.variant_sku if variant else "",
            variant_label=variant_label,
            name=item_data.item_name,
            product_name=product.name,
            quantity=item_data.quantity,
            unit_price=unit_price,
        )
        db.add(order_item)

        # Deduct inventory from variant or product
        if variant:
            variant.quantity -= item_data.quantity
            log = InventoryLog(
                product_id=product.id,
                change=-item_data.quantity,
                reason="order",
                reference_id=order.id,
                balance_after=variant.quantity,
                note=f"[Variant {variant.variant_sku}] Reserved for order {order.order_number}",
            )
        else:
            product.quantity -= item_data.quantity
            log = InventoryLog(
                product_id=product.id,
                change=-item_data.quantity,
                reason="order",
                reference_id=order.id,
                balance_after=product.quantity,
                note=f"Reserved for order {order.order_number}",
            )
        db.add(log)

        # Consume from oldest stock batches (FIFO)
        _consume_batches_fifo(db, product.id, variant.id if variant else "", item_data.quantity)
        _recalculate_price_from_batches(db, product.id, variant.id if variant else "")
        total_items += item_data.quantity
        items_subtotal += item_data.quantity * unit_price

    # Calculate processing fee: $1.75 first item + $0.50 each additional
    order.processing_fee = (
        settings.PROCESSING_FEE_FIRST_ITEM
        + max(0, total_items - 1) * settings.PROCESSING_FEE_EXTRA_ITEM
    ) if total_items > 0 else 0.0
    order.total_price = items_subtotal + order.processing_fee

    initial_status = OrderStatus(data.status) if data.status else OrderStatus.CONFIRMED
    _add_status_history(order, initial_status, "Order created" + (" (CSV import)" if data.status else ""))

    # Flush items so order.items relationship is available for QR generation
    db.flush()

    # Generate QR code for picking/packing
    try:
        import os

        from app.services.qr_service import generate_order_qr

        qr_bytes = generate_order_qr(order)
        os.makedirs(settings.QR_CODE_DIR, exist_ok=True)
        qr_path = os.path.join(settings.QR_CODE_DIR, f"order-{order.order_number}.png")
        with open(qr_path, "wb") as f:
            f.write(qr_bytes)
        order.qr_code_path = qr_path
    except Exception:
        pass  # QR generation is non-critical, don't block order creation

    db.commit()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: str) -> Order | None:
    return db.query(Order).filter(Order.id == order_id).first()


def get_order_by_number(db: Session, order_number: str) -> Order | None:
    return db.query(Order).filter(Order.order_number == order_number).first()


def get_order_by_tracking(db: Session, tracking_number: str) -> Order | None:
    return db.query(Order).filter(Order.tracking_number == tracking_number).first()


def list_orders(
    db: Session, skip: int = 0, limit: int = 0, status: OrderStatus | None = None,
    search: str | None = None, statuses: list[OrderStatus] | None = None,
) -> list[Order]:
    q = db.query(Order)
    if statuses:
        q = q.filter(Order.status.in_(statuses))
    elif status:
        q = q.filter(Order.status == status)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            Order.order_number.ilike(pattern)
            | Order.order_name.ilike(pattern)
            | Order.customer_name.ilike(pattern)
            | Order.tracking_number.ilike(pattern)
        )
    q = q.order_by(Order.created_at.desc()).offset(skip)
    if limit > 0:
        q = q.limit(limit)
    return q.all()


def update_order_status(db: Session, order_id: str, data: OrderStatusUpdate) -> Order | None:
    order = get_order(db, order_id)
    if not order:
        return None
    order.status = data.status
    _add_status_history(order, data.status.value, data.note)
    db.commit()
    db.refresh(order)
    return order


def update_order(db: Session, order_id: str, data: OrderUpdate) -> Order | None:
    """Update order fields and item names/quantities."""
    order = get_order(db, order_id)
    if not order:
        return None

    # Update order-level fields
    if data.order_name is not None:
        # Check duplicate if changing name
        if data.order_name and data.order_name != order.order_name:
            existing = db.query(Order).filter(Order.order_name == data.order_name, Order.id != order.id).first()
            if existing:
                raise ValueError(f"Order name '{data.order_name}' already exists (order {existing.order_number})")
        order.order_name = data.order_name
    if data.customer_name is not None:
        order.customer_name = data.customer_name
    if data.customer_email is not None:
        order.customer_email = data.customer_email
    if data.customer_phone is not None:
        order.customer_phone = data.customer_phone
    if data.shop_name is not None:
        order.shop_name = data.shop_name
    if data.carrier is not None:
        order.carrier = data.carrier
    if data.service is not None:
        order.service = data.service
    if data.notes is not None:
        order.notes = data.notes

    # Update shipping address
    if data.ship_to:
        if data.ship_to.name is not None:
            order.ship_to_name = data.ship_to.name
        if data.ship_to.street1 is not None:
            order.ship_to_street1 = data.ship_to.street1
        if data.ship_to.street2 is not None:
            order.ship_to_street2 = data.ship_to.street2
        if data.ship_to.city is not None:
            order.ship_to_city = data.ship_to.city
        if data.ship_to.state is not None:
            order.ship_to_state = data.ship_to.state
        if data.ship_to.zip is not None:
            order.ship_to_zip = data.ship_to.zip
        if data.ship_to.country is not None:
            order.ship_to_country = data.ship_to.country

    # Update items (name, quantity)
    if data.items:
        items_by_id = {item.id: item for item in order.items}
        for item_update in data.items:
            order_item = items_by_id.get(item_update.id)
            if not order_item:
                raise ValueError(f"Order item '{item_update.id}' not found in this order")
            if item_update.name is not None:
                order_item.name = item_update.name
            if item_update.quantity is not None and item_update.quantity != order_item.quantity:
                diff = item_update.quantity - order_item.quantity
                # Adjust inventory
                if order_item.variant_id:
                    variant = db.query(Variant).filter(Variant.id == order_item.variant_id).first()
                    if variant:
                        if diff > 0 and variant.quantity < diff:
                            raise ValueError(f"Insufficient stock for variant {variant.variant_sku}. Available: {variant.quantity}")
                        variant.quantity -= diff
                        db.add(InventoryLog(
                            product_id=order_item.product_id,
                            change=-diff,
                            reason="order_updated",
                            reference_id=order.id,
                            balance_after=variant.quantity,
                            note=f"[Variant {variant.variant_sku}] Qty changed {order_item.quantity} → {item_update.quantity} for order {order.order_number}",
                        ))
                else:
                    product = db.query(Product).filter(Product.id == order_item.product_id).first()
                    if product:
                        if diff > 0 and product.quantity < diff:
                            raise ValueError(f"Insufficient stock for {product.sku}. Available: {product.quantity}")
                        product.quantity -= diff
                        db.add(InventoryLog(
                            product_id=product.id,
                            change=-diff,
                            reason="order_updated",
                            reference_id=order.id,
                            balance_after=product.quantity,
                            note=f"Qty changed {order_item.quantity} → {item_update.quantity} for order {order.order_number}",
                        ))
                # Update FIFO batches
                if diff > 0:
                    _consume_batches_fifo(db, order_item.product_id, order_item.variant_id or "", diff)
                elif diff < 0:
                    _restore_batches_fifo(db, order_item.product_id, order_item.variant_id or "", -diff)
                _recalculate_price_from_batches(db, order_item.product_id, order_item.variant_id or "")
                order_item.quantity = item_update.quantity

        # Recalculate pricing
        total_items = sum(item.quantity for item in order.items)
        items_subtotal = sum(item.quantity * item.unit_price for item in order.items)
        order.processing_fee = (
            settings.PROCESSING_FEE_FIRST_ITEM
            + max(0, total_items - 1) * settings.PROCESSING_FEE_EXTRA_ITEM
        ) if total_items > 0 else 0.0
        order.total_price = items_subtotal + order.processing_fee + order.shipping_cost

    db.commit()
    db.refresh(order)
    return order


def delete_order(db: Session, order_id: str) -> bool:
    """Permanently delete an order and restore inventory (admin only)."""
    order = get_order(db, order_id)
    if not order:
        return False

    # Restore inventory if order was not cancelled (already restored) or delivered
    if order.status not in (OrderStatus.CANCELLED,):
        for item in order.items:
            if item.variant_id:
                variant = db.query(Variant).filter(Variant.id == item.variant_id).first()
                if variant:
                    variant.quantity += item.quantity
                    db.add(InventoryLog(
                        product_id=item.product_id,
                        change=item.quantity,
                        reason="order_deleted",
                        reference_id=order.id,
                        balance_after=variant.quantity,
                        note=f"[Variant {variant.variant_sku}] Restored from deleted order {order.order_number}",
                    ))
            else:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    product.quantity += item.quantity
                    db.add(InventoryLog(
                        product_id=product.id,
                        change=item.quantity,
                        reason="order_deleted",
                        reference_id=order.id,
                        balance_after=product.quantity,
                        note=f"Restored from deleted order {order.order_number}",
                    ))
            # Restore FIFO batches and recalculate price
            _restore_batches_fifo(db, item.product_id, item.variant_id or "", item.quantity)
            _recalculate_price_from_batches(db, item.product_id, item.variant_id or "")

    # Delete related pick_items
    from app.models.picking import PickItem
    db.query(PickItem).filter(PickItem.order_id == order.id).delete()

    # Delete the order (order_items cascade-deleted automatically)
    db.delete(order)
    db.commit()
    return True


def merge_orders_by_name(db: Session) -> dict:
    """Find all orders sharing the same order_name and merge them into one order per name.
    Items from duplicate orders are moved to the earliest order; duplicates are deleted.
    Inventory is NOT touched since items were already deducted when each order was created.
    """
    from app.models.picking import PickItem

    # Find order_names that have more than 1 order (ignore empty names)
    dupes = (
        db.query(Order.order_name, sa_func.count(Order.id))
        .filter(Order.order_name != "", Order.order_name.isnot(None))
        .group_by(Order.order_name)
        .having(sa_func.count(Order.id) > 1)
        .all()
    )

    merged_count = 0
    merged_details = []

    for order_name, count in dupes:
        # Get all orders with this name, oldest first
        orders = (
            db.query(Order)
            .filter(Order.order_name == order_name)
            .order_by(Order.created_at.asc())
            .all()
        )
        if len(orders) < 2:
            continue

        primary = orders[0]
        duplicates = orders[1:]
        absorbed_order_numbers = []

        for dup in duplicates:
            # Move items from duplicate to primary
            for item in dup.items:
                item.order_id = primary.id
            db.flush()

            # Remove duplicate from picking lists
            db.query(PickItem).filter(PickItem.order_id == dup.id).delete()

            absorbed_order_numbers.append(dup.order_number)

            # Append notes from duplicate
            if dup.notes and dup.notes not in (primary.notes or ""):
                primary.notes = ((primary.notes + "; ") if primary.notes else "") + dup.notes

            # Delete the duplicate order (items already moved, cascade won't delete them)
            db.delete(dup)

        db.flush()

        # Recalculate processing fee & total for primary
        total_items = sum(item.quantity for item in primary.items)
        items_subtotal = sum(item.quantity * item.unit_price for item in primary.items)
        from app.config import settings
        primary.processing_fee = (
            settings.PROCESSING_FEE_FIRST_ITEM
            + max(0, total_items - 1) * settings.PROCESSING_FEE_EXTRA_ITEM
        ) if total_items > 0 else 0.0
        primary.total_price = items_subtotal + primary.processing_fee + primary.shipping_cost

        _add_status_history(primary, primary.status, f"Merged with orders: {', '.join(absorbed_order_numbers)}")

        merged_count += 1
        merged_details.append({
            "order_name": order_name,
            "primary_order_number": primary.order_number,
            "absorbed_order_numbers": absorbed_order_numbers,
            "total_items": total_items,
        })

    db.commit()
    return {"merged": merged_count, "details": merged_details}


def cancel_order(db: Session, order_id: str) -> Order | None:
    order = get_order(db, order_id)
    if not order:
        return None
    if order.status in (OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED):
        raise ValueError(f"Cannot cancel order in {order.status} status")

    # Refund EasyPost label if purchased
    refund_note = ""
    if order.easypost_shipment_id and order.label_url:
        try:
            from app.services.shipping_service import refund_shipment
            status = refund_shipment(db, order)
            refund_note = f" | Label refund: {status}"
        except Exception as e:
            refund_note = f" | Label refund failed: {e}"

    # Restore inventory
    for item in order.items:
        if item.variant_id:
            variant = db.query(Variant).filter(Variant.id == item.variant_id).first()
            if variant:
                variant.quantity += item.quantity
                log = InventoryLog(
                    product_id=item.product_id,
                    change=item.quantity,
                    reason="order_cancelled",
                    reference_id=order.id,
                    balance_after=variant.quantity,
                    note=f"[Variant {variant.variant_sku}] Restored from cancelled order {order.order_number}",
                )
                db.add(log)
        else:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.quantity += item.quantity
                log = InventoryLog(
                    product_id=product.id,
                    change=item.quantity,
                    reason="order_cancelled",
                    reference_id=order.id,
                    balance_after=product.quantity,
                    note=f"Restored from cancelled order {order.order_number}",
                )
                db.add(log)
        # Restore FIFO batches and recalculate price
        _restore_batches_fifo(db, item.product_id, item.variant_id or "", item.quantity)
        _recalculate_price_from_batches(db, item.product_id, item.variant_id or "")

    # Remove from any active packing list
    from app.models.picking import PickItem, PickingList, PickingListStatus
    pick_items = (
        db.query(PickItem)
        .join(PickingList)
        .filter(
            PickItem.order_id == order.id,
            PickingList.status.in_([PickingListStatus.ACTIVE, PickingListStatus.PROCESSING]),
        )
        .all()
    )
    if pick_items:
        pl_id = pick_items[0].picking_list_id
        for pi in pick_items:
            db.delete(pi)
        db.flush()
        # Delete picking list if now empty
        remaining = db.query(PickItem).filter(PickItem.picking_list_id == pl_id).count()
        if remaining == 0:
            pl = db.query(PickingList).filter(PickingList.id == pl_id).first()
            if pl:
                db.delete(pl)
        refund_note += " | Removed from packing list"

    order.status = OrderStatus.CANCELLED
    _add_status_history(order, OrderStatus.CANCELLED, "Order cancelled" + refund_note)
    db.commit()
    db.refresh(order)
    return order
