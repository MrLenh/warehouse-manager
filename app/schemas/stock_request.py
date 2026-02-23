from datetime import datetime

from pydantic import BaseModel

from app.models.stock_request import StockRequestStatus


class StockRequestItemCreate(BaseModel):
    product_id: str
    variant_id: str = ""
    quantity_requested: int
    unit_cost: float = 0.0


class StockRequestCreate(BaseModel):
    supplier: str = ""
    notes: str = ""
    items: list[StockRequestItemCreate]


class StockRequestItemReceive(BaseModel):
    item_id: str
    quantity_received: int


class StockRequestReceive(BaseModel):
    items: list[StockRequestItemReceive]


class StockRequestItemOut(BaseModel):
    id: str
    product_id: str
    variant_id: str
    sku: str
    product_name: str
    variant_label: str
    quantity_requested: int
    quantity_received: int
    unit_cost: float

    model_config = {"from_attributes": True}


class StockRequestOut(BaseModel):
    id: str
    request_number: str
    supplier: str
    status: str
    notes: str
    items: list[StockRequestItemOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
