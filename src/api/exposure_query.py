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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fabric.sql_endpoint import FabricSqlReader
from intelligence.vulnerability.exposure_contracts import (
    ExposureCursorError,
    ExposureRestartConflict,
)

EXPOSURE_FACTS_TABLE = "gold_exposure_facts"
MAX_EXPOSURE_PAGE_SIZE = 100
MAX_EXPOSURE_FILTER_VALUES = 50
MAX_EXPOSURE_FACETS = 8
MAX_FACET_ROWS = 1_000
MAX_EXPOSURE_QUERY_TIMEOUT_SECONDS = 30
CURSOR_TTL_SECONDS = 15 * 60
CURSOR_KEY_OVERLAP_SECONDS = 30 * 60
CURSOR_VERSION = 1
MAX_CURSOR_BYTES = 8_192

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
        normalized_position = _validate_position(position)
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
        position = _validate_position(payload.get("position"))
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


class ExposureQueryService:
    """Execute one immutable, scope-first Exposure count/facet/page request."""

    def __init__(
        self,
        reader: FabricSqlReader | Any | None,
        *,
        cursor_codec: ExposureCursorCodec | None = None,
        generation_window: Any | None = None,
        authorization_resolver: Any | None = None,
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
        if cursor:
            if self._cursor_codec is None:
                raise ExposureQueryUnavailableError(
                    "Exposure cursor verification is unavailable"
                )
            if window is None:
                raise ExposureQueryUnavailableError(
                    "Exposure generation retention state is unavailable"
                )
            cursor_state = self._cursor_codec.decode(
                cursor,
                authorization=authorization,
                query=query,
                expected_generation_id=generation_id,
                now=current,
            )
            generation = window.require_readable(
                cursor_state.generation,
                now=current,
            )
            after = cursor_state.position
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
        compiled = _compile_queries(
            authorization,
            generation_id=generation,
            query=query,
            after=after,
            schema=getattr(
                getattr(self._reader, "endpoint", None),
                "schema",
                "dbo",
            ),
        )
        count_rows = self._reader.query(
            compiled.count_sql,
            compiled.parameters,
            max_rows=1,
        )
        total_count = (
            max(0, int(count_rows[0].get("total_count") or 0))
            if count_rows
            else 0
        )
        count_row = count_rows[0] if count_rows else {}
        completeness = _completeness_payload(
            total_count,
            count_row.get("all_complete"),
        )
        freshness = _freshness_payload(count_row.get("freshest_at"))
        facet_rows = (
            self._reader.query(
                compiled.facet_sql,
                compiled.parameters,
                max_rows=MAX_FACET_ROWS,
            )
            if compiled.facet_sql
            else []
        )
        raw_page = self._reader.query(
            compiled.page_sql,
            compiled.page_parameters,
            max_rows=compiled.page_limit,
        )
        has_more = len(raw_page) > query.page_size
        selected = raw_page[: query.page_size]
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
                "OR LOWER([recommendation]) LIKE ? ESCAPE '\\')"
            )
            escaped = (
                value.casefold()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            parameters.extend((f"%{escaped}%",) * 3)
            continue
        column = _FILTER_FIELDS[field]
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
            )
            continue
        predicates.append(
            f"{column} {_COMPARISON_OPERATORS[operator]} ?"
        )
        parameters.append(item.value)


def _append_in_predicate(
    predicates: list[str],
    parameters: list[Any],
    column: str,
    values: Sequence[str],
) -> None:
    placeholders = ", ".join("?" for _ in values)
    predicates.append(f"{column} IN ({placeholders})")
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
        state = "unavailable"
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
        or isinstance(value[0], (dict, list, tuple))
        or not str(value[1] or "")
    ):
        raise _invalid_cursor("Exposure cursor position is invalid")
    return value[0], str(value[1])


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
