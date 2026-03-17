from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inventory_log import InventoryLog
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, Variant
from app.models.stock_request import StockRequestItem


def inventory_summary(db: Session) -> dict:
    products = db.query(Product).all()
    total_products = len(products)
    total_units = sum(p.quantity for p in products)
    total_value = sum(p.quantity * p.price for p in products)
    low_stock = [p for p in products if p.quantity <= 5]

    return {
        "total_products": total_products,
        "total_units_in_stock": total_units,
        "total_inventory_value": round(total_value, 2),
        "low_stock_count": len(low_stock),
        "low_stock_items": [
            {"sku": p.sku, "name": p.name, "quantity": p.quantity} for p in low_stock
        ],
        "by_category": _group_by_category(products),
    }


def _group_by_category(products: list[Product]) -> list[dict]:
    cats: dict[str, dict] = {}
    for p in products:
        cat = p.category or "Uncategorized"
        if cat not in cats:
            cats[cat] = {"category": cat, "product_count": 0, "total_units": 0, "total_value": 0.0}
        cats[cat]["product_count"] += 1
        cats[cat]["total_units"] += p.quantity
        cats[cat]["total_value"] += p.quantity * p.price
    for v in cats.values():
        v["total_value"] = round(v["total_value"], 2)
    return list(cats.values())


def order_summary(db: Session, start_date: datetime | None = None, end_date: datetime | None = None, customer_id: str | None = None) -> dict:
    q = db.query(Order)
    if start_date:
        q = q.filter(Order.created_at >= start_date)
    if end_date:
        q = q.filter(Order.created_at <= end_date)
    if customer_id:
        q = q.filter(Order.customer_id == customer_id)

    orders = q.all()
    total = len(orders)
    by_status: dict[str, int] = {}
    total_revenue = 0.0
    total_shipping = 0.0
    total_processing = 0.0
    total_items = 0

    for o in orders:
        status_val = o.status if isinstance(o.status, str) else o.status.value
        by_status[status_val] = by_status.get(status_val, 0) + 1
        total_revenue += o.total_price
        total_shipping += o.shipping_cost
        total_processing += o.processing_fee
        total_items += sum(item.quantity for item in o.items)

    # Orders grouped by date for chart
    orders_by_date: dict[str, int] = {}
    for o in orders:
        d = o.created_at.strftime("%Y-%m-%d") if o.created_at else "Unknown"
        orders_by_date[d] = orders_by_date.get(d, 0) + 1
    sorted_dates = sorted(orders_by_date.keys())
    orders_by_date_sorted = [{"date": d, "count": orders_by_date[d]} for d in sorted_dates]

    # Invoice summary for filtered orders
    invoice_ids = set()
    for o in orders:
        if o.invoice_id:
            invoice_ids.add(o.invoice_id)

    from app.models.invoice import Invoice
    invoices = db.query(Invoice).filter(Invoice.id.in_(invoice_ids)).all() if invoice_ids else []
    total_invoices = len(invoices)

    return {
        "total_orders": total,
        "total_items": total_items,
        "orders_by_status": by_status,
        "total_revenue": round(total_revenue, 2),
        "total_shipping_cost": round(total_shipping, 2),
        "total_processing_fees": round(total_processing, 2),
        "total_invoices": total_invoices,
        "orders_by_date": orders_by_date_sorted,
        "date_range": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
    }


def top_products(db: Session, limit: int = 10) -> list[dict]:
    results = (
        db.query(
            OrderItem.product_id,
            OrderItem.sku,
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("total_sold"),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label("total_revenue"),
        )
        .group_by(OrderItem.product_id, OrderItem.sku, OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "product_id": r.product_id,
            "sku": r.sku,
            "name": r.product_name,
            "total_sold": int(r.total_sold),
            "total_revenue": round(float(r.total_revenue), 2),
        }
        for r in results
    ]


