from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inventory_log import InventoryLog
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, Variant
from app.models.stock_request import StockRequest, StockRequestItem, StockRequestStatus


def order_time_metrics(
    db: Session,
    start_date: str | None = None,
    end_date: str | None = None,
    group_by: str = "daily",
) -> dict:
    """Calculate average order processing time metrics grouped by day or month.

    Metrics (all measured from confirmed timestamp):
    - confirmed_time: confirmed → processing
    - processing_time: confirmed → packed
    - drop_off_time: confirmed → drop_off
    - shipped_time: confirmed → shipped
    - delivered_time: confirmed → delivered
    """
    import json
    from datetime import timedelta

    today = datetime.now(timezone.utc).date()
    if end_date:
        end_d = datetime.fromisoformat(end_date).date()
    else:
        end_d = today
    if start_date:
        start_d = datetime.fromisoformat(start_date).date()
    else:
        start_d = end_d - timedelta(days=29)

    orders = db.query(Order).all()

    TARGET_STATUSES = ["processing", "packed", "drop_off", "shipped", "delivered"]
    METRIC_NAMES = {
        "processing": "confirmed_time",
        "packed": "processing_time",
        "drop_off": "drop_off_time",
        "shipped": "shipped_time",
        "delivered": "delivered_time",
    }

    # Collect per-order durations keyed by the date the order was confirmed
    # { group_key: { metric_name: [hours, ...] } }
    from collections import defaultdict
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for order in orders:
        try:
            history = json.loads(order.status_history) if order.status_history else []
        except (json.JSONDecodeError, TypeError):
            continue
        if not history:
            continue

        # Find confirmed timestamp
        confirmed_ts = None
        status_timestamps: dict[str, datetime] = {}
        for entry in history:
            status = entry.get("status", "")
            ts_str = entry.get("timestamp", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, TypeError):
                continue

            if status == "confirmed" and confirmed_ts is None:
                confirmed_ts = ts
            if status in TARGET_STATUSES and status not in status_timestamps:
                status_timestamps[status] = ts

        if not confirmed_ts:
            continue

        confirmed_date = confirmed_ts.date()
        if confirmed_date < start_d or confirmed_date > end_d:
            continue

        if group_by == "monthly":
            group_key = confirmed_date.strftime("%Y-%m")
        else:
            group_key = confirmed_date.isoformat()

        for status, metric_name in METRIC_NAMES.items():
            if status in status_timestamps:
                delta_hours = (status_timestamps[status] - confirmed_ts).total_seconds() / 3600
                if delta_hours >= 0:
                    grouped[group_key][metric_name].append(delta_hours)

    # Build date/month series
    if group_by == "monthly":
        keys = set()
        d = start_d.replace(day=1)
        while d <= end_d:
            keys.add(d.strftime("%Y-%m"))
            if d.month == 12:
                d = d.replace(year=d.year + 1, month=1)
            else:
                d = d.replace(month=d.month + 1)
        sorted_keys = sorted(keys)
    else:
        sorted_keys = []
        d = start_d
        while d <= end_d:
            sorted_keys.append(d.isoformat())
            d += timedelta(days=1)

    all_metric_names = list(METRIC_NAMES.values())
    chart = []
    for key in sorted_keys:
        entry = {"date": key}
        bucket = grouped.get(key, {})
        for mn in all_metric_names:
            values = bucket.get(mn, [])
            entry[mn + "_avg"] = round(sum(values) / len(values), 2) if values else None
            entry[mn + "_count"] = len(values)
        chart.append(entry)

    # Overall averages
    overall: dict[str, dict] = {}
    for mn in all_metric_names:
        all_vals = []
        for bucket in grouped.values():
            all_vals.extend(bucket.get(mn, []))
        overall[mn] = {
            "avg_hours": round(sum(all_vals) / len(all_vals), 2) if all_vals else None,
            "count": len(all_vals),
        }

    return {
        "group_by": group_by,
        "date_range": {"start": start_d.isoformat(), "end": end_d.isoformat()},
        "overall": overall,
        "chart": chart,
    }


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
    SHIPPED_STATUSES = {
        OrderStatus.DROP_OFF, OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED,
    }

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
    shipped_items = 0

    for o in orders:
        status_val = o.status if isinstance(o.status, str) else o.status.value
        by_status[status_val] = by_status.get(status_val, 0) + 1
        total_revenue += o.total_price
        total_shipping += o.shipping_cost
        total_processing += o.processing_fee
        items_qty = sum(item.quantity for item in o.items)
        total_items += items_qty
        if status_val in {s.value if not isinstance(s, str) else s for s in SHIPPED_STATUSES}:
            shipped_items += items_qty

    # Shipped items by updated_at: orders shipped (status changed) within the date range
    # This catches orders created before the date range but shipped within it
    shipped_items_by_ship_date = 0
    if start_date or end_date:
        sq = db.query(Order).filter(
            Order.status.in_(list(SHIPPED_STATUSES))
        )
        if customer_id:
            sq = sq.filter(Order.customer_id == customer_id)
        if start_date:
            sq = sq.filter(Order.updated_at >= start_date)
        if end_date:
            sq = sq.filter(Order.updated_at <= end_date)
        for o in sq.all():
            shipped_items_by_ship_date += sum(item.quantity for item in o.items)
    else:
        shipped_items_by_ship_date = shipped_items

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
        "shipped_items": shipped_items_by_ship_date,
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

    # Pre-compute cumulative gap per product from adjustment logs
    gap_rows = (
        db.query(InventoryLog.product_id, func.coalesce(func.sum(InventoryLog.gap), 0).label("total_gap"))
        .filter(InventoryLog.reason == "adjustment")
        .group_by(InventoryLog.product_id)
        .all()
    )
    gap_map = {r.product_id: int(r.total_gap) for r in gap_rows}

    # Pre-compute pending quantities from active stock requests
    ACTIVE_SR_STATUSES = [StockRequestStatus.PENDING, StockRequestStatus.APPROVED, StockRequestStatus.RECEIVING]
    pending_rows = (
        db.query(
            StockRequestItem.product_id,
            StockRequestItem.variant_id,
            func.sum(StockRequestItem.quantity_requested - StockRequestItem.quantity_received).label("pending"),
        )
        .join(StockRequest)
        .filter(StockRequest.status.in_(ACTIVE_SR_STATUSES))
        .group_by(StockRequestItem.product_id, StockRequestItem.variant_id)
        .all()
    )
    pending_map = {(r.product_id, r.variant_id or ""): max(int(r.pending), 0) for r in pending_rows}

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
                on_hold = on_hold_map.get(key, 0)
                available = v.quantity
                in_warehouse = available + on_hold
                pending = pending_map.get(key, 0)
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
                    "on_hold": on_hold,
                    "available": available,
                    "in_warehouse": in_warehouse,
                    "in_production": in_prod_map.get(key, 0),
                    "shipped": shipped_map.get(key, 0),
                    "gap": gap_map.get(p.id, 0),
                    "pending": pending,
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
            on_hold = on_hold_map.get(key, 0)
            available = p.quantity
            in_warehouse = available + on_hold
            pending = pending_map.get(key, 0)
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
                "on_hold": on_hold,
                "available": available,
                "in_warehouse": in_warehouse,
                "in_production": in_prod_map.get(key, 0),
                "shipped": shipped_map.get(key, 0),
                "gap": gap_map.get(p.id, 0),
                "pending": pending,
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


