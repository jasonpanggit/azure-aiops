"""Explicit staged-reader and journal stores; no runtime activation or identity proof."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from storage.datasets import StagedGenerationReader
from storage.onelake_documents import ExplicitRemoteDocumentStore, OneLakeDocumentStore


@dataclass(frozen=True)
class AttemptDocumentBindings:
    """Borrowed read capability and separate coordinator journal document store."""

    staged: StagedGenerationReader
    journal_documents: ExplicitRemoteDocumentStore
    staged_owner_object_id: str
    journal_owner_object_id: str


@contextmanager
def bind_remote_attempt_documents(
    *,
    staged_root: str,
    staged_credential: Any,
    staged_owner_object_id: str,
    journal_root: str,
    journal_credential: Any,
    journal_owner_object_id: str,
) -> Iterator[AttemptDocumentBindings]:
    """Bind disjoint roots to distinct declared owners without credential fallback.

    Owns both SDK stores for this context, borrows application credentials.
    Owner IDs are trusted declarations, not token/RBAC evidence or broker worker
    identity. Distinct Python credential instances do not prove distinct owners.
    No client is opened and no token requested until an operation is invoked.
    """
    oid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    if (
        type(staged_owner_object_id) is not str
        or type(journal_owner_object_id) is not str
        or re.fullmatch(oid, staged_owner_object_id) is None
        or re.fullmatch(oid, journal_owner_object_id) is None
        or staged_owner_object_id == journal_owner_object_id
    ):
        raise ValueError(
            "distinct declared staged and journal owner object IDs required"
        )
    with (
        OneLakeDocumentStore.remote(
            staged_root, credential=staged_credential
        ) as staged,
        OneLakeDocumentStore.remote(
            journal_root, credential=journal_credential
        ) as journal,
    ):
        left, right = (
            staged.root.casefold().split("/"),
            journal.root.casefold().split("/"),
        )
        if left[: len(right)] == right or right[: len(left)] == left:
            raise ValueError("staged and journal roots must be disjoint")
        yield AttemptDocumentBindings(
            StagedGenerationReader(staged),
            journal,
            staged_owner_object_id,
            journal_owner_object_id,
        )
