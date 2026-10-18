"""Shared scope-exact advisory reviews; never Azure RBAC or approval authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from onboarding.credentials import redact
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_REVISION = 9_007_199_254_740_991
MAX_CAMPAIGNS = 10
MAX_PRINCIPALS = 100
MAX_SOURCE_BYTES = 512 * 1024
MAX_COLLECTION_BYTES = 6 * 1024 * 1024
Audience = Literal["service_owner", "security", "auditor"]
Recommendation = Literal["retain_recommended", "revoke_recommended", "investigate"]
CampaignId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class CampaignRequestError(ValueError):
    """The explicit request violates a bound or campaign transition."""


class CampaignNotFoundError(LookupError):
    """The campaign is not present in this exact authorized scope."""


class CampaignReviewerError(PermissionError):
    """A recommendation was not made by the assigned authentication subject."""


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Campaign timestamps require an explicit timezone")
    return result


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    expected_revision: int = Field(ge=0, lt=MAX_REVISION)


class CampaignCreate(_Request):
    """Assign a named subject to newly composed, not client-uploaded, evidence."""

    title: str = Field(min_length=1, max_length=160)
    audience: Audience
    reviewer_subject: str = Field(min_length=1, max_length=4096)
    due_at: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def aware_deadline(self):
        _time(self.due_at)
        return self


class CampaignDecision(_Request):
    """A source-bound recommendation by the actual assigned authenticated subject."""

    campaign_id: CampaignId
    principal_id: str = Field(min_length=1, max_length=2048)
    recommendation: Recommendation
    reason: str = Field(min_length=1, max_length=1200)


class CampaignRemove(_Request):
    """Remove a terminal stored copy; downloaded records cannot be revoked."""

    campaign_id: CampaignId


class CampaignTransition(CampaignRemove):
    """Explicit attributed completion or cancellation."""

    reason: str = Field(min_length=1, max_length=1200)


class _Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    principal_id: str = Field(min_length=1, max_length=2048)
    recommendation: Recommendation
    reason: str = Field(min_length=1, max_length=1200)
    actor: str = Field(min_length=1, max_length=4096)
    recorded_at: str = Field(max_length=40)


class _Closure(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    actor: str = Field(min_length=1, max_length=4096)
    reason: str = Field(min_length=1, max_length=1200)
    recorded_at: str = Field(max_length=40)


class _RiskEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    classification: Literal["privileged_signal", "incomplete", "no_classified_signal"]
    unresolved_role_assignments: int = Field(ge=0)
    unknown_age_assignments: int = Field(ge=0)
    stale_assignments: int = Field(ge=0)
    age_evaluated_at: str = Field(max_length=40)
    effective_access: Literal["not_evaluated"]


class _ObservedPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    principal_id: str = Field(min_length=1, max_length=2048)
    principal_type: str = Field(max_length=256)
    assignment_count: int = Field(ge=0)
    privileged: bool
    stale: bool
    roles: list[str]
    widest_scope: str = Field(max_length=4096)
    widest_scope_breadth: str = Field(max_length=256)
    last_changed: str = Field(max_length=256)
    blast_radius: dict[str, int]
    risk_evidence: _RiskEvidence | None = None

    @model_validator(mode="after")
    def coherent_evidence(self):
        evidence = self.risk_evidence
        if evidence is not None:
            _time(evidence.age_evaluated_at)
            expected = "privileged_signal" if self.privileged else "incomplete" if evidence.unresolved_role_assignments else "no_classified_signal"
            if (
                evidence.classification != expected
                or evidence.unresolved_role_assignments > self.assignment_count
                or evidence.unknown_age_assignments + evidence.stale_assignments > self.assignment_count
                or self.stale != (evidence.stale_assignments > 0)
            ):
                raise ValueError("Campaign classification evidence is inconsistent")
        return self


class _Campaign(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    campaign_id: CampaignId
    title: str = Field(min_length=1, max_length=160)
    audience: Audience
    reviewer_subject: str = Field(min_length=1, max_length=4096)
    created_by: str = Field(min_length=1, max_length=4096)
    created_at: str = Field(max_length=40)
    due_at: str = Field(max_length=40)
    status: Literal["open", "completed", "cancelled"] = "open"
    source_content: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: list[_Decision] = Field(default_factory=list, max_length=MAX_PRINCIPALS)
    closure: _Closure | None = None

    def source(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        document = json.loads(self.source_content)
        field = {"service_owner": "items", "security": "privileged_principals", "auditor": "principals"}[self.audience]
        return document, document["data"][field]

    @model_validator(mode="after")
    def coherent_campaign(self):
        created = _time(self.created_at)
        if not created < _time(self.due_at) <= created + timedelta(days=365):
            raise ValueError("Campaign deadline is invalid")
        encoded = self.source_content.encode()
        if len(encoded) > MAX_SOURCE_BYTES or hashlib.sha256(encoded).hexdigest() != self.source_sha256:
            raise ValueError("Campaign source integrity is invalid")
        document, items = self.source()
        provenance = document["data"]["provenance"]
        if (
            _json(document) != self.source_content or redact(document) != document
            or document["data"]["audience"] != self.audience
            or not isinstance(document.get("evidence"), list)
            or not isinstance(document.get("warnings", []), list)
            or not isinstance(provenance.get("observed_at"), str)
        ):
            raise ValueError("Campaign source provenance is invalid")
        _time(provenance["generated_at"])
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_PRINCIPALS:
            raise ValueError("Campaign requires 1 to 100 observed principals")
        for item in items:
            _ObservedPrincipal.model_validate(item)
        ids = [item["principal_id"] for item in items]
        if any(type(value) is not str or not value.strip() or len(value) > 2048 for value in ids):
            raise ValueError("Campaign principal identities are invalid")
        reviewed = [decision.principal_id for decision in self.decisions]
        if len(ids) != len(set(ids)) or len(reviewed) != len(set(reviewed)) or not set(reviewed) <= set(ids):
            raise ValueError("Campaign decisions do not match unique source identities")
        for decision in self.decisions:
            if decision.actor != self.reviewer_subject or _time(decision.recorded_at) < created:
                raise ValueError("Campaign decision attribution is invalid")
        if (self.status == "open") != (self.closure is None):
            raise ValueError("Campaign closure state is invalid")
        if self.closure:
            closed = _time(self.closure.recorded_at)
            if closed < created or any(_time(row.recorded_at) > closed for row in self.decisions):
                raise ValueError("Campaign closure time is invalid")
        if self.status == "completed" and set(ids) != set(reviewed):
            raise ValueError("Unreviewed campaign cannot be completed")
        return self


class _Collection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_REVISION)
    campaigns: list[_Campaign] = Field(max_length=MAX_CAMPAIGNS)

    @model_validator(mode="after")
    def coherent_collection(self):
        ids = [row.campaign_id for row in self.campaigns]
        minimum_revision = sum(1 + len(row.decisions) + int(row.closure is not None) for row in self.campaigns)
        if len(ids) != len(set(ids)) or minimum_revision > self.revision:
            raise ValueError("Campaign collection revisions or identities are invalid")
        for row in self.campaigns:
            document, _ = row.source()
            if document["scope"] != self.scope or document["data"]["provenance"]["scope"] != self.scope:
                raise ValueError("Campaign source scope is invalid")
        if len(_json(self.model_dump()).encode()) > MAX_COLLECTION_BYTES:
            raise ValueError("Campaign collection exceeds 6 MiB")
        return self


class AccessCampaignStore:
    """Shared exact-scope frozen review work, protected by local/OneLake CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(scope: dict[str, list[str]]) -> str:
        key = json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
        return f"state/access-campaigns/{hashlib.sha256(key).hexdigest()}.json"

    def _read(self, scope: dict[str, list[str]]):
        name = self._name(scope)
        try:
            snapshot = self.documents.read_snapshot(name)
            if snapshot.exists and len(_json(snapshot.payload).encode()) > MAX_COLLECTION_BYTES:
                raise ValueError("Campaign document exceeds its limit")
            state = (_Collection.model_validate(snapshot.payload) if snapshot.exists
                     else _Collection(scope=scope, revision=0, campaigns=[]))
            if state.scope != scope:
                raise ValueError("Campaign collection scope is invalid")
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            raise RuntimeError("Stored access campaigns are invalid") from exc
        return name, snapshot, state

    def _review(self, scope: dict[str, list[str]], revision: int):
        result = self._read(scope)
        if type(revision) is not int or not 0 <= revision < MAX_REVISION:
            raise CampaignRequestError("A safe reviewed collection revision is required")
        if result[2].revision != revision:
            raise DocumentConflictError("Access campaigns changed; reload before another action")
        return result

    @staticmethod
    def _find(state: _Collection, campaign_id: str) -> _Campaign:
        row = next((row for row in state.campaigns if row.campaign_id == campaign_id), None)
        if row is None:
            raise CampaignNotFoundError("Access campaign not found")
        return row

    @staticmethod
    def _summary(row: _Campaign, now: datetime) -> dict[str, Any]:
        document, items = row.source()
        return {
            **row.model_dump(exclude={"source_content", "decisions"}),
            "item_count": len(items), "decided_count": len(row.decisions),
            "overdue": row.status == "open" and _time(row.due_at) < now,
            "generated_at": document["data"]["provenance"]["generated_at"],
            "observed_at": document["data"]["provenance"]["observed_at"],
            "warning_count": len(document.get("warnings", [])),
            "source_size_bytes": len(row.source_content.encode()),
        }

    @classmethod
    def _manifest(cls, state: _Collection) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "scope": state.scope, "revision": state.revision, "as_of": now.isoformat(),
            "campaigns": [cls._summary(row, now) for row in reversed(state.campaigns)],
        }

    def read(self, scope: dict[str, list[str]]) -> dict[str, Any]:
        """Read shared metadata without current identity providers."""
        return self._manifest(self._read(scope)[2])

    def detail(self, scope: dict[str, list[str]], campaign_id: str) -> dict[str, Any]:
        """Recover the frozen source and immutable recommendations under current scope."""
        state = self._read(scope)[2]
        row = self._find(state, campaign_id)
        return {
            "revision": state.revision, "scope": scope,
            "campaign": self._summary(row, datetime.now(UTC)),
            "source_content": row.source_content, "items": row.source()[1],
            "decisions": [value.model_dump() for value in row.decisions],
        }

    def _save(self, name, snapshot, state: _Collection) -> dict[str, Any]:
        payload = state.model_dump()
        if len(_json(payload).encode()) > MAX_COLLECTION_BYTES:
            raise CampaignRequestError("Campaign collection exceeds 6 MiB; remove a terminal copy")
        validated = _Collection.model_validate(payload)
        if snapshot.exists:
            self.documents.replace_if_match(name, validated.model_dump(), expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, validated.model_dump())
        return self._manifest(validated)

    @staticmethod
    def _creation_bounds(state: _Collection, change: CampaignCreate, now: datetime) -> None:
        if len(state.campaigns) >= MAX_CAMPAIGNS:
            raise CampaignRequestError("Campaign collection is full; remove a terminal copy")
        if not now < _time(change.due_at) <= now + timedelta(days=365):
            raise CampaignRequestError("Choose a future deadline within 365 days")

    def preflight_create(self, scope: dict[str, list[str]], change: CampaignCreate) -> None:
        """Reject stale/full/expired work before acquiring any current evidence."""
        state = self._review(scope, change.expected_revision)[2]
        self._creation_bounds(state, change, datetime.now(UTC))

    def create(self, scope: dict[str, list[str]], change: CampaignCreate, actor: str, document: dict[str, Any]) -> dict[str, Any]:
        """Freeze a newly generated source; no truncation, auto assignment or eviction."""
        name, snapshot, state = self._review(scope, change.expected_revision)
        now = datetime.now(UTC)
        self._creation_bounds(state, change, now)
        content = _json(redact(document))
        if len(content.encode()) > MAX_SOURCE_BYTES:
            raise CampaignRequestError("Review source exceeds 512 KiB; narrow the selected scope")
        field = {"service_owner": "items", "security": "privileged_principals", "auditor": "principals"}[change.audience]
        items = json.loads(content)["data"][field]
        if not 1 <= len(items) <= MAX_PRINCIPALS:
            raise CampaignRequestError("Campaign requires 1 to 100 observed principals; narrow scope or select another audience")
        row = _Campaign(
            campaign_id=uuid4().hex, title=change.title, audience=change.audience,
            reviewer_subject=change.reviewer_subject, created_by=actor, created_at=now.isoformat(),
            due_at=change.due_at, source_content=content,
            source_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )
        state.campaigns.append(row); state.revision += 1
        return self._save(name, snapshot, state)

    def decide(self, scope: dict[str, list[str]], change: CampaignDecision, actor: str) -> dict[str, Any]:
        """Record one non-replaceable recommendation only as the assigned subject."""
        name, snapshot, state = self._review(scope, change.expected_revision)
        row = self._find(state, change.campaign_id)
        if actor != row.reviewer_subject:
            raise CampaignReviewerError("Only the assigned authenticated reviewer can record recommendations")
        if row.status != "open":
            raise CampaignRequestError("Only open campaigns accept recommendations")
        if change.principal_id not in {item["principal_id"] for item in row.source()[1]}:
            raise CampaignRequestError("Principal is not in the frozen campaign source")
        if any(value.principal_id == change.principal_id for value in row.decisions):
            raise CampaignRequestError("Recorded recommendations cannot be overwritten; create a new review if needed")
        row.decisions.append(_Decision(
            principal_id=change.principal_id, recommendation=change.recommendation,
            reason=change.reason, actor=actor, recorded_at=datetime.now(UTC).isoformat(),
        ))
        state.revision += 1
        return self._save(name, snapshot, state)

    def transition(self, scope: dict[str, list[str]], change: CampaignTransition, actor: str, action: Literal["complete", "cancel"]) -> dict[str, Any]:
        """Explicit closure never changes access or implies a successful recertification."""
        if action not in {"complete", "cancel"}:
            raise CampaignRequestError("Unsupported campaign transition")
        name, snapshot, state = self._review(scope, change.expected_revision)
        row = self._find(state, change.campaign_id)
        if row.status != "open":
            raise CampaignRequestError("The campaign is already closed")
        if action == "complete" and len(row.decisions) != len(row.source()[1]):
            raise CampaignRequestError("Review every captured principal before completing the campaign")
        row.status = "completed" if action == "complete" else "cancelled"
        row.closure = _Closure(actor=actor, reason=change.reason, recorded_at=datetime.now(UTC).isoformat())
        state.revision += 1
        return self._save(name, snapshot, state)

    def remove(self, scope: dict[str, list[str]], change: CampaignRemove) -> dict[str, Any]:
        """Remove a terminal stored copy, not downloaded copies or Azure grants."""
        name, snapshot, state = self._review(scope, change.expected_revision)
        row = self._find(state, change.campaign_id)
        if row.status == "open":
            raise CampaignRequestError("Complete or cancel the campaign before removing its stored copy")
        state.campaigns = [value for value in state.campaigns if value.campaign_id != row.campaign_id]
        state.revision += 1
        return self._save(name, snapshot, state)
