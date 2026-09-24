from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class DSP(Base):
    __tablename__ = "dsp"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','DISABLED')", name="ck_dsp_status"),
    )

    id = uuid_pk()
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
