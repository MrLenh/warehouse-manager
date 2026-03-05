import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StockRequestStatus(str, PyEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    RECEIVING = "receiving"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def _generate_box_barcode() -> str:
    short = uuid.uuid4().hex[:10].upper()
    return f"BOX-{short}"


class StockRequest(Base):
    __tablename__ = "stock_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_number: Mapped[str] = mapped_column(String, unique=True, index=True)
    supplier: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(
        Enum(StockRequestStatus, values_callable=lambda x: [e.value for e in x]),
        default=StockRequestStatus.DRAFT,
    )
    # Shipping tracking
    tracking_id: Mapped[str] = mapped_column(String, default="")
    carrier: Mapped[str] = mapped_column(String, default="")

    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["StockRequestItem"]] = relationship(
        "StockRequestItem", back_populates="stock_request", cascade="all, delete-orphan"
    )


class StockRequestItem(Base):
    __tablename__ = "stock_request_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_request_id: Mapped[str] = mapped_column(String, ForeignKey("stock_requests.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[str] = mapped_column(String, default="")

    sku: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str] = mapped_column(String, default="")
    variant_label: Mapped[str] = mapped_column(String, default="")

    quantity_requested: Mapped[int] = mapped_column(Integer, default=0)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    box_count: Mapped[int] = mapped_column(Integer, default=0)

    stock_request: Mapped["StockRequest"] = relationship("StockRequest", back_populates="items")
    boxes: Mapped[list["StockRequestBox"]] = relationship(
        "StockRequestBox", back_populates="stock_request_item", cascade="all, delete-orphan"
    )


class StockRequestBox(Base):
    __tablename__ = "stock_request_boxes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_request_item_id: Mapped[str] = mapped_column(String, ForeignKey("stock_request_items.id"), nullable=False)
    barcode: Mapped[str] = mapped_column(String, unique=True, index=True, default=_generate_box_barcode)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    received: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stock_request_item: Mapped["StockRequestItem"] = relationship("StockRequestItem", back_populates="boxes")
