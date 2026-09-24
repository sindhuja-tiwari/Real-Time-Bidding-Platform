from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid_fk, uuid_pk


class Creative(Base):
    __tablename__ = "creative"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','PAUSED')", name="ck_creative_status"),
    )

    id = uuid_pk()
    campaign_id = uuid_fk("campaign.id", nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    landing_url: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")

    campaign = relationship("Campaign", back_populates="creatives")
