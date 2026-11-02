"""Actual worker client through the materializer and existing closed transport."""

pytest_plugins = ("tests.test_publication_broker_transport",)

from dataclasses import replace
from types import MappingProxyType
from uuid import uuid4

import httpx
import pytest

from fabric.maintenance_output import describe_outputs
from fabric.sync_service import _generation_catalog, ontology_generation_products
from ontology_discovery.immutable_attempt import (
    AttemptPublicationProtocol,
    AttemptReference,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
    _hash,
)
from ontology_discovery.publication_broker_client import PublicationBrokerClient
from tests import test_immutable_attempt_protocol as existing
from tests.test_publication_broker_client import (
    AUDIENCE,
    ENDPOINT,
    OWNER,
    wire,  # noqa: F401
)
from tests.test_publication_broker_transport import TENANT


@pytest.fixture
def server_env(env):
    return env


def test_actual_broker_client_drives_materializer_lifecycle(
    tmp_path, monkeypatch, request,
):
    http_harness = request.getfixturevalue("wire")
    clients = []
    requests = []

    def construct(**kwargs):
        target = dict(kwargs["expected_target"])
        target["tenant_id"] = TENANT
        kwargs["expected_target"] = target
        http_harness.server.transport._target = MappingProxyType(target)

        release = kwargs["authorizer"].reader.read("admit")
        release.tenant_id = TENANT
        context = kwargs["output_policies"][0].context
        authorization_digest = _hash({
            "release": release.authorization_binding(),
            "target": target,
            "generation_id": context.generation_id,
            "content_hash": context.content_hash,
        })
        context = replace(
            context,
            expected_target=tuple(sorted(target.items())),
            authorization_digest=authorization_digest,
        )
        staged = kwargs["storage"].read_generation(context.generation_id)
        products = ontology_generation_products(
            staged["entities"],
            staged["relationships"],
            generation_id=context.generation_id,
            source_generation=context.source_generation,
            content_hash=context.content_hash,
            authorization_digest=context.authorization_digest,
            attestation_digest=context.attestation_digest,
            validation=staged["validation"],
        )
        catalog = _generation_catalog(
            products,
            {name: {"version": None} for name in products},
            context.generation_id,
            context.content_hash,
        )
        kwargs["output_policies"] = (
            replace(
                kwargs["output_policies"][0],
                context=context,
                manifest=describe_outputs(
                    products, kwargs["service"].onelake, catalog,
                ),
            ),
        )

        def send(request):
            requests.append(request)
            response = http_harness.server.transport.handle(
                method=request.method,
                path=request.url.raw_path.decode(),
                headers=list(request.headers.multi_items()),
                body=request.content,
            )
            assert response.status == 200, response.body
            return httpx.Response(
                response.status,
                content=response.body,
                headers={"content-type": response.content_type},
            )

        client = PublicationBrokerClient(
            endpoint=ENDPOINT,
            audience=AUDIENCE,
            expected_target=target,
            worker_object_id=OWNER,
            credential=http_harness.credential,
            transport=httpx.MockTransport(send),
        )
        assert isinstance(client, AttemptPublicationProtocol)
        kwargs.pop("attempt_boundary")
        kwargs["attempt_protocol"] = client
        clients.append(client)
        return CandidateGenerationMaterializer(**kwargs)

    monkeypatch.setattr(existing, "CandidateGenerationMaterializer", construct)
    try:
        env, materializer, _boundary, _prior_control, candidate, restore_calls = (
            existing.materializer_fixture(tmp_path / "materializer", monkeypatch)
        )
        client = clients[0]
        control = client.acquire(expected_revision="0")
        materializer.bind_attempt(
            control.session,
            attempt_id=client.allocate_attempt(control.session),
        )

        result = materializer(candidate)
        reference = AttemptReference.parse(result["attempt_reference"])
        auth_digest = materializer._output_policies[0].context.authorization_digest
        http_harness.server.boundary.grant(
            control.session, reference, digest=auth_digest,
        )
        admitted = materializer.commit_attempt(
            expected_revision=control.revision,
            request_id=str(uuid4()),
        )
        assert admitted.active == reference
        assert materializer.reader.active()[1]["attempt_reference"] == reference.as_dict()
        assert materializer.reader.read_ontology() == ([], [])
        assert materializer.reader.verify(materializer.reader.active()[1])

        restore_release = materializer._authorizer.reader.read("restore")
        restore_release.attestation_digest = "c" * 64
        restore_digest = restore_release.attestation_digest
        http_harness.server.boundary.grant(
            control.session, reference, operation="restore", digest=restore_digest,
        )
        restored = materializer.restore_attempt(
            reference,
            expected_revision=admitted.revision,
            request_id=str(uuid4()),
        )
        assert restored.active == reference
        assert restore_calls[0]["expected_target"]["generation_id"] == reference.generation_id
        assert env.sink.calls == env.catalogs == []

        operations = {request.url.path.rsplit("/", 1)[-1] for request in requests}
        assert {
            "acquire", "allocate", "stage", "commit",
            "read-control", "read-catalog", "read-table",
        } <= operations
        assert operations <= {
            "acquire", "allocate", "stage", "commit", "recover",
            "read-control", "read-catalog", "read-table",
        }
    finally:
        for client in clients:
            client.close()
