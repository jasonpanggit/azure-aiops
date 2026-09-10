"""Manages the Fabric Data Agent item that proposes advisory, non-authoritative
relationship suggestions on top of the deterministic ontology graph written by
the ontology pipeline (``ontology_entities``/``ontology_relationships``
in the ``operational_context_graph`` lakehouse).

Mirrors the other Fabric item managers' resolve-by-name-or-id,
create-if-missing pattern via Fabric's generic Items API
(``POST/GET /workspaces/{id}/items``), the same surface those managers use,
rather than the Microsoft-published ``fabric-data-agent-sdk`` package.

Why not the SDK (documented, not a shortcut): this repo already owns a
top-level ``fabric`` Python package (``src/fabric/``, a regular package with
an ``__init__.py``, importable as ``fabric.auth``/``fabric.fabric_client``/
etc. throughout this codebase). ``fabric-data-agent-sdk`` publishes its own
code under the *same* top-level ``fabric`` namespace (``fabric.dataagent``).
Verified live in this repo's ``.venv``: with both installed, ``import
fabric`` always resolves to this repo's ``src/fabric/__init__.py`` (it is
first on ``sys.path`` and is a regular, non-namespace package), so
``from fabric.dataagent.client import ...`` raises
``ModuleNotFoundError: No module named 'fabric.dataagent'`` even though the
SDK package is genuinely installed (confirmed via
``pip show -f fabric-data-agent-sdk``, which does list
``fabric/dataagent/...`` files under site-packages). Renaming this repo's
long-established ``fabric`` package to work around a third-party package's
namespace choice is out of scope for this exploratory addition, so this
module talks to the same public Fabric Items REST API the SDK itself uses
under the hood (per Microsoft Learn's "Fabric data agent Python SDK
(preview)" doc: "It runs on the Fabric public REST API, which is the same
surface you already use for other workspaces and items").

Item-management ("management plane") operations -- create the DataAgent
item, attach a lakehouse datasource, set AI instructions, publish -- are
covered by this manager.

Querying a published Data Agent ("runtime") is a *distinct* surface: per
Microsoft Learn ("Fabric data agent Python SDK (preview)"), a published
Data Agent is queried through its Model Context Protocol (MCP) endpoint
(``https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspaceId}/dataagents/{dataAgentId}/agent``)
or the SDK's OpenAI-compatible client -- there is no plain synchronous
REST "ask a question, get structured JSON back" endpoint documented for
this preview feature. See ``docs/fabric-data-agent-relationship-suggestions.md``
for the honest write-up of what is/isn't automatable today."""

from __future__ import annotations

import base64
import copy
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .fabric_client import FabricClient

if TYPE_CHECKING:
    from ontology_discovery.generation_resolver import (
        CompatibilityAlias,
        GenerationSelection,
    )

ITEM_TYPE = "DataAgent"

#: Fabric's published Data Agent definition schema version, per Microsoft
#: Learn's "Data Agent item definition" article (verified live 2026 doc
#: fetch): the top-level ``Files/Config/data_agent.json`` part just pins
#: this schema version, all real configuration lives in the sibling
#: ``stage_config.json``/``datasource.json``/``fewshots.json`` parts.
_DATA_AGENT_SCHEMA_VERSION = "2.1.0"
_DATASOURCE_SCHEMA_VERSION = "1.0.0"
_FEW_SHOTS_SCHEMA_VERSION = "1.0.0"
_STAGE_CONFIG_SCHEMA_VERSION = "1.0.0"

