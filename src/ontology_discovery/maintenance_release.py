"""Authenticated, read-only Phase 14 maintenance prerequisite/release verifier.

One verifier is shared by the coordinator, the publisher and the Plan 05
acceptance CLI.  The runtime only *reads* a signed attestation: it holds no
private key, cannot issue or update approvals and cannot choose its trust root.
Trusted public keys, the pinned environment and the running implementation
digest come from server-owned configuration (:func:`build_production_reader`);
tests inject an isolated, explicitly ``offline-qualification`` trust context
that production composition refuses to build.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from azure.core.exceptions import AzureError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from ontology_discovery.contracts import AdmissionEvaluationSnapshot
from ontology_discovery.policy import evaluate_release_eligibility

ATTESTATION_VERSION = "maintenance-attestation/v1"
PURPOSE_LIVE = "live-release"
PURPOSE_OFFLINE = "offline-qualification"
CORRECTED_TARGET = {
    "tenant_id": "262a3a77-7d74-4684-8937-897d98d2a17a",
    "subscription_id": "890c9bfc-d09c-4143-9ce5-465e75e3eecc",
}
# Local saved evidence contracts, NOT Fabric API operations. Each artifact is
# independently signed by an operator-pinned collector, then digest-bound by
# the release attestor and all three approvers.
LIVE_EVIDENCE_KINDS = (
    "scope_security", "source_discovery", "restart_replay", "target_preservation",
    "quality", "budget_cost", "kill_revoke", "stale_writer", "products",
    "recovery_postcheck", "recovery_cas", "deployment",
    "consumer_api", "consumer_fabric", "consumer_agent", "consumer_export",
    "consumer_semantic",
)
REQUIRED_APPROVAL_ROLES = frozenset(
    {"ontology_steward", "security_owner", "fabric_governance_steward"}
)
ISSUER_ROLE = "release_attestor"
MAX_EVALUATION_AGE = timedelta(days=30)
_NON_PASSING_MARKERS = (
    "waiver",
    "waived",
    "deferral",
    "deferred",
    "conditional",
    "human_needed",
    "gaps_found",
)
# Exact inherited contract.  Never lowered to the number currently present.
PREREQUISITE_SPECS: Mapping[str, tuple[tuple[str, tuple[int, ...] | None], ...]] = {
    "03.7": (
        ("03.1", (19, 20)),
        ("07", tuple(range(1, 7))),
        ("09", tuple(range(1, 12))),
        ("13", tuple(range(1, 23))),
    ),
    "03.8": (
        ("03.7", tuple(range(1, 13))),
        ("11", tuple(range(1, 17))),
        ("13", tuple(range(1, 23))),
        ("03.8", None),  # every plan present in the phase directory
    ),
}


class MaintenanceDenied(RuntimeError):
    """Closed, fail-closed denial with a stable reason code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MaintenanceConfigError(RuntimeError):
    """Production maintenance configuration is invalid (startup fails closed)."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_key: bytes  # raw 32-byte Ed25519 public key
    roles: frozenset[str]


@dataclass(frozen=True)
class TrustContext:
    """Server-owned pinned trust.  ``purpose`` is fixed at construction."""

    purpose: str
    environment: str
    implementation_digest: str
    identity_digest: str
    template_digest: str
    root_capability_digest: str
    issuers: Mapping[str, TrustedKey]
    approvers: Mapping[str, TrustedKey]
    artifact_root: Path
    max_evaluation_age: timedelta = MAX_EVALUATION_AGE

    @classmethod
    def offline_for_tests(cls, **kwargs: Any) -> TrustContext:
        """Isolated offline trust; never accepted by production composition."""

        return cls(purpose=PURPOSE_OFFLINE, **kwargs)


@dataclass(frozen=True)
class MaintenanceRelease:
    """Verified, current, exact-bound maintenance release."""

    release_id: str
    attestation_digest: str
    purpose: str
    revocation_revision: int
    tenant_id: str
    subscription_id: str
    connection_id: str
    workspace_id: str
    item_id: str
    sources: tuple[str, ...]
    pair: tuple[str, str, str]
    lineage: Mapping[str, str]
    definition_fingerprint: str
    ontology_version: str
    operations: frozenset[str]
    max_model_edges: int
    expires_at: datetime
    prerequisite_manifest_digest: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def scope(self) -> str:
        return f"{self.tenant_id}:{self.subscription_id}:{self.connection_id}".casefold()

    def authorization_binding(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "attestation_digest": self.attestation_digest,
            "revocation_revision": self.revocation_revision,
            "definition_fingerprint": self.definition_fingerprint,
            "pair": list(self.pair),
            "purpose": self.purpose,
        }


# ----------------------------------------------------------------- artifacts


def _frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def _status(front: str) -> str:
    for line in front.splitlines():
        if line.strip().startswith("status:"):
            return line.split(":", 1)[1].strip().strip("'\"").casefold()
    return ""


def _phase_dir(root: Path, prefix: str) -> Path:
    base = root / "phases"
    matches = sorted(
        path
        for path in base.glob(f"{prefix}-*")
        if path.is_dir() and path.name[len(prefix)] in "-"
    ) if base.is_dir() else []
    if len(matches) != 1:
        raise MaintenanceDenied(f"prerequisite_phase_unresolved:{prefix}")
    return matches[0]


def verify_prerequisite_corpus(
    artifact_root: Path, targets: list[str], *,
    _validation: _CorpusValidation | None = None,
    _contents: dict[str, bytes] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Verify exact inherited summaries/verifications; return their digest.

    Reads the actual planning files.  A shortfall (for example Phase 13's
    twenty-two summaries) is a denial, never a lowered expectation.
    """

    root = Path(artifact_root)
    if not targets or any(target not in PREREQUISITE_SPECS for target in targets):
        raise MaintenanceDenied("prerequisite_target_unknown")
    # Discover membership afresh, once, rather than glob/stat the root for each
    # repeated prerequisite (Phase 13 is inherited by both targets).
    directories: dict[str, Path] = {}
    base = root / "phases"
    if base.is_dir():
        with os.scandir(base) as entries:
            for entry in entries:
                if entry.is_dir():
                    directories[entry.name] = Path(entry.path)
    required_by_prefix: dict[str, set[int] | None] = {}
    for target in sorted(set(targets)):
        for prefix, numbers in PREREQUISITE_SPECS[target]:
            if numbers is None:
                required_by_prefix[prefix] = None
            elif prefix not in required_by_prefix:
                required_by_prefix[prefix] = set(numbers)
            elif required_by_prefix[prefix] is not None:
                required_by_prefix[prefix].update(numbers)
    contents: dict[str, bytes] = {}
    summaries: set[str] = set()
    verifications: dict[str, str] = {}
    for prefix, required in required_by_prefix.items():
        matches = [p for n, p in directories.items() if n.startswith(prefix + "-")]
        if len(matches) != 1:
            raise MaintenanceDenied(f"prerequisite_phase_unresolved:{prefix}")
        directory = matches[0]
        with os.scandir(directory) as entries:
            names = {entry.name for entry in entries if entry.is_file()}
        if required is None:
            required = tuple(
                sorted(
                    int(m.group(1))
                    for name in names
                    if (m := re.fullmatch(rf"{re.escape(prefix)}-(\d+)-PLAN\.md", name))
                )
            )
            if not required:
                raise MaintenanceDenied(f"prerequisite_plans_missing:{prefix}")
        # String paths avoid rebuilding/relativizing a Path per file per write.
        relative_directory = f"phases/{directory.name}/"
        for number in required:
            name = f"{prefix}-{number:02d}-SUMMARY.md"
            if name not in names:
                raise MaintenanceDenied(
                    f"prerequisite_summary_missing:{prefix}-{number:02d}"
                )
            relative = relative_directory + name
            with open(os.path.join(directory, name), "rb") as stream:
                contents[relative] = stream.read()
            if not contents[relative]:
                raise MaintenanceDenied(f"prerequisite_summary_missing:{prefix}-{number:02d}")
            summaries.add(relative)
        checks = sorted(n for n in names if n.endswith("-VERIFICATION.md"))
        if not checks:
            raise MaintenanceDenied(f"prerequisite_verification_missing:{prefix}")
        for name in checks:
            relative = relative_directory + name
            with open(os.path.join(directory, name), "rb") as stream:
                contents[relative] = stream.read()
            verifications[relative] = prefix
    if _contents is not None:
        _contents.update(contents)
    # Reuse is conditional on *all actual bytes*, never metadata. The cache is
    # reader-owned and holds just one revision. No signature, control, clock,
    # evidence or source authorization result is cached.
    revision = tuple(sorted(contents.items()))
    validation = _validation or _CorpusValidation()
    validated = validation.validated
    if validated is not None and validated[0] == revision:
        return validated[1], dict(validated[2])
    seen: dict[str, str] = {}
    for relative, data in revision:
        text = data.decode("utf-8")
        front = _frontmatter(text)
        if relative in summaries:
            if _status(front) not in {"complete", "completed", "passed"}:
                raise MaintenanceDenied(
                    "prerequisite_summary_unfinished:" +
                    Path(relative).name.removesuffix("-SUMMARY.md")
                )
        elif _status(front) != "passed" or any(
            marker in front.casefold() for marker in _NON_PASSING_MARKERS
        ):
            raise MaintenanceDenied(
                f"prerequisite_verification_not_passed:{verifications[relative]}"
            )
        seen[relative] = hashlib.sha256(data).hexdigest()
    manifest = digest(sorted(seen.items()))
    # Publish one immutable tuple, and capture it once above. Concurrent reads
    # must never pair one revision's bytes with another revision's manifest.
    validation.validated = (revision, manifest, tuple(seen.items()))
    return manifest, seen


