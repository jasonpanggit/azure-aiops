"""Read-only, reviewed workload logging policy contract.

The policy is supplied by an operator in the existing durable document store;
this module deliberately provides no default categories or destinations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from azure.core.exceptions import AzureError

from operations.observability_scenarios import PolicyException

POLICY_DOCUMENT = "state/workload_logging_policy.json"
POLICY_SCHEMA_VERSION = 1


class WorkloadLoggingPolicyUnavailable(RuntimeError):
    """No current, valid, scope-matched reviewed policy is available."""


@dataclass(frozen=True)
class WorkloadLoggingPolicy:
    policy_id: str
    version: str
    revision: int
    approved_by: str
    approved_at: str
    valid_until: str
    subscription_ids: tuple[str, ...]
    supported_resource_types: tuple[str, ...]
    required_categories: Mapping[str, tuple[str, ...]]
    required_destinations: Mapping[str, tuple[str, ...]]
    exceptions: tuple[PolicyException, ...]
    observed_at: str
    freshness: str
    complete: bool


class WorkloadLoggingPolicyStore:
    """Strict read adapter for an approved, explicitly scoped policy document."""

    def __init__(self, documents: Any, *, clock: Any = None) -> None:
        self._documents = documents
        self._clock = clock or (lambda: datetime.now(UTC))

    def read(self, *, subscription_ids: list[str]) -> WorkloadLoggingPolicy:
        if not subscription_ids:
            raise WorkloadLoggingPolicyUnavailable(
                "Workload logging policy requires an explicit subscription scope."
            )
        try:
            snapshot = self._documents.read_snapshot(POLICY_DOCUMENT)
        except (AzureError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise WorkloadLoggingPolicyUnavailable(
                "The reviewed workload logging policy source could not be read."
            ) from exc
        if not snapshot.exists:
            raise WorkloadLoggingPolicyUnavailable(
                "No approved workload logging policy is configured."
            )
        payload = snapshot.payload
        if not isinstance(payload, Mapping):
            raise WorkloadLoggingPolicyUnavailable(
                "Workload logging policy document is malformed."
            )
        now = _aware_now(self._clock)
        parsed = _parse_policy(payload, subscription_ids, now)
        return parsed


def _parse_policy(
    payload: Mapping[str, Any],
    subscription_ids: list[str],
    now: datetime,
) -> WorkloadLoggingPolicy:
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != POLICY_SCHEMA_VERSION
    ):
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy schema version is unsupported."
        )
    policy_id = _text(payload.get("policy_id"), "policy_id")
    version = _text(payload.get("version"), "version")
    revision = payload.get("revision")
    if type(revision) is not int or revision < 1:
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy revision is invalid."
        )
    if payload.get("approval_status") != "approved":
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy has not been approved."
        )
    approved_by = _text(payload.get("approved_by"), "approved_by")
    approved_at = _timestamp(payload.get("approved_at"), "approved_at")
    valid_until = _timestamp(payload.get("valid_until"), "valid_until")
    approved_time = _parse_time(approved_at)
    valid_time = _parse_time(valid_until)
    if approved_time > now or valid_time < approved_time:
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy approval interval is invalid."
        )

    scope = payload.get("scope")
    if not isinstance(scope, Mapping):
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy scope is invalid."
        )
    declared_subscriptions = _string_list(
        scope.get("subscription_ids"), "scope.subscription_ids"
    )
    if {value.casefold() for value in declared_subscriptions} != {
        value.casefold() for value in subscription_ids
    }:
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy scope does not exactly match the request."
        )

    supported = _string_list(
        payload.get("supported_resource_types"), "supported_resource_types"
    )
    if not supported:
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy must declare at least one resource type."
        )
    normalized_types = {value.casefold() for value in supported}
    if len(normalized_types) != len(supported) or any(
        "/" not in value or "*" in value or any(ch.isspace() for ch in value)
        for value in supported
    ):
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy resource types are invalid or duplicated."
        )
    categories = _requirements(
        payload.get("required_categories"), normalized_types, "required_categories"
    )
    destinations = _requirements(
        payload.get("required_destinations"),
        normalized_types,
        "required_destinations",
    )
    exceptions = _exceptions(
        payload.get("exceptions", []),
        subscription_ids=subscription_ids,
        categories=categories,
        destinations=destinations,
    )
    observed_at = now.isoformat().replace("+00:00", "Z")
    return WorkloadLoggingPolicy(
        policy_id=policy_id,
        version=version,
        revision=revision,
        approved_by=approved_by,
        approved_at=approved_at,
        valid_until=valid_until,
        subscription_ids=tuple(declared_subscriptions),
        supported_resource_types=tuple(value.casefold() for value in supported),
        required_categories=categories,
        required_destinations=destinations,
        exceptions=exceptions,
        observed_at=observed_at,
        freshness="fresh" if valid_time >= now else "stale",
        complete=True,
    )


def _requirements(
    value: Any,
    supported: set[str],
    field: str,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise WorkloadLoggingPolicyUnavailable(
            f"Workload logging policy {field} is invalid."
        )
    result: dict[str, tuple[str, ...]] = {}
    for resource_type, items in value.items():
        if not isinstance(resource_type, str):
            raise WorkloadLoggingPolicyUnavailable(
                f"Workload logging policy {field} has an invalid resource type."
            )
        key = resource_type.strip().casefold()
        if key in result:
            raise WorkloadLoggingPolicyUnavailable(
                f"Workload logging policy {field} has duplicate resource types."
            )
        result[key] = tuple(_string_list(items, f"{field}.{key}"))
        if not result[key]:
            raise WorkloadLoggingPolicyUnavailable(
                f"Workload logging policy {field}.{key} must not be empty."
            )
    if set(result) != supported:
        raise WorkloadLoggingPolicyUnavailable(
            f"Workload logging policy {field} must cover exactly its supported types."
        )
    return result


def _exceptions(
    value: Any,
    *,
    subscription_ids: list[str],
    categories: Mapping[str, tuple[str, ...]],
    destinations: Mapping[str, tuple[str, ...]],
) -> tuple[PolicyException, ...]:
    if not isinstance(value, list):
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy exceptions must be a list."
        )
    allowed = {item.casefold() for item in subscription_ids}
    result: list[PolicyException] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise WorkloadLoggingPolicyUnavailable(
                "Workload logging policy exception is malformed."
            )
        resource_id = _text(item.get("resource_id"), "exception.resource_id")
        subscription_id = _resource_subscription(resource_id)
        if subscription_id not in allowed:
            raise WorkloadLoggingPolicyUnavailable(
                "Workload logging policy exception is outside its declared scope."
            )
        key = resource_id.casefold()
        if key in seen:
            raise WorkloadLoggingPolicyUnavailable(
                "Workload logging policy contains duplicate exceptions."
            )
        seen.add(key)
        category_values = tuple(
            _string_list(item.get("categories", []), "exception.categories")
        )
        destination_values = tuple(
            _string_list(item.get("destinations", []), "exception.destinations")
        )
        all_categories = {
            value.casefold() for values in categories.values() for value in values
        }
        all_destinations = {
            value.casefold() for values in destinations.values() for value in values
        }
        if (
            not {value.casefold() for value in category_values} <= all_categories
            or not {value.casefold() for value in destination_values}
            <= all_destinations
            or not category_values
            and not destination_values
        ):
            raise WorkloadLoggingPolicyUnavailable(
                "Workload logging policy exception waives an undeclared requirement."
            )
        _text(item.get("approved_by"), "exception.approved_by")
        _text(item.get("reason"), "exception.reason")
        exception_approver = _text(item.get("approved_by"), "exception.approved_by")
        exception_reason = _text(item.get("reason"), "exception.reason")
        result.append(
            PolicyException(
                resource_id=resource_id,
                categories=category_values,
                destinations=destination_values,
                expires_at=_timestamp(item.get("expires_at"), "exception.expires_at"),
                approved_by=exception_approver,
                reason=exception_reason,
            )
        )
    return tuple(result)


def _resource_subscription(resource_id: str) -> str:
    parts = [part for part in resource_id.split("/") if part]
    if (
        len(parts) < 8
        or parts[0].casefold() != "subscriptions"
        or "providers" not in {part.casefold() for part in parts}
    ):
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy exception has an invalid resource ID."
        )
    return parts[1].casefold()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise WorkloadLoggingPolicyUnavailable(
            f"Workload logging policy {field} must be a non-empty-string list."
        )
    result = [item.strip() for item in value]
    if len({item.casefold() for item in result}) != len(result):
        raise WorkloadLoggingPolicyUnavailable(
            f"Workload logging policy {field} contains duplicates."
        )
    if field.startswith("required_destinations.") and any(
        not _valid_destination_reference(item) for item in result
    ):
        raise WorkloadLoggingPolicyUnavailable(
            f"Workload logging policy {field} must use canonical destination references."
        )
    return result


def _valid_destination_reference(value: str) -> bool:
    prefix, separator, reference = value.partition(":")
    return (
        separator == ":"
        and prefix.casefold()
        in {"log_analytics", "storage", "event_hub", "marketplace"}
        and bool(reference.strip())
    )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkloadLoggingPolicyUnavailable(
            f"Workload logging policy {field} is required."
        )
    return value.strip()


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    _parse_time(text)
    return text


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy contains an invalid timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise WorkloadLoggingPolicyUnavailable(
            "Workload logging policy timestamps require a timezone."
        )
    return parsed.astimezone(UTC)


def _aware_now(clock: Any) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Workload logging policy clock must return aware datetime")
    return value.astimezone(UTC)


__all__ = [
    "POLICY_DOCUMENT",
    "POLICY_SCHEMA_VERSION",
    "WorkloadLoggingPolicy",
    "WorkloadLoggingPolicyStore",
    "WorkloadLoggingPolicyUnavailable",
]
