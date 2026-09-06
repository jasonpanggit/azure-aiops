"""Declarative evaluation of user-authored design policy rules.

The built-in checks in :mod:`network.gaps` are hand-written Python: precise,
but each new rule needs a code change and a deployment. That is the right
trade for the ten shipped rules, and the wrong one for the long tail of
site-specific intent ("prod subnets must carry an owner tag", "no VNet
outside these regions"). Those rules are knowable only to the customer, and
there will always be more of them than we can anticipate.

This module closes that gap with a small declarative language, evaluated at
runtime, that a rule author expresses entirely in the policy document:

    {
      "rule_id": "prod-subnets-need-owner",
      "name": "Production subnets must declare an owner",
      "severity": "medium",
      "parameters": {
        "target": "subnets",
        "where": [{"field": "environment", "equals": "prod"}],
        "assert": [{"field": "tags.owner", "exists": true}]
      }
    }

``where`` selects the resources in scope; ``assert`` states what must hold
for each of them. A selected resource failing any assertion yields one gap.

Design constraints, in order of priority:

1. **No code execution.** The language has no expression evaluator, no
   ``eval``, and no callable injection. A policy document is untrusted input
   -- it arrives over the API from whoever can edit policy -- so the worst a
   malformed rule can do is fail to match.

2. **Silence is never a pass.** A rule that references an unknown target or
   an unsupported operator does not quietly evaluate to "compliant". It is
   reported as *invalid* through :meth:`CustomRuleEvaluator.invalid_rules`,
   so the UI can distinguish "checked and clean" from "never ran" (D-05).
   This mirrors how ``gaps.py`` already surfaces ``unevaluated_rules``.

3. **Evidence over verdicts.** Every emitted gap records the assertion that
   failed and the value actually observed, so a reviewer can audit the
   finding without re-running the engine.

The language is deliberately not Turing-complete. It expresses "which
resources" and "what must be true of them", which covers conformance
checking; anything requiring traversal or correlation belongs in a
hand-written check where it can be reasoned about and tested directly.
"""

from __future__ import annotations

import fnmatch
import ipaddress
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .design import NetworkDesignPolicy, PolicyRule
from .models import NetworkSnapshot

__all__ = [
    "SUPPORTED_OPERATORS",
    "SUPPORTED_TARGETS",
    "SUPPORTED_TARGET_NAMES",
    "CustomRuleEvaluator",
    "InvalidRule",
    "RuleValidationError",
    "validate_rule_parameters",
]


#: Snapshot collections a rule may target, keyed by the name used in a policy
#: document. Restricting to an explicit map (rather than ``getattr``) keeps a
#: rule from reaching into arbitrary snapshot internals.
SUPPORTED_TARGETS: dict[str, str] = {
    "vnets": "vnets",
    "subnets": "subnets",
    "nsgs": "nsgs",
    "nics": "nics",
    "route_tables": "route_tables",
    "peerings": "peerings",
    "firewalls": "firewalls",
    "private_endpoints": "private_endpoints",
    "private_dns_zones": "private_dns_zones",
    "gateways": "gateways",
    "load_balancers": "load_balancers",
    "private_link_resources": "private_link_resources",
}

#: ``nsg_rules`` is derived rather than a snapshot attribute -- rules live
#: inside their NSG. Handled separately in :meth:`_resources_for`.
_DERIVED_TARGETS = {"nsg_rules", "routes"}

#: Complete public target vocabulary accepted by ``validate_rule_parameters``.
#: Keep the snapshot mapping above separate because derived targets are
#: expanded by :meth:`CustomRuleEvaluator._resources_for`.
SUPPORTED_TARGET_NAMES: tuple[str, ...] = tuple(
    sorted(set(SUPPORTED_TARGETS) | _DERIVED_TARGETS)
)

SUPPORTED_OPERATORS: tuple[str, ...] = (
    "equals",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "matches",
    "not_matches",
    "exists",
    "gt",
    "gte",
    "lt",
    "lte",
    "in_cidr",
    "not_in_cidr",
)


class RuleValidationError(ValueError):
    """A policy rule is not expressible in this language."""


