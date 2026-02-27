import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PickingListStatus(str, PyEnum):
    ACTIVE = "active"
    PROCESSING = "processing"
    DONE = "done"
    ARCHIVED = "archived"


class PickingList(Base):
    __tablename__ = "picking_lists"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    picking_number: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, default=PickingListStatus.ACTIVE)
    assigned_to: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["PickItem"]] = relationship("PickItem", back_populates="picking_list", cascade="all, delete-orphan")


class PickItem(Base):
    __tablename__ = "pick_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    picking_list_id: Mapped[str] = mapped_column(String, ForeignKey("picking_lists.id"), nullable=False)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("orders.id"), nullable=False)
    order_item_id: Mapped[str] = mapped_column(String, nullable=False)
    product_id: Mapped[str] = mapped_column(String, nullable=False)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str] = mapped_column(String, default="")
    variant_label: Mapped[str] = mapped_column(String, default="")
    sequence: Mapped[int] = mapped_column(Integer, default=1)  # which unit (1-based) for multi-qty items
    qr_code: Mapped[str] = mapped_column(String, unique=True, index=True)  # unique QR identifier
    picked: Mapped[bool] = mapped_column(Boolean, default=False)
    picked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    picking_list: Mapped["PickingList"] = relationship("PickingList", back_populates="items")
