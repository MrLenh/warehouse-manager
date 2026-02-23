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
    db: Session = Depends(get_db),
):
    return report_service.order_summary(db, start_date=start_date, end_date=end_date)


@router.get("/top-products")
def top_products_report(limit: int = 10, db: Session = Depends(get_db)):
    return report_service.top_products(db, limit=limit)


@router.get("/inventory-movement")
def inventory_movement_report(
    product_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return report_service.inventory_movement(db, product_id=product_id, limit=limit)