@dataclass(frozen=True)
class InvalidRule:
    """A custom rule that could not be evaluated, and why.

    Carried separately from gaps so a broken rule reads as a *policy
    authoring problem*, not as estate compliance.
    """

    rule_id: str
    name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "name": self.name, "reason": self.reason}


_MISSING = object()


def _resolve_field(resource: Any, path: str) -> Any:
    """Reads a dotted field path off a model instance.

    Supports attributes and mapping keys so ``tags.owner`` and
    ``properties.foo.bar`` work without the rule author needing to know
    which parts of the model are dataclass fields and which are dicts.
    Returns ``_MISSING`` (not ``None``) when absent, because a field
    explicitly set to ``None`` is different from one that does not exist.
    """
    current: Any = resource
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
            current = current[part]
            continue
        if not hasattr(current, part):
            return _MISSING
        current = getattr(current, part)
    return current


def _as_text(value: Any) -> str:
    if value is None or value is _MISSING:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _iter_values(value: Any) -> list[Any]:
    """Normalizes a field to a list so one operator handles scalars and
    collections alike (``contains`` over a string vs over a tuple)."""
    if value is _MISSING or value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _to_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _in_cidr(value: Any, cidrs: Any) -> bool:
    """True when ``value`` (an IP or a prefix) falls inside any of ``cidrs``.

    Invalid addresses return False rather than raising: a rule must not be
    able to crash analysis with a malformed parameter.
    """
    candidates = cidrs if isinstance(cidrs, (list, tuple, set)) else [cidrs]
    networks = []
    for item in candidates:
        try:
            networks.append(ipaddress.ip_network(str(item), strict=False))
        except ValueError:
            continue
    if not networks:
        return False
    for raw in _iter_values(value):
        try:
            subject = ipaddress.ip_network(str(raw), strict=False)
        except ValueError:
            continue
        if any(subject.subnet_of(net) for net in networks if net.version == subject.version):
            return True
    return False


def _evaluate_condition(resource: Any, condition: Mapping[str, Any]) -> tuple[bool, Any]:
    """Applies one condition, returning (passed, observed_value)."""
    field = str(condition.get("field") or "").strip()
    actual = _resolve_field(resource, field) if field else _MISSING

    if "exists" in condition:
        wants = bool(condition["exists"])
        present = actual is not _MISSING and actual not in (None, "", (), [], {})
        return (present == wants), actual

    if "equals" in condition:
        return _as_text(actual).casefold() == _as_text(condition["equals"]).casefold(), actual
    if "not_equals" in condition:
        return _as_text(actual).casefold() != _as_text(condition["not_equals"]).casefold(), actual

    if "in" in condition or "not_in" in condition:
        negated = "not_in" in condition
        allowed = {
            _as_text(item).casefold()
            for item in _iter_values(condition.get("not_in" if negated else "in"))
        }
        hit = _as_text(actual).casefold() in allowed
        return (not hit if negated else hit), actual

    if "contains" in condition or "not_contains" in condition:
        negated = "not_contains" in condition
        needle = _as_text(condition.get("not_contains" if negated else "contains")).casefold()
        hit = any(needle in _as_text(item).casefold() for item in _iter_values(actual))
        return (not hit if negated else hit), actual

    if "matches" in condition or "not_matches" in condition:
        negated = "not_matches" in condition
        pattern = _as_text(condition.get("not_matches" if negated else "matches")).casefold()
        hit = any(fnmatch.fnmatch(_as_text(item).casefold(), pattern) for item in _iter_values(actual))
        return (not hit if negated else hit), actual

    if "in_cidr" in condition or "not_in_cidr" in condition:
        negated = "not_in_cidr" in condition
        hit = _in_cidr(actual, condition.get("not_in_cidr" if negated else "in_cidr"))
        return (not hit if negated else hit), actual

    for operator, compare in (
        ("gt", lambda a, b: a > b),
        ("gte", lambda a, b: a >= b),
        ("lt", lambda a, b: a < b),
        ("lte", lambda a, b: a <= b),
    ):
        if operator in condition:
            left, right = _to_number(actual), _to_number(condition[operator])
            if left is None or right is None:
                return False, actual
            return compare(left, right), actual

    # Unreachable for validated rules; validation rejects unknown operators.
    return False, actual


