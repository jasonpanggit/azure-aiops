"""Explicit local-qualified composition; no runtime factory or activation hook."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from azure.core.credentials import TokenCredential

from fabric.maintenance_output import GenerationOutputPolicy
from ontology_discovery.immutable_attempt_worker import (
    ImmutableAttemptWorker,
    OneLakeAttemptLifecycleJournal,
)
from ontology_discovery.maintenance_materialization import (
    ATTEMPT_PROTOCOL,
    CandidateGenerationMaterializer,
)
from ontology_discovery.publication_broker_client import PublicationBrokerClient
from ontology_discovery.publisher import PublicationSafetyError
from storage.onelake_documents import OneLakeDocumentStore


@contextmanager
def compose_local_immutable_attempt_worker(
    *,
    endpoint: str,
    audience: str,
    worker_object_id: str,
    credential_owner_object_id: str,
    credential: TokenCredential,
    expected_target: Mapping[str, str],
    dispatch_id: str,
    journal_root: Path,
    storage: Any,
    documents: OneLakeDocumentStore,
    service: Any,
    authorizer: Any,
    target_id: str,
    clock: Callable[[], datetime],
    output_policies: tuple[GenerationOutputPolicy, ...],
    definition_fingerprint: Callable[[], str] | None = None,
    lease_seconds: int = 300,
    cancelled: Callable[[], bool] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[ImmutableAttemptWorker]:
    """Compose one explicit local-qualified lifecycle from application dependencies.

    All arguments are trusted application inputs, never request-selected
    configuration. No work occurs until the yielded worker is called.
    The application retains ownership of the credential, storage, service and
    document dependencies. Once the client is constructed, this context owns
    it and its HTTP transport, closing both on normal exit or failure.
    Construction failures before client creation leave the transport borrowed.
    ``credential_owner_object_id`` is the application's reviewed credential
    binding, not token evidence; the broker still authenticates the signed
    worker identity independently.
    This does not qualify a remote materializer or enable a production factory.
    """
    local_root = getattr(getattr(service, "onelake", None), "local_root", None)
    if local_root is None:
        raise PublicationSafetyError("remote_mutation_lock_unqualified")
    if credential_owner_object_id != worker_object_id:
        raise PublicationSafetyError("immutable_composition:credential_owner_mismatch")
    if not isinstance(journal_root, Path) or documents.is_remote:
        raise PublicationSafetyError("immutable_composition:local_roots_required")
    product_root = Path(local_root).resolve()
    document_root = Path(documents.root).resolve()
    lifecycle_root = journal_root.resolve()
    for existing_root in (product_root, document_root):
        if lifecycle_root.is_relative_to(existing_root) or existing_root.is_relative_to(
            lifecycle_root
        ):
            raise PublicationSafetyError("immutable_composition:journal_root_overlap")
    target = dict(expected_target)
    if any(
        dict(policy.context.expected_target) != target for policy in output_policies
    ):
        raise PublicationSafetyError("immutable_composition:output_target_mismatch")
    client = PublicationBrokerClient(
        endpoint=endpoint,
        audience=audience,
        expected_target=target,
        worker_object_id=worker_object_id,
        credential=credential,
        transport=transport,
    )
    try:
        materializer = CandidateGenerationMaterializer(
            storage=storage,
            documents=documents,
            service=service,
            authorizer=authorizer,
            target_id=target_id,
            clock=clock,
            expected_target=target,
            definition_fingerprint=definition_fingerprint,
            output_policies=output_policies,
            publication_protocol=ATTEMPT_PROTOCOL,
            attempt_protocol=client,
        )
        yield ImmutableAttemptWorker(
            dispatch_id=dispatch_id,
            expected_target=target,
            client=client,
            materializer=materializer,
            journal=OneLakeAttemptLifecycleJournal(
                OneLakeDocumentStore(lifecycle_root)
            ),
            lease_seconds=lease_seconds,
            cancelled=cancelled,
        )
    finally:
        client.close()