def inventory_overview(db: Session) -> list[dict]:
    """Per-product/variant breakdown: requested, received, sold, adjustments, current stock,
    plus inventory breakdown (on_hold, available, in_production, shipped)."""

    # Pre-compute order-item quantities grouped by status category
    ON_HOLD_STATUSES = [OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.LABEL_PURCHASED]
    IN_PRODUCTION_STATUSES = [OrderStatus.PACKING, OrderStatus.PACKED]
    SHIPPED_STATUSES = [OrderStatus.DROP_OFF, OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED]

    def _qty_map(statuses):
        rows = (
            db.query(OrderItem.product_id, OrderItem.variant_id, func.sum(OrderItem.quantity).label("total"))
            .join(Order)
            .filter(Order.status.in_(statuses))
            .group_by(OrderItem.product_id, OrderItem.variant_id)
            .all()
        )
        return {(r.product_id, r.variant_id or ""): int(r.total) for r in rows}

    on_hold_map = _qty_map(ON_HOLD_STATUSES)
    in_prod_map = _qty_map(IN_PRODUCTION_STATUSES)
    shipped_map = _qty_map(SHIPPED_STATUSES)

    products = db.query(Product).all()
    result = []

    for p in products:
        has_variants = len(p.variants) > 0

        if has_variants:
            for v in p.variants:
                # Total requested from stock requests
                requested = (
                    db.query(func.coalesce(func.sum(StockRequestItem.quantity_requested), 0))
                    .filter(StockRequestItem.variant_id == v.id)
                    .scalar()
                )
                # Total received from stock requests
                received = (
                    db.query(func.coalesce(func.sum(StockRequestItem.quantity_received), 0))
                    .filter(StockRequestItem.variant_id == v.id)
                    .scalar()
                )
                # Total sold (negative inventory logs with reason='order')
                sold = abs(
                    db.query(func.coalesce(func.sum(InventoryLog.change), 0))
                    .filter(
                        InventoryLog.product_id == p.id,
                        InventoryLog.reason == "order",
                        InventoryLog.note.like(f"%{v.variant_sku}%"),
                    )
                    .scalar()
                )
                # Total adjustments
                adjusted = (
                    db.query(func.coalesce(func.sum(InventoryLog.change), 0))
                    .filter(
                        InventoryLog.product_id == p.id,
                        InventoryLog.reason == "adjustment",
                        InventoryLog.note.like(f"%{v.variant_sku}%"),
                    )
                    .scalar()
                )

                import json
                attrs = json.loads(v.attributes) if isinstance(v.attributes, str) else v.attributes
                variant_label = " / ".join(attrs.values()) if attrs else ""

                key = (p.id, v.id)
                result.append({
                    "product_id": p.id,
                    "variant_id": v.id,
                    "sku": p.sku,
                    "variant_sku": v.variant_sku,
                    "name": p.name,
                    "category": p.category,
                    "variant_label": variant_label,
                    "requested": int(requested),
                    "received": int(received),
                    "sold": int(sold),
                    "adjusted": int(adjusted),
                    "current_stock": v.quantity,
                    "location": v.location or p.location,
                    "on_hold": on_hold_map.get(key, 0),
                    "available": v.quantity,
                    "in_production": in_prod_map.get(key, 0),
                    "shipped": shipped_map.get(key, 0),
                })
        else:
            # Product without variants
            requested = (
                db.query(func.coalesce(func.sum(StockRequestItem.quantity_requested), 0))
                .filter(StockRequestItem.product_id == p.id, StockRequestItem.variant_id == "")
                .scalar()
            )
            received = (
                db.query(func.coalesce(func.sum(StockRequestItem.quantity_received), 0))
                .filter(StockRequestItem.product_id == p.id, StockRequestItem.variant_id == "")
                .scalar()
            )
            sold = abs(
                db.query(func.coalesce(func.sum(InventoryLog.change), 0))
                .filter(InventoryLog.product_id == p.id, InventoryLog.reason == "order")
                .scalar()
            )
            adjusted = (
                db.query(func.coalesce(func.sum(InventoryLog.change), 0))
                .filter(InventoryLog.product_id == p.id, InventoryLog.reason == "adjustment")
                .scalar()
            )

            key = (p.id, "")
            result.append({
                "product_id": p.id,
                "variant_id": "",
                "sku": p.sku,
                "variant_sku": "",
                "name": p.name,
                "category": p.category,
                "variant_label": "",
                "requested": int(requested),
                "received": int(received),
                "sold": int(sold),
                "adjusted": int(adjusted),
                "current_stock": p.quantity,
                "location": p.location,
                "on_hold": on_hold_map.get(key, 0),
                "available": p.quantity,
                "in_production": in_prod_map.get(key, 0),
                "shipped": shipped_map.get(key, 0),
            })

    return result


