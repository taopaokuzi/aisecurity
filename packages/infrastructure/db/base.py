from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import CheckConstraint, DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "idx_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
    "uq": "uk_%(table_name)s_%(column_0_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def prefixed_id_column() -> Mapped[str]:
    return mapped_column(String(64), primary_key=True)


def enum_check_constraint(
    column_name: str,
    values: Sequence[str],
    constraint_name: str,
) -> CheckConstraint:
    escaped_values = (value.replace("'", "''") for value in values)
    allowed_values = ", ".join(f"'{value}'" for value in escaped_values)
    return CheckConstraint(f"{column_name} IN ({allowed_values})", name=constraint_name)
