from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    product_id: str
    variant_id: str = ""
    quantity: int = 1


class AddressInput(BaseModel):
    name: str
    street1: str
    street2: str = ""
    city: str
    state: str
    zip: str
    country: str = "US"


class OrderCreate(BaseModel):
    order_name: str = ""
    customer_name: str
    customer_email: str = ""
    customer_phone: str = ""
    ship_to: AddressInput
    ship_from: AddressInput | None = None
    items: list[OrderItemCreate]
    webhook_url: str = ""
    notes: str = ""


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    note: str = ""


class OrderItemOut(BaseModel):
    id: str
    product_id: str
    variant_id: str = ""
    sku: str
    variant_sku: str = ""
    variant_label: str = ""
    product_name: str
    quantity: int
    unit_price: float

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: str
    order_number: str
    order_name: str
    customer_name: str
    customer_email: str
    status: str
    items: list[OrderItemOut]
    shipping_cost: float
    processing_fee: float
    total_price: float
    tracking_number: str
    tracking_url: str
    label_url: str
    qr_code_path: Optional[str] = ""
    notes: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("qr_code_path", mode="before")
    @classmethod
    def qr_code_path_default(cls, v):
        return v or ""


class BuyLabelRequest(BaseModel):
    carrier: str = "USPS"
    service: str = "Priority"
