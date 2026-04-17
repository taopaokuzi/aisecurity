from __future__ import annotations

import unittest

from packages.domain import DomainError, ErrorCode, TASK_004_REQUIRED_ERROR_CODES


class DomainErrorTests(unittest.TestCase):
    def test_required_task_004_error_codes_are_exported(self) -> None:
        self.assertEqual(
            TASK_004_REQUIRED_ERROR_CODES,
            (
                ErrorCode.DELEGATION_INVALID,
                ErrorCode.AGENT_DISABLED,
                ErrorCode.REQUEST_STATUS_INVALID,
                ErrorCode.CALLBACK_DUPLICATED,
                ErrorCode.CONNECTOR_UNAVAILABLE,
                ErrorCode.SESSION_ALREADY_REVOKED,
            ),
        )

    def test_domain_error_uses_default_message_and_serializes(self) -> None:
        error = DomainError(
            code=ErrorCode.CALLBACK_DUPLICATED,
            details={"idempotency_key": "feishu_cb_001"},
        )

        self.assertEqual(error.message, "Callback has already been processed")
        self.assertEqual(
            error.to_dict(),
            {
                "code": "CALLBACK_DUPLICATED",
                "message": "Callback has already been processed",
                "details": {"idempotency_key": "feishu_cb_001"},
            },
        )


if __name__ == "__main__":
    unittest.main()
