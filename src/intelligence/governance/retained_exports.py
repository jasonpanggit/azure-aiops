"""Personal exact-scope audit captures, never current evidence or release authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from onboarding.credentials import redact
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_CAPTURES = 10
MAX_CAPTURE_BYTES = 512 * 1024
MAX_COLLECTION_BYTES = 6 * 1024 * 1024
MAX_REVISION = 9_007_199_254_740_991
AuditKind = Literal[
    "subscription_onboarding", "network_design", "firewall_nsg",
    "vulnerability_exposure", "identity", "remediation", "executive",
]
ExportId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class AuditCaptureRequestError(ValueError):
    """An explicit request exceeds capture/revision bounds, not a storage fault."""


class AuditCaptureNotFoundError(LookupError):
    """A missing stored identity, distinct from malformed provider material."""


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def _aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Audit capture times must be timezone-aware")
    return result


class AuditCaptureRequest(BaseModel):
    """Select the current server-generated kind, never accept a client pack."""

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: AuditKind
    expected_revision: int = Field(ge=0, lt=MAX_REVISION)


class AuditCaptureRemoval(BaseModel):
    """Explicit removal from the reviewed personal collection."""

    model_config = ConfigDict(extra="forbid", strict=True)
    export_id: ExportId
    expected_revision: int = Field(ge=0, lt=MAX_REVISION)


class AuditCapture(BaseModel):
    """Frozen standard-redacted JSON with verifiable exact downloaded bytes."""

    model_config = ConfigDict(extra="forbid", strict=True)
    export_id: ExportId
    kind: AuditKind
    captured_at: str = Field(max_length=40)
    generated_at: str = Field(max_length=40)
    observed_at: str = Field(max_length=256)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=MAX_CAPTURE_BYTES)
    warning_count: int = Field(ge=0, le=MAX_CAPTURE_BYTES)
    content: str = Field(max_length=MAX_CAPTURE_BYTES)

    @model_validator(mode="after")
    def coherent_capture(self):
        """A timestamp or checksum mismatch is corruption, not a recoverable empty pack."""
        _aware(self.captured_at)
        _aware(self.generated_at)
        encoded = self.content.encode("utf-8")
        if len(encoded) != self.size_bytes or hashlib.sha256(encoded).hexdigest() != self.sha256:
            raise ValueError("Audit capture content integrity is invalid")
        document = json.loads(self.content)
        if _json(document) != self.content or not isinstance(document, dict):
            raise ValueError("Audit capture JSON must be canonical")
        data = document["data"]
        provenance = data["provenance"]
        if (
            data["kind"] != self.kind
            or provenance["generated_at"] != self.generated_at
            or provenance["observed_at"] != self.observed_at
            or not isinstance(document.get("evidence"), list)
            or not isinstance(data.get("sections"), dict)
            or not isinstance(document.get("warnings", []), list)
            or len(document.get("warnings", [])) != self.warning_count
        ):
            raise ValueError("Audit capture provenance is invalid")
        if redact(document) != document:
            raise ValueError("Audit capture contains unredacted secret-key material")
        return self


class AuditCaptureCollection(BaseModel):
    """One complete bounded document per exact authenticated subject and scope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str = Field(min_length=1, max_length=4096)
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_REVISION)
    captures: list[AuditCapture] = Field(max_length=MAX_CAPTURES)

    @model_validator(mode="after")
    def coherent_collection(self):
        ids = [row.export_id for row in self.captures]
        if len(ids) != len(set(ids)) or len(ids) > self.revision:
            raise ValueError("Audit capture collection identities are invalid")
        for row in self.captures:
            document = json.loads(row.content)
            if document["scope"] != self.scope or document["data"]["provenance"]["scope"] != self.scope:
                raise ValueError("Audit capture scope is invalid")
        if len(_json(self.model_dump()).encode()) > MAX_COLLECTION_BYTES:
            raise ValueError("Audit capture collection exceeds 6 MiB")
        return self


