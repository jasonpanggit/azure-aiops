"""Regression tests for verification-poll backoff overflow safety.

``_next_backoff_seconds`` computes an exponential backoff capped at 60
seconds. Before this fix, a record with a very large
``verification_attempts`` count (e.g. a long-stuck poll loop) could
raise ``OverflowError: int too large to convert to float`` from
``5.0 * (2 ** (attempt - 1))`` -- the unbounded Python int power grows
past float range long before ``min(60.0, ...)`` gets a chance to cap
it. See production logs: this fired roughly every ~10s for a stuck
verification record.
"""

from __future__ import annotations

import pytest

from intelligence.remediation.execution_service import _next_backoff_seconds


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [
        (1, 5.0),
        (2, 10.0),
        (3, 20.0),
        (4, 40.0),
        (5, 60.0),
        (6, 60.0),
        (100, 60.0),
    ],
)
def test_next_backoff_seconds_matches_documented_schedule(attempt: int, expected: float) -> None:
    assert _next_backoff_seconds(attempt) == expected


def test_next_backoff_seconds_does_not_overflow_for_huge_attempt_counts() -> None:
    # A stuck/long-running verification record could accumulate an
    # arbitrarily large attempt count; this must never raise.
    assert _next_backoff_seconds(10_000) == 60.0
    assert _next_backoff_seconds(10**9) == 60.0


def test_next_backoff_seconds_clamps_non_positive_attempts_to_first_step() -> None:
    assert _next_backoff_seconds(0) == 5.0
    assert _next_backoff_seconds(-5) == 5.0
