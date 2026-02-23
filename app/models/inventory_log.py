import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InventoryLog(Base):
    """Tracks every inventory change for audit trail."""

    __tablename__ = "inventory_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String, ForeignKey("products.id"), nullable=False)
    change: Mapped[int] = mapped_column(Integer, nullable=False)  # positive=in, negative=out
    reason: Mapped[str] = mapped_column(String, nullable=False)  # inbound, order, adjustment
    reference_id: Mapped[str] = mapped_column(String, default="")  # order_id or note
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
