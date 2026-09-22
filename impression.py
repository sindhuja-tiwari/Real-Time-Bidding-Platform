from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid_fk, uuid_pk


class Impression(Base):
    __tablename__ = "impression"

    id = uuid_pk()
    auction_id = uuid_fk("auction.id", nullable=False)
    campaign_id = uuid_fk("campaign.id", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    clicks = relationship("Click", back_populates="impression", cascade="all, delete-orphan")


class Click(Base):
    __tablename__ = "click"

    id = uuid_pk()
    impression_id = uuid_fk("impression.id", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    impression = relationship("Impression", back_populates="clicks")