@dataclass
class _CorpusValidation:
    """One content-validated revision; never an authority capability."""

    validated: tuple[
        tuple[tuple[str, bytes], ...], str, tuple[tuple[str, str], ...]
    ] | None = None


def verify_plan20_21_order(
    artifact_root: Path, finalization_digest: str, *, strict: bool = False,
    _contents: Mapping[str, bytes] | None = None,
) -> None:
    """Plan 21 must bind the accepted Plan 20 finalization and follow it."""

    directory = _phase_dir(Path(artifact_root), "13")
    first = directory / "13-20-SUMMARY.md"
    second = directory / "13-21-SUMMARY.md"
    if not first.is_file() or not second.is_file():
        raise MaintenanceDenied("plan20_21_summaries_missing")
    def text(path: Path) -> str:
        relative = str(path.relative_to(artifact_root))
        if _contents is not None and relative in _contents:
            return _contents[relative].decode("utf-8")
        return path.read_text(encoding="utf-8")

    first_text = text(first)
    second_text = text(second)
    if hashlib.sha256(first_text.encode()).hexdigest() != finalization_digest:
        raise MaintenanceDenied("plan20_finalization_digest_mismatch")
    if finalization_digest not in second_text:
        raise MaintenanceDenied("plan21_not_bound_to_plan20")
    done = [
        _completed(text) for text in (first_text, second_text)
    ]
    if not all(done) or done[0] > done[1]:
        raise MaintenanceDenied("plan21_precedes_plan20_finalization")
    if strict:
        first_front, second_front = _frontmatter(first_text), _frontmatter(second_text)
        def field_value(front: str, name: str) -> str:
            for line in front.splitlines():
                if line.startswith(name + ":"):
                    return line.split(":", 1)[1].strip().strip("'\"")
            return ""

        if any(field_value(front, "accepted") != "true" for front in (first_front, second_front)):
            raise MaintenanceDenied("plan20_21_acceptance_absent")
        if field_value(second_front, "plan20_finalization_digest") != finalization_digest:
            raise MaintenanceDenied("plan21_not_bound_to_plan20")
        finalized = _aware(done[0], "plan20_completed")
        started = _aware(field_value(second_front, "started"), "plan21_started")
        accepted = _aware(done[1], "plan21_completed")
        if not finalized < started <= accepted:
            raise MaintenanceDenied("plan21_precedes_plan20_finalization")


