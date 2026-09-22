from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, uuid_fk, uuid_pk


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint("role IN ('ADMIN','ADVERTISER','PUBLISHER')", name="ck_user_role"),
    )

    id = uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Advertiser(Base):
    __tablename__ = "advertiser"

    id = uuid_pk()
    owner_user_id = uuid_fk("user.id", nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    budget: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    campaigns = relationship("Campaign", back_populates="advertiser", cascade="all, delete-orphan")