def batch_daily_chart(db: Session, start_date: str | None = None, end_date: str | None = None) -> dict:
    """Daily chart data for batches: orders & items dropped off, and working time per day.

    Returns per-day totals and per-staff breakdowns so the frontend can toggle grouping.
    """
    import json
    from app.models.picking import PickingList, PickingListStatus, PickItem

    today = datetime.utcnow().date()
    if end_date:
        end_d = datetime.fromisoformat(end_date).date()
    else:
        end_d = today
    if start_date:
        start_d = datetime.fromisoformat(start_date).date()
    else:
        start_d = end_d  # default: single day

    # --- Drop-off data: scan order status_history for drop_off transitions ---
    orders = db.query(Order).all()
    # Map order_id -> list of item quantities (for counting items)
    order_items_qty: dict[str, int] = {}
    for oi in db.query(OrderItem).all():
        order_items_qty[oi.order_id] = order_items_qty.get(oi.order_id, 0) + oi.quantity

    # Build day -> {total drop-off orders, total drop-off items, per-staff}
    from collections import defaultdict
    day_data: dict[str, dict] = {}

    # Initialize all days in range
    d = start_d
    while d <= end_d:
        ds = d.isoformat()
        day_data[ds] = {
            "date": ds,
            "drop_off_orders": 0,
            "drop_off_items": 0,
            "staff": defaultdict(lambda: {"drop_off_orders": 0, "drop_off_items": 0, "working_seconds": 0}),
        }
        d += __import__("datetime").timedelta(days=1)

    # Find which orders were dropped off on which day, and by whom (via batch assignment)
    # Build order_id -> assigned_to from picking lists
    pick_items = db.query(PickItem).all()
    order_to_staff: dict[str, str] = {}
    pl_map: dict[str, PickingList] = {}
    for pi in pick_items:
        if pi.picking_list_id not in pl_map:
            pl_map[pi.picking_list_id] = pi.picking_list
        pl = pl_map[pi.picking_list_id]
        if pl and pl.assigned_to:
            order_to_staff[pi.order_id] = pl.assigned_to

    for order in orders:
        try:
            history = json.loads(order.status_history) if order.status_history else []
        except (json.JSONDecodeError, TypeError):
            history = []
        for entry in history:
            if entry.get("status") == "drop_off":
                ts = entry.get("timestamp", "")
                try:
                    drop_date = datetime.fromisoformat(ts).date() if ts else None
                except (ValueError, TypeError):
                    drop_date = None
                if drop_date and start_d <= drop_date <= end_d:
                    ds = drop_date.isoformat()
                    if ds in day_data:
                        items_count = order_items_qty.get(order.id, 0)
                        day_data[ds]["drop_off_orders"] += 1
                        day_data[ds]["drop_off_items"] += items_count
                        staff = order_to_staff.get(order.id, "unassigned")
                        day_data[ds]["staff"][staff]["drop_off_orders"] += 1
                        day_data[ds]["staff"][staff]["drop_off_items"] += items_count
                break  # Only count the first drop_off transition per order

    # --- Working time data: from pick items picked_at ---
    all_batches = db.query(PickingList).filter(PickingList.status != PickingListStatus.ARCHIVED).all()
    for batch in all_batches:
        if not batch.assigned_to:
            continue
        items = batch.items
        picked_times = [i.picked_at for i in items if i.picked and i.picked_at]
        if not picked_times:
            continue

        # Group picks by day
        from collections import defaultdict as _dd
        day_picks: dict[str, list] = _dd(list)
        for t in picked_times:
            t_naive = t.replace(tzinfo=None) if t and t.tzinfo else t
            pd = t_naive.date()
            if start_d <= pd <= end_d:
                day_picks[pd.isoformat()].append(t_naive)

        for ds, times in day_picks.items():
            if ds not in day_data:
                continue
            first = min(times)
            last = max(times)
            secs = (last - first).total_seconds() if first != last else 0
            day_data[ds]["staff"][batch.assigned_to]["working_seconds"] += secs

    # Build response
    chart = []
    for ds in sorted(day_data.keys()):
        dd = day_data[ds]
        total_working = sum(s["working_seconds"] for s in dd["staff"].values())
        staff_list = []
        for uname, sdata in dd["staff"].items():
            staff_list.append({
                "username": uname,
                "drop_off_orders": sdata["drop_off_orders"],
                "drop_off_items": sdata["drop_off_items"],
                "working_seconds": round(sdata["working_seconds"]),
                "working_minutes": round(sdata["working_seconds"] / 60, 1),
            })
        staff_list.sort(key=lambda x: x["username"])
        chart.append({
            "date": ds,
            "drop_off_orders": dd["drop_off_orders"],
            "drop_off_items": dd["drop_off_items"],
            "working_seconds": round(total_working),
            "working_minutes": round(total_working / 60, 1),
            "staff": staff_list,
        })

    return {"chart": chart}


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
    totals = {"on_hold": 0, "available": 0, "in_warehouse": 0, "in_production": 0, "shipped": 0, "gap": 0, "pending": 0}

    # Pre-compute pending quantities from active stock requests
    ACTIVE_SR_STATUSES = [StockRequestStatus.PENDING, StockRequestStatus.APPROVED, StockRequestStatus.RECEIVING]
    pending_rows = (
        db.query(
            StockRequestItem.product_id,
            StockRequestItem.variant_id,
            func.sum(StockRequestItem.quantity_requested - StockRequestItem.quantity_received).label("pending"),
        )
        .join(StockRequest)
        .filter(StockRequest.status.in_(ACTIVE_SR_STATUSES))
        .group_by(StockRequestItem.product_id, StockRequestItem.variant_id)
        .all()
    )
    pending_map = {(r.product_id, r.variant_id or ""): max(int(r.pending), 0) for r in pending_rows}

    # Pre-compute cumulative gap per product from adjustment logs
    gap_rows = (
        db.query(InventoryLog.product_id, func.coalesce(func.sum(InventoryLog.gap), 0).label("total_gap"))
        .filter(InventoryLog.reason == "adjustment")
        .group_by(InventoryLog.product_id)
        .all()
    )
    gap_map = {r.product_id: int(r.total_gap) for r in gap_rows}

    for p in products:
        has_variants = len(p.variants) > 0
        product_gap = gap_map.get(p.id, 0)

        if has_variants:
            for v in p.variants:
                key = (p.id, v.id)
                on_hold = on_hold_map.get(key, 0)
                in_prod = in_prod_map.get(key, 0)
                shipped = shipped_map.get(key, 0)
                available = v.quantity
                in_warehouse = available + on_hold
                pending = pending_map.get(key, 0)

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
                    "in_warehouse": in_warehouse,
                    "in_production": in_prod,
                    "shipped": shipped,
                    "gap": product_gap,
                    "pending": pending,
                })
                totals["on_hold"] += on_hold
                totals["available"] += available
                totals["in_warehouse"] += in_warehouse
                totals["in_production"] += in_prod
                totals["shipped"] += shipped
                totals["gap"] += product_gap
                totals["pending"] += pending
        else:
            key = (p.id, "")
            on_hold = on_hold_map.get(key, 0)
            in_prod = in_prod_map.get(key, 0)
            shipped = shipped_map.get(key, 0)
            available = p.quantity
            in_warehouse = available + on_hold
            pending = pending_map.get(key, 0)

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
                "in_warehouse": in_warehouse,
                "in_production": in_prod,
                "shipped": shipped,
                "gap": product_gap,
                "pending": pending,
            })
            totals["on_hold"] += on_hold
            totals["available"] += available
            totals["in_warehouse"] += in_warehouse
            totals["in_production"] += in_prod
            totals["shipped"] += shipped
            totals["gap"] += product_gap
            totals["pending"] += pending

    return {
        "totals": totals,
        "items": items,
    }


