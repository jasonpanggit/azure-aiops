"""Focused safety tests for named cross-replica run locks."""

from __future__ import annotations

import pytest

from storage.locking import RunLock


def test_run_lock_accepts_safe_explicit_document_name(tmp_path) -> None:
    lock = RunLock(tmp_path, lock_document="state/remediation_execution.lock")

    with lock:
        assert lock.path == tmp_path / "state" / "remediation_execution.lock"
        assert lock.path.exists()


def test_run_lock_preserves_ingestion_default(tmp_path) -> None:
    lock = RunLock(tmp_path)

    assert lock.path == tmp_path / "state" / "run.lock"


@pytest.mark.parametrize(
    "name",
    ["../escape.lock", "/tmp/absolute.lock", "", "state/../../escape.lock"],
)
def test_run_lock_rejects_unsafe_document_names(tmp_path, name: str) -> None:
    with pytest.raises(ValueError, match="lock document"):
        RunLock(tmp_path, lock_document=name)


def test_remediation_lock_is_isolated_from_ingestion_lock(tmp_path) -> None:
    with RunLock(tmp_path):
        with RunLock(tmp_path, lock_document="state/remediation_execution.lock"):
            pass
