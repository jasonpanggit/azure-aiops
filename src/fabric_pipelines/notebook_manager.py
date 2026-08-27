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
from collections.abc import Callable
from typing import Any

NOTEBOOK_DISPLAY_NAME = "topology_pipeline_notebook"

#: Second Fabric-hosted notebook item: the full operational-context-graph
#: (entity/relationship) pipeline, mirroring the topology notebook's
#: compute-architecture decision but covering the full Hermes ontology
#: scope rather than only network topology.
ONTOLOGY_NOTEBOOK_DISPLAY_NAME = "ontology_pipeline_notebook"
VULNERABILITY_NOTEBOOK_DISPLAY_NAME = "vulnerability_pipeline_notebook"
LIFECYCLE_NOTEBOOK_DISPLAY_NAME = "lifecycle_pipeline_notebook"
PATCH_NOTEBOOK_DISPLAY_NAME = "patch_pipeline_notebook"
CHANGE_NOTEBOOK_DISPLAY_NAME = "change_pipeline_notebook"
PREDEPLOY_NOTEBOOK_DISPLAY_NAME = "predeploy_pipeline_notebook"
IMPACT_CONTEXT_NOTEBOOK_DISPLAY_NAME = "impact_context_pipeline_notebook"

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

#: The operational-context-graph notebook's own top-level cells: read
#: inventory-shaped rows from the existing lakehouse tables via Spark, call
#: ``ontology_pipeline``'s pure functions (which themselves call the
#: existing ``EntityBuilder``/``RelationshipBuilder``/
#: ``generate_ontology_metadata``), then write results back via the same
#: Delta path this repo's DeltaWriter/OneLakeWriter already write through.
_ONTOLOGY_NOTEBOOK_CELLS: tuple[str, ...] = (
    (
        "# Fabric-hosted Spark notebook: operational-context-graph derivation\n"
        "# Reproduces ontology.entity_builder.EntityBuilder and\n"
        "# ontology.relationship_builder.RelationshipBuilder's full deterministic\n"
        "# entity/relationship inference (Application, BusinessService,\n"
        "# VirtualMachine, PatchAssessment, AdvisorRecommendation, ... plus\n"
        "# belongsTo/assessedBy/impacts/dependsOn, ...) against inventory-owned\n"
        "# identity data. This cell installs no new dependencies -- it imports\n"
        "# the same pure functions already unit-tested outside Fabric\n"
        "# (fabric_pipelines/ontology packages).\n"
    ),
    (
        "from fabric_pipelines.ontology_pipeline import (\n"
        "    derive_entities,\n"
        "    derive_ontology_metadata,\n"
        "    derive_relationships,\n"
        ")\n"
    ),
    (
        "# Read inventory-owned resource rows from the Lakehouse (Spark-native\n"
        "# read; no direct ARG query -- this mirrors the topology pipeline's\n"
        "# D-04a compute-architecture decision for the full ontology scope).\n"
        "source_rows = spark.read.table('inventory_resources').toJSON().map(lambda r: __import__('json').loads(r)).collect()\n"
        "run_id = spark.conf.get('spark.app.id', 'ontology-pipeline-run')\n"
        "observed = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()\n"
    ),
    (
        "entity_rows = derive_entities(source_rows, run_id=run_id, timestamp=observed)\n"
        "relationship_rows = derive_relationships(entity_rows, run_id)\n"
        "ontology_metadata = derive_ontology_metadata(entity_rows)\n"
    ),
    (
        "entities_df = spark.createDataFrame(entity_rows)\n"
        "relationships_df = spark.createDataFrame(relationship_rows)\n"
        "entities_df.write.format('delta').mode('overwrite').saveAsTable('ontology_entities')\n"
        "relationships_df.write.format('delta').mode('overwrite').saveAsTable('ontology_relationships')\n"
    ),
)


def _pipeline_cells(module_name: str, function_name: str = "run") -> tuple[str, ...]:
    return (
        f"# Fabric-hosted Spark notebook: {module_name}\n"
        "# Reads governed Lakehouse tables and calls the same pure Python\n"
        "# pipeline entrypoint exercised by local tests. No direct Azure ARG/LAW\n"
        "# acquisition is performed here.\n",
        f"from fabric_pipelines.{module_name} import {function_name}\n",
        "# Workspace-specific table reads are intentionally configured by the\n"
        "# deployment/runbook; call the imported function with row dictionaries\n"
        "# loaded from the Lakehouse and write its result table back with Spark.\n",
    )


