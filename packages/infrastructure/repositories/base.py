from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from packages.infrastructure.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class SqlAlchemyRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        return instance

    def get(self, identifier: str) -> ModelT | None:
        return self.session.get(self.model, identifier)

    def list(self, *, limit: int | None = 100, offset: int = 0) -> list[ModelT]:
        statement = select(self.model).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)

    def delete(self, instance: ModelT) -> None:
        self.session.delete(instance)

    def scalars(self, statement: Select[tuple[ModelT]]) -> list[ModelT]:
        return list(self.session.scalars(statement))
