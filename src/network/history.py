"""Explicit retained topology projections, not resource lifecycle or traffic history."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_CAPTURES = 5
MAX_NODES = 1500
MAX_EDGES = 6000
MAX_BYTES = 2 * 1024 * 1024
MAX_INT = 9_007_199_254_740_991
UUID_PATTERN = r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$"


class CaptureRequest(BaseModel):
    """Capture only a reviewed history revision; clients cannot supply topology."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=MAX_INT - 1)


class TopologyNode(BaseModel):
    """Fixed safe metadata only; rule contents, tags and arbitrary properties are absent."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, max_length=2048)
    name: str = Field(max_length=512)
    entity_type: str = Field(min_length=1, max_length=128)
    role: str = Field(max_length=128)
    subscription_id: str = Field(max_length=128)
    resource_group: str = Field(max_length=512)
    location: str = Field(max_length=128)
    connection_id: str = Field(max_length=128)
    environment: str = Field(max_length=128)
    business_service: str = Field(max_length=512)
    application: str = Field(max_length=512)
    owner: str = Field(max_length=512)


class PeeringState(BaseModel):
    """The configuration signals reported by the scoped topology, not packet proof."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    is_bidirectional: bool
    local_state: str = Field(max_length=128)
    remote_state: str = Field(max_length=128)
    allow_forwarded_traffic: bool
    allow_gateway_transit: bool
    use_remote_gateways: bool


class TopologyEdge(BaseModel):
    """A directed typed relationship with both endpoints in the retained projection."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, max_length=4352)
    source: str = Field(min_length=1, max_length=2048)
    target: str = Field(min_length=1, max_length=2048)
    relationship_type: str = Field(min_length=1, max_length=128)
    label: str = Field(max_length=512)
    peering: PeeringState | None

    @model_validator(mode="after")
    def coherent_edge(self):
        """Keep identity and peering payload unambiguous across captures."""
        if self.id != f"{self.relationship_type}:{self.source}::{self.target}":
            raise ValueError("Retained topology edge identity is invalid")
        if (self.relationship_type == "peering") != (self.peering is not None):
            raise ValueError("Retained topology peering metadata is invalid")
        return self


class TopologyCapture(BaseModel):
    """One bounded summary projection with request and reported source provenance."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    capture_id: str = Field(pattern=UUID_PATTERN)
    started_at: str = Field(max_length=40)
    finished_at: str = Field(max_length=40)
    source_observed_at: str = Field(max_length=64)
    nodes: list[TopologyNode] = Field(max_length=MAX_NODES)
    edges: list[TopologyEdge] = Field(max_length=MAX_EDGES)
    omitted_boundary_peering_count: int = Field(ge=0, le=MAX_INT)
    dropped_relationship_count: int = Field(ge=0, le=MAX_INT)

    @model_validator(mode="after")
    def coherent_capture(self):
        """Reject corrupt times, duplicate identities and dangling retained relationships."""
        start, finish = map(datetime.fromisoformat, (self.started_at, self.finished_at))
        if start.tzinfo is None or finish.tzinfo is None or start > finish:
            raise ValueError("Topology capture time order is invalid")
        if self.source_observed_at:
            observed = datetime.fromisoformat(self.source_observed_at)
            if observed.tzinfo is None or observed > finish:
                raise ValueError("Topology source observation time is invalid")
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes) or len({edge.id for edge in self.edges}) != len(
            self.edges
        ):
            raise ValueError("Topology identities must be distinct")
        if any(edge.source not in ids or edge.target not in ids for edge in self.edges):
            raise ValueError("Topology relationships require retained endpoints")
        return self


