import json

from remediation_scenario import remediation_planner
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine

COMMANDS = (
    "Generate Remediation Plan",
    "Show High Priority Plans",
    "Simulate Remediation",
    "Show Risk Reduction",
    "Show Required Approvals",
    "Show Rollback Plan",
    "Generate Modernization Roadmap",
    "Generate Operational Debt Reduction Plan",
    "Generate Executive Remediation Report",
    "Should This Plan Be Recommended?",
)


def test_operations_agent_exposes_ten_approval_only_remediation_commands():
    semantic = SemanticEngine.from_rows(**semantic_scenario())
    agent = OperationsAgent(semantic, remediation_planner=remediation_planner())

    for command in COMMANDS:
        result = agent.analyze(
            command,
            "Enterprise",
            subject_type="RemediationPortfolio",
        )
        serialized = json.dumps(result).casefold()
        assert result["read_only"] is True
        assert result["subject"]["entity_type"] == "RemediationPortfolio"
        assert result["remediation_planning"]["execution_performed"] is False
        assert "action_result" not in serialized
        assert "remediation_result" not in serialized
        assert "/subscriptions/" not in serialized
