"""Custom job model: user-defined background jobs for order status transitions."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomJob(Base):
    __tablename__ = "custom_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")

    # JSON list of order statuses to scan, e.g. ["pending", "drop_off"]
    source_statuses: Mapped[str] = mapped_column(Text, default="[]")

    # JSON list of tracking statuses that trigger transition, e.g. ["in_transit", "delivered"]
    tracking_conditions: Mapped[str] = mapped_column(Text, default="[]")

    # Target order status to set, e.g. "shipped"
    target_status: Mapped[str] = mapped_column(String, default="shipped")

    # Whether orders must have a tracking number to be scanned
    require_tracking_number: Mapped[bool] = mapped_column(Boolean, default=True)

    # Scheduler interval in minutes
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30)

    # Whether this job is active (registered in scheduler)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
