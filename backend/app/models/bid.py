from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, uuid_fk, uuid_pk


class Bid(Base):
    __tablename__ = "bid"
    __table_args__ = (
        CheckConstraint(
            "status IN ('VALID','TIMEOUT','INVALID','BELOW_FLOOR','BUDGET_EXCEEDED','WON','LOST')",
            name="ck_bid_status",
        ),
        CheckConstraint("amount >= 0", name="ck_bid_amount_nonneg"),
    )

    id = uuid_pk()
    auction_id = uuid_fk("auction.id", nullable=False)
    dsp_id = uuid_fk("dsp.id", nullable=False)
    campaign_id = uuid_fk("campaign.id", nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    auction = relationship("Auction", back_populates="bids", foreign_keys=[auction_id])
