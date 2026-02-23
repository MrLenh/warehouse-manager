from datetime import datetime

from pydantic import BaseModel

from app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    product_id: str
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
    sku: str
    product_name: str
    quantity: int
    unit_price: float

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: str
    order_number: str
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
    notes: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BuyLabelRequest(BaseModel):
    carrier: str = "USPS"
    service: str = "Priority"
