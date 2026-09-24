from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, uuid_fk, uuid_pk


class Campaign(Base):
    __tablename__ = "campaign"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','PAUSED','ENDED')", name="ck_campaign_status"),
        CheckConstraint("end_time > start_time", name="ck_campaign_dates"),
        CheckConstraint("remaining_budget >= 0", name="ck_campaign_budget_nonneg"),
    )

    id = uuid_pk()
    advertiser_id = uuid_fk("advertiser.id", nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    daily_budget: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    remaining_budget: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    bid_floor: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    target_countries: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    target_devices: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    advertiser = relationship("Advertiser", back_populates="campaigns")
    creatives = relationship("Creative", back_populates="campaign", cascade="all, delete-orphan")
