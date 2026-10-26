"""Bounded Resource Health scenarios for observability evidence coverage."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeAlias

from api.scope import scope_attributes

DIAGNOSTIC_SETTINGS_COVERAGE = "diagnostic_settings_coverage"
ALERT_DELIVERY_COVERAGE = "alert_delivery_coverage"
OBSERVABILITY_SCENARIOS = frozenset(
    {DIAGNOSTIC_SETTINGS_COVERAGE, ALERT_DELIVERY_COVERAGE}
)


ScopeBinding: TypeAlias = Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class PolicyException:
    """A resource-specific, time-bounded exception to explicit policy items."""

    resource_id: str
    categories: tuple[str, ...]
    destinations: tuple[str, ...]
    expires_at: str


@dataclass(frozen=True)
class DiagnosticSetting:
    """Observed categories and destinations on one resource's setting."""

    resource_id: str
    categories: tuple[str, ...]
    destinations: tuple[str, ...]


@dataclass(frozen=True)
class DiagnosticSettingsEvidence:
    """Scope-bound workload policy and Diagnostic Settings read evidence."""

    scope_binding: ScopeBinding
    supported_resource_types: tuple[str, ...]
    policy_version: str
    policy_observed_at: str
    policy_freshness: str
    policy_complete: bool
    required_categories: Mapping[str, tuple[str, ...]]
    required_destinations: Mapping[str, tuple[str, ...]]
    exceptions: tuple[PolicyException, ...]
    settings_observed_at: str
    settings_freshness: str
    settings_complete: bool
    settings: tuple[DiagnosticSetting, ...]
    unreadable_resource_ids: tuple[str, ...] = ()
    unknown_resource_ids: tuple[str, ...] = ()
    excluded_resource_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertRule:
    """One alert rule and its explicitly classified applicability."""

    rule_id: str
    enabled: bool
    scope_kind: str
    resource_ids: tuple[str, ...]
    action_group_ids: tuple[str, ...]
    requires_action_group: bool = True


@dataclass(frozen=True)
class ActionGroupReference:
    """A target's observed existence and readability in the authorized scope."""

    action_group_id: str
    status: str


@dataclass(frozen=True)
class AlertDeliveryEvidence:
    """Scope-bound alert-rule and Action Group configuration evidence."""

    scope_binding: ScopeBinding
    supported_resource_types: tuple[str, ...]
    rules_observed_at: str
    rules_freshness: str
    rules_complete: bool
    action_groups_observed_at: str
    action_groups_freshness: str
    action_groups_complete: bool
    rules: tuple[AlertRule, ...]
    action_groups: tuple[ActionGroupReference, ...]
    unreadable_resource_ids: tuple[str, ...] = ()
    unknown_resource_ids: tuple[str, ...] = ()
    excluded_resource_ids: tuple[str, ...] = ()


class ObservabilityReadPort(Protocol):
    """Optional, provider-neutral configuration reader; never acquires data itself."""

    def read_diagnostic_settings(self, scope: Any) -> DiagnosticSettingsEvidence: ...

    def read_alert_delivery(self, scope: Any) -> AlertDeliveryEvidence: ...


OBSERVABILITY_SCENARIO_CONTRACT = {
    "version": "1",
    "owner": "resource_health_observability",
    "page": "resource_health",
    "scope": "effective_authorized_scope",
    "existing_tool": "incidents",
    "scenarios": {
        DIAGNOSTIC_SETTINGS_COVERAGE: {
            "required_evidence": [
                "scoped_inventory",
                "workload_logging_policy",
                "diagnostic_settings",
            ],
            "evaluate": ["policy_required_categories", "policy_required_destinations"],
        },
        ALERT_DELIVERY_COVERAGE: {
            "required_evidence": [
                "scoped_inventory",
                "azure_monitor_alert_rules",
                "action_group_references",
            ],
            "evaluate": [
                "disabled_rules",
                "missing_action_group_references",
                "invalid_action_group_references",
            ],
        },
    },
    "limits": {
        "tool_calls": 1,
        "inventory_reads": 1,
        "returned_resource_rows": 0,
        "mutation": False,
    },
    "output_schema": {
        "required": [
            "scenario_id",
            "scenario_version",
            "status",
            "inventory",
            "resource_denominator",
            "policy",
            "configuration_evidence",
            "findings",
            "unknowns",
            "next_checks",
        ],
        "statuses": ["unavailable", "partial", "evaluated"],
    },
}


