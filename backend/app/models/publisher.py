from __future__ import annotations

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid_fk, uuid_pk


class Publisher(Base):
    __tablename__ = "publisher"

    id = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)

    ad_slots = relationship("AdSlot", back_populates="publisher", cascade="all, delete-orphan")


class AdSlot(Base):
    __tablename__ = "ad_slot"

    id = uuid_pk()
    publisher_id = uuid_fk("publisher.id", nullable=False)
    placement: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    floor_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)

    publisher = relationship("Publisher", back_populates="ad_slots")
