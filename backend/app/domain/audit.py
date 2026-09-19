from collections.abc import Mapping, Sequence
from typing import Any


SENSITIVE_AUDIT_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "password",
        "password_hash",
        "refresh_token",
        "secret",
        "token",
    }
)


class SensitiveAuditDataError(ValueError):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"sensitive field is not allowed in audit data: {path}")


def ensure_audit_payload_safe(payload: Any, *, path: str = "payload") -> None:
    """Reject sensitive keys recursively without including their values in errors."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized_key = str(key).casefold().replace("-", "_")
            child_path = f"{path}.{key}"
            if normalized_key in SENSITIVE_AUDIT_KEYS:
                raise SensitiveAuditDataError(child_path)
            ensure_audit_payload_safe(value, path=child_path)
        return

    if isinstance(payload, Sequence) and not isinstance(
        payload,
        (str, bytes, bytearray),
    ):
        for index, value in enumerate(payload):
            ensure_audit_payload_safe(value, path=f"{path}[{index}]")
