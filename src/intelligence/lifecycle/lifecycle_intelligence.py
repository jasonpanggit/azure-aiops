from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from opentelemetry import metrics

from intelligence.incident.incident_intelligence import IncidentIntelligence

from .eol_catalog import EOLCatalog
from .lifecycle_analyzer import LifecycleAnalyzer
from .lifecycle_context_builder import LifecycleContextBuilder, canonical_resource_key
from .lifecycle_summary_engine import LifecycleSummaryEngine
from .lifecycle_trend_engine import LifecycleTrendEngine


class LifecycleTelemetry:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("hermes.lifecycle_intelligence", "0.1.0")
        self.analysis_duration = meter.create_histogram(
            "lifecycle.analysis.duration", unit="s"
        )
        self.catalog_freshness = meter.create_histogram(
            "lifecycle.catalog.freshness", unit="s"
        )
        self.risk_latency = meter.create_histogram(
            "lifecycle.risk.calculation.latency", unit="s"
        )
        self.business_impact_latency = meter.create_histogram(
            "lifecycle.business_impact.correlation.latency", unit="s"
        )
        self.executive_report_duration = meter.create_histogram(
            "lifecycle.executive_report.generation.duration", unit="s"
        )
        self.risk_calculation_latency = self.risk_latency
        self.impact_correlation_latency = self.business_impact_latency
        self.report_generation_duration = self.executive_report_duration


