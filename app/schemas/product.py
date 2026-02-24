import json
from datetime import datetime

from pydantic import BaseModel, field_validator


# --- Variant schemas ---

class VariantCreate(BaseModel):
    variant_sku: str
    attributes: dict[str, str] = {}  # {"color": "Red", "size": "M"}
    price_override: float = 0.0
    weight_oz_override: float = 0.0
    length_in_override: float = 0.0
    width_in_override: float = 0.0
    height_in_override: float = 0.0
    quantity: int = 0
    location: str = ""


class VariantUpdate(BaseModel):
    attributes: dict[str, str] | None = None
    price_override: float | None = None
    weight_oz_override: float | None = None
    length_in_override: float | None = None
    width_in_override: float | None = None
    height_in_override: float | None = None
    location: str | None = None


class VariantOut(BaseModel):
    id: str
    product_id: str
    variant_sku: str
    attributes: dict[str, str] = {}
    price_override: float
    weight_oz_override: float
    length_in_override: float
    width_in_override: float
    height_in_override: float
    quantity: int
    location: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("attributes", mode="before")
    @classmethod
    def parse_attributes(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


class VariantInventoryAdjust(BaseModel):
    quantity: int
    reason: str = "adjustment"
    note: str = ""


# --- Product schemas ---

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
    image_url: str = ""
    option_types: list[str] = []  # e.g. ["color", "size"]
    variants: list[VariantCreate] = []


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
    image_url: str | None = None
    option_types: list[str] | None = None


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
    image_url: str = ""
    option_types: list[str] = []
    variants: list[VariantOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("option_types", mode="before")
    @classmethod
    def parse_option_types(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


class InventoryAdjust(BaseModel):
    quantity: int  # positive to add, negative to remove
    reason: str = "adjustment"
    note: str = ""
