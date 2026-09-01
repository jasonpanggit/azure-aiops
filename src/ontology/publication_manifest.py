"""Publication manifest: lifecycle-disposition registry for generated
ontology projections (MED-09).

**This is a distinct concept from the existing per-connection ingestion
snapshot manifest** (`manifest.json`, written by
`src/fabric/dataset_mapper.py`/`src/fabric/sync_service.py` and read by
`src/api/runtime.py::_load_snapshot_tables()`), which tracks *one
connector's raw sync attempt* (`runId`/`startedAt`). This module never
touches that code path, never extends its schema, and is always referred
to as the *publication manifest* -- never bare "manifest" -- in code and
docstrings, to prevent the exact ambiguity documented in
`10-RESEARCH.md`'s Pitfall #4.

Why this exists (a real platform risk, not a defensive abstraction): the
Fabric item type this repo publishes ontology projections to
(`"type": "Ontology"` in `.platform`, see `ontology_publisher.py`) belongs
to "Fabric IQ," which Microsoft explicitly documents as preview with
**no SLA**. The publication manifest lets a physical projection be marked
``dormant`` (intentionally inactive, still physically present -- never
deleted) or ``retired`` (with versioned compatibility evidence), so a
consumer never mistakes an operator-initiated pause for data loss, and
never silently depends on a projection nobody is maintaining anymore.

Every generated ontology projection has exactly one of four dispositions:

- ``active`` -- currently published and expected to be queried.
- ``dormant`` -- physically present, intentionally inactive. Never
  deleted; the physical Fabric binding is untouched by a disposition
  change.
- ``retired`` -- superseded/decommissioned, carrying a
  ``compatibility_version`` and ``retired_reason`` as evidence of *why*
  and *from what version*.
- ``unknown`` -- returned only by :meth:`PublicationManifestStore.get` for
  a projection name that was never registered. This is a synthetic query
  result, never a disposition a caller can register or set explicitly --
  an unregistered projection must never be silently reported as
  ``active``.

Persistence: this module is a plain in-memory registry (the same
lightweight, caller-persisted idiom already used by
:class:`~ontology.pending_relationships.PendingRelationshipStore` and
:class:`~onboarding.registry.ConnectionRegistry`): callers durably persist
:meth:`PublicationManifestStore.to_list` themselves, e.g. to the
``metadata_publication_manifest`` Delta table declared in
``fabric.schema_registry`` (see that module for the schema), and rehydrate
via :meth:`PublicationManifestStore.from_list`. Writing to Delta itself is
out of scope for this module -- it defines the queryable contract every
later Fabric medallion health surface (and
``scripts/validate-lakehouse-tables.py``'s disposition classification)
consumes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

#: A disposition a caller may explicitly register or set. "unknown" is
#: deliberately excluded -- it is a synthetic query result only, never a
#: state a caller can put a projection into.
Disposition = Literal["active", "dormant", "retired"]

#: The full set of dispositions a query can return, including the
#: synthetic "unknown" result for an unregistered projection name.
QueryDisposition = Literal["active", "dormant", "retired", "unknown"]

_REGISTERABLE_DISPOSITIONS: frozenset[str] = frozenset({"active", "dormant", "retired"})


def _default_clock() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PublicationManifestEntry:
    """One projection's lifecycle-disposition record.

    Named ``PublicationManifestEntry`` (never bare "manifest entry") so it
    is never mistaken for the unrelated per-connection snapshot manifest.
    """

    projection_name: str
    disposition: QueryDisposition
    compatibility_version: str | None
    retired_reason: str | None
    registered_at: str
    updated_at: str


#: Returned by :meth:`PublicationManifestStore.get` for a projection name
#: that was never registered. A module-level singleton keeps every "not
#: found" result identical and cheap, and its `projection_name` is
#: deliberately left blank so a caller can never mistake it for a real,
#: registered entry by inspecting the name alone.
def _unknown_entry(projection_name: str) -> PublicationManifestEntry:
    return PublicationManifestEntry(
        projection_name=projection_name,
        disposition="unknown",
        compatibility_version=None,
        retired_reason=None,
        registered_at="",
        updated_at="",
    )


def _require_retired_evidence(
    compatibility_version: str | None, retired_reason: str | None
) -> None:
    if not compatibility_version or not retired_reason:
        raise ValueError(
            "PublicationManifestStore: disposition 'retired' requires both "
            "compatibility_version and retired_reason -- a projection can "
            "never be retired without versioned compatibility evidence."
        )


class PublicationManifestStore:
    """Queryable lifecycle-disposition registry for ontology projections.

    Distinctly named "publication manifest" store -- never bare
    "manifest" -- to prevent conflation with the existing per-connection
    snapshot manifest (see module docstring).
    """

    def __init__(self, *, clock: Callable[[], datetime] = _default_clock) -> None:
        self._clock = clock
        self._entries: dict[str, PublicationManifestEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def register(
        self,
        projection_name: str,
        *,
        disposition: Disposition = "active",
        compatibility_version: str | None = None,
        retired_reason: str | None = None,
    ) -> PublicationManifestEntry:
        """Registers a new ontology projection with an initial disposition.

        Registering with ``disposition="retired"`` requires
        ``compatibility_version`` and ``retired_reason`` just like
        :meth:`set_disposition` does -- there is no path that lets a
        projection become retired without that evidence, whether at
        initial registration or later.
        """
        if disposition not in _REGISTERABLE_DISPOSITIONS:
            raise ValueError(
                f"PublicationManifestStore.register: disposition must be one of "
                f"{sorted(_REGISTERABLE_DISPOSITIONS)}, got {disposition!r}"
            )
        if disposition == "retired":
            _require_retired_evidence(compatibility_version, retired_reason)
        now = self._clock().isoformat()
        entry = PublicationManifestEntry(
            projection_name=projection_name,
            disposition=disposition,
            compatibility_version=compatibility_version,
            retired_reason=retired_reason,
            registered_at=now,
            updated_at=now,
        )
        self._entries[projection_name] = entry
        return entry

    def set_disposition(
        self,
        projection_name: str,
        disposition: Disposition,
        *,
        compatibility_version: str | None = None,
        retired_reason: str | None = None,
    ) -> PublicationManifestEntry:
        """Changes a registered projection's disposition metadata only.

        This never triggers deletion of the underlying physical Fabric
        binding -- marking a projection ``dormant`` or ``retired`` changes
        only this registry's metadata for it. Raises :class:`KeyError` if
        ``projection_name`` was never registered (a disposition can only
        be changed for a projection that already has an initial
        registration) and :class:`ValueError` if ``disposition="retired"``
        is requested without both ``compatibility_version`` and
        ``retired_reason``.
        """
        if disposition not in _REGISTERABLE_DISPOSITIONS:
            raise ValueError(
                f"PublicationManifestStore.set_disposition: disposition must be "
                f"one of {sorted(_REGISTERABLE_DISPOSITIONS)}, got {disposition!r}"
            )
        existing = self._entries.get(projection_name)
        if existing is None:
            raise KeyError(
                f"PublicationManifestStore.set_disposition: {projection_name!r} "
                "was never registered -- call register() first."
            )
        if disposition == "retired":
            _require_retired_evidence(compatibility_version, retired_reason)
        updated = PublicationManifestEntry(
            projection_name=projection_name,
            disposition=disposition,
            compatibility_version=(
                compatibility_version
                if disposition == "retired"
                else existing.compatibility_version
            ),
            retired_reason=(
                retired_reason if disposition == "retired" else existing.retired_reason
            ),
            registered_at=existing.registered_at,
            updated_at=self._clock().isoformat(),
        )
        self._entries[projection_name] = updated
        return updated

    def get(self, projection_name: str) -> PublicationManifestEntry:
        """Returns the projection's current entry, or a synthetic
        ``unknown``-disposition entry if it was never registered.

        Never silently defaults an unregistered name to ``active`` --
        ``unknown`` is a distinct, explicit disposition a caller must
        handle on its own terms.
        """
        return self._entries.get(projection_name) or _unknown_entry(projection_name)

    def to_list(self) -> list[dict[str, str | None]]:
        """Flattens every entry for a caller to persist (e.g. write to the
        ``metadata_publication_manifest`` Delta table)."""
        return [
            {
                "projection_name": entry.projection_name,
                "disposition": entry.disposition,
                "compatibility_version": entry.compatibility_version,
                "retired_reason": entry.retired_reason,
                "registered_at": entry.registered_at,
                "updated_at": entry.updated_at,
            }
            for entry in self._entries.values()
        ]

    @classmethod
    def from_list(
        cls,
        rows: list[dict[str, str | None]],
        *,
        clock: Callable[[], datetime] = _default_clock,
    ) -> "PublicationManifestStore":
        """Rehydrates a store previously flattened with :meth:`to_list`."""
        store = cls(clock=clock)
        for row in rows:
            projection_name = str(row.get("projection_name") or "")
            if not projection_name:
                continue
            disposition = row.get("disposition") or "active"
            store._entries[projection_name] = PublicationManifestEntry(
                projection_name=projection_name,
                disposition=disposition,  # type: ignore[arg-type]
                compatibility_version=row.get("compatibility_version"),
                retired_reason=row.get("retired_reason"),
                registered_at=str(row.get("registered_at") or ""),
                updated_at=str(row.get("updated_at") or ""),
            )
        return store
