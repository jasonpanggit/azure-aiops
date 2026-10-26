"""Scope-bound Azure Monitor alert and Diagnostic Settings evidence readers.

Alert rules use the existing connection-scoped Resource Graph provider.
Diagnostic Settings reuse the already-read inventory denominator and each
resource's existing authorized connection credential; no second inventory
acquisition or destination-resource traversal is performed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from api.scope import Scope, scope_attributes, subscription_ids_for_scope
from onboarding.azure_clients import DiagnosticSettingsReadError
from onboarding.query_contract import QuerySpec

from .observability_scenarios import (
    ActionGroupReference,
    AlertDeliveryEvidence,
    AlertRule,
    DiagnosticSetting,
    DiagnosticSettingsEvidence,
)
from .workload_logging_policy import (
    WorkloadLoggingPolicyStore,
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
    """Read scope-bound Azure Monitor configuration into typed evidence."""

    def __init__(
        self,
        live_resources: Any,
        connections: Callable[[], Iterable[Any]],
        *,
        clock: Callable[[], datetime] | None = None,
        freshness_seconds: int = 900,
        diagnostic_client_factory: Callable[[Any], Any] | None = None,
        logging_policy_store: WorkloadLoggingPolicyStore | None = None,
        max_diagnostic_resources: int = 250,
    ) -> None:
        if freshness_seconds < 1 or max_diagnostic_resources < 1:
            raise ValueError("Observability reader bounds must be positive")
        self._live = live_resources
        self._connections = connections
        self._clock = clock or (lambda: datetime.now(UTC))
        self._freshness_seconds = freshness_seconds
        self._diagnostic_client_factory = diagnostic_client_factory
        self._logging_policy_store = logging_policy_store
        self._max_diagnostic_resources = max_diagnostic_resources

    def read_diagnostic_settings(
        self, scope: Any, inventory: Mapping[str, Any]
    ) -> DiagnosticSettingsEvidence:
        """Read settings for the already-authorized inventory snapshot."""
        if (
            self._diagnostic_client_factory is None
            or self._logging_policy_store is None
        ):
            raise ObservabilityEvidenceUnavailable(
                "The governed workload logging policy or ARM reader is not configured."
            )
        connections = list(self._connections())
        subscriptions = self._authorized_subscriptions(
            scope,
            connections=connections,
            allow_inventory_scopes=True,
        )
        policy = self._logging_policy_store.read(subscription_ids=subscriptions)
        settings_started_at = self._clock().astimezone(UTC)
        supported = set(policy.supported_resource_types)
        rows = inventory.get("resources")
        total = inventory.get("total")
        warnings = inventory.get("warnings")
        qualification = inventory.get("scope_qualification")
        if not isinstance(rows, list) or type(total) is not int or total < 0:
            raise ValueError("The existing inventory denominator is malformed")
        snapshot_complete = (
            len(rows) == total
            and isinstance(qualification, Mapping)
            and qualification.get("status") == "supported"
            and isinstance(warnings, list)
            and not warnings
            and all(isinstance(row, Mapping) for row in rows)
        )
        allowed = {value.casefold() for value in subscriptions}
        scoped_rows: list[tuple[str, str, str]] = []
        unknown_ids: set[str] = set()
        excluded_ids: set[str] = set()
        seen_ids: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            resource_id = str(row.get("resource_id") or "").strip()
            resource_type = str(row.get("resource_type") or "").strip().casefold()
            subscription_id = _subscription_of(resource_id)
            declared_subscription = str(
                row.get("subscription_id") or row.get("subscriptionId") or ""
            ).casefold()
            if declared_subscription and declared_subscription != subscription_id:
                raise PermissionError(
                    "Inventory subscription metadata conflicts with the resource ID"
                )
            attributes = scope_attributes(row)
            if subscription_id and subscription_id not in allowed:
                raise PermissionError(
                    "Inventory contains a resource outside the effective subscription scope"
                )
            if not scope.is_unrestricted() and attributes:
                if not scope.matches(attributes):
                    raise PermissionError(
                        "Inventory contains a resource outside the effective scope"
                    )
            elif not scope.is_unrestricted() and not attributes:
                if resource_id:
                    unknown_ids.add(resource_id)
                continue
            if not resource_id or not subscription_id or not resource_type:
                if resource_id:
                    unknown_ids.add(resource_id)
                continue
            if resource_id.casefold() in seen_ids:
                unknown_ids.add(resource_id)
                continue
            seen_ids.add(resource_id.casefold())
            if resource_type not in supported:
                excluded_ids.add(resource_id)
                continue
            scoped_rows.append((resource_id, resource_type, subscription_id))

        connection_by_subscription: dict[str, list[Any]] = {}
        for connection in connections:
            if getattr(connection, "is_active", True):
                connection_by_subscription.setdefault(
                    str(getattr(connection, "subscription_id", "")).casefold(), []
                ).append(connection)
        target_rows = scoped_rows[: self._max_diagnostic_resources]
        if len(scoped_rows) > len(target_rows):
            unknown_ids.update(row[0] for row in scoped_rows[len(target_rows) :])
            snapshot_complete = False

        client_by_subscription: dict[str, Any] = {}
        failed_subscriptions: set[str] = set()
        settings: list[DiagnosticSetting] = []
        unreadable_ids: set[str] = set()
        for resource_id, _resource_type, subscription_id in target_rows:
            if subscription_id in failed_subscriptions:
                unreadable_ids.add(resource_id)
                continue
            candidates = connection_by_subscription.get(subscription_id, [])
            if len(candidates) != 1:
                unreadable_ids.add(resource_id)
                continue
            try:
                client = client_by_subscription.get(subscription_id)
                if client is None:
                    client = self._diagnostic_client_factory(candidates[0])
                    client_by_subscription[subscription_id] = client
                raw_settings = client.list_resource_settings(
                    resource_id,
                    authorized_subscription_ids={subscription_id},
                )
                settings.extend(
                    _normalize_diagnostic_setting(item, resource_id)
                    for item in raw_settings
                )
            except DiagnosticSettingsReadError as exc:
                if exc.status_code in {401, 403}:
                    unreadable_ids.add(resource_id)
                    if exc.status_code == 401:
                        failed_subscriptions.add(subscription_id)
                else:
                    unknown_ids.add(resource_id)
            except PermissionError:
                raise
            except (TypeError, ValueError):
                unknown_ids.add(resource_id)
            except (LookupError, OSError, RuntimeError):
                unreadable_ids.add(resource_id)
                failed_subscriptions.add(subscription_id)

        settings_observed_at = settings_started_at.isoformat().replace("+00:00", "Z")
        settings_freshness = self._freshness(settings_observed_at)
        return DiagnosticSettingsEvidence(
            scope_binding={
                key: tuple(values) for key, values in scope.to_dict().items()
            },
            supported_resource_types=policy.supported_resource_types,
            policy_version=policy.version,
            policy_observed_at=policy.observed_at,
            policy_freshness=policy.freshness,
            policy_complete=policy.complete,
            required_categories=policy.required_categories,
            required_destinations=policy.required_destinations,
            exceptions=policy.exceptions,
            settings_observed_at=settings_observed_at,
            settings_freshness=settings_freshness,
            settings_complete=(
                snapshot_complete and not unreadable_ids and not unknown_ids
            ),
            settings=tuple(settings),
            unreadable_resource_ids=tuple(sorted(unreadable_ids)),
            unknown_resource_ids=tuple(sorted(unknown_ids)),
            excluded_resource_ids=tuple(sorted(excluded_ids)),
            policy_id=policy.policy_id,
            policy_approved_by=policy.approved_by,
            policy_approved_at=policy.approved_at,
            policy_revision=policy.revision,
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
        group_fresh = self._observation_freshness(group_obs) == "fresh"
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
            rules_freshness=self._observation_freshness(rule_obs),
            rules_complete=rules_complete,
            action_groups_observed_at=str(group_obs.observed_at or ""),
            action_groups_freshness=self._observation_freshness(group_obs),
            action_groups_complete=group_complete,
            rules=rules,
            action_groups=tuple(
                {
                    ref.action_group_id.casefold(): ref
                    for ref in (*groups, *references)
                }.values()
            ),
        )

    def _authorized_subscriptions(
        self,
        scope: Any,
        *,
        connections: list[Any] | None = None,
        allow_inventory_scopes: bool = False,
    ) -> list[str]:
        if not isinstance(scope, Scope):
            raise PermissionError("Observability reads require an effective scope")
        if (
            not allow_inventory_scopes
            and set(scope.dimensions) - _ENFORCEABLE_DIMENSIONS
        ):
            raise ValueError(
                "Alert evidence cannot enforce scope dimensions beyond subscription."
            )
        connection_rows = (
            connections if connections is not None else list(self._connections())
        )
        subscriptions = subscription_ids_for_scope(
            scope, connection_rows, default_all=scope.is_unrestricted()
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
        source_status = getattr(observation, "source_status", ())
        source_status_complete = not source_status or (
            all(
                getattr(item, "status", "") == "succeeded"
                and getattr(item, "completeness", "") in {"complete", "healthy-empty"}
                and type(getattr(item, "represented_count", None)) is int
                and type(getattr(item, "expected_count", None)) is int
                and item.represented_count == item.expected_count
                for item in source_status
            )
            and (
                not getattr(observation, "expected_count", 0)
                or len(source_status) == getattr(observation, "expected_count", 0)
            )
            and sum(item.represented_count for item in source_status)
            == getattr(observation, "represented_count", 0)
        )
        represented = getattr(observation, "represented_count", 0)
        expected = getattr(observation, "expected_count", 0)
        counts_match = represented == expected if represented or expected else True
        return (
            getattr(observation, "completeness", "") in {"complete", "healthy-empty"}
            and getattr(observation, "status", "") == "ok"
            and {value.casefold() for value in subscriptions} <= active
            and counts_match
            and source_status_complete
        )

    def _observation_freshness(self, observation: Any) -> str:
        source_status = getattr(observation, "source_status", ())
        if not source_status:
            return self._freshness(getattr(observation, "observed_at", ""))
        states = [
            self._freshness(getattr(item, "observed_at", ""))
            for item in source_status
            if getattr(item, "status", "") == "succeeded"
        ]
        if len(states) != len(source_status) or not states:
            return "unknown"
        if "stale" in states:
            return "stale"
        return "fresh" if all(state == "fresh" for state in states) else "unknown"

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
            resource_id = row.get("id")
            if not isinstance(resource_id, str) or not _is_resource_id(resource_id):
                raise TypeError("Alert configuration resource ID is malformed")
            declared_subscription = str(row.get("subscriptionId") or "").casefold()
            resource_subscription = _subscription_of(resource_id)
            if (
                declared_subscription != resource_subscription
                or resource_subscription not in allowed
            ):
                raise PermissionError("Alert configuration row is outside scope")
        return rows

    @staticmethod
    def _group_ids(actions: Any) -> tuple[str, ...]:
        if actions is None:
            return ()
        if isinstance(actions, Mapping):
            actions = actions.get("actionGroups", [])
            if actions is None:
                return ()
        if not isinstance(actions, list):
            raise TypeError("Alert rule Action Group configuration is malformed")
        ids = []
        for item in actions:
            value = item.get("actionGroupId") if isinstance(item, Mapping) else item
            if not isinstance(value, str) or not value.strip():
                raise TypeError("Alert rule Action Group reference is malformed")
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
        rule_type = str(row.get("type") or "").casefold()
        return (
            rule_type in _RULE_TYPES
            and type(row.get("enabled")) is bool
            and "actions" in row
            and (
                rule_type != "microsoft.insights/metricalerts"
                or bool(ArgObservabilityReader._scope_ids(row))
            )
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
            kind = "unknown" if not scope_ids else (
                "direct_resource"
                if all(_is_resource_id(value) for value in scope_ids)
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
        if str(row.get("type") or "").casefold() != _ACTION_GROUP_TYPE:
            raise TypeError("Action Group source returned a different resource type")
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


def _normalize_diagnostic_setting(
    row: Mapping[str, Any],
    resource_id: str,
) -> DiagnosticSetting:
    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        raise TypeError("Diagnostic Settings properties are malformed")
    logs = properties.get("logs")
    if not isinstance(logs, list):
        raise TypeError("Diagnostic Settings log categories are malformed")
    categories: list[str] = []
    for entry in logs:
        if not isinstance(entry, Mapping) or type(entry.get("enabled")) is not bool:
            raise TypeError("Diagnostic Settings log category is malformed")
        if not entry["enabled"]:
            continue
        if entry.get("categoryGroup"):
            raise ValueError(
                "Diagnostic category groups require a qualified category expansion"
            )
        category = entry.get("category")
        if not isinstance(category, str) or not category.strip():
            raise TypeError("Enabled Diagnostic Settings category is unnamed")
        categories.append(category.strip())
    destinations: list[str] = []
    for key, prefix in (
        ("workspaceId", "log_analytics"),
        ("storageAccountId", "storage"),
        ("eventHubAuthorizationRuleId", "event_hub"),
        ("marketplacePartnerId", "marketplace"),
    ):
        value = properties.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or not value.strip():
            raise TypeError("Diagnostic Settings destination reference is malformed")
        destination = value.strip()
        if key == "eventHubAuthorizationRuleId":
            event_hub_name = properties.get("eventHubName")
            if event_hub_name not in (None, ""):
                if (
                    not isinstance(event_hub_name, str)
                    or not event_hub_name.strip()
                ):
                    raise TypeError("Diagnostic Settings Event Hub name is malformed")
                destination += "/" + event_hub_name.strip()
        destinations.append(f"{prefix}:{destination}")
    return DiagnosticSetting(
        resource_id=resource_id,
        categories=tuple(sorted(set(categories))),
        destinations=tuple(sorted(set(destinations))),
    )