def batch_report(db: Session, date: str | None = None, assigned_to: str | None = None) -> dict:
    """Batch performance report: completed today, new today, in-progress, pending.
    Includes productivity metrics: orders/hour, items/hour, working time per staff."""
    from app.models.picking import PickingList, PickingListStatus, PickItem

    q = db.query(PickingList).filter(PickingList.status != PickingListStatus.ARCHIVED)
    all_batches = q.all()

    # Determine the target date for filtering
    if date:
        target_date = datetime.fromisoformat(date).date()
    else:
        target_date = datetime.utcnow().date()

    target_start = datetime.combine(target_date, datetime.min.time())
    target_end = datetime.combine(target_date, datetime.max.time())

    def _naive(dt: datetime) -> datetime:
        """Strip timezone info so comparisons with naive target_start/target_end work."""
        return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

    # Categorize batches
    done_today = []
    new_today = []
    in_progress = []
    pending = []

    for batch in all_batches:
        items = batch.items
        total_items = len(items)
        picked_items = sum(1 for i in items if i.picked)
        order_ids = set(i.order_id for i in items)

        # Calculate working time: first picked_at to last picked_at
        picked_times = [i.picked_at for i in items if i.picked and i.picked_at]
        first_pick = min(picked_times) if picked_times else None
        last_pick = max(picked_times) if picked_times else None
        working_seconds = (last_pick - first_pick).total_seconds() if first_pick and last_pick and first_pick != last_pick else 0
        working_hours = working_seconds / 3600 if working_seconds > 0 else 0

        # Productivity
        orders_per_hour = len(order_ids) / working_hours if working_hours > 0 else 0
        items_per_hour = picked_items / working_hours if working_hours > 0 else 0

        batch_info = {
            "id": batch.id,
            "picking_number": batch.picking_number,
            "status": batch.status if isinstance(batch.status, str) else batch.status.value,
            "priority": batch.priority or "normal",
            "assigned_to": batch.assigned_to or "",
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "order_count": len(order_ids),
            "total_items": total_items,
            "picked_items": picked_items,
            "first_pick_at": first_pick.isoformat() if first_pick else None,
            "last_pick_at": last_pick.isoformat() if last_pick else None,
            "working_seconds": round(working_seconds),
            "working_time": _format_duration(working_seconds),
            "orders_per_hour": round(orders_per_hour, 1),
            "items_per_hour": round(items_per_hour, 1),
        }

        # Filter by assigned_to if specified
        if assigned_to and batch.assigned_to != assigned_to:
            continue

        status_val = batch.status if isinstance(batch.status, str) else batch.status.value

        # Done today: status=done AND has picks on target date
        if status_val == "done":
            if picked_times and any(target_start <= _naive(t) <= target_end for t in picked_times):
                done_today.append(batch_info)
            elif not date:
                # Include all done batches if no date filter
                done_today.append(batch_info)

        # New today: created on target date
        if batch.created_at and target_start <= _naive(batch.created_at) <= target_end:
            new_today.append(batch_info)

        # In progress (processing)
        if status_val == "processing":
            in_progress.append(batch_info)

        # Pending (active = not started yet)
        if status_val == "active":
            pending.append(batch_info)

    # Staff summary
    staff_map: dict[str, dict] = {}
    for batch in all_batches:
        if not batch.assigned_to:
            continue
        if assigned_to and batch.assigned_to != assigned_to:
            continue

        items = batch.items
        picked_times = [i.picked_at for i in items if i.picked and i.picked_at]

        # Only count batches that had activity on target date
        day_picks = [t for t in picked_times if target_start <= _naive(t) <= target_end]
        if not day_picks:
            continue

        user = batch.assigned_to
        if user not in staff_map:
            staff_map[user] = {
                "username": user,
                "batches_done": 0,
                "total_orders": 0,
                "total_items_picked": 0,
                "total_working_seconds": 0,
            }

        status_val = batch.status if isinstance(batch.status, str) else batch.status.value
        if status_val == "done":
            staff_map[user]["batches_done"] += 1

        order_ids = set(i.order_id for i in items)
        staff_map[user]["total_orders"] += len(order_ids)
        staff_map[user]["total_items_picked"] += len(day_picks)

        first_day = min(day_picks)
        last_day = max(day_picks)
        if first_day != last_day:
            staff_map[user]["total_working_seconds"] += (last_day - first_day).total_seconds()

    staff_summary = []
    for s in staff_map.values():
        hrs = s["total_working_seconds"] / 3600 if s["total_working_seconds"] > 0 else 0
        s["working_time"] = _format_duration(s["total_working_seconds"])
        s["orders_per_hour"] = round(s["total_orders"] / hrs, 1) if hrs > 0 else 0
        s["items_per_hour"] = round(s["total_items_picked"] / hrs, 1) if hrs > 0 else 0
        staff_summary.append(s)

    staff_summary.sort(key=lambda x: x["total_items_picked"], reverse=True)

    return {
        "date": target_date.isoformat(),
        "done_today": done_today,
        "new_today": new_today,
        "in_progress": in_progress,
        "pending": pending,
        "summary": {
            "done_count": len(done_today),
            "new_count": len(new_today),
            "in_progress_count": len(in_progress),
            "pending_count": len(pending),
        },
        "staff_summary": staff_summary,
    }


