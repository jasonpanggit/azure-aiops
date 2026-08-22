from __future__ import annotations


class RootCauseEngine:
    """Ranks evidence without asserting confirmed root cause."""

    def __init__(self, *, max_items: int = 50) -> None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError("Root-cause item bound must be a positive integer")
        self.max_items = max_items

    def analyze(self, finding, timeline):
        causes = (finding.get("probable_causes") or [])[: self.max_items]
        contributing = (finding.get("contributing_factors") or [])[: self.max_items]
        top_confidence = max(
            [float(row.get("confidence") or 0) for row in [*causes, *contributing]],
            default=0.0,
        )
        top_cause = causes[0] if causes else None
        contradicting = self._contradicting_evidence(top_cause, causes, contributing, timeline)
        unknowns = self._unknowns(finding, timeline)
        next_steps = self._next_steps(finding, top_cause, contradicting, unknowns)
        return {
            "probable_causes": causes,
            "contributing_factors": contributing,
            "confidence": min(top_confidence, 0.95),
            "evidence": [
                row
                for cause in [*causes, *contributing]
                for row in cause.get("evidence", [])
            ][: self.max_items],
            "timeline": timeline[: self.max_items],
            "impacted_systems": [
                finding.get("resource"),
                *finding.get("impacted_applications", []),
            ][: self.max_items],
            "reasoning_chain": [
                "Select evidence on the same canonical resource",
                "Require evidence to precede the incident for causal eligibility",
                "Weight temporal proximity, severity, and explicit causal relevance",
                "Treat lifecycle and post-incident evidence as context, not confirmed cause",
            ][: self.max_items],
            "contradicting_evidence": contradicting,
            "unknowns": unknowns,
            "next_steps": next_steps,
            "confirmed_cause": False,
            "conclusion": "Probable operational causes ranked for investigation; causality is not confirmed.",
        }

    def _contradicting_evidence(self, top_cause, causes, contributing, timeline):
        if top_cause is None:
            return []
        contradictory = []
        top_classification = str(top_cause.get("classification") or "").casefold()
        top_type = str(top_cause.get("evidence_type") or "")
        seen = set()
        for row in [*causes[1:], *contributing]:
            classification = str(row.get("classification") or "").casefold()
            if classification and classification != top_classification:
                summary = str(row.get("summary") or row.get("evidence_type") or "Conflicting evidence")[:512]
                identity = (str(row.get("evidence_id") or summary), summary)
                if identity not in seen:
                    seen.add(identity)
                    contradictory.append(
                        {
                            "evidence_id": row.get("evidence_id"),
                            "evidence_type": row.get("evidence_type"),
                            "classification": row.get("classification"),
                            "summary": summary,
                            "reason": f"Same-resource evidence ranked as {row.get('classification') or 'context'} instead of the leading {top_type} hypothesis.",
                        }
                    )
        for event in timeline:
            event_type = str(event.get("event_type") or "")
            summary = str(event.get("summary") or "")
            token = summary.casefold()
            if any(word in token for word in ("success", "succeeded", "recovered", "healthy", "resolved", "compliant", "installed")):
                identity = (str(event.get("event_id") or summary), summary)
                if identity not in seen:
                    seen.add(identity)
                    contradictory.append(
                        {
                            "evidence_id": event.get("event_id"),
                            "evidence_type": event_type,
                            "classification": "Recovery evidence",
                            "summary": summary[:512],
                            "reason": "Observed recovery or success weakens a single-cause interpretation.",
                        }
                    )
        return contradictory[: self.max_items]

    def _unknowns(self, finding, timeline):
        unknowns = []
        resource = self._resource_name(finding)
        event_types = {str(event.get("event_type") or "") for event in timeline}
        if not (event_types & {"Network Change", "Firewall Rule Change", "NSG Change"}):
            unknowns.append(f"network_change_evidence_unavailable:{resource}")
        if "CVE Exposure" not in event_types:
            unknowns.append(f"cve_exposure_data_unavailable:{resource}")
        if str(finding.get("owner") or "Unknown").casefold() == "unknown":
            unknowns.append(f"owner_not_mapped:{resource}")
        if str(finding.get("support_team") or "Unknown").casefold() == "unknown":
            unknowns.append(f"support_team_not_mapped:{resource}")
        return unknowns[: self.max_items]

    def _next_steps(self, finding, top_cause, contradicting, unknowns):
        if top_cause is None:
            return [
                "Review the incident timeline and available evidence before drawing an operational conclusion."
            ]
        resource = self._resource_name(finding)
        when = str(top_cause.get("observed_at") or finding.get("incident", {}).get("started_at") or "")
        evidence_type = str(top_cause.get("evidence_type") or "operational evidence")
        steps = [
            f"Review {evidence_type} on {resource} before {when} and confirm it aligns with the incident start window."[:512]
        ]
        if any(item.startswith("network_change_evidence_unavailable:") for item in unknowns):
            steps.append(f"Review NSG, firewall, and route-change evidence for {resource} around {when}."[:512])
        if any(item.startswith("cve_exposure_data_unavailable:") for item in unknowns):
            steps.append(f"Confirm whether CVE exposure or missing patch evidence exists for {resource}."[:512])
        if contradicting:
            steps.append("Compare the leading cause against recovery or alternative evidence before escalating a remediation plan."[:512])
        return steps[: self.max_items]

    @staticmethod
    def _resource_name(finding) -> str:
        resource = finding.get("resource")
        if isinstance(resource, dict):
            return str(resource.get("name") or resource.get("resource_key") or "resource")[:128]
        return str(resource or "resource")[:128]
