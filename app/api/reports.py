from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/inventory")
def inventory_report(db: Session = Depends(get_db)):
    return report_service.inventory_summary(db)


@router.get("/orders")
def orders_report(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    customer_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return report_service.order_summary(db, start_date=start_date, end_date=end_date, customer_id=customer_id)


@router.get("/top-products")
def top_products_report(limit: int = 10, db: Session = Depends(get_db)):
    return report_service.top_products(db, limit=limit)


@router.get("/inventory-overview")
def inventory_overview_report(db: Session = Depends(get_db)):
    return report_service.inventory_overview(db)


@router.get("/inventory-breakdown")
def inventory_breakdown_report(db: Session = Depends(get_db)):
    """Inventory split by order lifecycle:
    - on_hold: confirmed, processing, label_purchased
    - available: current stock (ready for new orders)
    - in_production: packing, packed
    - shipped: drop_off, shipped, in_transit, delivered
    """
    return report_service.inventory_breakdown(db)


@router.get("/inventory-movement")
def inventory_movement_report(
    product_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return report_service.inventory_movement(db, product_id=product_id, limit=limit)


@router.get("/batches")
def batch_report(
    date: str | None = Query(None, description="Date in YYYY-MM-DD format"),
    assigned_to: str | None = Query(None, description="Filter by staff username"),
    db: Session = Depends(get_db),
):
    return report_service.batch_report(db, date=date, assigned_to=assigned_to)