def validate_parameters(args: Mapping[str, Any]) -> str:
    """Accept exactly one known scenario and no caller-supplied evidence."""
    scenario = args.get("scenario")
    if scenario not in OBSERVABILITY_SCENARIOS:
        raise ValueError("Unknown observability coverage scenario")
    if set(args) != {"scenario"}:
        raise ValueError("Observability coverage accepts only a scenario name")
    return str(scenario)


def unavailable_assessment(
    scenario: str,
    *,
    inventory: Mapping[str, Any] | None = None,
    inventory_issue: str = "",
    evidence: DiagnosticSettingsEvidence | AlertDeliveryEvidence | None = None,
) -> dict[str, Any]:
    """Build an unknown-safe result without implying unsupported provider reads."""
    if scenario not in OBSERVABILITY_SCENARIOS:
        raise ValueError("Unknown observability coverage scenario")

    rows: list[Any] = []
    reported_count: int | None = None
    observed_at: str | None = None
    qualification: Mapping[str, Any] = {}
    inventory_state = "unavailable"
    inventory_warnings: list[str] = []
    if inventory is not None:
        raw_rows = inventory.get("resources")
        raw_count = inventory.get("total")
        raw_qualification = inventory.get("scope_qualification")
        raw_warnings = inventory.get("warnings", [])
        if isinstance(raw_warnings, list):
            inventory_warnings = [str(item) for item in raw_warnings if str(item)]
        else:
            inventory_warnings = ["Inventory warnings were malformed."]
        if (
            isinstance(raw_rows, list)
            and type(raw_count) is int
            and raw_count >= 0
            and isinstance(raw_qualification, Mapping)
        ):
            rows = raw_rows
            reported_count = raw_count
            qualification = raw_qualification
            observed_at = str(inventory.get("observed_at") or "") or None
            inventory_state = (
                "observed"
                if raw_count == len(raw_rows)
                and all(isinstance(row, Mapping) for row in raw_rows)
                and qualification.get("status") == "supported"
                and not inventory_warnings
                else "partial"
            )
        else:
            inventory_state = "partial"

    counts = Counter(
        str(row.get("resource_type") or "unknown").strip().casefold()
        for row in rows
        if isinstance(row, Mapping)
    )
    malformed_rows = sum(not isinstance(row, Mapping) for row in rows)
    observed_count = len(rows) if inventory_state != "unavailable" else None
    scope_qualified = qualification.get("status") == "supported"
    denominator_count = (
        observed_count if scope_qualified and inventory_state == "observed" else None
    )
    scenario_evidence = (
        {
            "workload_logging_policy": "unavailable",
            "diagnostic_settings": "unavailable",
        }
        if scenario == DIAGNOSTIC_SETTINGS_COVERAGE
        else {
            "azure_monitor_alert_rules": "unavailable",
            "action_group_references": "unavailable",
        }
    )
    policy_status = "unavailable"
    policy_version = None
    if isinstance(evidence, DiagnosticSettingsEvidence):
        policy_status = _evidence_status(
            evidence.policy_complete,
            evidence.policy_freshness,
            evidence.policy_observed_at,
        )
        scenario_evidence = {
            "workload_logging_policy": policy_status,
            "diagnostic_settings": _evidence_status(
                evidence.settings_complete,
                evidence.settings_freshness,
                evidence.settings_observed_at,
            ),
        }
        policy_version = evidence.policy_version or None
    elif isinstance(evidence, AlertDeliveryEvidence):
        scenario_evidence = {
            "azure_monitor_alert_rules": _evidence_status(
                evidence.rules_complete,
                evidence.rules_freshness,
                evidence.rules_observed_at,
            ),
            "action_group_references": _evidence_status(
                evidence.action_groups_complete,
                evidence.action_groups_freshness,
                evidence.action_groups_observed_at,
            ),
        }

    limitations = [
        "The active scoped inventory snapshot is not a live or completeness-qualified resource denominator.",
        "No qualified observability configuration reader is configured for this deployment.",
        "Configuration evidence, when available, would not prove telemetry or action delivery.",
    ]
    if scenario == ALERT_DELIVERY_COVERAGE:
        limitations.append(
            "Missing direct resource-scoped alert rules do not establish missing coverage from broader log-query rules."
        )

    return {
        "scenario_id": scenario,
        "scenario_version": OBSERVABILITY_SCENARIO_CONTRACT["version"],
        "status": "unavailable",
        "inventory": {
            "status": inventory_state,
            "observed_resource_count": observed_count,
            "reported_resource_count": reported_count,
            "observed_at": observed_at,
            "freshness": "unknown",
            "complete": False,
            "scope_qualification": dict(qualification)
            if qualification
            else {"status": "unavailable"},
            "resource_type_counts": [
                {"resource_type": resource_type, "count": count}
                for resource_type, count in sorted(counts.items())
            ],
            "malformed_resource_count": malformed_rows,
            "warnings": inventory_warnings,
        },
        "resource_denominator": {
            "status": "unknown",
            "authorized_scope_inventory_count": denominator_count,
            "observed_inventory_count": observed_count,
            "complete": False,
            "supported_resource_types": [],
            "type_support_status": "not_qualified",
            "unsupported_resource_count": None,
            "excluded_resource_count": None,
            "unreadable_observed_resource_count": None,
            "unknown_observed_resource_count": observed_count,
        },
        "policy": {
            "status": policy_status,
            "version": policy_version,
            "required_log_categories": None,
            "required_destinations": None,
            "exception_count": None,
        },
        "configuration_evidence": {
            name: {
                "status": status,
                "observed_at": _source_timestamp(evidence, name),
                "freshness": _source_freshness(evidence, name),
            }
            for name, status in scenario_evidence.items()
        },
        "alert_coverage": (
            {
                "enabled_rule_count": None,
                "disabled_rule_count": None,
                "missing_action_group_reference_count": None,
                "invalid_action_group_reference_count": None,
                "direct_resource_rule_coverage": "not_assessed",
                "indirect_log_query_rule_coverage": "not_assessed",
                "delivery_status": "not_proven",
            }
            if scenario == ALERT_DELIVERY_COVERAGE
            else None
        ),
        "findings": {"status": "not_evaluated", "count": None, "items": []},
        "unknowns": [
            "Required policy/configuration evidence is unavailable; no compliance or delivery conclusion was evaluated.",
            *([inventory_issue] if inventory_issue else []),
        ],
        "next_checks": [
            "Configure a qualified reader for the provider-neutral policy, Diagnostic Settings, Azure Monitor alert-rule, and Action Group evidence contract."
        ],
        "limitations": limitations,
    }


