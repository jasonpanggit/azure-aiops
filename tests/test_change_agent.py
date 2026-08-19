import json

import pytest
from change_scenario import change_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine


def test_change_commands_are_bounded_read_only_and_advisory():
    agent = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()),
        change_intelligence=change_engine(),
    )
    commands = (
        "Analyze Change Risk", "Show Recent Changes", "Show Configuration Drift",
        "Show Policy Deviations", "Show Incident Contributing Changes",
        "Generate Change Intelligence Report", "Generate Executive Change Brief"
    )
    for command in commands:
        result = agent.analyze(command, "Enterprise", subject_type="ChangePortfolio")
        assert result["read_only"] is True
        assert all(item["advisory_only"] for item in result["recommendations"])
        assert "/subscriptions/" not in json.dumps(result).casefold()

    with pytest.raises(ValueError, match="pre-authorized enterprise change portfolio"):
        agent.analyze("Analyze Change Risk", "CHG-100", subject_type="Change")
