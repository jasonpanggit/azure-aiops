"""Tests for the declarative custom rule engine.

The engine's whole purpose is to let a customer express intent we did not
anticipate. That makes two properties more important than feature coverage:

* a rule must never be able to execute code or crash analysis, and
* a rule that cannot be evaluated must be *reported*, never silently treated
  as passing.

Both are pinned here alongside the operator behaviour.
"""

from __future__ import annotations

import pytest

from network import (
    NetworkDesignPolicy,
    NetworkIntelligenceService,
    NetworkSecurityGroup,
    NetworkSecurityRule,
    NetworkSnapshot,
)
from network.gaps import NetworkGapAnalyzer
from network.models import Subnet, VNet
from network.rule_engine import (
    CustomRuleEvaluator,
    RuleValidationError,
    validate_rule_parameters,
)
from network.topology import build_topology


def _snapshot() -> NetworkSnapshot:
    return NetworkSnapshot(
        vnets=(
            VNet(
                resource_id="/vnet/prod",
                name="vnet-prod",
                location="australiaeast",
                environment="prod",
                subscription_id="sub-1",
                address_spaces=("10.0.0.0/16",),
                tags={"owner": "platform@example.com"},
            ),
            VNet(
                resource_id="/vnet/dev",
                name="vnet-dev",
                location="westus",
                environment="dev",
                subscription_id="sub-1",
                address_spaces=("10.1.0.0/16",),
                tags={},
            ),
        ),
        subnets=(
            Subnet(
                resource_id="/vnet/prod/subnets/app",
                name="snet-app",
                vnet_id="/vnet/prod",
                environment="prod",
                address_prefixes=("10.0.1.0/24",),
                nsg_id="/nsg/a",
                tags={"owner": "app@example.com"},
            ),
            Subnet(
                resource_id="/vnet/prod/subnets/data",
                name="snet-data",
                vnet_id="/vnet/prod",
                environment="prod",
                address_prefixes=("10.0.2.0/24",),
                nsg_id="",
                tags={},
            ),
        ),
        nsgs=(
            NetworkSecurityGroup(
                resource_id="/nsg/a",
                name="nsg-a",
                subnet_ids=("/vnet/prod/subnets/app",),
                rules=(
                    NetworkSecurityRule(
                        resource_id="/nsg/a/rules/wide",
                        name="allow-wide",
                        nsg_id="/nsg/a",
                        priority=100,
                        direction="Inbound",
                        access="Allow",
                        protocol="Tcp",
                        source_address="0.0.0.0/0",
                        destination_address="10.0.1.0/24",
                        destination_port="443",
                    ),
                ),
            ),
        ),
    )


def _rule(**parameters):
    return {
        "rule_id": "custom-under-test",
        "name": "Custom rule under test",
        "severity": "medium",
        "parameters": parameters,
    }


def _gaps_for(**parameters):
    policy = NetworkDesignPolicy.from_mapping({"rules": [_rule(**parameters)]})
    return CustomRuleEvaluator(_snapshot(), policy).evaluate()


class TestSelectionAndAssertion:
    def test_assertion_failure_produces_one_gap_per_resource(self) -> None:
        gaps = _gaps_for(
            target="subnets",
            **{"assert": [{"field": "nsg_id", "exists": True}]},
        )
        assert [gap.resource_name for gap in gaps] == ["snet-data"]

    def test_where_narrows_the_selected_set(self) -> None:
        """A subnet outside the `where` scope must not be judged."""
        gaps = _gaps_for(
            target="subnets",
            where=[{"field": "name", "equals": "snet-app"}],
            **{"assert": [{"field": "nsg_id", "exists": False}]},
        )
        assert [gap.resource_name for gap in gaps] == ["snet-app"]

    def test_a_compliant_estate_produces_no_gaps(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "address_spaces", "exists": True}]},
        )
        assert gaps == ()

    def test_match_any_passes_when_one_assertion_holds(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            match="any",
            **{
                "assert": [
                    {"field": "tags.owner", "exists": True},
                    {"field": "address_spaces", "exists": True},
                ]
            },
        )
        assert gaps == ()

    def test_match_all_fails_when_one_assertion_fails(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            match="all",
            **{
                "assert": [
                    {"field": "tags.owner", "exists": True},
                    {"field": "address_spaces", "exists": True},
                ]
            },
        )
        assert [gap.resource_name for gap in gaps] == ["vnet-dev"]

    def test_nested_targets_are_addressable(self) -> None:
        """NSG rules live inside their NSG, not on the snapshot."""
        gaps = _gaps_for(
            target="nsg_rules",
            **{"assert": [{"field": "source_address", "not_equals": "0.0.0.0/0"}]},
        )
        assert [gap.resource_name for gap in gaps] == ["allow-wide"]


