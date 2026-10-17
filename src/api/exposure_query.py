"""Scope-first, bounded queries over the Fabric SQL Exposure read model.

This module deliberately accepts an already-authorized identity and scope.  It
does not derive authorization from request parameters and it never falls back
to the Delta reader: every count, facet, and page operation is pushed into the
Fabric SQL endpoint with bound values and allowlisted identifiers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from api.evidence import classify_freshness
from fabric.sql_endpoint import FabricSqlReader
from intelligence.vulnerability.connector import canonical_enrichment_identifier
from intelligence.vulnerability.exposure_contracts import (
    ExposureCursorError,
    ExposureRestartConflict,
)
from operations.exposure_metrics import (
    ExposureMetrics,
    ExposureReconciliationPolicy,
    ExposureReconciliationReport,
    reconcile_exposure_arms,
)

EXPOSURE_FACTS_TABLE = "gold_exposure_facts"
EXPOSURE_EVIDENCE_TABLE = "gold_exposure_evidence"
SILVER_PATCH_FINDINGS_TABLE = "silver_patch_snapshot_findings"
SILVER_PATCH_SNAPSHOT_TABLE = "metadata_patch_snapshot"
SILVER_PATCH_GENERATION_PREFIX = "silver-patch:"
MAX_EXPOSURE_PAGE_SIZE = 100
MAX_KB_DETAIL_ROWS = 100
MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS = 64
MAX_KB_CVE_ASSOCIATIONS = 256
MAX_EXPOSURE_FILTER_VALUES = 50
MAX_SILVER_PATCH_SUBSCRIPTIONS = 500
MAX_EXPOSURE_FACETS = 8
MAX_FACET_ROWS = 1_000
MAX_EXPOSURE_QUERY_TIMEOUT_SECONDS = 30
CURSOR_TTL_SECONDS = 15 * 60
CURSOR_KEY_OVERLAP_SECONDS = 30 * 60
CURSOR_VERSION = 1
MAX_CURSOR_BYTES = 8_192

_CATALOG_PAYLOAD_FIELDS = {
    "nvd": frozenset(
        {
            "cve_id",
            "id",
            "title",
            "description",
            "severity",
            "cvss",
            "associated_kbs",
            "exploit_references",
        }
    ),
    "epss": frozenset({"cve", "epss_score", "epss_percentile"}),
    "kev": frozenset(
        {"kev_date_added", "kev_due_date", "kev_ransomware_use"}
    ),
    "msrc": frozenset(
        {
            "update_id",
            "kb_id",
            "title",
            "product_ids",
            "cve_ids",
            "published_at",
            "classification",
            "severity",
        }
    ),
}
_CATALOG_FORBIDDEN_KEYS = frozenset(
    {
        "target_id",
        "exposure_id",
        "fact_id",
        "scope_key",
        "tenant_id",
        "subscription_id",
        "connection_id",
        "environment",
        "affected_servers",
        "affected_applications",
        "affected_business_services",
        "findings",
    }
)

_PAGE_COLUMNS = (
    "exposure_id",
    "target_id",
    "target_kind",
    "weakness_id",
    "weakness_kind",
    "source_family",
    "source_state",
    "current_state",
    "active",
    "severity",
    "priority_score",
    "sla_state",
    "sla_age_seconds",
    "sla_target_seconds",
    "sla_due_at",
    "sla_overdue",
    "recommendation",
    "finding_title",
    "registry_id",
    "logical_image_id",
    "image_digest_id",
    "image_digest",
    "deployment_state",
    "represented_workload_count",
    "total_workload_count",
    "unknown_workload_count",
    "source_status",
    "completeness",
    "evidence_count",
    "detail_path",
    "timestamp",
    "ordering_priority_score",
    "ordering_severity_rank",
    "ordering_target_id",
    "fact_id",
)

_FILTER_FIELDS = {
    "active": "[active]",
    "completeness": "[completeness]",
    "current_state": "[current_state]",
    "deployment_state": "[deployment_state]",
    "severity": "[severity]",
    "sla_overdue": "[sla_overdue]",
    "sla_state": "[sla_state]",
    "source_family": "[source_family]",
    "source_state": "[source_state]",
    "target_kind": "[target_kind]",
    "weakness_id": "[weakness_id]",
}
# Enum-like text columns whose stored casing (e.g. Defender's "High"/"Critical")
# does not match the lowercase canonical values the UI sends (e.g. "high").
# Fabric's default collation is case-sensitive, so these comparisons must be
# folded on both sides or a legitimate filter silently matches zero rows.
_CASE_INSENSITIVE_FILTER_FIELDS = frozenset(
    {
        "completeness",
        "current_state",
        "deployment_state",
        "severity",
        "sla_state",
        "source_family",
        "source_state",
        "target_kind",
    }
)
_FACET_FIELDS = {
    "completeness": "[completeness]",
    "current_state": "[current_state]",
    "deployment_state": "[deployment_state]",
    "severity": "[severity]",
    "sla_state": "[sla_state]",
    "source_family": "[source_family]",
    "source_state": "[source_state]",
    "target_kind": "[target_kind]",
}
_SORT_FIELDS = {
    "priority_score": ("[ordering_priority_score]", "ordering_priority_score"),
    "severity": ("[ordering_severity_rank]", "ordering_severity_rank"),
    "target_id": ("[ordering_target_id]", "ordering_target_id"),
    "weakness_id": ("[weakness_id]", "weakness_id"),
}
_NUMERIC_SORT_FIELDS = frozenset({"priority_score", "severity"})
_COMPARISON_OPERATORS = {
    "eq": "=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}
_SUPPORTED_SCOPE_DIMENSIONS = frozenset(
    {"subscription", "subscription_connection"}
)
_CURSOR_KID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CVE_IDENTIFIER = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")
_CURSOR_FIELDS = frozenset(
    {
        "v",
        "sub",
        "tid",
        "connections",
        "scope",
        "generation",
        "filters",
        "sort",
        "page_size",
        "position",
        "iat",
        "exp",
        "kid",
    }
)


class ExposureQueryUnavailableError(RuntimeError):
    """Raised when the production Fabric SQL reader is unavailable."""


class ExposureKbIdentifierError(ValueError):
    """Raised when a KB detail request does not use a canonical identifier."""


@dataclass(frozen=True, slots=True)
class ExposureCursorKeyRing:
    """Managed active/previous HMAC keys loaded by one application revision."""

    active_kid: str
    active_key: bytes = field(repr=False)
    loaded_at: datetime
    previous_kid: str | None = None
    previous_key: bytes | None = field(default=None, repr=False)
    overlap_seconds: int = CURSOR_KEY_OVERLAP_SECONDS

    def __post_init__(self) -> None:
        active_kid = _validate_kid(self.active_kid, "active_kid")
        active_key = _validate_key(self.active_key, "active_key")
        loaded_at = _aware_utc(self.loaded_at, "loaded_at")
        previous_kid = (
            _validate_kid(self.previous_kid, "previous_kid")
            if self.previous_kid is not None
            else None
        )
        previous_key = (
            _validate_key(self.previous_key, "previous_key")
            if self.previous_key is not None
            else None
        )
        if (previous_kid is None) != (previous_key is None):
            raise ValueError(
                "Exposure previous_kid and previous_key must be provided together"
            )
        if previous_kid == active_kid and previous_key != active_key:
            raise ValueError(
                "Identical Exposure kids cannot identify different key material"
            )
        if (
            isinstance(self.overlap_seconds, bool)
            or not isinstance(self.overlap_seconds, int)
            or self.overlap_seconds < CURSOR_TTL_SECONDS
        ):
            raise ValueError(
                "Exposure cursor key overlap must cover at least one cursor TTL"
            )
        # Plan 04 retires the previous slot by making it identical to active.
        if previous_kid == active_kid and previous_key == active_key:
            previous_kid = None
            previous_key = None
        object.__setattr__(self, "active_kid", active_kid)
        object.__setattr__(self, "active_key", active_key)
        object.__setattr__(self, "loaded_at", loaded_at)
        object.__setattr__(self, "previous_kid", previous_kid)
        object.__setattr__(self, "previous_key", previous_key)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        loaded_at: datetime | None = None,
        overlap_seconds: int = CURSOR_KEY_OVERLAP_SECONDS,
    ) -> ExposureCursorKeyRing:
        values = environment if environment is not None else os.environ
        active_kid = str(
            values.get("EXPOSURE_CURSOR_ACTIVE_KID") or ""
        )
        active_key = str(
            values.get("EXPOSURE_CURSOR_ACTIVE_KEY") or ""
        ).encode()
        previous_kid = str(
            values.get("EXPOSURE_CURSOR_PREVIOUS_KID") or ""
        )
        previous_value = str(
            values.get("EXPOSURE_CURSOR_PREVIOUS_KEY") or ""
        )
        return cls(
            active_kid=active_kid,
            active_key=active_key,
            previous_kid=previous_kid or None,
            previous_key=previous_value.encode() if previous_value else None,
            loaded_at=loaded_at or datetime.now(UTC),
            overlap_seconds=overlap_seconds,
        )

    def verification_key(
        self,
        kid: str,
        *,
        now: datetime,
    ) -> bytes:
        if hmac.compare_digest(kid, self.active_kid):
            return self.active_key
        if self.previous_kid and hmac.compare_digest(kid, self.previous_kid):
            overlap_ends = self.loaded_at + timedelta(
                seconds=self.overlap_seconds
            )
            if now >= overlap_ends:
                raise ExposureCursorError(
                    "exposure_cursor_key_overlap_expired",
                    "Exposure cursor previous-key overlap has expired",
                )
            assert self.previous_key is not None
            return self.previous_key
        raise ExposureCursorError(
            "exposure_cursor_key_unavailable",
            "Exposure cursor signing key is unavailable",
        )


@dataclass(frozen=True, slots=True)
class ExposureAuthorization:
    """Server-derived identity and connection boundary for one query."""

    subject: str
    tenant_id: str
    connection_ids: tuple[str, ...]
    connection_subscriptions: Mapping[str, str] = field(default_factory=dict)
    scope: Mapping[str, Sequence[str]] = field(default_factory=dict)
    scope_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        subject = _required_text(self.subject, "subject")
        tenant_id = _required_text(self.tenant_id, "tenant_id").casefold()
        connection_ids = _canonical_values(self.connection_ids)
        if not connection_ids:
            raise ValueError(
                "Exposure authorization requires at least one connection_id"
            )
        connection_subscriptions = {
            str(connection_id or "").strip().casefold(): str(
                subscription_id or ""
            ).strip().casefold()
            for connection_id, subscription_id in dict(
                self.connection_subscriptions
            ).items()
            if str(connection_id or "").strip()
            and str(subscription_id or "").strip()
        }
        if not set(connection_subscriptions) <= set(connection_ids):
            raise ValueError(
                "Exposure connection subscription mapping exceeds authorization"
            )
        normalized_scope: dict[str, tuple[str, ...]] = {}
        for name, values in dict(self.scope).items():
            normalized_name = str(name or "").strip().casefold()
            if normalized_name not in _SUPPORTED_SCOPE_DIMENSIONS:
                raise ValueError(
                    f"Unsupported Exposure scope dimension: {normalized_name}"
                )
            canonical = _canonical_values(values)
            if canonical:
                normalized_scope[normalized_name] = canonical
        scoped_subscriptions = set(normalized_scope.get("subscription", ()))
        if scoped_subscriptions and not set(
            connection_subscriptions.values()
        ) <= scoped_subscriptions:
            raise ValueError(
                "Exposure connection subscription mapping exceeds scope"
            )
        scoped_connections = normalized_scope.get(
            "subscription_connection", ()
        )
        if scoped_connections and not set(scoped_connections) <= set(
            connection_ids
        ):
            raise ValueError(
                "Exposure scope contains a connection outside authorization"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "connection_ids", connection_ids)
        object.__setattr__(
            self,
            "connection_subscriptions",
            dict(sorted(connection_subscriptions.items())),
        )
        object.__setattr__(
            self,
            "scope",
            dict(sorted(normalized_scope.items())),
        )
        object.__setattr__(
            self,
            "scope_keys",
            _canonical_values(self.scope_keys),
        )

    def canonical_scope(self) -> dict[str, list[str]]:
        return {
            name: list(values)
            for name, values in sorted(self.scope.items())
        }


@dataclass(frozen=True, slots=True)
class ExposureProvenanceEvidence:
    """Aggregate active-fact provenance without exposing scoped identifiers."""

    generation: str
    active_fact_count: int
    expected_connection_fact_count: int
    legacy_connection_fact_count: int
    unexpected_connection_fact_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return the redacted API evidence payload."""
        return {
            "generation": self.generation,
            "active_fact_count": self.active_fact_count,
            "expected_connection_fact_count": self.expected_connection_fact_count,
            "legacy_connection_fact_count": self.legacy_connection_fact_count,
            "unexpected_connection_fact_count": (
                self.unexpected_connection_fact_count
            ),
        }