class LifecycleIntelligence:
    """Read-only business-aware lifecycle intelligence over semantic projections."""

    QUERY_NAMES: ClassVar[set[str]] = {
        "show eol systems",
        "show high risk systems",
        "show modernization candidates",
        "show business services at risk",
        "show lifecycle trends",
        "show lifecycle debt",
    }

    def __init__(
        self,
        *,
        resources: list[dict[str, Any]],
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
        freshness: str,
        catalog_last_updated: str = "",
        approaching_months: int = 24,
        near_months: int = 12,
        critical_months: int = 6,
        max_resources: int = 5000,
        max_history_rows: int = 50000,
        max_catalog_rows: int = 5000,
        max_output_items: int = 100,
        max_serialized_bytes: int = 1_000_000,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
        telemetry: LifecycleTelemetry | None = None,
    ) -> None:
        bounds = (max_resources, max_history_rows, max_catalog_rows, max_output_items)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in bounds
        ):
            raise ValueError("Lifecycle bounds must be positive integers")
        if (
            isinstance(max_serialized_bytes, bool)
            or not isinstance(max_serialized_bytes, int)
            or max_serialized_bytes < 1024
        ):
            raise ValueError("Lifecycle serialized output bound must be at least 1024 bytes")
        if len(history) > max_history_rows:
            raise ValueError("Lifecycle history exceeds configured bound")
        if len(catalog) > max_catalog_rows:
            raise ValueError("Lifecycle catalog exceeds configured bound")
        self.now = now
        self.clock = clock
        self.telemetry = telemetry or LifecycleTelemetry()
        self.max_output_items = max_output_items
        self.max_serialized_bytes = max_serialized_bytes
        self.freshness = self._timestamp(freshness, "freshness")
        current = self._current_time()
        if datetime.fromisoformat(self.freshness) > current:
            raise ValueError("Lifecycle freshness cannot be in the future")
        self.catalog = EOLCatalog.from_rows(
            catalog,
            approaching_months=approaching_months,
            near_months=near_months,
            critical_months=critical_months,
        )
        if (
            catalog_last_updated
            and str(catalog_last_updated).split("T", 1)[0] != self.catalog.freshness
        ):
            raise ValueError("Catalog freshness does not match authoritative entries")
        if self.catalog.freshness and datetime.fromisoformat(
            self.catalog.freshness
        ).replace(tzinfo=UTC) > current:
            raise ValueError("Lifecycle catalog freshness cannot be in the future")
        self.history = self._history(history, freshness=self.freshness)
        self.context_builder = LifecycleContextBuilder(
            resources, max_resources=max_resources
        )
        self.analyzer = LifecycleAnalyzer(
            self.catalog,
            self.context_builder,
            clock=self.clock,
            telemetry=self.telemetry,
        )
        self.trend_engine = LifecycleTrendEngine()
        self.summary_engine = LifecycleSummaryEngine()

    @classmethod
    def from_snapshot(cls, **snapshot: Any) -> LifecycleIntelligence:
        return cls(**snapshot)

    @classmethod
    def from_semantic_engine(
        cls,
        semantic_engine,
        *,
        inventory: list[dict[str, Any]],
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
        patch_posture: dict[str, dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LifecycleIntelligence:
        """Build lifecycle context through public Semantic Engine APIs only."""
        max_resources = kwargs.get("max_resources", 5000)
        if (
            isinstance(max_resources, bool)
            or not isinstance(max_resources, int)
            or max_resources < 1
        ):
            raise ValueError("Lifecycle max_resources must be a positive integer")
        if not isinstance(inventory, list):
            raise TypeError("Lifecycle inventory must be a list")
        if len(inventory) > max_resources:
            raise ValueError("Lifecycle resource snapshot exceeds configured bound")
        if any(not isinstance(row, dict) for row in inventory):
            raise TypeError("Lifecycle inventory rows must be mappings")
        max_catalog_rows = kwargs.get("max_catalog_rows", 5000)
        max_history_rows = kwargs.get("max_history_rows", 50000)
        for name, value in (
            ("max_catalog_rows", max_catalog_rows),
            ("max_history_rows", max_history_rows),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"Lifecycle {name} must be a positive integer")
        if not isinstance(catalog, list) or any(not isinstance(row, dict) for row in catalog):
            raise TypeError("Lifecycle catalog must be a list of mappings")
        if len(catalog) > max_catalog_rows:
            raise ValueError("Lifecycle catalog exceeds configured bound")
        if not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
            raise TypeError("Lifecycle history must be a list of mappings")
        if len(history) > max_history_rows:
            raise ValueError("Lifecycle history exceeds configured bound")
        if patch_posture is not None and not isinstance(patch_posture, dict):
            raise TypeError("Lifecycle patch posture must be a mapping")
        semantic_clock = kwargs.get("clock", time.monotonic)
        semantic_telemetry = kwargs.get("telemetry")
        if semantic_telemetry is None:
            semantic_telemetry = LifecycleTelemetry()
            kwargs["telemetry"] = semantic_telemetry
        posture = {}
        if len(patch_posture or {}) > max_resources:
            raise ValueError("Lifecycle patch posture exceeds configured bound")
        for key, value in (patch_posture or {}).items():
            if not isinstance(value, dict):
                raise TypeError("Lifecycle patch posture values must be mappings")
            canonical = canonical_resource_key(key)
            if not canonical or canonical in posture:
                raise ValueError("Lifecycle patch posture identities must be unique")
            score = value.get("compliance_score")
            if score is not None and (
                isinstance(score, bool)
                or not isinstance(score, int)
                or not 0 <= score <= 100
            ):
                raise ValueError(
                    "Patch posture compliance_score must be an integer from 0 to 100"
                )
            posture[canonical] = dict(value)
        catalog_channels = {
            (
                " ".join(str(row.get("product") or "").casefold().split()),
                " ".join(str(row.get("version") or "").casefold().split()),
            ): str(row.get("default_support_channel") or "mainstream")
            for row in catalog
        }
        resources: list[dict[str, Any]] = []
        for row in inventory:
            resource_key = canonical_resource_key(row.get("resource_id"))
            name = str(row.get("name") or "")
            entity_type = str(row.get("entity_type") or "Resource")
            if not resource_key or not name:
                raise ValueError("Lifecycle inventory rows require resource identity and name")
            impact_started = semantic_clock()
            try:
                context = semantic_engine.get_resource_context(
                    resource_key, subject_type=entity_type
                )
            except LookupError:
                continue
            semantic_telemetry.business_impact_latency.record(
                semantic_clock() - impact_started
            )
            if not isinstance(context, dict):
                raise TypeError("Lifecycle Semantic context must be a mapping")
            raw_sections = context.get("sections")
            if raw_sections is None:
                sections = {}
            elif not isinstance(raw_sections, dict):
                raise TypeError("Lifecycle Semantic sections must be a mapping")
            else:
                sections = raw_sections
            for section_name in (
                "applications",
                "business_services",
                "ownership",
                "support_teams",
            ):
                if section_name in sections and not isinstance(
                    sections[section_name], list
                ):
                    raise TypeError(f"Lifecycle Semantic {section_name} must be a list")
                if section_name in sections and any(
                    not isinstance(item, dict) for item in sections[section_name]
                ):
                    raise TypeError(
                        f"Lifecycle Semantic {section_name} members must be mappings"
                    )
            raw_classification = sections.get("operational_classification")
            if raw_classification is None:
                classification = {}
            elif not isinstance(raw_classification, dict):
                raise TypeError("Lifecycle operational classification must be a mapping")
            else:
                classification = raw_classification
            product, version = cls._technology_identity(row)
            raw_compliance = sections.get("compliance")
            if raw_compliance is None:
                compliance = {}
            elif not isinstance(raw_compliance, dict):
                raise TypeError("Lifecycle compliance context must be a mapping")
            else:
                compliance = raw_compliance
            fallback_patch_score = cls.semantic_patch_score(compliance.get("status"))
            internet_exposed = cls._internet_exposure(row)
            posture_score = None
            if resource_key in posture and "compliance_score" in posture[resource_key]:
                posture_score = posture[resource_key]["compliance_score"]

            resources.append(
                {
                    "resource_key": resource_key,
                    "name": name,
                    "entity_type": entity_type,
                    "subscription": str(
                        row.get("subscription")
                        or row.get("subscription_id")
                        or "Unknown"
                    ),
                    "region": str(
                        row.get("region") or row.get("location") or "Unknown"
                    ),
                    "product": product,
                    "version": version,
                    "support_channel": str(
                        row.get("support_channel")
                        or cls._resource_setting(row, "supportchannel")
                        or catalog_channels.get(
                            (
                                " ".join(product.casefold().split()),
                                " ".join(version.casefold().split()),
                            ),
                            "mainstream",
                        )
                    ),
                    "application": cls._first_name(sections.get("applications")),
                    "business_service": cls._first_name(
                        sections.get("business_services")
                    ),
                    "owner": cls._first_name(sections.get("ownership")),
                    "support_team": cls._first_name(sections.get("support_teams")),
                    "environment": str(
                        classification.get("environment") or "Unknown"
                    ),
                    "business_criticality": str(
                        classification.get("criticality") or "Unknown"
                    ),
                    "ownership_coverage": bool(sections.get("ownership")),
                    "internet_exposed": internet_exposed,
                    "patch_compliance_score": (
                        (
                            posture_score
                        )
                        if resource_key in posture
                        and "compliance_score" in posture[resource_key]
                        else fallback_patch_score
                    ),
                }
            )
        return cls(
            resources=resources,
            catalog=catalog,
            history=history,
            freshness=str(semantic_engine.freshness),
            catalog_last_updated=max(
                (str(row.get("last_update_date") or "") for row in catalog),
                default="",
            ),
            **kwargs,
        )

    def analyze(self) -> dict[str, Any]:
        started = self.clock()
        findings = self.analyzer.analyze(now=self._current_time())
        exposure = self.summary_engine.exposure(findings)
        trends = self.trend_engine.calculate(self.history, now=self._current_time())
        result = {
            "findings": findings,
            "exposure": exposure,
            "trends": trends,
            "catalog_freshness": self.catalog.freshness,
            "freshness": self.freshness,
            "read_only": True,
            "collection_metadata": self._metadata(
                len(findings), min(len(findings), self.max_output_items)
            ),
        }
        self.telemetry.analysis_duration.record(self.clock() - started)
        self._record_catalog_freshness()
        return self._bounded_public(result)

    def _history_findings(self) -> list[dict[str, Any]]:
        """Internal Fabric projection retaining canonical resource identity."""
        return self.analyzer.analyze(
            now=self._current_time(), include_internal_identity=True
        )

    def internal_resource_posture(self) -> dict[str, dict[str, Any]]:
        """Canonical-key lifecycle posture for governed peer intelligence layers."""
        return {
            str(item.get("_resource_key") or "").casefold(): {
                "status": str(item.get("lifecycle_status") or "Unknown"),
                "risk_score": int(item.get("risk_score") or 0),
                "observed_at": self.freshness,
                "eol": str(item.get("lifecycle_status") or "").casefold()
                == "eol",
                "modernization_candidate": int(item.get("risk_score") or 0) >= 50,
            }
            for item in self._history_findings()
            if item.get("_resource_key")
        }

    def query(self, question: str) -> dict[str, Any]:
        normalized = " ".join(question.strip().rstrip(".?!").casefold().split())
        if normalized not in self.QUERY_NAMES:
            raise ValueError("Unsupported lifecycle intelligence query")
        findings = self.analyzer.analyze(now=self._current_time())
        exposure = self.summary_engine.exposure(findings)
        trends = self.trend_engine.calculate(self.history, now=self._current_time())
        if normalized == "show eol systems":
            payload: Any = [item for item in findings if item["lifecycle_status"] == "EOL"]
        elif normalized == "show high risk systems":
            payload = [item for item in findings if item["risk_score"] >= 50]
        elif normalized == "show modernization candidates":
            payload = [
                item
                for item in findings
                if item["modernization_recommendation"]["priority"]
                in {"Priority 1", "Priority 2", "Priority 3"}
            ]
        elif normalized == "show business services at risk":
            payload = [
                item
                for item in exposure["by_business_service"]
                if item["max_risk_score"] >= 50
            ]
        elif normalized == "show lifecycle trends":
            payload = trends
        else:
            payload = exposure
        count = len(payload) if isinstance(payload, list) else 1
        response = {
            "query": normalized,
            "result": payload,
            "collection_metadata": self._metadata(
                count, min(count, self.max_output_items)
            ),
            "freshness": self.freshness,
            "read_only": True,
        }
        if isinstance(payload, dict):
            response["nested_collection_metadata"] = self._nested_metadata(payload)
        return self._bounded_public(response)

    def report(self, report_type: str) -> dict[str, Any]:
        started = self.clock()
        findings = self.analyzer.analyze(now=self._current_time())
        exposure = self.summary_engine.exposure(findings)
        trends = self.trend_engine.calculate(self.history, now=self._current_time())
        result = self.summary_engine.generate(
            report_type,
            findings=findings,
            exposure=exposure,
            trends=trends,
            freshness=self.freshness,
        )
        result["collection_metadata"] = self._nested_metadata(
            {"findings": findings, **exposure}
        )
        self.telemetry.executive_report_duration.record(self.clock() - started)
        return self._bounded_public(result)

    def _record_catalog_freshness(self) -> None:
        if not self.catalog.freshness:
            return
        updated = datetime.fromisoformat(self.catalog.freshness).replace(tzinfo=UTC)
        age = max((self._current_time() - updated).total_seconds(), 0)
        self.telemetry.catalog_freshness.record(age)

    def _current_time(self) -> datetime:
        value = self.now()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def semantic_patch_score(status: Any) -> int | None:
        normalized = str(status or "").strip().casefold()
        if normalized in {"compliant", "succeeded", "success", "completed"}:
            return 100
        if normalized in {"noncompliant", "failed", "failure", "error"}:
            return 0
        return None

    @staticmethod
    def _internet_exposure(row: dict[str, Any]) -> bool:
        if "internet_exposed" in row:
            value = row["internet_exposed"]
            if not isinstance(value, bool):
                raise TypeError("Lifecycle internet_exposed must be boolean")
            return value
        setting = LifecycleIntelligence._resource_setting(
            row, "internetexposed"
        ).strip().casefold()
        if not setting:
            return False
        if setting in {"true", "yes", "1"}:
            return True
        if setting in {"false", "no", "0"}:
            return False
        raise ValueError("Lifecycle internet exposure tag must be boolean")

    @staticmethod
    def _metadata(count: int, returned: int) -> dict[str, Any]:
        return {
            "count": count,
            "returned": returned,
            "truncated": returned < count,
        }

    def _nested_metadata(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._metadata(len(items), min(len(items), self.max_output_items))
            for key, items in value.items()
            if isinstance(items, list)
        }

    def _bounded_public(self, value: Any) -> Any:
        def bounded(item: Any) -> Any:
            if isinstance(item, dict):
                return {key: bounded(child) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [bounded(child) for child in item[: self.max_output_items]]
            if isinstance(item, str):
                return IncidentIntelligence._safe_text(item)
            return item

        result = bounded(value)
        if (
            len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
            > self.max_serialized_bytes
        ):
            raise ValueError("Lifecycle intelligence output exceeds configured bound")
        return result

    @staticmethod
    def _timestamp(value: Any, field_name: str) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Lifecycle {field_name} must be an ISO timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def _history(
        cls, rows: list[dict[str, Any]], *, freshness: str
    ) -> list[dict[str, Any]]:
        normalized = []
        identities: set[tuple[str, str, str]] = set()
        snapshot_time = datetime.fromisoformat(freshness)
        for source in rows:
            if not isinstance(source, dict):
                raise TypeError("Lifecycle history rows must be mappings")
            row = dict(source)
            resource_key = canonical_resource_key(row.get("resource_key"))
            ingestion_run_id = str(row.get("ingestion_run_id") or "").strip()
            if not resource_key or not ingestion_run_id:
                raise ValueError(
                    "Lifecycle history requires resource_key and ingestion_run_id"
                )
            row["resource_key"] = resource_key
            row["ingestion_run_id"] = ingestion_run_id
            row["observed_at"] = cls._timestamp(
                row.get("observed_at"), "history.observed_at"
            )
            if datetime.fromisoformat(row["observed_at"]) > snapshot_time:
                raise ValueError("Lifecycle history observation exceeds snapshot freshness")
            risk_score = row.get("risk_score")
            if risk_score is not None and (
                isinstance(risk_score, bool)
                or not isinstance(risk_score, int)
                or not 0 <= risk_score <= 100
            ):
                raise ValueError("Lifecycle history risk_score must be an integer from 0 to 100")
            status = str(row.get("lifecycle_status") or "Unknown")
            if status not in {
                "Supported",
                "Approaching EOL",
                "Near EOL",
                "Critical",
                "EOL",
                "Expired",
                "Unknown",
            }:
                raise ValueError("Lifecycle history lifecycle_status is invalid")
            identity = (
                resource_key,
                row["observed_at"],
                ingestion_run_id,
            )
            if identity in identities:
                raise ValueError("Duplicate lifecycle history observation")
            identities.add(identity)
            normalized.append(row)
        return normalized

    @staticmethod
    def _first_name(value: Any) -> str:
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return str(value[0].get("name") or "Unknown")
        return "Unknown"

    @classmethod
    def _technology_identity(cls, row: dict[str, Any]) -> tuple[str, str]:
        product = str(
            row.get("lifecycle_product")
            or cls._resource_setting(row, "lifecycleproduct")
            or row.get("os_name")
            or ""
        ).strip()
        version = str(
            row.get("lifecycle_version")
            or cls._resource_setting(row, "lifecycleversion")
            or row.get("os_version")
            or ""
        ).strip()
        resource_type = str(row.get("resource_type") or "").casefold()
        payload = cls._payload(row)
        properties = payload.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        if "managedclusters" in resource_type:
            product = product or "Kubernetes"
            version = version or str(
                row.get("kubernetes_version")
                or properties.get("kubernetesVersion")
                or ""
            )
        elif "microsoft.sql/servers" in resource_type:
            product = product or "SQL Server"
            version = version or str(
                row.get("sql_version") or properties.get("version") or ""
            )
        combined = f"{product} {version}"
        windows = re.search(
            r"Windows Server\s+(2012 R2|2016|2019|2022|2025)",
            combined,
            re.IGNORECASE,
        )
        if windows:
            return "Windows Server", windows.group(1)
        if "ubuntu" in combined.casefold():
            release = re.search(r"\b(20\.04|22\.04|24\.04)\b", combined)
            if release:
                return "Ubuntu", f"{release.group(1)} LTS"
        if any(marker in combined.casefold() for marker in ("red hat", "rhel")):
            release = re.search(r"\b([789])(?:\.\d+)?\b", version)
            if release:
                return "Red Hat Enterprise Linux", release.group(1)
        if "debian" in combined.casefold():
            release = re.search(r"\b(11|12)\b", version)
            if release:
                return "Debian", release.group(1)
        if "azure local" in combined.casefold():
            release = re.search(r"\b(2[3-9]\d{2})\b", combined)
            if release:
                return "Azure Local", release.group(1)
        if "azure stack hci" in combined.casefold():
            release = re.search(r"\b(22H2)\b", combined, re.IGNORECASE)
            if release:
                return "Azure Stack HCI", release.group(1).upper()
        if product.casefold() == "kubernetes":
            release = re.search(r"\b(1\.\d+)\b", version)
            if release:
                return "Kubernetes", release.group(1)
        return product or "Unknown", version or "Unknown"

    @classmethod
    def _resource_setting(cls, row: dict[str, Any], setting: str) -> str:
        payload = cls._payload(row)
        tags = payload.get("tags") or {}
        if not isinstance(tags, dict):
            return ""
        return next(
            (
                str(value)
                for key, value in tags.items()
                if str(key).replace("_", "").casefold() == setting.casefold()
            ),
            "",
        )

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        try:
            parsed = json.loads(str(row.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        nested = parsed.get("payload_json")
        if nested:
            try:
                decoded = json.loads(str(nested))
                return decoded if isinstance(decoded, dict) else parsed
            except json.JSONDecodeError:
                return parsed
        return parsed
