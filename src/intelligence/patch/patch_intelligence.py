from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from opentelemetry import metrics

from intelligence.incident.incident_intelligence import IncidentIntelligence
from intelligence.lifecycle.lifecycle_context_builder import canonical_resource_key

from .patch_analyzer import PatchAnalyzer
from .patch_compliance_engine import PatchComplianceEngine
from .patch_context_builder import PatchContextBuilder
from .patch_risk_engine import PatchRiskEngine
from .patch_summary_engine import PatchSummaryEngine
from .patch_trend_engine import PatchTrendEngine


class UpdateCategory(StrEnum):
    CRITICAL = "Critical"
    SECURITY = "Security"
    FEATURE = "Feature"
    DEFINITION = "Definition"
    OTHER = "Other"


def _require_count(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Patch {field_name} must be a non-negative integer")


def _require_score(value: Any, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 100
    ):
        raise ValueError(f"Patch {field_name} must be a finite score from 0 to 100")


@dataclass(frozen=True)
class Update:
    update_id: str
    name: str
    category: UpdateCategory = UpdateCategory.OTHER
    severity: str = "Unknown"
    published_at: str = ""


@dataclass(frozen=True)
class PatchAssessment:
    resource: str
    assessed_at: str
    status: str
    available_updates: int = 0
    missing_critical_updates: int = 0
    missing_security_updates: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "available_updates",
            "missing_critical_updates",
            "missing_security_updates",
        ):
            _require_count(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class PatchInstallation:
    resource: str
    update: Update
    installed_at: str
    status: str
    error: str = ""


@dataclass(frozen=True)
class MissingUpdate:
    resource: str
    update: Update
    age_days: int

    def __post_init__(self) -> None:
        _require_count(self.age_days, "age_days")


@dataclass(frozen=True)
class InstalledUpdate:
    resource: str
    update: Update
    installed_at: str


@dataclass(frozen=True)
class FailedUpdate:
    resource: str
    update: Update
    failed_at: str
    error: str = ""


@dataclass(frozen=True)
class CriticalUpdate:
    update: Update


@dataclass(frozen=True)
class SecurityUpdate:
    update: Update


@dataclass(frozen=True)
class ResourceCompliance:
    resource: str
    compliance_score: int
    patch_success_percent: float
    patch_failure_percent: float
    missing_critical_updates: int
    missing_security_updates: int
    unpatched: bool

    def __post_init__(self) -> None:
        _require_score(self.compliance_score, "compliance_score")
        _require_score(self.patch_success_percent, "patch_success_percent")
        _require_score(self.patch_failure_percent, "patch_failure_percent")
        _require_count(self.missing_critical_updates, "missing_critical_updates")
        _require_count(self.missing_security_updates, "missing_security_updates")
        if not isinstance(self.unpatched, bool):
            raise TypeError("Patch unpatched must be boolean")


@dataclass(frozen=True)
class PatchWindow:
    name: str
    start: str
    end: str
    timezone: str = "UTC"


@dataclass(frozen=True)
class PatchPolicy:
    name: str
    environment: str
    max_patch_age_days: int
    minimum_compliance_score: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_patch_age_days, bool)
            or not isinstance(self.max_patch_age_days, int)
            or self.max_patch_age_days < 1
        ):
            raise ValueError("Patch max_patch_age_days must be a positive integer")
        _require_score(self.minimum_compliance_score, "minimum_compliance_score")


@dataclass(frozen=True)
class PatchBaseline:
    name: str
    required_update_ids: tuple[str, ...] = field(default_factory=tuple)
    policy: str = ""


Installation = PatchInstallation
MaintenanceWindow = PatchWindow
Policy = PatchPolicy


class PatchTelemetry:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("aiops.patch_intelligence", "0.1.0")
        self.compliance_duration = meter.create_histogram(
            "patch.compliance.calculation.duration", unit="s"
        )
        self.analysis_latency = meter.create_histogram(
            "patch.intelligence.analysis.latency", unit="s"
        )
        self.trend_latency = meter.create_histogram(
            "patch.trend.calculation.latency", unit="s"
        )
        self.freshness = meter.create_histogram(
            "patch.intelligence.freshness", unit="s"
        )
        self.risk_duration = meter.create_histogram(
            "patch.risk.calculation.duration", unit="s"
        )
        self.business_impact_duration = meter.create_histogram(
            "patch.business_impact.correlation.duration", unit="s"
        )


