from datetime import datetime

from pydantic import BaseModel

from app.models.stock_request import StockRequestStatus


class StockRequestItemCreate(BaseModel):
    product_id: str
    variant_id: str = ""
    quantity_requested: int
    unit_cost: float = 0.0
    box_count: int = 0


class StockRequestCreate(BaseModel):
    supplier: str = ""
    ship_from: str = ""
    tracking_id: str = ""
    carrier: str = ""
    notes: str = ""
    auto_receive: bool = False
    items: list[StockRequestItemCreate]


class StockRequestTrackingUpdate(BaseModel):
    tracking_id: str = ""
    carrier: str = ""


class StockRequestItemReceive(BaseModel):
    item_id: str
    quantity_received: int
    unit_cost: float | None = None


class StockRequestReceive(BaseModel):
    items: list[StockRequestItemReceive]


class StockRequestBoxOut(BaseModel):
    id: str
    stock_request_item_id: str
    barcode: str
    sequence: int
    received: bool = False
    received_at: datetime | None = None

    model_config = {"from_attributes": True}


class BoxScanResult(BaseModel):
    success: bool
    message: str
    box: StockRequestBoxOut | None = None
    item_id: str = ""
    sku: str = ""
    product_name: str = ""
    boxes_received: int = 0
    boxes_total: int = 0
    all_boxes_received: bool = False


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
    box_count: int = 0
    boxes: list[StockRequestBoxOut] = []

    model_config = {"from_attributes": True}


class StockRequestOut(BaseModel):
    id: str
    request_number: str
    supplier: str
    ship_from: str = ""
    status: str
    tracking_id: str = ""
    carrier: str = ""
    notes: str
    items: list[StockRequestItemOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