#: Fixed AI instructions steering the Data Agent toward proposing candidate
#: relationships (not answering arbitrary BI questions) -- this is the
#: prompt/system-instruction half of "prompts the Data Agent to analyze the
#: entity/relationship tables and propose candidate additional
#: relationships"; the other half (actually invoking it and parsing a
#: structured response) is the documented gap -- see module docstring.
RELATIONSHIP_SUGGESTION_INSTRUCTIONS = (
    "You analyze the ontology_entities and ontology_relationships tables of "
    "an operational context graph (Application, BusinessService, "
    "VirtualMachine, PatchAssessment, AdvisorRecommendation, and other "
    "resource entity types, connected by belongsTo/assessedBy/impacts/"
    "dependsOn and other deterministic relationships). Your job is only to "
    "SUGGEST additional candidate relationships that the existing "
    "relationships table does not already contain, based on patterns you "
    "notice in the data -- for example, resources sharing the same tag "
    "values, similar naming conventions, or correlated deployment "
    "timestamps/locations. For every candidate relationship you propose, "
    "respond with one JSON object per line containing exactly these keys: "
    "subject_id, subject_type, predicate, object_id, object_type, "
    "confidence (0.0-1.0), rationale (a short plain-English explanation of "
    "the pattern you noticed). Never claim a relationship already present "
    "in ontology_relationships is new. Do not attempt to modify any table; "
    "you are advisory only."
)