class TestOperators:
    def test_in_matches_an_allowlist(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "location", "in": ["australiaeast", "australiasoutheast"]}]},
        )
        assert [gap.resource_name for gap in gaps] == ["vnet-dev"]

    def test_matches_supports_glob_patterns(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "name", "matches": "vnet-*"}]},
        )
        assert gaps == ()

    def test_in_cidr_compares_networks_not_strings(self) -> None:
        """10.0.0.0/16 is inside 10.0.0.0/8 despite sharing no string prefix rule."""
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "address_spaces", "in_cidr": "10.0.0.0/8"}]},
        )
        assert gaps == ()

    def test_in_cidr_flags_an_out_of_range_space(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "address_spaces", "in_cidr": "10.0.0.0/16"}]},
        )
        assert [gap.resource_name for gap in gaps] == ["vnet-dev"]

    def test_numeric_comparison_on_priority(self) -> None:
        gaps = _gaps_for(
            target="nsg_rules",
            **{"assert": [{"field": "priority", "gte": 200}]},
        )
        assert [gap.resource_name for gap in gaps] == ["allow-wide"]

    def test_dotted_paths_reach_into_tag_dictionaries(self) -> None:
        gaps = _gaps_for(
            target="subnets",
            **{"assert": [{"field": "tags.owner", "exists": True}]},
        )
        assert [gap.resource_name for gap in gaps] == ["snet-data"]


class TestSafety:
    """A policy document is untrusted input. It must not be able to hurt us."""

    def test_a_malformed_cidr_parameter_does_not_raise(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "address_spaces", "in_cidr": "not-a-network"}]},
        )
        assert len(gaps) == 2  # no match, but no crash

    def test_a_comparison_against_a_non_numeric_field_does_not_raise(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "name", "gt": 5}]},
        )
        assert len(gaps) == 2

    def test_an_unknown_field_is_absent_not_an_error(self) -> None:
        gaps = _gaps_for(
            target="vnets",
            **{"assert": [{"field": "no.such.field", "exists": False}]},
        )
        assert gaps == ()

    @pytest.mark.parametrize(
        "parameters,expected",
        [
            ({"assert": [{"field": "name", "equals": "x"}]}, "missing 'target'"),
            ({"target": "aliens", "assert": []}, "unknown target"),
            ({"target": "vnets"}, "missing 'assert'"),
            ({"target": "vnets", "assert": []}, "at least one condition"),
            (
                {"target": "vnets", "assert": [{"field": "name"}]},
                "no supported operator",
            ),
            (
                {"target": "vnets", "assert": [{"equals": "x"}]},
                "missing 'field'",
            ),
            (
                {"target": "vnets", "assert": [{"field": "n", "equals": "x"}], "match": "some"},
                "'match' must be",
            ),
        ],
    )
    def test_invalid_bodies_are_rejected_with_a_reason(self, parameters, expected) -> None:
        with pytest.raises(RuleValidationError, match=expected):
            validate_rule_parameters(parameters)

    def test_an_invalid_rule_is_reported_not_silently_passed(self) -> None:
        """The core safety property: a broken rule must never look compliant."""
        policy = NetworkDesignPolicy.from_mapping(
            {"rules": [_rule(target="aliens", **{"assert": [{"field": "n", "equals": "x"}]})]}
        )
        evaluator = CustomRuleEvaluator(_snapshot(), policy)
        assert evaluator.evaluate() == ()
        invalid = evaluator.invalid_rules()
        assert len(invalid) == 1
        assert invalid[0].rule_id == "custom-under-test"
        assert "unknown target" in invalid[0].reason

    def test_a_disabled_rule_is_not_evaluated(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    {
                        **_rule(
                            target="subnets",
                            **{"assert": [{"field": "nsg_id", "exists": True}]},
                        ),
                        "enabled": False,
                    }
                ]
            }
        )
        assert CustomRuleEvaluator(_snapshot(), policy).evaluate() == ()


