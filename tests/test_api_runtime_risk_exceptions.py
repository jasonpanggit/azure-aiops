"""Tests for the module-level risk-exception store in `api.runtime`.

Exceptions are user-submitted mutations that must survive
`_load_vulnerability_service()` rebuilding a brand-new service instance on
every request, so they live in a module-level store rather than on the
service itself. These tests exercise the store directly.
"""

from __future__ import annotations

import pytest

from api import runtime
from intelligence.vulnerability.models import RiskException


@pytest.fixture(autouse=True)
def _clean_store():
    runtime._risk_exception_store.clear()
    yield
    runtime._risk_exception_store.clear()


def test_add_list_and_revoke_risk_exception_round_trip():
    exception = RiskException(
        exception_id="exc-1", cve_id="CVE-2026-0001", reason="Approved by CISO"
    )
    runtime.add_risk_exception(exception)

    listed = runtime.list_risk_exceptions()
    assert listed == [exception]

    assert runtime.revoke_risk_exception("exc-1") is True
    assert runtime.list_risk_exceptions() == []


def test_revoke_unknown_exception_returns_false():
    assert runtime.revoke_risk_exception("does-not-exist") is False
