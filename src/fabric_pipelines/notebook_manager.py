"""Creates and maintains the genuine Fabric-hosted notebook item that runs
this pipeline's topology derivation as real Fabric Spark compute (D-04a
compute-architecture decision: `fabric-hosted-notebook`, not merely an
extension of the Python OneLake-writer pattern).

Uses Fabric's generic Items API (``POST /workspaces/{id}/items``) with a
PySpark notebook definition part, mirroring the wire-format conventions
already established by ``ontology.ontology_manager.OntologyManager`` and
``fabric.lakehouse_manager.LakehouseManager`` (resolve-by-name-or-id,
create-if-missing, base64 InlineBase64 definition parts) rather than
inventing a new Fabric-item client pattern.

The notebook content itself is authored here as a Jupyter-format ``.ipynb``
JSON payload (Fabric's supported notebook definition format) whose cells
import and call this same package's pure Python functions
(``topology_pipeline.derive_edges``, ``flowlog_ingest.join_flow_logs_with_nsg_rules``,
``ontology_binding.TopologyOntologyBinder``) -- the notebook is a genuine
Fabric-hosted Spark execution surface, but it calls the exact same
deterministic derivation logic already proven correct and tested outside
Fabric, rather than re-implementing the predicate vocabulary a second time
inside notebook cells (Don't Hand-Roll: one derivation implementation).
"""

from __future__ import annotations

import base64
import json
from typing import Any

NOTEBOOK_DISPLAY_NAME = "topology_pipeline_notebook"

#: The notebook's own top-level cells: read inventory-shaped rows from the
#: existing lakehouse tables via Spark, call this package's pure functions,
#: then write results back via the same Delta path this repo's
#: DeltaWriter/OneLakeWriter already write through (so the notebook and the
#: local/CI-tested pipeline are provably the same logic, run on two
#: different compute surfaces).
_NOTEBOOK_CELLS: tuple[str, ...] = (
    (
        "# Fabric-hosted Spark notebook: topology derivation (D-04a comparison arm)\n"
        "# Reproduces hermes_arg_connector.normalize's predicate vocabulary against\n"
        "# inventory-owned identity data, plus NSG+flow-log-derived topology (D-11).\n"
        "# This cell installs no new dependencies -- it imports the same pure\n"
        "# functions already unit-tested outside Fabric (fabric_pipelines package).\n"
    ),
    (
        "from fabric_pipelines.topology_pipeline import derive_edges, to_topology_edge_row\n"
        "from fabric_pipelines.flowlog_ingest import (\n"
        "    curated_flow_log_fixture,\n"
        "    join_flow_logs_with_nsg_rules,\n"
        ")\n"
        "from fabric_pipelines.ontology_binding import TopologyOntologyBinder\n"
    ),
    (
        "# Read inventory-owned network rows from the Lakehouse (Spark-native read;\n"
        "# no direct ARG/LAW query -- this is the whole point of the D-04a arm).\n"
        "entity_rows = {\n"
        "    'network_vnets': spark.read.table('inventory_network_vnets').toJSON().map(lambda r: __import__('json').loads(r)).collect(),\n"
        "    'network_security_groups': spark.read.table('inventory_network_security_groups').toJSON().map(lambda r: __import__('json').loads(r)).collect(),\n"
        "}\n"
        "observed = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()\n"
    ),
    (
        "entities, edges = derive_edges(entity_rows, observed=observed)\n"
        "edge_rows = [to_topology_edge_row(edge) for edge in edges]\n"
    ),
    (
        "entities_df = spark.createDataFrame(entities)\n"
        "edges_df = spark.createDataFrame(edge_rows)\n"
        "entities_df.write.format('delta').mode('overwrite').saveAsTable('topology_entities')\n"
        "edges_df.write.format('delta').mode('overwrite').saveAsTable('topology_edges')\n"
    ),
)


