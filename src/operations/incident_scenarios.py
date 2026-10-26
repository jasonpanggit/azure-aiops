"""Bounded Package C evidence projections; correlation never establishes cause."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

SCENARIOS = ("recent_change", "incident_impact")
INCIDENT_INVESTIGATION = {
    "version": "1",
    "owners": ["incident", "change", "resource_health_observability"],
    "allowed_tools": ["incidents"],
    "parameters": ["scenario", "resource_id", "since", "until"],
    "required_evidence": [
        "change_projection",
        "alert_projection",
        "health_history",
        "dependencies",
    ],
    "limits": {
        "window_days": 7,
        "timeline_rows": 50,
        "dependency_depth": 1,
        "dependencies": 10,
    },
    "output_schema": [
        "timeline",
        "hypotheses",
        "impact",
        "coverage",
        "unknowns",
        "next_checks",
    ],
}


def instant(value: Any) -> datetime:
    """Parse an explicit timezone-qualified observation, never substitute now."""
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Investigation timestamps require an explicit timezone")
    try:
        return parsed.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError(
            "Investigation timestamp is outside the supported UTC range"
        ) from exc


def validate_parameters(args: Mapping[str, Any]) -> tuple[str, datetime, datetime]:
    """Require one resource and a chronological window no longer than seven days."""
    if args.get("scenario") not in SCENARIOS:
        raise ValueError("Unknown incident investigation scenario")
    resource_id = str(args.get("resource_id") or "").strip().rstrip("/")
    parts = resource_id.split("/")
    if (
        len(parts) < 9
        or parts[0] != ""
        or parts[1].casefold() != "subscriptions"
        or not parts[2]
        or parts[3].casefold() != "resourcegroups"
        or not parts[4]
        or parts[5].casefold() != "providers"
        or any(not part for part in parts[6:])
        or len(parts) % 2 != 1
        or len(resource_id) > 2048
        or any(
            not re.fullmatch(r"[A-Za-z0-9_.() -]+", part) or part in {".", ".."}
            for part in parts[1:]
        )
    ):
        raise ValueError("Investigation requires a resource ARM id")
    start, end = instant(args.get("since")), instant(args.get("until"))
    if not start < end or end - start > timedelta(days=7):
        raise ValueError(
            "Investigation window must be chronological and at most seven days"
        )
    if args.get("incident_id"):
        raise ValueError("Scenario resource/window cannot be combined with incident_id")
    return resource_id, start, end


def _ref(family: str, identity: Any, timestamp: str, resource: str) -> str:
    digest = hashlib.sha256(
        f"{family}\0{identity}\0{timestamp}\0{resource}".encode()
    ).hexdigest()[:20]
    return f"{family}:{digest}"


def validate_snapshot_binding(args: Mapping[str, Any], snapshot: Any) -> None:
    """Reject a scenario hint that differs from the selected resource/window."""
    validate_parameters(args)
    selected = [
        str(getattr(entity, "resource_id", "")).rstrip("/").casefold()
        for entity in snapshot.selected_entities
    ]
    if selected != [str(args["resource_id"]).rstrip("/").casefold()]:
        raise ValueError("Scenario must match exactly one selected resource")
    for field in ("since", "until"):
        if snapshot.filters.get(field) != [str(args[field]).strip().casefold()]:
            raise ValueError("Scenario window must match selected filters")


def scenario_summary(investigation: Mapping[str, Any]) -> str:
    """Describe only the bounded evidence, identically in canonical/compatibility modes."""
    window = investigation["window"]
    coverage = (
        "Unavailable evidence"
        if investigation["status"] == "unavailable"
        else "Partial coverage"
    )
    return (
        f"{investigation['scenario_id']} for {investigation['resource_id']} "
        f"from {window['since']} through {window['until']}: "
        f"{len(investigation['timeline'])} observed timeline events, "
        f"{len(investigation['hypotheses'])} low-confidence change hypotheses, "
        f"{len(investigation['impact'])} known direct dependencies evaluated. "
        f"{coverage}; temporal proximity is not causality. "
        "History may contain bounded provider observations; completeness is not established. "
        "See the collected evidence for supporting/counterevidence, unknowns and next checks."
    )


def change_projection(engine: Any) -> dict[str, Any]:
    """Read normalized independent changes, omitting arbitrary text/config values."""
    return {
        "observed_at": str(engine.freshness),
        "rows": [
            {
                "identity": row["change_id"],
                "resource_id": row["resource_key"],
                "timestamp": row["changed_at"],
                "kind": "change",
                "configuration": {
                    "status": "withheld",
                    "reason": "Configuration names and values are not retained by this scenario.",
                },
            }
            for row in engine.changes
        ],
    }


def incident_projection(engine: Any) -> dict[str, Any]:
    """Adapt the existing live-alert or normalized snapshot incident facade."""
    from intelligence.incidents.incident_engine import IncidentEngine
    from semantic.live_operations import LiveIncidentEngine

    if isinstance(engine, LiveIncidentEngine):
        rows = []
        invalid = 0
        for raw in engine.rows:
            props = raw.get("properties") or {}
            essentials = props.get("essentials") or props
            resource = essentials.get("targetResource") or essentials.get(
                "targetResourceId"
            )
            timestamp = essentials.get("startDateTime") or essentials.get(
                "firedDateTime"
            )
            if not resource or not timestamp:
                # Do not inherit the ordinary report's freshness/alert-id fallback.
                invalid += 1
                continue
            rows.append(
                {
                    "identity": raw.get("id"),
                    "resource_id": resource,
                    "timestamp": timestamp,
                    "kind": "alert",
                    "status": essentials.get("monitorCondition")
                    or essentials.get("alertState"),
                }
            )
        return {
            "observed_at": engine.freshness,
            "rows": rows,
            "invalid_rows": invalid,
            "contexts": {},
        }
    if not isinstance(engine, IncidentEngine):
        raise TypeError("Unsupported incident evidence projection")
    intelligence = engine.intelligence
    return {
        "observed_at": intelligence.freshness,
        "rows": [
            {
                "identity": row["evidence_id"],
                "resource_id": row["resource_key"],
                "timestamp": row["observed_at"],
                "kind": "alert",
                "status": row.get("status"),
            }
            for row in intelligence.evidence
            if row["evidence_type"] == "Alert"
        ]
        + [
            {
                "identity": row["incident_id"],
                "resource_id": row["resource_key"],
                "timestamp": row["started_at"],
                "kind": "incident",
                "status": row.get("status"),
            }
            for row in intelligence.incidents
        ],
        "contexts": intelligence.analyzer.context_builder,
    }


def investigate(
    args: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    changes: Mapping[str, Any] | None,
    incidents: Mapping[str, Any] | None,
    authorize: Any,
    history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Join one collected evidence bundle with bounded, independently authorized neighbors."""
    resource, start, end = validate_parameters(args)
    resource = str(identity["resource_id"]).rstrip("/")
    root = resource.casefold()
    unknowns = [
        "Temporal proximity is not causality; no causal root cause is established.",
        "Historical metrics and full alert lifecycle remain unavailable; availability transitions do not establish application health.",
        "Activity-log completeness and provider read access are not qualified by projection availability.",
    ]
    coverage = {}
    for family, projection in (("changes", changes), ("alerts", incidents)):
        coverage[family] = {
            "status": "partial" if projection is not None else "unavailable",
            "observed_at": str(projection.get("observed_at") or "")
            if projection
            else "",
            "complete": False,
        }
        if projection is None:
            unknowns.append(
                f"{family.capitalize()} projection unavailable; empty evidence is not proof of absence."
            )
    health = history.get("health") if history else None
    activity = history.get("changes") if history else None
    # Keep snapshot change/alert receipts distinct from native ARM history.
    for family, projection in (("activity_log", activity), ("health", health)):
        coverage[family] = {
            key: value
            for key, value in (projection or {}).items()
            if key != "rows"
        }
        coverage[family].update(
            status=str((projection or {}).get("status") or "unavailable"),
            complete=False,
        )
        if coverage[family]["status"] == "unavailable":
            unknowns.append(f"{family} history unavailable; no absence or health claim is supported.")
        elif projection and (
            projection.get("error_code")
            or projection.get("invalid_rows")
            or not projection.get("pagination_exhausted")
        ):
            unknowns.append(f"{family} history is incomplete, stale, malformed or truncated; inspect its coverage receipt.")
    dependencies = []
    impact_requested = args["scenario"] == "incident_impact"
    contexts = incidents.get("contexts") if incidents and impact_requested else None
    if contexts:
        context = contexts.get(root)
        neighbors = context.get("downstream_dependents") or []
        for neighbor in neighbors[:10]:
            # Friendly-name relationships are not identity authority.
            if not isinstance(neighbor, str) or not neighbor.casefold().startswith(
                "/subscriptions/"
            ):
                unknowns.append(
                    "A dependency lacks an authorizable ARM identity; its identity is withheld."
                )
                continue
            member = authorize(neighbor)
            if member is None:
                unknowns.append(
                    "A dependency is outside authorized inventory or unavailable; its identity is withheld."
                )
                continue
            dependent = str(member["resource_id"]).rstrip("/")
            if dependent.casefold() == root or any(
                row["resource_id"].casefold() == dependent.casefold()
                for row in dependencies
            ):
                continue
            dependencies.append(
                {
                    "resource_id": dependent,
                    "relationship": "known_projection_dependency",
                    "depth": 1,
                    "observed_at": str(incidents.get("observed_at") or ""),
                    "evidence_ref": _ref(
                        "dependency",
                        dependent,
                        str(incidents.get("observed_at") or ""),
                        resource,
                    ),
                }
            )
        if len(neighbors) > 10 or context.get("context_truncated"):
            unknowns.append(
                "Dependency projection/traversal truncated; only the first ten direct neighbors are considered."
            )
    coverage["dependencies"] = {
        "status": ("partial" if contexts else "unavailable")
        if impact_requested
        else "not_requested",
        "complete": False,
        "max_depth": 1,
        "max_neighbors": 10,
        "returned": len(dependencies),
        "observed_at": str(incidents.get("observed_at") or "") if contexts else "",
    }
    if not contexts and impact_requested:
        unknowns.append(
            "Known dependency projection unavailable; no ontology maintenance or inferred edges were requested."
        )
    allowed = {root, *(row["resource_id"].casefold() for row in dependencies)}
    timeline = []
    invalid_rows = 0
    for family, projection in (
        ("changes", changes), ("alerts", incidents),
        ("activity_log", activity), ("health", health),
    ):
        if projection is None:
            continue
        invalid_rows += int(projection.get("invalid_rows") or 0)
        for row in projection.get("rows") or []:
            row_resource = str(row.get("resource_id") or "").rstrip("/")
            if row_resource.casefold() not in allowed:
                continue
            if family == "changes" and row_resource.casefold() != root:
                continue
            try:
                timestamp = instant(row.get("timestamp"))
            except (ValueError, TypeError):
                invalid_rows += 1
                continue
            if not start <= timestamp <= end:
                continue
            status = str(row.get("status") or "").casefold()
            timeline.append(
                {
                    "evidence_ref": _ref(
                        family,
                        row.get("identity"),
                        timestamp.isoformat(),
                        row_resource.casefold(),
                    ),
                    "resource_id": row_resource,
                    "timestamp": timestamp.isoformat(),
                    "kind": row["kind"],
                    "status": status
                    if status
                    in {
                        "fired",
                        "resolved",
                        "active",
                        "closed",
                        "healthy",
                        "degraded",
                        "unhealthy",
                        "succeeded",
                        "failed",
                        "started",
                        "accepted",
                        "canceled",
                    }
                    else "unknown",
                    **(
                        {"configuration": row["configuration"]}
                        if "configuration" in row
                        else {}
                    ),
                    **(
                        {
                            "source": row["source"],
                            "reported_at": row["reported_at"],
                        }
                        if family in {"activity_log", "health"} else {}
                    ),
                }
            )
    timeline.sort(key=lambda row: (row["timestamp"], row["evidence_ref"]))
    if len(timeline) > 50:
        unknowns.append(
            "Timeline truncated to fifty rows; hypotheses use only returned evidence."
        )
    timeline = timeline[:50]
    if invalid_rows:
        unknowns.append(
            "Evidence with missing/invalid timestamps or target identity was excluded; coverage is incomplete."
        )
    symptoms = [
        row
        for row in timeline
        if row["kind"] in {"incident", "alert", "health"}
        and row["status"] in {"fired", "active", "degraded", "unhealthy"}
    ]
    counter = [
        row["evidence_ref"]
        for row in timeline
        if row["resource_id"].casefold() == root
        and row["status"] in {"resolved", "closed", "healthy"}
    ]
    hypotheses = []
    for change in (row for row in timeline if row["kind"] == "change"):
        supporting = [
            row["evidence_ref"]
            for row in symptoms
            if row["resource_id"].casefold() == root
            and row["timestamp"] >= change["timestamp"]
        ]
        opposing = [
            row["evidence_ref"]
            for row in symptoms
            if row["resource_id"].casefold() == root
            and row["timestamp"] < change["timestamp"]
        ] + counter
        hypotheses.append(
            {
                "hypothesis": "Selected-resource change may warrant validation"
                if supporting
                else "Change observed without subsequent supporting symptom in this window",
                "change_ref": change["evidence_ref"],
                "supporting_evidence": [change["evidence_ref"], *supporting],
                "counterevidence": opposing,
                "confidence": "low",
                "causality": "not_established",
                "ranking_basis": "same-resource change preceding supplied symptom"
                if supporting
                else "change only",
                "next_check": "Compare authorized deployment/activity logs and historical metrics before and after the change; validate mechanism and alternative explanations.",
                "_score": int(bool(supporting)) - int(bool(opposing)),
            }
        )
    hypotheses.sort(key=lambda row: (-row["_score"], row["change_ref"]))
    for rank, hypothesis in enumerate(hypotheses[:10], 1):
        hypothesis.pop("_score")
        hypothesis["rank"] = rank
    if not hypotheses:
        unknowns.append(
            "No selected-resource change observed in the returned window; incomplete logs cannot establish that no change occurred."
        )
    if counter and symptoms:
        unknowns.append(
            "Conflicting symptom/recovery evidence is retained; no specialist conclusion overrides it."
        )
    impact = []
    for dependency in dependencies:
        evidence = [
            row["evidence_ref"]
            for row in symptoms
            if row["resource_id"].casefold() == dependency["resource_id"].casefold()
        ]
        impact.append(
            {
                **dependency,
                "impact": "observed_symptom"
                if evidence
                else "inferred_possible_impact",
                "supporting_evidence": [dependency["evidence_ref"], *evidence],
                "counterevidence": [
                    row["evidence_ref"]
                    for row in timeline
                    if row["resource_id"].casefold()
                    == dependency["resource_id"].casefold()
                    and row["status"] in {"resolved", "closed", "healthy"}
                ],
                "confirmed_outage": False,
                "relationship_valid_in_window": "unknown",
            }
        )
    return {
        "scenario_id": args["scenario"],
        "scenario_version": "1",
        "resource_id": resource,
        "window": {"since": start.isoformat(), "until": end.isoformat()},
        "status": "partial"
        if changes is not None or incidents is not None
        or any(
            projection and projection.get("status") == "partial"
            for projection in (activity, health)
        )
        else "unavailable",
        "coverage": coverage,
        "timeline": timeline,
        "hypotheses": hypotheses[:10],
        "impact": impact,
        "unknowns": list(dict.fromkeys(unknowns)),
        "next_checks": [
            "Qualify complete resource/time-scoped activity and change history with authorized read access.",
            "Compare historical health and alert lifecycle evidence, including recovery and missing telemetry.",
            "Validate dependency direction, freshness and actual service symptoms with the owner before asserting impact.",
        ],
        "read_only": True,
        "causality": "not_established",
    }
