"""Wave 0 contracts for scope-bound cursor pagination."""

from __future__ import annotations

import pytest

from tests.exposure_scenario import (
    EXPECTED_TIED_PRIORITY_ROWS,
    load_exposure_scenario,
    tied_priority_rows,
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


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-13")
def test_scope_is_applied_before_count_and_page_queries() -> None:
    from api.exposure_query import ExposureQueryService

    assert ExposureQueryService is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-13")
def test_cursor_binds_principal_scope_query_page_size_and_generation() -> None:
    from api.exposure_query import ExposureCursorCodec

    assert ExposureCursorCodec is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-13")
def test_cursor_tampering_and_unknown_or_expired_key_fail_closed() -> None:
    from api.exposure_query import ExposureCursorCodec

    assert ExposureCursorCodec is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-13")
def test_evicted_generation_requires_restart_and_never_rebases() -> None:
    from api.exposure_query import ExposureQueryService

    assert ExposureQueryService is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-13")
def test_full_cursor_walk_matches_total_without_duplicates_or_omissions() -> None:
    from api.exposure_query import ExposureQueryService

    assert ExposureQueryService is not None