def _condition_operator(condition: Mapping[str, Any]) -> str | None:
    for operator in SUPPORTED_OPERATORS:
        if operator in condition:
            return operator
    return None


def _validate_conditions(conditions: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(conditions, (list, tuple)):
        raise RuleValidationError(f"'{label}' must be a list of conditions")
    validated: list[Mapping[str, Any]] = []
    for index, condition in enumerate(conditions):
        if not isinstance(condition, Mapping):
            raise RuleValidationError(f"'{label}[{index}]' must be an object")
        if not str(condition.get("field") or "").strip():
            raise RuleValidationError(f"'{label}[{index}]' is missing 'field'")
        if _condition_operator(condition) is None:
            raise RuleValidationError(
                f"'{label}[{index}]' has no supported operator "
                f"(one of: {', '.join(SUPPORTED_OPERATORS)})"
            )
        validated.append(condition)
    return validated


def validate_rule_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Checks a rule body and returns it normalized, or raises.

    Exposed so the policy API can reject a malformed rule at author time --
    telling someone their rule is broken when they save it is far more useful
    than silently not evaluating it later.
    """
    if not isinstance(parameters, Mapping):
        raise RuleValidationError("rule parameters must be an object")

    target = str(parameters.get("target") or "").strip()
    if not target:
        raise RuleValidationError("rule is missing 'target'")
    if target not in SUPPORTED_TARGET_NAMES:
        known = ", ".join(SUPPORTED_TARGET_NAMES)
        raise RuleValidationError(f"unknown target '{target}' (expected one of: {known})")

    assertions = parameters.get("assert")
    if assertions is None:
        raise RuleValidationError("rule is missing 'assert'")
    validated_assert = _validate_conditions(assertions, "assert")
    if not validated_assert:
        raise RuleValidationError("'assert' must contain at least one condition")

    where = parameters.get("where") or []
    validated_where = _validate_conditions(where, "where")

    match_mode = str(parameters.get("match") or "all").strip().casefold()
    if match_mode not in {"all", "any"}:
        raise RuleValidationError("'match' must be 'all' or 'any'")

    return {
        "target": target,
        "where": validated_where,
        "assert": validated_assert,
        "match": match_mode,
    }


def is_declarative_rule(rule: PolicyRule) -> bool:
    """True when a rule carries a declarative body this engine can run."""
    parameters = rule.parameters
    return isinstance(parameters, Mapping) and bool(parameters.get("assert"))


class CustomRuleEvaluator:
    """Evaluates the declarative rules in a policy against a snapshot.

    Constructed with the same inputs as ``NetworkGapAnalyzer`` so it can be
    composed into gap analysis without the analyzer needing to know how the
    language works.
    """

    def __init__(
        self,
        snapshot: NetworkSnapshot,
        policy: NetworkDesignPolicy | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.policy = policy or NetworkDesignPolicy()
        self._invalid: list[InvalidRule] = []

    def evaluable_rules(self) -> list[PolicyRule]:
        """Enabled rules carrying a declarative body, valid or not.

        Includes invalid ones deliberately: the caller needs to know a rule
        *claimed* to be declarative, so it is not double-counted as
        "unevaluated for lack of a check".
        """
        return [
            rule
            for rule in self.policy.rules
            if rule.enabled and is_declarative_rule(rule)
        ]

    def invalid_rules(self) -> tuple[InvalidRule, ...]:
        """Rules that failed validation during the last :meth:`evaluate`."""
        return tuple(self._invalid)

    def evaluate(self) -> tuple[Any, ...]:
        """Runs every declarative rule, returning the gaps they produce.

        Returns ``NetworkGap`` instances, imported lazily to avoid a circular
        import (``gaps`` composes this evaluator).
        """
        from .gaps import NetworkGap, _gap_id

        self._invalid = []
        gaps: list[NetworkGap] = []

        for rule in self.evaluable_rules():
            try:
                body = validate_rule_parameters(rule.parameters)
            except RuleValidationError as error:
                self._invalid.append(
                    InvalidRule(rule_id=rule.rule_id, name=rule.name, reason=str(error))
                )
                continue
            gaps.extend(self._evaluate_rule(rule, body, NetworkGap, _gap_id))

        return tuple(gaps)

    def _evaluate_rule(
        self,
        rule: PolicyRule,
        body: Mapping[str, Any],
        gap_cls: Any,
        gap_id: Any,
    ) -> list[Any]:
        selected = self._select(body["target"], body["where"])
        assertions = body["assert"]
        require_all = body["match"] == "all"

        gaps: list[Any] = []
        for resource in selected:
            results = [
                (condition, *_evaluate_condition(resource, condition))
                for condition in assertions
            ]
            passed = (
                all(item[1] for item in results)
                if require_all
                else any(item[1] for item in results)
            )
            if passed:
                continue
            failures = [item for item in results if not item[1]]
            gaps.append(
                self._build_gap(rule, body, resource, failures, gap_cls, gap_id)
            )
        return gaps

    def _select(
        self, target: str, where: Sequence[Mapping[str, Any]]
    ) -> list[Any]:
        resources = self._resources_for(target)
        if not where:
            return list(resources)
        return [
            resource
            for resource in resources
            if all(_evaluate_condition(resource, condition)[0] for condition in where)
        ]

    def _resources_for(self, target: str) -> list[Any]:
        if target == "nsg_rules":
            return [rule for nsg in self.snapshot.nsgs for rule in nsg.rules]
        if target == "routes":
            return [
                route for table in self.snapshot.route_tables for route in table.routes
            ]
        attribute = SUPPORTED_TARGETS.get(target)
        if attribute is None:
            return []
        return list(getattr(self.snapshot, attribute, ()) or ())

    def _build_gap(
        self,
        rule: PolicyRule,
        body: Mapping[str, Any],
        resource: Any,
        failures: Sequence[tuple[Mapping[str, Any], bool, Any]],
        gap_cls: Any,
        gap_id: Any,
    ) -> Any:
        resource_id = _as_text(_resolve_field(resource, "resource_id"))
        resource_name = _as_text(_resolve_field(resource, "name"))
        detail_parts = []
        evidence_failures = []
        for condition, _passed, observed in failures:
            operator = _condition_operator(condition) or "?"
            expected = condition.get(operator)
            field = condition.get("field")
            detail_parts.append(
                f"{field} {operator} {expected!r} (observed: {_as_text(observed) or 'absent'})"
            )
            evidence_failures.append(
                {
                    "field": field,
                    "operator": operator,
                    "expected": expected,
                    "observed": _as_text(observed),
                }
            )

        return gap_cls(
            # Namespaced by rule so two custom rules failing on the same
            # resource stay distinct findings.
            gap_id=gap_id(f"custom:{rule.rule_id}", resource_id),
            category=rule.category or "custom",
            severity=rule.severity or "medium",
            title=rule.name,
            detail=(
                rule.description.strip()
                or f"{resource_name or resource_id} does not satisfy: "
                + "; ".join(detail_parts)
            ),
            resource_id=resource_id,
            resource_name=resource_name,
            resource_type=_as_text(_resolve_field(resource, "entity_type")) or body["target"],
            evidence={
                "rule_id": rule.rule_id,
                "target": body["target"],
                "match": body["match"],
                "failed_assertions": evidence_failures,
            },
            recommendation=(
                _as_text(rule.parameters.get("recommendation")).strip()
                or f"Update {resource_name or resource_id} so it satisfies "
                + "; ".join(detail_parts)
            ),
            basis=(
                f"Custom design policy rule '{rule.rule_id}', evaluated declaratively "
                f"against {body['target']} in the current snapshot"
            ),
            connection_id=_as_text(_resolve_field(resource, "connection_id")),
            subscription_id=_as_text(_resolve_field(resource, "subscription_id")),
            environment=_as_text(_resolve_field(resource, "environment")),
            vnet_id=_as_text(_resolve_field(resource, "vnet_id")),
        )