def verify_plan21_22_order(
    artifact_root: Path, *, _contents: Mapping[str, bytes] | None = None,
) -> None:
    """Require accepted Plan 22 to bind and follow accepted Plan 21.

    Acceptance fields are necessary content, not signatures. The caller must
    authenticate the complete corpus through the existing release reader.
    """
    directory = _phase_dir(Path(artifact_root), "13")
    if not (directory / "13-22-PLAN.md").is_file():
        raise MaintenanceDenied("plan22_plan_missing")

    def text(name: str) -> str:
        path = directory / name
        relative = str(path.relative_to(artifact_root))
        if _contents is not None and relative in _contents:
            return _contents[relative].decode("utf-8")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise MaintenanceDenied("plan21_22_summaries_missing") from None

    second = text("13-21-SUMMARY.md")
    third = text("13-22-SUMMARY.md")
    front = _frontmatter(third)

    def field(name: str) -> str:
        values = [
            line.split(":", 1)[1].strip().strip("'\"")
            for line in front.splitlines() if line.startswith(name + ":")
        ]
        return values[0] if len(values) == 1 else ""

    if field("accepted") != "true":
        raise MaintenanceDenied("plan22_acceptance_absent")
    if field("plan21_acceptance_digest") != hashlib.sha256(second.encode()).hexdigest():
        raise MaintenanceDenied("plan22_not_bound_to_plan21")
    accepted = _aware(_completed(second), "plan21_completed")
    started = _aware(field("started"), "plan22_started")
    completed = _aware(_completed(third), "plan22_completed")
    if not accepted < started <= completed:
        raise MaintenanceDenied("plan22_precedes_plan21_acceptance")


