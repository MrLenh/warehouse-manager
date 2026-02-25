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
    carrier: str = ""  # empty = use config default
    service: str = ""  # empty = use config default
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
    image_url: str = ""

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: str
    order_number: str
    order_name: str
    customer_name: str
    customer_email: str
    customer_phone: str = ""
    status: str
    carrier: str = "USPS"
    service: str = "GroundAdvantage"
    items: list[OrderItemOut]
    ship_to_street1: str = ""
    ship_to_street2: str = ""
    ship_to_city: str = ""
    ship_to_state: str = ""
    ship_to_zip: str = ""
    ship_to_country: str = "US"
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

    @field_validator("carrier", mode="before")
    @classmethod
    def carrier_default(cls, v):
        return v or "USPS"

    @field_validator("service", mode="before")
    @classmethod
    def service_default(cls, v):
        return v or "GroundAdvantage"


class BuyLabelRequest(BaseModel):
    carrier: str = ""  # empty = use order's carrier or config default
    service: str = ""  # empty = use order's service or config default
    weight_oz: float = 0
    length_in: float = 0
    width_in: float = 0
    height_in: float = 0
