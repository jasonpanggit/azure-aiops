"""Publisher-only, expiring one-shot validation drill controls."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from storage.onelake_documents import OneLakeDocumentStore

_DOCUMENT = "ontology/publisher-drill.json"
_POST_FAMILIES = frozenset({"api", "fabric", "agent", "export", "semantic"})
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class DrillPaused(RuntimeError):
    """Intentional pre-CAS validation pause."""


@dataclass(frozen=True)
class DrillControlConfig:
    enabled: bool = False
    environment: str = ""
    connection_environment: str = ""
    workspace_environment: str = ""
    publisher_client_id: str = ""
    azure_client_id: str = ""
    drill_root: str = ""
    protected_roots: tuple[str, ...] = ()

    @classmethod
    def disabled(cls) -> DrillControlConfig:
        return cls()


class PublisherDrillControl:
    """A single publisher-scoped drill with audited terminal cleanup."""

    def __init__(self, config: DrillControlConfig) -> None:
        self.config = config
        self._documents: OneLakeDocumentStore | None = None
        if not config.enabled:
            return
        if (
            config.environment.casefold() != "validation"
            or config.connection_environment.casefold() != "validation"
            or config.workspace_environment.casefold() != "validation"
        ):
            raise ValueError(
                "drill control requires the non-production validation environment"
            )
        if (
            not config.publisher_client_id
            or config.azure_client_id != config.publisher_client_id
        ):
            raise PermissionError("drill control requires the publisher identity")
        root = str(config.drill_root or "").strip()
        if not root or root in {str(value).strip() for value in config.protected_roots}:
            raise ValueError("drill root must be isolated from all protected roots")
        self._documents = OneLakeDocumentStore(root)

    def arm(
        self,
        *,
        drill_id: str,
        target_command_hash: str,
        fault: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> dict[str, object]:
        documents = self._require_enabled()
        moment = _aware(issued_at)
        expiry = _aware(expires_at)
        if expiry <= moment:
            raise ValueError("drill expiry must be after issue time")
        if len(str(drill_id)) < 32:
            raise ValueError("drill_id must be unpredictable")
        if not _HEX_64.fullmatch(str(target_command_hash)):
            raise ValueError("target_command_hash must be a SHA-256 digest")
        if fault != "pre_cas_pause" and not (
            fault.startswith("post_check:")
            and fault.removeprefix("post_check:") in _POST_FAMILIES
        ):
            raise ValueError("fault is not allowlisted")
        existing = documents.read_snapshot(_DOCUMENT)
        if existing.exists and existing.payload.get("status") not in {
            "cleaned",
            "expired",
        }:
            raise RuntimeError("an actionable drill already exists")
        actor_hash = hashlib.sha256(
            self.config.publisher_client_id.encode()
        ).hexdigest()
        row: dict[str, object] = {
            "drill_id": str(drill_id),
            "target_command_hash": str(target_command_hash),
            "fault": fault,
            "issued_at": moment.isoformat(),
            "expires_at": expiry.isoformat(),
            "status": "armed",
            "actor_hash": actor_hash,
            "config_hash": _config_hash(self.config),
            "audit": [
                {
                    "status": "armed",
                    "at": moment.isoformat(),
                    "actor_hash": actor_hash,
                    "config_hash": _config_hash(self.config),
                }
            ],
        }
        if existing.etag is None:
            documents.create_only(_DOCUMENT, row)
        else:
            documents.replace_if_match(
                _DOCUMENT, row, expected_etag=existing.etag
            )
        return row

    def inspect(self, *, now: datetime) -> dict[str, object]:
        if not self.config.enabled:
            return {"status": "disabled"}
        self.sweep(now=now)
        return dict(self._require_enabled().read_snapshot(_DOCUMENT).payload)

    def before_cas(self, *, command_hash: str, now: datetime) -> None:
        row, etag = self._active(command_hash, now)
        if row is None or row["fault"] != "pre_cas_pause":
            return
        if row["status"] == "armed":
            self._transition(row, etag, "ready", now)
            raise DrillPaused("publisher drill paused before pointer CAS")
        if row["status"] == "resumed":
            consumed, consumed_etag = self._transition(
                row, etag, "consumed", now
            )
            self._transition(consumed, consumed_etag, "cleaned", now)

    def resume(
        self, *, drill_id: str, actor_client_id: str, now: datetime
    ) -> None:
        if actor_client_id != self.config.publisher_client_id:
            raise PermissionError("only the publisher identity may resume a drill")
        documents = self._require_enabled()
        snapshot = documents.read_snapshot(_DOCUMENT)
        row = snapshot.payload
        if (
            not snapshot.exists
            or row.get("drill_id") != drill_id
            or row.get("status") != "ready"
        ):
            raise RuntimeError("drill is not ready to resume")
        self._transition(row, snapshot.etag, "resumed", now)

    def fail_post_check(
        self, *, command_hash: str, family: str, now: datetime
    ) -> bool:
        row, etag = self._active(command_hash, now)
        if (
            row is None
            or row["status"] != "armed"
            or row["fault"] != f"post_check:{family}"
        ):
            return False
        consumed, consumed_etag = self._transition(
            row, etag, "consumed", now
        )
        self._transition(consumed, consumed_etag, "cleaned", now)
        return True

    def sweep(self, *, now: datetime) -> int:
        if not self.config.enabled:
            return 0
        documents = self._require_enabled()
        snapshot = documents.read_snapshot(_DOCUMENT)
        if not snapshot.exists:
            return 0
        row = snapshot.payload
        if row.get("status") in {"cleaned", "expired"}:
            return 0
        if datetime.fromisoformat(str(row["expires_at"])) > _aware(now):
            return 0
        expired, expired_etag = self._transition(
            row, snapshot.etag, "expired", now
        )
        self._transition(expired, expired_etag, "cleaned", now)
        return 1

    def audit(self) -> list[dict[str, object]]:
        if not self.config.enabled:
            return []
        row = self._require_enabled().read_snapshot(_DOCUMENT).payload
        return [dict(item) for item in row.get("audit", [])]

    def clean(self, *, actor_client_id: str, now: datetime) -> bool:
        if actor_client_id != self.config.publisher_client_id:
            raise PermissionError("only the publisher identity may clean a drill")
        snapshot = self._require_enabled().read_snapshot(_DOCUMENT)
        if not snapshot.exists or snapshot.payload.get("status") == "cleaned":
            return False
        self._transition(snapshot.payload, snapshot.etag, "cleaned", now)
        return True

    def _active(
        self, command_hash: str, now: datetime
    ) -> tuple[dict[str, object] | None, str | None]:
        self.sweep(now=now)
        snapshot = self._require_enabled().read_snapshot(_DOCUMENT)
        row = snapshot.payload
        if (
            not snapshot.exists
            or row.get("target_command_hash") != command_hash
            or row.get("status") in {"cleaned", "expired"}
        ):
            return None, None
        return dict(row), snapshot.etag

    def _transition(
        self,
        row: dict[str, object],
        etag: str | None,
        status: str,
        now: datetime,
    ) -> tuple[dict[str, object], str]:
        if etag is None:
            raise RuntimeError("drill state is not durable")
        updated = dict(row)
        audit = [dict(item) for item in row.get("audit", [])]
        audit.append(
            {
                "status": status,
                "at": _aware(now).isoformat(),
                "actor_hash": row["actor_hash"],
                "config_hash": row["config_hash"],
            }
        )
        updated["status"] = status
        updated["audit"] = audit
        written = self._require_enabled().replace_if_match(
            _DOCUMENT, updated, expected_etag=etag
        )
        return updated, str(written.etag)

    def _require_enabled(self) -> OneLakeDocumentStore:
        if not self.config.enabled or self._documents is None:
            raise PermissionError("publisher drill control is disabled")
        return self._documents


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("drill timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _config_hash(config: DrillControlConfig) -> str:
    value = (
        f"{config.environment}|{config.connection_environment}|"
        f"{config.workspace_environment}|{config.publisher_client_id}|"
        f"{config.drill_root}"
    )
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "DrillControlConfig",
    "DrillPaused",
    "PublisherDrillControl",
]
