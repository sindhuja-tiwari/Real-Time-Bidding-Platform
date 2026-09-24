from __future__ import annotations

import uuid

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def uuid_fk(target: str, **kwargs):
    from sqlalchemy import ForeignKey

    return mapped_column(Uuid, ForeignKey(target), **kwargs)


def created_at_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now())
