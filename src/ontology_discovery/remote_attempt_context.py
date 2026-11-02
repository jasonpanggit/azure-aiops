"""Explicit remote attempt context; no runtime discovery or activation hook."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import httpx
from azure.core.credentials import TokenCredential

from ontology_discovery.attempt_projection import (
    ImmutableLogicalProjectionPolicy,
    ReadOnlyAttemptProjector,
)
from ontology_discovery.immutable_attempt_worker import (
    ImmutableAttemptWorker,
    OneLakeAttemptLifecycleJournal,
)
from ontology_discovery.publication_broker_client import PublicationBrokerClient
from ontology_discovery.publisher import PublicationSafetyError
from storage.attempt_documents import bind_remote_attempt_documents


@contextmanager
def remote_immutable_attempt_context(
    *,
    endpoint: str,
    audience: str,
    worker_object_id: str,
    credential_owner_object_id: str,
    credential: TokenCredential,
    staged_root: str,
    staged_credential: TokenCredential,
    staged_owner_object_id: str,
    journal_root: str,
    journal_credential: TokenCredential,
    journal_owner_object_id: str,
    expected_target: Mapping[str, str],
    dispatch_id: str,
    authorizer: Any,
    definition_fingerprint: Callable[[], str],
    policies: tuple[ImmutableLogicalProjectionPolicy, ...],
    lease_seconds: int = 300,
    cancelled: Callable[[], bool] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[ImmutableAttemptWorker]:
    """Bind application-owned inputs without performing publication or discovery.

    All dependencies are trusted caller inputs, never candidate-selected.
    Credential owner IDs are reviewed declarations, not token/RBAC evidence.
    Stage/journal ownership is separate from the broker worker identity.
    This context borrows credentials and the current authorizer. It owns the
    lazy document stores and, after client construction, HTTP client/transport.
    Construction before that point leaves the injected transport borrowed.
    No token, document or broker request occurs until the worker is invoked.
    Exiting closes owned resources on success, construction or body failure;
    the worker and its dependencies must not be used beyond that lifetime.
    No runtime caller, activation flag or commissioning claim is introduced.
    """
    if credential_owner_object_id != worker_object_id:
        raise PublicationSafetyError("remote_attempt_context:credential_owner_mismatch")
    target = dict(expected_target)
    with bind_remote_attempt_documents(
        staged_root=staged_root,
        staged_credential=staged_credential,
        staged_owner_object_id=staged_owner_object_id,
        journal_root=journal_root,
        journal_credential=journal_credential,
        journal_owner_object_id=journal_owner_object_id,
    ) as documents:
        client = PublicationBrokerClient(
            endpoint=endpoint,
            audience=audience,
            expected_target=target,
            worker_object_id=worker_object_id,
            credential=credential,
            transport=transport,
        )
        try:
            projector = ReadOnlyAttemptProjector(
                storage=documents.staged,
                authorizer=authorizer,
                expected_target=target,
                definition_fingerprint=definition_fingerprint,
                attempt_protocol=client,
                policies=policies,
            )
            yield ImmutableAttemptWorker(
                dispatch_id=dispatch_id,
                expected_target=target,
                client=client,
                materializer=projector,
                journal=OneLakeAttemptLifecycleJournal(documents.journal_documents),
                lease_seconds=lease_seconds,
                cancelled=cancelled,
            )
        finally:
            client.close()