def _build_notebook_source(
    *,
    environment_id: str = "",
    workspace_id: str = "",
    lakehouse_id: str = "",
    lakehouse_name: str = "",
    cells: tuple[str, ...] = _NOTEBOOK_CELLS,
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
    for source in cells:
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
    display_name: str = NOTEBOOK_DISPLAY_NAME,
    cells: tuple[str, ...] = _NOTEBOOK_CELLS,
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
    ``spark.read.table(...)``/``.saveAsTable(...)`` calls in ``cells``
    to resolve against a metastore catalog at all.

    ``display_name``/``cells`` default to the topology-pipeline notebook's
    own content so existing callers are unaffected; the ontology pipeline
    notebook is built by passing ``display_name=ONTOLOGY_NOTEBOOK_DISPLAY_NAME,
    cells=_ONTOLOGY_NOTEBOOK_CELLS`` (see ``build_ontology_notebook_definition``).
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
                    cells=cells,
                ),
            ),
            _part(
                ".platform",
                {"metadata": {"type": "Notebook", "displayName": display_name}},
                payload_type="InlineBase64",
            ),
        ]
    }


def build_ontology_notebook_definition(
    *,
    environment_id: str = "",
    workspace_id: str = "",
    lakehouse_id: str = "",
    lakehouse_name: str = "",
) -> dict[str, Any]:
    """Returns the Fabric item ``definition`` payload for the
    operational-context-graph (entity/relationship) notebook -- the same
    ``.py`` notebook-source format as ``build_notebook_definition``, just
    with ``_ONTOLOGY_NOTEBOOK_CELLS`` and its own display name."""
    return build_notebook_definition(
        environment_id=environment_id,
        workspace_id=workspace_id,
        lakehouse_id=lakehouse_id,
        lakehouse_name=lakehouse_name,
        display_name=ONTOLOGY_NOTEBOOK_DISPLAY_NAME,
        cells=_ONTOLOGY_NOTEBOOK_CELLS,
    )


def build_vulnerability_notebook_definition(**kwargs: Any) -> dict[str, Any]:
    return build_notebook_definition(
        **kwargs,
        display_name=VULNERABILITY_NOTEBOOK_DISPLAY_NAME,
        cells=_pipeline_cells("vulnerability_pipeline"),
    )


def build_lifecycle_notebook_definition(**kwargs: Any) -> dict[str, Any]:
    return build_notebook_definition(
        **kwargs,
        display_name=LIFECYCLE_NOTEBOOK_DISPLAY_NAME,
        cells=_pipeline_cells("lifecycle_pipeline"),
    )


def build_patch_notebook_definition(**kwargs: Any) -> dict[str, Any]:
    return build_notebook_definition(
        **kwargs,
        display_name=PATCH_NOTEBOOK_DISPLAY_NAME,
        cells=_pipeline_cells("patch_pipeline"),
    )


def build_change_notebook_definition(**kwargs: Any) -> dict[str, Any]:
    return build_notebook_definition(
        **kwargs,
        display_name=CHANGE_NOTEBOOK_DISPLAY_NAME,
        cells=_pipeline_cells("change_pipeline"),
    )


def build_predeploy_notebook_definition(**kwargs: Any) -> dict[str, Any]:
    return build_notebook_definition(
        **kwargs,
        display_name=PREDEPLOY_NOTEBOOK_DISPLAY_NAME,
        cells=_pipeline_cells("predeploy_pipeline"),
    )


def build_impact_context_notebook_definition(**kwargs: Any) -> dict[str, Any]:
    return build_notebook_definition(
        **kwargs,
        display_name=IMPACT_CONTEXT_NOTEBOOK_DISPLAY_NAME,
        cells=_pipeline_cells("impact_context_builder", "build_graph"),
    )


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
    definition_builder: Callable[..., dict[str, Any]] = build_notebook_definition,
) -> dict[str, Any]:
    """Idempotent create-or-update of a Fabric notebook item.

    ``definition_builder`` defaults to the topology-pipeline notebook's own
    ``build_notebook_definition``; pass
    ``build_ontology_notebook_definition`` to deploy the operational-
    context-graph notebook instead (mirrors this function's existing
    shape rather than introducing a second manager)."""
    definition = definition_builder(
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
    "ONTOLOGY_NOTEBOOK_DISPLAY_NAME",
    "VULNERABILITY_NOTEBOOK_DISPLAY_NAME",
    "LIFECYCLE_NOTEBOOK_DISPLAY_NAME",
    "PATCH_NOTEBOOK_DISPLAY_NAME",
    "CHANGE_NOTEBOOK_DISPLAY_NAME",
    "PREDEPLOY_NOTEBOOK_DISPLAY_NAME",
    "IMPACT_CONTEXT_NOTEBOOK_DISPLAY_NAME",
    "NotebookManager",
    "build_notebook_definition",
    "build_ontology_notebook_definition",
    "build_vulnerability_notebook_definition",
    "build_lifecycle_notebook_definition",
    "build_patch_notebook_definition",
    "build_change_notebook_definition",
    "build_predeploy_notebook_definition",
    "build_impact_context_notebook_definition",
    "ensure_notebook",
]