@dataclass(frozen=True, slots=True)
class ExposureFilter:
    field: str
    operator: str
    value: Any


@dataclass(frozen=True, slots=True)
class ExposureSort:
    field: str = "priority_score"
    direction: str = "desc"


@dataclass(frozen=True, slots=True)
class ExposureQuery:
    filters: tuple[ExposureFilter, ...] = ()
    facets: tuple[str, ...] = ()
    sort: ExposureSort = field(default_factory=ExposureSort)
    page_size: int = 50


@dataclass(frozen=True, slots=True)
class ExposureQueryPage:
    items: tuple[dict[str, Any], ...]
    total_count: int
    facets: dict[str, list[dict[str, Any]]]
    generation: str
    applied_scope: dict[str, list[str]]
    applied_filters: tuple[dict[str, Any], ...]
    applied_sort: dict[str, str]
    next_position: tuple[Any, str] | None
    completeness: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    next_cursor: str | None = None
    distinct_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExposureCursorState:
    generation: str
    position: tuple[Any, str]
    issued_at: int
    expires_at: int
    kid: str


@dataclass(frozen=True, slots=True)
class ExposureGenerationWindow:
    """Active generation and retained snapshots with their expiry times."""

    active_generation: str
    retained_generations: Mapping[str, datetime | None] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        active = _required_text(
            self.active_generation,
            "active_generation",
        )
        retained: dict[str, datetime | None] = {}
        for generation, expires_at in self.retained_generations.items():
            normalized = _required_text(generation, "retained_generation")
            retained[normalized] = (
                _aware_utc(expires_at, "retain_until")
                if expires_at is not None
                else None
            )
        object.__setattr__(self, "active_generation", active)
        object.__setattr__(
            self,
            "retained_generations",
            dict(sorted(retained.items())),
        )

    def require_readable(
        self,
        generation_id: str,
        *,
        now: datetime,
    ) -> str:
        generation = _required_text(
            generation_id,
            "read_model_generation_id",
        )
        if generation == self.active_generation:
            return generation
        if generation not in self.retained_generations:
            raise ExposureRestartConflict(
                "exposure_generation_evicted",
                generation=generation,
            )
        retain_until = self.retained_generations[generation]
        if retain_until is not None and now >= retain_until:
            raise ExposureRestartConflict(
                "exposure_generation_expired",
                generation=generation,
            )
        return generation


class ExposureCursorCodec:
    """Issue and verify canonical HMAC-SHA256 Exposure snapshot cursors."""

    def __init__(self, keyring: ExposureCursorKeyRing) -> None:
        self._keyring = keyring

    def issue(
        self,
        authorization: ExposureAuthorization,
        *,
        generation_id: str,
        query: ExposureQuery,
        position: tuple[Any, str],
        now: datetime | None = None,
    ) -> str:
        _validate_query(query)
        issued_at = int(_aware_utc(now or datetime.now(UTC), "now").timestamp())
        normalized_position = _cursor_payload_position(
            position,
            sort_field=query.sort.field,
        )
        payload = {
            "v": CURSOR_VERSION,
            **_cursor_binding(
                authorization,
                generation_id=generation_id,
                query=query,
            ),
            "position": list(normalized_position),
            "iat": issued_at,
            "exp": issued_at + CURSOR_TTL_SECONDS,
            "kid": self._keyring.active_kid,
        }
        encoded_payload = _base64url(_canonical_json(payload).encode())
        signature = hmac.new(
            self._keyring.active_key,
            encoded_payload.encode(),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_base64url(signature)}"

    def decode(
        self,
        cursor: str,
        *,
        authorization: ExposureAuthorization,
        query: ExposureQuery,
        expected_generation_id: str | None = None,
        now: datetime | None = None,
    ) -> ExposureCursorState:
        current = _aware_utc(now or datetime.now(UTC), "now")
        payload_part, signature_part = _split_cursor(cursor)
        payload_bytes = _decode_base64url(payload_part)
        if len(payload_bytes) > MAX_CURSOR_BYTES:
            raise _invalid_cursor("Exposure cursor payload is too large")
        try:
            payload = json.loads(payload_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _invalid_cursor("Exposure cursor payload is invalid") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != _CURSOR_FIELDS
            or payload.get("v") != CURSOR_VERSION
            or _canonical_json(payload).encode() != payload_bytes
        ):
            raise _invalid_cursor("Exposure cursor payload is invalid")
        kid = str(payload.get("kid") or "")
        key = self._keyring.verification_key(kid, now=current)
        expected_signature = hmac.new(
            key,
            payload_part.encode(),
            hashlib.sha256,
        ).digest()
        signature = _decode_base64url(signature_part)
        if not hmac.compare_digest(expected_signature, signature):
            raise _invalid_cursor("Exposure cursor signature is invalid")

        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        if (
            isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or expires_at - issued_at != CURSOR_TTL_SECONDS
            or issued_at > int(current.timestamp()) + 30
        ):
            raise _invalid_cursor("Exposure cursor timestamps are invalid")
        if int(current.timestamp()) >= expires_at:
            raise ExposureCursorError(
                "exposure_cursor_expired",
                "Exposure cursor has expired",
            )

        generation = _required_cursor_text(
            payload.get("generation"),
            "generation",
        )
        expected = _cursor_binding(
            authorization,
            generation_id=expected_generation_id or generation,
            query=query,
        )
        actual = {
            name: payload.get(name)
            for name in (
                "sub",
                "tid",
                "connections",
                "scope",
                "generation",
                "filters",
                "sort",
                "page_size",
            )
        }
        if not hmac.compare_digest(
            _canonical_json(actual),
            _canonical_json(expected),
        ):
            raise ExposureCursorError(
                "exposure_cursor_request_mismatch",
                "Exposure cursor does not match the authorized request binding",
            )
        position = _cursor_query_position(
            payload.get("position"),
            sort_field=query.sort.field,
        )
        return ExposureCursorState(
            generation=generation,
            position=position,
            issued_at=issued_at,
            expires_at=expires_at,
            kid=kid,
        )


@dataclass(frozen=True, slots=True)
class _CompiledQueries:
    count_sql: str
    facet_sql: str | None
    page_sql: str
    parameters: tuple[Any, ...]
    page_parameters: tuple[Any, ...]
    page_limit: int
    sort_position_column: str


@dataclass(frozen=True, slots=True)
class _SilverPatchSnapshot:
    generation: str
    ingestion_run_id: str | None
    completeness: str
    freshness_state: str
    freshness_at: str
    represented_connections: int
    expected_connections: int


