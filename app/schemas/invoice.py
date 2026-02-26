from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class InvoiceCreate(BaseModel):
    customer_id: str
    date_to: date
    invoice_name: str
    processing_fee_unit: Optional[float] = None  # None = use config default
    stocking_fee_unit: Optional[float] = None  # None = use config default
    discount: float = 0.0
    notes: str = ""


class InvoiceStatusUpdate(BaseModel):
    status: str  # new, requested, paid, cancel


class InvoiceOrderOut(BaseModel):
    id: str
    order_number: str
    order_name: str
    customer_name: str
    status: str
    item_count: int
    shipping_cost: float
    processing_fee: float
    total_price: float
    created_at: datetime


class InvoiceOut(BaseModel):
    id: str
    invoice_number: str
    invoice_name: str
    customer_id: str
    customer_name: str = ""
    date_to: date
    status: str = "new"
    order_count: int
    item_count: int
    processing_fee_unit: float
    processing_fee_total: float
    shipping_fee_total: float
    stocking_fee_unit: float
    stocking_fee_total: float
    discount: float = 0.0
    total_price: float
    notes: str
    orders: list[InvoiceOrderOut] = []
    created_at: datetime
    updated_at: datetime


class InvoicePreview(BaseModel):
    order_count: int
    item_count: int
    processing_fee_unit: float
    processing_fee_total: float
    shipping_fee_total: float
    stocking_fee_unit: float
    stocking_fee_total: float
    discount: float = 0.0
    total_price: float
    orders: list[InvoiceOrderOut]
