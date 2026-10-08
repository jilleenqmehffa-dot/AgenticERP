from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import TypeVar
from uuid import uuid4

from app.core.enums import ActorType


ErrorT = TypeVar("ErrorT", bound=Exception)
ErrorFactory = Callable[[str], ErrorT]


def positive_int(
    value: object,
    field_name: str,
    *,
    error: ErrorFactory[ErrorT] = ValueError,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise error(f"{field_name} must be a positive integer")
    return value


def required_text(
    value: object,
    field_name: str,
    *,
    max_length: int | None = None,
    error: ErrorFactory[ErrorT] = ValueError,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{field_name} must be a nonempty string")
    normalized = value.strip()
    if max_length is not None and len(normalized) > max_length:
        raise error(f"{field_name} exceeds {max_length} characters")
    return normalized


def decimal_quantity(
    value: object,
    field_name: str,
    *,
    allow_zero: bool = False,
    error: ErrorFactory[ErrorT] = ValueError,
) -> Decimal:
    if isinstance(value, bool):
        raise error(f"invalid {field_name}")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise error(f"invalid {field_name}") from None
    if not quantity.is_finite() or quantity < 0 or (
        quantity == 0 and not allow_zero
    ):
        raise error(f"invalid {field_name}")
    return quantity


def actor_type(
    value: object,
    *,
    coerce: bool = False,
    error: ErrorFactory[ErrorT] = ValueError,
) -> ActorType:
    if isinstance(value, ActorType):
        return value
    if coerce:
        try:
            return ActorType(value)
        except (TypeError, ValueError):
            pass
    raise error("actor_type is invalid")


def actor_id(
    actor: ActorType,
    value: object,
    *,
    max_length: int = 255,
    error: ErrorFactory[ErrorT] = ValueError,
) -> str:
    if value is None and actor == ActorType.SYSTEM:
        return ActorType.SYSTEM.value
    normalized = required_text(value, "actor_id", error=error)
    if len(normalized) > max_length:
        raise error(f"actor_id exceeds {max_length} characters")
    return normalized


def trace_id(
    value: object,
    *,
    max_length: int = 64,
    error: ErrorFactory[ErrorT] = ValueError,
) -> str:
    if value is None:
        return str(uuid4())
    normalized = required_text(value, "trace_id", error=error)
    if len(normalized) > max_length:
        raise error(f"trace_id exceeds {max_length} characters")
    return normalized
