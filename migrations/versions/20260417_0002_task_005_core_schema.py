"""task_005_core_schema

Revision ID: 20260417_0002
Revises: 20260416_0001
Create Date: 2026-04-17 03:56:47.204297
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260417_0002'
down_revision = '20260416_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('employee_no', sa.String(length=64), nullable=True),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('email', sa.String(length=256), nullable=True),
    sa.Column('department_id', sa.String(length=64), nullable=True),
    sa.Column('department_name', sa.String(length=128), nullable=True),
    sa.Column('manager_user_id', sa.String(length=64), nullable=True),
    sa.Column('user_status', sa.String(length=32), nullable=False),
    sa.Column('identity_source', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("identity_source IN ('SSO', 'Imported')", name='ck_users_identity_source'),
    sa.CheckConstraint("user_status IN ('Active', 'Disabled')", name='ck_users_user_status'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_users')),
    sa.UniqueConstraint('employee_no', name='uk_users_employee_no')
    )
    op.create_index('idx_users_department_id', 'users', ['department_id'], unique=False)
    op.create_table('agent_identities',
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('agent_name', sa.String(length=128), nullable=False),
    sa.Column('agent_version', sa.String(length=32), nullable=False),
    sa.Column('agent_type', sa.String(length=32), nullable=False),
    sa.Column('agent_status', sa.String(length=32), nullable=False),
    sa.Column('capability_scope_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("agent_status IN ('Active', 'Disabled')", name='ck_agent_identities_agent_status'),
    sa.CheckConstraint("agent_type IN ('first_party')", name='ck_agent_identities_agent_type'),
    sa.PrimaryKeyConstraint('agent_id', name=op.f('pk_agent_identities'))
    )
    op.create_index('idx_agent_identities_agent_status', 'agent_identities', ['agent_status'], unique=False)
    op.create_table('delegation_credentials',
    sa.Column('delegation_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('task_scope', sa.String(length=64), nullable=False),
    sa.Column('scope_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('delegation_status', sa.String(length=32), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expire_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revocation_reason', sa.String(length=256), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("delegation_status IN ('Active', 'Expired', 'Revoked')", name='ck_delegation_credentials_delegation_status'),
    sa.ForeignKeyConstraint(['agent_id'], ['agent_identities.agent_id'], name='fk_delegation_credentials_agents'),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], name='fk_delegation_credentials_users'),
    sa.PrimaryKeyConstraint('delegation_id', name=op.f('pk_delegation_credentials'))
    )
    op.create_index('idx_delegation_credentials_expire_at', 'delegation_credentials', ['expire_at'], unique=False)
    op.create_index('idx_delegation_credentials_user_agent_status', 'delegation_credentials', ['user_id', 'agent_id', 'delegation_status'], unique=False)
    op.create_table('permission_requests',
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('delegation_id', sa.String(length=64), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('resource_key', sa.String(length=128), nullable=True),
    sa.Column('resource_type', sa.String(length=32), nullable=True),
    sa.Column('action', sa.String(length=32), nullable=True),
    sa.Column('constraints_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('requested_duration', sa.String(length=32), nullable=True),
    sa.Column('structured_request_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('suggested_permission', sa.String(length=256), nullable=True),
    sa.Column('risk_level', sa.String(length=32), nullable=True),
    sa.Column('approval_status', sa.String(length=32), nullable=False),
    sa.Column('grant_status', sa.String(length=32), nullable=False),
    sa.Column('request_status', sa.String(length=32), nullable=False),
    sa.Column('current_task_state', sa.String(length=32), nullable=True),
    sa.Column('policy_version', sa.String(length=64), nullable=True),
    sa.Column('renew_round', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('failed_reason', sa.String(length=256), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("approval_status IN ('NotRequired', 'Pending', 'Approved', 'Rejected', 'Withdrawn', 'Expired', 'CallbackFailed')", name='ck_permission_requests_approval_status'),
    sa.CheckConstraint("current_task_state IN ('Pending', 'Running', 'Succeeded', 'Failed', 'Retrying', 'Compensating', 'Compensated')", name='ck_permission_requests_current_task_state'),
    sa.CheckConstraint("grant_status IN ('NotCreated', 'ProvisioningRequested', 'Provisioning', 'Active', 'Expiring', 'Expired', 'Revoking', 'Revoked', 'ProvisionFailed', 'RevokeFailed')", name='ck_permission_requests_grant_status'),
    sa.CheckConstraint("request_status IN ('Draft', 'Submitted', 'Evaluating', 'PendingApproval', 'Approved', 'Provisioning', 'Active', 'Expiring', 'Expired', 'Revoked', 'Failed')", name='ck_permission_requests_request_status'),
    sa.CheckConstraint("risk_level IN ('Low', 'Medium', 'High', 'Critical')", name='ck_permission_requests_risk_level'),
    sa.CheckConstraint('renew_round >= 0', name='ck_permission_requests_renew_round'),
    sa.ForeignKeyConstraint(['agent_id'], ['agent_identities.agent_id'], name='fk_permission_requests_agents'),
    sa.ForeignKeyConstraint(['delegation_id'], ['delegation_credentials.delegation_id'], name='fk_permission_requests_delegations'),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], name='fk_permission_requests_users'),
    sa.PrimaryKeyConstraint('request_id', name=op.f('pk_permission_requests'))
    )
    op.create_index('idx_permission_requests_approval_status', 'permission_requests', ['approval_status'], unique=False)
    op.create_index('idx_permission_requests_risk_level', 'permission_requests', ['risk_level'], unique=False)
    op.create_index('idx_permission_requests_status_updated_at', 'permission_requests', ['request_status', sa.literal_column('updated_at DESC')], unique=False)
    op.create_index('idx_permission_requests_user_created_at', 'permission_requests', ['user_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('permission_request_events',
    sa.Column('event_id', sa.String(length=64), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('operator_type', sa.String(length=32), nullable=False),
    sa.Column('operator_id', sa.String(length=64), nullable=True),
    sa.Column('from_request_status', sa.String(length=32), nullable=True),
    sa.Column('to_request_status', sa.String(length=32), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("from_request_status IN ('Draft', 'Submitted', 'Evaluating', 'PendingApproval', 'Approved', 'Provisioning', 'Active', 'Expiring', 'Expired', 'Revoked', 'Failed')", name='ck_permission_request_events_from_request_status'),
    sa.CheckConstraint("operator_type IN ('User', 'Agent', 'Approver', 'ITAdmin', 'SecurityAdmin', 'System')", name='ck_permission_request_events_operator_type'),
    sa.CheckConstraint("to_request_status IN ('Draft', 'Submitted', 'Evaluating', 'PendingApproval', 'Approved', 'Provisioning', 'Active', 'Expiring', 'Expired', 'Revoked', 'Failed')", name='ck_permission_request_events_to_request_status'),
    sa.ForeignKeyConstraint(['request_id'], ['permission_requests.request_id'], name='fk_permission_request_events_requests'),
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_permission_request_events'))
    )
    op.create_index('idx_permission_request_events_event_type', 'permission_request_events', ['event_type'], unique=False)
    op.create_index('idx_permission_request_events_request_id', 'permission_request_events', ['request_id', sa.literal_column('occurred_at DESC')], unique=False)
    op.create_table('approval_records',
    sa.Column('approval_id', sa.String(length=64), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('external_approval_id', sa.String(length=128), nullable=True),
    sa.Column('approval_node', sa.String(length=64), nullable=False),
    sa.Column('approver_id', sa.String(length=64), nullable=True),
    sa.Column('approval_status', sa.String(length=32), nullable=False),
    sa.Column('callback_payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("approval_status IN ('NotRequired', 'Pending', 'Approved', 'Rejected', 'Withdrawn', 'Expired', 'CallbackFailed')", name='ck_approval_records_approval_status'),
    sa.ForeignKeyConstraint(['request_id'], ['permission_requests.request_id'], name='fk_approval_records_requests'),
    sa.PrimaryKeyConstraint('approval_id', name=op.f('pk_approval_records')),
    sa.UniqueConstraint('external_approval_id', name='uk_approval_records_external_approval_id'),
    sa.UniqueConstraint('idempotency_key', name='uk_approval_records_idempotency_key')
    )
    op.create_index('idx_approval_records_request_id', 'approval_records', ['request_id'], unique=False)
    op.create_index('idx_approval_records_status', 'approval_records', ['approval_status'], unique=False)
    op.create_table('access_grants',
    sa.Column('grant_id', sa.String(length=64), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('resource_key', sa.String(length=128), nullable=False),
    sa.Column('resource_type', sa.String(length=32), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('grant_status', sa.String(length=32), nullable=False),
    sa.Column('connector_status', sa.String(length=32), nullable=False),
    sa.Column('reconcile_status', sa.String(length=32), nullable=False),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expire_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revocation_reason', sa.String(length=256), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("connector_status IN ('Accepted', 'Applied', 'Failed', 'Partial')", name='ck_access_grants_connector_status'),
    sa.CheckConstraint("grant_status IN ('NotCreated', 'ProvisioningRequested', 'Provisioning', 'Active', 'Expiring', 'Expired', 'Revoking', 'Revoked', 'ProvisionFailed', 'RevokeFailed')", name='ck_access_grants_grant_status'),
    sa.ForeignKeyConstraint(['request_id'], ['permission_requests.request_id'], name='fk_access_grants_requests'),
    sa.PrimaryKeyConstraint('grant_id', name=op.f('pk_access_grants'))
    )
    op.create_index('idx_access_grants_request_id', 'access_grants', ['request_id'], unique=False)
    op.create_index('idx_access_grants_resource_action', 'access_grants', ['resource_key', 'action'], unique=False)
    op.create_index('idx_access_grants_status_expire_at', 'access_grants', ['grant_status', 'expire_at'], unique=False)
    op.create_table('audit_records',
    sa.Column('audit_id', sa.String(length=64), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('actor_type', sa.String(length=32), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('subject_chain', sa.String(length=512), nullable=True),
    sa.Column('result', sa.String(length=32), nullable=False),
    sa.Column('reason', sa.String(length=256), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("actor_type IN ('User', 'Agent', 'Approver', 'ITAdmin', 'SecurityAdmin', 'System')", name='ck_audit_records_actor_type'),
    sa.CheckConstraint("result IN ('Success', 'Fail', 'Denied')", name='ck_audit_records_result'),
    sa.PrimaryKeyConstraint('audit_id', name=op.f('pk_audit_records'))
    )
    op.create_index('idx_audit_records_actor', 'audit_records', ['actor_type', 'actor_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_audit_records_event_type_created_at', 'audit_records', ['event_type', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_audit_records_request_id_created_at', 'audit_records', ['request_id', sa.literal_column('created_at DESC')], unique=False)


def downgrade() -> None:
    op.drop_index('idx_audit_records_request_id_created_at', table_name='audit_records')
    op.drop_index('idx_audit_records_event_type_created_at', table_name='audit_records')
    op.drop_index('idx_audit_records_actor', table_name='audit_records')
    op.drop_table('audit_records')
    op.drop_index('idx_access_grants_status_expire_at', table_name='access_grants')
    op.drop_index('idx_access_grants_resource_action', table_name='access_grants')
    op.drop_index('idx_access_grants_request_id', table_name='access_grants')
    op.drop_table('access_grants')
    op.drop_index('idx_approval_records_status', table_name='approval_records')
    op.drop_index('idx_approval_records_request_id', table_name='approval_records')
    op.drop_table('approval_records')
    op.drop_index('idx_permission_request_events_request_id', table_name='permission_request_events')
    op.drop_index('idx_permission_request_events_event_type', table_name='permission_request_events')
    op.drop_table('permission_request_events')
    op.drop_index('idx_permission_requests_user_created_at', table_name='permission_requests')
    op.drop_index('idx_permission_requests_status_updated_at', table_name='permission_requests')
    op.drop_index('idx_permission_requests_risk_level', table_name='permission_requests')
    op.drop_index('idx_permission_requests_approval_status', table_name='permission_requests')
    op.drop_table('permission_requests')
    op.drop_index('idx_delegation_credentials_user_agent_status', table_name='delegation_credentials')
    op.drop_index('idx_delegation_credentials_expire_at', table_name='delegation_credentials')
    op.drop_table('delegation_credentials')
    op.drop_index('idx_agent_identities_agent_status', table_name='agent_identities')
    op.drop_table('agent_identities')
    op.drop_index('idx_users_department_id', table_name='users')
    op.drop_table('users')
