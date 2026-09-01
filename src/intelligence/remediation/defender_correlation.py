"""Defender-correlated business-decision remediation cases.

Defender emits technical, resource-scoped signals (unhealthy recommendations,
active alerts, attack-path membership, secure-score control gaps). None of
those signals alone answer whether an operator should act now, later, or not
at all -- that requires joining the signal to the business it protects (which
application, which service, who owns it, what depends on it) and to whether a
governed catalog action even exists for it.

This module performs exactly that join, read-only. It never calls Azure and
never shells out to another process (enforced by a repository-wide grep
check over ``src/intelligence/remediation/``). Technical severity never drives the
recommended disposition by itself: a resource without a known business
mapping is always escalated for human triage rather than acted on, no matter
how severe the underlying Defender signal is (see phase 2 decision D-09).

Cases are grouped by ``(canonical_resource_key, weakness_key)`` -- the same
resource can appear in several cases when Defender's signal families report
genuinely distinct weaknesses (D-02). Every case keeps its contributing
Defender evidence as distinguishable citations (D-03), separates observed
facts from derived inferences and unknowns (D-15), and reports a
``no_safe_action`` outcome (never fabricated remediation steps) when no
governed catalog action addresses the weakness (RECOMM-03).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from api.evidence import classify_freshness
from api.scope import Scope, scope_attributes
from intelligence.predictive.predictive_context_builder import PredictiveContextBuilder
from intelligence.remediation.dependency_analyzer import DependencyAnalyzer

_SEVERITY_SCORE = {"critical": 100, "high": 75, "medium": 50, "low": 25}
_DISPOSITIONS = frozenset({"act_now", "schedule", "defer", "not_applicable", "escalate"})


def _canonical(value: Any) -> str:
    return PredictiveContextBuilder.canonical_key(value)


def _weakness_key(row: Mapping[str, Any], *, id_field: str, id_prefix: str) -> str:
    """Derive a shared weakness identity: CVE first, then recommendation/title text."""
    cve = str(row.get("cve_id") or "").strip()
    if not cve:
        cve_ids = row.get("cveIds")
        if isinstance(cve_ids, list) and cve_ids:
            cve = str(cve_ids[0] or "").strip()
    if cve:
        return f"cve:{cve.casefold()}"
    text = str(
        row.get("recommendation")
        or row.get("title")
        or row.get("displayName")
        or ""
    ).strip()
    if text:
        return f"text:{text.casefold()}"
    return f"id:{id_prefix}:{str(row.get(id_field) or '')}"


class DefenderRemediationCase:
    """Marker type identifying the dict shape produced by ``cases()``.

    Cases are plain ``dict`` payloads (matching the rest of this package's
    JSON-serializable convention); this class exists so callers can refer to
    the shape by name without importing a TypedDict definition.
    """


class DefenderRemediationCorrelator:
    """Joins Defender read-model signals to business context, read-only.

    Constructed from an already-resolved ``VulnerabilityIntelligenceService``
    (the sole source of Defender signal rows) and the same resource records a
    ``RemediationPlanner`` uses, so no new inventory read path is introduced.
    """

    def __init__(
        self,
        *,
        vulnerability_service: Any,
        dependency_analyzer: DependencyAnalyzer,
        resource_lookup: Iterable[Mapping[str, Any]] = (),
        action_catalog: list[Mapping[str, Any]] | None = None,
        max_cases: int = 1000,
        max_citations_per_case: int = 100,
    ) -> None:
        for name, value in (
            ("max_cases", max_cases),
            ("max_citations_per_case", max_citations_per_case),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if min(max_cases, max_citations_per_case) < 1:
            raise ValueError("Defender correlation bounds must be positive")
        self.vulnerability_service = vulnerability_service
        self.dependency_analyzer = dependency_analyzer
        self.max_cases = max_cases
        self.max_citations_per_case = max_citations_per_case
        self.resources_by_key: dict[str, dict[str, Any]] = {}
        for resource in resource_lookup:
            key = _canonical(resource.get("resource_key"))
            if key:
                self.resources_by_key[key] = dict(resource)
        self.action_catalog = [dict(action) for action in action_catalog or ()]

    def cases(self, scope: Scope | None = None) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        service = self.vulnerability_service
        family_status = self._family_status(scope)

        for assessment in service.defender_posture(scope):
            resource_id = str(assessment.get("asset_id") or "")
            key = _canonical(resource_id)
            if not key:
                continue
            weakness = _weakness_key(
                assessment, id_field="assessment_id", id_prefix="assessment"
            )
            self._append_citation(
                groups,
                key,
                weakness,
                source_type="assessment",
                source_id=str(assessment.get("assessment_id") or ""),
                observed_at=str(assessment.get("last_assessed_at") or ""),
                severity=str(assessment.get("severity") or ""),
                summary=str(
                    assessment.get("recommendation")
                    or assessment.get("description")
                    or "Defender assessment finding"
                ),
                weakness_source=assessment,
            )

        for alert in service.security_alerts(scope, active_only=False):
            weakness = _weakness_key(alert, id_field="id", id_prefix="alert")
            for resource_id in alert.get("resourceIds") or ():
                key = _canonical(resource_id)
                if not key:
                    continue
                self._append_citation(
                    groups,
                    key,
                    weakness,
                    source_type="alert",
                    source_id=str(alert.get("id") or ""),
                    observed_at=str(alert.get("timeGenerated") or ""),
                    severity=str(alert.get("severity") or ""),
                    summary=str(alert.get("title") or "Defender alert"),
                    weakness_source=alert,
                )

        for path in service.defender_attack_paths_for_scope(scope):
            weakness = _weakness_key(path, id_field="id", id_prefix="attack_path")
            for resource_id in path.get("resourceIds") or ():
                key = _canonical(resource_id)
                if not key:
                    continue
                self._append_citation(
                    groups,
                    key,
                    weakness,
                    source_type="attack_path",
                    source_id=str(path.get("id") or ""),
                    observed_at=str(service.freshness or ""),
                    severity="high",
                    summary=str(
                        path.get("title")
                        or path.get("displayName")
                        or "Defender attack path membership"
                    ),
                    weakness_source=path,
                )

        for control in service.secure_score_controls(scope):
            weakness = _weakness_key(
                control, id_field="id", id_prefix="secure_score_control"
            )
            for resource_id in control.get("assessmentDefinitions") or ():
                key = _canonical(resource_id)
                if not key:
                    continue
                self._append_citation(
                    groups,
                    key,
                    weakness,
                    source_type="secure_score_control",
                    source_id=str(control.get("id") or ""),
                    observed_at=str(control.get("observedAt") or ""),
                    severity="medium",
                    summary=str(
                        control.get("title")
                        or control.get("displayName")
                        or "Defender secure score control gap"
                    ),
                    weakness_source=control,
                )

        if len(groups) > self.max_cases:
            raise ValueError("Defender remediation cases exceed configured bound")

        cases = [
            self._build_case(key, weakness, group, family_status)
            for (key, weakness), group in groups.items()
        ]
        return sorted(
            cases,
            key=lambda case: (
                -_SEVERITY_SCORE.get(str(case.get("max_severity") or "").casefold(), 0),
                case["resource_key"],
                case["weakness_key"],
            ),
        )

    def posture_by_resource(self) -> dict[str, dict[str, Any]]:
        """Scalar Defender signals per canonical resource key (fixed vocabulary).

        This is consumed verbatim by later plans in this phase (02-03,
        02-07) and must not be renamed without updating those plans too.
        """
        service = self.vulnerability_service
        posture: dict[str, dict[str, Any]] = {}

        def _slot(resource_id: str) -> dict[str, Any] | None:
            key = _canonical(resource_id)
            if not key:
                return None
            if key not in posture:
                resource = self.resources_by_key.get(key, {})
                posture[key] = {
                    "defender_active_critical_alert_count": 0,
                    "defender_active_high_alert_count": 0,
                    "defender_attack_path_membership_count": 0,
                    "defender_attack_path_target_count": 0,
                    "defender_unhealthy_control_count": 0,
                    "defender_secure_score_gap": 0,
                    "defender_exploitable_finding_count": 0,
                    "defender_max_severity": "",
                    "defender_evidence_freshness": "",
                    "defender_business_mapping_known": bool(
                        resource.get("application") or resource.get("business_service")
                    ),
                }
            return posture[key]

        def _bump_severity(slot: dict[str, Any], severity: str, observed_at: str) -> None:
            current = _SEVERITY_SCORE.get(str(slot["defender_max_severity"]).casefold(), -1)
            candidate = _SEVERITY_SCORE.get(severity.casefold(), 0)
            if candidate >= current:
                slot["defender_max_severity"] = severity.casefold()
            if observed_at and observed_at > str(slot["defender_evidence_freshness"] or ""):
                slot["defender_evidence_freshness"] = observed_at

        for assessment in service.defender_posture():
            slot = _slot(str(assessment.get("asset_id") or ""))
            if slot is None:
                continue
            _bump_severity(
                slot,
                str(assessment.get("severity") or ""),
                str(assessment.get("last_assessed_at") or ""),
            )

        for alert in service.security_alerts(active_only=True):
            severity = str(alert.get("severity") or "").casefold()
            for resource_id in alert.get("resourceIds") or ():
                slot = _slot(str(resource_id))
                if slot is None:
                    continue
                if severity == "critical":
                    slot["defender_active_critical_alert_count"] += 1
                elif severity == "high":
                    slot["defender_active_high_alert_count"] += 1
                cve_ids = alert.get("cveIds")
                if isinstance(cve_ids, list) and cve_ids:
                    slot["defender_exploitable_finding_count"] += 1
                _bump_severity(slot, severity, str(alert.get("timeGenerated") or ""))

        for path in service.defender_attack_paths_for_scope():
            resource_ids = list(path.get("resourceIds") or ())
            target_id = str(path.get("targetNodeId") or "")
            target_resource_ids = {
                str(node.get("resourceId") or "")
                for node in path.get("nodes") or ()
                if str(node.get("id") or "") == target_id
            }
            for resource_id in resource_ids:
                slot = _slot(str(resource_id))
                if slot is None:
                    continue
                slot["defender_attack_path_membership_count"] += 1
                if resource_id in target_resource_ids:
                    slot["defender_attack_path_target_count"] += 1

        for control in service.secure_score_controls():
            gap = max(
                0.0,
                float(control.get("maxScore") or 0) - float(control.get("currentScore") or 0),
            )
            for resource_id in control.get("assessmentDefinitions") or ():
                slot = _slot(str(resource_id))
                if slot is None:
                    continue
                slot["defender_unhealthy_control_count"] += 1
                slot["defender_secure_score_gap"] = max(
                    slot["defender_secure_score_gap"], int(gap)
                )

        return posture

    def _family_status(self, scope: Scope | None) -> dict[str, dict[str, Any]]:
        """Per-source-family availability, never defaulting a missing family to healthy."""
        service = self.vulnerability_service
        overview = getattr(service, "defender_overview", None)
        coverage: dict[str, Any] = {}
        if callable(overview):
            try:
                coverage = dict(overview(scope).get("coverage") or {})
            except TypeError:
                coverage = dict(overview().get("coverage") or {})
        mapping = {
            "assessment": coverage.get("recommendations"),
            "alert": coverage.get("alerts"),
            "attack_path": coverage.get("attack_paths"),
            "secure_score_control": coverage.get("secure_score"),
        }
        status: dict[str, dict[str, Any]] = {}
        for source_type, family in mapping.items():
            if isinstance(family, Mapping):
                status[source_type] = dict(family)
            else:
                status[source_type] = {"availability": "unknown", "freshness": "unknown"}
        return status

    def _append_citation(
        self,
        groups: dict[tuple[str, str], dict[str, Any]],
        resource_key: str,
        weakness_key: str,
        *,
        source_type: str,
        source_id: str,
        observed_at: str,
        severity: str,
        summary: str,
        weakness_source: Mapping[str, Any],
    ) -> None:
        group = groups.setdefault(
            (resource_key, weakness_key),
            {"citations": [], "weakness_source": weakness_source},
        )
        if len(group["citations"]) >= self.max_citations_per_case:
            raise ValueError("Defender case citations exceed configured bound")
        group["citations"].append(
            {
                "source_type": source_type,
                "source_id": source_id[:512],
                "observed_at": observed_at,
                "freshness": classify_freshness(observed_at) if observed_at else "unknown",
                "summary": summary[:1024],
                "severity": severity.casefold(),
            }
        )

    def _build_case(
        self,
        resource_key: str,
        weakness_key: str,
        group: dict[str, Any],
        family_status: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        citations = sorted(
            group["citations"], key=lambda citation: (citation["source_type"], citation["source_id"])
        )
        resource = self.resources_by_key.get(resource_key, {})
        dependencies = self.dependency_analyzer.analyze(resource)
        business_mapping_known = bool(
            dependencies["affected_applications"] or dependencies["affected_services"]
        )
        max_severity = max(
            (citation["severity"] for citation in citations),
            key=lambda severity: _SEVERITY_SCORE.get(severity, 0),
            default="",
        )
        catalog_match = self._catalog_match(group["weakness_source"])

        source_families = {
            citation["source_type"]: family_status.get(
                citation["source_type"], {"availability": "unknown", "freshness": "unknown"}
            )
            for citation in citations
        }
        degraded_families = {
            source_type: status
            for source_type, status in source_families.items()
            if str(status.get("availability") or "unknown") != "available"
        }
        severities_present = {citation["severity"] for citation in citations if citation["severity"]}
        contradictory = len(severities_present) > 1 and (
            "critical" in severities_present or "high" in severities_present
        ) and (
            "low" in severities_present or "medium" in severities_present
        )

        confidence = self._confidence(
            business_mapping_known,
            len(citations),
            degraded=bool(degraded_families),
            contradictory=contradictory,
        )
        disposition, outcome, outcome_reason = self._disposition(
            business_mapping_known=business_mapping_known,
            catalog_match=catalog_match,
            max_severity=max_severity,
        )
        urgency_rationale = self._urgency_rationale(
            max_severity=max_severity,
            citation_count=len(citations),
            business_mapping_known=business_mapping_known,
        )
        resource_name = str(resource.get("name") or "") or _resource_name_from_key(resource_key)

        observed_facts = [
            f"{citation['source_type']}:{citation['source_id']} reported {citation['severity'] or 'unspecified'} severity - {citation['summary']}"
            for citation in citations
        ]
        derived_inferences = []
        unknowns = []
        if business_mapping_known:
            derived_inferences.append(
                f"Affects {', '.join(dependencies['affected_services'] or dependencies['affected_applications'])}"
                f" with {dependencies['dependency_count']} bounded dependency reference(s)."
            )
        else:
            unknowns.extend(["application", "business_service", "owner"])
            derived_inferences.append(
                "No governed business mapping was found for this resource; impact cannot be inferred."
            )
        if not catalog_match:
            unknowns.append("catalog_action")
        if degraded_families:
            unknowns.extend(sorted(f"source_family:{name}" for name in degraded_families))
        if contradictory:
            derived_inferences.append(
                "Defender source families disagree on severity for this resource; "
                "treating the disagreement as reduced confidence rather than a single definitive claim."
            )

        scope_attrs = scope_attributes(resource)

        return {
            "resource_key": resource_key,
            "weakness_key": weakness_key,
            "resource_name": resource_name,
            "evidence_citations": citations,
            "business_context": dependencies,
            "business_mapping_review_required": not business_mapping_known,
            "cost_of_action": self._cost_of_action(dependencies, business_mapping_known),
            "cost_of_inaction": self._cost_of_inaction(
                dependencies, max_severity, business_mapping_known
            ),
            "disposition": disposition,
            "urgency_rationale": urgency_rationale,
            "confidence": confidence,
            "max_severity": max_severity,
            "catalog_match": catalog_match,
            "outcome": outcome,
            "outcome_reason": outcome_reason,
            "observed_facts": observed_facts,
            "derived_inferences": derived_inferences,
            "unknowns": unknowns,
            "source_family_status": source_families,
            "contradictory_evidence": contradictory,
            "read_only": True,
            **scope_attrs,
        }


    def _catalog_match(self, weakness_source: Mapping[str, Any]) -> bool:
        if not self.action_catalog:
            return False
        candidate_text = str(
            weakness_source.get("recommendation")
            or weakness_source.get("title")
            or weakness_source.get("displayName")
            or ""
        ).casefold()
        if not candidate_text:
            return False
        for action in self.action_catalog:
            for clause in (action.get("trigger") or {}).get("any") or ():
                if clause.get("field") != "defender_recommendation":
                    continue
                if str(clause.get("equals") or "").casefold() == candidate_text:
                    return True
        return False

    @staticmethod
    def _confidence(
        business_mapping_known: bool,
        citation_count: int,
        *,
        degraded: bool = False,
        contradictory: bool = False,
    ) -> float:
        base = 0.85 if business_mapping_known else 0.3
        # Additional corroborating evidence nudges confidence up slightly,
        # bounded so it never crosses into a different confidence tier.
        bonus = min(0.1, 0.02 * max(0, citation_count - 1))
        confidence = min(base + bonus, 0.95 if business_mapping_known else 0.45)
        if degraded:
            confidence -= 0.15
        if contradictory:
            confidence -= 0.2
        return round(max(0.05, confidence), 2)

    @staticmethod
    def _disposition(
        *, business_mapping_known: bool, catalog_match: bool, max_severity: str
    ) -> tuple[str, str, str]:
        if not business_mapping_known:
            return (
                "escalate",
                "actionable" if catalog_match else "no_safe_action",
                ""
                if catalog_match
                else "No governed catalog action addresses this weakness; escalate for manual review.",
            )
        if not catalog_match:
            return (
                "defer",
                "no_safe_action",
                "No governed catalog action addresses this weakness; recommend platform-team review "
                "before any change is proposed.",
            )
        if max_severity in {"critical", "high"}:
            return "act_now", "actionable", ""
        if max_severity == "medium":
            return "schedule", "actionable", ""
        return "defer", "actionable", ""

    @staticmethod
    def _urgency_rationale(
        *, max_severity: str, citation_count: int, business_mapping_known: bool
    ) -> str:
        severity_text = max_severity or "unspecified"
        if not business_mapping_known:
            return (
                f"{severity_text} severity signal with no known business mapping across "
                f"{citation_count} citation(s); escalate for business-context confirmation "
                "before any recommendation can be trusted."
            )
        return (
            f"{severity_text} severity signal corroborated by {citation_count} citation(s) "
            "against a known business mapping."
        )

    @staticmethod
    def _cost_of_action(dependencies: dict[str, Any], business_mapping_known: bool) -> str:
        if business_mapping_known:
            owners = ", ".join(dependencies["owners"]) or "an unassigned owner"
            return (
                f"Requires a maintenance window coordinated with {owners} and "
                f"{dependencies['dependency_count']} bounded dependency reference(s)."
            )
        return "Cost of action cannot be scoped without a known business owner; treat as unbounded until mapped."

    @staticmethod
    def _cost_of_inaction(
        dependencies: dict[str, Any], max_severity: str, business_mapping_known: bool
    ) -> str:
        severity_text = max_severity or "unspecified"
        if business_mapping_known:
            services = ", ".join(dependencies["affected_services"] or dependencies["affected_applications"])
            return f"Continued {severity_text}-severity exposure on {services} until remediated."
        return (
            f"Continued {severity_text}-severity exposure on an unmapped resource; business impact "
            "cannot be bounded until ownership is confirmed."
        )


def _resource_name_from_key(resource_key: str) -> str:
    return resource_key.rstrip("/").rsplit("/", 1)[-1] if resource_key else "Unknown"
