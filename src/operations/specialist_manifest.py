"""Strict loader for the versioned Operations specialist contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

INVENTORY_DATA_HEALTH_ID = "inventory_data_health"
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


class ManifestModel(BaseModel):
    """Base model that rejects undeclared specialist contract fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class KnowledgePolicy(ManifestModel):
    mode: Literal["deterministic_first"]
    optional_sources: tuple[str, ...] = ()


class OutputContract(ManifestModel):
    schema_version: Literal["1"]
    requires_citations: bool = True
    statuses: tuple[
        Literal["ok", "empty", "partial", "unavailable", "denied"], ...
    ]


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
    dependencies: tuple[str, ...] = Field(default=(), max_length=8)
    operations_mcp_tools: tuple[str, ...] = Field(default=(), max_length=16)
    azure_mcp_tools: tuple[str, ...] = Field(default=(), max_length=16)
    knowledge_policy: KnowledgePolicy
    page_mappings: tuple[
        Literal["inventory", "connections", "connections_fabric"], ...
    ] = Field(min_length=1, max_length=8)
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
        if any(marker in tool.casefold() for tool in tool_names for marker in _MUTATION_MARKERS):
            raise ValueError("specialist contracts may contain only read-only tools")
        return self


class SpecialistManifest(ManifestModel):
    """Versioned source contract for reviewed Operations specialists."""

    version: Literal["1"]
    contract_version: Literal["1.0"]
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
        return self

    def require(self, specialist_id: str) -> SpecialistDefinition:
        """Return a specialist definition or reject the unknown identifier."""

        for specialist in self.specialists:
            if specialist.id == specialist_id:
                return specialist
        raise ValueError(f"unknown specialist {specialist_id!r}")


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


def load_specialist_manifest(
    path: str | Path | None = None,
) -> SpecialistManifest:
    """Load and strictly validate a specialist manifest from disk."""

    manifest_path = Path(path) if path is not None else _DEFAULT_MANIFEST_PATH
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _reject_credentials(payload)
    return SpecialistManifest.model_validate(payload)


__all__ = [
    "INVENTORY_DATA_HEALTH_ID",
    "SpecialistDefinition",
    "SpecialistManifest",
    "load_specialist_manifest",
]
