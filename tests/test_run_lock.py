"""Unit tests for `hermes_arg_connector.locking.RunLock`.

The lock stops two replicas ingesting into the same data root at once. It
replaced a PostgreSQL advisory lock, so the OneLake path must preserve the two
guarantees the advisory lock gave for free:

- exactly one holder, with no race window, and
- automatic recovery if the holder dies without releasing (hence a finite,
  renewable lease rather than an infinite one).

The remote tests inject a fake Data Lake service client so they exercise the
real lease logic without Azure.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from hermes_arg_connector.locking import LEASE_DURATION_SECONDS, RunLock

ROOT = "abfss://ws-hermes@onelake.dfs.fabric.microsoft.com/lakehouse/Files/hermes"


class _FakeLease:
    """Stands in for the service-side lease: one holder at a time per file."""

    holders: ClassVar[dict[str, object]] = {}

    def __init__(self, file_client):
        self._client = file_client
        self.duration = None

    def acquire(self, lease_duration):
        if _FakeLease.holders.get(self._client.path) is not None:
            raise RuntimeError("LeaseAlreadyPresent")
        _FakeLease.holders[self._client.path] = self
        self.duration = lease_duration

    def renew(self):
        self._client.renewals += 1

    def release(self):
        _FakeLease.holders.pop(self._client.path, None)


class _FakeFileClient:
    def __init__(self, path, created):
        self.path = path
        self._created = created
        self.renewals = 0

    def exists(self):
        return self.path in self._created

    def create_file(self):
        self._created.add(self.path)


class _FakeFileSystem:
    def __init__(self, name, created):
        self.name = name
        self._created = created

    def get_file_client(self, path):
        return _FakeFileClient(f"{self.name}/{path}", self._created)


class _FakeService:
    def __init__(self):
        self.created: set[str] = set()
        self.file_systems: list[str] = []

    def get_file_system_client(self, name):
        self.file_systems.append(name)
        return _FakeFileSystem(name, self.created)


@pytest.fixture(autouse=True)
def _reset_leases(monkeypatch):
    _FakeLease.holders = {}
    monkeypatch.setattr(
        "azure.storage.filedatalake.DataLakeLeaseClient", _FakeLease, raising=False
    )


def test_local_root_lock_is_exclusive(tmp_path):
    # Nested deliberately: the inner acquisition must fail while the outer
    # lock is still held.
    with RunLock(tmp_path):  # noqa: SIM117
        with pytest.raises(RuntimeError, match="already running"):
            with RunLock(tmp_path):
                pass


def test_local_lock_is_reacquirable_after_release(tmp_path):
    with RunLock(tmp_path):
        pass
    with RunLock(tmp_path):
        pass


def test_remote_lock_acquires_a_finite_lease():
    service = _FakeService()
    with RunLock(ROOT, service_client=service) as lock:
        assert lock._lease.duration == LEASE_DURATION_SECONDS
    # The workspace is the container; the lakehouse path stays in the key.
    assert service.file_systems == ["ws-hermes"]
    assert service.created == {"ws-hermes/lakehouse/Files/hermes/state/run.lock"}


def test_remote_lock_is_exclusive():
    service = _FakeService()
    # Nested deliberately: the inner acquisition must fail while the outer
    # lock is still held.
    with RunLock(ROOT, service_client=service):  # noqa: SIM117
        with pytest.raises(RuntimeError, match="already running"):
            with RunLock(ROOT, service_client=service):
                pass


def test_remote_lock_is_reacquirable_after_release():
    service = _FakeService()
    with RunLock(ROOT, service_client=service):
        pass
    with RunLock(ROOT, service_client=service):
        pass
    # The lock file is kept (only the lease is dropped), so a peer must not
    # recreate it and clobber a lease.
    assert len(service.created) == 1


def test_renew_extends_the_lease():
    service = _FakeService()
    with RunLock(ROOT, service_client=service) as lock:
        lock.renew()
        assert lock._lease._client.renewals == 1


def test_renew_is_a_no_op_for_local_roots(tmp_path):
    with RunLock(tmp_path) as lock:
        lock.renew()


@pytest.mark.parametrize(
    "root",
    [
        "abfss://ws-hermes@onelake.dfs.fabric.microsoft.com",
        "abfss://@onelake.dfs.fabric.microsoft.com/lakehouse",
    ],
)
def test_unusable_onelake_roots_are_rejected(root):
    with pytest.raises(ValueError), RunLock(root, service_client=_FakeService()):
        pass