class PatchIntelligence:
    """Read-only business-aware patch intelligence over governed semantic facts."""

    QUERY_NAMES: ClassVar[set[str]] = {
        "show patch compliance",
        "show patch risk",
        "show vulnerable applications",
        "show critical patch failures",
        "show patch priority list",
        "show security exposure",
        "show patch trends",
        "show business impact",
        "show patch debt",
    }

    def __init__(
        self,
        *,
        resources: list[dict[str, Any]],
        assessments: list[dict[str, Any]],
        installations: list[dict[str, Any]],
        history: list[dict[str, Any]],
        security_findings: list[dict[str, Any]],
        advisor_recommendations: list[dict[str, Any]],
        policies: list[dict[str, Any]],
        freshness: str,
        baselines: list[dict[str, Any]] | None = None,
        windows: list[dict[str, Any]] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
        telemetry: PatchTelemetry | None = None,
        max_resources: int = 5000,
        max_evidence_rows: int = 50000,
        max_output_items: int = 100,
        max_serialized_bytes: int = 1_000_000,
    ) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (max_resources, max_evidence_rows, max_output_items)
        ):
            raise ValueError("Patch bounds must be positive integers")
        if (
            isinstance(max_serialized_bytes, bool)
            or not isinstance(max_serialized_bytes, int)
            or max_serialized_bytes < 1024
        ):
            raise ValueError("Patch serialized output bound must be at least 1024 bytes")
        collections = (
            resources,
            assessments,
            installations,
            history,
            security_findings,
            advisor_recommendations,
            policies,
            baselines or [],
            windows or [],
        )
        if any(not isinstance(rows, list) for rows in collections):
            raise TypeError("Patch snapshot collections must be lists")
        if any(any(not isinstance(row, dict) for row in rows) for rows in collections):
            raise TypeError("Patch snapshot rows must be mappings")
        if len(resources) > max_resources:
            raise ValueError("Patch resources exceed the configured resource bound")
        for name, rows in (
            ("assessments", assessments),
            ("installations", installations),
            ("history", history),
            ("security_findings", security_findings),
            ("advisor_recommendations", advisor_recommendations),
        ):
            if len(rows) > max_evidence_rows:
                raise ValueError(
                    f"Patch {name} exceeds the configured evidence row bound"
                )
        self.now = now
        self.max_output_items = max_output_items
        self.max_serialized_bytes = max_serialized_bytes
        self.resources = [dict(row) for row in resources]
        self.assessments = self._normalize_evidence_timestamps(
            assessments, ("assessed_at", "last_modified", "timestamp"), "assessments"
        )
        self.installations = self._normalize_evidence_timestamps(
            installations,
            ("published_at", "installed_at", "last_modified"),
            "installations",
        )
        self.history = self._normalize_evidence_timestamps(
            history, ("observed_at", "last_modified", "timestamp"), "history"
        )
        self.security_findings = self._normalize_evidence_timestamps(
            security_findings, ("observed_at", "timestamp"), "security_findings"
        )
        self.advisor_recommendations = self._normalize_evidence_timestamps(
            advisor_recommendations,
            ("observed_at", "timestamp"),
            "advisor_recommendations",
        )
        self._validate_numeric_evidence()
        self._reject_duplicate_installations()
        self._reject_duplicate_history()
        self.policies = [PatchPolicy(**row) for row in policies]
        self.baselines = [PatchBaseline(**row) for row in (baselines or [])]
        self.windows = [PatchWindow(**row) for row in (windows or [])]
        self.freshness_value = self._normalize_timestamp(freshness, "freshness")
        freshness_at = datetime.fromisoformat(self.freshness_value)
        current = self.now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        if freshness_at > current.astimezone(UTC):
            raise ValueError("Patch intelligence freshness timestamp is in the future")
        self._reject_future_observations(
            freshness_at,
            (
                (self.assessments, ("assessed_at", "last_modified", "timestamp")),
                (
                    self.installations,
                    ("published_at", "installed_at", "last_modified"),
                ),
                (self.history, ("observed_at", "last_modified", "timestamp")),
                (self.security_findings, ("observed_at", "timestamp")),
                (self.advisor_recommendations, ("observed_at", "timestamp")),
            ),
        )
        self.clock = clock
        self.telemetry = telemetry or PatchTelemetry()
        self.compliance_engine = PatchComplianceEngine()
        self.analyzer = PatchAnalyzer(
            PatchContextBuilder(self.resources, max_resources=max_resources),
            compliance=self.compliance_engine,
        )
        self.trends_engine = PatchTrendEngine()
        self.summary_engine = PatchSummaryEngine()

    @classmethod
    def from_semantic_snapshot(cls, **snapshot: Any) -> PatchIntelligence:
        """Construct from OneLake/semantic projections; performs no Azure calls."""
        return cls(**snapshot)

    @classmethod
    def from_semantic_engine(
        cls,
        semantic_engine,
        *,
        inventory: list[dict[str, Any]],
        assessments: list[dict[str, Any]],
        installations: list[dict[str, Any]],
        history: list[dict[str, Any]],
        policies: list[dict[str, Any]],
        **kwargs: Any,
    ) -> PatchIntelligence:
        """Correlate OneLake patch facts through public Semantic Engine contexts."""
        max_resources = kwargs.get("max_resources", 5000)
        max_evidence_rows = kwargs.get("max_evidence_rows", 50000)
        for name, value in (
            ("max_resources", max_resources),
            ("max_evidence_rows", max_evidence_rows),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"Patch {name} must be a positive integer")
        collections = (inventory, assessments, installations, history, policies)
        if any(not isinstance(rows, list) for rows in collections):
            raise TypeError("Patch Semantic source collections must be lists")
        if any(any(not isinstance(row, dict) for row in rows) for rows in collections):
            raise TypeError("Patch Semantic source rows must be mappings")
        if len(inventory) > max_resources:
            raise ValueError("Patch inventory exceeds configured resource bound")
        for name, rows in (
            ("assessments", assessments),
            ("installations", installations),
            ("history", history),
        ):
            if len(rows) > max_evidence_rows:
                raise ValueError(f"Patch {name} exceeds configured evidence bound")
        if any(not row.get("resource_id") or not row.get("name") for row in inventory):
            raise ValueError("Patch inventory rows require resource identity and name")
        names_by_id = {
            canonical_resource_key(row.get("resource_id")): str(row.get("name") or "")
            for row in inventory
            if row.get("resource_id") and row.get("name")
        }
        for rows, fields in (
            (assessments, ("assessed_resource_id", "target_resource_id")),
            (installations, ("target_resource_id",)),
            (history, ("assessed_resource_id", "target_resource_id")),
        ):
            for evidence in rows:
                target = canonical_resource_key(
                    next((evidence.get(field) for field in fields if evidence.get(field)), None)
                )
                if not target or target not in names_by_id:
                    raise ValueError(
                        "Patch Semantic evidence requires a matching canonical target"
                    )
        resources: list[dict[str, Any]] = []
        security_findings: list[dict[str, Any]] = []
        advisor_recommendations: list[dict[str, Any]] = []
        unresolved_resource_keys: list[str] = []
        for row in inventory:
            name = str(row.get("name") or "")
            entity_type = str(row.get("entity_type") or "Resource")
            resource_key = canonical_resource_key(row.get("resource_id"))
            # Inventory can legitimately contain resources that are absent from
            # the currently published ontology snapshot (for example when a
            # discovery run is newer than the last ontology publication). Treat
            # those as coverage gaps rather than failing the entire provider
            # load, which would otherwise keep API readiness at 503 for every
            # capability.
            try:
                context = semantic_engine.get_resource_context(
                    resource_key, subject_type=entity_type
                )
                impact = semantic_engine.get_impact_context(
                    resource_key, subject_type=entity_type
                )
            except LookupError:
                unresolved_resource_keys.append(resource_key)
                continue
            if not isinstance(context, dict) or not isinstance(impact, dict):
                raise TypeError("Patch Semantic context and impact must be mappings")
            raw_sections = context.get("sections")
            if raw_sections is None:
                sections = {}
            elif not isinstance(raw_sections, dict):
                raise TypeError("Patch Semantic sections must be a mapping")
            else:
                sections = raw_sections
            for section_name in (
                "applications",
                "business_services",
                "ownership",
                "support_teams",
                "security_findings",
                "advisor_findings",
            ):
                if section_name in sections and not isinstance(
                    sections[section_name], list
                ):
                    raise TypeError(f"Patch Semantic {section_name} must be a list")
                if section_name in sections and any(
                    not isinstance(item, dict) for item in sections[section_name]
                ):
                    raise TypeError(
                        f"Patch Semantic {section_name} members must be mappings"
                    )
            raw_classification = sections.get("operational_classification")
            if raw_classification is None:
                classification = {}
            elif not isinstance(raw_classification, dict):
                raise TypeError("Patch operational classification must be a mapping")
            else:
                classification = raw_classification
            resources.append(
                {
                    "resource_key": resource_key,
                    "name": name,
                    "entity_type": entity_type,
                    "subscription": str(row.get("subscription") or row.get("subscription_id") or "Unknown"),
                    "application": cls._first_name(sections.get("applications")),
                    "business_service": cls._first_name(
                        sections.get("business_services")
                    ),
                    "owner": cls._first_name(sections.get("ownership")),
                    "support_team": cls._first_name(sections.get("support_teams")),
                    "environment": str(
                        classification.get("environment")
                        or row.get("environment")
                        or "Unknown"
                    ),
                    "business_criticality": str(
                        classification.get("criticality")
                        or row.get("criticality")
                        or "Unknown"
                    ),
                    "application_impact": str(
                        classification.get("criticality")
                        or row.get("criticality")
                        or "Unknown"
                    ),
                    "ownership_coverage": bool(sections.get("ownership")),
                    "blast_radius": impact.get("blast_radius") or {},
                }
            )
            security_findings.extend(
                {
                    "resource_key": str(row.get("resource_id") or "").casefold(),
                    "resource": name,
                    **dict(item),
                }
                for item in sections.get("security_findings") or []
                if isinstance(item, dict)
            )
            advisor_recommendations.extend(
                {
                    "resource_key": str(row.get("resource_id") or "").casefold(),
                    "resource": name,
                    "title": str(item.get("name") or "Advisor recommendation"),
                    "impact": "Unknown",
                }
                for item in sections.get("advisor_findings") or []
                if isinstance(item, dict)
            )
        normalized_assessments = [
            {
                "resource_key": canonical_resource_key(
                    row.get("assessed_resource_id")
                    or row.get("target_resource_id")
                ),
                "resource": names_by_id.get(
                    canonical_resource_key(
                        row.get("assessed_resource_id")
                        or row.get("target_resource_id")
                    ),
                    str(row.get("resource") or ""),
                ),
                "assessed_at": str(
                    row.get("last_modified") or row.get("timestamp") or ""
                ),
                "status": str(row.get("status") or "unknown"),
                "available_updates": cls._strict_nonnegative_int(
                    row.get("available_updates"), "available_updates"
                ),
                "missing_critical_updates": cls._strict_nonnegative_int(
                    row.get("missing_critical_updates"), "missing_critical_updates"
                ),
                "missing_security_updates": cls._strict_nonnegative_int(
                    row.get("missing_security_updates"), "missing_security_updates"
                ),
            }
            for row in assessments
        ]
        normalized_installations = [
            {
                **dict(row),
                "resource_key": canonical_resource_key(row.get("target_resource_id")),
                "resource": names_by_id.get(
                    canonical_resource_key(row.get("target_resource_id")),
                    str(row.get("resource") or ""),
                ),
            }
            for row in installations
        ]
        normalized_history = [
            {
                "resource_key": canonical_resource_key(
                    row.get("assessed_resource_id")
                    or row.get("target_resource_id")
                ),
                "resource": names_by_id.get(
                    canonical_resource_key(
                        row.get("assessed_resource_id")
                        or row.get("target_resource_id")
                    ),
                    str(row.get("resource") or ""),
                ),
                "observed_at": str(
                    row.get("observed_at")
                    or row.get("last_modified")
                    or row.get("timestamp")
                    or ""
                ),
                "status": str(row.get("status") or "unknown"),
                "missing_critical_updates": cls._strict_nonnegative_int(
                    row.get("missing_critical_updates"), "missing_critical_updates"
                ),
                "missing_security_updates": cls._strict_nonnegative_int(
                    row.get("missing_security_updates"), "missing_security_updates"
                ),
                "risk_score": cls._strict_optional_score(row.get("risk_score")),
            }
            for row in history
        ]
        contexts_by_key = {
            str(row.get("resource_key") or "").casefold(): row for row in resources
        }
        security_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in security_findings:
            security_by_key.setdefault(str(row.get("resource_key") or ""), []).append(
                row
            )
        advisors_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in advisor_recommendations:
            advisors_by_key.setdefault(str(row.get("resource_key") or ""), []).append(
                row
            )
        risk_engine = PatchRiskEngine()
        for item in normalized_history:
            if item["risk_score"] is not None or item["resource_key"] not in contexts_by_key:
                continue
            key = item["resource_key"]
            item["risk_score"] = risk_engine.calculate(
                context=contexts_by_key[key],
                compliance={
                    "patch_age_days": 0,
                    "highest_severity": (
                        "Critical" if item["missing_critical_updates"] else "Unknown"
                    ),
                    "missing_critical_updates": item[
                        "missing_critical_updates"
                    ],
                    "evidence_coverage": "Complete",
                },
                security_findings=security_by_key.get(key, []),
                advisor_recommendations=advisors_by_key.get(key, []),
            )["score"]
        return cls(
            resources=resources,
            assessments=normalized_assessments,
            installations=normalized_installations,
            history=normalized_history,
            security_findings=security_findings,
            advisor_recommendations=advisor_recommendations,
            policies=policies,
            freshness=str(semantic_engine.freshness),
            **kwargs,
        )

    def analyze(self) -> dict[str, Any]:
        started = self.clock()
        findings, compliance, trends, exposure = self._analysis_components()
        result = {
            "findings": findings,
            "compliance": compliance,
            "exposure": exposure,
            "trends": trends,
            "freshness": self.freshness_value,
            "read_only": True,
            "collection_metadata": self._metadata(
                len(findings), min(len(findings), self.max_output_items)
            ),
        }
        self.telemetry.analysis_latency.record(self.clock() - started)
        self._record_freshness()
        return self._bounded_public(result)

    def query(self, question: str) -> dict[str, Any]:
        normalized = " ".join(question.strip().rstrip(".?!").casefold().split())
        if normalized not in self.QUERY_NAMES:
            raise ValueError("Unsupported patch intelligence query")
        findings, compliance, trends, exposure = self._analysis_components()
        if normalized == "show patch compliance":
            payload: Any = compliance
        elif normalized == "show patch risk":
            payload = [self._risk_projection(item) for item in findings]
        elif normalized == "show vulnerable applications":
            payload = exposure["vulnerable_applications"]
        elif normalized == "show critical patch failures":
            payload = [
                item
                for item in findings
                if int(item.get("failed_critical_update_count") or 0) > 0
            ]
        elif normalized == "show patch priority list":
            payload = findings
        elif normalized == "show security exposure":
            payload = exposure
        elif normalized == "show patch trends":
            payload = trends
        elif normalized == "show business impact":
            impact_started = self.clock()
            payload = self._business_impact_rows()
            self.telemetry.business_impact_duration.record(
                self.clock() - impact_started
            )
        else:
            payload = {
                key: exposure[key]
                for key in ("security_patch_debt", "compliance_debt")
            }
        count = len(payload) if isinstance(payload, list) else 1
        return self._bounded_public({
            "query": normalized,
            "result": payload,
            "collection_metadata": self._metadata(
                count, min(count, self.max_output_items)
            ),
            "freshness": self.freshness_value,
            "read_only": True,
        })

    def business_impact(self) -> list[dict[str, Any]]:
        started = self.clock()
        rows = self._business_impact_rows()
        self.telemetry.business_impact_duration.record(self.clock() - started)
        return self._bounded_public(rows)

    def _business_impact_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "patch_failure": item["failed_update_count"] > 0,
                "resource": item["resource"],
                "application": item["application"],
                "business_service": item["business_service"],
                "owner": item["owner"],
                "support_team": item["support_team"],
                "impact_level": item["business_impact"],
                "blast_radius": {
                    "affected_resource_count": len(item["affected_resources"]),
                    "affected_resources": item["affected_resources"],
                    "application_count": int(
                        item.get("blast_radius", {}).get("application_count") or 0
                    ),
                    "business_service_count": int(
                        item.get("blast_radius", {}).get("business_service_count") or 0
                    ),
                    "service_count": int(
                        item.get("blast_radius", {}).get("service_count") or 0
                    ),
                },
            }
            for item in self._findings()
            if item["unpatched"] or item["failed_update_count"]
        ]

    def report(self, report_type: str) -> dict[str, Any]:
        findings, compliance, trends, exposure = self._analysis_components()
        report = self.summary_engine.generate(
            report_type,
            findings=findings,
            compliance=compliance,
            exposure=exposure,
            trends=trends,
            freshness=self.freshness_value,
        )
        return self._bounded_public(report)

    def internal_resource_posture(self) -> dict[str, dict[str, Any]]:
        """Internal canonical-key posture for other governed intelligence layers."""
        observed_by_key: dict[str, str] = {}
        debt_by_key: dict[str, int] = {}
        for assessment in self.assessments:
            resource_key = canonical_resource_key(assessment.get("resource_key"))
            observed_at = str(
                assessment.get("assessed_at")
                or assessment.get("last_modified")
                or assessment.get("timestamp")
                or ""
            )
            if resource_key and observed_at > observed_by_key.get(resource_key, ""):
                observed_by_key[resource_key] = observed_at
                debt_by_key[resource_key] = int(
                    assessment.get("available_updates") or 0
                )
        keys = {
            (
                str(context.get("subscription") or "Unknown"),
                str((context.get("resource") or {}).get("name") or ""),
                str((context.get("resource") or {}).get("entity_type") or "Resource"),
            ): str(context["_resource_key"])
            for context in self.analyzer.context_builder.all()
        }
        posture: dict[str, dict[str, Any]] = {}
        for finding in self._findings():
            resource = finding.get("resource") or {}
            key = keys.get(
                (
                    str(finding.get("subscription") or "Unknown"),
                    str(resource.get("name") or ""),
                    str(resource.get("entity_type") or "Resource"),
                ),
                "",
            )
            if key:
                posture[key] = {
                    "compliance_score": int(finding.get("compliance_score") or 0),
                    "risk_score": int(finding.get("risk_score") or 0),
                    "status": str(finding.get("status") or "unknown"),
                    "observed_at": observed_by_key.get(key, ""),
                    "patch_debt": debt_by_key.get(key, 0),
                    "failed_update": str(finding.get("status") or "").casefold()
                    in {"failed", "failure", "error"},
                }
        return posture

    def models(self) -> dict[str, list[dict[str, Any]]]:
        assessments = [asdict(PatchAssessment(**row)) for row in self.assessments]
        installations = []
        for row in self.installations:
            update = Update(
                update_id=str(row.get("update_id") or ""),
                name=str(row.get("update_name") or ""),
                category=self._category(row.get("category")),
                severity=str(row.get("severity") or "Unknown"),
                published_at=str(row.get("published_at") or ""),
            )
            installations.append(
                asdict(
                    PatchInstallation(
                        resource=str(row.get("resource") or ""),
                        update=update,
                        installed_at=str(row.get("installed_at") or ""),
                        status=str(row.get("status") or ""),
                        error=str(row.get("error") or ""),
                    )
                )
            )
        return self._bounded_public({
            "assessments": assessments,
            "installations": installations,
            "policies": [asdict(item) for item in self.policies],
            "baselines": [asdict(item) for item in self.baselines],
            "windows": [asdict(item) for item in self.windows],
        })

    def _analysis_components(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
        findings = self._findings()
        compliance_started = self.clock()
        compliance = self._compliance(findings)
        self.telemetry.compliance_duration.record(self.clock() - compliance_started)
        trend_started = self.clock()
        trends = self.trends_engine.calculate(self.history, now=self.now())
        self.telemetry.trend_latency.record(self.clock() - trend_started)
        return (
            findings,
            compliance,
            trends,
            self.summary_engine.exposure(findings),
        )

    @staticmethod
    def _metadata(count: int, returned: int) -> dict[str, Any]:
        return {
            "count": count,
            "returned": returned,
            "truncated": returned < count,
        }

    def _bounded_public(self, value: Any) -> Any:
        def annotate(item: Any) -> Any:
            if isinstance(item, dict):
                result = {key: annotate(child) for key, child in item.items()}
                for key, child in item.items():
                    metadata_key = f"{key}_metadata"
                    if (
                        isinstance(child, (list, tuple))
                        and len(child) > self.max_output_items
                        and metadata_key not in result
                    ):
                        result[metadata_key] = self._metadata(
                            len(child), min(len(child), self.max_output_items)
                        )
                return result
            if isinstance(item, (list, tuple)):
                return [annotate(child) for child in item]
            return item

        def bounded(item: Any) -> Any:
            if isinstance(item, dict):
                return {key: bounded(child) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [bounded(child) for child in item[: self.max_output_items]]
            if isinstance(item, str):
                return IncidentIntelligence._safe_text(item)
            return item

        result = bounded(annotate(value))
        if (
            len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
            > self.max_serialized_bytes
        ):
            raise ValueError("Patch intelligence output exceeds configured bound")
        return result

    def _findings(self) -> list[dict[str, Any]]:
        started = self.clock()
        findings = self.analyzer.analyze(
            assessments=self.assessments,
            installations=self.installations,
            security_findings=self.security_findings,
            advisor_recommendations=self.advisor_recommendations,
            policies=[asdict(item) for item in self.policies],
            now=self.now(),
        )
        self.telemetry.risk_duration.record(self.clock() - started)
        return findings

    def _compliance(self, findings: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(findings)
        attempted = sum(int(item.get("attempted_update_count") or 0) for item in findings)
        successful = sum(int(item.get("successful_update_count") or 0) for item in findings)
        failed = sum(int(item.get("failed_update_count") or 0) for item in findings)
        overall = {
            "resource_count": count,
            "unpatched_resource_count": sum(bool(item["unpatched"]) for item in findings),
            "missing_critical_updates": sum(int(item["missing_critical_updates"]) for item in findings),
            "missing_security_updates": sum(int(item["missing_security_updates"]) for item in findings),
            "compliance_score": round(
                sum(int(item["compliance_score"]) for item in findings) / count, 2
            )
            if count
            else 0.0,
            "patch_success_percent": round(100 * successful / attempted, 2)
            if attempted
            else 0.0,
            "patch_failure_percent": round(100 * failed / attempted, 2)
            if attempted
            else 0.0,
            "risk_level": self._risk_level(
                max((int(item.get("risk_score") or 0) for item in findings), default=0)
            ),
        }
        resources = [
            {
                "resource": item["resource"],
                "compliance_score": item["compliance_score"],
                "patch_success_percent": item["patch_success_percent"],
                "patch_failure_percent": item["patch_failure_percent"],
                "missing_critical_updates": item["missing_critical_updates"],
                "missing_security_updates": item["missing_security_updates"],
                "unpatched": item["unpatched"],
                "risk_level": item["risk_level"],
            }
            for item in findings
        ]
        return {
            "overall": overall,
            **self.compliance_engine.rollups(findings),
            "resources": resources,
        }

    @staticmethod
    def _risk_level(score: int) -> str:
        return (
            "Critical"
            if score >= 75
            else "High"
            if score >= 50
            else "Moderate"
            if score >= 25
            else "Low"
        )

    def _record_freshness(self) -> None:
        observed = datetime.fromisoformat(self.freshness_value)
        current = self.now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        age = max((current.astimezone(UTC) - observed).total_seconds(), 0)
        self.telemetry.freshness.record(age)

    @staticmethod
    def _normalize_timestamp(value: Any, field_name: str) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Patch intelligence {field_name} timestamp is invalid") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    @classmethod
    def _normalize_evidence_timestamps(
        cls,
        rows: list[dict[str, Any]],
        fields: tuple[str, ...],
        collection: str,
    ) -> list[dict[str, Any]]:
        normalized = []
        for source in rows:
            row = dict(source)
            for field_name in fields:
                if row.get(field_name):
                    row[field_name] = cls._normalize_timestamp(
                        row[field_name], f"{collection}.{field_name}"
                    )
            normalized.append(row)
        return normalized

    def _validate_numeric_evidence(self) -> None:
        specifications = (
            (
                self.assessments,
                (
                    "available_updates",
                    "missing_critical_updates",
                    "missing_security_updates",
                ),
                None,
            ),
            (self.installations, ("age_days",), None),
            (
                self.history,
                (
                    "missing_critical_updates",
                    "missing_security_updates",
                ),
                None,
            ),
            (self.history, ("risk_score",), 100),
        )
        for rows, fields, maximum in specifications:
            for row in rows:
                for field_name in fields:
                    value = row.get(field_name)
                    if value is None:
                        continue
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 0
                        or (maximum is not None and value > maximum)
                    ):
                        raise ValueError(
                            f"Patch {field_name} must be a non-negative integer"
                        )

    def _reject_duplicate_installations(self) -> None:
        identities = set()
        for row in self.installations:
            resource_identity = canonical_resource_key(row.get("resource_key")) or " ".join(
                str(row.get("resource") or "").strip().casefold().split()
            )
            if not resource_identity:
                raise ValueError("Patch installation requires resource identity")
            if not str(row.get("update_id") or "").strip():
                raise ValueError("Patch installation requires update_id")
            if not str(row.get("installed_at") or "").strip():
                raise ValueError("Patch installation requires installed_at")
            identity = (
                resource_identity,
                str(row.get("update_id") or "").strip().casefold(),
                str(row.get("installed_at") or ""),
            )
            if identity in identities:
                raise ValueError("Duplicate patch installation evidence")
            identities.add(identity)

    def _reject_duplicate_history(self) -> None:
        identities = set()
        for row in self.history:
            resource_identity = canonical_resource_key(row.get("resource_key")) or " ".join(
                str(row.get("resource") or "").strip().casefold().split()
            )
            identity = (resource_identity, str(row.get("observed_at") or ""))
            if not all(identity):
                continue
            if identity in identities:
                raise ValueError("Duplicate patch history evidence")
            identities.add(identity)

    @staticmethod
    def _strict_nonnegative_int(value: Any, field_name: str) -> int:
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Patch {field_name} must be a non-negative integer")
        return value

    @staticmethod
    def _strict_optional_score(value: Any) -> int | None:
        if value is None:
            return None
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 100
        ):
            raise ValueError("Patch risk_score must be an integer from 0 to 100")
        return value

    @staticmethod
    def _reject_future_observations(
        freshness: datetime,
        collections: tuple[
            tuple[list[dict[str, Any]], tuple[str, ...]], ...
        ],
    ) -> None:
        for rows, fields in collections:
            for row in rows:
                for field_name in fields:
                    if not row.get(field_name):
                        continue
                    observed = datetime.fromisoformat(str(row[field_name]))
                    if observed > freshness:
                        raise ValueError(
                            f"Patch evidence {field_name} is newer than snapshot freshness"
                        )

    @staticmethod
    def _risk_projection(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "resource": item["resource"],
            "application": item["application"],
            "business_service": item["business_service"],
            "risk_score": item["risk_score"],
            "risk_level": item["risk_level"],
            "risk_justification": item["risk_justification"],
        }

    @staticmethod
    def _category(value: Any) -> UpdateCategory:
        normalized = str(value or "Other").casefold()
        for category in UpdateCategory:
            if category.value.casefold() == normalized:
                return category
        return UpdateCategory.OTHER

    @staticmethod
    def _first_name(value: Any) -> str:
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return str(value[0].get("name") or "Unknown")
        return "Unknown"
