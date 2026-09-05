"""Strict loader for the versioned Operations specialist contract."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

INVENTORY_DATA_HEALTH_ID = "inventory_data_health"
LOCKED_SPECIALIST_IDS = (
    "network",
    "vulnerability",
    "patch",
    "incident",
    "change",
    "governance",
    "remediation",
    "executive_summary",
    INVENTORY_DATA_HEALTH_ID,
    "identity_access",
    "finops",
    "resource_health_observability",
)
_DEFAULT_MANIFEST_PATH = Path(__file__).with_name("specialists.v1.json")
_CREDENTIAL_MARKERS = {
    "access_token",
    "api_key",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
}
_MUTATION_MARKERS = (
    "approve",
    "create",
    "delete",
    "execute",
    "mutation",
    "patch_apply",
    "restart",
    "update",
    "write",
)
_READ_ONLY_EXECUTE_TOOLS = {"arm_execute_query"}
_LOCKED_POLICY_DIGEST = "38f307f26927ac43919d0a8bd71fee8dc2fcffdae3d49796bb8321ec96edd8bf"
_READ_ONLY_AZURE_MCP_TOOLS = frozenset(
    {
        "advisor_recommendation_list",
        "advisor_recommendation_summary",
        "appservice_webapp_get",
        "arm_execute_query",
        "arm_get_deployment_status",
        "arm_query_costs",
        "compute_vm_get",
        "functionapp_get",
        "group_list",
        "monitor_activitylog_list",
        "monitor_resource_log_query",
        "policy_assignment_list",
        "resourcehealth_availability-status_get",
        "resourcehealth_health-events_list",
        "role_assignment_list",
        "subscription_list",
        "wellarchitectedframework_serviceguide_get",
    }
)

PageMapping = Literal[
    "overview",
    "network",
    "vulnerability",
    "patch",
    "incident",
    "compliance",
    "exposure",
    "cve_detail",
    "defender_posture",
    "kb_detail",
    "patch_priorities",
    "situations",
    "situation_detail",
    "changes",
    "changes_predeploy",
    "inventory",
    "connections",
    "connections_fabric",
    "governance",
    "identity",
    "finops",
    "remediation",
    "resource_health",
    "resource",
    "services",
    "service_detail",
    "twin",
    "copilot",
    "investigate",
    "agents",
]


class ManifestModel(BaseModel):
    """Base model that rejects undeclared specialist contract fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class KnowledgePolicy(ManifestModel):
    mode: Literal["deterministic_first"]
    optional_sources: tuple[str, ...] = ()


class OutputContract(ManifestModel):
    schema_version: Literal["1"]
    requires_citations: Literal[True] = True
    statuses: tuple[
        Literal["ok", "empty", "partial", "unavailable", "denied"], ...
    ]
    required_fields: tuple[str, ...] = Field(min_length=1, max_length=32)
    domain_fields: tuple[str, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def validate_fields(self) -> OutputContract:
        if len(self.required_fields) != len(set(self.required_fields)):
            raise ValueError("output required_fields must be unique")
        if len(self.domain_fields) != len(set(self.domain_fields)):
            raise ValueError("output domain_fields must be unique")
        return self


class UIMetadata(ManifestModel):
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)


class FoundryMetadata(ManifestModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    model: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=32)