def _verify_live_evidence(
    payload: Mapping[str, Any], trust: TrustContext,
    control: Mapping[str, Any], now: datetime,
    *, corpus: Mapping[str, Any] | None = None,
) -> None:
    """Authenticate owned local receipts; no collector, cloud call or mutation.

    Deliberately mandatory for live purpose only: the legacy offline Authority
    exercises the common admission contract but cannot be promoted to live by
    changing its purpose. Test-only callers can construct complete synthetic
    live-schema cases using isolated in-memory trust, never production config.
    """
    release = payload["release"]
    for key, expected in CORRECTED_TARGET.items():
        if release.get(key) != expected:
            raise MaintenanceDenied(f"corrected_target_mismatch:{key}")
    if release["lineage"].get("provider") != "foundry":
        raise MaintenanceDenied("provider_not_supported")
    plans: dict[str, str] = {}
    if corpus is None:
        _, corpus = verify_prerequisite_corpus(trust.artifact_root, ["03.7", "03.8"])
    for relative in corpus:
        if not relative.endswith("-SUMMARY.md"):
            continue
        path = trust.artifact_root / relative.replace("-SUMMARY.md", "-PLAN.md")
        if not path.is_file():
            raise MaintenanceDenied("prerequisite_plan_missing:" + path.name)
        plans[str(path.relative_to(trust.artifact_root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    plan_digest = digest(sorted(plans.items()))
    if payload["prerequisite"].get("plan_manifest_digest") != plan_digest:
        raise MaintenanceDenied("prerequisite_plan_manifest_digest_mismatch")
    if payload["prerequisite"].get("inherited_preconditions_digest") != plan_digest:
        raise MaintenanceDenied("inherited_preconditions_digest_mismatch")

    qualification = payload.get("qualification")
    artifacts = qualification.get("artifacts") if isinstance(qualification, Mapping) else None
    if not isinstance(artifacts, list):
        artifacts = []
    binding = digest({k: v for k, v in payload.items() if k not in {"approvals", "qualification"}})
    consumers: dict[str, set[str]] = {key: set() for key in ("collector_id", "source_id", "capture_id", "result_digest")}
    observed_measurements: dict[str, Mapping[str, Any]] = {}
    root = trust.artifact_root.resolve()
    for kind in LIVE_EVIDENCE_KINDS:
        matches = [a for a in artifacts if isinstance(a, Mapping) and a.get("kind") == kind]
        if len(matches) != 1:
            raise MaintenanceDenied(f"live_evidence_missing:{kind}")
        reference = matches[0]
        try:
            path = (root / str(reference["path"])).resolve()
            if not path.is_relative_to(root):
                raise MaintenanceDenied(f"live_evidence_path_invalid:{kind}")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != reference.get("sha256"):
                raise MaintenanceDenied(f"live_evidence_digest_mismatch:{kind}")
            envelope = json.loads(data)
            receipt = envelope["payload"]
            collector = trust.issuers.get(str(receipt["collector_id"]))
            if (
                collector is None or "evidence_collector" not in collector.roles
                or collector.key_id != envelope.get("key_id")
                or envelope.get("algorithm") != "Ed25519"
                or collector.key_id in set(control.get("revoked_key_ids") or ())
                or receipt["collector_id"] == payload["issuer"]["issuer_id"]
                or receipt["collector_id"] in {a["approver_id"] for a in payload["approvals"]}
            ):
                raise MaintenanceDenied(f"live_evidence_collector_untrusted:{kind}")
            _verify_signature(collector, canonical_json(receipt), envelope.get("signature"))
            if receipt.get("origin") != "live" or receipt.get("kind") != kind:
                raise MaintenanceDenied(f"live_evidence_origin_invalid:{kind}")
            if receipt.get("binding") != binding:
                raise MaintenanceDenied(f"live_evidence_binding_mismatch:{kind}")
            observed = _aware(receipt.get("observed_at"), "evidence_observed_at")
            expiry = _aware(receipt.get("expires_at"), "evidence_expires_at")
            if not observed <= now < expiry or now - observed > trust.max_evaluation_age:
                raise MaintenanceDenied(f"live_evidence_stale:{kind}")
            if any(not str(receipt.get(key) or "").strip() for key in ("source_id", "capture_id", "result_digest")):
                raise MaintenanceDenied(f"live_evidence_provenance_missing:{kind}")
            measurements = receipt.get("measurements")
            if not isinstance(measurements, Mapping) or not measurements:
                raise MaintenanceDenied(f"live_evidence_measurements_missing:{kind}")
            _verify_measurements(kind, measurements, payload)
            if receipt["result_digest"] != digest(measurements):
                raise MaintenanceDenied(f"live_evidence_result_digest_mismatch:{kind}")
            observed_measurements[kind] = measurements
            if kind.startswith("consumer_"):
                for key, seen in consumers.items():
                    value = str(receipt[key])
                    if value in seen:
                        raise MaintenanceDenied("consumer_observation_not_independent")
                    seen.add(value)
        except MaintenanceDenied:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise MaintenanceDenied(f"live_evidence_unreadable:{kind}") from None
    products = observed_measurements["products"]
    product_fingerprint = digest({
        "catalog_digest": products["catalog_digest"], "products": products["products"],
    })
    for kind, measurements in observed_measurements.items():
        if kind.startswith("consumer_") and (
            measurements["generation_digest"] != products["candidate_digest"]
            or measurements["product_fingerprint"] != product_fingerprint
        ):
            raise MaintenanceDenied(f"live_consumer_product_binding_mismatch:{kind}")
        if kind.startswith("recovery_") and measurements["new_digest"] != products["candidate_digest"]:
            raise MaintenanceDenied(f"live_recovery_candidate_binding_mismatch:{kind}")


def _verify_measurements(kind: str, values: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    """Require attributable measurements, not repeated manifest `passed` flags."""
    required = {
        "scope_security": ("scope_denials_digest", "injection_results_digest", "identity_matrix_digest"),
        "source_discovery": ("declaration_capture_digest", "appdependencies_capture_digest", "exact_pair_digest"),
        "restart_replay": ("baseline_digest", "replayed_digest", "process_id_before", "process_id_after"),
        "target_preservation": ("full_capture_digest", "normalized_readback_digest", "predecessor_digest", "exclusive_writer_digest", "rules_history_disposition_digest"),
        "quality": ("adjudications_digest", "slice_results_digest", "citation_results_digest", "evaluation_digest"),
        "budget_cost": ("usage_digest", "price_digest", "latency_samples_digest", "limits_digest"),
        "kill_revoke": ("kill_receipt_digest", "revocation_receipt_digest", "no_later_write_digest"),
        "stale_writer": ("loser_fence", "winner_fence", "winner_products_digest"),
        "products": ("candidate_digest", "catalog_digest", "products"),
        "recovery_postcheck": ("old_digest", "new_digest", "restored_digest", "restart_process_id", "products", "old_products", "new_products", "catalog_digest"),
        "recovery_cas": ("old_digest", "new_digest", "restored_digest", "restart_process_id", "products", "old_products", "new_products", "catalog_digest"),
        "deployment": ("decision_digest", "implementation_digest", "identity_digest", "template_digest", "root_capability_digest", "immutable_image_digest", "target_digest"),
    }
    fields = required.get(kind, ("generation_digest", "product_fingerprint", "query_digest", "response_digest"))
    if any(values.get(key) in (None, "", [], {}) or isinstance(values.get(key), bool) for key in fields):
        raise MaintenanceDenied(f"live_evidence_measurements_missing:{kind}")
    if kind == "restart_replay" and (
        values["baseline_digest"] != values["replayed_digest"]
        or values["process_id_before"] == values["process_id_after"]
    ):
        raise MaintenanceDenied("live_replay_mismatch")
    if kind == "quality" and values["evaluation_digest"] != digest(payload["evaluation"]):
        raise MaintenanceDenied("live_evaluation_digest_mismatch")
    if kind == "stale_writer" and (
        type(values["loser_fence"]) is not int or type(values["winner_fence"]) is not int
        or not 0 <= values["loser_fence"] < values["winner_fence"]
    ):
        raise MaintenanceDenied("live_stale_writer_fence_invalid")
    if kind == "deployment":
        expected = {key: payload[key] for key in (
            "implementation_digest", "identity_digest", "template_digest", "root_capability_digest"
        )}
        expected["decision_digest"] = payload["deployment_decision"]["decision_digest"]
        expected["target_digest"] = digest({key: payload["release"][key] for key in (
            "tenant_id", "subscription_id", "connection_id", "workspace_id", "item_id"
        )})
        if any(values[key] != value for key, value in expected.items()):
            raise MaintenanceDenied("live_deployment_binding_mismatch")
    if kind.startswith("recovery_") and (
        values["old_digest"] != values["restored_digest"]
        or values["new_digest"] == values["old_digest"]
    ):
        raise MaintenanceDenied(f"live_recovery_mismatch:{kind}")
    if kind in {"products", "recovery_postcheck", "recovery_cas"}:
        from fabric.dataset_mapper import (
            ONTOLOGY_ENTITY_TYPES,
            ONTOLOGY_RELATIONSHIP_TYPES,
            ontology_entity_table,
            ontology_relationship_table,
        )

        expected = {"ontology_entities", "ontology_relationships", "ontology_health", "ontology_quality_report"}
        expected.update(ontology_entity_table(entity) for entity in ONTOLOGY_ENTITY_TYPES)
        expected.update(ontology_relationship_table(*triple) for triple in ONTOLOGY_RELATIONSHIP_TYPES)
        products = values["products"]
        if not isinstance(products, list) or not products:
            raise MaintenanceDenied(f"live_products_missing:{kind}")
        names = set()
        for product in products:
            if (
                not isinstance(product, Mapping)
                or not product.get("table") or product["table"] in names
                or not re.fullmatch(r"[0-9a-f]{64}", str(product.get("row_hash")))
                or type(product.get("delta_version")) is not int
                or product["delta_version"] < 0
            ):
                raise MaintenanceDenied(f"live_product_invalid:{kind}")
            names.add(product["table"])
        if names != expected:
            raise MaintenanceDenied(f"live_products_incomplete:{kind}")
        if kind.startswith("recovery_"):
            old = values["old_products"]
            new = values["new_products"]
            for rows in (old, new):
                # Reuse exactly the same complete-product validation.
                _verify_measurements("products", {
                    "candidate_digest": values["old_digest"],
                    "catalog_digest": values["catalog_digest"], "products": rows,
                }, payload)
            old_by_table = {p["table"]: p for p in old}
            new_by_table = {p["table"]: p for p in new}
            for restored in products:
                predecessor = old_by_table[restored["table"]]
                candidate = new_by_table[restored["table"]]
                if restored["row_hash"] != predecessor["row_hash"] or (
                    candidate["row_hash"] != predecessor["row_hash"] and not (
                        predecessor["delta_version"] < candidate["delta_version"] < restored["delta_version"]
                    )
                ):
                    raise MaintenanceDenied(f"live_physical_restore_mismatch:{kind}")
            edge = "ontology_rel_depends_on_application_application"
            if old_by_table[edge]["row_hash"] == new_by_table[edge]["row_hash"]:
                raise MaintenanceDenied(f"live_novel_product_missing:{kind}")


def _completed(text: str) -> str:
    for line in _frontmatter(text).splitlines():
        if line.strip().startswith("completed:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


# -------------------------------------------------------------- attestation


def _aware(value: object, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise MaintenanceDenied(f"{name}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MaintenanceDenied(f"{name}_invalid")
    return parsed.astimezone(UTC)


def _verify_signature(key: TrustedKey, message: bytes, signature_b64: object) -> None:
    try:
        signature = base64.b64decode(str(signature_b64), validate=True)
        Ed25519PublicKey.from_public_bytes(key.public_key).verify(signature, message)
    except (InvalidSignature, binascii.Error, ValueError):
        raise MaintenanceDenied("signature_invalid") from None


def approval_message(
    binding: str, approval: Mapping[str, Any]
) -> bytes:
    return canonical_json(
        {
            "binding": binding,
            "role": approval.get("role"),
            "approver_id": approval.get("approver_id"),
            "key_id": approval.get("key_id"),
            "reason": approval.get("reason"),
            "expires_at": approval.get("expires_at"),
        }
    )


def verify_maintenance_attestation(
    envelope: Mapping[str, Any] | None,
    *,
    trust: TrustContext,
    control: Mapping[str, Any],
    now: datetime,
    _corpus_validation: _CorpusValidation | None = None,
) -> MaintenanceRelease:
    """Verify one signed envelope against pinned trust, files and control state."""

    moment = now.astimezone(UTC)
    if not isinstance(envelope, Mapping) or not isinstance(
        envelope.get("payload"), Mapping
    ):
        raise MaintenanceDenied("attestation_absent")
    if envelope.get("algorithm") != "Ed25519":
        raise MaintenanceDenied("algorithm_not_allowed")
    payload = dict(envelope["payload"])
    if payload.get("version") != ATTESTATION_VERSION:
        raise MaintenanceDenied("attestation_version_unknown")
    if payload.get("purpose") != trust.purpose:
        raise MaintenanceDenied("purpose_mismatch")
    if trust.purpose not in {PURPOSE_LIVE, PURPOSE_OFFLINE}:
        raise MaintenanceDenied("purpose_unknown")

    issuer = payload.get("issuer")
    if not isinstance(issuer, Mapping):
        raise MaintenanceDenied("issuer_absent")
    trusted = trust.issuers.get(str(issuer.get("issuer_id")))
    if (
        trusted is None
        or trusted.key_id != issuer.get("key_id")
        or envelope.get("key_id") != trusted.key_id
        or ISSUER_ROLE not in trusted.roles
        or issuer.get("role") != ISSUER_ROLE
    ):
        raise MaintenanceDenied("issuer_untrusted")
    if trusted.key_id in set(control.get("revoked_key_ids") or ()):
        raise MaintenanceDenied("issuer_revoked")
    _verify_signature(trusted, canonical_json(payload), envelope.get("signature"))

    # Control (mutable, read fresh by the caller): kill and revocation.
    if control.get("kill") is not False:
        raise MaintenanceDenied("kill_switch_engaged")
    attestation_digest = digest(payload)
    if attestation_digest in set(control.get("revoked_attestations") or ()):
        raise MaintenanceDenied("attestation_revoked")
    if control.get("revocation_revision") != payload.get("revocation_revision"):
        raise MaintenanceDenied("revocation_revision_changed")

    # Freshness.
    not_before = _aware(payload.get("not_before"), "not_before")
    issued_at = _aware(payload.get("issued_at"), "issued_at")
    expires_at = _aware(payload.get("expires_at"), "expires_at")
    if not issued_at <= moment or not not_before <= moment:
        raise MaintenanceDenied("attestation_not_yet_valid")
    if moment >= expires_at:
        raise MaintenanceDenied("attestation_expired")

    # Exact environment / running implementation / deployment matrix.
    if payload.get("environment") != trust.environment:
        raise MaintenanceDenied("environment_mismatch")
    for name, pinned in (
        ("implementation_digest", trust.implementation_digest),
        ("identity_digest", trust.identity_digest),
        ("template_digest", trust.template_digest),
        ("root_capability_digest", trust.root_capability_digest),
    ):
        if not pinned or payload.get(name) != pinned:
            raise MaintenanceDenied(f"{name}_mismatch")
    if control.get("implementation_digest") not in (None, trust.implementation_digest):
        raise MaintenanceDenied("implementation_drift")
    deployment = payload.get("deployment_decision")
    if not isinstance(deployment, Mapping) or deployment.get("status") != "accepted":
        raise MaintenanceDenied("deployment_not_accepted")
    if not str(deployment.get("decision_digest") or ""):
        raise MaintenanceDenied("deployment_not_accepted")

    # Approvals: independently signed, distinct, bound to this payload.
    base = digest({key: value for key, value in payload.items() if key != "approvals"})
    approvals = payload.get("approvals")
    if not isinstance(approvals, list):
        raise MaintenanceDenied("approvals_absent")
    roles: set[str] = set()
    identities: set[str] = {str(issuer.get("issuer_id"))}
    for approval in approvals:
        if not isinstance(approval, Mapping):
            raise MaintenanceDenied("approval_malformed")
        approver = trust.approvers.get(str(approval.get("approver_id")))
        role = str(approval.get("role"))
        if (
            approver is None
            or approver.key_id != approval.get("key_id")
            or role not in approver.roles
            or role not in REQUIRED_APPROVAL_ROLES
            or not str(approval.get("reason") or "").strip()
            or str(approval.get("approver_id")) in identities
        ):
            raise MaintenanceDenied("approval_untrusted")
        if _aware(approval.get("expires_at"), "approval_expiry") <= moment:
            raise MaintenanceDenied("approval_expired")
        if approver.key_id in set(control.get("revoked_key_ids") or ()):
            raise MaintenanceDenied("approver_revoked")
        _verify_signature(
            approver, approval_message(base, approval), approval.get("signature")
        )
        identities.add(str(approval.get("approver_id")))
        roles.add(role)
    if roles != REQUIRED_APPROVAL_ROLES:
        raise MaintenanceDenied("approvals_incomplete")

    # Prerequisites from the actual files, never narrative booleans.
    prerequisite = payload.get("prerequisite")
    if not isinstance(prerequisite, Mapping):
        raise MaintenanceDenied("prerequisite_absent")
    if sorted(prerequisite.get("targets") or ()) != ["03.7", "03.8"]:
        raise MaintenanceDenied("prerequisite_targets_incomplete")
    contents: dict[str, bytes] = {}
    manifest_digest, corpus = verify_prerequisite_corpus(
        trust.artifact_root, list(prerequisite.get("targets") or ()),
        _validation=_corpus_validation, _contents=contents,
    )
    if prerequisite.get("manifest_digest") != manifest_digest:
        raise MaintenanceDenied("prerequisite_manifest_digest_mismatch")
    verify_plan20_21_order(
        trust.artifact_root, str(prerequisite.get("plan20_finalization_digest") or ""),
        strict=trust.purpose == PURPOSE_LIVE,
        _contents=contents,
    )
    if trust.purpose == PURPOSE_LIVE:
        verify_plan21_22_order(trust.artifact_root, _contents=contents)
    if not str(prerequisite.get("inherited_preconditions_digest") or ""):
        raise MaintenanceDenied("inherited_preconditions_absent")

    release = payload.get("release")
    evaluation = payload.get("evaluation")
    if not isinstance(release, Mapping) or not isinstance(evaluation, Mapping):
        raise MaintenanceDenied("release_absent")
    try:
        snapshot = AdmissionEvaluationSnapshot.model_validate_json(
            canonical_json(evaluation.get("snapshot"))
        )
    except ValidationError:
        raise MaintenanceDenied("evaluation_invalid") from None
    pair = release.get("pair")
    if not isinstance(pair, Mapping):
        raise MaintenanceDenied("release_pair_absent")
    triple = (
        str(pair.get("subject_type")),
        str(pair.get("predicate")),
        str(pair.get("object_type")),
    )
    if snapshot.pair != triple:
        raise MaintenanceDenied("evaluation_pair_mismatch")
    eligibility = evaluate_release_eligibility(snapshot)  # mandatory inherited floor
    if eligibility.status != "ELIGIBLE":
        raise MaintenanceDenied("evaluation_not_eligible:" + ",".join(eligibility.reasons))
    if snapshot.evaluated_at > moment or moment - snapshot.evaluated_at > trust.max_evaluation_age:
        raise MaintenanceDenied("evaluation_stale")
    lineage = release.get("lineage")
    if not isinstance(lineage, Mapping) or evaluation.get("bound_lineage") != lineage:
        raise MaintenanceDenied("evaluation_lineage_mismatch")
    if not str(lineage.get("model") or "").strip():
        raise MaintenanceDenied("release_model_lineage_required")
    if evaluation.get("bound_implementation_digest") != trust.implementation_digest:
        raise MaintenanceDenied("evaluation_implementation_mismatch")
    if release.get("native_planner") is not False:
        raise MaintenanceDenied("native_unsupported")
    operations = frozenset(str(op) for op in release.get("operations") or ())
    if not operations or not operations <= {"admit", "restore"}:
        raise MaintenanceDenied("operations_invalid")
    try:
        max_edges = int(release.get("max_model_edges"))
    except (TypeError, ValueError):
        raise MaintenanceDenied("release_budget_invalid") from None
    if not 1 <= max_edges <= 200:
        raise MaintenanceDenied("release_budget_invalid")
    required = (
        "release_id", "tenant_id", "subscription_id", "connection_id",
        "workspace_id", "item_id", "definition_fingerprint", "ontology_version",
    )
    if any(not str(release.get(name) or "").strip() for name in required):
        raise MaintenanceDenied("release_incomplete")
    sources = tuple(sorted(str(s) for s in release.get("sources") or ()))
    if len(sources) < 2:
        raise MaintenanceDenied("release_sources_incomplete")
    if trust.purpose == PURPOSE_LIVE:
        _verify_live_evidence(payload, trust, control, moment, corpus=corpus)
    return MaintenanceRelease(
        release_id=str(release["release_id"]),
        attestation_digest=attestation_digest,
        purpose=trust.purpose,
        revocation_revision=int(payload["revocation_revision"]),
        tenant_id=str(release["tenant_id"]),
        subscription_id=str(release["subscription_id"]),
        connection_id=str(release["connection_id"]),
        workspace_id=str(release["workspace_id"]),
        item_id=str(release["item_id"]),
        sources=sources,
        pair=triple,
        lineage={str(k): str(v) for k, v in lineage.items()},
        definition_fingerprint=str(release["definition_fingerprint"]),
        ontology_version=str(release["ontology_version"]),
        operations=operations,
        max_model_edges=max_edges,
        expires_at=expires_at,
        prerequisite_manifest_digest=manifest_digest,
    )


class MaintenanceReleaseReader:
    """Read-only reader; every ``read`` re-verifies with a fresh clock/control."""

    def __init__(
        self,
        *,
        trust: TrustContext,
        envelope_source: Callable[[], Mapping[str, Any] | None],
        control_source: Callable[[], Mapping[str, Any] | None],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._trust = trust
        self._envelope_source = envelope_source
        self._control_source = control_source
        self._clock = clock or (lambda: datetime.now(UTC))
        self._corpus_validation = _CorpusValidation()

    @property
    def purpose(self) -> str:
        return self._trust.purpose

    def read(self, operation: str = "admit") -> MaintenanceRelease:
        return self._read(operation)

    def read_saved(
        self, envelope: Mapping[str, Any] | None, operation: str = "admit"
    ) -> MaintenanceRelease:
        """CLI seam: authenticate fresh runtime state AND require exact saved bytes.

        No caller trust or control enters this seam; a saved file cannot replace
        the server-pinned release, including its signatures and approvals.
        """
        return self._read(operation, saved=envelope, require_saved=True)

    def _read(
        self, operation: str, *, saved: Mapping[str, Any] | None = None,
        require_saved: bool = False,
    ) -> MaintenanceRelease:
        try:
            control = self._control_source()
            envelope = self._envelope_source()
        except (OSError, ValueError):
            raise MaintenanceDenied("release_unreadable") from None
        if not isinstance(control, Mapping):
            raise MaintenanceDenied("control_unavailable")
        release = verify_maintenance_attestation(
            envelope, trust=self._trust, control=control, now=self._clock(),
            _corpus_validation=self._corpus_validation,
        )
        if require_saved and (
            not isinstance(saved, Mapping) or canonical_json(saved) != canonical_json(envelope)
        ):
            raise MaintenanceDenied("input_attestation_not_pinned")
        if operation not in release.operations:
            raise MaintenanceDenied(f"operation_not_authorized:{operation}")
        return release

    def check(self, operation: str = "admit") -> str:
        """Return '' when open or the closed denial reason."""

        try:
            self.read(operation)
        except MaintenanceDenied as denied:
            return denied.reason
        return ""


def _json_file(path: str) -> Callable[[], Mapping[str, Any] | None]:
    def read() -> Mapping[str, Any] | None:
        target = Path(path)
        if not target.is_file():
            return None
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None

    return read


def _read_key_vault_trust_config(
    secret_id: str,
    managed_identity_client_id: str,
    client_factory: Callable[[str, str], Any] | None = None,
) -> Mapping[str, Any]:
    """Load a version-pinned public config secret through a user-assigned MI."""

    try:
        parsed = urlsplit(secret_id)
        hostname = parsed.hostname or ""
        host_parts = hostname.split(".")
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or len(host_parts) != 4
            or host_parts[1:] != ["vault", "azure", "net"]
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,22}[a-z0-9]", host_parts[0])
        ):
            raise MaintenanceConfigError("maintenance_trust_secret_id_invalid")
        path = parsed.path.split("/")
        if (
            len(path) != 4
            or path[0] != ""
            or path[1] != "secrets"
            or not re.fullmatch(r"[A-Za-z0-9-]{1,127}", path[2])
            or not re.fullmatch(r"[A-Fa-f0-9]{32}", path[3])
        ):
            raise MaintenanceConfigError("maintenance_trust_secret_id_invalid")
    except ValueError:
        raise MaintenanceConfigError("maintenance_trust_secret_id_invalid") from None
    if not managed_identity_client_id:
        raise MaintenanceConfigError("maintenance_trust_managed_identity_missing")

    credential = None
    client = None
    try:
        if client_factory is None:
            from azure.identity import ManagedIdentityCredential
            from azure.keyvault.secrets import SecretClient

            credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
            client = SecretClient(
                vault_url=f"{parsed.scheme}://{hostname}",
                credential=credential,
            )
        else:
            client = client_factory(
                f"{parsed.scheme}://{hostname}", managed_identity_client_id
            )
        try:
            secret = client.get_secret(path[2], path[3])
        except (AzureError, OSError, ValueError):
            raise MaintenanceConfigError(
                "maintenance_trust_config_secret_unavailable"
            ) from None
        value = getattr(secret, "value", None)
        if not isinstance(value, str) or not value:
            raise MaintenanceConfigError("maintenance_trust_secret_empty")
        try:
            config = json.loads(value)
        except json.JSONDecodeError:
            raise MaintenanceConfigError("maintenance_trust_config_invalid") from None
        if not isinstance(config, Mapping):
            raise MaintenanceConfigError("maintenance_trust_config_invalid")
        return config
    except MaintenanceConfigError:
        raise
    except (AzureError, OSError, ValueError, TypeError):
        raise MaintenanceConfigError(
            "maintenance_trust_config_secret_unavailable"
        ) from None
    finally:
        for resource in (client, credential):
            close = getattr(resource, "close", None)
            if callable(close):
                close()


def _keys(raw: object, role_field: str = "roles") -> dict[str, TrustedKey]:
    out: dict[str, TrustedKey] = {}
    if not isinstance(raw, Mapping):
        raise MaintenanceConfigError("maintenance_trust_keys_invalid")
    for identity, item in raw.items():
        if not isinstance(item, Mapping):
            raise MaintenanceConfigError("maintenance_trust_keys_invalid")
        if item.get("origin") in {"test", "offline"}:
            raise MaintenanceConfigError("maintenance_trust_origin_rejected")
        if (
            not {"key_id", "public_key_b64", role_field}.issubset(item)
            or not set(item).issubset(
                {"key_id", "public_key_b64", role_field, "origin"}
            )
        ):
            raise MaintenanceConfigError("maintenance_trust_keys_invalid")
        try:
            if not isinstance(item[role_field], list) or not item[role_field]:
                raise ValueError
            public = base64.b64decode(str(item["public_key_b64"]), validate=True)
            Ed25519PublicKey.from_public_bytes(public)
            out[str(identity)] = TrustedKey(
                key_id=str(item["key_id"]),
                public_key=public,
                roles=frozenset(str(r) for r in item[role_field]),
            )
        except (KeyError, ValueError, binascii.Error):
            raise MaintenanceConfigError("maintenance_trust_keys_invalid") from None
    return out


def build_production_reader(
    environ: Mapping[str, str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    key_vault_secret_client_factory: Callable[[str, str], Any] | None = None,
) -> MaintenanceReleaseReader | None:
    """Build the default-off reader from a local file or pinned Key Vault secret.

    Production purpose is fixed to ``live-release``; offline/test trust is a
    startup error.  No caller or model value reaches this function. Key Vault
    access uses only the configured user-assigned managed identity.

    ``key_vault_secret_client_factory`` is an injection seam for isolated tests;
    production callers should leave it unset.
    """

    env = os.environ if environ is None else environ
    config_path = str(env.get("ONTOLOGY_MAINTENANCE_TRUST_CONFIG") or "").strip()
    secret_id = str(
        env.get("ONTOLOGY_MAINTENANCE_TRUST_CONFIG_SECRET_ID") or ""
    ).strip()
    if config_path and secret_id:
        raise MaintenanceConfigError("maintenance_trust_config_source_ambiguous")
    if not config_path and not secret_id:
        return None
    try:
        if secret_id:
            config = _read_key_vault_trust_config(
                secret_id,
                str(env.get("AZURE_CLIENT_ID") or "").strip(),
                key_vault_secret_client_factory,
            )
        else:
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if not isinstance(config, Mapping):
            raise MaintenanceConfigError("maintenance_trust_config_invalid")
        allowed_config_fields = {
            "purpose",
            "environment",
            "implementation_digest",
            "identity_digest",
            "template_digest",
            "root_capability_digest",
            "issuers",
            "approvers",
            "artifact_root",
            "release_path",
            "control_path",
        }
        if not set(config).issubset(allowed_config_fields):
            raise MaintenanceConfigError("maintenance_trust_config_invalid")
        if config.get("purpose") != PURPOSE_LIVE:
            raise MaintenanceConfigError("maintenance_purpose_not_live")
        trust = TrustContext(
            purpose=PURPOSE_LIVE,
            environment=str(config["environment"]),
            implementation_digest=str(config["implementation_digest"]),
            identity_digest=str(config["identity_digest"]),
            template_digest=str(config["template_digest"]),
            root_capability_digest=str(config["root_capability_digest"]),
            issuers=_keys(config["issuers"]),
            approvers=_keys(config["approvers"]),
            artifact_root=Path(config["artifact_root"]),
        )
        return MaintenanceReleaseReader(
            trust=trust,
            envelope_source=_json_file(str(config["release_path"])),
            control_source=_json_file(str(config["control_path"])),
            clock=clock,
        )
    except MaintenanceConfigError:
        raise
    except (OSError, KeyError, ValueError, TypeError):
        raise MaintenanceConfigError("maintenance_trust_config_invalid") from None


__all__ = [
    "ATTESTATION_VERSION",
    "PREREQUISITE_SPECS",
    "PURPOSE_LIVE",
    "PURPOSE_OFFLINE",
    "MaintenanceConfigError",
    "MaintenanceDenied",
    "MaintenanceRelease",
    "MaintenanceReleaseReader",
    "TrustContext",
    "TrustedKey",
    "approval_message",
    "build_production_reader",
    "canonical_json",
    "digest",
    "verify_maintenance_attestation",
    "verify_plan20_21_order",
    "verify_plan21_22_order",
    "verify_prerequisite_corpus",
]
