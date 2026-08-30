from pathlib import Path


SCRIPT = Path("scripts/phase9-operations-smoke.sh").read_text()


def test_operations_smoke_is_secret_free_and_exercises_governed_contract():
    assert "AIOPS_MCP_BEARER_TOKEN" in SCRIPT
    assert "Authorization: ******" in SCRIPT
    assert "tools/list" in SCRIPT
    assert "tools/call" in SCRIPT
    assert "snapshots" in SCRIPT and "replay" in SCRIPT
    assert "snapshot_hash" in SCRIPT
    assert "network_topology" in SCRIPT
    assert "fabric_iq_relationships" in SCRIPT
    assert "delete" not in SCRIPT.casefold()
