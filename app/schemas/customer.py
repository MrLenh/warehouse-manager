from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    company: str = ""
    notes: str = ""


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None


class CustomerOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    company: str
    notes: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