class SpecialistDefinition(ManifestModel):
    """One stable, credential-free specialist definition."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=320)
    intent_examples: tuple[str, ...] = Field(min_length=1, max_length=20)
    dependencies: tuple[str, ...] = Field(default=(), max_length=16)
    operations_mcp_tools: tuple[str, ...] = Field(default=(), max_length=16)
    azure_mcp_tools: tuple[str, ...] = Field(default=(), max_length=16)
    knowledge_policy: KnowledgePolicy
    page_mappings: tuple[PageMapping, ...] = Field(min_length=1, max_length=8)
    output_contract: OutputContract
    ui_metadata: UIMetadata
    foundry: FoundryMetadata
    read_only: Literal[True]

    @model_validator(mode="after")
    def validate_unique_read_only_contract(self) -> SpecialistDefinition:
        collections = (
            self.intent_examples,
            self.dependencies,
            self.operations_mcp_tools,
            self.azure_mcp_tools,
            self.page_mappings,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("specialist contract collections must not contain duplicates")
        tool_names = (*self.operations_mcp_tools, *self.azure_mcp_tools)
        if any(_is_mutation_tool(tool) for tool in tool_names):
            raise ValueError("specialist contracts may contain only read-only tools")
        return self


class SpecialistManifest(ManifestModel):
    """Versioned source contract for reviewed Operations specialists."""

    version: Literal["1"]
    contract_version: Literal["1.0"]
    runtime_contract_version: Literal["network-finding.v1"]
    legacy_operations_mcp_tools: tuple[str, ...] = Field(min_length=1, max_length=32)
    specialists: tuple[SpecialistDefinition, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_specialist_graph(self) -> SpecialistManifest:
        ids = [specialist.id for specialist in self.specialists]
        if len(ids) != len(set(ids)):
            raise ValueError("specialist ids must be unique")
        known = set(ids)
        for specialist in self.specialists:
            unknown = set(specialist.dependencies) - known
            if unknown:
                raise ValueError(
                    f"specialist {specialist.id!r} has unknown dependencies: {sorted(unknown)}"
                )
        self._validate_acyclic_dependencies()
        if tuple(ids) != LOCKED_SPECIALIST_IDS:
            raise ValueError(
                "specialist ids must exactly match the locked twelve-specialist portfolio"
            )
        foundry_names = [specialist.foundry.name for specialist in self.specialists]
        if len(foundry_names) != len(set(foundry_names)):
            raise ValueError("Foundry specialist names must be unique")
        if len(self.legacy_operations_mcp_tools) != len(
            set(self.legacy_operations_mcp_tools)
        ):
            raise ValueError("legacy Operations MCP tools must be unique")
        executive = self.require("executive_summary")
        if executive.operations_mcp_tools or executive.azure_mcp_tools:
            raise ValueError("executive_summary must remain aggregation-only")
        if set(executive.dependencies) != known - {"executive_summary"}:
            raise ValueError("executive_summary must depend on every domain specialist")
        return self

    def _validate_acyclic_dependencies(self) -> None:
        dependencies = {
            specialist.id: specialist.dependencies
            for specialist in self.specialists
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(specialist_id: str) -> None:
            if specialist_id in visiting:
                raise ValueError("specialist dependency cycle detected")
            if specialist_id in visited:
                return
            visiting.add(specialist_id)
            for dependency in dependencies[specialist_id]:
                visit(dependency)
            visiting.remove(specialist_id)
            visited.add(specialist_id)

        for specialist_id in dependencies:
            visit(specialist_id)

    def require(self, specialist_id: str) -> SpecialistDefinition:
        """Return a specialist definition or reject the unknown identifier."""

        for specialist in self.specialists:
            if specialist.id == specialist_id:
                return specialist
        raise ValueError(f"unknown specialist {specialist_id!r}")

    @property
    def specialist_ids(self) -> tuple[str, ...]:
        """Return stable specialist IDs in manifest order."""

        return tuple(specialist.id for specialist in self.specialists)

    def operations_mcp_grants(self) -> dict[str, tuple[str, ...]]:
        """Project exact Operations MCP grants by specialist."""

        return {
            specialist.id: specialist.operations_mcp_tools
            for specialist in self.specialists
        }

    def azure_mcp_grants(self) -> dict[str, tuple[str, ...]]:
        """Project exact Azure MCP grants by specialist."""

        return {
            specialist.id: specialist.azure_mcp_tools
            for specialist in self.specialists
        }

    def operations_tool_names(self) -> tuple[str, ...]:
        """Return the deterministic union of reviewed Operations tools."""

        return _ordered_unique(
            tool
            for specialist in self.specialists
            for tool in specialist.operations_mcp_tools
        )

    def page_mapping_projection(self) -> dict[str, tuple[str, ...]]:
        """Project page kinds to their bounded specialist candidates."""

        pages: dict[str, list[str]] = {}
        for specialist in self.specialists:
            for page in specialist.page_mappings:
                pages.setdefault(page, []).append(specialist.id)
        return {page: tuple(ids) for page, ids in pages.items()}

    def runtime_projection(self) -> tuple[dict[str, Any], ...]:
        """Project manifest entries into the existing AgentDefinition shape."""

        return tuple(
            {
                "id": specialist.id,
                "name": f"{specialist.display_name} Agent",
                "role": specialist.purpose,
                "tools": list(specialist.operations_mcp_tools),
                "keywords": list(specialist.intent_examples),
                "depends_on": list(specialist.dependencies),
                "contract_version": self.runtime_contract_version,
            }
            for specialist in self.specialists
        )

    def catalog_projection(self) -> tuple[dict[str, Any], ...]:
        """Project stable API/UI metadata without provider readiness claims."""

        return tuple(
            {
                "id": specialist.id,
                "display_name": specialist.display_name,
                "purpose": specialist.purpose,
                "ui_metadata": specialist.ui_metadata.model_dump(mode="json"),
                "page_mappings": list(specialist.page_mappings),
            }
            for specialist in self.specialists
        )

    def output_contracts(self) -> dict[str, dict[str, set[str]]]:
        """Project strict finding contracts for prompt-output validation."""

        return {
            specialist.id: {
                "required": set(specialist.output_contract.required_fields),
                "domain_fields": set(specialist.output_contract.domain_fields),
            }
            for specialist in self.specialists
        }


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _is_mutation_tool(tool: str) -> bool:
    normalized = tool.casefold()
    if normalized in _READ_ONLY_EXECUTE_TOOLS:
        return False
    return any(marker in normalized for marker in _MUTATION_MARKERS)


def _reject_credentials(value: Any, *, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().casefold()
            if normalized in _CREDENTIAL_MARKERS or any(
                marker in normalized for marker in _CREDENTIAL_MARKERS
            ):
                raise ValueError(f"credentials are forbidden in specialist manifests: {path}.{key}")
            _reject_credentials(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        normalized = value.casefold()
        if any(
            re.search(rf"\b{re.escape(marker)}\s*[:=]", normalized)
            for marker in _CREDENTIAL_MARKERS
        ):
            raise ValueError(
                f"credentials are forbidden in specialist manifests: {path}"
            )


def _policy_digest(manifest: SpecialistManifest) -> str:
    serialized = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_specialist_manifest(
    path: str | Path | None = None,
) -> SpecialistManifest:
    """Load and strictly validate a specialist manifest from disk."""

    manifest_path = Path(path) if path is not None else _DEFAULT_MANIFEST_PATH
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _reject_credentials(payload)
    manifest = SpecialistManifest.model_validate(payload)

    from operations.tools import TOOL_REGISTRY

    missing_tools = set(manifest.operations_tool_names()) - set(TOOL_REGISTRY)
    if missing_tools:
        raise ValueError(f"missing Operations MCP tools: {sorted(missing_tools)}")
    missing_azure_tools = {
        tool
        for grants in manifest.azure_mcp_grants().values()
        for tool in grants
        if tool not in _READ_ONLY_AZURE_MCP_TOOLS
    }
    if missing_azure_tools:
        raise ValueError(
            f"missing or non-read-only Azure MCP tools: {sorted(missing_azure_tools)}"
        )
    if not set(manifest.legacy_operations_mcp_tools) <= set(
        manifest.operations_tool_names()
    ):
        raise ValueError("legacy Operations MCP tools must be reviewed grants")
    if _policy_digest(manifest) != _LOCKED_POLICY_DIGEST:
        raise ValueError("manifest does not match the locked specialist contract")
    return manifest


__all__ = [
    "INVENTORY_DATA_HEALTH_ID",
    "LOCKED_SPECIALIST_IDS",
    "SpecialistDefinition",
    "SpecialistManifest",
    "load_specialist_manifest",
]
