"""Connection validation across the access surface an onboarded SPN requires.

Each check is independent so a partially-permissioned SPN produces an
actionable per-capability report instead of a single opaque failure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from ontology.subscription_connection import SubscriptionConnection

from .credentials import CredentialResolver, SecretNotFoundError

CONNECTION_CHECKS: tuple[str, ...] = (
    "spn_authentication",
    "subscription_reachability",
    "arg_read",
    "network_resource_read",
    "patch_update_read",
    "advisor_read",
    "resource_changes_read",
)

REQUIRED_CHECKS: frozenset[str] = frozenset(
    {"spn_authentication", "subscription_reachability", "arg_read"}
)

CHECK_REMEDIATION: Mapping[str, str] = {
    "spn_authentication": "Verify tenant_id, client_id, and that the secret reference resolves to a current secret.",
    "subscription_reachability": "Grant the SPN Reader on /subscriptions/<id> and confirm the subscription is enabled.",
    "arg_read": "Grant Reader so Microsoft.ResourceGraph/resources/read succeeds for the subscription.",
    "network_resource_read": "Grant Reader over network resources (VNets, NSGs, route tables, peerings).",
    "patch_update_read": "Enable Azure Update Manager and grant read on patchassessmentresources/patchinstallationresources.",
    "advisor_read": "Grant Reader on Microsoft.Advisor/recommendations for the subscription.",
    "resource_changes_read": "Grant Reader so Microsoft.Resources/changes (resourcechanges) can be queried.",
}

_CHECK_QUERIES: Mapping[str, str] = {
    "subscription_reachability": (
        "ResourceContainers | where type =~ 'microsoft.resources/subscriptions' | project id | limit 1"
    ),
    "arg_read": "Resources | project id | limit 1",
    "network_resource_read": (
        "Resources | where type startswith 'microsoft.network/' | project id | limit 1"
    ),
    "patch_update_read": "patchassessmentresources | project id | limit 1",
    "advisor_read": (
        "advisorresources | where type =~ 'microsoft.advisor/recommendations' | project id | limit 1"
    ),
    "resource_changes_read": "resourcechanges | project id | limit 1",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    required: bool
    detail: str = ""
    remediation: str | None = None
    duration_ms: int = 0
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "required": self.required,
            "skipped": self.skipped,
            "detail": self.detail,
            "remediation": self.remediation,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class ValidationReport:
    connection_id: str
    subscription_id: str
    checked_at: str
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)

    @property
    def required_failures(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if check.required and not check.passed)

    @property
    def optional_failures(self) -> tuple[CheckResult, ...]:
        return tuple(
            check for check in self.checks if not check.required and not check.passed and not check.skipped
        )

    @property
    def passed(self) -> bool:
        return not self.required_failures

    @property
    def status(self) -> str:
        if self.required_failures:
            return "failed"
        if self.optional_failures:
            return "degraded"
        return "healthy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "subscription_id": self.subscription_id,
            "checked_at": self.checked_at,
            "status": self.status,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "failed_required": [check.name for check in self.required_failures],
            "failed_optional": [check.name for check in self.optional_failures],
        }


class ConnectionProbe(Protocol):
    """Executes a scoped ARG query for one connection."""

    def authenticate(self, connection: SubscriptionConnection) -> str: ...

    def query(self, connection: SubscriptionConnection, query: str) -> list[dict]: ...


class ArgConnectionProbe:
    """Default probe: authenticates the SPN, then runs scoped ARG queries."""

    def __init__(
        self,
        resolver: CredentialResolver | None = None,
        arg_client: Any = None,
        arg_client_factory: Callable[[SubscriptionConnection], Any] | None = None,
    ) -> None:
        self.resolver = resolver or CredentialResolver()
        self.arg_client = arg_client
        self.arg_client_factory = arg_client_factory

    def authenticate(self, connection: SubscriptionConnection) -> str:
        credential = self.resolver.build(connection.credential)
        token = credential.get_token("https://management.azure.com/.default")
        if not getattr(token, "token", None):
            raise RuntimeError("Azure AD returned an empty access token for the connection SPN")
        return "acquired management access token"

    def query(self, connection: SubscriptionConnection, query: str) -> list[dict]:
        client = (
            self.arg_client_factory(connection)
            if self.arg_client_factory is not None
            else self.arg_client
        )
        if client is None:
            raise RuntimeError(
                "No Azure Resource Graph client is configured for connection validation"
            )
        from onboarding.query_contract import QuerySpec

        spec = QuerySpec(name="validation", table="Resources", query=query, incremental=False)
        return client.query(spec, [connection.subscription_id])


class ConnectionValidator:
    """Runs the full connection check suite and returns a per-capability report."""

    def __init__(
        self,
        probe: ConnectionProbe | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.probe = probe or ArgConnectionProbe()
        self.clock = clock or (lambda: datetime.now(UTC))

    def validate(
        self,
        connection: SubscriptionConnection,
        *,
        checks: tuple[str, ...] | None = None,
    ) -> ValidationReport:
        selected = tuple(checks or CONNECTION_CHECKS)
        unknown = [name for name in selected if name not in CONNECTION_CHECKS]
        if unknown:
            raise ValueError(f"Unknown connection check(s): {', '.join(sorted(unknown))}")

        results: list[CheckResult] = []
        auth_failed = False
        for name in selected:
            required = name in REQUIRED_CHECKS
            if auth_failed:
                results.append(
                    CheckResult(
                        name=name,
                        passed=False,
                        required=required,
                        skipped=True,
                        detail="Skipped because SPN authentication failed",
                        remediation=CHECK_REMEDIATION.get(name),
                    )
                )
                continue
            result = self._run_check(connection, name, required)
            results.append(result)
            if name == "spn_authentication" and not result.passed:
                auth_failed = True

        return ValidationReport(
            connection_id=connection.connection_id,
            subscription_id=connection.subscription_id,
            checked_at=_iso(self.clock()),
            checks=tuple(results),
        )

    def _run_check(
        self, connection: SubscriptionConnection, name: str, required: bool
    ) -> CheckResult:
        started = self.clock()
        try:
            if name == "spn_authentication":
                detail = self.probe.authenticate(connection)
            else:
                rows = self.probe.query(connection, _CHECK_QUERIES[name])
                detail = f"read {len(rows)} row(s)"
            return CheckResult(
                name=name,
                passed=True,
                required=required,
                detail=detail,
                duration_ms=_elapsed_ms(started, self.clock()),
            )
        except SecretNotFoundError as exc:
            return CheckResult(
                name=name,
                passed=False,
                required=required,
                detail=f"credential resolution failed: {exc}",
                remediation=CHECK_REMEDIATION.get(name),
                duration_ms=_elapsed_ms(started, self.clock()),
            )
        except Exception as exc:  # noqa: BLE001 - every check failure is reportable
            return CheckResult(
                name=name,
                passed=False,
                required=required,
                detail=str(exc).strip() or exc.__class__.__name__,
                remediation=CHECK_REMEDIATION.get(name),
                duration_ms=_elapsed_ms(started, self.clock()),
            )


def _elapsed_ms(started: datetime, finished: datetime) -> int:
    return max(int((finished - started).total_seconds() * 1000), 0)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "CHECK_REMEDIATION",
    "CONNECTION_CHECKS",
    "REQUIRED_CHECKS",
    "ArgConnectionProbe",
    "CheckResult",
    "ConnectionProbe",
    "ConnectionValidator",
    "ValidationReport",
]
