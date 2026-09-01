from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa
import yaml

from ontology.relationship_builder import ASSET_TYPES

from .schema_registry import schema_for

# Rules that always block publication when non-zero, regardless of
# environment/threshold config. Ownership/tag coverage is intentionally
# excluded here -- it is governed by `DataQualityValidator`'s configurable
# per-environment warn/block threshold instead (MED-06).
_BLOCKING_RULES = (
    "required_fields",
    "schema_validation",
    "duplicates",
    "subscription_consistency",
    "orphan_relationships",
)

# Safe-by-default: an unconfigured environment never blocks on ownership/tag
# gaps -- it only ever counts and reports them. Production environments are
# expected to opt into `mode: block` explicitly via fabric.config.yaml.
DEFAULT_OWNERSHIP_TAG_THRESHOLDS: dict[str, Any] = {
    "mode": "warn",
    "max_missing_ownership_pct": 100.0,
    "max_missing_tag_pct": 100.0,
}


@dataclass(frozen=True)
class QualityReport:
    table_name: str
    rows_checked: int
    rule_counts: dict[str, int] = field(default_factory=dict)
    failures: tuple[dict[str, Any], ...] = ()
    # Which rule names count toward `failed_records`/`passed`. Always includes
    # the hard rules (required_fields, schema_validation, duplicates,
    # subscription_consistency, orphan_relationships). `ownership_coverage`/
    # `tag_coverage` are added only when the validator's configured mode is
    # `block` and the missing-percentage threshold for that specific rule was
    # exceeded -- in `warn` mode (or under-threshold in `block` mode) those
    # rule's failure entries stay visible in `failures`/`rule_counts` for
    # reporting, but never flip `passed`/count toward `failed_records`. This
    # keeps ownership/tag gaps "counted and reported, never silently dropped"
    # (MED-06) without breaking every other consumer of `failed_records` that
    # predates this rule and expects it to mean "hard-blocking".
    blocking_rules: frozenset[str] = field(default_factory=lambda: frozenset(_BLOCKING_RULES))

    @property
    def failed_records(self) -> int:
        return len(
            {
                int(failure["row_index"])
                for failure in self.failures
                if failure["rule"] in self.blocking_rules
            }
        )

    @property
    def passed(self) -> bool:
        return self.failed_records == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "rows_checked": self.rows_checked,
            "failed_records": self.failed_records,
            "passed": self.passed,
            "rule_counts": self.rule_counts,
            "failures": list(self.failures),
        }


