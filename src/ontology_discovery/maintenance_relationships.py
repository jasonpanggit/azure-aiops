"""Trusted proposal-decision to validator-complete canonical relationship rows."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ontology_discovery.maintenance_release import (
    MaintenanceDenied,
    MaintenanceRelease,
    digest,
)

STABLE_ID_PREFIX = "maintenance-rel://"


def stable_relationship_id(
    *, tenant_id: str, subscription_id: str, subject_id: str, predicate: str, object_id: str
) -> str:
    """Identity of the directed edge; never the source-versioned proposal ID."""

    return STABLE_ID_PREFIX + digest(
        {
            "tenant": tenant_id.strip().casefold(),
            "subscription": subscription_id.strip().casefold(),
            "subject": subject_id.strip().casefold(),
            "predicate": predicate,
            "object": object_id.strip().casefold(),
        }
    )


OBSERVATION_PREFIX = "source-observation://"
FIRST_ADMISSION_PREFIX = "first-admission://"


class FirstAdmissionLedger:
    """Durable coordinator-written trusted record store (create-only entries).

    Besides the legacy ``resource_id -> first valid instant`` entries it holds
    the captured source observation per source generation and the exact
    provenance of each first admission.  The publisher reads these through
    :meth:`reader` and never trusts the candidate row for them.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def reader(self) -> TrustedRecordReader:
        return TrustedRecordReader(self._path)

    def _mutate(self, fn: Any) -> Any:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._path.with_suffix(self._path.suffix + ".lock")
        with open(lock, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                rows: dict[str, Any] = (
                    json.loads(self._path.read_text(encoding="utf-8"))
                    if self._path.is_file()
                    else {}
                )
                before = json.dumps(rows, sort_keys=True)
                result = fn(rows)
                if json.dumps(rows, sort_keys=True) != before:
                    fd, tmp = tempfile.mkstemp(dir=str(self._path.parent))
                    with os.fdopen(fd, "w", encoding="utf-8") as out:
                        json.dump(rows, out, sort_keys=True)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(tmp, self._path)
                return result
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _create_only(rows: dict[str, Any], key: str, record: dict[str, Any]) -> dict[str, Any]:
        existing = rows.get(key)
        if existing is None:
            rows[key] = record
            return record
        if existing != record:
            raise MaintenanceDenied("trusted_record_conflict")
        return existing

    def record_source_observation(
        self,
        source_generation_id: str,
        *,
        observed_at: datetime,
        ingestion_run_id: str,
        manifest_digest: str,
    ) -> dict[str, Any]:
        record = {
            "source_generation_id": str(source_generation_id),
            "source_observed_at": observed_at.isoformat(),
            "ingestion_run_id": str(ingestion_run_id),
            "manifest_digest": str(manifest_digest),
        }
        return self._mutate(
            lambda rows: self._create_only(
                rows, OBSERVATION_PREFIX + str(source_generation_id), record
            )
        )

    def get_or_record(
        self,
        resource_id: str,
        instant: datetime,
        *,
        provenance: Mapping[str, str] | None = None,
    ) -> str:
        def apply(rows: dict[str, Any]) -> str:
            first = rows.setdefault(resource_id, instant.isoformat())
            if provenance is not None:
                self._create_only(
                    rows,
                    FIRST_ADMISSION_PREFIX + resource_id,
                    {
                        "resource_id": resource_id,
                        "first_admitted_at": first,
                        **{str(k): str(v) for k, v in provenance.items()},
                    },
                )
            return str(first)

        return self._mutate(apply)


class TrustedRecordReader:
    """Durable read-only port over the coordinator-written trusted records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _rows(self) -> dict[str, Any]:
        try:
            rows = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return rows if isinstance(rows, dict) else {}

    def source_observation(self, source_generation_id: str) -> dict[str, Any] | None:
        record = self._rows().get(OBSERVATION_PREFIX + str(source_generation_id))
        return dict(record) if isinstance(record, dict) else None

    def first_admission(self, resource_id: str) -> dict[str, Any] | None:
        rows = self._rows()
        record = rows.get(FIRST_ADMISSION_PREFIX + resource_id)
        if not isinstance(record, dict) or rows.get(resource_id) != record.get(
            "first_admitted_at"
        ):
            return None
        return dict(record)


def materialize_relationship(
    *,
    proposal_id: str,
    relationship: Mapping[str, Any],
    release: MaintenanceRelease,
    entities: Mapping[str, Mapping[str, Any]],
    evidence_records: Mapping[str, Mapping[str, Any]],
    source_observed_at: datetime,
    ingestion_run_id: str,
    first_admitted_at: str,
    source_generation_id: str,
    ontology_version: str,
) -> dict[str, Any]:
    """Build one complete canonical row from trusted facts only.

    Tenant/subscription/scope come from the authorized release, endpoint casing
    and types from authorized inventory entities.  Nothing is taken from model
    output other than the already policy-verified proposal identity.
    """

    subject = entities.get(str(relationship["subject_id"]).casefold())
    obj = entities.get(str(relationship["object_id"]).casefold())
    if subject is None or obj is None:
        raise ValueError("endpoint_not_in_authorized_inventory")
    if ontology_version != release.ontology_version:
        raise ValueError("ontology_version_not_authorized")
    refs = sorted(str(ref) for ref in relationship["evidence_refs"])
    resource_id = stable_relationship_id(
        tenant_id=release.tenant_id,
        subscription_id=release.subscription_id,
        subject_id=str(subject["resource_id"]),
        predicate=str(relationship["predicate"]),
        object_id=str(obj["resource_id"]),
    )
    evidence_digest = digest([evidence_records[ref] for ref in refs])
    lineage = {
        "proposal_id": proposal_id,
        "evidence_ids": refs,
        "evidence_digest": evidence_digest,
        "release_id": release.release_id,
        "attestation_digest": release.attestation_digest,
        "provider_lineage": dict(release.lineage),
        "definition_fingerprint": release.definition_fingerprint,
        "source_generation_id": source_generation_id,
    }
    payload = {
        "origin": "maintenance-admission",
        "proposal_id": proposal_id,
        "evidence_sources": sorted(
            {str(evidence_records[ref].get("source")) for ref in refs}
        ),
    }
    return {
        "tenant_id": release.tenant_id,
        "subscription_id": release.subscription_id,
        "resource_id": resource_id,
        "timestamp": source_observed_at.isoformat(),
        "change_version": digest(
            {
                "proposal_id": proposal_id,
                "evidence_digest": evidence_digest,
                "release": release.authorization_binding(),
                "source_generation_id": source_generation_id,
            }
        ),
        "ingestion_run_id": ingestion_run_id,
        "subject_id": str(subject["resource_id"]),
        "subject_type": str(relationship["subject_type"]),
        "predicate": str(relationship["predicate"]),
        "object_id": str(obj["resource_id"]),
        "object_type": str(relationship["object_type"]),
        "source": "model",
        "model_derived": True,
        "confidence": 1.0,
        "scope": release.scope,
        "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "lineage_json": json.dumps(lineage, sort_keys=True, separators=(",", ":")),
        "lifecycle_status": "active",
        "valid_from": first_admitted_at,
        "retired_at": "",
        "ontology_version": ontology_version,
    }


__all__ = [
    "STABLE_ID_PREFIX",
    "FirstAdmissionLedger",
    "TrustedRecordReader",
    "materialize_relationship",
    "stable_relationship_id",
]