def _format_duration(seconds: float) -> str:
    """Format seconds into human readable duration like '2h 15m'."""
    if seconds <= 0:
        return "—"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def inventory_breakdown(db: Session) -> dict:
    """Break down inventory into categories based on order status.

    - on_hold: items in orders with status confirmed, processing, label_purchased
    - available: current stock (product/variant quantity) — ready for new orders
    - in_production: items in orders with status packing, packed
    - shipped: items in orders with status drop_off, shipped, in_transit, delivered
    """
    ON_HOLD_STATUSES = [
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.LABEL_PURCHASED,
    ]
    IN_PRODUCTION_STATUSES = [
        OrderStatus.PACKING,
        OrderStatus.PACKED,
    ]
    SHIPPED_STATUSES = [
        OrderStatus.DROP_OFF,
        OrderStatus.SHIPPED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELIVERED,
    ]

    def _qty_by_statuses(statuses: list[OrderStatus]) -> dict[tuple[str, str], int]:
        """Return {(product_id, variant_id): total_qty} for order items in given statuses."""
        rows = (
            db.query(
                OrderItem.product_id,
                OrderItem.variant_id,
                func.sum(OrderItem.quantity).label("total"),
            )
            .join(Order)
            .filter(Order.status.in_(statuses))
            .group_by(OrderItem.product_id, OrderItem.variant_id)
            .all()
        )
        return {(r.product_id, r.variant_id or ""): int(r.total) for r in rows}

    on_hold_map = _qty_by_statuses(ON_HOLD_STATUSES)
    in_prod_map = _qty_by_statuses(IN_PRODUCTION_STATUSES)
    shipped_map = _qty_by_statuses(SHIPPED_STATUSES)

    products = db.query(Product).all()
    items = []
    totals = {"on_hold": 0, "available": 0, "in_production": 0, "shipped": 0}

    for p in products:
        has_variants = len(p.variants) > 0

        if has_variants:
            for v in p.variants:
                key = (p.id, v.id)
                on_hold = on_hold_map.get(key, 0)
                in_prod = in_prod_map.get(key, 0)
                shipped = shipped_map.get(key, 0)
                available = v.quantity

                import json as _json
                attrs = _json.loads(v.attributes) if isinstance(v.attributes, str) else v.attributes
                variant_label = " / ".join(attrs.values()) if attrs else ""

                items.append({
                    "product_id": p.id,
                    "variant_id": v.id,
                    "sku": p.sku,
                    "variant_sku": v.variant_sku,
                    "name": p.name,
                    "category": p.category,
                    "variant_label": variant_label,
                    "on_hold": on_hold,
                    "available": available,
                    "in_production": in_prod,
                    "shipped": shipped,
                })
                totals["on_hold"] += on_hold
                totals["available"] += available
                totals["in_production"] += in_prod
                totals["shipped"] += shipped
        else:
            key = (p.id, "")
            on_hold = on_hold_map.get(key, 0)
            in_prod = in_prod_map.get(key, 0)
            shipped = shipped_map.get(key, 0)
            available = p.quantity

            items.append({
                "product_id": p.id,
                "variant_id": "",
                "sku": p.sku,
                "variant_sku": "",
                "name": p.name,
                "category": p.category,
                "variant_label": "",
                "on_hold": on_hold,
                "available": available,
                "in_production": in_prod,
                "shipped": shipped,
            })
            totals["on_hold"] += on_hold
            totals["available"] += available
            totals["in_production"] += in_prod
            totals["shipped"] += shipped

    return {
        "totals": totals,
        "items": items,
    }


def inventory_movement(
    db: Session,
    product_id: str | None = None,
    reason: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    q = db.query(InventoryLog)
    if product_id:
        q = q.filter(InventoryLog.product_id == product_id)
    if reason:
        q = q.filter(InventoryLog.reason == reason)

    total = q.count()
    logs = q.order_by(InventoryLog.created_at.desc()).offset(offset).limit(limit).all()

    # Pre-fetch product names/SKUs
    product_ids = list({log.product_id for log in logs})
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {p.id: p for p in products}

    items = []
    for log in logs:
        p = products_map.get(log.product_id)
        items.append({
            "id": log.id,
            "product_id": log.product_id,
            "sku": p.sku if p else "",
            "product_name": p.name if p else "",
            "change": log.change,
            "reason": log.reason,
            "reference_id": log.reference_id,
            "balance_after": log.balance_after,
            "note": log.note,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return {"total": total, "items": items}
