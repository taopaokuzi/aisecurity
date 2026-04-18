"""task_014_session_contexts

Revision ID: 20260417_0005
Revises: 20260417_0004
Create Date: 2026-04-17 23:10:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260417_0005"
down_revision = "20260417_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_contexts",
        sa.Column("global_session_id", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("task_session_id", sa.String(length=128), nullable=True),
        sa.Column("connector_session_ref", sa.String(length=128), nullable=True),
        sa.Column("session_status", sa.String(length=32), nullable=False),
        sa.Column("revocation_reason", sa.String(length=256), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "session_status IN ('Active', 'Revoking', 'Revoked', 'Syncing', 'SyncFailed', 'Expired')",
            name="ck_session_contexts_session_status",
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["access_grants.grant_id"],
            name="fk_session_contexts_grants",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["permission_requests.request_id"],
            name="fk_session_contexts_requests",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_identities.agent_id"],
            name="fk_session_contexts_agents",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_session_contexts_users",
        ),
        sa.PrimaryKeyConstraint("global_session_id", name=op.f("pk_session_contexts")),
        sa.UniqueConstraint("grant_id", name="uk_session_contexts_grant_id"),
    )
    op.create_index(
        "idx_session_contexts_request_id",
        "session_contexts",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "idx_session_contexts_status",
        "session_contexts",
        ["session_status"],
        unique=False,
    )
    op.create_index(
        "idx_session_contexts_agent_status",
        "session_contexts",
        ["agent_id", "session_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_session_contexts_agent_status", table_name="session_contexts")
    op.drop_index("idx_session_contexts_status", table_name="session_contexts")
    op.drop_index("idx_session_contexts_request_id", table_name="session_contexts")
    op.drop_table("session_contexts")