class TopologyHistory(BaseModel):
    """Exact actor/effective-scope chronological history for projection schema one."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(ge=1, le=1)
    actor: str
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_INT)
    captures: list[TopologyCapture] = Field(max_length=MAX_CAPTURES)

    @model_validator(mode="after")
    def coherent_history(self):
        """Never reinterpret corrupt or duplicate history as an empty collection."""
        if len(self.captures) != min(self.revision, MAX_CAPTURES):
            raise ValueError("Topology history revision is invalid")
        if len({row.capture_id for row in self.captures}) != len(self.captures):
            raise ValueError("Topology capture identities must be distinct")
        times = [datetime.fromisoformat(row.finished_at) for row in self.captures]
        if times != sorted(times):
            raise ValueError("Topology capture receipts must be chronological")
        return self


class NetworkHistoryStore:
    """Retain five explicit safe topology projections on the existing durable CAS root."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/network-history/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bytes(payload: dict) -> int:
        return len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists and self._bytes(snapshot.payload) > MAX_BYTES:
            raise RuntimeError("Stored topology history exceeds its document limit")
        try:
            state = (
                TopologyHistory.model_validate(snapshot.payload)
                if snapshot.exists
                else TopologyHistory(
                    schema_version=1, actor=actor, scope=scope, revision=0, captures=[]
                )
            )
        except ValidationError as exc:
            raise RuntimeError("Stored topology history schema is invalid") from exc
        if (state.actor, state.scope) != (actor, scope):
            raise RuntimeError("Stored topology history identity is invalid")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Read retained receipts without refreshing the current Network provider."""
        return self._read(actor, scope)[2].model_dump()

    def append(
        self,
        actor: str,
        scope: dict[str, list[str]],
        expected_revision: int,
        capture: TopologyCapture,
    ) -> dict:
        """Append one server-acquired projection or fail without advancing history."""
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision:
            raise DocumentConflictError(
                "Topology history changed; reload before capturing"
            )
        updated = TopologyHistory(
            schema_version=1,
            actor=actor,
            scope=scope,
            revision=state.revision + 1,
            captures=[*state.captures, capture][-MAX_CAPTURES:],
        ).model_dump()
        if self._bytes(updated) > MAX_BYTES:
            raise ValueError(
                "Topology history exceeds its 2 MiB document limit; narrow the scope"
            )
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated


def topology_capture(
    topology: dict, source_observed_at: str, started_at: str, finished_at: str
) -> TopologyCapture:
    """Project an untruncated scoped summary without embedded rules or boundary identities."""
    coverage = topology["coverage"]
    if (
        coverage["truncated"] is not False
        or coverage["nodes"]["truncated"] is not False
        or coverage["nodes"]["total"] != coverage["nodes"]["returned"]
        or coverage["relationships"]["truncated"] is not False
    ):
        raise ValueError(
            "Topology summary is truncated; narrow the scope before capturing"
        )
    nodes = [
        TopologyNode.model_validate(
            {key: row[key] for key in TopologyNode.model_fields}
        )
        for row in topology["resources"]
    ]
    ids = {node.id for node in nodes}
    edges = [
        TopologyEdge.model_validate(
            {
                **{
                    key: row[key]
                    for key in ("id", "source", "target", "relationship_type", "label")
                },
                "peering": None,
            }
        )
        for row in topology["relationships"]
    ]
    omitted = 0
    for link in topology["links"]:
        if link["local_vnet_id"] not in ids or link["remote_vnet_id"] not in ids:
            omitted += 1
            continue
        source, target = link["local_vnet_id"], link["remote_vnet_id"]
        edges.append(
            TopologyEdge(
                id=f"peering:{source}::{target}",
                source=source,
                target=target,
                relationship_type="peering",
                label="VNet peering",
                peering=PeeringState.model_validate(
                    {key: link[key] for key in PeeringState.model_fields}
                ),
            )
        )
    dropped = topology["counts"]["dropped_relationships"]
    if any(type(value) is not int or value < 0 for value in dropped.values()):
        raise ValueError("Topology dropped relationship counts are invalid")
    return TopologyCapture(
        capture_id=str(uuid4()),
        started_at=started_at,
        finished_at=finished_at,
        source_observed_at=source_observed_at,
        nodes=sorted(nodes, key=lambda row: row.id),
        edges=sorted(edges, key=lambda row: row.id),
        omitted_boundary_peering_count=omitted,
        dropped_relationship_count=sum(dropped.values()),
    )


def compare_captures(before: TopologyCapture, after: TopologyCapture) -> list[dict]:
    """Compare only fixed retained fields, without inferring lifecycle or change cause."""
    changes = []
    for kind, left, right in (
        ("node", before.nodes, after.nodes),
        ("edge", before.edges, after.edges),
    ):
        previous = {row.id: row.model_dump() for row in left}
        current = {row.id: row.model_dump() for row in right}
        for identity in sorted(previous.keys() | current.keys()):
            old, new = previous.get(identity), current.get(identity)
            if old == new:
                continue
            change: Literal["added", "no_longer_observed", "changed"] = (
                "added"
                if old is None
                else "no_longer_observed"
                if new is None
                else "changed"
            )
            fields = (
                sorted(key for key in old if old[key] != new[key])
                if old and new
                else []
            )
            changes.append(
                {
                    "kind": kind,
                    "id": identity,
                    "change": change,
                    "changed_fields": fields,
                    "before": old,
                    "after": new,
                }
            )
    return changes