class DataQualityValidator:
    REQUIRED_FIELDS = (
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
    )

    def __init__(
        self,
        *,
        environment: str = "dev",
        ownership_tag_thresholds: Mapping[str, Any] | None = None,
    ) -> None:
        self.environment = environment
        merged = dict(DEFAULT_OWNERSHIP_TAG_THRESHOLDS)
        if ownership_tag_thresholds:
            merged.update(ownership_tag_thresholds)
        self.ownership_tag_thresholds = merged

    @classmethod
    def from_config(
        cls,
        environment: str,
        *,
        config_path: str | Path = "fabric.config.yaml",
    ) -> "DataQualityValidator":
        """Build a validator whose ownership/tag thresholds come from
        `fabric.config.yaml`'s `fabric.data_quality.ownership_tag_thresholds.<environment>`
        section. Missing file/section/keys fall back to the safe
        (never-block) default -- config drives the rule, absence of config
        never silently blocks publication.
        """
        thresholds: Mapping[str, Any] | None = None
        path = Path(config_path)
        if path.is_file():
            try:
                payload = yaml.safe_load(path.read_text()) or {}
            except yaml.YAMLError:
                payload = {}
            section = (
                (payload.get("fabric") or {})
                .get("data_quality", {})
                .get("ownership_tag_thresholds", {})
            )
            env_thresholds = section.get(environment)
            if isinstance(env_thresholds, Mapping):
                thresholds = env_thresholds
        return cls(environment=environment, ownership_tag_thresholds=thresholds)

    def validate_table(
        self,
        table_name: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> QualityReport:
        failures: list[dict[str, Any]] = []
        schema = schema_for(table_name)
        counts = {
            "required_fields": 0,
            "schema_validation": 0,
            "duplicates": 0,
            "subscription_consistency": 0,
            "ownership_coverage": 0,
            "tag_coverage": 0,
        }
        seen: set[str] = set()
        for index, row in enumerate(rows):
            missing = [field for field in self.REQUIRED_FIELDS if row.get(field) in (None, "")]
            if missing:
                counts["required_fields"] += 1
                failures.append(_failure(index, "required_fields", ",".join(missing)))
            key = str(row.get("resource_id") or "").casefold()
            if key and key in seen:
                counts["duplicates"] += 1
                failures.append(_failure(index, "duplicates", key))
            seen.add(key)

            schema_error = _schema_error(row, schema)
            if schema_error:
                counts["schema_validation"] += 1
                failures.append(_failure(index, "schema_validation", schema_error))

            subscription = str(row.get("subscription_id") or "")
            resource_id = str(row.get("resource_id") or "")
            match = re.search(r"/subscriptions/([^/]+)", resource_id, flags=re.IGNORECASE)
            if match and subscription and match.group(1).casefold() != subscription.casefold():
                counts["subscription_consistency"] += 1
                failures.append(
                    _failure(index, "subscription_consistency", f"{subscription}:{match.group(1)}")
                )

            # Ownership/tag coverage only makes sense for resource-like
            # assets (the entities MED-06's live baseline counts as
            # "84 missing ownership"/"52 missing tags") -- relationships and
            # non-asset entities have no ownership/tagging concept of their
            # own and are never flagged.
            if str(row.get("entity_type") or "") in ASSET_TYPES:
                payload = _parse_payload(row.get("payload_json"))
                owner = payload.get("owner")
                if not (isinstance(owner, str) and owner.strip()):
                    counts["ownership_coverage"] += 1
                    failures.append(_failure(index, "ownership_coverage", "missing owner"))
                tags = payload.get("tags")
                if not (isinstance(tags, dict) and tags):
                    counts["tag_coverage"] += 1
                    failures.append(_failure(index, "tag_coverage", "missing tags"))

        blocking = _blocking_rules(counts, len(rows), self.ownership_tag_thresholds)
        return QualityReport(
            table_name=table_name,
            rows_checked=len(rows),
            rule_counts=counts,
            failures=tuple(failures),
            blocking_rules=blocking,
        )

    def validate_relationships(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        entity_ids: set[str],
        table_name: str = "silver_resource_relationships",
    ) -> QualityReport:
        base = self.validate_table(table_name, rows)
        failures = list(base.failures)
        counts = dict(base.rule_counts)
        counts["orphan_relationships"] = 0
        normalized_entities = {value.casefold() for value in entity_ids}
        for index, row in enumerate(rows):
            subject = str(row.get("subject_id") or "").casefold()
            object_id = str(row.get("object_id") or "").casefold()
            if subject not in normalized_entities or object_id not in normalized_entities:
                counts["orphan_relationships"] += 1
                failures.append(
                    _failure(index, "orphan_relationships", f"{subject}->{object_id}")
                )
        blocking = _blocking_rules(counts, len(rows), self.ownership_tag_thresholds)
        return QualityReport(
            table_name=table_name,
            rows_checked=len(rows),
            rule_counts=counts,
            failures=tuple(failures),
            blocking_rules=blocking,
        )


def _failure(index: int, rule: str, detail: str) -> dict[str, Any]:
    return {"row_index": index, "rule": rule, "detail": detail}


def _parse_payload(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _blocking_rules(
    counts: Mapping[str, int],
    rows_checked: int,
    thresholds: Mapping[str, Any],
) -> frozenset[str]:
    rules = set(_BLOCKING_RULES)
    if thresholds.get("mode") == "block" and rows_checked:
        ownership_pct = counts.get("ownership_coverage", 0) / rows_checked * 100
        if ownership_pct > float(thresholds.get("max_missing_ownership_pct", 100.0)):
            rules.add("ownership_coverage")
        tag_pct = counts.get("tag_coverage", 0) / rows_checked * 100
        if tag_pct > float(thresholds.get("max_missing_tag_pct", 100.0)):
            rules.add("tag_coverage")
    return frozenset(rules)


def _schema_error(row: Mapping[str, Any], schema: pa.Schema) -> str:
    if set(row) != set(schema.names):
        missing = sorted(set(schema.names) - set(row))
        extra = sorted(set(row) - set(schema.names))
        return f"columns missing={missing} extra={extra}"
    for schema_field in schema:
        value = row.get(schema_field.name)
        if value is None:
            if not schema_field.nullable:
                return f"{schema_field.name}:null"
            continue
        if pa.types.is_string(schema_field.type) and not isinstance(value, str):
            return f"{schema_field.name}:expected string"
        if pa.types.is_integer(schema_field.type) and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            return f"{schema_field.name}:expected non-negative integer"
        if pa.types.is_floating(schema_field.type) and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return f"{schema_field.name}:expected finite number"
        if schema_field.name == "confidence" and not 0 <= value <= 1:
            return "confidence:expected number from 0 to 1"
        if pa.types.is_boolean(schema_field.type) and not isinstance(value, bool):
            return f"{schema_field.name}:expected boolean"
    return ""
