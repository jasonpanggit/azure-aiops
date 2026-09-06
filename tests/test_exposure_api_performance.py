"""Bounded-work contracts for the production Exposure query path."""

from __future__ import annotations

from typing import Any

import pytest

from api.exposure_query import (
    MAX_EXPOSURE_PAGE_SIZE,
    ExposureAuthorization,
    ExposureQuery,
    ExposureQueryService,
)


class PageReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], int | None]] = []

    def query(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((sql, tuple(parameters), max_rows))
        if "COUNT_BIG" in sql:
            return [{"total_count": 100_000}]
        if "dimension_name" in sql:
            return []
        page_limit = int(max_rows or 0)
        return [
            {"exposure_id": f"exposure-{index:06d}", "priority_score": 1000 - index}
            for index in range(page_limit)
        ]


def _authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        subject="scale-reader@example.com",
        tenant_id="tenant-scale",
        connection_ids=("connection-scale",),
        scope={"subscription": ("subscription-scale",)},
    )


def test_page_work_is_bounded_independently_of_total_count() -> None:
    reader = PageReader()
    result = ExposureQueryService(reader).list_page(
        _authorization(),
        generation_id="generation-100k",
        query=ExposureQuery(page_size=MAX_EXPOSURE_PAGE_SIZE),
    )

    assert result.total_count == 100_000
    assert len(result.items) == MAX_EXPOSURE_PAGE_SIZE
    assert result.next_position == (
        result.items[-1]["priority_score"],
        result.items[-1]["exposure_id"],
    )
    page_sql, _parameters, max_rows = reader.calls[-1]
    assert f"TOP ({MAX_EXPOSURE_PAGE_SIZE + 1})" in page_sql
    assert max_rows == MAX_EXPOSURE_PAGE_SIZE + 1
    assert " OFFSET " not in page_sql.upper()
    assert "SELECT *" not in page_sql.upper()


@pytest.mark.parametrize("page_size", [0, MAX_EXPOSURE_PAGE_SIZE + 1, 10_000])
def test_page_size_is_rejected_before_query(page_size: int) -> None:
    reader = PageReader()

    with pytest.raises(ValueError, match="page_size"):
        ExposureQueryService(reader).list_page(
            _authorization(),
            generation_id="generation-100k",
            query=ExposureQuery(page_size=page_size),
        )

    assert reader.calls == []
