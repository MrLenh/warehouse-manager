from sqlalchemy.orm import Session

from app.models.product import Product, Variant
from app.models.stock_adjust_request import StockAdjustRequest
from app.schemas.product import InventoryAdjust, VariantInventoryAdjust
from app.services import product_service


def lookup_for_adjust(db: Session, sku: str) -> dict | None:
    """Look up product/variant by SKU and return current in-warehouse qty."""
    variant = product_service.get_variant_by_sku(db, sku)
    if variant:
        product = product_service.get_product(db, variant.product_id)
        import json as _json
        attrs = variant.attributes
        if isinstance(attrs, str):
            try:
                attrs = _json.loads(attrs)
            except (ValueError, TypeError):
                attrs = {}
        variant_label = " / ".join(str(v) for v in (attrs or {}).values()) if attrs else ""
        return {
            "type": "variant",
            "product_id": product.id,
            "variant_id": variant.id,
            "sku": variant.variant_sku,
            "product_name": product.name,
            "variant_label": variant_label,
            "in_warehouse_qty": variant.quantity,
            "location": variant.location or product.location,
        }
    product = product_service.get_product_by_sku(db, sku)
    if product:
        if product.variants:
            return {
                "error": f"Product '{sku}' has variants. Scan a variant SKU instead.",
                "variants": [v.variant_sku for v in product.variants[:10]],
            }
        return {
            "type": "product",
            "product_id": product.id,
            "variant_id": "",
            "sku": product.sku,
            "product_name": product.name,
            "variant_label": "",
            "in_warehouse_qty": product.quantity,
            "location": product.location,
        }
    return None


def create_stock_adjust_request(
    db: Session,
    sku: str,
    actual_qty: int,
    note: str,
    adjusted_by: str,
) -> StockAdjustRequest:
    """Create a stock adjust request and apply the adjustment to inventory.

    The adjustment goes through product_service.adjust_inventory or
    adjust_variant_inventory which handles FIFO cost tracking.
    """
    info = lookup_for_adjust(db, sku)
    if not info:
        raise ValueError(f"SKU '{sku}' not found")
    if info.get("error"):
        raise ValueError(info["error"])

    in_warehouse = info["in_warehouse_qty"]
    adjust_amount = actual_qty - in_warehouse

    cost_amount = 0.0
    if adjust_amount != 0:
        adjust_data = (
            VariantInventoryAdjust(
                quantity=adjust_amount,
                reason="adjustment",
                note=f"Stock count by {adjusted_by}: {note}".strip(": "),
            )
            if info["type"] == "variant"
            else InventoryAdjust(
                quantity=adjust_amount,
                reason="adjustment",
                note=f"Stock count by {adjusted_by}: {note}".strip(": "),
            )
        )
        if info["type"] == "variant":
            product_service.adjust_variant_inventory(db, info["variant_id"], adjust_data, adjusted_by=adjusted_by)
        else:
            product_service.adjust_inventory(db, info["product_id"], adjust_data, adjusted_by=adjusted_by)
        # Read back the cost from the most recent inventory log
        from app.models.inventory_log import InventoryLog
        last_log = (
            db.query(InventoryLog)
            .filter(InventoryLog.product_id == info["product_id"])
            .order_by(InventoryLog.created_at.desc())
            .first()
        )
        if last_log:
            cost_amount = last_log.cost_amount or 0.0

    req = StockAdjustRequest(
        product_id=info["product_id"],
        variant_id=info["variant_id"],
        sku=info["sku"],
        product_name=info["product_name"],
        variant_label=info["variant_label"],
        in_warehouse_qty=in_warehouse,
        actual_qty=actual_qty,
        adjust_amount=adjust_amount,
        cost_amount=cost_amount,
        adjusted_by=adjusted_by,
        note=note,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def list_stock_adjust_requests(db: Session, skip: int = 0, limit: int = 100) -> list[StockAdjustRequest]:
    return (
        db.query(StockAdjustRequest)
        .order_by(StockAdjustRequest.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