def _build_notebook_source(
    *,
    environment_id: str = "",
    workspace_id: str = "",
    lakehouse_id: str = "",
    lakehouse_name: str = "",
) -> str:
    """Renders ``_NOTEBOOK_CELLS`` in Fabric's ``.py`` notebook-source format
    (NOT plain Python, NOT ipynb JSON): a ``# Fabric notebook source``
    prologue, a notebook-level ``# META`` block, then one ``# CELL`` marker
    per cell with its own per-cell ``# META`` trailer. This is the format
    Fabric's item-definition API actually requires for a ``.py`` notebook
    part -- submitting raw ipynb JSON under a ``.py`` path name fails with
    ``PyToIPynbFailure: prologue is invalid``.

    When ``environment_id`` is provided, the notebook-level ``dependencies``
    entry attaches that Environment item as the notebook's default Spark
    environment, so on-demand runs get a session with this repo's own
    packages (``fabric_pipelines``, ``hermes_arg_connector``, ``storage``)
    pre-installed rather than failing with an import error.

    When ``lakehouse_id`` is provided, the notebook-level ``dependencies``
    entry also attaches that Lakehouse item as the notebook's default
    lakehouse, which is what makes unqualified ``spark.read.table(...)`` /
    ``.saveAsTable(...)`` calls in ``_NOTEBOOK_CELLS`` resolve against it --
    without a default lakehouse, Fabric's Spark session has no metastore
    catalog to resolve those table names against."""
    dependency_block_lines: list[str] = []
    if lakehouse_id:
        dependency_block_lines.extend(
            [
                '# META     "lakehouse": {',
                f'# META       "default_lakehouse": "{lakehouse_id}",',
                f'# META       "default_lakehouse_name": "{lakehouse_name}",',
                f'# META       "default_lakehouse_workspace_id": "{workspace_id}"',
                "# META     }" + ("," if environment_id else ""),
            ]
        )
    if environment_id:
        dependency_block_lines.extend(
            [
                '# META     "environment": {',
                f'# META       "environmentId": "{environment_id}",',
                f'# META       "workspaceId": "{workspace_id}"',
                "# META     }",
            ]
        )
    dependencies_lines: list[str]
    if dependency_block_lines:
        dependencies_lines = [
            '# META   "dependencies": {',
            *dependency_block_lines,
            "# META   }",
        ]
    else:
        dependencies_lines = ['# META   "dependencies": {}']
    lines = [
        "# Fabric notebook source",
        "",
        "# METADATA ********************",
        "",
        "# META {",
        '# META   "kernel_info": {',
        '# META     "name": "synapse_pyspark"',
        "# META   },",
        *dependencies_lines,
        "# META }",
        "",
    ]
    for source in _NOTEBOOK_CELLS:
        lines.append("# CELL ********************")
        lines.append("")
        lines.extend(source.splitlines())
        lines.append("")
        lines.append("# METADATA ********************")
        lines.append("")
        lines.append("# META {")
        lines.append('# META   "language": "python",')
        lines.append('# META   "language_group": "synapse_pyspark"')
        lines.append("# META }")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_notebook_definition(
    *,
    environment_id: str = "",
    workspace_id: str = "",
    lakehouse_id: str = "",
    lakehouse_name: str = "",
) -> dict[str, Any]:
    """Returns the Fabric item ``definition`` payload for the notebook.

    When ``environment_id`` is supplied, the notebook source's own
    notebook-level ``# META`` block is given a ``"dependencies": {
    "environment": {...}}`` entry -- this is how Fabric attaches a default
    Spark environment (and therefore this repo's own installed packages) to
    a notebook, distinct from the ``.platform`` part (which only carries
    item-kind/display-name metadata, not environment attachment).

    When ``lakehouse_id`` is supplied, the same ``dependencies`` entry also
    gets a ``"lakehouse": {...}`` block attaching that Lakehouse item as the
    notebook's default lakehouse -- required for the unqualified
    ``spark.read.table(...)``/``.saveAsTable(...)`` calls in
    ``_NOTEBOOK_CELLS`` to resolve against a metastore catalog at all.
    """
    return {
        "parts": [
            _text_part(
                "notebook-content.py",
                _build_notebook_source(
                    environment_id=environment_id,
                    workspace_id=workspace_id,
                    lakehouse_id=lakehouse_id,
                    lakehouse_name=lakehouse_name,
                ),
            ),
            _part(
                ".platform",
                {"metadata": {"type": "Notebook", "displayName": NOTEBOOK_DISPLAY_NAME}},
                payload_type="InlineBase64",
            ),
        ]
    }


