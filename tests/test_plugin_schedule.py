from __future__ import annotations

import json
import os
import subprocess
import sys

from hermes_arg_connector import plugin as hermes_plugin
from hermes_arg_connector.schedule import build_hermes_cron_command


class FakeContext:
    def __init__(self) -> None:
        self.cli = []
        self.tools = []

    def register_cli_command(self, **kwargs):
        self.cli.append(kwargs)

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


def test_plugin_registers_cli_and_read_only_operations_agent_tool() -> None:
    ctx = FakeContext()
    hermes_plugin.register(ctx)

    assert ctx.cli[0]["name"] == "azure-graph"
    assert ctx.tools[0]["name"] == "operations_analysis"
    assert ctx.tools[0]["toolset"] == "azure_operational_context"
    assert set(ctx.tools[0]["schema"]["parameters"]["properties"]) == {
        "command",
        "subject",
        "subject_type",
    }
    assert not {
        "azure_context_query",
        "ontology_context_query",
        "semantic_knowledge_query",
        "fabric_inventory_command",
    } & {
        tool["name"] for tool in ctx.tools
    }
    assert [tool["name"] for tool in ctx.tools] == ["operations_analysis"]


def test_plugin_module_imports_without_pyarrow_or_yaml() -> None:
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'pyarrow' or fullname.startswith('pyarrow.') or fullname == 'yaml':
            raise ModuleNotFoundError(fullname)
        return None
sys.meta_path.insert(0, Block())
import hermes_arg_connector.plugin
print('ok')
"""
    env = {**os.environ, "PYTHONPATH": "src"}
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=False)
    assert completed.returncode == 0, completed.stderr


def test_root_plugin_entrypoint_imports_operations_schema() -> None:
    import hermes_plugin

    assert hermes_plugin.TOOL_SCHEMA["name"] == "operations_analysis"


def test_operations_tool_errors_do_not_echo_supplied_subject(monkeypatch) -> None:
    class FailingAgent:
        def analyze(self, *_args, **_kwargs):
            raise LookupError("No semantic entity matches '/subscriptions/SECRET'")

    class Runtime:
        def operations_agent(self):
            return FailingAgent()

    monkeypatch.setattr(hermes_plugin, "_get_semantic_runtime", lambda: Runtime())

    result = json.loads(
        hermes_plugin._handle_operations(
            {
                "command": "Analyze VM",
                "subject": "/subscriptions/SECRET",
            }
        )
    )

    assert result == {"error": "Operational subject was not found"}
    assert "SECRET" not in str(result)


def test_schedule_command_reuses_hermes_cron() -> None:
    command = build_hermes_cron_command(
        schedule="every 30m",
        script_name="azure-resource-graph-sync.py",
        workdir="/workspace/hog",
    )
    assert command[:3] == ["hermes", "cron", "create"]
    assert "--no-agent" in command
    assert "--script" in command
    assert "--workdir" in command
