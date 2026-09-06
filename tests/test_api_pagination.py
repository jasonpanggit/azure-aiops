"""Safe public error contracts for Exposure cursor pagination."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.exposure_query import (
    ExposureCursorError,
    ExposureCursorKeyRing,
    ExposureRestartConflict,
)


def test_cursor_errors_expose_only_stable_safe_codes() -> None:
    error = ExposureCursorError(
        "exposure_cursor_invalid",
        "Exposure cursor signature is invalid",
    )

    assert error.code == "exposure_cursor_invalid"
    assert error.safe_message == "Exposure cursor signature is invalid"
    assert "secret" not in error.to_dict().values()


@pytest.mark.parametrize(
    "code",
    ["exposure_generation_evicted", "exposure_generation_expired"],
)
def test_generation_conflict_requires_explicit_restart(code: str) -> None:
    conflict = ExposureRestartConflict(code, generation="generation-old")

    assert conflict.restart_required is True
    assert conflict.status_code == 409
    assert conflict.to_dict() == {
        "code": code,
        "restart_required": True,
        "generation": "generation-old",
    }


def test_keyring_rejects_short_duplicate_or_partial_managed_keys() -> None:
    loaded_at = datetime(2026, 9, 6, tzinfo=UTC)
    with pytest.raises(ValueError, match="at least 32 bytes"):
        ExposureCursorKeyRing(
            active_kid="active",
            active_key=b"short",
            loaded_at=loaded_at,
        )
    with pytest.raises(ValueError, match="provided together"):
        ExposureCursorKeyRing(
            active_kid="active",
            active_key=b"a" * 48,
            previous_kid="previous",
            loaded_at=loaded_at,
        )
    with pytest.raises(ValueError, match="different key material"):
        ExposureCursorKeyRing(
            active_kid="same",
            active_key=b"a" * 48,
            previous_kid="same",
            previous_key=b"b" * 48,
            loaded_at=loaded_at,
        )


def test_keyring_repr_never_discloses_managed_key_values() -> None:
    keyring = ExposureCursorKeyRing(
        active_kid="active",
        active_key=b"active-secret-value-that-is-long-enough",
        previous_kid="previous",
        previous_key=b"previous-secret-value-that-is-long-enough",
        loaded_at=datetime(2026, 9, 6, tzinfo=UTC),
    )

    rendered = repr(keyring)
    assert "active-secret" not in rendered
    assert "previous-secret" not in rendered
