import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockBatch(Base):
    """Tracks each import batch for FIFO cost calculation.

    Each received stock request item creates a batch with its unit_cost
    and remaining quantity. When orders consume stock, oldest batches
    are consumed first (FIFO).
    """

    __tablename__ = "stock_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String, ForeignKey("products.id"), nullable=False, index=True)
    variant_id: Mapped[str] = mapped_column(String, default="", index=True)
    stock_request_id: Mapped[str] = mapped_column(String, ForeignKey("stock_requests.id"), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
