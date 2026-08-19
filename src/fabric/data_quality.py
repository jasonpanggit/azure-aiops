from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from .schema_registry import schema_for


@dataclass(frozen=True)
class QualityReport:
    table_name: str
    rows_checked: int
    rule_counts: dict[str, int] = field(default_factory=dict)
    failures: tuple[dict[str, Any], ...] = ()

    @property
    def failed_records(self) -> int:
        return len({int(failure["row_index"]) for failure in self.failures})

    @property
    def passed(self) -> bool:
        return not self.failures

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
        return QualityReport(
            table_name=table_name,
            rows_checked=len(rows),
            rule_counts=counts,
            failures=tuple(failures),
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
        return QualityReport(
            table_name=table_name,
            rows_checked=len(rows),
            rule_counts=counts,
            failures=tuple(failures),
        )


def _failure(index: int, rule: str, detail: str) -> dict[str, Any]:
    return {"row_index": index, "rule": rule, "detail": detail}


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
