"""task_012_connector_tasks

Revision ID: 20260417_0003
Revises: 20260417_0002
Create Date: 2026-04-17 12:20:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260417_0003"
down_revision = "20260417_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_tasks",
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("task_status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_retry_count", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=256), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "task_status IN ('Pending', 'Running', 'Succeeded', 'Failed', 'Retrying', 'Compensating', 'Compensated')",
            name="ck_connector_tasks_task_status",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_connector_tasks_retry_count"),
        sa.CheckConstraint("max_retry_count >= 0", name="ck_connector_tasks_max_retry_count"),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["access_grants.grant_id"],
            name="fk_connector_tasks_grants",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["permission_requests.request_id"],
            name="fk_connector_tasks_requests",
        ),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_connector_tasks")),
    )
    op.create_index(
        "idx_connector_tasks_grant_id_status",
        "connector_tasks",
        ["grant_id", "task_status"],
        unique=False,
    )
    op.create_index(
        "idx_connector_tasks_scheduled_at",
        "connector_tasks",
        ["task_status", "scheduled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_connector_tasks_scheduled_at", table_name="connector_tasks")
    op.drop_index("idx_connector_tasks_grant_id_status", table_name="connector_tasks")
    op.drop_table("connector_tasks")
