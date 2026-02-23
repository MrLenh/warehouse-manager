import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OrderStatus(str, PyEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    PACKED = "packed"
    LABEL_PURCHASED = "label_purchased"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_number: Mapped[str] = mapped_column(String, unique=True, index=True)
    order_name: Mapped[str] = mapped_column(String, default="")
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    customer_email: Mapped[str] = mapped_column(String, default="")
    customer_phone: Mapped[str] = mapped_column(String, default="")

    # Shipping address
    ship_to_name: Mapped[str] = mapped_column(String, default="")
    ship_to_street1: Mapped[str] = mapped_column(String, default="")
    ship_to_street2: Mapped[str] = mapped_column(String, default="")
    ship_to_city: Mapped[str] = mapped_column(String, default="")
    ship_to_state: Mapped[str] = mapped_column(String, default="")
    ship_to_zip: Mapped[str] = mapped_column(String, default="")
    ship_to_country: Mapped[str] = mapped_column(String, default="US")

    # From address (warehouse)
    ship_from_name: Mapped[str] = mapped_column(String, default="Warehouse")
    ship_from_street1: Mapped[str] = mapped_column(String, default="")
    ship_from_city: Mapped[str] = mapped_column(String, default="")
    ship_from_state: Mapped[str] = mapped_column(String, default="")
    ship_from_zip: Mapped[str] = mapped_column(String, default="")
    ship_from_country: Mapped[str] = mapped_column(String, default="US")

    status: Mapped[str] = mapped_column(
        Enum(OrderStatus, values_callable=lambda x: [e.value for e in x]),
        default=OrderStatus.PENDING,
    )
    status_history: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of {status, timestamp}

    # Pricing
    shipping_cost: Mapped[float] = mapped_column(Float, default=0.0)
    processing_fee: Mapped[float] = mapped_column(Float, default=0.0)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)

    # EasyPost
    easypost_shipment_id: Mapped[str] = mapped_column(String, default="")
    tracking_number: Mapped[str] = mapped_column(String, default="")
    tracking_url: Mapped[str] = mapped_column(String, default="")
    label_url: Mapped[str] = mapped_column(String, default="")

    # Webhook
    webhook_url: Mapped[str] = mapped_column(String, default="")

    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String, ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[str] = mapped_column(String, default="")
    sku: Mapped[str] = mapped_column(String, nullable=False)
    variant_sku: Mapped[str] = mapped_column(String, default="")
    variant_label: Mapped[str] = mapped_column(String, default="")  # e.g. "Red / M"
    product_name: Mapped[str] = mapped_column(String, default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)

    order: Mapped["Order"] = relationship("Order", back_populates="items")
