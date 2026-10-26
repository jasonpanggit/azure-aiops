"""Azure Resource Graph normalization of alert-rule and Action Group configuration.

This reader only reuses the existing connection-scoped live provider; it adds no
credential, ingestion, or inventory path. Diagnostic Settings and workload logging
policy have no governed source, so that scenario stays unavailable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from api.scope import Scope, subscription_ids_for_scope
from onboarding.query_contract import QuerySpec

from .observability_scenarios import (
    ActionGroupReference,
    AlertDeliveryEvidence,
    AlertRule,
    DiagnosticSettingsEvidence,
)

# Resource types whose platform metrics are alertable; a missing direct rule is
# only meaningful for these types.
SUPPORTED_DIRECT_ALERT_RESOURCE_TYPES = (
    "microsoft.compute/virtualmachines",
    "microsoft.web/sites",
    "microsoft.sql/servers/databases",
    "microsoft.storage/storageaccounts",
    "microsoft.keyvault/vaults",
)

_RULE_TYPES = {
    "microsoft.insights/metricalerts",
    "microsoft.insights/scheduledqueryrules",
    "microsoft.insights/activitylogalerts",
}
_ACTION_GROUP_TYPE = "microsoft.insights/actiongroups"
_RULES_QUERY = QuerySpec(
    name="observability_alert_rules",
    table="Resources",
    query=(
        "Resources "
        "| where type in~ ('microsoft.insights/metricalerts', "
        "'microsoft.insights/scheduledqueryrules', "
        "'microsoft.insights/activitylogalerts') "
        "| project id, type, subscriptionId, "
        "enabled=properties.enabled, scopes=properties.scopes, scope=properties.scope, "
        "actions=properties.actions"
    ),
    incremental=False,
    source_family="azure_monitor_alert_rules",
)
_ACTION_GROUPS_QUERY = QuerySpec(
    name="observability_action_groups",
    table="Resources",
    query=(
        "Resources "
        "| where type =~ 'microsoft.insights/actiongroups' "
        "| project id, type, subscriptionId, enabled=properties.enabled"
    ),
    incremental=False,
    source_family="azure_monitor_action_groups",
)
_ENFORCEABLE_DIMENSIONS = {"subscription", "subscription_connection"}


class ObservabilityEvidenceUnavailable(RuntimeError):
    """The requested evidence has no governed source in this runtime."""


class ArgObservabilityReader:
    """Normalize ARG alert-rule and Action Group rows into typed evidence."""

    def __init__(
        self,
        live_resources: Any,
        connections: Callable[[], Iterable[Any]],
        *,
        clock: Callable[[], datetime] | None = None,
        freshness_seconds: int = 900,
    ) -> None:
        self._live = live_resources
        self._connections = connections
        self._clock = clock or (lambda: datetime.now(UTC))
        self._freshness_seconds = freshness_seconds

    def read_diagnostic_settings(self, scope: Any) -> DiagnosticSettingsEvidence:
        raise ObservabilityEvidenceUnavailable(
            "No governed workload logging policy or Diagnostic Settings source exists."
        )

    def read_alert_delivery(self, scope: Any) -> AlertDeliveryEvidence:
        subscriptions = self._authorized_subscriptions(scope)
        rule_obs = self._live.query(_RULES_QUERY, subscription_ids=subscriptions)
        group_obs = self._live.query(
            _ACTION_GROUPS_QUERY, subscription_ids=subscriptions
        )
        allowed = {value.casefold() for value in subscriptions}
        rule_rows = self._rows(rule_obs, allowed)
        group_rows = self._rows(group_obs, allowed)
        rules = tuple(self._rule(row, allowed) for row in rule_rows)
        groups = tuple(self._group(row) for row in group_rows)
        known_groups = {group.action_group_id.casefold() for group in groups}
        group_complete = self._complete(group_obs, subscriptions)
        group_fresh = self._freshness(group_obs.observed_at) == "fresh"
        references = self._references(
            rule_rows,
            known_groups,
            allowed,
            absence_is_authoritative=group_complete and group_fresh,
        )
        # The typed rule cannot carry an unknown enabled state; an unclassifiable
        # rule makes the whole rule collection incomplete rather than a finding.
        rules_complete = self._complete(rule_obs, subscriptions) and all(
            self._classifiable(row) for row in rule_rows
        )
        return AlertDeliveryEvidence(
            scope_binding={
                key: tuple(values) for key, values in scope.to_dict().items()
            },
            supported_resource_types=SUPPORTED_DIRECT_ALERT_RESOURCE_TYPES,
            rules_observed_at=str(rule_obs.observed_at or ""),
            rules_freshness=self._freshness(rule_obs.observed_at),
            rules_complete=rules_complete,
            action_groups_observed_at=str(group_obs.observed_at or ""),
            action_groups_freshness=self._freshness(group_obs.observed_at),
            action_groups_complete=group_complete,
            rules=rules,
            action_groups=tuple(
                {
                    ref.action_group_id.casefold(): ref
                    for ref in (*groups, *references)
                }.values()
            ),
        )

    def _authorized_subscriptions(self, scope: Any) -> list[str]:
        if not isinstance(scope, Scope):
            raise PermissionError("Observability reads require an effective scope")
        if set(scope.dimensions) - _ENFORCEABLE_DIMENSIONS:
            raise ValueError(
                "Alert evidence cannot enforce scope dimensions beyond subscription."
            )
        subscriptions = subscription_ids_for_scope(
            scope, list(self._connections()), default_all=scope.is_unrestricted()
        )
        if not subscriptions:
            raise ValueError("No authorized subscription is in scope")
        return subscriptions

    def _complete(self, observation: Any, subscriptions: list[str]) -> bool:
        active = {
            str(getattr(connection, "subscription_id", "")).casefold()
            for connection in self._connections()
            if getattr(connection, "is_active", True)
        }
        return (
            getattr(observation, "completeness", "") in {"complete", "healthy-empty"}
            and getattr(observation, "status", "") == "ok"
            and {value.casefold() for value in subscriptions} <= active
        )

    def _freshness(self, observed_at: Any) -> str:
        try:
            observed = datetime.fromisoformat(str(observed_at))
        except ValueError:
            return "unknown"
        if observed.tzinfo is None:
            return "unknown"
        age = (self._clock() - observed).total_seconds()
        if age < -60:
            return "unknown"
        return "fresh" if age <= self._freshness_seconds else "stale"

    @staticmethod
    def _rows(observation: Any, allowed: set[str]) -> list[Mapping[str, Any]]:
        rows = list(getattr(observation, "rows", ()))
        for row in rows:
            if not isinstance(row, Mapping):
                raise TypeError("Alert configuration row is malformed")
            if str(row.get("subscriptionId") or "").casefold() not in allowed:
                raise PermissionError("Alert configuration row is outside scope")
        return rows

    @staticmethod
    def _group_ids(actions: Any) -> tuple[str, ...]:
        if isinstance(actions, Mapping):
            actions = actions.get("actionGroups")
        if not isinstance(actions, list):
            return ()
        ids = []
        for item in actions:
            value = item.get("actionGroupId") if isinstance(item, Mapping) else item
            if isinstance(value, str) and value.strip():
                ids.append(value.strip())
        return tuple(ids)

    @staticmethod
    def _scope_ids(row: Mapping[str, Any]) -> tuple[str, ...]:
        """Read plural `scopes` or the singular `scope` some rule types use."""
        raw = row.get("scopes")
        if not isinstance(raw, list):
            raw = row.get("scope")
        if isinstance(raw, str):
            raw = [raw]
        return tuple(
            value.strip()
            for value in (raw if isinstance(raw, list) else ())
            if isinstance(value, str) and value.strip()
        )

    @staticmethod
    def _classifiable(row: Mapping[str, Any]) -> bool:
        return (
            str(row.get("type") or "").casefold() in _RULE_TYPES
            and type(row.get("enabled")) is bool
        )

    def _rule(self, row: Mapping[str, Any], allowed: set[str]) -> AlertRule:
        rule_type = str(row.get("type") or "").casefold()
        enabled = row.get("enabled")
        scope_ids = self._scope_ids(row)
        if rule_type not in _RULE_TYPES or type(enabled) is not bool:
            kind = "unknown"
            # Placeholder only: the collection is marked incomplete so this
            # rule is never evaluated as a disabled-rule finding.
            enabled = True
        elif rule_type == "microsoft.insights/scheduledqueryrules":
            kind = "log_query"
        elif rule_type == "microsoft.insights/metricalerts":
            kind = (
                "direct_resource"
                if scope_ids and all(_is_resource_id(value) for value in scope_ids)
                else "other"
            )
        else:
            kind = "other"
        return AlertRule(
            rule_id=str(row.get("id") or ""),
            enabled=enabled,
            scope_kind=kind,
            resource_ids=scope_ids if kind == "direct_resource" else (),
            action_group_ids=self._group_ids(row.get("actions")),
        )

    @staticmethod
    def _group(row: Mapping[str, Any]) -> ActionGroupReference:
        enabled = row.get("enabled")
        status = (
            "unknown"
            if type(enabled) is not bool
            else ("valid" if enabled else "invalid")
        )
        return ActionGroupReference(str(row.get("id") or ""), status)

    def _references(
        self,
        rule_rows: list[Mapping[str, Any]],
        known: set[str],
        allowed: set[str],
        *,
        absence_is_authoritative: bool,
    ) -> list[ActionGroupReference]:
        """Classify referenced groups absent from the read set."""
        refs: list[ActionGroupReference] = []
        for row in rule_rows:
            for group_id in self._group_ids(row.get("actions")):
                if group_id.casefold() in known:
                    continue
                subscription = _subscription_of(group_id)
                # Absence proves invalidity only inside authorized subscriptions
                # and only when the Action Group collection is complete and fresh.
                status = (
                    "invalid"
                    if absence_is_authoritative and subscription in allowed
                    else "unknown"
                )
                refs.append(ActionGroupReference(group_id, status))
        return refs


def _segments(value: str) -> list[str]:
    return [segment for segment in value.split("/") if segment]


def _is_resource_id(value: str) -> bool:
    parts = _segments(value.casefold())
    return len(parts) >= 8 and parts[0] == "subscriptions" and "providers" in parts


def _subscription_of(value: str) -> str:
    parts = _segments(value.casefold())
    return parts[1] if len(parts) > 1 and parts[0] == "subscriptions" else ""
