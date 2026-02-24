from datetime import datetime

from pydantic import BaseModel


class PickingListCreate(BaseModel):
    order_ids: list[str]


class PickItemOut(BaseModel):
    id: str
    picking_list_id: str
    order_id: str
    order_item_id: str
    product_id: str
    sku: str
    product_name: str = ""
    variant_label: str = ""
    sequence: int = 1
    qr_code: str
    picked: bool = False
    picked_at: datetime | None = None

    model_config = {"from_attributes": True}


class PickingListOut(BaseModel):
    id: str
    picking_number: str
    status: str
    created_at: datetime
    updated_at: datetime
    items: list[PickItemOut] = []
    # Computed fields
    total_items: int = 0
    picked_items: int = 0
    order_count: int = 0

    model_config = {"from_attributes": True}


class ScanResult(BaseModel):
    success: bool
    message: str
    pick_item: PickItemOut | None = None
    order_id: str = ""
    order_number: str = ""
    order_picked: int = 0
    order_total: int = 0
    order_complete: bool = False
