from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock_request import StockRequestStatus
from app.schemas.stock_request import (
    StockRequestCreate,
    StockRequestOut,
    StockRequestReceive,
)
from app.services import stock_request_service

router = APIRouter(prefix="/stock-requests", tags=["Stock Requests"])


@router.post("", response_model=StockRequestOut, status_code=201)
def create_stock_request(data: StockRequestCreate, db: Session = Depends(get_db)):
    try:
        return stock_request_service.create_stock_request(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("", response_model=list[StockRequestOut])
def list_stock_requests(
    skip: int = 0,
    limit: int = 100,
    status: StockRequestStatus | None = None,
    db: Session = Depends(get_db),
):
    return stock_request_service.list_stock_requests(db, skip=skip, limit=limit, status=status)


@router.get("/{sr_id}", response_model=StockRequestOut)
def get_stock_request(sr_id: str, db: Session = Depends(get_db)):
    sr = stock_request_service.get_stock_request(db, sr_id)
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/approve", response_model=StockRequestOut)
def approve_stock_request(sr_id: str, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.approve_stock_request(db, sr_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/receive", response_model=StockRequestOut)
def receive_items(sr_id: str, data: StockRequestReceive, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.receive_items(db, sr_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/complete", response_model=StockRequestOut)
def complete_stock_request(sr_id: str, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.complete_stock_request(db, sr_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr


@router.post("/{sr_id}/cancel", response_model=StockRequestOut)
def cancel_stock_request(sr_id: str, db: Session = Depends(get_db)):
    try:
        sr = stock_request_service.cancel_stock_request(db, sr_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not sr:
        raise HTTPException(404, "Stock request not found")
    return sr
