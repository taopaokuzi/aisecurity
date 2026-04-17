from __future__ import annotations

import unittest
from datetime import UTC, datetime

from packages.domain import (
    AccessGrant,
    ApprovalRecord,
    ApprovalStatus,
    ConnectorStatus,
    DelegationCredential,
    DelegationStatus,
    GrantStatus,
    PermissionRequest,
    RequestStatus,
)


def utc_datetime(hour: int) -> datetime:
    return datetime(2026, 4, 17, hour, 0, tzinfo=UTC)


class DomainModelTests(unittest.TestCase):
    def test_permission_request_coerces_documented_status_strings(self) -> None:
        permission_request = PermissionRequest(
            request_id="req_123",
            user_id="user_001",
            agent_id="agent_perm_assistant_v1",
            delegation_id="dlg_123",
            raw_text="我需要查看销售部Q3报表",
            risk_level="Low",
            approval_status="Pending",
            grant_status="NotCreated",
            request_status="Submitted",
            created_at=utc_datetime(9),
            updated_at=utc_datetime(10),
        )

        self.assertIs(permission_request.approval_status, ApprovalStatus.PENDING)
        self.assertIs(permission_request.grant_status, GrantStatus.NOT_CREATED)
        self.assertIs(permission_request.request_status, RequestStatus.SUBMITTED)

    def test_permission_request_rejects_active_request_without_active_grant(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Active requests require grant_status to be Active",
        ):
            PermissionRequest(
                request_id="req_123",
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                delegation_id="dlg_123",
                raw_text="我需要查看销售部Q3报表",
                approval_status="Approved",
                grant_status="Provisioning",
                request_status="Active",
                created_at=utc_datetime(9),
                updated_at=utc_datetime(10),
            )

    def test_delegation_credential_requires_revoked_status_when_revoked_at_exists(self) -> None:
        with self.assertRaisesRegex(ValueError, "delegation_status to be Revoked"):
            DelegationCredential(
                delegation_id="dlg_123",
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                task_scope="permission_self_service",
                scope={"resource_types": ["report"]},
                delegation_status="Active",
                issued_at=utc_datetime(9),
                expire_at=utc_datetime(10),
                created_at=utc_datetime(9),
                updated_at=utc_datetime(10),
                revoked_at=utc_datetime(11),
            )

    def test_access_grant_requires_applied_connector_when_active(self) -> None:
        with self.assertRaisesRegex(ValueError, "connector_status to be Applied"):
            AccessGrant(
                grant_id="grt_001",
                request_id="req_123",
                resource_key="sales.q3_report",
                resource_type="report",
                action="read",
                grant_status="Active",
                connector_status="Accepted",
                expire_at=utc_datetime(12),
                created_at=utc_datetime(9),
                updated_at=utc_datetime(10),
            )

    def test_approval_record_rejects_conflicting_timestamps(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot both be set"):
            ApprovalRecord(
                approval_id="apr_001",
                request_id="req_123",
                approval_node="manager",
                approval_status="Approved",
                approved_at=utc_datetime(11),
                rejected_at=utc_datetime(12),
                created_at=utc_datetime(9),
                updated_at=utc_datetime(10),
            )

    def test_delegation_credential_coerces_status_string(self) -> None:
        credential = DelegationCredential(
            delegation_id="dlg_123",
            user_id="user_001",
            agent_id="agent_perm_assistant_v1",
            task_scope="permission_self_service",
            scope={"resource_types": ["report"], "allowed_actions": ["read"]},
            delegation_status="Revoked",
            issued_at=utc_datetime(9),
            expire_at=utc_datetime(10),
            created_at=utc_datetime(9),
            updated_at=utc_datetime(10),
            revoked_at=utc_datetime(10),
        )

        self.assertIs(credential.delegation_status, DelegationStatus.REVOKED)

    def test_access_grant_coerces_documented_connector_status(self) -> None:
        grant = AccessGrant(
            grant_id="grt_001",
            request_id="req_123",
            resource_key="sales.q3_report",
            resource_type="report",
            action="read",
            grant_status="Active",
            connector_status="Applied",
            expire_at=utc_datetime(12),
            effective_at=utc_datetime(11),
            created_at=utc_datetime(9),
            updated_at=utc_datetime(10),
        )

        self.assertIs(grant.connector_status, ConnectorStatus.APPLIED)


if __name__ == "__main__":
    unittest.main()
