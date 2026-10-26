"""Project exact inventory and telemetry facts into bounded advisory evidence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .contracts import MAX_CANDIDATE_PAIRS

_DEPENDENCY_TAG = "aiops.dependencyResourceIds"
_APPLICATION_MEMBER_PREDICATE = "member_of"
_PREDICATE = "depends_on"
_MAX_PROJECTED_SOURCE_FACTS = 25_000


def project_application_dependency_evidence(
    *,
    scope: str,
    batch_source_generation_id: str,
    observed_at: datetime,
    application_entities: Iterable[Mapping[str, Any]],
    deterministic_relationships: Iterable[Mapping[str, Any]],
    inventory_records: Iterable[Mapping[str, Any]],
    app_dependency_rows: Iterable[Mapping[str, Any]] | None,
    monitor_identity_bindings: Mapping[str, str | Iterable[str]],
    inventory_generation_id: str,
    monitor_generation_id: str,
    generation_binding_verified: bool = False,
    inventory_observed_at: datetime | None = None,
    max_age: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    """Create exact Application ``depends_on`` candidates from source facts.

    Monitor role/target labels are accepted only through explicit
    ``monitor_identity_bindings`` to inventory resource IDs.  Physical
    resources resolve to an Application only through existing, in-scope
    ``member_of`` relationships.  Provenance carries source generation IDs
    separately from the batch generation; the latter is trusted only when the
    caller has durably bound the refreshed source manifest to its run.
    """

    trusted_scope = _required(scope, "scope")
    batch_generation = _required(
        batch_source_generation_id, "batch_source_generation_id"
    )
    inventory_generation = _required(
        inventory_generation_id, "inventory_generation_id"
    )
    monitor_generation = _required(monitor_generation_id, "monitor_generation_id")
    _aware(observed_at, "observed_at")
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    inventory_time = inventory_observed_at or observed_at
    _aware(inventory_time, "inventory_observed_at")

    entities = list(application_entities)
    applications: set[str] = set()
    for entity in entities:
        if (
            str(entity.get("entity_type") or "").casefold() == "application"
            and str(entity.get("scope") or trusted_scope).casefold()
            == trusted_scope.casefold()
            and str(entity.get("lifecycle_status") or "active").casefold()
            == "active"
        ):
            entity_id = _identity(entity.get("resource_id") or entity.get("entity_id"))
            if entity_id:
                applications.add(entity_id)

    physical_to_application: dict[str, set[str]] = defaultdict(set)
    for relationship in deterministic_relationships:
        if str(relationship.get("predicate") or "").casefold() != (
            _APPLICATION_MEMBER_PREDICATE
        ):
            continue
        asset_id = _identity(relationship.get("subject_id"))
        application_id = _identity(relationship.get("object_id"))
        if application_id in applications and asset_id:
            physical_to_application[asset_id].add(application_id)

    raw_inventory = list(inventory_records)
    inventory_by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    uncertainties: set[str] = set()
    for row in raw_inventory:
        resource_id = _identity(row.get("resource_id") or row.get("id"))
        if resource_id and _inventory_resource_in_scope(
            resource_id, row, trusted_scope
        ):
            inventory_by_id[resource_id].append(row)
        elif resource_id:
            uncertainties.add("inventory_resource_out_of_scope")

    facts: dict[str, dict[str, Any]] = {}
    pair_origins: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    for resource_id, rows in sorted(inventory_by_id.items()):
        asset_apps = physical_to_application.get(resource_id, set())
        if len(rows) > 1:
            fingerprints = {
                _fingerprint({
                    "payload": _inventory_payload(row),
                    "source_generation_id": str(
                        row.get("source_generation_id") or inventory_generation
                    ).strip(),
                    "observed_at": (
                        timestamp.astimezone(UTC).isoformat()
                        if (timestamp := _inventory_timestamp(row, inventory_time)) is not None
                        else None
                    ),
                })
                for row in rows
            }
            if len(fingerprints) > 1:
                uncertainties.add("inventory_duplicate_resource_conflict")
                continue
        row = rows[0]
        tags = _tags(_inventory_payload(row))
        declarations = [
            value for name, value in tags.items()
            if str(name).casefold() == _DEPENDENCY_TAG.casefold()
        ]
        if len({_fingerprint(value) for value in declarations}) > 1:
            uncertainties.add("dependency_declaration_conflict")
            continue
        declaration = declarations[0] if declarations else None
        if declaration is None:
            continue
        if len(asset_apps) != 1:
            uncertainties.add(
                "inventory_application_binding_ambiguous"
                if asset_apps
                else "inventory_application_binding_missing"
            )
            continue
        try:
            targets = json.loads(declaration) if isinstance(declaration, str) else declaration
        except (TypeError, ValueError):
            uncertainties.add("dependency_declaration_malformed")
            continue
        if (
            not isinstance(targets, list)
            or len(targets) > MAX_CANDIDATE_PAIRS
            or any(not isinstance(value, str) for value in targets)
        ):
            uncertainties.add("dependency_declaration_invalid")
            continue
        subject = next(iter(asset_apps))
        for target_value in targets:
            target_resource = _identity(target_value)
            if not target_resource:
                uncertainties.add("dependency_target_missing")
                continue
            if target_resource not in inventory_by_id:
                uncertainties.add("dependency_target_out_of_scope")
                continue
            target_apps = physical_to_application.get(target_resource, set())
            if len(target_apps) != 1:
                uncertainties.add(
                    "inventory_target_binding_ambiguous"
                    if target_apps
                    else "inventory_target_binding_missing"
                )
                continue
            pair = (subject, _PREDICATE, next(iter(target_apps)))
            if pair[0] == pair[2]:
                uncertainties.add("self_dependency_abstained")
                continue
            source_generation = str(
                row.get("source_generation_id") or inventory_generation
            ).strip()
            timestamp = _inventory_timestamp(row, inventory_time)
            if timestamp is None:
                uncertainties.add("source_observation_stale_or_timestamp_invalid")
                continue
            fresh = _fresh(timestamp, observed_at, max_age)
            valid_generation = source_generation == inventory_generation
            fingerprint = _fingerprint(_inventory_payload(row))
            evidence = _evidence_record(
                pair=pair,
                scope=trusted_scope,
                batch_generation=batch_generation,
                source="azure-resource-graph:dependency-tag",
                source_system="Azure Resource Graph inventory tags",
                origin_fingerprint=fingerprint,
                original_source_generation_id=source_generation,
                observed_at=timestamp,
                expires_at=timestamp + max_age,
                supports=bool(generation_binding_verified and fresh and valid_generation),
                uncertainty=(
                    ""
                    if generation_binding_verified and fresh and valid_generation
                    else _reason(
                        fresh=fresh,
                        generation_valid=valid_generation,
                        generation_bound=generation_binding_verified,
                    )
                ),
                lineage={
                    "inventory_resource_id": resource_id,
                    "declared_target_resource_id": target_resource,
                    "tag_key": _DEPENDENCY_TAG,
                },
            )
            _add_fact(facts, pair_origins, pair, evidence)
            if not evidence["supports"]:
                uncertainties.add(str(evidence["uncertainty"]))

    monitor_rows = None if app_dependency_rows is None else list(app_dependency_rows)
    monitor_inventory_ids = set(inventory_by_id)
    binding_index = _bindings(monitor_identity_bindings)
    if monitor_rows is None:
        uncertainties.add("azure_monitor_dependencies_unavailable")
    elif not monitor_rows:
        uncertainties.add("azure_monitor_dependencies_empty")
    else:
        for row in monitor_rows:
            if _synthetic(row.get("SyntheticSource")):
                uncertainties.add("synthetic_dependency_observation_excluded")
                continue
            monitor_time = _timestamp(row.get("TimeGenerated"), None)
            if monitor_time is None:
                uncertainties.add("dependency_observation_timestamp_missing")
                continue
            emitter_resource = _identity(row.get("_ResourceId"))
            if not emitter_resource or emitter_resource not in monitor_inventory_ids:
                uncertainties.add("dependency_emitter_resource_unbound")
                continue
            subscription = str(row.get("_SubscriptionId") or "").strip().casefold()
            if subscription and not _subscription_in_scope(trusted_scope, subscription):
                uncertainties.add("dependency_observation_out_of_scope")
                continue
            role_resource = _resolve_binding(binding_index, row.get("AppRoleName"))
            target_resource = _resolve_binding(binding_index, row.get("Target"))
            if not role_resource or not target_resource:
                uncertainties.add("dependency_monitor_identity_binding_missing")
                continue
            if role_resource != emitter_resource:
                uncertainties.add("dependency_emitter_binding_mismatch")
                continue
            if role_resource not in monitor_inventory_ids or target_resource not in inventory_by_id:
                uncertainties.add("dependency_monitor_identity_out_of_scope")
                continue
            emitting_apps = physical_to_application.get(role_resource, set())
            target_apps = physical_to_application.get(target_resource, set())
            if len(emitting_apps) != 1 or len(target_apps) != 1:
                uncertainties.add(
                    "dependency_monitor_identity_binding_ambiguous"
                    if emitting_apps or target_apps
                    else "dependency_monitor_application_binding_missing"
                )
                continue
            pair = (
                next(iter(emitting_apps)),
                _PREDICATE,
                next(iter(target_apps)),
            )
            if pair[0] == pair[2]:
                uncertainties.add("self_dependency_abstained")
                continue
            fresh = _fresh(monitor_time, observed_at, max_age)
            # This fixed Logs API response has no source-generation column.
            # Bind the observation to this server-created query window, never
            # to an arbitrary field a caller attached to a fixture/wrapper.
            original_generation = monitor_generation
            valid_generation = original_generation == monitor_generation
            # Hash only the fixed public AppDependencies projection. Arbitrary
            # caller metadata cannot alter source identity or independence.
            fingerprint = _fingerprint(
                {
                    key: row.get(key)
                    for key in (
                        "TimeGenerated",
                        "Id",
                        "OperationId",
                        "_ResourceId",
                        "_SubscriptionId",
                        "AppRoleName",
                        "Target",
                        "DependencyType",
                        "Success",
                        "SyntheticSource",
                    )
                }
            )
            evidence = _evidence_record(
                pair=pair,
                scope=trusted_scope,
                batch_generation=batch_generation,
                source="azure-monitor:AppDependencies",
                source_system="AppDependencies",
                origin_fingerprint=fingerprint,
                original_source_generation_id=original_generation,
                observed_at=monitor_time,
                expires_at=monitor_time + max_age,
                supports=bool(
                    generation_binding_verified and fresh and valid_generation
                ),
                uncertainty=(
                    ""
                    if generation_binding_verified and fresh and valid_generation
                    else _reason(
                        fresh=fresh,
                        generation_valid=valid_generation,
                        generation_bound=generation_binding_verified,
                    )
                ),
                lineage={
                    "telemetry_resource_id": emitter_resource,
                    "app_role_name_hash": _fingerprint(row.get("AppRoleName")),
                    "target_binding_hash": _fingerprint(row.get("Target")),
                    "dependency_type": str(row.get("DependencyType") or "")[:64],
                    "success": row.get("Success"),
                    "operation_id_hash": _fingerprint(row.get("OperationId")),
                },
            )
            _add_fact(facts, pair_origins, pair, evidence)
            if not evidence["supports"]:
                uncertainties.add(str(evidence["uncertainty"]))

    if len(facts) > _MAX_PROJECTED_SOURCE_FACTS or len(pair_origins) > _MAX_PROJECTED_SOURCE_FACTS:
        raise ValueError("dependency projection exceeds the bounded source-fact limit")
    evidence_records = sorted(facts.values(), key=lambda item: item["evidence_id"])
    candidate_pairs = []
    for pair in sorted(pair_origins):
        evidence_ids = sorted(pair_origins[pair])
        independent_sources = {
            facts[evidence_id]["source"] for evidence_id in evidence_ids
        }
        if len(independent_sources) < 2:
            uncertainties.add("dependency_pair_single_source_only")
        candidate_pairs.append(
            {
                "pair_id": "|".join(pair),
                "scope": trusted_scope,
                "subject_id": pair[0],
                "subject_type": "Application",
                "predicate": pair[1],
                "object_id": pair[2],
                "object_type": "Application",
                "evidence_ids": evidence_ids,
            }
        )

    return {
        "changed_entities": [
            {
                **dict(entity),
                "scope": trusted_scope,
                "entity_id": _identity(
                    entity.get("resource_id") or entity.get("entity_id")
                ),
            }
            for entity in entities
            if str(entity.get("entity_type") or "").casefold() == "application"
            and str(entity.get("scope") or trusted_scope).casefold()
            == trusted_scope.casefold()
        ],
        "candidate_pairs": candidate_pairs,
        "evidence_records": evidence_records,
        "source_generation_id": batch_generation,
        "observed_at": observed_at,
        "freshness": "current",
        "coverage": (
            "complete"
            if monitor_rows is not None
            and generation_binding_verified
            and not uncertainties
            else "degraded"
        ),
        "uncertainties": sorted(uncertainties),
        "source_generations": {
            "inventory": inventory_generation,
            "monitor": monitor_generation,
        },
    }


def _add_fact(
    facts: dict[str, dict[str, Any]],
    pair_origins: dict[tuple[str, str, str], set[str]],
    pair: tuple[str, str, str],
    evidence: dict[str, Any],
) -> None:
    key = (
        evidence["source"],
        evidence["source_generation_id"],
        "|".join(pair),
    )
    evidence_id = "E-" + _fingerprint(key)[:24]
    evidence["evidence_id"] = evidence_id
    evidence["entity_ids"] = [pair[0], pair[2]]
    existing = facts.get(evidence_id)
    if existing is None:
        facts[evidence_id] = evidence
    elif existing["origin_fingerprint"] == evidence["origin_fingerprint"]:
        # Duplicate delivery of an identical source fact is one observation.
        return
    elif (
        (evidence["supports"] and not existing["supports"])
        or (
            evidence["supports"] == existing["supports"]
            and evidence["observed_at"] > existing["observed_at"]
        )
        or (
            evidence["supports"] == existing["supports"]
            and evidence["observed_at"] == existing["observed_at"]
            and evidence["origin_fingerprint"] < existing["origin_fingerprint"]
        )
    ):
        # Same source system is never independent corroboration. Keep only the
        # freshest supported fact for that source/pair, avoiding multiplicity
        # inflation and preserving its exact original fingerprint.
        facts[evidence_id] = evidence
    pair_origins[pair].add(evidence_id)


def _evidence_record(
    *,
    pair: tuple[str, str, str],
    scope: str,
    batch_generation: str,
    source: str,
    source_system: str,
    origin_fingerprint: str,
    original_source_generation_id: str,
    observed_at: datetime,
    expires_at: datetime,
    supports: bool,
    uncertainty: str,
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "scope": scope,
        "subject_id": pair[0],
        "subject_type": "Application",
        "predicate": pair[1],
        "object_id": pair[2],
        "object_type": "Application",
        "source": source,
        "source_system": source_system,
        "origin_fingerprint": origin_fingerprint,
        "source_generation_id": batch_generation,
        "original_source_generation_id": original_source_generation_id,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "expires_at": expires_at.astimezone(UTC).isoformat(),
        "freshness": "fresh" if supports else "stale_or_unbound",
        "supports": supports,
        "contradicts": False,
        "uncertainty": uncertainty,
        "lineage": dict(lineage),
    }


def _bindings(
    values: Mapping[str, str | Iterable[str]],
) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for raw_label, raw_ids in values.items():
        label = str(raw_label or "").strip().casefold()
        candidates = (
            [raw_ids]
            if isinstance(raw_ids, str)
            else list(raw_ids)
        )
        normalized = {_identity(value) for value in candidates if _identity(value)}
        if label:
            resolved = next(iter(normalized)) if len(normalized) == 1 else None
            if label not in result:
                result[label] = resolved
            elif result[label] != resolved:
                result[label] = None
    return result


def _resolve_binding(bindings: Mapping[str, str | None], label: object) -> str:
    value = bindings.get(str(label or "").strip().casefold())
    return value or ""


def _inventory_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("payload_json", row.get("payload", row))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, Mapping) else {}


def _tags(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("tags") or payload.get("Tags") or {}
    return value if isinstance(value, Mapping) else {}


def _inventory_timestamp(row: Mapping[str, Any], default: datetime) -> datetime | None:
    value = row.get("observed_at")
    if value is None or value == "":
        value = row.get("timestamp")
    return _timestamp(value, default)


def _timestamp(value: object, default: datetime | None) -> datetime | None:
    if value is None or value == "":
        return default
    if not isinstance(value, (str, datetime)):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _fresh(
    observed_at: datetime | None, now: datetime, max_age: timedelta
) -> bool:
    if observed_at is None:
        return False
    age = now.astimezone(UTC) - observed_at.astimezone(UTC)
    return timedelta(0) <= age <= max_age


def _reason(
    *, fresh: bool, generation_valid: bool, generation_bound: bool
) -> str:
    if not fresh:
        return "source_observation_stale_or_timestamp_invalid"
    if not generation_valid:
        return "source_generation_mismatch"
    if not generation_bound:
        return "source_generation_binding_unverified"
    return ""


def _synthetic(value: object) -> bool:
    return str(value or "").strip().casefold() in {"true", "1", "yes"}


def _subscription_in_scope(scope: str, subscription_id: str) -> bool:
    normalized = scope.casefold()
    return any(
        part.strip().casefold() == subscription_id
        for part in normalized.replace(":", "/").split("/")
    )


def _inventory_resource_in_scope(
    resource_id: str, row: Mapping[str, Any], scope: str
) -> bool:
    scope_parts = [
        part.strip().casefold()
        for part in scope.replace(":", "/").split("/")
        if part.strip()
    ]
    expected_subscription = scope_parts[1] if len(scope_parts) > 1 else ""
    supplied_subscription = str(
        row.get("subscription_id") or row.get("subscriptionId") or ""
    ).strip().casefold()
    if supplied_subscription and supplied_subscription != expected_subscription:
        return False
    segments = [part for part in resource_id.split("/") if part]
    lowered = [part.casefold() for part in segments]
    if "subscriptions" in lowered:
        index = lowered.index("subscriptions")
        return (
            index + 1 < len(segments)
            and segments[index + 1].casefold() == expected_subscription
        )
    return bool(supplied_subscription and supplied_subscription == expected_subscription)


def _identity(value: object) -> str:
    return str(value or "").strip().casefold()


def _required(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


__all__ = ["project_application_dependency_evidence"]