def evaluate_diagnostic_settings(
    inventory: Mapping[str, Any],
    evidence: DiagnosticSettingsEvidence,
    *,
    scope: Any,
) -> dict[str, Any]:
    """Compare qualified observed settings with explicit policy requirements."""
    _require_scope_binding(evidence.scope_binding, scope)
    resources, inventory_info = _inventory_rows(inventory)
    supported = _normalized_values(evidence.supported_resource_types)
    if (
        not supported
        or not _valid_policy(evidence)
        or not _source_ready(
            evidence.policy_complete,
            evidence.policy_freshness,
            evidence.policy_observed_at,
        )
        or not _source_ready(
            evidence.settings_complete,
            evidence.settings_freshness,
            evidence.settings_observed_at,
        )
    ):
        raise ValueError("Diagnostic Settings evidence is incomplete or stale")

    scoped: list[tuple[str, str]] = []
    excluded = 0
    unknown = inventory_info["malformed_resource_count"]
    seen_ids: set[str] = set()
    for row in resources:
        resource_id = _resource_id(row)
        resource_type = _resource_type(row)
        scope_match = _resource_scope_match(row, scope)
        if scope_match is False:
            raise PermissionError(
                "Inventory contains a resource outside the effective scope"
            )
        if scope_match is None:
            unknown += 1
            continue
        if not resource_id or not resource_type:
            unknown += 1
        elif resource_type not in supported:
            excluded += 1
        elif resource_id.casefold() in seen_ids:
            unknown += 1
        else:
            seen_ids.add(resource_id.casefold())
            scoped.append((resource_id.casefold(), resource_type))

    setting_by_resource: dict[str, tuple[set[str], set[str]]] = {}
    for setting in evidence.settings:
        if not isinstance(setting, DiagnosticSetting) or not isinstance(
            setting.resource_id, str
        ):
            raise TypeError("Diagnostic Settings evidence is malformed")
        _require_string_tuple(setting.categories)
        _require_string_tuple(setting.destinations)
        key = setting.resource_id.strip().casefold()
        if not key:
            raise ValueError(
                "Diagnostic Settings evidence contains an empty resource id"
            )
        categories, destinations = setting_by_resource.setdefault(key, (set(), set()))
        categories.update(_normalized_values(setting.categories))
        destinations.update(_normalized_values(setting.destinations))

    unreadable = {
        value.strip().casefold() for value in evidence.unreadable_resource_ids
    }
    unknown_ids = {value.strip().casefold() for value in evidence.unknown_resource_ids}
    excluded_ids = {
        value.strip().casefold() for value in evidence.excluded_resource_ids
    }
    observed_ids = {resource_id for resource_id, _ in scoped}
    unreadable_count = len(unreadable & observed_ids)
    unknown += len(unknown_ids & observed_ids)
    excluded += len(excluded_ids & observed_ids)
    evaluable = [
        (resource_id, resource_type)
        for resource_id, resource_type in scoped
        if resource_id not in unreadable | unknown_ids | excluded_ids
    ]
    active_exceptions = 0
    expired_exceptions = 0
    exceptions_by_resource: dict[str, tuple[set[str], set[str]]] = {}
    for exception in evidence.exceptions:
        if not isinstance(exception, PolicyException) or not isinstance(
            exception.resource_id, str
        ):
            raise TypeError("Policy exception evidence is malformed")
        _require_string_tuple(exception.categories)
        _require_string_tuple(exception.destinations)
        if not exception.resource_id.strip():
            raise ValueError("Policy exception contains an empty resource id")
        expiry = _parse_timestamp(exception.expires_at)
        observed = _parse_timestamp(evidence.policy_observed_at)
        if expiry is None or observed is None:
            raise ValueError("Policy exception or policy timestamp is invalid")
        if expiry < observed:
            expired_exceptions += 1
            continue
        active_exceptions += 1
        categories, destinations = exceptions_by_resource.setdefault(
            exception.resource_id.strip().casefold(), (set(), set())
        )
        categories.update(_normalized_values(exception.categories))
        destinations.update(_normalized_values(exception.destinations))

    category_gaps = 0
    destination_gaps = 0
    findings: list[dict[str, Any]] = []
    for resource_id, resource_type in evaluable:
        configured_categories, configured_destinations = setting_by_resource.get(
            resource_id, (set(), set())
        )
        exempt_categories, exempt_destinations = exceptions_by_resource.get(
            resource_id, (set(), set())
        )
        required_categories = (
            _policy_values(evidence.required_categories, resource_type)
            - exempt_categories
        )
        required_destinations = (
            _policy_values(evidence.required_destinations, resource_type)
            - exempt_destinations
        )
        missing_categories = sorted(required_categories - configured_categories)
        missing_destinations = sorted(required_destinations - configured_destinations)
        category_gaps += len(missing_categories)
        destination_gaps += len(missing_destinations)
        if missing_categories or missing_destinations:
            findings.append(
                {
                    "resource_type": resource_type,
                    "missing_category_count": len(missing_categories),
                    "missing_destination_count": len(missing_destinations),
                    "missing_categories": missing_categories,
                    "missing_destinations": missing_destinations,
                }
            )

    exact_inventory = inventory_info["status"] == "observed"
    complete = (
        exact_inventory
        and inventory_info["freshness"] == "fresh"
        and bool(evaluable)
        and unreadable_count == 0
        and unknown == 0
    )
    count = len(evaluable)
    return {
        **_base_assessment(
            DIAGNOSTIC_SETTINGS_COVERAGE,
            inventory_info,
            supported,
            excluded,
            unreadable_count,
            unknown,
            complete,
        ),
        "status": "evaluated" if complete else "partial",
        "policy": {
            "status": "evaluated",
            "version": evidence.policy_version,
            "required_log_categories": _display_policy(evidence.required_categories),
            "required_destinations": _display_policy(evidence.required_destinations),
            "exception_count": len(evidence.exceptions),
            "active_exception_count": active_exceptions,
            "expired_exception_count": expired_exceptions,
            "observed_at": evidence.policy_observed_at,
            "freshness": evidence.policy_freshness,
        },
        "configuration_evidence": {
            "workload_logging_policy": {
                "status": "evaluated",
                "observed_at": evidence.policy_observed_at,
                "freshness": evidence.policy_freshness,
            },
            "diagnostic_settings": {
                "status": "evaluated",
                "observed_at": evidence.settings_observed_at,
                "freshness": evidence.settings_freshness,
            },
        },
        "diagnostic_settings_coverage": {
            "evaluable_resource_count": count,
            "excluded_resource_count": excluded,
            "unreadable_resource_count": unreadable_count,
            "unknown_resource_count": unknown,
            "freshness": "unknown",
            "missing_category_count": category_gaps,
            "missing_destination_count": destination_gaps,
            "outcome": (
                "gaps_found"
                if category_gaps or destination_gaps
                else "no_gaps_observed"
                if complete
                else "incomplete"
            ),
        },
        "alert_coverage": None,
        "findings": {
            "status": "evaluated" if count else "not_evaluated",
            "count": len(findings),
            "items": findings,
        },
        "unknowns": _inventory_unknowns(inventory_info, unreadable_count, unknown),
        "next_checks": [
            "Confirm any reported configuration gaps against the owning workload before making changes."
        ],
        "limitations": [
            "Observed configuration does not prove telemetry is being emitted or delivered.",
            "Inventory freshness remains unknown because the current InventoryReadPort does not qualify source age.",
        ],
    }


