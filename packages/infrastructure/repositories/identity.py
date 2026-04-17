from __future__ import annotations

from sqlalchemy import select

from packages.domain import AgentStatus, DelegationStatus
from packages.infrastructure.db.models import (
    AgentIdentityRecord,
    DelegationCredentialRecord,
    UserRecord,
)

from .base import SqlAlchemyRepository


class UserRepository(SqlAlchemyRepository[UserRecord]):
    model = UserRecord

    def list_by_department(self, department_id: str, *, limit: int | None = 100) -> list[UserRecord]:
        statement = (
            select(UserRecord)
            .where(UserRecord.department_id == department_id)
            .order_by(UserRecord.created_at.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)


class AgentIdentityRepository(SqlAlchemyRepository[AgentIdentityRecord]):
    model = AgentIdentityRecord

    def list_active(self) -> list[AgentIdentityRecord]:
        statement = (
            select(AgentIdentityRecord)
            .where(AgentIdentityRecord.agent_status == AgentStatus.ACTIVE.value)
            .order_by(AgentIdentityRecord.created_at.desc())
        )
        return self.scalars(statement)


class DelegationCredentialRepository(SqlAlchemyRepository[DelegationCredentialRecord]):
    model = DelegationCredentialRecord

    def list_active_for_user_agent(
        self,
        *,
        user_id: str,
        agent_id: str,
    ) -> list[DelegationCredentialRecord]:
        statement = (
            select(DelegationCredentialRecord)
            .where(DelegationCredentialRecord.user_id == user_id)
            .where(DelegationCredentialRecord.agent_id == agent_id)
            .where(
                DelegationCredentialRecord.delegation_status
                == DelegationStatus.ACTIVE.value
            )
            .order_by(DelegationCredentialRecord.expire_at.desc())
        )
        return self.scalars(statement)
