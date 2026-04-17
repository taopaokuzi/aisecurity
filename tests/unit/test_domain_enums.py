from __future__ import annotations

import unittest

from packages.domain import (
    ACTOR_TYPE_VALUES,
    APPROVAL_STATUS_VALUES,
    GRANT_STATUS_VALUES,
    OPERATOR_TYPE_VALUES,
    REQUEST_STATUS_VALUES,
    RISK_LEVEL_VALUES,
    SESSION_STATUS_VALUES,
    TASK_STATUS_VALUES,
)


class DomainEnumTests(unittest.TestCase):
    def test_core_status_values_match_docs(self) -> None:
        self.assertEqual(
            REQUEST_STATUS_VALUES,
            (
                "Draft",
                "Submitted",
                "Evaluating",
                "PendingApproval",
                "Approved",
                "Provisioning",
                "Active",
                "Expiring",
                "Expired",
                "Revoked",
                "Failed",
            ),
        )
        self.assertEqual(
            APPROVAL_STATUS_VALUES,
            (
                "NotRequired",
                "Pending",
                "Approved",
                "Rejected",
                "Withdrawn",
                "Expired",
                "CallbackFailed",
            ),
        )
        self.assertEqual(
            GRANT_STATUS_VALUES,
            (
                "NotCreated",
                "ProvisioningRequested",
                "Provisioning",
                "Active",
                "Expiring",
                "Expired",
                "Revoking",
                "Revoked",
                "ProvisionFailed",
                "RevokeFailed",
            ),
        )
        self.assertEqual(
            SESSION_STATUS_VALUES,
            ("Active", "Revoking", "Revoked", "Syncing", "SyncFailed", "Expired"),
        )
        self.assertEqual(
            TASK_STATUS_VALUES,
            (
                "Pending",
                "Running",
                "Succeeded",
                "Failed",
                "Retrying",
                "Compensating",
                "Compensated",
            ),
        )
        self.assertEqual(RISK_LEVEL_VALUES, ("Low", "Medium", "High", "Critical"))

    def test_actor_and_operator_values_match_docs(self) -> None:
        expected = ("User", "Agent", "Approver", "ITAdmin", "SecurityAdmin", "System")
        self.assertEqual(ACTOR_TYPE_VALUES, expected)
        self.assertEqual(OPERATOR_TYPE_VALUES, expected)


if __name__ == "__main__":
    unittest.main()
