"""Durable registry of subscription connections.

Persistence is secret-free by construction: only ``secret_ref`` pointers are
written to storage. Storage is pluggable (see :mod:`onboarding.store`):
a single JSON file for local dev, or a OneLake document when ``AIOPS_HOME``
points at Fabric -- same code path either way.
"""

from __future__ import annotations

from typing import Any

from ontology.subscription_connection import SubscriptionConnection

from .credentials import redact_reference
from .metadata import BusinessMetadata
from .store import RegistryStore, RegistryStoreConflictError, default_store

REGISTRY_VERSION = 1


class ConnectionNotFoundError(LookupError):
    """Raised when a connection id is not present in the registry."""


class DuplicateConnectionError(ValueError):
    """Raised when creating a connection id that already exists."""


class RegistryConflictError(RuntimeError):
    """Raised when a concurrent writer modified the registry mid-update."""


class ConnectionRegistry:
    """File-backed store for :class:`SubscriptionConnection` records.

    Writes use optimistic concurrency: every mutation reads the current revision
    and refuses to persist if another writer advanced it in the meantime. This
    prevents concurrent API writers from silently clobbering each other.
    """

    def __init__(self, root: str, *, store: RegistryStore | None = None) -> None:
        self.root = str(root)
        self.store = store or default_store(self.root)

    def load(self) -> dict[str, SubscriptionConnection]:
        return self._load_with_revision()[0]

    def revision(self) -> int:
        return self._load_with_revision()[1]

    def _load_with_revision(self) -> tuple[dict[str, SubscriptionConnection], int]:
        payload = self._read()
        connections: dict[str, SubscriptionConnection] = {}
        for row in payload.get("connections") or []:
            connection = SubscriptionConnection.from_mapping(row)
            if connection is not None:
                connections[connection.connection_id] = connection
        return connections, int(payload.get("revision") or 0)

    def list(self, *, include_disabled: bool = True) -> list[SubscriptionConnection]:
        connections = sorted(self.load().values(), key=lambda item: item.connection_id)
        if include_disabled:
            return connections
        return [item for item in connections if item.is_active]

    def get(self, connection_id: str) -> SubscriptionConnection:
        return self.get_with_revision(connection_id)[0]

    def get_with_revision(
        self, connection_id: str
    ) -> tuple[SubscriptionConnection, int]:
        key = str(connection_id or "").strip()
        connections, revision = self._load_with_revision()
        if key in connections:
            return connections[key], revision
        folded = key.casefold()
        for candidate in connections.values():
            if candidate.connection_id.casefold() == folded:
                return candidate, revision
        raise ConnectionNotFoundError(f"Subscription connection '{connection_id}' is not registered")

    def exists(self, connection_id: str) -> bool:
        try:
            self.get(connection_id)
        except ConnectionNotFoundError:
            return False
        return True

    def add(self, connection: SubscriptionConnection) -> SubscriptionConnection:
        connections, revision = self._load_with_revision()
        if connection.connection_id in connections:
            raise DuplicateConnectionError(
                f"Subscription connection '{connection.connection_id}' already exists"
            )
        for existing in connections.values():
            if (
                existing.subscription_id.casefold() == connection.subscription_id.casefold()
                and existing.tenant_id.casefold() == connection.tenant_id.casefold()
                and existing.is_active
            ):
                raise DuplicateConnectionError(
                    f"Subscription {connection.subscription_id} is already onboarded as "
                    f"'{existing.connection_id}'"
                )
        connections[connection.connection_id] = connection
        self._write(connections, expected_revision=revision)
        return connection

    def save(
        self,
        connection: SubscriptionConnection,
        *,
        expected_revision: int | None = None,
    ) -> SubscriptionConnection:
        connections, revision = self._load_with_revision()
        if expected_revision is not None and expected_revision != revision:
            raise RegistryConflictError(
                f"Registry revision {revision} does not match expected {expected_revision}; "
                "reload the connection and retry"
            )
        if connection.connection_id not in connections:
            raise ConnectionNotFoundError(
                f"Subscription connection '{connection.connection_id}' is not registered"
            )
        connections[connection.connection_id] = connection
        self._write(connections, expected_revision=revision)
        return connection

    def delete(self, connection_id: str) -> SubscriptionConnection:
        connections, revision = self._load_with_revision()
        key = str(connection_id or "").strip()
        connection = connections.get(key)
        if connection is None:
            folded = key.casefold()
            connection = next(
                (
                    candidate
                    for candidate in connections.values()
                    if candidate.connection_id.casefold() == folded
                ),
                None,
            )
        if connection is None:
            raise ConnectionNotFoundError(f"Subscription connection '{connection_id}' is not registered")
        del connections[connection.connection_id]
        self._write(connections, expected_revision=revision)
        return connection

    def metadata_for(self, connection: SubscriptionConnection) -> BusinessMetadata:
        return BusinessMetadata.from_mapping(connection.metadata.get("business") or {})

    def _read(self) -> dict[str, Any]:
        return self.store.read()

    def _write(
        self,
        connections: dict[str, SubscriptionConnection],
        *,
        expected_revision: int,
    ) -> None:
        payload = {
            "version": REGISTRY_VERSION,
            "revision": expected_revision + 1,
            "connections": [
                _persistable(connection)
                for _, connection in sorted(connections.items(), key=lambda item: item[0])
            ],
        }
        try:
            self.store.write(payload, expected_revision=expected_revision)
        except RegistryStoreConflictError as exc:
            raise RegistryConflictError(str(exc)) from exc


def _persistable(connection: SubscriptionConnection) -> dict[str, Any]:
    """Serialize a connection while guaranteeing no secret material is written."""
    row = connection.to_dict()
    credential = row.get("credential")
    if isinstance(credential, dict):
        credential.pop("client_secret", None)
        credential.pop("secret", None)
        credential["secret_ref"] = redact_reference(credential.get("secret_ref"))
    return row


__all__ = [
    "REGISTRY_VERSION",
    "ConnectionNotFoundError",
    "ConnectionRegistry",
    "DuplicateConnectionError",
    "RegistryConflictError",
]
