import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockAdjustRequest(Base):
    """Records a manual stock count / physical adjustment.

    Workflow:
        1. User scans product/variant QR code.
        2. System shows current in-warehouse stock (snapshot).
        3. User enters the actual physical count.
        4. System computes adjust = actual - in_warehouse.
        5. Record is saved (audit) and inventory is updated.
    """

    __tablename__ = "stock_adjust_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String, ForeignKey("products.id"), nullable=False, index=True)
    variant_id: Mapped[str] = mapped_column(String, default="", index=True)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str] = mapped_column(String, default="")
    variant_label: Mapped[str] = mapped_column(String, default="")

    in_warehouse_qty: Mapped[int] = mapped_column(Integer, nullable=False)  # snapshot at scan time
    actual_qty: Mapped[int] = mapped_column(Integer, nullable=False)         # what user counted
    adjust_amount: Mapped[int] = mapped_column(Integer, nullable=False)      # actual - in_warehouse (can be negative)
    cost_amount: Mapped[float] = mapped_column(Float, default=0.0)           # FIFO cost of the adjustment

    adjusted_by: Mapped[str] = mapped_column(String, default="")             # username
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