class DataAgentManager:
    """Thin manager over Fabric's DataAgent item type."""

    ITEM_TYPE = ITEM_TYPE

    def __init__(self, client: FabricClient, workspace_id: str) -> None:
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
            raise ValueError(f"Multiple Fabric data agents named {display_name!r}; configure item_id")
        return matches[0] if matches else None

    def create(
        self,
        display_name: str,
        *,
        lakehouse_id: str,
        lakehouse_workspace_id: str,
        lakehouse_display_name: str,
        description: str = "",
        ai_instructions: str = RELATIONSHIP_SUGGESTION_INSTRUCTIONS,
        table_names: tuple[str, ...] = ("ontology_entities", "ontology_relationships"),
        data_source_instructions: str = "",
        few_shots: tuple[Mapping[str, str], ...] = (),
    ) -> dict[str, Any]:
        """Creates a DataAgent item with a public definition (per Microsoft
        Learn's "Data Agent item definition" article) that already stages a
        lakehouse-tables datasource pointed at the ontology lakehouse and
        sets the relationship-suggestion AI instructions -- so the item is
        immediately usable (modulo publishing) rather than requiring a
        second manual portal configuration pass."""
        definition = build_data_agent_definition(
            lakehouse_id=lakehouse_id,
            lakehouse_workspace_id=lakehouse_workspace_id,
            lakehouse_display_name=lakehouse_display_name,
            ai_instructions=ai_instructions,
            table_names=table_names,
            data_source_instructions=data_source_instructions,
            few_shots=few_shots,
        )
        return self.client.request(
            "POST",
            self.base_path,
            json_body={
                "displayName": display_name,
                "description": description
                or "Advisory relationship-suggestion Data Agent over the ontology_pipeline graph",
                "type": self.ITEM_TYPE,
                "definition": definition,
            },
        )

    def update_definition(
        self,
        item_id: str,
        definition: dict[str, Any],
        *,
        existing_definition: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Updates an existing DataAgent item's staged definition via the
        generic Items API's ``updateDefinition`` operation (unlike
        ``publish``, this one *is* the standard generic-Items-API path and
        is shared across item types, including Notebook/Environment
        elsewhere in this repo).

        Existing published and platform parts are preserved so staging a new
        draft never silently withdraws the currently published agent."""
        if existing_definition is None:
            existing_definition = self.get_definition(item_id)
        definition = _preserve_server_parts(definition, existing_definition)
        return self.client.request(
            "POST",
            f"{self.base_path}/{item_id}/updateDefinition",
            json_body={"definition": definition},
        )

    def get_definition(self, item_id: str) -> dict[str, Any]:
        """Returns the complete draft and published Data Agent definition."""
        return self.client.request(
            "POST",
            f"{self.base_path}/{item_id}/getDefinition",
            json_body={"format": "Default"},
        )

    def publish(self, item_id: str, *, published_description: str = "") -> dict[str, Any]:
        """Publishes the staged DataAgent configuration, per Microsoft
        Learn's "Publish Data Agent" operation -- verified live against the
        actual API during this session, this is a DataAgent-specific path
        (``POST /workspaces/{id}/dataAgents/{dataAgentId}/staging/publish``),
        distinct from the generic Items API's own ``.../items/{id}/publish``
        (which 404s for DataAgent items; the initial implementation of this
        method assumed the generic path and had to be corrected after a
        live 404). Uses the DataAgent-specific staging publish path."""
        # Verified live: this endpoint 400s if the JSON body is omitted
        # entirely (``json_body=None``) but accepts ``{}``, so always send a
        # (possibly empty) dict rather than collapsing an empty body away.
        body: dict[str, Any] = {}
        if published_description:
            body["publishedDescription"] = published_description
        return self.client.request(
            "POST",
            f"/workspaces/{self.workspace_id}/dataAgents/{item_id}/staging/publish",
            json_body=body,
        )


def _b64(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def build_data_agent_definition(
    *,
    lakehouse_id: str,
    lakehouse_workspace_id: str,
    lakehouse_display_name: str,
    ai_instructions: str,
    table_names: tuple[str, ...] = ("ontology_entities", "ontology_relationships"),
    generation: GenerationSelection | None = None,
    table_aliases: Mapping[str, CompatibilityAlias] | None = None,
    data_source_instructions: str = "",
    few_shots: tuple[Mapping[str, str], ...] = (),
) -> dict[str, Any]:
    """Builds the DataAgent item definition ``parts`` payload per Microsoft
    Learn's "Data Agent item definition" article (fetched live during this
    session): ``Files/Config/data_agent.json`` (schema pin),
    ``Files/Config/draft/stage_config.json`` (AI instructions),
    ``Files/Config/draft/{type}-{name}/datasource.json`` (one lakehouse
    datasource, staged so a subsequent ``publish()`` call promotes it).

    ``table_names`` are staged as *selected* ``lakehouse_tables.table``
    elements on the datasource (``is_selected: true``) -- fetched from the
    ``DataSourceElement`` schema at
    ``developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/dataSource/1.0.0/schema.json``.
    This was discovered live during this session: a datasource with no
    ``elements`` selected causes ``tools/call`` on the published agent's MCP
    endpoint to return ``{"isError": true, "text": "...run failed before
    producing a result."}`` -- the agent has a lakehouse attached but no
    tables it's actually allowed to query. Explicitly selecting
    ``ontology_entities``/``ontology_relationships`` (the two Delta tables
    ``ontology_pipeline.py`` writes) fixes this.

    This only stages the *definition* of what data source the agent should
    reason over and how it should behave -- it does not itself invoke the
    agent (see module docstring: querying is a separate, MCP-based runtime
    surface, not exercised by this manager)."""

    if table_aliases is not None:
        table_names = _bound_alias_names(table_names, generation, table_aliases)
    if not table_names or any(not name.strip() for name in table_names):
        raise ValueError("Data Agent definitions require at least one named table")
    if len(set(table_names)) != len(table_names):
        raise ValueError("Data Agent table names must be unique")
    datasource_name = lakehouse_display_name or "ontology_lakehouse"
    datasource_part_prefix = f"Files/Config/draft/lakehouse_tables-{datasource_name}"

    data_agent_json = {"$schema": _DATA_AGENT_SCHEMA_VERSION}
    stage_config_json = {
        "$schema": _STAGE_CONFIG_SCHEMA_VERSION,
        "aiInstructions": ai_instructions,
    }
    datasource_json = {
        "$schema": _DATASOURCE_SCHEMA_VERSION,
        "artifactId": lakehouse_id,
        "workspaceId": lakehouse_workspace_id,
        "displayName": datasource_name,
        "type": "lakehouse_tables",
        "userDescription": (
            "Deterministic operational context graph (entities + "
            "relationships) ported from AIOps's entity_builder.py/"
            "relationship_builder.py."
        ),
        "elements": [
            {
                "is_selected": True,
                "display_name": table_name,
                "type": "lakehouse_tables.table",
            }
            for table_name in table_names
        ],
    }
    if data_source_instructions.strip():
        datasource_json["dataSourceInstructions"] = data_source_instructions.strip()

    parts = [
        {
            "path": "Files/Config/data_agent.json",
            "payload": _b64(data_agent_json),
            "payloadType": "InlineBase64",
        },
        {
            "path": "Files/Config/draft/stage_config.json",
            "payload": _b64(stage_config_json),
            "payloadType": "InlineBase64",
        },
        {
            "path": f"{datasource_part_prefix}/datasource.json",
            "payload": _b64(datasource_json),
            "payloadType": "InlineBase64",
        },
    ]
    if few_shots:
        parts.append(
            {
                "path": f"{datasource_part_prefix}/fewshots.json",
                "payload": _b64(
                    {
                        "$schema": _FEW_SHOTS_SCHEMA_VERSION,
                        "fewShots": [_normalize_few_shot(item) for item in few_shots],
                    }
                ),
                "payloadType": "InlineBase64",
            }
        )
    return {"parts": parts}


def _normalize_few_shot(example: Mapping[str, str]) -> dict[str, str]:
    example_id = str(example.get("id") or "").strip()
    question = str(example.get("question") or "").strip()
    query = str(example.get("query") or "").strip()
    if not example_id or not question or not query:
        raise ValueError("Each Data Agent few-shot requires id, question, and query")
    try:
        UUID(example_id)
    except ValueError as exc:
        raise ValueError("Data Agent few-shot id must be a UUID") from exc
    if not query.casefold().startswith("select"):
        raise ValueError("Data Agent few-shot queries must be read-only SELECT statements")
    return {"id": example_id, "question": question, "query": query}


def hydrate_data_agent_table_selection(
    definition: dict[str, Any],
    live_definition: Mapping[str, Any],
    table_names: tuple[str, ...],
) -> dict[str, Any]:
    """Bind a draft definition to Fabric's live nested table element IDs."""
    requested = set(table_names)
    if not requested or len(requested) != len(table_names):
        raise ValueError("Requested Data Agent tables must be non-empty and unique")

    hydrated = copy.deepcopy(definition)
    target_part = _single_draft_datasource_part(hydrated)
    live_parts = (live_definition.get("definition") or live_definition).get("parts")
    if not isinstance(live_parts, list):
        raise TypeError("Live Data Agent definition parts are unavailable")
    live_part = _single_draft_datasource_part({"parts": live_parts})
    target_payload = _decoded_part(target_part)
    live_payload = _decoded_part(live_part)
    for field in ("artifactId", "workspaceId", "displayName", "type"):
        if target_payload.get(field) != live_payload.get(field):
            raise ValueError(f"Live Data Agent datasource {field} does not match the target")

    target_path = str(target_part.get("path") or "")
    live_path = str(live_part.get("path") or "")
    if target_path != live_path:
        target_prefix = target_path.removesuffix("/datasource.json")
        live_prefix = live_path.removesuffix("/datasource.json")
        for part in hydrated["parts"]:
            path = str(part.get("path") or "")
            if path.startswith(f"{target_prefix}/"):
                part["path"] = f"{live_prefix}{path.removeprefix(target_prefix)}"

    elements = copy.deepcopy(live_payload.get("elements") or [])
    discovered: set[str] = set()

    def select(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if node.get("type") == "lakehouse_tables.table":
                name = str(node.get("display_name") or "")
                node["is_selected"] = name in requested
                if name in requested:
                    discovered.add(name)
            children = node.get("children")
            if isinstance(children, list):
                select(children)

    select(elements)
    missing = sorted(requested - discovered)
    if missing:
        raise ValueError(f"Fabric Data Agent tables are missing: {missing}")
    target_payload["elements"] = elements
    if live_payload.get("metadata") is not None:
        target_payload["metadata"] = copy.deepcopy(live_payload["metadata"])
    target_part["payload"] = _b64(target_payload)
    return _preserve_server_parts(hydrated, live_definition)


def _single_draft_datasource_part(definition: dict[str, Any]) -> dict[str, Any]:
    parts = definition.get("parts")
    if not isinstance(parts, list):
        raise TypeError("Data Agent definition parts are unavailable")
    matches = [
        part
        for part in parts
        if isinstance(part, dict)
        and "/draft/" in str(part.get("path") or "")
        and str(part.get("path") or "").endswith("/datasource.json")
    ]
    if len(matches) != 1:
        raise ValueError("Data Agent definition must contain one draft datasource")
    return matches[0]


def _decoded_part(part: Mapping[str, Any]) -> dict[str, Any]:
    decoded = json.loads(base64.b64decode(str(part.get("payload") or "")))
    if not isinstance(decoded, dict):
        raise TypeError("Data Agent definition part must contain a JSON object")
    return decoded


def _preserve_server_parts(
    definition: dict[str, Any],
    live_definition: Mapping[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(definition)
    target_parts = merged.get("parts")
    live_parts = (live_definition.get("definition") or live_definition).get("parts")
    if not isinstance(target_parts, list) or not isinstance(live_parts, list):
        raise TypeError("Data Agent definition parts are unavailable")
    target_paths = {
        str(part.get("path") or "")
        for part in target_parts
        if isinstance(part, dict)
    }
    for part in live_parts:
        if not isinstance(part, dict):
            continue
        path = str(part.get("path") or "")
        preserve = (
            path == ".platform"
            or path == "Files/Config/publish_info.json"
            or path.startswith("Files/Config/published/")
        )
        if preserve and path not in target_paths:
            target_parts.append(copy.deepcopy(part))
            target_paths.add(path)
    return merged


def _bound_alias_names(
    table_names: tuple[str, ...],
    generation: GenerationSelection | None,
    table_aliases: Mapping[str, CompatibilityAlias],
) -> tuple[str, ...]:
    if generation is None:
        raise ValueError("generation is required with ontology table aliases")
    bound: list[str] = []
    for name in table_names:
        try:
            alias = table_aliases[name]
        except KeyError as exc:
            raise ValueError(f"Missing compatibility alias for {name!r}") from exc
        if alias.logical_name != name or alias.generation_id != generation.generation_id:
            raise ValueError(f"Compatibility alias for {name!r} is not bound to the selection")
        bound.append(alias.logical_name)
    return tuple(bound)


def ensure_data_agent(
    manager: DataAgentManager,
    *,
    display_name: str,
    lakehouse_id: str,
    lakehouse_workspace_id: str,
    lakehouse_display_name: str,
    item_id: str = "",
    ai_instructions: str = RELATIONSHIP_SUGGESTION_INSTRUCTIONS,
) -> dict[str, Any]:
    """Idempotent resolve-or-create of the DataAgent item.

    When an existing item is resolved, its staged definition is always
    re-pushed via ``update_definition`` (not just left as-is) -- this was
    necessary live during this session: the datasource/table-selection or
    AI-instructions content can change across script runs (e.g. adding
    ``elements`` table selections after discovering the agent otherwise has
    no queryable tables), and ``resolve()`` alone would silently keep
    serving the item's stale, already-broken definition."""
    item = manager.resolve(item_id=item_id, display_name=display_name)
    definition = build_data_agent_definition(
        lakehouse_id=lakehouse_id,
        lakehouse_workspace_id=lakehouse_workspace_id,
        lakehouse_display_name=lakehouse_display_name,
        ai_instructions=ai_instructions,
    )
    if item is not None:
        manager.update_definition(str(item["id"]), definition)
        return {**item, "action": "resolved"}
    created = manager.create(
        display_name,
        lakehouse_id=lakehouse_id,
        lakehouse_workspace_id=lakehouse_workspace_id,
        lakehouse_display_name=lakehouse_display_name,
        ai_instructions=ai_instructions,
    )
    return {**created, "action": "created"}


__all__ = [
    "ITEM_TYPE",
    "RELATIONSHIP_SUGGESTION_INSTRUCTIONS",
    "DataAgentManager",
    "build_data_agent_definition",
    "ensure_data_agent",
    "hydrate_data_agent_table_selection",
]
