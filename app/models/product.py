import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sku: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    category: Mapped[str] = mapped_column(String, default="")
    weight_oz: Mapped[float] = mapped_column(Float, default=0.0)
    length_in: Mapped[float] = mapped_column(Float, default=0.0)
    width_in: Mapped[float] = mapped_column(Float, default=0.0)
    height_in: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String, default="")
    qr_code_path: Mapped[str] = mapped_column(String, default="")

    # Variant option types for this product, e.g. '["color","size"]'
    option_types: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    variants: Mapped[list["Variant"]] = relationship("Variant", back_populates="product", cascade="all, delete-orphan")


class Variant(Base):
    __tablename__ = "variants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String, ForeignKey("products.id"), nullable=False)
    variant_sku: Mapped[str] = mapped_column(String, unique=True, index=True)

    # Attributes as JSON, e.g. '{"color":"Red","size":"M"}'
    attributes: Mapped[str] = mapped_column(Text, default="{}")

    # Override parent product values (0 = use parent)
    price_override: Mapped[float] = mapped_column(Float, default=0.0)
    weight_oz_override: Mapped[float] = mapped_column(Float, default=0.0)
    length_in_override: Mapped[float] = mapped_column(Float, default=0.0)
    width_in_override: Mapped[float] = mapped_column(Float, default=0.0)
    height_in_override: Mapped[float] = mapped_column(Float, default=0.0)

    quantity: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    product: Mapped["Product"] = relationship("Product", back_populates="variants")

    @property
    def effective_price(self) -> float:
        return self.price_override if self.price_override > 0 else self.product.price

    @property
    def effective_weight_oz(self) -> float:
        return self.weight_oz_override if self.weight_oz_override > 0 else self.product.weight_oz

    @property
    def effective_length_in(self) -> float:
        return self.length_in_override if self.length_in_override > 0 else self.product.length_in

    @property
    def effective_width_in(self) -> float:
        return self.width_in_override if self.width_in_override > 0 else self.product.width_in

    @property
    def effective_height_in(self) -> float:
        return self.height_in_override if self.height_in_override > 0 else self.product.height_in
