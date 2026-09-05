from __future__ import annotations

import datetime as datetime_module

from intelligence.remediation.action_version import action_version_for


def _citations() -> list[dict]:
    return [
        {"source_type": "patch_assessment", "source_id": "KB600001", "observed_at": "2026-01-01T00:00:00Z"},
        {"source_type": "patch_assessment", "source_id": "KB600002", "observed_at": "2026-01-02T00:00:00Z"},
    ]


def test_determinism_across_two_direct_calls() -> None:
    first = action_version_for(
        action_id="controlled-patch-recovery",
        target_id="/subscriptions/sub-1/vm-1",
        scope=["KB600001", "KB600002"],
        evidence_citations=_citations(),
    )
    second = action_version_for(
        action_id="controlled-patch-recovery",
        target_id="/subscriptions/sub-1/vm-1",
        scope=["KB600001", "KB600002"],
        evidence_citations=_citations(),
    )

    assert first == second
    assert len(first) == 16


def test_changing_citation_source_id_changes_output() -> None:
    baseline = action_version_for(
        action_id="a", target_id="t", scope=[], evidence_citations=_citations()
    )
    citations = _citations()
    citations[0]["source_id"] = "KB999999"

    changed = action_version_for(
        action_id="a", target_id="t", scope=[], evidence_citations=citations
    )

    assert baseline != changed


def test_changing_citation_observed_at_changes_output() -> None:
    baseline = action_version_for(
        action_id="a", target_id="t", scope=[], evidence_citations=_citations()
    )
    citations = _citations()
    citations[0]["observed_at"] = "2099-01-01T00:00:00Z"

    changed = action_version_for(
        action_id="a", target_id="t", scope=[], evidence_citations=citations
    )

    assert baseline != changed


def test_changing_scope_changes_output_with_everything_else_held_constant() -> None:
    baseline = action_version_for(
        action_id="a", target_id="t", scope=["KB1"], evidence_citations=_citations()
    )
    changed = action_version_for(
        action_id="a", target_id="t", scope=["KB1", "KB2"], evidence_citations=_citations()
    )
    changed_defender = action_version_for(
        action_id="a",
        target_id="t",
        scope="Enable auto-provisioning",
        evidence_citations=_citations(),
    )

    assert baseline != changed
    assert baseline != changed_defender


def test_wall_clock_time_never_influences_output(monkeypatch) -> None:
    kwargs = {
        "action_id": "a",
        "target_id": "t",
        "scope": {"x": 1},
        "evidence_citations": _citations(),
    }

    first = action_version_for(**kwargs)

    class _FrozenDatetime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 1, tzinfo=tz)

    monkeypatch.setattr(datetime_module, "datetime", _FrozenDatetime)
    monkeypatch.setattr("time.time", lambda: 999999999.0)

    second = action_version_for(**kwargs)

    assert first == second


def test_empty_evidence_citations_produce_a_stable_distinct_sentinel_digest() -> None:
    empty_first = action_version_for(action_id="a", target_id="t", scope=[], evidence_citations=[])
    empty_second = action_version_for(action_id="a", target_id="t", scope=[], evidence_citations=[])
    populated = action_version_for(action_id="a", target_id="t", scope=[], evidence_citations=_citations())

    assert empty_first == empty_second
    assert empty_first != populated


def test_citation_order_does_not_affect_output() -> None:
    citations = _citations()
    reordered = list(reversed(citations))

    first = action_version_for(action_id="a", target_id="t", scope=[], evidence_citations=citations)
    second = action_version_for(action_id="a", target_id="t", scope=[], evidence_citations=reordered)

    assert first == second