def inventory_daily_report(
    db: Session,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Daily inventory report: quantity changes grouped by product, date, and reason."""
    q = db.query(InventoryLog)

    if start_date:
        q = q.filter(InventoryLog.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59)
        q = q.filter(InventoryLog.created_at <= end_dt)

    logs = q.order_by(InventoryLog.created_at.desc()).all()

    # Pre-fetch product info
    product_ids = list({log.product_id for log in logs})
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {p.id: p for p in products}

    # Group by date -> product -> reason
    daily: dict[str, dict[str, dict]] = {}
    for log in logs:
        date_key = log.created_at.strftime("%Y-%m-%d") if log.created_at else "Unknown"
        p = products_map.get(log.product_id)
        product_key = log.product_id

        if date_key not in daily:
            daily[date_key] = {}
        if product_key not in daily[date_key]:
            daily[date_key][product_key] = {
                "product_id": log.product_id,
                "sku": p.sku if p else "",
                "product_name": p.name if p else "",
                "inbound": 0,
                "order": 0,
                "adjustment": 0,
                "gap": 0,
                "net_change": 0,
                "entries": 0,
            }

        entry = daily[date_key][product_key]
        reason = log.reason or "other"
        if reason in ("inbound", "order", "adjustment"):
            entry[reason] += log.change
        entry["net_change"] += log.change
        entry["gap"] += getattr(log, "gap", 0) or 0
        entry["entries"] += 1

    # Build response
    result = []
    for date_key in sorted(daily.keys(), reverse=True):
        items = sorted(daily[date_key].values(), key=lambda x: abs(x["net_change"]), reverse=True)
        day_totals = {"inbound": 0, "order": 0, "adjustment": 0, "gap": 0, "net_change": 0, "entries": 0}
        for item in items:
            day_totals["inbound"] += item["inbound"]
            day_totals["order"] += item["order"]
            day_totals["adjustment"] += item["adjustment"]
            day_totals["gap"] += item["gap"]
            day_totals["net_change"] += item["net_change"]
            day_totals["entries"] += item["entries"]
        result.append({
            "date": date_key,
            "totals": day_totals,
            "items": items,
        })

    return {"days": result}


def inventory_daily_chart(
    db: Session,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Daily inventory chart data: reconstruct historical inventory levels
    by replaying InventoryLog changes backwards from current state,
    and order status_history for on_hold/in_production/shipped."""
    import json as _json
    from datetime import timedelta

    ON_HOLD_STATUSES = {"confirmed", "processing", "label_purchased"}
    IN_PRODUCTION_STATUSES = {"packing", "packed"}
    SHIPPED_STATUSES = {"drop_off", "shipped", "in_transit", "delivered"}

    # Determine date range
    if end_date:
        end_dt = datetime.fromisoformat(end_date).date()
    else:
        end_dt = datetime.utcnow().date()
    if start_date:
        start_dt = datetime.fromisoformat(start_date).date()
    else:
        start_dt = end_dt - timedelta(days=6)

    # Build date series
    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.isoformat())
        current += timedelta(days=1)

    # --- 1. Reconstruct historical 'available' from InventoryLog ---
    # Current available stock
    products = db.query(Product).all()
    current_available = 0
    for p in products:
        if p.variants:
            current_available += sum(v.quantity for v in p.variants)
        else:
            current_available += p.quantity

    # Get daily net changes from inventory logs (all dates from start_date onwards)
    daily_changes_rows = (
        db.query(
            func.date(InventoryLog.created_at).label("log_date"),
            func.coalesce(func.sum(InventoryLog.change), 0).label("net_change"),
            func.coalesce(func.sum(InventoryLog.gap), 0).label("daily_gap"),
        )
        .group_by(func.date(InventoryLog.created_at))
        .all()
    )
    daily_net = {str(r.log_date): int(r.net_change) for r in daily_changes_rows}
    gap_by_date = {str(r.log_date): int(r.daily_gap) for r in daily_changes_rows}

    # Work backwards from current available to reconstruct each day's ending available
    # available[today] = current_available
    # available[day] = available[day+1] - net_change[day+1]
    today = datetime.utcnow().date()
    available_by_date = {}
    running = current_available

    # Build all dates from end_dt back to start_dt, then forward from today
    all_dates_back = []
    d = today
    while d >= start_dt:
        all_dates_back.append(d.isoformat())
        d -= timedelta(days=1)

    # Forward pass: from today to end_dt if end_dt is in the future
    d = today + timedelta(days=1)
    while d <= end_dt:
        all_dates_back.insert(0, d.isoformat())
        d += timedelta(days=1)

    # Start from today's value and go backwards
    running = current_available
    available_by_date[today.isoformat()] = running
    d = today
    while d >= start_dt:
        d_str = d.isoformat()
        if d == today:
            available_by_date[d_str] = running
        else:
            # The next day's available was computed already
            next_d = (d + timedelta(days=1)).isoformat()
            next_day_change = daily_net.get(next_d, 0)
            running = running - next_day_change
            available_by_date[d_str] = running
        d -= timedelta(days=1)

    # For future dates beyond today, use current_available
    d = today + timedelta(days=1)
    while d <= end_dt:
        available_by_date[d.isoformat()] = current_available
        d += timedelta(days=1)

    # --- 2. Reconstruct on_hold / in_production / shipped from order status_history ---
    # Load all orders with their items
    orders = db.query(Order).all()
    order_items_qty = {}
    for o in orders:
        total_qty = sum(item.quantity for item in o.items)
        order_items_qty[o.id] = total_qty

    # For each date, determine what status each order was in at end of that day
    # Parse status_history to find the status at each date
    def _order_status_at_date(order, target_date_str):
        """Get the order status at end of a given date by replaying status_history."""
        target_end = datetime.fromisoformat(target_date_str).replace(hour=23, minute=59, second=59)

        history = []
        raw = order.status_history or "[]"
        try:
            history = _json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            history = []

        if not history:
            # No history; use current status if order was created before target date
            if order.created_at and order.created_at <= target_end:
                return order.status if isinstance(order.status, str) else order.status.value
            return None

        # Find the latest status entry on or before target date
        last_status = None
        for entry in history:
            ts_str = entry.get("timestamp") or entry.get("time") or entry.get("at") or ""
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts = ts.replace(tzinfo=None)  # strip tz for comparison
            except (ValueError, TypeError):
                continue
            if ts <= target_end:
                last_status = entry.get("status") or entry.get("to") or entry.get("new_status")

        return last_status

    # Pre-compute per-date totals
    on_hold_by_date = {}
    in_prod_by_date = {}
    shipped_by_date = {}

    for d_str in dates:
        on_hold = 0
        in_prod = 0
        shipped = 0

        for o in orders:
            qty = order_items_qty.get(o.id, 0)
            if qty == 0:
                continue

            status = _order_status_at_date(o, d_str)
            if not status:
                continue

            if status in ON_HOLD_STATUSES:
                on_hold += qty
            elif status in IN_PRODUCTION_STATUSES:
                in_prod += qty
            elif status in SHIPPED_STATUSES:
                shipped += qty

        on_hold_by_date[d_str] = on_hold
        in_prod_by_date[d_str] = in_prod
        shipped_by_date[d_str] = shipped

    # --- 3. Pending from active stock requests (use current value for all dates) ---
    ACTIVE_SR_STATUSES = [StockRequestStatus.PENDING, StockRequestStatus.APPROVED, StockRequestStatus.RECEIVING]
    total_pending = (
        db.query(func.coalesce(
            func.sum(StockRequestItem.quantity_requested - StockRequestItem.quantity_received), 0
        ))
        .join(StockRequest)
        .filter(StockRequest.status.in_(ACTIVE_SR_STATUSES))
        .scalar()
    )
    total_pending = max(int(total_pending), 0)

    # --- 4. Build chart data ---
    chart_data = []
    for d_str in dates:
        avail = available_by_date.get(d_str, current_available)
        on_hold = on_hold_by_date.get(d_str, 0)
        in_warehouse = avail + on_hold
        chart_data.append({
            "date": d_str,
            "in_warehouse": in_warehouse,
            "available": avail,
            "on_hold": on_hold,
            "in_production": in_prod_by_date.get(d_str, 0),
            "shipped": shipped_by_date.get(d_str, 0),
            "gap": gap_by_date.get(d_str, 0),
            "pending": total_pending,
        })

    return {"chart": chart_data}


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
            "gap": getattr(log, "gap", 0) or 0,
            "note": log.note,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return {"total": total, "items": items}
