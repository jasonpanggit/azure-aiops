"""Regression coverage for the silver-patch exposure query projection.

Guards against a shared-column/projection drift: `_PAGE_COLUMNS` is reused to
select from both the Gold `gold_exposure_facts` table and the live
silver-patch CTE. If a column is added to `_PAGE_COLUMNS` (for example
`finding_title`, added alongside the Gold schema in PR #210) without also
adding a matching alias to the silver-patch `source_projection`, SQL Server
raises `Invalid column name` for every live silver-patch query
(target_kind=server, source_family=aum) even though the Gold-backed path
remains healthy.
"""

from __future__ import annotations

import re

from src.api.exposure_query import (
    _PAGE_COLUMNS,
    ExposureAuthorization,
    ExposureFilter,
    ExposureQuery,
    _compile_silver_patch_queries,
    _SilverPatchSnapshot,
)


def _authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        subject="test-subject",
        tenant_id="tenant-1",
        connection_ids=("connection-1",),
        connection_subscriptions={"connection-1": "sub-1"},
    )


def _snapshot() -> _SilverPatchSnapshot:
    return _SilverPatchSnapshot(
        generation="silver-patch:2024-01-01T00:00:00Z",
        ingestion_run_id="run-1",
        completeness="complete",
        freshness_state="fresh",
        freshness_at="2024-01-01T00:00:00Z",
        represented_connections=1,
        expected_connections=1,
    )


def _query() -> ExposureQuery:
    return ExposureQuery(
        filters=(
            ExposureFilter(field="target_kind", operator="eq", value="server"),
            ExposureFilter(field="source_family", operator="eq", value="aum"),
        ),
    )


def test_silver_patch_projection_aliases_every_shared_page_column() -> None:
    """Every `_PAGE_COLUMNS` entry must be selectable from the silver_patch CTE."""
    compiled = _compile_silver_patch_queries(
        _authorization(),
        snapshot=_snapshot(),
        query=_query(),
        after=None,
        schema="dbo",
    )
    base_cte_match = re.search(
        r"WITH \[silver_patch\] AS \(SELECT (.*?) FROM \[dbo\]\.\[silver_patch_snapshot_findings\]",
        compiled.page_sql,
        re.DOTALL,
    )
    assert base_cte_match, "expected a [silver_patch] CTE in the compiled page SQL"
    source_projection = base_cte_match.group(1)
    for column in _PAGE_COLUMNS:
        assert f"AS [{column}]" in source_projection, (
            f"silver_patch source_projection is missing an alias for "
            f"[{column}]; selecting it from [silver_patch] will raise "
            f"'Invalid column name' at query time"
        )


def test_silver_patch_projection_derives_finding_title_from_update_name() -> None:
    """finding_title should surface the AUM update_name, not a hardcoded value."""
    compiled = _compile_silver_patch_queries(
        _authorization(),
        snapshot=_snapshot(),
        query=_query(),
        after=None,
        schema="dbo",
    )
    assert "NULLIF([update_name], '') AS [finding_title]" in compiled.page_sql
    for column in ("target_id", "weakness_id", "image_digest"):
        assert f"COUNT_BIG(DISTINCT NULLIF(LOWER([{column}]), ''))" in compiled.count_sql
