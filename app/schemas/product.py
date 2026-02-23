from datetime import datetime

from pydantic import BaseModel


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str = ""
    category: str = ""
    weight_oz: float = 0.0
    length_in: float = 0.0
    width_in: float = 0.0
    height_in: float = 0.0
    price: float = 0.0
    quantity: int = 0
    location: str = ""


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    weight_oz: float | None = None
    length_in: float | None = None
    width_in: float | None = None
    height_in: float | None = None
    price: float | None = None
    location: str | None = None


class ProductOut(BaseModel):
    id: str
    sku: str
    name: str
    description: str
    category: str
    weight_oz: float
    length_in: float
    width_in: float
    height_in: float
    price: float
    quantity: int
    location: str
    qr_code_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InventoryAdjust(BaseModel):
    quantity: int  # positive to add, negative to remove
    reason: str = "adjustment"
    note: str = ""