def evaluate_alert_delivery(
    inventory: Mapping[str, Any],
    evidence: AlertDeliveryEvidence,
    *,
    scope: Any,
) -> dict[str, Any]:
    """Evaluate disabled rules and Action Group references without delivery claims."""
    if (
        not isinstance(evidence, AlertDeliveryEvidence)
        or not isinstance(evidence.rules, tuple)
        or not isinstance(evidence.action_groups, tuple)
    ):
        raise TypeError("Alert configuration evidence is malformed")
    _require_scope_binding(evidence.scope_binding, scope)
    resources, inventory_info = _inventory_rows(inventory)
    _require_string_tuple(evidence.supported_resource_types)
    supported = _normalized_values(evidence.supported_resource_types)
    if (
        not supported
        or not _source_ready(
            evidence.rules_complete,
            evidence.rules_freshness,
            evidence.rules_observed_at,
        )
        or not _source_ready(
            evidence.action_groups_complete,
            evidence.action_groups_freshness,
            evidence.action_groups_observed_at,
        )
    ):
        raise ValueError("Alert configuration evidence is incomplete or stale")

    scoped: list[tuple[str, str]] = []
    excluded = 0
    unknown = inventory_info["malformed_resource_count"]
    seen_ids: set[str] = set()
    for row in resources:
        resource_id = _resource_id(row)
        resource_type = _resource_type(row)
        scope_match = _resource_scope_match(row, scope)
        if scope_match is False:
            raise PermissionError(
                "Inventory contains a resource outside the effective scope"
            )
        if scope_match is None:
            unknown += 1
            continue
        if not resource_id or not resource_type:
            unknown += 1
        elif resource_type not in supported:
            excluded += 1
        elif resource_id.casefold() in seen_ids:
            unknown += 1
        else:
            seen_ids.add(resource_id.casefold())
            scoped.append((resource_id.casefold(), resource_type))
    observed_ids = {resource_id for resource_id, _ in scoped}
    unreadable_ids = {
        value.strip().casefold() for value in evidence.unreadable_resource_ids
    }
    unknown_ids = {value.strip().casefold() for value in evidence.unknown_resource_ids}
    excluded_ids = {
        value.strip().casefold() for value in evidence.excluded_resource_ids
    }
    unreadable_count = len(unreadable_ids & observed_ids)
    unknown += len(unknown_ids & observed_ids)
    excluded += len(excluded_ids & observed_ids)
    evaluable_ids = observed_ids - unreadable_ids - unknown_ids - excluded_ids

    action_group_status: dict[str, str] = {}
    for action_group in evidence.action_groups:
        if not isinstance(action_group, ActionGroupReference) or not isinstance(
            action_group.action_group_id, str
        ):
            raise TypeError("Action Group evidence is malformed")
        action_group_id = action_group.action_group_id.strip().casefold()
        if not action_group_id or action_group.status not in {
            "valid",
            "invalid",
            "unknown",
        }:
            raise ValueError("Action Group evidence is malformed")
        if action_group_id in action_group_status:
            raise ValueError("Action Group evidence contains a duplicate reference")
        action_group_status[action_group_id] = action_group.status
    missing_refs = 0
    invalid_refs = 0
    unknown_refs = 0
    disabled_rules = 0
    direct_resource_ids: set[str] = set()
    indirect_rule_count = 0
    unknown_applicability_count = 0
    rule_ids: set[str] = set()
    for rule in evidence.rules:
        if (
            not isinstance(rule, AlertRule)
            or not isinstance(rule.rule_id, str)
            or type(rule.enabled) is not bool
            or not rule.rule_id.strip()
            or type(rule.requires_action_group) is not bool
        ):
            raise ValueError("Alert rule evidence is malformed")
        _require_string_tuple(rule.resource_ids)
        _require_string_tuple(rule.action_group_ids)
        rule_id = rule.rule_id.strip().casefold()
        if rule_id in rule_ids:
            raise ValueError("Alert rule evidence contains a duplicate rule")
        rule_ids.add(rule_id)
        if rule.scope_kind not in {"direct_resource", "log_query", "other", "unknown"}:
            raise ValueError("Alert rule applicability is malformed")
        if not rule.enabled:
            disabled_rules += 1
        elif rule.scope_kind == "direct_resource":
            direct_resource_ids.update(
                value.strip().casefold() for value in rule.resource_ids if value.strip()
            )
        elif rule.scope_kind == "log_query":
            indirect_rule_count += 1
        elif rule.scope_kind == "unknown":
            unknown_applicability_count += 1
        references = _normalized_values(rule.action_group_ids)
        if rule.requires_action_group and not references:
            missing_refs += 1
        for reference in references:
            status = action_group_status.get(reference)
            if status == "invalid":
                invalid_refs += 1
            elif status != "valid":
                unknown_refs += 1

    exact_inventory = inventory_info["status"] == "observed"
    complete = (
        exact_inventory
        and inventory_info["freshness"] == "fresh"
        and bool(evaluable_ids)
        and unreadable_count == 0
        and bool(scoped)
        and unknown == 0
        and unknown_refs == 0
        and unknown_applicability_count == 0
    )
    scoped_ids = evaluable_ids
    direct_covered = len(scoped_ids & direct_resource_ids)
    direct_uncovered = len(scoped_ids - direct_resource_ids)
    return {
        **_base_assessment(
            ALERT_DELIVERY_COVERAGE,
            inventory_info,
            supported,
            excluded,
            unreadable_count,
            unknown,
            complete,
        ),
        "status": "evaluated" if complete else "partial",
        "policy": {
            "status": "not_applicable",
            "version": None,
            "required_log_categories": None,
            "required_destinations": None,
            "exception_count": None,
        },
        "configuration_evidence": {
            "azure_monitor_alert_rules": {
                "status": "evaluated",
                "observed_at": evidence.rules_observed_at,
                "freshness": evidence.rules_freshness,
            },
            "action_group_references": {
                "status": "evaluated" if unknown_refs == 0 else "partial",
                "observed_at": evidence.action_groups_observed_at,
                "freshness": evidence.action_groups_freshness,
            },
        },
        "alert_coverage": {
            "enabled_rule_count": sum(rule.enabled for rule in evidence.rules),
            "disabled_rule_count": disabled_rules,
            "missing_action_group_reference_count": missing_refs,
            "invalid_action_group_reference_count": invalid_refs,
            "unknown_action_group_reference_count": unknown_refs,
            "direct_resource_rule_coverage": {
                "status": "observed",
                "covered_resource_count": direct_covered,
                "direct_rule_missing_count": direct_uncovered,
                "denominator_count": len(evaluable_ids),
            },
            "indirect_log_query_rule_coverage": {
                "status": (
                    "present_not_resource_attributed"
                    if indirect_rule_count
                    else "not_assessed"
                ),
                "rule_count": indirect_rule_count,
            },
            "unknown_applicability_rule_count": unknown_applicability_count,
            "delivery_status": "not_proven",
        },
        "findings": {
            "status": "evaluated",
            "count": disabled_rules + missing_refs + invalid_refs,
            "items": [
                {"kind": "disabled_alert_rule", "count": disabled_rules},
                {"kind": "missing_action_group_reference", "count": missing_refs},
                {"kind": "invalid_action_group_reference", "count": invalid_refs},
            ],
        },
        "unknowns": _inventory_unknowns(inventory_info, unreadable_count, unknown)
        + (
            ["One or more Action Group references could not be qualified."]
            if unknown_refs
            else []
        ),
        "next_checks": [
            "Validate the configured action path with an authorized delivery test; configuration alone does not prove notification delivery."
        ],
        "limitations": [
            "Configured alert rules and Action Group references do not prove telemetry or notification delivery.",
            "A missing direct resource rule does not establish absence of broader log-query coverage.",
            "Inventory freshness remains unknown because the current InventoryReadPort does not qualify source age.",
        ],
    }