class ExposureQueryService:
    """Execute one immutable, scope-first Exposure count/facet/page request."""

    def __init__(
        self,
        reader: FabricSqlReader | Any | None,
        *,
        cursor_codec: ExposureCursorCodec | None = None,
        generation_window: Any | None = None,
        authorization_resolver: Any | None = None,
        catalog_records_resolver: Any | None = None,
        catalog_records_refresher: Any | None = None,
        metrics: ExposureMetrics | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        timeout = getattr(reader, "timeout_seconds", None)
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= MAX_EXPOSURE_QUERY_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "Fabric SQL Exposure query timeout must be between 1 and "
                f"{MAX_EXPOSURE_QUERY_TIMEOUT_SECONDS} seconds"
            )
        self._reader = reader
        self._cursor_codec = cursor_codec
        self._generation_window = generation_window
        self._authorization_resolver = authorization_resolver
        self._catalog_records_resolver = catalog_records_resolver
        self._catalog_records_refresher = catalog_records_refresher
        self._metrics = metrics or ExposureMetrics()
        self._clock = clock

    def authorization_for(
        self,
        principal: Any,
        scope: Any,
    ) -> ExposureAuthorization:
        """Resolve server-owned tenant/connections for an effective API scope."""
        if not callable(self._authorization_resolver):
            raise ExposureQueryUnavailableError(
                "Exposure authorization resolver is unavailable"
            )
        authorization = self._authorization_resolver(principal, scope)
        if not isinstance(authorization, ExposureAuthorization):
            raise TypeError(
                "Exposure authorization resolver must return "
                "ExposureAuthorization"
            )
        subject = str(getattr(principal, "subject", "") or "")
        if not hmac.compare_digest(authorization.subject, subject):
            raise PermissionError(
                "Exposure authorization does not match the authenticated caller"
            )
        effective_scope = (
            scope.to_dict()
            if scope is not None and hasattr(scope, "to_dict")
            else None
        )
        if effective_scope is None:
            raise TypeError(
                "Exposure authorization requires a server-derived effective scope"
            )
        for dimension, values in effective_scope.items():
            if dimension not in _SUPPORTED_SCOPE_DIMENSIONS:
                raise ValueError(
                    f"Unsupported Exposure scope dimension: {dimension}"
                )
            if set(values) != set(authorization.scope.get(dimension, ())):
                raise PermissionError(
                    "Exposure authorization does not match the effective scope"
                )
        return authorization

    def readable_generation_id(self) -> str:
        """Resolve the active readable Exposure generation once for a request."""

        window = (
            self._generation_window()
            if callable(self._generation_window)
            else self._generation_window
        )
        if not isinstance(window, ExposureGenerationWindow):
            raise ExposureQueryUnavailableError(
                "Exposure readable generation is unavailable"
            )
        generation = str(window.active_generation or "").strip()
        if not generation:
            raise ExposureQueryUnavailableError(
                "Exposure readable generation is unavailable"
            )
        return generation

    def active_provenance_evidence(
        self,
        authorization: ExposureAuthorization,
        *,
        generation_id: str,
        expected_connection_id: str,
    ) -> ExposureProvenanceEvidence:
        """Count active server/AUM facts by redacted connection provenance."""
        if self._reader is None:
            raise ExposureQueryUnavailableError(
                "Fabric SQL Exposure reader is unavailable; Delta fallback is disabled"
            )
        expected_connection = _required_text(
            expected_connection_id,
            "expected_connection_id",
        ).casefold()
        if expected_connection not in authorization.connection_ids:
            raise PermissionError(
                "Expected Exposure connection is outside authorization"
            )
        scoped_connections = authorization.scope.get(
            "subscription_connection",
            (),
        )
        if scoped_connections and expected_connection not in scoped_connections:
            raise PermissionError(
                "Expected Exposure connection is outside the effective scope"
            )
        generation = _required_text(
            generation_id,
            "read_model_generation_id",
        )
        if not generation.startswith(SILVER_PATCH_GENERATION_PREFIX):
            raise ValueError(
                "Exposure provenance evidence requires a Silver patch generation"
            )
        mapped_subscription = authorization.connection_subscriptions.get(
            expected_connection
        )
        if not mapped_subscription:
            raise PermissionError(
                "Expected Exposure connection has no authorized subscription"
            )
        scoped_authorization = ExposureAuthorization(
            subject=authorization.subject,
            tenant_id=authorization.tenant_id,
            connection_ids=(expected_connection,),
            connection_subscriptions={
                expected_connection: mapped_subscription,
            },
            scope={
                "subscription": (mapped_subscription,),
                "subscription_connection": (expected_connection,),
            },
        )
        schema = getattr(
            getattr(self._reader, "endpoint", None),
            "schema",
            "dbo",
        )
        snapshot = _silver_patch_snapshot(
            self._reader,
            scoped_authorization,
            schema=schema,
            now=datetime.now(UTC),
        )
        if generation != snapshot.generation:
            raise ExposureRestartConflict(
                "exposure_generation_evicted",
                generation=generation,
            )
        table = (
            f"{_identifier(schema)}.{_identifier(SILVER_PATCH_FINDINGS_TABLE)}"
        )
        predicates, parameters = _silver_patch_scope(scoped_authorization)
        if snapshot.ingestion_run_id is None:
            predicates.append("1 = 0")
        else:
            predicates.append("[ingestion_run_id] = ?")
            parameters.append(snapshot.ingestion_run_id)
        predicates.append(
            "LOWER([status]) IN ('missing', 'installation_failed')"
        )
        sql = (
            "SELECT "
            "COUNT_BIG(DISTINCT [resource_id]) AS [active_fact_count], "
            "COUNT_BIG(DISTINCT CASE WHEN LOWER([connection_id]) = ? "
            "THEN [resource_id] END) AS [expected_connection_fact_count], "
            "COUNT_BIG(DISTINCT CASE WHEN LOWER([connection_id]) LIKE 'legacy:%' "
            "THEN [resource_id] END) AS [legacy_connection_fact_count], "
            "COUNT_BIG(DISTINCT CASE WHEN "
            "LOWER(COALESCE([connection_id], '')) <> ? "
            "THEN [resource_id] END) AS [unexpected_connection_fact_count] "
            f"FROM {table} WHERE {' AND '.join(predicates)}"
        )
        rows = self._reader.query(
            sql,
            (expected_connection, expected_connection, *parameters),
            max_rows=1,
        )
        row = rows[0] if rows else {}
        return ExposureProvenanceEvidence(
            generation=generation,
            active_fact_count=max(0, int(row.get("active_fact_count") or 0)),
            expected_connection_fact_count=max(
                0,
                int(row.get("expected_connection_fact_count") or 0),
            ),
            legacy_connection_fact_count=max(
                0,
                int(row.get("legacy_connection_fact_count") or 0),
            ),
            unexpected_connection_fact_count=max(
                0,
                int(row.get("unexpected_connection_fact_count") or 0),
            ),
        )

    def reconcile_shadow_page(
        self,
        *,
        old_rows: Iterable[Mapping[str, Any]],
        new_rows: Iterable[Mapping[str, Any]],
        generation_id: str,
        old_completeness: str,
        new_completeness: str,
        authorized_scope_keys: Iterable[str],
        expected_changes: (
            Mapping[tuple[str, str], Iterable[str]] | None
        ) = None,
        policy: ExposureReconciliationPolicy | None = None,
    ) -> ExposureReconciliationReport:
        """Compare one representative old/new read at one generation."""

        return reconcile_exposure_arms(
            old_rows,
            new_rows,
            generation_id=generation_id,
            old_completeness=old_completeness,
            new_completeness=new_completeness,
            authorized_scope_keys=authorized_scope_keys,
            expected_changes=expected_changes,
            policy=policy,
            metrics=self._metrics,
            checkpoint="representative_read",
        )

    def list_page(
        self,
        authorization: ExposureAuthorization,
        *,
        generation_id: str | None = None,
        query: ExposureQuery,
        after: tuple[Any, str] | None = None,
        cursor: str | None = None,
        now: datetime | None = None,
    ) -> ExposureQueryPage:
        if self._reader is None:
            raise ExposureQueryUnavailableError(
                "Fabric SQL Exposure reader is unavailable; Delta fallback is disabled"
            )
        current = _aware_utc(now or datetime.now(UTC), "now")
        if cursor and after is not None:
            raise ValueError("Exposure cursor and raw position are mutually exclusive")
        use_silver_patch = _is_silver_patch_query(authorization, query)
        schema = getattr(
            getattr(self._reader, "endpoint", None),
            "schema",
            "dbo",
        )
        silver_snapshot = (
            _silver_patch_snapshot(
                self._reader,
                authorization,
                schema=schema,
                now=current,
            )
            if use_silver_patch
            else None
        )
        window = (
            (
                self._generation_window()
                if callable(self._generation_window)
                else self._generation_window
            )
            if not use_silver_patch
            else None
        )
        if window is not None and not isinstance(
            window,
            ExposureGenerationWindow,
        ):
            raise TypeError(
                "Exposure generation_window must return ExposureGenerationWindow"
            )
        if cursor:
            if self._cursor_codec is None:
                raise ExposureQueryUnavailableError(
                    "Exposure cursor verification is unavailable"
                )
            if window is None and not use_silver_patch:
                raise ExposureQueryUnavailableError(
                    "Exposure generation retention state is unavailable"
                )
            try:
                cursor_state = self._cursor_codec.decode(
                    cursor,
                    authorization=authorization,
                    query=query,
                    expected_generation_id=(
                        generation_id
                        if not use_silver_patch
                        or str(generation_id or "").startswith(
                            SILVER_PATCH_GENERATION_PREFIX
                        )
                        else None
                    ),
                    now=current,
                )
                if use_silver_patch:
                    generation = cursor_state.generation
                    if generation != silver_snapshot.generation:
                        raise ExposureRestartConflict(
                            "exposure_generation_evicted",
                            generation=generation,
                        )
                else:
                    generation = window.require_readable(
                        cursor_state.generation,
                        now=current,
                    )
            except ExposureRestartConflict:
                self._metrics.record_query_event(
                    operation="cursor",
                    outcome="restart",
                )
                raise
            except ExposureCursorError:
                self._metrics.record_query_event(
                    operation="cursor",
                    outcome="error",
                )
                raise
            else:
                self._metrics.record_query_event(
                    operation="cursor",
                    outcome="ok",
                )
            after = cursor_state.position
        else:
            if use_silver_patch:
                requested_generation = str(generation_id or "")
                generation = (
                    requested_generation
                    if requested_generation.startswith(
                        SILVER_PATCH_GENERATION_PREFIX
                    )
                    else str(silver_snapshot.generation)
                )
                if generation != silver_snapshot.generation:
                    raise ExposureRestartConflict(
                        "exposure_generation_evicted",
                        generation=generation,
                    )
            else:
                selected_generation = (
                    generation_id
                    or (
                        window.active_generation
                        if window is not None
                        else None
                    )
                )
                generation = _required_text(
                    selected_generation,
                    "read_model_generation_id",
                )
                if window is not None:
                    generation = window.require_readable(
                        generation,
                        now=current,
                    )
        compiled = (
            _compile_silver_patch_queries(
                authorization,
                snapshot=silver_snapshot,
                query=query,
                after=after,
                schema=schema,
            )
            if use_silver_patch
            else _compile_queries(
                authorization,
                generation_id=generation,
                query=query,
                after=after,
                schema=schema,
            )
        )
        count_started = self._clock()
        try:
            count_rows = self._reader.query(
                compiled.count_sql,
                compiled.parameters,
                max_rows=1,
            )
        except Exception:
            self._metrics.record_query(
                operation="count",
                duration_ms=(self._clock() - count_started) * 1000.0,
                rows_returned=0,
                outcome="error",
            )
            raise
        total_count = (
            max(0, int(count_rows[0].get("total_count") or 0))
            if count_rows
            else 0
        )
        count_row = count_rows[0] if count_rows else {}
        distinct_counts = {}
        for name in ("targets", "weaknesses", "recorded_digests"):
            value = count_row.get(f"distinct_{name}")
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > total_count:
                    raise ValueError("Exposure distinct counts are inconsistent")
                distinct_counts[name] = value
        self._metrics.record_query(
            operation="count",
            duration_ms=(self._clock() - count_started) * 1000.0,
            rows_returned=total_count,
            outcome="ok",
        )
        completeness = _completeness_payload(
            total_count,
            count_row.get("all_complete"),
        )
        freshness = _freshness_payload(count_row.get("freshest_at"))
        if use_silver_patch:
            completeness = {
                "state": silver_snapshot.completeness,
                "represented_connections": (
                    silver_snapshot.represented_connections
                ),
                "expected_connections": silver_snapshot.expected_connections,
            }
            freshness = {
                "state": silver_snapshot.freshness_state,
                "as_of": silver_snapshot.freshness_at,
            }
        facet_rows: list[dict[str, Any]] = []
        if compiled.facet_sql:
            facet_started = self._clock()
            try:
                facet_rows = self._reader.query(
                    compiled.facet_sql,
                    compiled.parameters,
                    max_rows=MAX_FACET_ROWS,
                )
            except Exception:
                self._metrics.record_query(
                    operation="facet",
                    duration_ms=(self._clock() - facet_started) * 1000.0,
                    rows_returned=0,
                    outcome="error",
                )
                raise
            self._metrics.record_query(
                operation="facet",
                duration_ms=(self._clock() - facet_started) * 1000.0,
                rows_returned=len(facet_rows),
                outcome="ok",
            )
        page_started = self._clock()
        try:
            raw_page = self._reader.query(
                compiled.page_sql,
                compiled.page_parameters,
                max_rows=compiled.page_limit,
            )
        except Exception:
            self._metrics.record_query(
                operation="page",
                duration_ms=(self._clock() - page_started) * 1000.0,
                rows_returned=0,
                outcome="error",
            )
            raise
        has_more = len(raw_page) > query.page_size
        selected = raw_page[: query.page_size]
        self._metrics.record_query(
            operation="page",
            duration_ms=(self._clock() - page_started) * 1000.0,
            rows_returned=len(selected),
            outcome="ok",
        )
        next_position: tuple[Any, str] | None = None
        if has_more and selected:
            last = selected[-1]
            position_value = last.get(compiled.sort_position_column)
            if position_value is None:
                position_value = last.get(query.sort.field)
            next_position = (
                position_value,
                str(last.get("exposure_id") or ""),
            )
        next_cursor = (
            self._cursor_codec.issue(
                authorization,
                generation_id=generation,
                query=query,
                position=next_position,
                now=current,
            )
            if next_position is not None and self._cursor_codec is not None
            else None
        )
        return ExposureQueryPage(
            items=tuple(_public_row(row) for row in selected),
            total_count=total_count,
            facets=_facet_payload(facet_rows),
            generation=generation,
            applied_scope=authorization.canonical_scope(),
            applied_filters=_canonical_filter_payload(query.filters),
            applied_sort={
                "field": query.sort.field,
                "direction": query.sort.direction,
            },
            next_position=next_position,
            completeness=completeness,
            freshness=freshness,
            next_cursor=next_cursor,
            distinct_counts=distinct_counts,
        )

    def catalog_item(
        self,
        authorization: ExposureAuthorization,
        *,
        generation_id: str | None,
        weakness_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if self._reader is None:
            raise ExposureQueryUnavailableError(
                "Fabric SQL Exposure reader is unavailable; Delta fallback is disabled"
            )
        identifier = _required_text(weakness_id, "weakness_id").upper()
        if not _CVE_IDENTIFIER.fullmatch(identifier):
            raise ValueError("External catalog lookup requires a canonical CVE identifier")
        current = _aware_utc(now or datetime.now(UTC), "now")
        window = (
            self._generation_window()
            if callable(self._generation_window)
            else self._generation_window
        )
        if window is not None and not isinstance(
            window,
            ExposureGenerationWindow,
        ):
            raise TypeError(
                "Exposure generation_window must return ExposureGenerationWindow"
            )
        selected_generation = generation_id or (
            window.active_generation if window is not None else None
        )
        generation = _required_text(
            selected_generation,
            "read_model_generation_id",
        )
        if window is not None:
            generation = window.require_readable(generation, now=current)

        schema = getattr(
            getattr(self._reader, "endpoint", None),
            "schema",
            "dbo",
        )
        facts = f"{_identifier(schema)}.{_identifier(EXPOSURE_FACTS_TABLE)}"
        evidence = f"{_identifier(schema)}.{_identifier(EXPOSURE_EVIDENCE_TABLE)}"
        predicates = ["[tenant_id] = ?"]
        parameters: list[Any] = [authorization.tenant_id]
        _append_in_predicate(
            predicates,
            parameters,
            "[connection_id]",
            authorization.connection_ids,
        )
        subscriptions = tuple(authorization.scope.get("subscription", ()))
        if subscriptions:
            _append_in_predicate(
                predicates,
                parameters,
                "[subscription_id]",
                subscriptions,
            )
        if authorization.scope_keys:
            _append_in_predicate(
                predicates,
                parameters,
                "[scope_key]",
                authorization.scope_keys,
            )
        predicates.append("[read_model_generation_id] = ?")
        parameters.append(generation)
        membership_parameters = (*parameters, identifier)
        membership_sql = (
            f"SELECT TOP (1) [fact_id] FROM {facts} WHERE "
            f"{' AND '.join(predicates)} AND [weakness_id] = ? "
            "ORDER BY [fact_id] ASC"
        )
        membership = self._reader.query(
            membership_sql,
            membership_parameters,
            max_rows=1,
        )
        parameters.extend((identifier, identifier))
        public_columns = (
            "source",
            "identifier",
            "status",
            "stale",
            "lkg_available",
            "safe_error_code",
            "attempted_at",
            "succeeded_at",
            "source_at",
            "enriched_at",
            "payload_json",
        )
        inner_projection = ", ".join(
            f"[e].{_identifier(column)} AS {_identifier(column)}"
            for column in public_columns
        )
        outer_projection = ", ".join(_identifier(column) for column in public_columns)
        limit = MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS + 1
        sql = (
            "WITH [authorized_facts] AS ("
            f"SELECT DISTINCT [fact_id] FROM {facts} WHERE "
            f"{' AND '.join(predicates)}"
            "), [ranked_evidence] AS ("
            f"SELECT {inner_projection}, "
            "ROW_NUMBER() OVER (PARTITION BY [e].[source], [e].[identifier] "
            "ORDER BY [e].[enriched_at] DESC, [e].[evidence_id] ASC) "
            "AS [evidence_rank] "
            f"FROM {evidence} AS [e] "
            "INNER JOIN [authorized_facts] AS [a] ON [a].[fact_id] = [e].[fact_id] "
            "WHERE [e].[identifier] = ? OR "
            "([e].[source] = 'msrc' AND EXISTS ("
            "SELECT 1 FROM OPENJSON([e].[payload_json], '$.cve_ids') "
            "WITH ([cve_id] nvarchar(256) '$') AS [ids] "
            "WHERE [ids].[cve_id] = ?))"
            ") "
            f"SELECT TOP ({limit}) {outer_projection} FROM [ranked_evidence] "
            "WHERE [evidence_rank] = 1 "
            "ORDER BY [source] ASC, [identifier] ASC, [enriched_at] DESC"
        )
        rows = (
            self._reader.query(
                sql,
                tuple(parameters),
                max_rows=limit,
            )
            if membership
            else []
        )
        if len(rows) > MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS:
            raise ExposureQueryUnavailableError(
                "External vulnerability catalog evidence exceeded its safe bound"
            )
        resolved_rows = list(rows)
        if callable(self._catalog_records_refresher):
            resolved_rows.extend(
                dict(row)
                for row in self._catalog_records_refresher(identifier)
                if isinstance(row, Mapping)
            )
        elif callable(self._catalog_records_resolver):
            resolved_rows.extend(
                dict(row)
                for row in self._catalog_records_resolver(identifier)
                if isinstance(row, Mapping)
            )
        sources: dict[str, dict[str, Any]] = {}
        for row in sorted(
            resolved_rows,
            key=lambda value: (
                str(value.get("source") or ""),
                str(value.get("identifier") or ""),
                str(value.get("enriched_at") or ""),
            ),
            reverse=True,
        ):
            source = str(row.get("source") or "").strip().casefold()
            source_identifier = str(row.get("identifier") or "")
            key = f"{source}:{source_identifier}" if source == "msrc" else source
            if not source or key in sources:
                continue
            if len(sources) >= MAX_EXTERNAL_CATALOG_EVIDENCE_ROWS:
                raise ExposureQueryUnavailableError(
                    "External vulnerability catalog evidence exceeded its safe bound"
                )
            payload_value = row.get("payload")
            payload = (
                _catalog_payload(source, json.dumps(payload_value))
                if isinstance(payload_value, Mapping)
                else _catalog_payload(source, row.get("payload_json"))
            )
            sources[key] = {
                "source": source,
                "identifier": source_identifier,
                "status": str(row.get("status") or "unknown"),
                "stale": bool(row.get("stale")),
                "has_last_known_good": bool(
                    row.get("lkg_available")
                    or row.get("has_last_known_good")
                    or payload is not None
                ),
                "safe_error_code": str(row.get("safe_error_code") or ""),
                "attempted_at": str(row.get("attempted_at") or ""),
                "succeeded_at": str(row.get("succeeded_at") or ""),
                "source_at": str(row.get("source_at") or ""),
                "enriched_at": str(row.get("enriched_at") or ""),
                "payload": payload,
            }
        if not sources:
            return None
        return {
            "contract_version": "1.0.0",
            "catalog_scope": "external_public_metadata",
            "environment_membership_included": False,
            "generation": generation,
            "item": {
                "cve_id": identifier,
                "sources": sources,
            },
        }

    def kb_item(
        self,
        authorization: ExposureAuthorization,
        *,
        kb_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Return one authorized KB detail from Silver plus durable metadata."""

        if self._reader is None:
            raise ExposureQueryUnavailableError(
                "Fabric SQL Exposure reader is unavailable; Delta fallback is disabled"
            )
        try:
            raw_identifier = _required_text(kb_id, "kb_id")
        except ValueError as exc:
            raise ExposureKbIdentifierError(
                "KB detail requires a canonical KB identifier"
            ) from exc
        if len(raw_identifier) > 32:
            raise ExposureKbIdentifierError(
                "KB detail requires a canonical KB identifier"
            )
        try:
            identifier = canonical_enrichment_identifier("msrc", raw_identifier)
        except ValueError as exc:
            raise ExposureKbIdentifierError(
                "KB detail requires a canonical KB identifier"
            ) from exc
        current = _aware_utc(now or datetime.now(UTC), "now")
        schema = getattr(
            getattr(self._reader, "endpoint", None),
            "schema",
            "dbo",
        )
        snapshot = _silver_patch_snapshot(
            self._reader,
            authorization,
            schema=schema,
            now=current,
        )
        if snapshot.ingestion_run_id is None:
            return None
        table = f"{_identifier(schema)}.{_identifier(SILVER_PATCH_FINDINGS_TABLE)}"
        predicates, parameters = _silver_patch_scope(authorization)
        predicates.extend(
            (
                "[ingestion_run_id] = ?",
                f"{_silver_patch_weakness_sql()} = ?",
            )
        )
        parameters.extend((snapshot.ingestion_run_id, identifier))
        limit = MAX_KB_DETAIL_ROWS
        rows = self._reader.query(
            "WITH [ranked_targets] AS ("
            "SELECT [update_name], [severity], [published_at], "
            "[target_resource_id], [status], [timestamp], [last_modified], "
            "ROW_NUMBER() OVER (PARTITION BY [subscription_id], [target_resource_id] "
            "ORDER BY TRY_CONVERT(datetimeoffset, NULLIF([last_modified], '')) DESC, "
            "TRY_CONVERT(datetimeoffset, NULLIF([timestamp], '')) DESC, "
            "CASE WHEN LOWER([status]) IN ('missing', 'installation_failed') "
            "THEN 0 ELSE 1 END, [resource_id] ASC) AS [target_rank] "
            f"FROM {table} WHERE {' AND '.join(predicates)}"
            "), [latest_targets] AS ("
            "SELECT [update_name], [severity], [published_at], "
            "[target_resource_id], [status], [timestamp], "
            "SUM(CASE WHEN LOWER([status]) IN ('missing', 'installation_failed') "
            "THEN 1 ELSE 0 END) OVER () AS [affected_server_count] "
            "FROM [ranked_targets] WHERE [target_rank] = 1"
            ") "
            f"SELECT TOP ({limit}) [update_name], [severity], [published_at], "
            "[target_resource_id], [status], [timestamp], [affected_server_count] "
            "FROM [latest_targets] "
            "ORDER BY CASE WHEN LOWER([status]) IN ('missing', 'installation_failed') "
            "THEN 0 ELSE 1 END, [timestamp] DESC, [target_resource_id] ASC",
            tuple(parameters),
            max_rows=limit,
        )
        if not rows:
            return None

        catalog_records = (
            tuple(self._catalog_records_resolver(identifier))
            if callable(self._catalog_records_resolver)
            else ()
        )
        msrc_record = _latest_catalog_record(
            catalog_records,
            source="msrc",
            identifier=identifier,
        )
        msrc_payload = _record_catalog_payload(msrc_record)
        raw_cve_ids = (
            msrc_payload.get("cve_ids", ())
            if isinstance(msrc_payload, Mapping)
            else ()
        )
        cve_ids = tuple(
            sorted(
                {
                    str(value or "").strip().upper()
                    for value in raw_cve_ids
                    if _CVE_IDENTIFIER.fullmatch(
                        str(value or "").strip().upper()
                    )
                }
            )
        )
        if len(cve_ids) > MAX_KB_CVE_ASSOCIATIONS:
            raise ExposureQueryUnavailableError(
                "KB detail exceeded its safe CVE association bound"
            )
        cves: list[dict[str, Any]] = []
        cve_source_states: dict[str, dict[str, Any]] = {}
        for cve_id in cve_ids:
            cve, source_states_for_cve = _kb_cve_detail(
                cve_id,
                tuple(self._catalog_records_resolver(cve_id))
                if callable(self._catalog_records_resolver)
                else (),
            )
            cves.append(cve)
            cve_source_states.update(source_states_for_cve)
        source_state = _kb_msrc_source_state(
            identifier,
            msrc_record,
            msrc_payload,
        )
        source_states = {
            f"msrc:{identifier}": source_state,
            **cve_source_states,
        }
        complete = all(_kb_source_complete(state) for state in source_states.values())
        available_count = sum(
            1 for state in source_states.values() if state["has_last_known_good"]
        )
        stale = any(bool(state["stale"]) for state in source_states.values())
        affected_servers = sorted(
            {
                str(row.get("target_resource_id") or "")
                for row in rows
                if str(row.get("target_resource_id") or "")
                and str(row.get("status") or "").casefold()
                in {"missing", "installation_failed"}
            }
        )
        affected_server_count = max(
            (int(row.get("affected_server_count") or 0) for row in rows),
            default=0,
        )
        return {
            "generation": snapshot.generation,
            "snapshot_freshness_at": snapshot.freshness_at,
            "snapshot": {
                "completeness": snapshot.completeness,
                "freshness": snapshot.freshness_state,
                "as_of": snapshot.freshness_at,
            },
            "kb_id": identifier,
            "title": str(
                (msrc_payload or {}).get("title")
                or next(
                    (
                        row.get("update_name")
                        for row in rows
                        if str(row.get("update_name") or "").strip()
                    ),
                    "",
                )
            ),
            "severity": str(
                (msrc_payload or {}).get("severity")
                or _highest_severity(rows)
                or "Unknown"
            ),
            "published_at": str(
                (msrc_payload or {}).get("published_at")
                or max(
                    (str(row.get("published_at") or "") for row in rows),
                    default="",
                )
            ),
            "cve_ids": list(cve_ids),
            "cves": cves,
            "affected_servers": affected_servers,
            "affected_server_count": affected_server_count,
            "affected_servers_truncated": affected_server_count
            > len(affected_servers),
            "affected_business_services": [],
            "findings": [],
            "enrichment": {
                "status": (
                    "complete"
                    if complete
                    else "degraded"
                    if available_count
                    else "unavailable"
                ),
                "complete": complete,
                "stale": stale,
                "expected_count": len(source_states),
                "available_count": available_count,
                "sources": source_states,
            },
        }


def _catalog_payload(source: str, value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, Mapping):
        return None
    allowed = _CATALOG_PAYLOAD_FIELDS.get(source, frozenset())
    payload = {
        str(key): _catalog_public_value(item)
        for key, item in parsed.items()
        if str(key) in allowed and str(key).casefold() not in _CATALOG_FORBIDDEN_KEYS
    }
    return payload or None


def _catalog_public_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _catalog_public_value(item)
            for key, item in value.items()
            if str(key).casefold() not in _CATALOG_FORBIDDEN_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_catalog_public_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _latest_catalog_record(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str,
    identifier: str,
) -> dict[str, Any] | None:
    matches = [
        dict(record)
        for record in records
        if str(record.get("source") or "").casefold() == source
        and str(record.get("identifier") or "").upper() == identifier
    ]
    return max(
        matches,
        key=lambda record: str(
            record.get("enriched_at")
            or record.get("succeeded_at")
            or record.get("attempted_at")
            or ""
        ),
        default=None,
    )


def _record_catalog_payload(
    record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if record is None:
        return None
    source = str(record.get("source") or "").casefold()
    payload = record.get("payload")
    return (
        _catalog_payload(source, json.dumps(payload))
        if isinstance(payload, Mapping)
        else _catalog_payload(source, record.get("payload_json"))
    )


def _kb_msrc_source_state(
    identifier: str,
    record: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return _kb_catalog_source_state("msrc", identifier, record, payload)


def _kb_catalog_source_state(
    source: str,
    identifier: str,
    record: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "source": source,
        "identifier": identifier,
        "status": str((record or {}).get("status") or "failed"),
        "stale": bool((record or {}).get("stale")),
        "safe_error_code": str(
            (record or {}).get("safe_error_code")
            or ("" if payload else "provider_unavailable")
        ),
        "attempted_at": (record or {}).get("attempted_at"),
        "succeeded_at": (record or {}).get("succeeded_at"),
        "source_at": (record or {}).get("source_at"),
        "enriched_at": (record or {}).get("enriched_at"),
        "refresh_after": (record or {}).get("refresh_after"),
        "has_last_known_good": payload is not None,
    }


def _kb_cve_detail(
    cve_id: str,
    records: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    retained_records = tuple(records)
    nvd_record = _latest_catalog_record(
        retained_records,
        source="nvd",
        identifier=cve_id,
    )
    epss_record = _latest_catalog_record(
        retained_records,
        source="epss",
        identifier=cve_id,
    )
    kev_record = _latest_catalog_record(
        retained_records,
        source="kev",
        identifier=cve_id,
    )
    nvd_payload = _record_catalog_payload(nvd_record) or {}
    epss_payload = _record_catalog_payload(epss_record) or {}
    kev_payload = _record_catalog_payload(kev_record) or {}
    cvss = nvd_payload.get("cvss")
    severity = str(nvd_payload.get("severity") or "Unknown")
    epss_score = _optional_probability(epss_payload.get("epss_score"))
    epss_percentile = _optional_probability(
        epss_payload.get("epss_percentile")
    )
    return (
        {
            "cve_id": cve_id,
            "title": str(nvd_payload.get("title") or cve_id),
            "severity": severity,
            "cvss": (
                dict(cvss)
                if isinstance(cvss, Mapping)
                else {"base_score": None, "vector": "", "severity": severity}
            ),
            "epss_score": epss_score,
            "epss_percentile": epss_percentile,
            "is_known_exploited": bool(kev_payload) if kev_record else None,
            "kev_due_date": str(kev_payload.get("kev_due_date") or ""),
        },
        {
            f"nvd:{cve_id}": _kb_catalog_source_state(
                "nvd",
                cve_id,
                nvd_record,
                nvd_payload or None,
            ),
            f"epss:{cve_id}": _kb_catalog_source_state(
                "epss",
                cve_id,
                epss_record,
                epss_payload or None,
            ),
            f"kev:{cve_id}": _kb_catalog_source_state(
                "kev",
                cve_id,
                kev_record,
                kev_payload if kev_record else None,
            ),
        },
    )


def _optional_probability(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and 0.0 <= number <= 1.0 else None


def _kb_source_complete(state: Mapping[str, Any]) -> bool:
    return (
        str(state.get("status") or "").casefold() == "succeeded"
        and bool(state.get("has_last_known_good"))
        and not bool(state.get("stale"))
    )


def _highest_severity(rows: Iterable[Mapping[str, Any]]) -> str:
    ranks = {
        "unknown": 0,
        "low": 1,
        "moderate": 2,
        "medium": 2,
        "security": 3,
        "important": 3,
        "high": 3,
        "critical": 4,
    }
    return max(
        (str(row.get("severity") or "") for row in rows),
        key=lambda value: ranks.get(value.casefold(), 0),
        default="",
    )


def _compile_queries(
    authorization: ExposureAuthorization,
    *,
    generation_id: str,
    query: ExposureQuery,
    after: tuple[Any, str] | None,
    schema: str,
) -> _CompiledQueries:
    _validate_query(query)
    table = f"{_identifier(schema)}.{_identifier(EXPOSURE_FACTS_TABLE)}"
    predicates = ["[tenant_id] = ?"]
    parameters: list[Any] = [authorization.tenant_id]
    _append_in_predicate(
        predicates,
        parameters,
        "[connection_id]",
        authorization.connection_ids,
    )
    subscriptions = tuple(
        authorization.scope.get("subscription", ())
    )
    if subscriptions:
        _append_in_predicate(
            predicates,
            parameters,
            "[subscription_id]",
            subscriptions,
        )
    if authorization.scope_keys:
        _append_in_predicate(
            predicates,
            parameters,
            "[scope_key]",
            authorization.scope_keys,
        )
    predicates.append("[read_model_generation_id] = ?")
    parameters.append(generation_id)
    _append_filter_predicates(predicates, parameters, query.filters)

    projection = ", ".join(_identifier(column) for column in _PAGE_COLUMNS)
    where_sql = " AND ".join(predicates)
    scoped_cte = (
        "WITH [scoped] AS ("
        f"SELECT {projection} FROM {table} WHERE {where_sql}"
        ")"
    )
    count_sql = (
        f"{scoped_cte} "
        "SELECT COUNT_BIG(DISTINCT [exposure_id]) AS [total_count], "
        "COUNT_BIG(DISTINCT NULLIF(LOWER([target_id]), '')) AS [distinct_targets], "
        "COUNT_BIG(DISTINCT NULLIF(LOWER([weakness_id]), '')) AS [distinct_weaknesses], "
        "COUNT_BIG(DISTINCT NULLIF(LOWER([image_digest]), '')) AS [distinct_recorded_digests], "
        "MAX([timestamp]) AS [freshest_at], "
        "MIN(CASE WHEN [completeness] = 'complete' THEN 1 ELSE 0 END) "
        "AS [all_complete] "
        "FROM [scoped]"
    )
    facet_sql = _compile_facet_sql(scoped_cte, query.facets)

    sort_sql, position_column = _SORT_FIELDS[query.sort.field]
    direction = query.sort.direction.upper()
    keyset = ""
    page_parameters = list(parameters)
    if after is not None:
        if len(after) != 2 or not str(after[1] or ""):
            raise ValueError(
                "Exposure cursor position must contain sort value and exposure_id"
            )
        comparison = "<" if direction == "DESC" else ">"
        keyset = (
            f" AND ({sort_sql} {comparison} ? OR "
            f"({sort_sql} = ? AND [exposure_id] > ?))"
        )
        page_parameters.extend((after[0], after[0], str(after[1])))
    page_limit = query.page_size + 1
    page_sql = (
        f"{scoped_cte}, [deduped] AS ("
        f"SELECT {projection}, "
        "ROW_NUMBER() OVER (PARTITION BY [exposure_id] "
        "ORDER BY [fact_id] ASC) AS [exposure_rank] "
        "FROM [scoped]"
        ") "
        f"SELECT TOP ({page_limit}) {projection} FROM [deduped] "
        f"WHERE [exposure_rank] = 1{keyset} "
        f"ORDER BY {sort_sql} {direction}, [exposure_id] ASC"
    )
    return _CompiledQueries(
        count_sql=count_sql,
        facet_sql=facet_sql,
        page_sql=page_sql,
        parameters=tuple(parameters),
        page_parameters=tuple(page_parameters),
        page_limit=page_limit,
        sort_position_column=position_column,
    )


def _is_silver_patch_query(
    authorization: ExposureAuthorization,
    query: ExposureQuery,
) -> bool:
    if (
        authorization.scope_keys
        or not authorization.connection_subscriptions
    ):
        return False
    target_filters = [
        item
        for item in query.filters
        if str(item.field).casefold() == "target_kind"
    ]
    if len(target_filters) != 1:
        return False
    target = target_filters[0]
    if (
        str(target.operator).casefold() != "eq"
        or str(target.value).casefold() != "server"
    ):
        return False
    source_filters = [
        item
        for item in query.filters
        if str(item.field).casefold() == "source_family"
    ]
    if len(source_filters) != 1:
        return False
    source = source_filters[0]
    if str(source.operator).casefold() == "eq":
        values = (str(source.value).casefold(),)
    elif str(source.operator).casefold() == "in" and not isinstance(
            source.value,
            (str, bytes),
    ):
        values = _canonical_values(source.value)
    else:
        return False
    return values == ("aum",)


def _silver_patch_subscriptions(
    authorization: ExposureAuthorization,
) -> tuple[str, ...]:
    subscriptions = tuple(
        sorted(set(authorization.connection_subscriptions.values()))
    )
    if len(subscriptions) > MAX_SILVER_PATCH_SUBSCRIPTIONS:
        raise ExposureQueryUnavailableError(
            "Silver patch subscription scope exceeds its safe bound"
        )
    return subscriptions


def _silver_patch_scope(
    authorization: ExposureAuthorization,
) -> tuple[list[str], list[Any]]:
    predicates = ["[tenant_id] = ?"]
    parameters: list[Any] = [authorization.tenant_id]
    _append_in_predicate(
        predicates,
        parameters,
        "[subscription_id]",
        _silver_patch_subscriptions(authorization),
    )
    return predicates, parameters


def _silver_patch_status_scope(
    authorization: ExposureAuthorization,
) -> tuple[list[str], list[Any]]:
    predicates = ["[tenant_id] = ?"]
    parameters: list[Any] = [authorization.tenant_id]
    _append_in_predicate(
        predicates,
        parameters,
        "[subscription_id]",
        _silver_patch_subscriptions(authorization),
    )
    return predicates, parameters


def _silver_patch_snapshot(
    reader: Any,
    authorization: ExposureAuthorization,
    *,
    schema: str,
    now: datetime,
) -> _SilverPatchSnapshot:
    snapshot_table = (
        f"{_identifier(schema)}.{_identifier(SILVER_PATCH_SNAPSHOT_TABLE)}"
    )
    predicates, parameters = _silver_patch_status_scope(authorization)
    subscriptions = _silver_patch_subscriptions(authorization)
    limit = len(subscriptions) + 1
    snapshot_rows = reader.query(
        "WITH [ranked_snapshot] AS ("
        "SELECT [subscription_id], [ingestion_run_id], [source_generation], "
        "[status], [completeness], [freshness], [freshness_at], "
        "[freshness_threshold_seconds], [represented_count], [expected_count], "
        "ROW_NUMBER() OVER (PARTITION BY [subscription_id] "
        "ORDER BY [timestamp] DESC, [ingestion_run_id] DESC, [resource_id] ASC) "
        "AS [snapshot_rank] "
        f"FROM {snapshot_table} WHERE {' AND '.join(predicates)}"
        ") "
        f"SELECT TOP ({limit}) [subscription_id], [ingestion_run_id], "
        "[source_generation], [status], [completeness], [freshness], "
        "[freshness_at], [freshness_threshold_seconds], [represented_count], "
        "[expected_count] FROM [ranked_snapshot] WHERE [snapshot_rank] = 1 "
        "ORDER BY [subscription_id] ASC",
        tuple(parameters),
        max_rows=limit,
    )
    actual_subscriptions = {
        str(row.get("subscription_id") or "").casefold()
        for row in snapshot_rows
    }
    if (
        len(snapshot_rows) > len(subscriptions)
        or actual_subscriptions != set(subscriptions)
    ):
        raise ExposureQueryUnavailableError(
            "Silver patch snapshot is incomplete for the authorized scope"
        )
    publication_ids = sorted(
        {
            _required_text(
                row.get("ingestion_run_id"),
                "Silver patch publication generation",
            )
            for row in snapshot_rows
        }
    )
    if len(publication_ids) != 1:
        raise ExposureQueryUnavailableError(
            "Silver patch subscriptions do not share one publication generation"
        )
    publication_id = publication_ids[0]
    completeness_values = {
        str(row.get("completeness") or "unavailable").casefold()
        for row in snapshot_rows
    }
    if "unavailable" in completeness_values:
        completeness = "unavailable"
    elif "stale" in completeness_values:
        completeness = "stale"
    elif "partial" in completeness_values:
        completeness = "partial"
    elif completeness_values == {"healthy-empty"}:
        completeness = "healthy-empty"
    else:
        completeness = "complete"
    represented_connections = sum(
        max(0, int(row.get("represented_count") or 0))
        for row in snapshot_rows
    )
    freshness_at = min(
        (str(row.get("freshness_at") or "") for row in snapshot_rows),
        default="",
    )
    freshness_states = {
        classify_freshness(
            str(row.get("freshness_at") or ""),
            now=now,
            threshold_seconds=max(
                1,
                int(row.get("freshness_threshold_seconds") or 0),
            ),
        )
        for row in snapshot_rows
    }
    freshness_state = (
        "stale"
        if "stale" in freshness_states
        else "unknown"
        if "unknown" in freshness_states
        else "fresh"
    )
    ingestion_run_id = (
        None if completeness == "healthy-empty" else publication_id
    )
    return _SilverPatchSnapshot(
        generation=f"{SILVER_PATCH_GENERATION_PREFIX}{publication_id}",
        ingestion_run_id=ingestion_run_id,
        completeness=completeness,
        freshness_state=freshness_state,
        freshness_at=freshness_at,
        represented_connections=represented_connections,
        expected_connections=sum(
            max(0, int(row.get("expected_count") or 0))
            for row in snapshot_rows
        ),
    )


def _compile_silver_patch_queries(
    authorization: ExposureAuthorization,
    *,
    snapshot: _SilverPatchSnapshot,
    query: ExposureQuery,
    after: tuple[Any, str] | None,
    schema: str,
) -> _CompiledQueries:
    _validate_query(query)
    table = f"{_identifier(schema)}.{_identifier(SILVER_PATCH_FINDINGS_TABLE)}"
    predicates, parameters = _silver_patch_scope(authorization)
    if snapshot.ingestion_run_id is None:
        predicates.append("1 = 0")
    else:
        predicates.append("[ingestion_run_id] = ?")
        parameters.append(snapshot.ingestion_run_id)
    severity_score = (
        "CASE LOWER([severity]) WHEN 'critical' THEN 100.0 "
        "WHEN 'important' THEN 80.0 WHEN 'high' THEN 80.0 "
        "WHEN 'security' THEN 70.0 WHEN 'moderate' THEN 50.0 "
        "WHEN 'medium' THEN 50.0 WHEN 'low' THEN 20.0 ELSE 40.0 END"
    )
    severity_rank = (
        "CASE LOWER([severity]) WHEN 'critical' THEN 4 "
        "WHEN 'important' THEN 3 WHEN 'high' THEN 3 "
        "WHEN 'security' THEN 3 WHEN 'moderate' THEN 2 "
        "WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END"
    )
    weakness_id = _silver_patch_weakness_sql()
    completeness = snapshot.completeness
    source_status = (
        "succeeded"
        if completeness in {"complete", "healthy-empty"}
        else "partial"
    )
    source_projection = (
        "CONCAT('silver-patch:', LOWER([resource_id])) AS [exposure_id], "
        "[target_resource_id] AS [target_id], 'server' AS [target_kind], "
        f"{weakness_id} AS [weakness_id], 'kb' AS [weakness_kind], "
        "'aum' AS [source_family], LOWER([status]) AS [source_state], "
        "LOWER([status]) AS [current_state], "
        "CAST(CASE WHEN LOWER([status]) IN ('missing', 'installation_failed') THEN 1 ELSE 0 END AS bit) AS [active], "
        "LOWER([severity]) AS [severity], "
        f"CASE WHEN LOWER([status]) IN ('missing', 'installation_failed') THEN {severity_score} ELSE 0.0 END AS [priority_score], "
        "'unknown' AS [sla_state], CAST(NULL AS bigint) AS [sla_age_seconds], "
        "CAST(NULL AS bigint) AS [sla_target_seconds], CAST(NULL AS nvarchar(64)) AS [sla_due_at], "
        "CAST(NULL AS bit) AS [sla_overdue], "
        "NULLIF([update_name], '') AS [finding_title], "
        f"CASE WHEN LOWER([status]) = 'missing' THEN CONCAT('Install ', {weakness_id}) "
        f"WHEN LOWER([status]) = 'installation_failed' THEN CONCAT('Retry ', {weakness_id}, ' installation') "
        f"ELSE CONCAT({weakness_id}, ' is installed') END AS [recommendation], "
        "'' AS [registry_id], '' AS [logical_image_id], '' AS [image_digest_id], "
        "'' AS [image_digest], 'not_applicable' AS [deployment_state], "
        "CAST(1 AS bigint) AS [represented_workload_count], "
        "CAST(1 AS bigint) AS [total_workload_count], "
        "CAST(0 AS bigint) AS [unknown_workload_count], "
        f"'{source_status}' AS [source_status], '{completeness}' AS [completeness], "
        "CAST(1 AS bigint) AS [evidence_count], "
        f"CONCAT('/exposure/kbs/', {weakness_id}) AS [detail_path], "
        "[timestamp] AS [timestamp], "
        f"CASE WHEN LOWER([status]) IN ('missing', 'installation_failed') THEN {severity_score} ELSE 0.0 END AS [ordering_priority_score], "
        f"{severity_rank} AS [ordering_severity_rank], "
        "[target_resource_id] AS [ordering_target_id], [resource_id] AS [fact_id]"
    )
    base_cte = (
        "WITH [silver_patch] AS ("
        f"SELECT {source_projection} FROM {table} WHERE {' AND '.join(predicates)}"
        ")"
    )
    filter_predicates: list[str] = []
    filter_parameters: list[Any] = []
    _append_filter_predicates(filter_predicates, filter_parameters, query.filters)
    where_sql = " AND ".join(filter_predicates) if filter_predicates else "1 = 1"
    projection = ", ".join(_identifier(column) for column in _PAGE_COLUMNS)
    scoped_cte = (
        f"{base_cte}, [scoped] AS ("
        f"SELECT {projection} FROM [silver_patch] WHERE {where_sql}"
        ")"
    )
    all_parameters = (*parameters, *filter_parameters)
    count_sql = (
        f"{scoped_cte} SELECT COUNT_BIG(DISTINCT [exposure_id]) AS [total_count], "
        "COUNT_BIG(DISTINCT NULLIF(LOWER([target_id]), '')) AS [distinct_targets], "
        "COUNT_BIG(DISTINCT NULLIF(LOWER([weakness_id]), '')) AS [distinct_weaknesses], "
        "COUNT_BIG(DISTINCT NULLIF(LOWER([image_digest]), '')) AS [distinct_recorded_digests], "
        "MAX([timestamp]) AS [freshest_at], "
        "MIN(CASE WHEN [completeness] = 'complete' THEN 1 ELSE 0 END) AS [all_complete] "
        "FROM [scoped]"
    )
    facet_sql = _compile_facet_sql(scoped_cte, query.facets)
    sort_sql, position_column = _SORT_FIELDS[query.sort.field]
    direction = query.sort.direction.upper()
    keyset = ""
    page_parameters = list(all_parameters)
    if after is not None:
        if len(after) != 2 or not str(after[1] or ""):
            raise ValueError(
                "Exposure cursor position must contain sort value and exposure_id"
            )
        comparison = "<" if direction == "DESC" else ">"
        keyset = (
            f" AND ({sort_sql} {comparison} ? OR "
            f"({sort_sql} = ? AND [exposure_id] > ?))"
        )
        page_parameters.extend((after[0], after[0], str(after[1])))
    page_limit = query.page_size + 1
    page_sql = (
        f"{scoped_cte}, [deduped] AS ("
        f"SELECT {projection}, ROW_NUMBER() OVER (PARTITION BY [exposure_id] "
        "ORDER BY [fact_id] ASC) AS [exposure_rank] FROM [scoped]"
        ") "
        f"SELECT TOP ({page_limit}) {projection} FROM [deduped] "
        f"WHERE [exposure_rank] = 1{keyset} "
        f"ORDER BY {sort_sql} {direction}, [exposure_id] ASC"
    )
    return _CompiledQueries(
        count_sql=count_sql,
        facet_sql=facet_sql,
        page_sql=page_sql,
        parameters=tuple(all_parameters),
        page_parameters=tuple(page_parameters),
        page_limit=page_limit,
        sort_position_column=position_column,
    )


def _silver_patch_weakness_sql() -> str:
    return (
        "CASE WHEN UPPER([kb_id]) LIKE 'KB%' THEN UPPER([kb_id]) "
        "ELSE CONCAT('KB', UPPER([kb_id])) END"
    )


def _validate_query(query: ExposureQuery) -> None:
    if (
        isinstance(query.page_size, bool)
        or not isinstance(query.page_size, int)
        or not 1 <= query.page_size <= MAX_EXPOSURE_PAGE_SIZE
    ):
        raise ValueError(
            f"Exposure page_size must be between 1 and {MAX_EXPOSURE_PAGE_SIZE}"
        )
    field = str(query.sort.field or "").strip().casefold()
    direction = str(query.sort.direction or "").strip().casefold()
    if field not in _SORT_FIELDS:
        raise ValueError(f"Unsupported Exposure sort field: {query.sort.field}")
    if direction not in {"asc", "desc"}:
        raise ValueError(
            f"Unsupported Exposure sort direction: {query.sort.direction}"
        )
    if field != query.sort.field or direction != query.sort.direction:
        raise ValueError("Exposure sort must use canonical lowercase values")
    facets = tuple(str(value or "").strip().casefold() for value in query.facets)
    if len(facets) > MAX_EXPOSURE_FACETS or len(set(facets)) != len(facets):
        raise ValueError("Exposure facets must be unique and bounded")
    unsupported_facets = sorted(set(facets) - set(_FACET_FIELDS))
    if unsupported_facets:
        raise ValueError(
            f"Unsupported Exposure facet field: {unsupported_facets[0]}"
        )
    for item in query.filters:
        field = str(item.field or "").strip().casefold()
        operator = str(item.operator or "").strip().casefold()
        if field not in _FILTER_FIELDS and field != "search":
            raise ValueError(
                f"Unsupported Exposure filter field: {item.field}"
            )
        allowed = {"contains"} if field == "search" else {
            *_COMPARISON_OPERATORS,
            "in",
        }
        if operator not in allowed:
            raise ValueError(
                f"Unsupported Exposure filter operator: {item.operator}"
            )


def _append_filter_predicates(
    predicates: list[str],
    parameters: list[Any],
    filters: Iterable[ExposureFilter],
) -> None:
    for item in filters:
        field = str(item.field).casefold()
        operator = str(item.operator).casefold()
        if field == "search":
            value = _required_text(item.value, "search filter")
            predicates.append(
                "(LOWER([target_id]) LIKE ? ESCAPE '\\' "
                "OR LOWER([weakness_id]) LIKE ? ESCAPE '\\' "
                "OR LOWER([recommendation]) LIKE ? ESCAPE '\\' "
                "OR LOWER([finding_title]) LIKE ? ESCAPE '\\')"
            )
            escaped = (
                value.casefold()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            parameters.extend((f"%{escaped}%",) * 4)
            continue
        column = _FILTER_FIELDS[field]
        fold = field in _CASE_INSENSITIVE_FILTER_FIELDS
        if operator == "in":
            if isinstance(item.value, (str, bytes)) or not isinstance(
                item.value,
                Iterable,
            ):
                raise ValueError("Exposure 'in' filter requires a value list")
            values = _canonical_values(item.value)
            if (
                not values
                or len(values) > MAX_EXPOSURE_FILTER_VALUES
            ):
                raise ValueError(
                    "Exposure filter values must contain between 1 and "
                    f"{MAX_EXPOSURE_FILTER_VALUES} items"
                )
            _append_in_predicate(
                predicates,
                parameters,
                column,
                values,
                fold=fold,
            )
            continue
        if fold and isinstance(item.value, str):
            predicates.append(
                f"LOWER({column}) {_COMPARISON_OPERATORS[operator]} LOWER(?)"
            )
        else:
            predicates.append(
                f"{column} {_COMPARISON_OPERATORS[operator]} ?"
            )
        parameters.append(item.value)


def _append_in_predicate(
    predicates: list[str],
    parameters: list[Any],
    column: str,
    values: Sequence[str],
    *,
    fold: bool = False,
) -> None:
    placeholders = ", ".join(
        "LOWER(?)" if fold else "?" for _ in values
    )
    predicates.append(
        f"{f'LOWER({column})' if fold else column} IN ({placeholders})"
    )
    parameters.extend(values)


def _compile_facet_sql(
    scoped_cte: str,
    facets: Sequence[str],
) -> str | None:
    if not facets:
        return None
    selects = [
        (
            f"SELECT '{field}' AS [dimension_name], "
            f"{_FACET_FIELDS[field]} AS [dimension_value], "
            "COUNT_BIG(DISTINCT [exposure_id]) AS [exposure_count] "
            f"FROM [scoped] GROUP BY {_FACET_FIELDS[field]}"
        )
        for field in facets
    ]
    return f"{scoped_cte} " + " UNION ALL ".join(selects)


def _facet_payload(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("dimension_name") or "")
        if not name:
            continue
        result.setdefault(name, []).append(
            {
                "value": row.get("dimension_value"),
                "count": max(0, int(row.get("exposure_count") or 0)),
            }
        )
    for values in result.values():
        values.sort(key=lambda item: str(item["value"]).casefold())
    return dict(sorted(result.items()))


def _completeness_payload(
    total_count: int,
    all_complete: Any,
) -> dict[str, str]:
    if total_count == 0:
        # A query that legitimately matches zero rows (e.g. a severity
        # filter with no matching findings) is a healthy, complete result,
        # not a provider outage. `all_complete` is itself undefined here
        # (MIN() over an empty scoped set is NULL) so it cannot be used to
        # distinguish the cases; "healthy-empty" is the correct default.
        state = "healthy-empty"
    elif int(all_complete or 0) == 1:
        state = "complete"
    else:
        state = "partial"
    return {"state": state}


def _freshness_payload(value: Any) -> dict[str, str]:
    as_of = str(value or "")
    return {
        "state": "reported" if as_of else "unknown",
        "as_of": as_of,
    }


def _canonical_filter_payload(
    filters: Iterable[ExposureFilter],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "field": str(item.field).casefold(),
            "operator": str(item.operator).casefold(),
            "value": (
                list(_canonical_values(item.value))
                if item.operator == "in"
                else item.value
            ),
        }
        for item in filters
    )


def _cursor_binding(
    authorization: ExposureAuthorization,
    *,
    generation_id: str,
    query: ExposureQuery,
) -> dict[str, Any]:
    _validate_query(query)
    return {
        "sub": authorization.subject,
        "tid": authorization.tenant_id,
        "connections": list(authorization.connection_ids),
        "scope": authorization.canonical_scope(),
        "generation": _required_text(
            generation_id,
            "read_model_generation_id",
        ),
        "filters": list(_canonical_filter_payload(query.filters)),
        "sort": {
            "field": query.sort.field,
            "direction": query.sort.direction,
        },
        "page_size": query.page_size,
    }


def _validate_position(value: Any) -> tuple[Any, str]:
    if (
        not isinstance(value, (tuple, list))
        or len(value) != 2
        or isinstance(value[0], (dict, list, tuple, bool))
        or value[0] is None
        or not str(value[1] or "")
    ):
        raise _invalid_cursor("Exposure cursor position is invalid")
    return value[0], str(value[1])


def _cursor_payload_position(
    value: Any,
    *,
    sort_field: str,
) -> tuple[Any, str]:
    sort_value, exposure_id = _validate_position(value)
    if sort_field in _NUMERIC_SORT_FIELDS:
        if isinstance(sort_value, Decimal):
            if not sort_value.is_finite():
                raise _invalid_cursor("Exposure cursor position is invalid")
            sort_value = _canonical_decimal(sort_value)
        elif isinstance(sort_value, float) and not isfinite(sort_value) or not isinstance(sort_value, (int, float)):
            raise _invalid_cursor("Exposure cursor position is invalid")
    elif not isinstance(sort_value, str):
        raise _invalid_cursor("Exposure cursor position is invalid")
    return sort_value, exposure_id


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _cursor_query_position(
    value: Any,
    *,
    sort_field: str,
) -> tuple[Any, str]:
    sort_value, exposure_id = _validate_position(value)
    if sort_field in _NUMERIC_SORT_FIELDS:
        if isinstance(sort_value, str):
            try:
                sort_value = Decimal(sort_value)
            except InvalidOperation as exc:
                raise _invalid_cursor(
                    "Exposure cursor position is invalid"
                ) from exc
            if not sort_value.is_finite():
                raise _invalid_cursor("Exposure cursor position is invalid")
        elif isinstance(sort_value, float) and not isfinite(sort_value) or not isinstance(sort_value, (int, float, Decimal)):
            raise _invalid_cursor("Exposure cursor position is invalid")
    elif not isinstance(sort_value, str):
        raise _invalid_cursor("Exposure cursor position is invalid")
    return sort_value, exposure_id


def _split_cursor(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > MAX_CURSOR_BYTES * 2:
        raise _invalid_cursor("Exposure cursor is invalid")
    parts = value.split(".")
    if len(parts) != 2 or not all(parts):
        raise _invalid_cursor("Exposure cursor is invalid")
    return parts[0], parts[1]


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_base64url(value: str) -> bytes:
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise _invalid_cursor("Exposure cursor encoding is invalid") from exc


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid_cursor("Exposure cursor payload is invalid") from exc


def _invalid_cursor(message: str) -> ExposureCursorError:
    return ExposureCursorError("exposure_cursor_invalid", message)


def _required_cursor_text(value: Any, field_name: str) -> str:
    try:
        return _required_text(value, field_name)
    except ValueError as exc:
        raise _invalid_cursor(
            f"Exposure cursor {field_name} is invalid"
        ) from exc


def _validate_kid(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _CURSOR_KID.fullmatch(normalized):
        raise ValueError(f"Exposure {field_name} is invalid")
    return normalized


def _validate_key(value: Any, field_name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError(
            f"Exposure {field_name} must contain at least 32 bytes"
        )
    return bytes(value)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"Exposure {field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if not key.startswith("ordering_")
        and key not in {"fact_id", "exposure_rank"}
    }


def _identifier(value: str) -> str:
    normalized = str(value or "")
    if not normalized or any(
        not (character.isascii() and (character.isalnum() or character == "_"))
        for character in normalized
    ):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f"[{normalized}]"


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Exposure {field_name} is required")
    return normalized


def _canonical_values(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value or "").strip().casefold()
                for value in values
                if str(value or "").strip()
            }
        )
    )


__all__ = [
    "CURSOR_KEY_OVERLAP_SECONDS",
    "CURSOR_TTL_SECONDS",
    "MAX_EXPOSURE_PAGE_SIZE",
    "MAX_EXPOSURE_QUERY_TIMEOUT_SECONDS",
    "ExposureAuthorization",
    "ExposureCursorCodec",
    "ExposureCursorError",
    "ExposureCursorKeyRing",
    "ExposureCursorState",
    "ExposureFilter",
    "ExposureGenerationWindow",
    "ExposureQuery",
    "ExposureQueryPage",
    "ExposureQueryService",
    "ExposureQueryUnavailableError",
    "ExposureRestartConflict",
    "ExposureSort",
]
