import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_number: Mapped[str] = mapped_column(String, unique=True, index=True)
    invoice_name: Mapped[str] = mapped_column(String, nullable=False)
    customer_id: Mapped[str] = mapped_column(String, ForeignKey("customers.id"), nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, default="new")  # new, requested, paid, cancel

    # Summary
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int] = mapped_column(Integer, default=0)

    # Fees
    processing_fee_unit: Mapped[float] = mapped_column(Float, default=0.0)
    processing_fee_total: Mapped[float] = mapped_column(Float, default=0.0)
    shipping_fee_total: Mapped[float] = mapped_column(Float, default=0.0)
    stocking_fee_unit: Mapped[float] = mapped_column(Float, default=0.0)
    stocking_fee_total: Mapped[float] = mapped_column(Float, default=0.0)
    discount: Mapped[float] = mapped_column(Float, default=0.0)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)

    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    customer: Mapped["Customer"] = relationship("Customer", back_populates="invoices")
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="invoice")


# Avoid circular imports
from app.models.customer import Customer  # noqa: E402, F401
from app.models.order import Order  # noqa: E402, F401
