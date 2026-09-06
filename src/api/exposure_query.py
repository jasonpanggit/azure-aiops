"""Scope-first, bounded queries over the Fabric SQL Exposure read model.

This module deliberately accepts an already-authorized identity and scope.  It
does not derive authorization from request parameters and it never falls back
to the Delta reader: every count, facet, and page operation is pushed into the
Fabric SQL endpoint with bound values and allowlisted identifiers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fabric.sql_endpoint import FabricSqlReader

EXPOSURE_FACTS_TABLE = "gold_exposure_facts"
MAX_EXPOSURE_PAGE_SIZE = 100
MAX_EXPOSURE_FILTER_VALUES = 50
MAX_EXPOSURE_FACETS = 8
MAX_FACET_ROWS = 1_000

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


class ExposureQueryUnavailableError(RuntimeError):
    """Raised when the production Fabric SQL reader is unavailable."""


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

    def __init__(self, reader: FabricSqlReader | Any | None) -> None:
        self._reader = reader

    def list_page(
        self,
        authorization: ExposureAuthorization,
        *,
        generation_id: str,
        query: ExposureQuery,
        after: tuple[Any, str] | None = None,
    ) -> ExposureQueryPage:
        if self._reader is None:
            raise ExposureQueryUnavailableError(
                "Fabric SQL Exposure reader is unavailable; Delta fallback is disabled"
            )
        generation = _required_text(
            generation_id,
            "read_model_generation_id",
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
        "SELECT COUNT_BIG(DISTINCT [exposure_id]) AS [total_count] "
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
                "(LOWER([target_id]) LIKE ? OR LOWER([weakness_id]) LIKE ? "
                "OR LOWER([recommendation]) LIKE ?)"
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
    "MAX_EXPOSURE_PAGE_SIZE",
    "ExposureAuthorization",
    "ExposureFilter",
    "ExposureQuery",
    "ExposureQueryPage",
    "ExposureQueryService",
    "ExposureQueryUnavailableError",
    "ExposureSort",
]