class TestGapShape:
    def test_a_gap_carries_auditable_evidence(self) -> None:
        gaps = _gaps_for(
            target="subnets",
            **{"assert": [{"field": "nsg_id", "exists": True}]},
        )
        evidence = gaps[0].evidence
        assert evidence["rule_id"] == "custom-under-test"
        assert evidence["target"] == "subnets"
        failure = evidence["failed_assertions"][0]
        assert failure["field"] == "nsg_id"
        assert failure["operator"] == "exists"

    def test_gap_inherits_rule_severity_and_resource_context(self) -> None:
        gaps = _gaps_for(
            target="subnets",
            **{"assert": [{"field": "nsg_id", "exists": True}]},
        )
        assert gaps[0].severity == "medium"
        assert gaps[0].vnet_id == "/vnet/prod"
        assert gaps[0].environment == "prod"

    def test_two_rules_failing_on_one_resource_stay_distinct(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    {
                        "rule_id": "rule-one",
                        "name": "One",
                        "parameters": {
                            "target": "subnets",
                            "assert": [{"field": "nsg_id", "exists": True}],
                        },
                    },
                    {
                        "rule_id": "rule-two",
                        "name": "Two",
                        "parameters": {
                            "target": "subnets",
                            "assert": [{"field": "tags.owner", "exists": True}],
                        },
                    },
                ]
            }
        )
        gaps = CustomRuleEvaluator(_snapshot(), policy).evaluate()
        for_data = [gap for gap in gaps if gap.resource_name == "snet-data"]
        assert len({gap.gap_id for gap in for_data}) == 2


class TestGapAnalyzerIntegration:
    """The engine is only useful if gap analysis actually runs it."""

    @staticmethod
    def _analyzer(policy: NetworkDesignPolicy) -> NetworkGapAnalyzer:
        snapshot = _snapshot()
        return NetworkGapAnalyzer(snapshot, build_topology(snapshot), policy)

    def test_declarative_rules_appear_in_analyze_output(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    _rule(
                        target="subnets",
                        **{"assert": [{"field": "nsg_id", "exists": True}]},
                    )
                ]
            }
        )
        gaps = self._analyzer(policy).analyze()
        assert any(gap.evidence.get("rule_id") == "custom-under-test" for gap in gaps)

    def test_a_declarative_rule_is_not_reported_as_unevaluated(self) -> None:
        """This is the bug the engine exists to fix.

        Before the engine, any rule outside the built-in check table was
        reported as unevaluated -- which is what made a user-authored rule
        look inert.
        """
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    _rule(
                        target="subnets",
                        **{"assert": [{"field": "nsg_id", "exists": True}]},
                    )
                ]
            }
        )
        analyzer = self._analyzer(policy)
        assert [rule.rule_id for rule in analyzer.unevaluated_rules()] == []

    def test_a_rule_with_no_body_is_still_reported_as_unevaluated(self) -> None:
        """The old honesty guarantee must survive: no body, no evaluation."""
        policy = NetworkDesignPolicy.from_mapping(
            {"rules": [{"rule_id": "prose-only", "name": "Written as a sentence"}]}
        )
        analyzer = self._analyzer(policy)
        assert [rule.rule_id for rule in analyzer.unevaluated_rules()] == ["prose-only"]

    def test_a_malformed_rule_is_invalid_rather_than_unevaluated(self) -> None:
        """'You wrote it wrong' and 'we have no check' are different problems."""
        policy = NetworkDesignPolicy.from_mapping(
            {"rules": [_rule(target="aliens", **{"assert": [{"field": "n", "equals": 1}]})]}
        )
        analyzer = self._analyzer(policy)
        analyzer.analyze()
        assert [rule.rule_id for rule in analyzer.unevaluated_rules()] == []
        assert [rule.rule_id for rule in analyzer.invalid_rules()] == ["custom-under-test"]

    def test_builtin_rules_still_run_alongside_custom_ones(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    _rule(
                        target="subnets",
                        **{"assert": [{"field": "nsg_id", "exists": True}]},
                    )
                ]
            }
        )
        gaps = self._analyzer(policy).analyze()
        custom = {gap.evidence.get("rule_id") for gap in gaps}
        assert "custom-under-test" in custom
        # nsg-on-every-subnet is a built-in and should also fire on snet-data
        assert any(gap.category == "missing_nsg" for gap in gaps)


