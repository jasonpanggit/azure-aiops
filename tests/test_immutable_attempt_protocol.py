"""Trusted broker reference adapter; no fake represents deployed Azure services."""

import hashlib
import json
import threading
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from fabric.maintenance_output import describe_outputs, output_digest
from fabric.sync_service import _generation_catalog, ontology_generation_products
from ontology_discovery.immutable_attempt import (
    AttemptBoundary,
    AttemptControl,
    AttemptReference,
    AttemptSession,
    AzureSqlBlobAttemptBoundary,
    ImmutableAttemptProtocol,
    ImmutableObjectReference,
    OneLakeAttemptBoundary,
    _digest,
    _json,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
    PinnedProductReader,
    _hash,
)
from ontology_discovery.publisher import (
    OntologyGenerationPublisher,
    PublicationSafetyError,
)
from ontology_discovery.publisher_worker import PublisherWorker
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore
from tests.test_ontology_output_manifest import example


class BrokerFixture(AttemptBoundary):
    """Enforcing test authority owning private CAS documents and immutable bytes.

    Lock simulates ONE SQL control transaction, not a distributed/OneLake lease.
    No backing-store object or mutation credentials are exposed by the protocol.
    Authority writes, clock, takeover and commit serialize under the same lock.
    Real providers must implement their own trusted SQL+WORM boundary.
    """

    def __init__(self, path):
        self.__documents = OneLakeDocumentStore(path)
        self.__lock = threading.RLock()
        self.__objects = {}
        self.__grants = {}
        self.now = 0
        self.crash = None
        self.retention_state = "locked"
        self.retention_until = 100
        self.required_retention_until = 50
        self.append_exceptions = False
        self.authenticated_principal = "A"  # Transport identity, not a request field.
        if not self.__documents.read_snapshot("control.json").exists:
            self.__documents.create_only("control.json", {
                "owner": "initial", "epoch": 0, "session_id": "initial", "active": None,
                "receipt": None, "audit": [], "revision": 0, "operations": {},
            })

    def _control(self):
        snap = self.__documents.read_snapshot("control.json")
        value = snap.payload
        return AttemptControl(
            AttemptSession(value["owner"], value["epoch"], value["session_id"]),
            AttemptReference.parse(value["active"]) if value["active"] else None,
            str(value["revision"]),
        )

    def read_control(self):
        with self.__lock:
            return self._control()

    def takeover(self, owner):
        with self.__lock:
            self.authenticated_principal = owner
            snap = self.__documents.read_snapshot("control.json")
            value = snap.payload
            epoch = value["epoch"] + 1
            value.update(
                owner=owner, epoch=epoch, session_id=f"{owner}-{epoch}",
                revision=value["revision"] + 1,
            )
            self.__documents.replace_if_match("control.json", value, expected_etag=snap.etag)
            return self._control()

    def grant(self, session, reference, *, operation="admit", digest="auth", expires=10):
        with self.__lock:
            self.__grants[(session.session_id, reference.catalog_digest, operation)] = (
                digest, expires,
            )

    def revoke(self, session, reference, operation="admit"):
        with self.__lock:
            self.__grants.pop((session.session_id, reference.catalog_digest, operation))

    def _owned(self, session):
        if self._control().session != session or self.authenticated_principal != session.owner:
            raise PublicationSafetyError("broker:stale_session")

    def _retention(self):
        if (
            self.retention_state != "locked" or self.append_exceptions
            or self.retention_until <= self.now
            or self.retention_until < self.required_retention_until
        ):
            raise PublicationSafetyError("broker:retention_unqualified")

    def begin(self, session, attempt_id, candidate_json):
        with self.__lock:
            self._owned(session)
            name = f"attempts/{attempt_id}.json"
            existing = self.__documents.read_snapshot(name)
            binding = {"session": session.__dict__, "candidate": candidate_json}
            if existing.exists and existing.payload != binding:
                raise PublicationSafetyError("broker:namespace_conflict")
            if not existing.exists:
                self.__documents.create_only(name, binding)

    def _binding(self, attempt_id):
        body = self.__documents.read_snapshot(f"attempts/{attempt_id}.json").payload
        return AttemptSession(**body["session"]), body["candidate"]

    def create_product(self, session, attempt_id, table, product_json):
        with self.__lock:
            self._retention()
            if (
                self._binding(attempt_id)[0] != session
                or self.authenticated_principal != session.owner
            ):
                raise PublicationSafetyError("broker:namespace_owner")
            # A stale session may finish only its own unreachable immutable
            # namespace. It cannot change namespace binding or overwrite bytes.
            key = (attempt_id, table)
            if key in self.__objects and self.__objects[key] != product_json:
                raise PublicationSafetyError("broker:immutable_conflict")
            if (attempt_id, "catalog") in self.__objects and key not in self.__objects:
                raise PublicationSafetyError("broker:sealed")
            self.__objects[key] = product_json
            if self.crash == "product":
                self.crash = None
                raise TimeoutError("simulated lost create response")
            return self._object_reference(attempt_id, table, product_json)

    @staticmethod
    def _object_reference(attempt_id, table, product_json):
        digest = hashlib.sha256(product_json.encode()).hexdigest()
        return ImmutableObjectReference(
            account_resource_id="synthetic-storage-account",
            endpoint="https://synthetic.invalid", container="synthetic-locked-container",
            object_name=f"attempts/{attempt_id}/{table}.json",
            length=len(product_json.encode()), content_digest=digest, etag=f'"{digest}"',
        )

    def seal(self, session, reference, catalog_json):
        with self.__lock:
            self._retention()
            binding = self._binding(reference.attempt_id)
            catalog = json.loads(catalog_json)
            if (
                binding[0] != session or self.authenticated_principal != session.owner
                or json.loads(binding[1]) != catalog["candidate"]
                or _digest(catalog) != reference.catalog_digest
                or catalog["candidate"]["generation_id"] != reference.generation_id
            ):
                raise PublicationSafetyError("broker:seal_binding")
            products = catalog["products"]
            existing = {
                name for attempt, name in self.__objects
                if attempt == reference.attempt_id and name != "catalog"
            }
            if existing != set(products):
                raise PublicationSafetyError("broker:incomplete_catalog")
            for name, entry in products.items():
                raw = self.__objects[(reference.attempt_id, name)]
                if hashlib.sha256(raw.encode()).hexdigest() != entry["content_digest"]:
                    raise PublicationSafetyError("broker:content")
                if entry["artifact"] != self._object_reference(
                    reference.attempt_id, name, raw,
                ).as_dict():
                    raise PublicationSafetyError("broker:object_identity")
            key = (reference.attempt_id, "catalog")
            if key in self.__objects and self.__objects[key] != catalog_json:
                raise PublicationSafetyError("broker:immutable_catalog")
            if self.crash == "partial-catalog":
                self.crash = None
                raise TimeoutError("unsealed upload not visible")
            self.__objects[key] = catalog_json

    def read_catalog(self, reference):
        with self.__lock:
            self._retention()
            try:
                return self.__objects[(reference.attempt_id, "catalog")]
            except KeyError:
                raise PublicationSafetyError("broker:unsealed") from None

    def read_product(self, reference, table):
        with self.__lock:
            catalog = json.loads(self.read_catalog(reference))
            if table not in catalog["products"]:
                raise PublicationSafetyError("broker:product_not_in_seal")
            return self.__objects[(reference.attempt_id, table)]

    def recover_commit(
        self, session, reference, *, expected_revision, operation,
        request_id, authorization_digest,
    ):
        with self.__lock:
            if self.authenticated_principal != session.owner:
                raise PublicationSafetyError("broker:stale_session")
            snap = self.__documents.read_snapshot("control.json")
            args = _json({
                "session": session.__dict__, "reference": reference.as_dict(),
                "expected_revision": expected_revision, "operation": operation,
                "authorization_digest": authorization_digest,
            })
            prior = snap.payload["operations"].get(request_id)
            if prior is not None:
                if prior["args"] != args:
                    raise PublicationSafetyError("broker:request_reuse")
                return AttemptControl(
                    AttemptSession(**prior["session"]),
                    AttemptReference.parse(prior["active"]), prior["revision"],
                )  # Historical result only, no mutation or reauthorization.
            return None

    def commit(
        self, session, reference, *, expected_revision, operation,
        request_id, authorization_digest,
    ):
        with self.__lock:
            recovered = self.recover_commit(
                session, reference, expected_revision=expected_revision, operation=operation,
                request_id=request_id, authorization_digest=authorization_digest,
            )
            if recovered is not None:
                return recovered
            snap = self.__documents.read_snapshot("control.json")
            args = _json({
                "session": session.__dict__, "reference": reference.as_dict(),
                "expected_revision": expected_revision, "operation": operation,
                "authorization_digest": authorization_digest,
            })
            self._owned(session)
            self._retention()
            grant = self.__grants.get((session.session_id, reference.catalog_digest, operation))
            if grant is None or grant[0] != authorization_digest or grant[1] <= self.now:
                raise PublicationSafetyError("broker:authority_expired_or_revoked")
            catalog = json.loads(self.read_catalog(reference))
            if _digest(catalog) != reference.catalog_digest:
                raise PublicationSafetyError("broker:seal_digest")
            if str(snap.payload["revision"]) != expected_revision:
                raise DocumentConflictError("broker:control_revision")
            value = snap.payload
            value.update(
                active=reference.as_dict(), receipt=reference.as_dict(),
                revision=value["revision"] + 1,
            )
            value["audit"].append({"request": request_id, "operation": operation})
            value["operations"][request_id] = {
                "args": args, "session": session.__dict__, "active": reference.as_dict(),
                "revision": str(value["revision"]),
            }
            # ONE document CAS models atomic pointer/receipt/audit transaction.
            self.__documents.replace_if_match("control.json", value, expected_etag=snap.etag)
            result = self._control()
            if self.crash == "commit":
                self.crash = None
                raise TimeoutError("simulated lost commit response")
            return result

    def restart(self):
        """New broker process; fake immutable storage service outlives it."""
        with self.__lock:
            replacement = BrokerFixture(self.__documents.root)
            replacement.__objects = self.__objects
            replacement.now = self.now
            replacement.authenticated_principal = self.authenticated_principal
            # Grants are deliberately not copied; replay needs no new grant.
            return replacement


