"""Strict, immutable evaluation evidence for ontology release policy."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "1.0.0"
MAX_SLICE_METRICS = 512
MAX_THRESHOLDS = 512
MAX_CRITICAL_FAILURES = 64
MAX_ARTIFACT_REFERENCES = 32
MAX_SOURCE_EXPIRIES = 64
_SHA256_PATTERN = r"^[a-f0-9]{64}$"
_SCOPE_PATTERN = r"^scope-[a-f0-9]{16,64}$"
_SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
_ARTIFACT_PATTERN = r"^artifact:[a-z0-9][a-z0-9._:-]*$"


class EvaluationStatus(StrEnum):
    """Exact persisted-evidence status vocabulary."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"


class FrozenContract(BaseModel):
    """Reject coercion, mutation, and unknown evaluation fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class EvaluationLineage(FrozenContract):
    """Versions and hashes needed to reproduce an evaluation."""

    dataset_version: str = Field(min_length=1, max_length=128)
    dataset_hash: str = Field(pattern=_SHA256_PATTERN)
    prompt_version: str = Field(min_length=1, max_length=128)
    prompt_hash: str = Field(pattern=_SHA256_PATTERN)
    schema_version: str = Field(min_length=1, max_length=128)
    schema_hash: str = Field(pattern=_SHA256_PATTERN)
    model_version: str = Field(min_length=1, max_length=128)
    model_hash: str = Field(pattern=_SHA256_PATTERN)
    agent_version: str = Field(min_length=1, max_length=128)
    agent_hash: str = Field(pattern=_SHA256_PATTERN)
    policy_version: str = Field(min_length=1, max_length=128)
    policy_hash: str = Field(pattern=_SHA256_PATTERN)


class SourceExpiry(FrozenContract):
    """Source-specific observation lifetime used by freshness classification."""

    source: str = Field(
        min_length=1,
        max_length=80,
        pattern=_SAFE_IDENTIFIER_PATTERN,
    )
    observed_at: datetime
    expires_at: datetime

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.expires_at <= self.observed_at:
            raise ValueError("source expiry must be after its observation")
        return self


class SliceMetric(FrozenContract):
    """One deterministic metric for an aggregate or governed slice."""

    metric: str = Field(min_length=1, max_length=80, pattern=_SAFE_IDENTIFIER_PATTERN)
    slice_key: str = Field(min_length=1, max_length=160, pattern=_SAFE_IDENTIFIER_PATTERN)
    numerator: int = Field(ge=0, le=1_000_000_000)
    denominator: int = Field(gt=0, le=1_000_000_000)
    value: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    critical: bool = False

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        expected = self.numerator / self.denominator
        if abs(self.value - expected) > 1e-12:
            raise ValueError("metric value must equal numerator / denominator")
        return self


class EvaluationThreshold(FrozenContract):
    """Server-owned minimum for one evaluated metric and slice."""

    metric: str = Field(min_length=1, max_length=80, pattern=_SAFE_IDENTIFIER_PATTERN)
    slice_key: str = Field(min_length=1, max_length=160, pattern=_SAFE_IDENTIFIER_PATTERN)
    minimum: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    critical: bool = False


class ArtifactReference(FrozenContract):
    """Opaque, sanitized reference to a separately governed artifact."""

    kind: Literal["dataset", "report", "trace", "manifest"]
    reference: str = Field(min_length=10, max_length=160, pattern=_ARTIFACT_PATTERN)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class EvaluationSnapshot(FrozenContract):
    """Content-addressed evaluation result persisted before policy consumption."""

    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    snapshot_id: str = Field(pattern=r"^EVS-[A-F0-9]{64}$")
    scope_key: str = Field(pattern=_SCOPE_PATTERN)
    scope_hash: str = Field(pattern=r"^[a-f0-9]{16,64}$")
    observed_at: datetime
    evaluated_at: datetime
    expires_at: datetime
    lineage: EvaluationLineage
    source_expiries: tuple[SourceExpiry, ...] = Field(
        min_length=1,
        max_length=MAX_SOURCE_EXPIRIES,
    )
    slice_metrics: tuple[SliceMetric, ...] = Field(
        min_length=1,
        max_length=MAX_SLICE_METRICS,
    )
    thresholds: tuple[EvaluationThreshold, ...] = Field(
        min_length=1,
        max_length=MAX_THRESHOLDS,
    )
    critical_failures: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_CRITICAL_FAILURES,
    )
    release_eligible: bool
    artifact_references: tuple[ArtifactReference, ...] = Field(
        default=(),
        max_length=MAX_ARTIFACT_REFERENCES,
    )

    @field_validator("observed_at", "evaluated_at", "expires_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("critical_failures")
    @classmethod
    def validate_failure_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("critical failure codes must be unique")
        for value in values:
            if not re.fullmatch(_SAFE_IDENTIFIER_PATTERN, value):
                raise ValueError("critical failure codes must be safe identifiers")
        return values

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.scope_hash != self.scope_key.removeprefix("scope-"):
            raise ValueError("scope hash must match the sanitized scope key")
        if not (self.observed_at <= self.evaluated_at < self.expires_at):
            raise ValueError(
                "snapshot times must satisfy observed_at <= evaluated_at < expires_at"
            )
        sources = [item.source.casefold() for item in self.source_expiries]
        if len(sources) != len(set(sources)):
            raise ValueError("source expiry names must be unique")
        metric_keys = [(item.metric, item.slice_key) for item in self.slice_metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("slice metric keys must be unique")
        threshold_keys = [(item.metric, item.slice_key) for item in self.thresholds]
        if len(threshold_keys) != len(set(threshold_keys)):
            raise ValueError("threshold keys must be unique")
        if self.release_eligible and self.critical_failures:
            raise ValueError("critical failures make release evidence ineligible")
        metrics = {
            (item.metric, item.slice_key): item.value for item in self.slice_metrics
        }
        failed_critical_threshold = any(
            item.critical
            and (
                (item.metric, item.slice_key) not in metrics
                or metrics[(item.metric, item.slice_key)] < item.minimum
            )
            for item in self.thresholds
        )
        if self.release_eligible and failed_critical_threshold:
            raise ValueError("release eligibility requires every critical threshold")
        expected_id = _snapshot_id(self._identity_payload())
        if self.snapshot_id != expected_id:
            raise ValueError("snapshot identity does not match its content")
        return self

    @property
    def effective_expires_at(self) -> datetime:
        """Earliest global or source-specific expiry."""
        return min(self.expires_at, *(item.expires_at for item in self.source_expiries))

    def creation_values(self) -> dict[str, object]:
        """Return typed values accepted by :meth:`create`, excluding derived fields."""
        return {
            "scope_key": self.scope_key,
            "observed_at": self.observed_at,
            "evaluated_at": self.evaluated_at,
            "expires_at": self.expires_at,
            "lineage": self.lineage,
            "source_expiries": self.source_expiries,
            "slice_metrics": self.slice_metrics,
            "thresholds": self.thresholds,
            "critical_failures": self.critical_failures,
            "release_eligible": self.release_eligible,
            "artifact_references": self.artifact_references,
        }

    def _identity_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", exclude={"snapshot_id"})
        return payload

    @classmethod
    def create(
        cls,
        *,
        scope_key: str,
        observed_at: datetime,
        evaluated_at: datetime,
        expires_at: datetime,
        lineage: EvaluationLineage,
        source_expiries: tuple[SourceExpiry, ...],
        slice_metrics: tuple[SliceMetric, ...],
        thresholds: tuple[EvaluationThreshold, ...],
        release_eligible: bool,
        critical_failures: tuple[str, ...] = (),
        artifact_references: tuple[ArtifactReference, ...] = (),
    ) -> Self:
        scope_hash = scope_key.removeprefix("scope-")
        values: dict[str, object] = {
            "contract_version": CONTRACT_VERSION,
            "scope_key": scope_key,
            "scope_hash": scope_hash,
            "observed_at": observed_at,
            "evaluated_at": evaluated_at,
            "expires_at": expires_at,
            "lineage": lineage,
            "source_expiries": source_expiries,
            "slice_metrics": slice_metrics,
            "thresholds": thresholds,
            "critical_failures": critical_failures,
            "release_eligible": release_eligible,
            "artifact_references": artifact_references,
        }
        values["snapshot_id"] = _snapshot_id(values)
        return cls.model_validate(values)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluation timestamps must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError("evaluation timestamps must use UTC")
    return value.astimezone(UTC)


def _snapshot_id(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return "EVS-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Cannot canonicalize {type(value).__name__}")


__all__ = [
    "ArtifactReference",
    "EvaluationLineage",
    "EvaluationSnapshot",
    "EvaluationStatus",
    "EvaluationThreshold",
    "SliceMetric",
    "SourceExpiry",
]