class TestPrivateEndpointRuleExample:
    """The rule the user originally tried to write, now expressible.

    'Private endpoints should be used when possible' failed before because
    a prose rule had no backing check. Written declaratively it evaluates.
    """

    def test_service_endpoint_subnets_can_be_flagged(self) -> None:
        snapshot = NetworkSnapshot(
            subnets=(
                Subnet(
                    resource_id="/vnet/a/subnets/legacy",
                    name="snet-legacy",
                    vnet_id="/vnet/a",
                    service_endpoints=("Microsoft.Storage",),
                    private_endpoint_ids=(),
                ),
                Subnet(
                    resource_id="/vnet/a/subnets/modern",
                    name="snet-modern",
                    vnet_id="/vnet/a",
                    service_endpoints=(),
                    private_endpoint_ids=("/pe/storage",),
                ),
            )
        )
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    {
                        "rule_id": "prefer-private-endpoints",
                        "name": "Private endpoints should be used when possible",
                        "severity": "medium",
                        "parameters": {
                            "target": "subnets",
                            "where": [{"field": "service_endpoints", "exists": True}],
                            "assert": [{"field": "private_endpoint_ids", "exists": True}],
                        },
                    }
                ]
            }
        )
        gaps = CustomRuleEvaluator(snapshot, policy).evaluate()
        assert [gap.resource_name for gap in gaps] == ["snet-legacy"]


def test_service_surfaces_custom_gaps_end_to_end() -> None:
    """Through the public service entry point, as the API uses it."""
    from network_scenario import network_rows

    policy = NetworkDesignPolicy.from_mapping(
        {
            "rules": [
                {
                    "rule_id": "vnets-must-declare-owner",
                    "name": "Every VNet must declare an owner tag",
                    "severity": "low",
                    "parameters": {
                        "target": "vnets",
                        "assert": [{"field": "tags.owner", "exists": True}],
                    },
                }
            ]
        }
    )
    service = NetworkIntelligenceService.from_rows(network_rows(), policy=policy)
    assert any(
        gap.evidence.get("rule_id") == "vnets-must-declare-owner" for gap in service.gaps
    )


def test_documented_targets_and_operators_match_the_engine():
    """The DSL is useless if the documentation drifts from what it accepts.

    A rule author works from the docs, not the source. An operator that is
    documented but unimplemented produces a rule that silently never matches;
    one that is implemented but undocumented is unreachable in practice. Both
    failure modes are invisible without this check.
    """
    from pathlib import Path

    from network.rule_engine import (
        _DERIVED_TARGETS,
        SUPPORTED_OPERATORS,
        SUPPORTED_TARGETS,
    )

    doc = (Path(__file__).resolve().parents[1] / "docs" / "NETWORK_INTELLIGENCE.md").read_text()

    undocumented_targets = sorted(
        name for name in set(SUPPORTED_TARGETS) | _DERIVED_TARGETS if f"`{name}`" not in doc
    )
    undocumented_operators = sorted(
        name for name in SUPPORTED_OPERATORS if f"`{name}`" not in doc
    )

    assert undocumented_targets == []
    assert undocumented_operators == []