def fixture(tmp_path):
    broker = BrokerFixture(tmp_path / "private-control")
    core = ImmutableAttemptProtocol(broker)
    control = broker.takeover("A")
    candidate = {
        "generation_id": "generation", "source_generation": "source",
        "content_hash": "content", "staged_manifest_digest": "staged",
        "validation_digest": "validation", "authorization_digest": "auth",
        "attestation_digest": "attestation", "expected_target": {
            key: f"synthetic-{key}" for key in (
                "tenant_id", "subscription_id", "connection_id",
                "workspace_id", "item_id", "definition_fingerprint",
            )
        },
    }
    return broker, core, control, candidate


def stage(core, control, candidate, attempt="attempt-A", rows=None):
    return core.stage(
        control.session, attempt_id=attempt, candidate=candidate,
        products={"ontology_entities": rows or [], "ontology_relationships": []},
    )


def commit(core, control, reference, request="request", operation="admit", auth="auth"):
    return core.commit(
        control.session, reference, expected_revision=control.revision,
        operation=operation, request_id=request, authorization_digest=auth,
    )


def test_stale_writer_paused_before_commit_cannot_overwrite_B(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    ref_a = stage(core, a, candidate)
    broker.grant(a.session, ref_a)
    b = broker.takeover("B")
    ref_b = stage(core, b, candidate, "attempt-B", [{"resource_id": "B"}])
    broker.grant(b.session, ref_b)
    accepted = commit(core, b, ref_b, "B-commit")
    with pytest.raises(PublicationSafetyError, match="stale_session"):
        commit(core, a, ref_a)
    assert core.active()[0] == ref_b
    assert accepted.active == ref_b
    assert core.read_table(ref_a, "ontology_entities") == []
    assert core.read_table(ref_b, "ontology_entities") == [{"resource_id": "B"}]


def test_stale_writer_resumes_only_own_unreachable_attempt(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    broker.crash = "product"
    with pytest.raises(TimeoutError):
        stage(core, a, candidate)
    b = broker.takeover("B")
    ref_b = stage(core, b, candidate, "attempt-B")
    broker.grant(b.session, ref_b)
    commit(core, b, ref_b)
    with pytest.raises(PublicationSafetyError, match="stale_session"):
        stage(core, a, candidate)
    with pytest.raises(PublicationSafetyError, match="namespace_owner"):
        broker.create_product(a.session, "attempt-B", "ontology_entities", "{}")
    # Already-admitted product request can finish A's namespace, not B's.
    broker.authenticated_principal = "A"  # Resume A's authenticated request.
    broker.create_product(a.session, "attempt-A", "ontology_relationships", '{"rows":[]}')
    assert core.active()[0] == ref_b


@pytest.mark.parametrize("gap", ["expiry", "revocation", "restore-only"])
def test_commit_boundary_not_prior_callback_enforces_authority(tmp_path, gap):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    # Simulated pause AFTER all client-side checks, BEFORE trusted commit.
    if gap == "expiry":
        broker.now = 10
    elif gap == "revocation":
        broker.revoke(a.session, reference)
    else:
        broker.revoke(a.session, reference)
        broker.grant(a.session, reference, operation="restore")
    with pytest.raises(PublicationSafetyError, match="authority"):
        commit(core, a, reference)
    assert core.active() == (None, None)


def test_ABA_requires_new_epoch_and_original_revision(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    broker.takeover("B")
    a2 = broker.takeover("A")
    assert a2.session.epoch != a.session.epoch
    with pytest.raises(PublicationSafetyError, match="stale_session"):
        commit(core, a, reference)
    broker.grant(a2.session, reference)
    with pytest.raises(DocumentConflictError):
        core.commit(
            a2.session, reference, expected_revision=a.revision, operation="admit",
            request_id="ABA", authorization_digest="auth",
        )


def test_reader_pins_exact_attempt_not_latest_receipt_for_same_generation(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    commit(core, a, reference)
    stage(core, broker.read_control(), candidate, "later-unpublished", [{"resource_id": "not active"}])
    forbidden = SimpleNamespace(latest=lambda *_: pytest.fail("latest receipt used"))
    reader = PinnedProductReader(
        read_pointer=lambda: pytest.fail("legacy pointer used"),
        receipts=forbidden, delta=None, onelake=None, attempt_protocol=core,
    )
    generation, receipt = reader.active()
    assert generation == candidate["generation_id"]
    assert reader.read_table("ontology_entities", receipt) == []
    assert reader.read_ontology() == ([], [])
    assert reader.verify(receipt)


def test_independent_restoration_selects_retained_bytes_without_rewrite(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    retained = stage(core, a, candidate)
    broker.grant(a.session, retained)
    commit(core, a, retained)
    a = broker.read_control()
    current = stage(core, a, candidate, "new", [{"resource_id": "new"}])
    broker.grant(a.session, current)
    commit(core, a, current, "new")
    latest = broker.read_control()
    with pytest.raises(PublicationSafetyError, match="authority"):
        commit(core, latest, retained, "restore", operation="restore")
    broker.grant(a.session, retained, operation="restore", digest="restore-auth")
    commit(core, latest, retained, "restore", operation="restore", auth="restore-auth")
    assert core.active()[0] == retained
    assert core.read_table(current, "ontology_entities") == [{"resource_id": "new"}]
    with pytest.raises(PublicationSafetyError, match="immutable"):
        broker.create_product(a.session, retained.attempt_id, "ontology_entities", '{"rows":[1]}')


@pytest.mark.parametrize("crash", ["product", "partial-catalog", "commit"])
def test_crash_retry_exact_bytes_and_idempotent_commit(tmp_path, crash):
    broker, core, a, candidate = fixture(tmp_path)
    if crash != "commit":
        broker.crash = crash
        with pytest.raises(TimeoutError):
            stage(core, a, candidate)
        assert core.active() == (None, None)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    if crash == "commit":
        broker.crash = "commit"
        with pytest.raises(TimeoutError):
            commit(core, a, reference)
    result = commit(core, a, reference)
    assert commit(core, a, reference) == result
    with pytest.raises(PublicationSafetyError, match="request_reuse"):
        commit(core, a, reference, operation="restore")
    assert core.active()[0] == reference


def test_partial_catalog_is_not_reader_visible(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    broker.begin(a.session, "partial", _json(candidate))
    with pytest.raises(PublicationSafetyError, match="unsealed"):
        core.read_catalog(AttemptReference("partial", "generation", "0" * 64))


def test_provider_boundary_refuses_raw_OneLake_CAS_and_broad_credentials(tmp_path):
    with pytest.raises(PublicationSafetyError, match="provider_fenced"):
        OneLakeAttemptBoundary(OneLakeDocumentStore(tmp_path))
    with pytest.raises(PublicationSafetyError, match="enforcing_boundary"):
        ImmutableAttemptProtocol(OneLakeDocumentStore(tmp_path))
    with pytest.raises(PublicationSafetyError, match="not_implemented_or_qualified"):
        AzureSqlBlobAttemptBoundary(qualified=True, immutable=True)


@pytest.mark.parametrize("condition", ["unlocked", "unverified", "expired", "horizon", "append"])
def test_server_inspected_retention_is_required_at_seal_and_commit(tmp_path, condition):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    if condition in {"unlocked", "unverified"}:
        broker.retention_state = condition
    elif condition == "expired":
        broker.retention_until = 0
    elif condition == "horizon":
        broker.retention_until = 49
    else:
        broker.append_exceptions = True
    with pytest.raises(PublicationSafetyError, match="retention"):
        commit(core, a, reference)
    with pytest.raises(PublicationSafetyError, match="retention"):
        stage(core, a, candidate, "unqualified-seal")
    assert core.active() == (None, None)


def materializer_fixture(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    manifest = env.staged["manifest"]
    manifest["complete"] = True
    manifest["content_hash"] = _hash({
        key: value for key, value in manifest.items() if key not in {"content_hash", "complete"}
    })
    release = SimpleNamespace(
        **env.target, attestation_digest="synthetic-attestation", release_id="synthetic-release",
        authorization_binding=lambda: {"release": "synthetic"},
    )
    auth_digest = _hash({
        "release": release.authorization_binding(), "target": env.target,
        "generation_id": manifest["generation_id"], "content_hash": manifest["content_hash"],
    })
    env.context = replace(
        env.context, content_hash=manifest["content_hash"],
        staged_manifest_digest=output_digest(manifest), authorization_digest=auth_digest,
    )
    env.args.update(content_hash=manifest["content_hash"], authorization_digest=auth_digest)
    products = ontology_generation_products(**env.args)
    catalog = _generation_catalog(
        products, {name: {"version": None} for name in products},
        manifest["generation_id"], manifest["content_hash"],
    )
    policy = replace(env.policy, context=env.context, manifest=describe_outputs(products, env.lake, catalog))
    broker = BrokerFixture(tmp_path / "broker")
    control = broker.takeover("A")
    calls = []

    def authorize_restore(**kwargs):
        calls.append(kwargs)
        return release

    authorizer = SimpleNamespace(
        reader=SimpleNamespace(read=lambda operation: release),
        model_rows=lambda rows: [],
        authorize_restore=authorize_restore,
    )
    materializer = CandidateGenerationMaterializer(
        storage=SimpleNamespace(
            read_generation=lambda generation: deepcopy(env.staged),
            read_pointer=lambda: pytest.fail("legacy pointer used"),
        ),
        documents=OneLakeDocumentStore(tmp_path / "not-the-control"),
        service=env.service, authorizer=authorizer, target_id="synthetic",
        clock=lambda: None, expected_target=env.target,
        output_policies=(policy,), publication_protocol="immutable-attempt/v1",
        attempt_boundary=broker,
    )
    candidate = SimpleNamespace(
        generation_id=env.context.generation_id, source_generation=env.context.source_generation,
        entities=(), relationships=(),
    )
    materializer.bind_attempt(control.session, attempt_id="materializer-attempt")
    return env, materializer, broker, control, candidate, calls


def test_existing_materializer_stages_commits_reads_and_restores_exact_attempt(tmp_path, monkeypatch):
    env, materializer, broker, control, candidate, restore_calls = materializer_fixture(
        tmp_path, monkeypatch,
    )
    result = materializer(candidate)
    reference = AttemptReference.parse(result["attempt_reference"])
    assert env.sink.calls == env.catalogs == []  # No fixed-table/catalog sinks.
    broker.grant(control.session, reference, digest=env.context.authorization_digest)
    committed = materializer.commit_attempt(expected_revision=control.revision, request_id="publish")
    generation, receipt = materializer.reader.active()
    assert generation == candidate.generation_id
    assert materializer.reader.read_ontology() == ([], [])
    assert materializer.reader.verify(receipt)
    broker.grant(
        control.session, reference, operation="restore", digest="synthetic-attestation",
    )
    restored = materializer.restore_attempt(
        reference, expected_revision=committed.revision, request_id="restore",
    )
    assert restored.active == reference
    assert restore_calls[0]["expected_target"]["generation_id"] == reference.generation_id
    assert env.sink.calls == env.catalogs == []


def test_materializer_retry_rebuilds_exact_attempt_and_legacy_paths_refuse(tmp_path, monkeypatch):
    env, materializer, broker, _control, candidate, _ = materializer_fixture(tmp_path, monkeypatch)
    broker.crash = "partial-catalog"
    with pytest.raises(TimeoutError):
        materializer(candidate)
    result = materializer(candidate)
    assert result["status"] == "completed"
    with pytest.raises(PublicationSafetyError, match="use_bind_attempt"):
        materializer.bind(owner_id="A", fence=1, predecessor=None, pointer_etag=None)
    with pytest.raises(PublicationSafetyError, match="use_restore_attempt"):
        materializer.recover_physical(reason="legacy")
    with pytest.raises(PublicationSafetyError, match="use_commit_attempt"):
        materializer.verify_before_cas(candidate)
    # Legacy publisher refuses before staging or a second legacy pointer CAS.
    publisher = object.__new__(OntologyGenerationPublisher)
    with pytest.raises(PublicationSafetyError, match="legacy_pointer"):
        publisher.publish(
            candidate, publisher_identity="", checkpoint_ids=[], pointer_conditions=None,
            owner_id="A", fence=1, consumer_compatibility={},
            cancellation_check=lambda: False, lease_guard=lambda: None,
            materialize_generation=materializer,
        )
    with pytest.raises(PublicationSafetyError, match="legacy_worker_protocol"):
        PublisherWorker(
            dispatches=None, publisher=publisher, publisher_identity="",
            owner_id="", fence_allocator=None, materialize=materializer,
            consumer_check=None, now=lambda: None,
        )
    assert env.sink.calls == env.catalogs == []


def test_lost_commit_response_replay_survives_restart_and_does_not_restore_stale_pointer(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    broker.crash = "commit"
    with pytest.raises(TimeoutError):
        commit(core, a, reference)
    broker = broker.restart()
    core = ImmutableAttemptProtocol(broker)
    b = broker.takeover("B")
    winner = stage(core, b, candidate, "B-after-restart")
    broker.grant(b.session, winner)
    commit(core, b, winner, "B-publish")
    broker.authenticated_principal = "A"
    historical = commit(core, a, reference)
    assert historical.active == reference
    assert core.active()[0] == winner  # Historical retry never rewrites pointer.


def test_concurrent_catalogs_and_stale_restoration_have_single_revision_winner(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    retained = stage(core, a, candidate, "retained")
    other = stage(core, a, candidate, "other")
    broker.grant(a.session, retained, operation="restore", digest="restore")
    broker.grant(a.session, other)
    commit(core, a, other)
    with pytest.raises(DocumentConflictError):
        commit(core, a, retained, "stale-restore", operation="restore", auth="restore")
    assert core.active()[0] == other
    assert core.read_table(retained, "ontology_entities") == []


def test_forged_epoch_with_fresh_revision_cannot_bypass_boundary(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    b = broker.takeover("B")
    with pytest.raises(PublicationSafetyError, match="stale_session"):
        core.commit(
            a.session, reference, expected_revision=b.revision, request_id="fresh-CAS",
            operation="admit", authorization_digest="auth",
        )
    assert core.active() == (None, None)


def test_reader_refuses_when_enforced_retention_no_longer_covers_active_reference(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    commit(core, a, reference)
    broker.now = 101
    with pytest.raises(PublicationSafetyError, match="retention"):
        core.active()


def test_pinned_reader_does_not_cache_caller_mutated_rows(tmp_path):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate, rows=[{"resource_id": "original"}])
    broker.grant(a.session, reference)
    commit(core, a, reference)
    reader = PinnedProductReader(
        read_pointer=lambda: pytest.fail("legacy pointer"), receipts=None,
        delta=None, onelake=None, attempt_protocol=core,
    )
    entities, _ = reader.read_ontology()
    entities[0]["resource_id"] = "mutated"
    assert reader.read_ontology()[0][0]["resource_id"] == "original"


@pytest.mark.parametrize("change", ["missing-target", "extra-target", "empty-authority"])
def test_core_rejects_incomplete_candidate_binding_before_namespace_creation(tmp_path, change):
    _broker, core, a, candidate = fixture(tmp_path)
    if change == "missing-target":
        del candidate["expected_target"]["definition_fingerprint"]
    elif change == "extra-target":
        candidate["expected_target"]["unreviewed"] = "value"
    else:
        candidate["authorization_digest"] = ""
    with pytest.raises(PublicationSafetyError, match="binding"):
        stage(core, a, candidate)
    assert core.active() == (None, None)


def test_authenticated_worker_cannot_supply_another_owners_current_session(tmp_path):
    broker, core, _a, candidate = fixture(tmp_path)
    b = broker.takeover("B")
    reference = stage(core, b, candidate, "B-only")
    broker.grant(b.session, reference)
    broker.authenticated_principal = "A"  # Verified transport actor, not payload owner.
    with pytest.raises(PublicationSafetyError, match="stale_session"):
        commit(core, b, reference)  # Even exact current owner+epoch+revision reject.
    with pytest.raises(PublicationSafetyError, match="namespace_owner"):
        broker.create_product(b.session, "B-only", "ontology_entities", "{}")
    assert core.active() == (None, None)


def test_unqualified_infrastructure_scaffold_cannot_enable_provider():
    with pytest.raises(PublicationSafetyError, match="not_implemented_or_qualified"):
        AzureSqlBlobAttemptBoundary(publication_backend_v1={
            "execution_enabled": False, "qualified": False, "bootstrap_required": True,
            "policy_state": "Unlocked", "versioning": False,
        })


@pytest.mark.parametrize("damage", ["missing", "content", "versioned"])
def test_reader_rejects_missing_or_mismatched_artifact_without_fallback(tmp_path, damage):
    broker, core, a, candidate = fixture(tmp_path)
    reference = stage(core, a, candidate)
    broker.grant(a.session, reference)
    commit(core, a, reference)
    # Test-only provider damage, outside trusted boundary. No repair/fallback.
    objects = broker._BrokerFixture__objects
    key = (reference.attempt_id, "ontology_entities")
    if damage == "missing":
        del objects[key]
    elif damage == "content":
        objects[key] = '{"rows":[{"secret":"DO_NOT_ECHO"}]}'
    else:
        with pytest.raises(PublicationSafetyError, match="object_reference"):
            replace(
                broker._object_reference(reference.attempt_id, "ontology_entities", objects[key]),
                version_id="unexpected-version",
            )
        return
    with pytest.raises(PublicationSafetyError) as caught:
        core.active()
    assert "DO_NOT_ECHO" not in str(caught.value)
