#!/usr/bin/env python3
"""Test minimal notebook execution to isolate root cause."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.auth import FabricAuthConfig, build_credential  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric_pipelines.notebook_manager import NotebookManager  # noqa: E402


def test_minimal_notebook(manager: NotebookManager) -> bool:
    """Test with minimal cell: just print statement."""
    print("\n" + "="*60)
    print("TEST: Minimal print statement only")
    print("="*60)

    definition = {
        "parts": [
            {
                "path": "/Notebook/document.ipynb",
                "payload": "eyJjZWxscyI6IFt7ImNlbGxfdHlwZSI6ICJjb2RlIiwgInNvdXJjZSI6IFsicHJpbnQoJ0hlbGxvIGZyb20gTm90ZWJvb2snKSJdfV0sICJtZXRhZGF0YSI6IHt9LCAibmJmb3JtYXQiOiA0LCAibmJmb3JtYXRfbWlub3IiOiAwfQ==",
                "payloadType": "InlineBase64"
            }
        ]
    }

    try:
        print("Creating notebook...")
        result = manager.create("test_minimal_print", definition)
        notebook_id = result["id"]
        print(f"✓ Created: {notebook_id}")

        print("Running notebook...")
        run_result = manager.run_on_demand(notebook_id)
        print(f"✓ Run succeeded: status={run_result['status']}")
        return True

    except Exception as e:
        print(f"✗ Failed: {type(e).__name__}: {e}")
        return False


def test_dataframe_creation(manager: NotebookManager) -> bool:
    """Test with DataFrame creation but no table write."""
    print("\n" + "="*60)
    print("TEST: DataFrame creation (no table write)")
    print("="*60)

    cell_code = """from pyspark.sql.types import StructType, StructField, StringType
schema = StructType([StructField('id', StringType(), True)])
df = spark.createDataFrame([], schema)
print('DataFrame created')
"""

    # Base64 encode the notebook JSON
    import base64
    import json
    notebook_json = {
        "cells": [
            {"cell_type": "code", "source": [cell_code]}
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 0
    }
    payload = base64.b64encode(json.dumps(notebook_json).encode()).decode()

    definition = {
        "parts": [
            {
                "path": "/Notebook/document.ipynb",
                "payload": payload,
                "payloadType": "InlineBase64"
            }
        ]
    }

    try:
        print("Creating notebook...")
        result = manager.create("test_dataframe", definition)
        notebook_id = result["id"]
        print(f"✓ Created: {notebook_id}")

        print("Running notebook...")
        run_result = manager.run_on_demand(notebook_id)
        print(f"✓ Run succeeded: status={run_result['status']}")
        return True

    except Exception as e:
        print(f"✗ Failed: {type(e).__name__}: {e}")
        return False


def test_table_write(manager: NotebookManager, lakehouse_name: str) -> bool:
    """Test with table write operation."""
    print("\n" + "="*60)
    print("TEST: DataFrame creation + table write")
    print("="*60)

    cell_code = f"""from pyspark.sql.types import StructType, StructField, StringType
schema = StructType([StructField('id', StringType(), True)])
df = spark.createDataFrame([], schema)
df.write.format('delta').mode('overwrite').option('mergeSchema', 'true').saveAsTable('test_table')
print('Table written')
"""

    # Base64 encode the notebook JSON
    import base64
    import json
    notebook_json = {
        "cells": [
            {"cell_type": "code", "source": [cell_code]}
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 0
    }
    payload = base64.b64encode(json.dumps(notebook_json).encode()).decode()

    definition = {
        "parts": [
            {
                "path": "/Notebook/document.ipynb",
                "payload": payload,
                "payloadType": "InlineBase64"
            }
        ]
    }

    try:
        print("Creating notebook...")
        result = manager.create("test_table_write", definition)
        notebook_id = result["id"]
        print(f"✓ Created: {notebook_id}")

        print("Running notebook...")
        run_result = manager.run_on_demand(notebook_id)
        print(f"✓ Run succeeded: status={run_result['status']}")
        return True

    except Exception as e:
        print(f"✗ Failed: {type(e).__name__}: {e}")
        return False


def main() -> int:
    config_path = Path("fabric.config.yaml")
    if not config_path.exists():
        print(f"error: {config_path} not found", file=sys.stderr)
        return 1

    raw = yaml.safe_load(config_path.read_text()) or {}
    fabric_cfg = raw.get("fabric") or {}
    workspace_id = str(fabric_cfg.get("workspace_id") or "")
    lakehouse_name = str(fabric_cfg.get("lakehouse_name") or "")

    auth_cfg = FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    credential = build_credential(auth_cfg)
    client = FabricClient(credential)
    manager = NotebookManager(client, workspace_id)

    results = []
    results.append(("Print only", test_minimal_notebook(manager)))
    results.append(("DataFrame creation", test_dataframe_creation(manager)))
    results.append(("Table write", test_table_write(manager, lakehouse_name)))

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {name}")
    print("="*60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