def _base_assessment(
    scenario: str,
    inventory: Mapping[str, Any],
    supported: set[str],
    excluded: int,
    unreadable: int,
    unknown: int,
    complete: bool,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario,
        "scenario_version": OBSERVABILITY_SCENARIO_CONTRACT["version"],
        "inventory": inventory,
        "resource_denominator": {
            "status": "observed_snapshot",
            "authorized_scope_inventory_count": (
                inventory["observed_resource_count"]
                if inventory["status"] == "observed"
                and inventory["scope_qualification"].get("status") == "supported"
                else None
            ),
            "observed_inventory_count": inventory["observed_resource_count"],
            "complete": complete,
            "supported_resource_types": sorted(supported),
            "type_support_status": "qualified",
            "unsupported_resource_count": excluded,
            "excluded_resource_count": excluded,
            "unreadable_observed_resource_count": unreadable,
            "unknown_observed_resource_count": unknown,
            "basis": "scoped_inventory_snapshot",
        },
    }


def _inventory_rows(
    inventory: Mapping[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    rows: list[Any] = []
    raw_rows = inventory.get("resources")
    raw_count = inventory.get("total")
    qualification = inventory.get("scope_qualification")
    warnings = inventory.get("warnings", [])
    if (
        isinstance(raw_rows, list)
        and type(raw_count) is int
        and raw_count >= 0
        and isinstance(qualification, Mapping)
    ):
        rows = raw_rows
        state = (
            "observed"
            if raw_count == len(raw_rows)
            and all(isinstance(row, Mapping) for row in raw_rows)
            and qualification.get("status") == "supported"
            and isinstance(warnings, list)
            and not warnings
            else "partial"
        )
    else:
        state = "partial"
    observed_at = str(inventory.get("observed_at") or "")
    return rows, {
        "status": state,
        "observed_resource_count": len(rows) if state != "unavailable" else None,
        "reported_resource_count": raw_count if type(raw_count) is int else None,
        "observed_at": observed_at or None,
        "freshness": "unknown",
        "complete": False,
        "scope_qualification": (
            dict(qualification)
            if isinstance(qualification, Mapping)
            else {"status": "unavailable"}
        ),
        "resource_type_counts": [
            {"resource_type": key, "count": count}
            for key, count in sorted(
                Counter(
                    _resource_type(row) or "unknown"
                    for row in rows
                    if isinstance(row, Mapping)
                ).items()
            )
        ],
        "malformed_resource_count": sum(not isinstance(row, Mapping) for row in rows),
        "warnings": [str(item) for item in warnings if str(item)]
        if isinstance(warnings, list)
        else ["Inventory warnings were malformed."],
    }


def _valid_policy(evidence: DiagnosticSettingsEvidence) -> bool:
    if not isinstance(evidence, DiagnosticSettingsEvidence):
        return False
    if (
        not isinstance(evidence.policy_version, str)
        or not isinstance(evidence.exceptions, tuple)
        or not isinstance(evidence.settings, tuple)
        or not isinstance(evidence.supported_resource_types, tuple)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in evidence.supported_resource_types
        )
    ):
        return False
    supported = _normalized_values(evidence.supported_resource_types)
    categories = _normalize_policy(evidence.required_categories)
    destinations = _normalize_policy(evidence.required_destinations)
    return (
        bool(evidence.policy_version.strip())
        and supported <= categories.keys()
        and supported <= destinations.keys()
    )


def _normalize_policy(
    policy: Mapping[str, tuple[str, ...]],
) -> dict[str, set[str]]:
    if not isinstance(policy, Mapping):
        raise TypeError("Logging policy evidence is malformed")
    result: dict[str, set[str]] = {}
    for resource_type, values in policy.items():
        key = str(resource_type or "").strip().casefold()
        if (
            not key
            or not isinstance(values, tuple)
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise ValueError("Logging policy evidence is malformed")
        result[key] = _normalized_values(values)
    return result


def _policy_values(
    policy: Mapping[str, tuple[str, ...]], resource_type: str
) -> set[str]:
    return _normalize_policy(policy).get(resource_type.casefold(), set())


def _display_policy(
    policy: Mapping[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    normalized = _normalize_policy(policy)
    return [
        {"resource_type": key, "values": sorted(values)}
        for key, values in sorted(normalized.items())
    ]


def _normalized_values(values: Any) -> set[str]:
    if not isinstance(values, (tuple, list)):
        return set()
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _require_string_tuple(values: Any) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError("Observability evidence contains malformed values")


def _resource_id(row: Mapping[str, Any]) -> str:
    return str(row.get("resource_id") or "").strip()


def _resource_type(row: Mapping[str, Any]) -> str:
    return str(row.get("resource_type") or "").strip().casefold()


def _resource_scope_match(row: Mapping[str, Any], scope: Any) -> bool | None:
    if scope.is_unrestricted():
        return True
    attributes = scope_attributes(row)
    for dimension, allowed in scope.dimensions.items():
        value = attributes.get(dimension)
        if not value:
            return None
        if value not in allowed:
            return False
    return True


def _scope_key(binding: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for name, values in binding.items():
        key = str(name).strip().casefold()
        if (
            not isinstance(values, (tuple, list))
            or any(not isinstance(value, str) or not value.strip() for value in values)
            or not key
            or key in normalized
        ):
            raise PermissionError("Observability evidence has an invalid scope binding")
        normalized[key] = tuple(sorted(value.strip().casefold() for value in values))
    return normalized


def _require_scope_binding(binding: ScopeBinding, scope: Any) -> None:
    try:
        matches = (
            isinstance(binding, Mapping)
            and callable(getattr(scope, "to_dict", None))
            and _scope_key(binding) == _scope_key(scope.to_dict())
        )
    except (AttributeError, TypeError, ValueError):
        matches = False
    if not matches:
        raise PermissionError("Observability evidence is bound to a different scope")


def _source_ready(complete: bool, freshness: str, observed_at: str) -> bool:
    return (
        complete is True
        and freshness == "fresh"
        and _parse_timestamp(observed_at) is not None
    )


def _evidence_status(complete: bool, freshness: str, observed_at: str) -> str:
    if not observed_at or _parse_timestamp(observed_at) is None:
        return "unavailable"
    if freshness == "stale":
        return "stale"
    if complete is not True or freshness != "fresh":
        return "partial"
    return "observed"


def _source_timestamp(
    evidence: DiagnosticSettingsEvidence | AlertDeliveryEvidence | None,
    name: str,
) -> str | None:
    if isinstance(evidence, DiagnosticSettingsEvidence):
        return {
            "workload_logging_policy": evidence.policy_observed_at,
            "diagnostic_settings": evidence.settings_observed_at,
        }.get(name)
    if isinstance(evidence, AlertDeliveryEvidence):
        return {
            "azure_monitor_alert_rules": evidence.rules_observed_at,
            "action_group_references": evidence.action_groups_observed_at,
        }.get(name)
    return None


def _source_freshness(
    evidence: DiagnosticSettingsEvidence | AlertDeliveryEvidence | None,
    name: str,
) -> str | None:
    if isinstance(evidence, DiagnosticSettingsEvidence):
        return {
            "workload_logging_policy": evidence.policy_freshness,
            "diagnostic_settings": evidence.settings_freshness,
        }.get(name)
    if isinstance(evidence, AlertDeliveryEvidence):
        return {
            "azure_monitor_alert_rules": evidence.rules_freshness,
            "action_group_references": evidence.action_groups_freshness,
        }.get(name)
    return None


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _inventory_unknowns(
    inventory: Mapping[str, Any], unreadable: int, unknown: int
) -> list[str]:
    issues = []
    if inventory["status"] != "observed":
        issues.append("The scoped inventory collection is partial or unqualified.")
    if unreadable:
        issues.append(f"{unreadable} supported resources were unreadable.")
    if unknown:
        issues.append(f"{unknown} observed resource records are unknown or malformed.")
    issues.append(
        "Inventory is a scoped published snapshot; completeness and freshness for the live Azure estate are not qualified."
    )
    return issues


def scenario_summary(assessment: Mapping[str, Any]) -> str:
    """Summarize bounded evidence without converting it to a healthy result."""
    status = assessment.get("status")
    inventory = assessment.get("inventory")
    count = (
        inventory.get("observed_resource_count")
        if isinstance(inventory, Mapping)
        else None
    )
    denominator = (
        f"{count} scoped inventory identities were observed"
        if type(count) is int
        else "the scoped inventory denominator is unavailable"
    )
    if status == "unavailable":
        detail = (
            "Required policy/configuration evidence was not available, so no "
            "coverage evaluation was completed."
        )
    elif assessment.get("scenario_id") == DIAGNOSTIC_SETTINGS_COVERAGE:
        coverage = assessment.get("diagnostic_settings_coverage", {})
        detail = (
            f"{coverage.get('missing_category_count', 0)} required log categories "
            f"and {coverage.get('missing_destination_count', 0)} destinations "
            "were missing on the evaluable snapshot resources."
        )
    else:
        coverage = assessment.get("alert_coverage", {})
        detail = (
            f"{coverage.get('disabled_rule_count', 0)} disabled alert rules, "
            f"{coverage.get('missing_action_group_reference_count', 0)} missing "
            "and "
            f"{coverage.get('invalid_action_group_reference_count', 0)} invalid "
            "Action Group references were observed."
        )
    return (
        f"{assessment['scenario_id']}: observability coverage is {status}; "
        f"{denominator}. {detail} No live estate completeness, telemetry, or "
        "delivery conclusion is claimed."
    )


__all__ = [
    "ALERT_DELIVERY_COVERAGE",
    "DIAGNOSTIC_SETTINGS_COVERAGE",
    "OBSERVABILITY_SCENARIOS",
    "OBSERVABILITY_SCENARIO_CONTRACT",
    "ActionGroupReference",
    "AlertDeliveryEvidence",
    "AlertRule",
    "DiagnosticSetting",
    "DiagnosticSettingsEvidence",
    "ObservabilityReadPort",
    "PolicyException",
    "evaluate_alert_delivery",
    "evaluate_diagnostic_settings",
    "scenario_summary",
    "unavailable_assessment",
    "validate_parameters",
]
