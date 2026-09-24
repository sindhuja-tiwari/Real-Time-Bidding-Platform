from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid_fk, uuid_pk


class Auction(Base):
    __tablename__ = "auction"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','COMPLETED','NO_BID','FAILED')", name="ck_auction_status"
        ),
    )

    id = uuid_pk()
    request_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    ad_slot_id = uuid_fk("ad_slot.id", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    winning_bid_id = uuid_fk("bid.id", nullable=True)

    bids = relationship(
        "Bid", back_populates="auction", foreign_keys="Bid.auction_id", cascade="all, delete-orphan"
    )
