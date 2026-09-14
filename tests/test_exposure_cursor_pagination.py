"""Managed, scope-bound snapshot cursor contracts for Exposure."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from api.exposure_query import (
    CURSOR_TTL_SECONDS,
    ExposureAuthorization,
    ExposureCursorCodec,
    ExposureCursorError,
    ExposureCursorKeyRing,
    ExposureFilter,
    ExposureGenerationWindow,
    ExposureQuery,
    ExposureQueryService,
    ExposureRestartConflict,
    ExposureSort,
)
from tests.exposure_scenario import (
    EXPECTED_TIED_PRIORITY_ROWS,
    load_exposure_scenario,
    tied_priority_rows,
)

NOW = datetime(2026, 9, 6, 8, 30, tzinfo=UTC)


def _authorization(
    *,
    subject: str = "operator@example.com",
    tenant_id: str = "tenant-authorized",
    connections: tuple[str, ...] = ("connection-a", "connection-b"),
) -> ExposureAuthorization:
    return ExposureAuthorization(
        subject=subject,
        tenant_id=tenant_id,
        connection_ids=connections,
        scope={
            "subscription": ("subscription-a", "subscription-b"),
            "subscription_connection": connections,
        },
    )


def _query(*, page_size: int = 25) -> ExposureQuery:
    return ExposureQuery(
        filters=(
            ExposureFilter("active", "eq", True),
            ExposureFilter("severity", "in", ("critical", "high")),
        ),
        facets=("severity", "target_kind"),
        sort=ExposureSort("priority_score", "desc"),
        page_size=page_size,
    )


def _ring(
    *,
    active_kid: str = "cursor-active",
    active_key: bytes = b"a" * 48,
    previous_kid: str | None = None,
    previous_key: bytes | None = None,
    loaded_at: datetime = NOW,
) -> ExposureCursorKeyRing:
    return ExposureCursorKeyRing(
        active_kid=active_kid,
        active_key=active_key,
        previous_kid=previous_kid,
        previous_key=previous_key,
        loaded_at=loaded_at,
    )


def test_cursor_fixture_expands_to_101_unique_deterministically_ordered_ties() -> None:
    scenario = load_exposure_scenario()

    first = tied_priority_rows(scenario)
    second = tied_priority_rows(scenario)
    identities = [row["exposure_id"] for row in first]

    assert first == second
    assert len(first) == EXPECTED_TIED_PRIORITY_ROWS
    assert len(set(identities)) == EXPECTED_TIED_PRIORITY_ROWS
    assert identities == sorted(identities)
    assert {row["priority_score"] for row in first} == {900}


def test_cursor_binds_every_authorization_query_and_snapshot_field() -> None:
    codec = ExposureCursorCodec(_ring())
    authorization = _authorization()
    query = _query()
    cursor = codec.issue(
        authorization,
        generation_id="generation-17",
        query=query,
        position=(900.0, "exposure-025"),
        now=NOW,
    )

    state = codec.decode(
        cursor,
        authorization=authorization,
        query=query,
        expected_generation_id="generation-17",
        now=NOW + timedelta(seconds=1),
    )

    assert state.position == (900.0, "exposure-025")
    assert state.generation == "generation-17"
    assert state.kid == "cursor-active"
    assert state.issued_at == int(NOW.timestamp())
    assert state.expires_at - state.issued_at == CURSOR_TTL_SECONDS

    changes = [
        (_authorization(subject="other@example.com"), query, "generation-17"),
        (_authorization(tenant_id="other-tenant"), query, "generation-17"),
        (
            _authorization(connections=("connection-a",)),
            query,
            "generation-17",
        ),
        (
            authorization,
            ExposureQuery(
                filters=(ExposureFilter("active", "eq", False),),
                sort=query.sort,
                page_size=query.page_size,
            ),
            "generation-17",
        ),
        (
            authorization,
            ExposureQuery(
                filters=query.filters,
                sort=ExposureSort("target_id", "asc"),
                page_size=query.page_size,
            ),
            "generation-17",
        ),
        (
            authorization,
            ExposureQuery(
                filters=query.filters,
                sort=query.sort,
                page_size=50,
            ),
            "generation-17",
        ),
        (authorization, query, "generation-18"),
    ]
    for changed_authorization, changed_query, changed_generation in changes:
        with pytest.raises(ExposureCursorError, match="request binding"):
            codec.decode(
                cursor,
                authorization=changed_authorization,
                query=changed_query,
                expected_generation_id=changed_generation,
                now=NOW + timedelta(seconds=1),
            )


def test_decimal_cursor_position_is_canonical_and_restored_exactly() -> None:
    codec = ExposureCursorCodec(_ring())
    authorization = _authorization()
    query = _query(page_size=1)

    cursor = codec.issue(
        authorization,
        generation_id="generation-17",
        query=query,
        position=(Decimal("91.2500"), "exposure-025"),
        now=NOW,
    )
    state = codec.decode(
        cursor,
        authorization=authorization,
        query=query,
        expected_generation_id="generation-17",
        now=NOW + timedelta(seconds=1),
    )

    assert state.position == (Decimal("91.25"), "exposure-025")
    payload, _signature = cursor.split(".")
    decoded = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    assert decoded["position"] == ["91.25", "exposure-025"]


def test_cursor_tampering_and_unknown_or_expired_key_fail_closed() -> None:
    authorization = _authorization()
    query = _query()
    codec = ExposureCursorCodec(_ring())
    cursor = codec.issue(
        authorization,
        generation_id="generation-17",
        query=query,
        position=(900.0, "exposure-025"),
        now=NOW,
    )

    payload, signature = cursor.split(".")
    decoded = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    decoded["position"][1] = "exposure-999"
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    with pytest.raises(ExposureCursorError, match="signature"):
        codec.decode(
            f"{tampered_payload}.{signature}",
            authorization=authorization,
            query=query,
            now=NOW + timedelta(seconds=1),
        )

    unknown_codec = ExposureCursorCodec(_ring(active_kid="cursor-other"))
    with pytest.raises(ExposureCursorError, match="key"):
        unknown_codec.decode(
            cursor,
            authorization=authorization,
            query=query,
            now=NOW + timedelta(seconds=1),
        )

    with pytest.raises(ExposureCursorError, match="expired"):
        codec.decode(
            cursor,
            authorization=authorization,
            query=query,
            now=NOW + timedelta(seconds=CURSOR_TTL_SECONDS + 1),
        )


def test_previous_key_validates_only_during_configured_overlap() -> None:
    authorization = _authorization()
    query = _query()
    old_codec = ExposureCursorCodec(
        _ring(active_kid="cursor-old", active_key=b"o" * 48)
    )
    old_cursor = old_codec.issue(
        authorization,
        generation_id="generation-17",
        query=query,
        position=(900.0, "exposure-025"),
        now=NOW + timedelta(seconds=1_700),
    )
    rotated = ExposureCursorCodec(
        _ring(
            active_kid="cursor-new",
            active_key=b"n" * 48,
            previous_kid="cursor-old",
            previous_key=b"o" * 48,
            loaded_at=NOW,
        )
    )

    assert (
        rotated.decode(
            old_cursor,
            authorization=authorization,
            query=query,
            now=NOW + timedelta(seconds=1_799),
        ).kid
        == "cursor-old"
    )
    with pytest.raises(ExposureCursorError, match="overlap"):
        rotated.decode(
            old_cursor,
            authorization=authorization,
            query=query,
            now=NOW + timedelta(seconds=1_801),
        )


def test_evicted_and_expired_generations_require_typed_restart() -> None:
    codec = ExposureCursorCodec(_ring())
    authorization = _authorization()
    query = _query()
    cursor = codec.issue(
        authorization,
        generation_id="generation-old",
        query=query,
        position=(900.0, "exposure-025"),
        now=NOW,
    )
    reader = CursorWalkReader([])

    evicted = ExposureQueryService(
        reader,
        cursor_codec=codec,
        generation_window=lambda: ExposureGenerationWindow(
            active_generation="generation-new",
            retained_generations={},
        ),
    )
    with pytest.raises(ExposureRestartConflict) as evicted_error:
        evicted.list_page(
            authorization,
            query=query,
            cursor=cursor,
            now=NOW + timedelta(seconds=1),
        )
    assert evicted_error.value.code == "exposure_generation_evicted"
    assert evicted_error.value.restart_required is True

    expired = ExposureQueryService(
        reader,
        cursor_codec=codec,
        generation_window=lambda: ExposureGenerationWindow(
            active_generation="generation-new",
            retained_generations={
                "generation-old": NOW - timedelta(seconds=1)
            },
        ),
    )
    with pytest.raises(ExposureRestartConflict) as expired_error:
        expired.list_page(
            authorization,
            query=query,
            cursor=cursor,
            now=NOW + timedelta(seconds=1),
        )
    assert expired_error.value.code == "exposure_generation_expired"


class CursorWalkReader:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        if "COUNT_BIG" in sql and "GROUP BY" not in sql:
            return [{"total_count": len(self.rows)}]
        if "dimension_name" in sql:
            return []
        after_id = str(parameters[-1]) if "AND [exposure_id] > ?" in sql else ""
        eligible = [
            row for row in self.rows if str(row["exposure_id"]) > after_id
        ]
        return eligible[: int(max_rows or 0)]


def test_full_cursor_walk_matches_total_without_duplicates_or_omissions() -> None:
    rows = tied_priority_rows(load_exposure_scenario())
    codec = ExposureCursorCodec(_ring())
    service = ExposureQueryService(
        CursorWalkReader(rows),
        cursor_codec=codec,
        generation_window=lambda: ExposureGenerationWindow(
            active_generation="exposure-generation-0001",
            retained_generations={},
        ),
    )
    authorization = _authorization()
    query = ExposureQuery(page_size=25)
    cursor: str | None = None
    seen: list[str] = []

    while True:
        page = service.list_page(
            authorization,
            query=query,
            cursor=cursor,
            now=NOW,
        )
        assert page.total_count == EXPECTED_TIED_PRIORITY_ROWS
        seen.extend(str(row["exposure_id"]) for row in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    expected = [str(row["exposure_id"]) for row in rows]
    assert seen == expected
    assert len(seen) == len(set(seen)) == EXPECTED_TIED_PRIORITY_ROWS