class RetainedAuditExportStore:
    """Retain explicitly requested packs using existing local/OneLake CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/governance-exports/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        try:
            snapshot = self.documents.read_snapshot(name)
            if snapshot.exists and len(_json(snapshot.payload).encode()) > MAX_COLLECTION_BYTES:
                raise ValueError("Audit capture collection exceeds its document limit")
            state = (
                AuditCaptureCollection.model_validate(snapshot.payload) if snapshot.exists
                else AuditCaptureCollection(actor=actor, scope=scope, revision=0, captures=[])
            )
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            raise RuntimeError("Retained audit export storage is invalid") from exc
        if state.actor != actor or state.scope != scope:
            raise RuntimeError("Retained audit export collection identity is invalid")
        return name, snapshot, state

    @staticmethod
    def _manifest(state: AuditCaptureCollection) -> dict[str, Any]:
        return {
            **state.model_dump(exclude={"captures"}),
            "captures": [row.model_dump(exclude={"content"}) for row in reversed(state.captures)],
            "redaction": "standard_secret_keys",
        }

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict[str, Any]:
        """Recover metadata without consulting any current evidence provider."""
        return self._manifest(self._read(actor, scope)[2])

    def detail(self, actor: str, scope: dict[str, list[str]], export_id: str) -> dict[str, Any]:
        """Recover immutable bytes only within the caller's current exact read scope."""
        state = self._read(actor, scope)[2]
        row = next((row for row in state.captures if row.export_id == export_id), None)
        if row is None:
            raise AuditCaptureNotFoundError("Retained audit export not found")
        return {"manifest": row.model_dump(exclude={"content"}), "content": row.content,
                "redaction": "standard_secret_keys"}

    def capture(
        self, actor: str, scope: dict[str, list[str]], expected_revision: int,
        *, document: dict[str, Any],
    ) -> dict[str, Any]:
        """Capture a complete server pack once; never truncate, replace or evict."""
        if type(expected_revision) is not int or not 0 <= expected_revision < MAX_REVISION:
            raise AuditCaptureRequestError("A safe reviewed collection revision is required")
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision or state.revision >= MAX_REVISION:
            raise DocumentConflictError("Audit exports changed; reload before capturing")
        if len(state.captures) >= MAX_CAPTURES:
            raise AuditCaptureRequestError("Audit export collection is full; explicitly remove a capture")
        safe = redact(document)
        content = _json(safe)
        encoded = content.encode()
        if len(encoded) > MAX_CAPTURE_BYTES:
            raise AuditCaptureRequestError("Audit export exceeds 512 KiB; narrow the selected scope")
        try:
            data = safe["data"]
            provenance = data["provenance"]
            row = AuditCapture(
                export_id=uuid4().hex, kind=data["kind"],
                captured_at=datetime.now(UTC).isoformat(),
                generated_at=provenance["generated_at"], observed_at=provenance["observed_at"],
                sha256=hashlib.sha256(encoded).hexdigest(), size_bytes=len(encoded),
                warning_count=len(safe.get("warnings", [])), content=content,
            )
            payload = {
                "schema_version": 1, "actor": actor, "scope": scope,
                "revision": state.revision + 1,
                "captures": [item.model_dump() for item in [*state.captures, row]],
            }
            if len(_json(payload).encode()) > MAX_COLLECTION_BYTES:
                raise AuditCaptureRequestError("Audit collection exceeds 6 MiB; explicitly remove a capture")
            updated = AuditCaptureCollection.model_validate(payload)
        except (KeyError, TypeError, ValidationError) as exc:
            raise RuntimeError("Generated audit pack cannot be retained safely") from exc
        if snapshot.exists:
            self.documents.replace_if_match(name, updated.model_dump(), expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated.model_dump())
        return self._manifest(updated)

    def remove(
        self, actor: str, scope: dict[str, list[str]], expected_revision: int, export_id: str,
    ) -> dict[str, Any]:
        """Remove one reviewed capture; already downloaded files cannot be revoked."""
        if type(expected_revision) is not int or not 0 <= expected_revision < MAX_REVISION:
            raise AuditCaptureRequestError("A safe reviewed collection revision is required")
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision or state.revision >= MAX_REVISION:
            raise DocumentConflictError("Audit exports changed; reload before removing")
        remaining = [row for row in state.captures if row.export_id != export_id]
        if len(remaining) == len(state.captures):
            raise AuditCaptureNotFoundError("Retained audit export not found")
        state = AuditCaptureCollection(
            actor=actor, scope=scope, revision=state.revision + 1, captures=remaining,
        )
        self.documents.replace_if_match(name, state.model_dump(), expected_etag=snapshot.etag)
        return self._manifest(state)
