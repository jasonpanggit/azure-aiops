import json

import pytest
from predictive_scenario import predictive_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine


def test_predictive_commands_are_read_only_advisory_and_identifier_safe():
    agent=OperationsAgent(SemanticEngine.from_rows(**semantic_scenario()), predictive_intelligence=predictive_engine())
    commands=("Analyze Predictive Risk", "What Is Likely To Fail Next", "Show Unstable Applications", "Show Services Accumulating Debt", "Forecast Incidents", "Show Workloads Requiring Intervention", "Generate Predictive Operations Report", "Generate Executive Predictive Brief")
    for command in commands:
        result=agent.analyze(command, "Enterprise", subject_type="PredictivePortfolio")
        assert result["read_only"] is True
        assert all(item["advisory_only"] for item in result["recommendations"])
        assert "/subscriptions/" not in json.dumps(result).casefold()
    with pytest.raises(ValueError, match="pre-authorized enterprise predictive portfolio"):
        agent.analyze("Analyze Predictive Risk", "vm-payments", subject_type="Resource")