class NotebookManager:
    """Thin manager over Fabric's generic Items API, scoped to Notebook
    items -- mirrors ``LakehouseManager``/``OntologyManager``'s
    resolve/create shape rather than introducing a new client pattern."""

    ITEM_TYPE = "Notebook"

    def __init__(self, client: Any, workspace_id: str) -> None:
        self.client = client
        self.workspace_id = workspace_id
        self.base_path = f"/workspaces/{workspace_id}/items"

    def resolve(self, *, item_id: str = "", display_name: str = "") -> dict[str, Any] | None:
        if item_id:
            return self.client.request("GET", f"{self.base_path}/{item_id}")
        matches = [
            item
            for item in self.client.iter_items(self.base_path, params={"type": self.ITEM_TYPE})
            if str(item.get("displayName") or "") == display_name
        ]
        if len(matches) > 1:
            raise ValueError(f"Multiple Fabric notebooks named {display_name!r}; configure item_id")
        return matches[0] if matches else None

    def create(self, display_name: str, definition: dict[str, Any]) -> dict[str, Any]:
        return self.client.request(
            "POST",
            self.base_path,
            json_body={
                "displayName": display_name,
                "description": "Fabric-hosted D-04a topology-pipeline comparison-arm notebook",
                "type": self.ITEM_TYPE,
                "definition": definition,
            },
        )

    def update_definition(self, item_id: str, definition: dict[str, Any]) -> dict[str, Any]:
        return self.client.request(
            "POST",
            f"{self.base_path}/{item_id}/updateDefinition",
            json_body={"definition": definition},
        )

    def run_on_demand(self, item_id: str) -> dict[str, Any]:
        """Triggers a Fabric on-demand job run of the notebook item -- the
        genuine Fabric-hosted Spark execution this compute-architecture
        decision requires, as opposed to a Python client writing Delta files
        from outside Fabric's own compute."""
        return self.client.request(
            "POST",
            f"{self.base_path}/{item_id}/jobs/instances",
            params={"jobType": "RunNotebook"},
        )


def ensure_notebook(
    manager: NotebookManager,
    *,
    display_name: str = NOTEBOOK_DISPLAY_NAME,
    item_id: str = "",
    environment_id: str = "",
    lakehouse_id: str = "",
    lakehouse_name: str = "",
) -> dict[str, Any]:
    """Idempotent create-or-update of the topology-pipeline notebook item."""
    definition = build_notebook_definition(
        environment_id=environment_id,
        workspace_id=manager.workspace_id if (environment_id or lakehouse_id) else "",
        lakehouse_id=lakehouse_id,
        lakehouse_name=lakehouse_name,
    )
    item = manager.resolve(item_id=item_id, display_name=display_name)
    if item is None:
        created = manager.create(display_name, definition)
        return {**created, "action": "created"}
    manager.update_definition(str(item["id"]), definition)
    return {**item, "action": "updated"}


def _part(path: str, payload: dict[str, Any], *, payload_type: str) -> dict[str, str]:
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return {"path": path, "payload": encoded, "payloadType": payload_type}


def _text_part(path: str, text: str) -> dict[str, str]:
    """Like ``_part`` but for a raw-text definition part (the notebook's
    ``.py`` source), which must NOT be JSON-encoded first."""
    encoded = base64.b64encode(text.encode()).decode()
    return {"path": path, "payload": encoded, "payloadType": "InlineBase64"}


__all__ = [
    "NOTEBOOK_DISPLAY_NAME",
    "NotebookManager",
    "build_notebook_definition",
    "ensure_notebook",
]
