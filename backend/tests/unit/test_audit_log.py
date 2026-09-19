import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError

from app.core.enums import ActorType
from app.domain.audit import SensitiveAuditDataError, ensure_audit_payload_safe
from app.models.audit_log import AuditLog
from app.repositories.audit_log import AuditLogRepository
from app.schemas.audit_log import AuditLogCreate, AuditLogRead


def make_audit_log() -> AuditLog:
    return AuditLog(
        id=1,
        actor_type=ActorType.EMPLOYEE,
        actor_id="42",
        action="COMPLETE_TASK",
        entity_type="BUSINESS_TASK",
        entity_id="1001",
        before_data={"status": "IN_PROGRESS"},
        after_data={"status": "COMPLETED"},
        trace_id="TRACE-001",
        created_at=datetime.now(timezone.utc),
        metadata_={"request_id": "REQ-001"},
    )


class AuditLogTests(unittest.IsolatedAsyncioTestCase):
    def test_create_captures_actor_entity_change_and_trace(self) -> None:
        audit = AuditLogCreate(
            actor_type=ActorType.EMPLOYEE,
            actor_id="42",
            action="COMPLETE_TASK",
            entity_type="BUSINESS_TASK",
            entity_id="1001",
            before_data={"status": "IN_PROGRESS"},
            after_data={"status": "COMPLETED"},
            trace_id="TRACE-001",
            metadata={"request_id": "REQ-001"},
        )

        self.assertEqual(audit.actor_type, ActorType.EMPLOYEE)
        self.assertEqual(audit.before_data, {"status": "IN_PROGRESS"})
        self.assertEqual(audit.after_data, {"status": "COMPLETED"})

    def test_sensitive_fields_are_rejected_recursively(self) -> None:
        with self.assertRaises(SensitiveAuditDataError):
            ensure_audit_payload_safe(
                {"user": {"credentials": [{"access_token": "do-not-log"}]}}
            )

        with self.assertRaises(ValidationError):
            AuditLogCreate(
                actor_type=ActorType.SYSTEM,
                actor_id="SYSTEM",
                action="LOGIN",
                entity_type="EMPLOYEE",
                entity_id="42",
                after_data={"password_hash": "do-not-log"},
                trace_id="TRACE-002",
            )

    def test_read_schema_maps_internal_metadata_attribute(self) -> None:
        result = AuditLogRead.model_validate(make_audit_log())

        self.assertEqual(result.metadata, {"request_id": "REQ-001"})

    async def test_repository_appends_without_committing(self) -> None:
        session = MagicMock()
        session.flush = AsyncMock()
        repository = AuditLogRepository(session)
        audit_log = make_audit_log()

        result = await repository.append(audit_log)

        self.assertIs(result, audit_log)
        session.add.assert_called_once_with(audit_log)
        session.flush.assert_awaited_once_with()
        session.commit.assert_not_called()

    async def test_repository_rejects_sensitive_model_payload(self) -> None:
        session = MagicMock()
        session.flush = AsyncMock()
        repository = AuditLogRepository(session)
        audit_log = make_audit_log()
        audit_log.after_data = {"authorization": "do-not-log"}

        with self.assertRaises(SensitiveAuditDataError):
            await repository.append(audit_log)

        session.add.assert_not_called()
        session.flush.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
