"""Real provider composition with offline SDK/DB transports; NOT SQL semantics."""

import hashlib
import json
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from azure.core.exceptions import HttpResponseError
from cryptography.hazmat.primitives.asymmetric import rsa

from api.auth import EntraJwtAuthenticator
from api.errors import ApiError
from api.rbac import Grant
from api.scope import Scope
from fabric.schema_registry import schema_for
from ontology_discovery.immutable_attempt import (
    PROTOCOL,
    AttemptReference,
    AzureSqlBlobAttemptBoundary,
    ImmutableAttemptProtocol,
    _json,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
)
from ontology_discovery.publisher import PublicationSafetyError
from ontology_discovery.sql_blob_broker import (
    SqlBlobPublicationBroker,
    SqlBrokerControl,
    SqlBrokerVerifier,
    bootstrap_broker_metadata,
)
from ontology_discovery.sql_publication_control import (
    SqlPublicationAuthority,
    SqlPublicationError,
)
from storage.immutable_blob_artifacts import (
    ArtifactVerificationError,
    ImmutableBlobArtifactStore,
)
from storage.onelake_documents import OneLakeDocumentStore
from tests.test_immutable_attempt_protocol import materializer_fixture
from tests.test_immutable_blob_artifacts import HORIZON, NOW, Fixture
from tests.test_sql_publication_control import TARGET as SQL_TARGET
from tests.test_sql_publication_control import Connection, Cursor

jwt = pytest.importorskip("jwt", reason="Existing API extra is required for JWT validation tests")
pyodbc = pytest.importorskip("pyodbc", reason="Existing .[fabric-sql] extra is required for SQL driver tests")
A, B = str(uuid4()), str(uuid4())
AUTH = hashlib.sha256(b"admission-authority").hexdigest()
RESTORE_AUTH = hashlib.sha256(b"restoration-authority").hexdigest()
TARGET = dict.fromkeys(
    ("tenant_id", "subscription_id", "connection_id", "workspace_id", "item_id", "definition_fingerprint"),
    "synthetic",
)


class RoutingDatabase:
    """Models procedure outcomes, not T-SQL, locks or actual effective permissions."""

    def __init__(self):
        self.target_id = str(uuid4())
        self.now = NOW
        self.control = {
            "target_id": self.target_id, "owner_id": None, "session_id": None, "epoch": 0,
            "revision": 0, "active_attempt": None, "active_digest": None,
        }
        self.attempts, self.operations, self.grants = {}, {}, {}
        self.events, self.calls = [], []
        self.fail_commit = self.fail_seal = False
        self.lock = threading.RLock()
        self.expected_target = deepcopy(TARGET)

    def connect(self, role):
        database = self

        class Cursor:
            description = None

            def execute(self, query, values=()):
                assert query.count("?") == len(values)
                name = re.search(r"EXEC publication\.\[?(\w+)\]?", query)[1]
                names, self.rows = database.dispatch(role, name, values)
                self.description = [(name,) for name in names] or None
                return self

            def fetchall(self):
                return self.rows

            def nextset(self):
                return False

            def close(self):
                pass

        return SimpleNamespace(cursor=Cursor, close=lambda: None)

    @staticmethod
    def result(value):
        return ["result_json"], [(_json(value),)]

    def owned(self, owner, session, epoch):
        assert (owner, session, epoch) == (
            self.control["owner_id"], self.control["session_id"], self.control["epoch"],
        )

    def dispatch(self, role, name, p):
        with self.lock:
            self.calls.append((role, name, p))
            assert role == {
                "SealOwnedAttempt": "verifier", "RecordGrant": "authority", "Revoke": "authority",
            }.get(name, "control")
            try:
                return self._dispatch(name, p)
            except (AssertionError, KeyError):
                raise pyodbc.Error("synthetic procedure denied") from None

    def _dispatch(self, name, p):
        assert p[0] == self.target_id
        if name == "ReadControl":
            return self.result(deepcopy(self.control))
        if name == "Acquire":
            _, owner, revision, _lease = p
            assert revision == self.control["revision"]
            self.control.update(
                owner_id=owner, session_id=str(uuid4()), epoch=self.control["epoch"] + 1,
                revision=revision + 1,
            )
            return self.result(deepcopy(self.control))
        if name == "BeginAttempt":
            _, owner, session, epoch, candidate, attempt = p
            self.owned(owner, session, epoch)
            assert json.loads(candidate)["expected_target"] == self.expected_target
            value = (owner, session, epoch, candidate)
            if attempt in self.attempts:
                assert self.attempts[attempt]["begin"] == value
            else:
                self.attempts[attempt] = {"begin": value}
            return ["attempt_id"], [(attempt,)]
        if name == "SealOwnedAttempt":
            _, owner, session, epoch, attempt, catalog, digest, inventory, evidence = p
            self.owned(owner, session, epoch)
            assert self.attempts[attempt]["begin"][:3] == (owner, session, epoch)
            value = (catalog, digest, inventory, evidence)
            assert digest == hashlib.sha256(catalog.encode()).digest()
            assert _json(json.loads(catalog)["candidate"]) == self.attempts[attempt]["begin"][3]
            row = self.attempts[attempt]
            if "seal" in row:
                assert row["seal"] == value
            row["seal"] = value
            if self.fail_seal:
                self.fail_seal = False
                raise pyodbc.Error("synthetic lost seal response")
            return [], []
        if name in {"ReadAttempt", "ReadReferenceMetadata", "ReadReadableReferenceMetadata"}:
            _, attempt, digest = p
            catalog, actual, inventory, evidence = self.attempts[attempt]["seal"]
            assert actual == digest
            if name == "ReadReadableReferenceMetadata":
                assert datetime.fromisoformat(json.loads(evidence)["effective_until"]) > self.now
            if name in {"ReadReferenceMetadata", "ReadReadableReferenceMetadata"}:
                return self.result({"generation_id": json.loads(catalog)["candidate"]["generation_id"]})
            assert datetime.fromisoformat(json.loads(evidence)["effective_until"]) > self.now
            return ["catalog_json", "inventory_json", "evidence_json"], [(catalog, inventory, evidence)]
        if name == "RecordGrant":
            _, session, epoch, digest, operation, authority, _evidence, _start, until = p
            self.grants[(session, epoch, digest, operation)] = (authority, until.replace(tzinfo=UTC))
            return [], []
        if name == "Revoke":
            _, session, epoch, digest, operation = p
            self.grants.pop((session, epoch, digest, operation), None)
            return [], []
        assert name in {"CommitAttempt", "RecoverOutcome"}
        _, owner, session, epoch, revision, attempt, digest, operation, authority, request = p
        if request in self.operations:
            args, outcome = self.operations[request]
            assert args == p
            return self.result({"found": True, "outcome": outcome} if name == "RecoverOutcome" else outcome)
        if name == "RecoverOutcome":
            return self.result({"found": False})
        self.owned(owner, session, epoch)
        assert revision == self.control["revision"]
        row = self.attempts[attempt]
        assert row["seal"][1] == digest
        assert datetime.fromisoformat(json.loads(row["seal"][3])["effective_until"]) > self.now
        if operation == "admit":
            assert row["begin"][:3] == (owner, session, epoch)
        approved, deadline = self.grants[(session, epoch, digest, operation)]
        assert approved == authority and deadline > self.now
        self.control.update(active_attempt=attempt, active_digest=digest.hex(), revision=revision + 1)
        outcome = deepcopy(self.control)
        self.operations[request] = (p, outcome)
        self.events.append((attempt, operation))
        if self.fail_commit:
            self.fail_commit = False
            raise pyodbc.Error("synthetic lost commit response after persisted transition")
        return self.result(outcome)


@pytest.fixture
def fx():
    blob = Fixture()
    database = RoutingDatabase()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = EntraJwtAuthenticator(
        tenant_id="test-tenant", audience="api://test-publication",
        grants_resolver=lambda _oid, roles: (
            (Grant("ontology_maintainer"),) if "ontology_maintainer" in roles else ()
        ),
        subject_claim="oid",
    )
    auth.jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=private_key.public_key()))

    def headers(owner=A, **changes):
        claims = {
            "oid": owner, "preferred_username": B,
            "roles": ["ontology_maintainer"], "iss": auth.issuer,
            "aud": auth.audience, "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        }
        claims.update(changes)
        return {"authorization": "Bearer " + jwt.encode(claims, private_key, algorithm="RS256")}

    control = SqlBrokerControl(SQL_TARGET, None, connect=lambda: database.connect("control"))
    verifier = SqlBrokerVerifier(SQL_TARGET, None, connect=lambda: database.connect("verifier"))
    authority = SqlPublicationAuthority(SQL_TARGET, None, connect=lambda: database.connect("authority"))

    def server(store=blob.store, expected_target=TARGET):
        return SqlBlobPublicationBroker(
            control=control, verifier=verifier, artifacts=store, authenticator=auth,
            target_id=database.target_id, expected_target=expected_target, retain_until=HORIZON,
            allowed_owners=frozenset({A, B}),
        )

    service = server()
    boundary = service.for_request(headers())
    assert boundary.read_control().session is None
    core = ImmutableAttemptProtocol(boundary)
    session = boundary.acquire(expected_revision="0")
    candidate = {
        "generation_id": "generation", "source_generation": "source", "content_hash": "content",
        "staged_manifest_digest": "staged", "validation_digest": "validation",
        "authorization_digest": AUTH, "attestation_digest": "attestation",
        "expected_target": TARGET,
    }

    def stage(current=boundary, state=session, *, generation="generation"):
        value = {**candidate, "generation_id": generation}
        attempt = current.allocate_attempt(state.session)
        reference = ImmutableAttemptProtocol(current).stage(
            state.session, attempt_id=attempt, candidate=value,
            products={"ontology_entities": [], "ontology_relationships": []},
        )
        return reference

    def grant(state, reference, *, operation="admit"):
        digest = AUTH if operation == "admit" else RESTORE_AUTH
        authority.record_grant(
            database.target_id, state.session.session_id, state.session.epoch,
            catalog_digest=reference.catalog_digest, operation=operation,
            authority_digest=digest, evidence_digest="b" * 64,
            valid_from=NOW - timedelta(minutes=1), valid_until=NOW + timedelta(days=1),
        )

    def commit(state, reference, *, current=core, operation="admit", request=None):
        request = request or str(uuid4())
        return current.commit(
            state.session, reference, expected_revision=state.revision, request_id=request,
            operation=operation, authorization_digest=AUTH if operation == "admit" else RESTORE_AUTH,
        )

    yield SimpleNamespace(
        blob=blob, db=database, auth=auth, headers=headers, server=server, boundary=boundary,
        core=core, state=session, stage=stage, grant=grant, commit=commit,
        authority=authority, service=service, candidate=candidate,
    )
    blob.client.close()


def test_complete_batch_then_separate_catalog_actual_provider_inventory(fx):
    reference = fx.stage()
    assert len(fx.blob.writes) == 3
    namespaces = [name.split("/")[1] for name, _ in fx.blob.writes]
    assert namespaces[:2] == [reference.attempt_id, reference.attempt_id]
    assert namespaces[2] != reference.attempt_id
    catalog, _digest, inventory, evidence = fx.db.attempts[reference.attempt_id]["seal"]
    recorded = json.loads(evidence)["provider_readback"]
    assert recorded["product_inventory"]["attempt_id"] == reference.attempt_id
    assert recorded["catalog_inventory"]["attempt_id"] == namespaces[2]
    catalog_object = recorded["catalog_inventory"]["objects"][0]
    assert fx.blob.data[catalog_object["blob_name"]] == catalog.encode()
    assert len(json.loads(inventory)) == 2
    fx.grant(fx.state, reference)
    result = fx.commit(fx.state, reference)
    assert fx.core.active() == (reference, json.loads(catalog))
    assert fx.core.read_table(reference, "ontology_entities") == []
    assert result.active == reference and fx.db.events == [(reference.attempt_id, "admit")]


def test_partial_manifest_cannot_be_uploaded_via_single_product_api(fx):
    with pytest.raises(PublicationSafetyError, match="complete_product_batch"):
        fx.boundary.create_product(fx.state.session, str(uuid4()), "ontology_entities", "{}")
    assert not fx.blob.writes


def test_invalid_actual_rows_rejected_before_sql_begin_or_blob_upload(fx):
    attempt = fx.boundary.allocate_attempt(fx.state.session)
    with pytest.raises(PublicationSafetyError, match="product_schema"):
        fx.core.stage(
            fx.state.session, attempt_id=attempt, candidate=fx.candidate,
            products={"ontology_entities": [], "ontology_relationships": [{"confidence": True}]},
        )
    assert attempt not in fx.db.attempts and not fx.blob.writes


def test_direct_composite_seal_rechecks_actual_rows_before_catalog_or_verifier(fx):
    attempt = fx.boundary.allocate_attempt(fx.state.session)
    fx.boundary.begin(fx.state.session, attempt, _json(fx.candidate))
    table = "ontology_relationships"
    body = _json({"rows": [{"confidence": True}]})
    artifact = fx.boundary.create_products(fx.state.session, attempt, {table: body})[table]
    catalog = {
        "protocol": PROTOCOL, "attempt_id": attempt, "candidate": fx.candidate,
        "products": {table: {
            "rows": 1, "content_digest": artifact.content_digest,
            "arrow_schema_digest": hashlib.sha256(schema_for(table).serialize()).hexdigest(),
            "artifact": artifact.as_dict(),
        }},
    }
    catalog_json = _json(catalog)
    reference = AttemptReference(attempt, fx.candidate["generation_id"], hashlib.sha256(catalog_json.encode()).hexdigest())
    with pytest.raises(PublicationSafetyError, match="product_schema"):
        fx.boundary.seal(fx.state.session, reference, catalog_json)
    assert len(fx.blob.data) == 1 and "seal" not in fx.db.attempts[attempt]


def test_unlocked_provider_rejects_before_any_blob_sink_or_sql_seal(fx):
    fx.blob.policy["properties"]["state"] = "Unlocked"
    with pytest.raises(ArtifactVerificationError, match="immutable_policy_unverified"):
        fx.stage()
    assert not fx.blob.writes and not fx.db.events
    assert not any(name == "SealOwnedAttempt" for _role, name, _params in fx.db.calls)


@pytest.mark.parametrize("claims", [
    {"aud": "wrong-audience"}, {"iss": "wrong-issuer"},
    {"exp": datetime(2000, 1, 1, tzinfo=UTC)}, {"oid": str(uuid4())}, {"roles": ["reader"]},
])
def test_real_jwt_validation_and_fixed_allowlist_cannot_be_payload_asserted(fx, claims):
    with pytest.raises((ApiError, PublicationSafetyError)):
        fx.service.for_request(fx.headers(**claims))
    assert not fx.blob.writes


def test_oid_not_preferred_username_and_scoped_maintenance_grant_required(fx):
    assert fx.boundary.read_control().session.owner == A  # preferred_username was B.
    fx.auth.grants_resolver = lambda *_: (
        Grant("ontology_maintainer", Scope.from_mapping({"subscription": ["not-our-target"]})),
    )
    with pytest.raises(PublicationSafetyError, match="caller_scope"):
        fx.service.for_request(fx.headers())


def test_default_entra_subject_choice_is_unchanged(fx):
    default = EntraJwtAuthenticator(
        tenant_id=fx.auth.tenant_id, audience=fx.auth.audience,
        grants_resolver=fx.auth.grants_resolver,
    )
    default.jwks = fx.auth.jwks
    assert default.authenticate(fx.headers()).subject == B
    assert fx.auth.authenticate(fx.headers()).subject == A


def test_invalid_signature_is_not_an_authenticated_owner(fx):
    headers = fx.headers()
    prefix, signature = headers["authorization"].rsplit(".", 1)
    headers["authorization"] = prefix + "." + ("B" if signature[0] == "A" else "A") + signature[1:]
    count = len(fx.db.calls)
    with pytest.raises(ApiError):
        fx.service.for_request(headers)
    assert len(fx.db.calls) == count


def test_cached_metadata_still_checks_db_horizon_before_any_product_body(fx, monkeypatch):
    reference = fx.stage()
    fx.db.now = NOW + timedelta(days=100)
    monkeypatch.setattr(fx.blob.store, "read_object", lambda *_: pytest.fail("Expired cached read hit Blob"))
    with pytest.raises(SqlPublicationError):
        fx.boundary.read_product(reference, "ontology_entities")
    assert fx.db.calls[-1][1] == "ReadReadableReferenceMetadata"


def test_broker_migration_has_closed_transactional_seal_and_read_only_metadata():
    connection = Connection(Cursor())
    bootstrap_broker_metadata(connection)
    sql = "\n".join(query for query, _ in connection._cursor.calls)
    assert connection.committed
    assert sql.count("CREATE OR ALTER PROCEDURE") == 3
    assert "RetainUntil > SYSUTCDATETIME()" in sql
    owned, metadata = sql.split("CREATE OR ALTER PROCEDURE publication.ReadReferenceMetadata")
    first, second = metadata.split("CREATE OR ALTER PROCEDURE publication.ReadReadableReferenceMetadata")
    assert "RetainUntil" not in first
    assert "RetainUntil" in second
    assert owned.index("IF @@TRANCOUNT <> 0") < owned.index("BEGIN TRANSACTION")
    assert "RAISERROR ('publication_seal_ambient_transaction', 16, 1)" in owned
    assert owned.count("WITH (UPDLOCK, HOLDLOCK)") == 2
    assert "SessionDeadline > SYSUTCDATETIME()" in owned
    assert "EXEC publication.SealAttempt" in owned
    assert not re.search(r"\b(UPDATE|DELETE|INSERT|CREATE USER|ADD MEMBER)\b", sql)
    connection = Connection(Cursor(fail=pyodbc.Error("test admin DDL error")))
    with pytest.raises(pyodbc.Error):
        bootstrap_broker_metadata(connection)
    assert connection.rolled_back and not connection.committed


@pytest.mark.parametrize("upload_number", [1, 3])
def test_takeover_during_product_or_catalog_upload_cannot_persist_stale_seal(fx, upload_number):
    winner = []

    def takeover(_name):
        if len(fx.blob.writes) == upload_number:
            fx.blob.on_upload = None
            other = fx.service.for_request(fx.headers(B))
            winner.append(other.acquire(expected_revision=fx.state.revision))

    fx.blob.on_upload = takeover
    with pytest.raises((PublicationSafetyError, SqlPublicationError)):
        fx.stage()
    assert winner and fx.boundary.read_control() == winner[0]
    assert fx.blob.data  # In-flight immutable creates may leave unreachable orphans.
    assert not any("seal" in row for row in fx.db.attempts.values())
    assert not fx.db.events


def test_takeover_after_broker_precheck_is_rejected_by_owned_seal_procedure(fx, monkeypatch):
    verifier = fx.service._verifier
    original = verifier.seal_owned_attempt
    winner = []

    def takeover_then_seal(*args, **kwargs):
        other = fx.service.for_request(fx.headers(B))
        winner.append(other.acquire(expected_revision=fx.state.revision))
        return original(*args, **kwargs)

    monkeypatch.setattr(verifier, "seal_owned_attempt", takeover_then_seal)
    with pytest.raises(SqlPublicationError):
        fx.stage()
    assert fx.boundary.read_control() == winner[0]
    assert not any("seal" in row for row in fx.db.attempts.values())
    assert fx.db.calls[-2][1] == "SealOwnedAttempt"


def test_paused_A_after_upload_cannot_activate_over_B_and_cannot_reuse_B_session(fx):
    reference_a = fx.stage()
    fx.grant(fx.state, reference_a)
    other = fx.service.for_request(fx.headers(B))
    state_b = other.acquire(expected_revision=fx.state.revision)
    reference_b = fx.stage(other, state_b, generation="B")
    fx.grant(state_b, reference_b)
    winner = fx.commit(state_b, reference_b, current=ImmutableAttemptProtocol(other))
    with pytest.raises((PublicationSafetyError, SqlPublicationError)):
        fx.commit(fx.state, reference_a)
    with pytest.raises(PublicationSafetyError, match="session_caller_mismatch"):
        fx.boundary.allocate_attempt(state_b.session)
    assert other.read_control() == winner
    assert fx.core.read_table(reference_a, "ontology_entities") == []


@pytest.mark.parametrize("invalid", ["expired", "revoked", "retention", "takeover"])
def test_historical_outcome_after_restart_needs_no_blob_read_or_fresh_grant(fx, invalid, monkeypatch):
    reference = fx.stage()
    fx.grant(fx.state, reference)
    request = str(uuid4())
    fx.db.fail_commit = True
    with pytest.raises(SqlPublicationError):
        fx.commit(fx.state, reference, request=request)
    historical = fx.boundary.read_control()
    if invalid == "takeover":
        other = fx.service.for_request(fx.headers(B))
        b = other.acquire(expected_revision=historical.revision)
        winner = fx.stage(other, b, generation="B")
        fx.grant(b, winner)
        fx.commit(b, winner, current=ImmutableAttemptProtocol(other))
    elif invalid == "expired":
        fx.db.now = NOW + timedelta(days=100)
    elif invalid == "revoked":
        fx.authority.revoke(
            fx.db.target_id, fx.state.session.session_id, fx.state.session.epoch,
            catalog_digest=reference.catalog_digest, operation="admit",
        )
    else:
        fx.blob.policy["properties"]["state"] = "Unlocked"
    before = deepcopy(fx.db.control)
    count = len(fx.db.events)
    restarted = fx.server().for_request(fx.headers())
    monkeypatch.setattr(fx.blob.store, "read_object", lambda *_: pytest.fail("Historical recovery read Blob"))
    core = ImmutableAttemptProtocol(restarted)
    assert fx.commit(fx.state, reference, current=core, request=request) == historical
    assert fx.db.control == before and len(fx.db.events) == count
    with pytest.raises((PublicationSafetyError, SqlPublicationError)):
        core.recover_commit(
            fx.state.session, AttemptReference(reference.attempt_id, "wrong-generation", reference.catalog_digest),
            expected_revision=fx.state.revision, operation="admit",
            request_id=request, authorization_digest=AUTH,
        )


def test_restart_pinned_read_reconstructs_but_unfinished_upload_handle_does_not(fx):
    reference = fx.stage()
    fresh_store = ImmutableBlobArtifactStore(
        fx.blob.store.target, fx.blob.credential,
        service_client=fx.blob.service, management_reader=fx.blob.reader,
    )
    restarted = fx.server(fresh_store).for_request(fx.headers())
    assert ImmutableAttemptProtocol(restarted).read_table(reference, "ontology_entities") == []
    with pytest.raises(PublicationSafetyError, match="unfinished_attempt_handle"):
        restarted.begin(fx.state.session, reference.attempt_id, _json(fx.core.read_catalog(reference)["candidate"]))


def test_lost_seal_response_reuses_original_verified_evidence_without_reupload_change(fx):
    attempt = fx.boundary.allocate_attempt(fx.state.session)
    candidate = {
        "generation_id": "generation", "source_generation": "source", "content_hash": "content",
        "staged_manifest_digest": "staged", "validation_digest": "validation",
        "authorization_digest": AUTH, "attestation_digest": "attestation", "expected_target": TARGET,
    }
    kwargs = {
        "attempt_id": attempt, "candidate": candidate,
        "products": {"ontology_entities": [], "ontology_relationships": []},
    }
    fx.db.fail_seal = True
    with pytest.raises(SqlPublicationError):
        fx.core.stage(fx.state.session, **kwargs)
    before = fx.db.attempts[attempt]["seal"]
    reference = fx.core.stage(fx.state.session, **kwargs)
    assert fx.db.attempts[attempt]["seal"] == before
    assert len(fx.blob.writes) == 3
    assert fx.core.read_table(reference, "ontology_entities") == []


def test_catalog_upload_response_loss_never_exposes_partial_sql_seal(fx):
    attempt = fx.boundary.allocate_attempt(fx.state.session)
    kwargs = {
        "attempt_id": attempt, "candidate": fx.candidate,
        "products": {"ontology_entities": [], "ontology_relationships": []},
    }

    def lose_catalog_response(_name):
        if len(fx.blob.writes) == 3:
            fx.blob.on_upload = None
            raise HttpResponseError("synthetic response lost after catalog create")

    fx.blob.on_upload = lose_catalog_response
    with pytest.raises(ArtifactVerificationError):
        fx.core.stage(fx.state.session, **kwargs)
    assert "seal" not in fx.db.attempts[attempt]
    assert fx.core.active() == (None, None)
    reference = fx.core.stage(fx.state.session, **kwargs)
    assert len(fx.blob.data) == 3
    assert all(not options["overwrite"] for _name, options in fx.blob.writes)
    assert fx.core.read_table(reference, "ontology_entities") == []


@pytest.mark.parametrize("component", ["catalog", "descriptor", "inventory"])
def test_exact_persisted_catalog_or_inventory_substitution_rejects(fx, component):
    reference = fx.stage()
    row = fx.db.attempts[reference.attempt_id]
    catalog, digest, inventory, evidence = row["seal"]
    body = json.loads(evidence)
    if component == "catalog":
        body["provider_readback"]["catalog_inventory"]["objects"][0]["blob_name"] += "-substituted"
    elif component == "descriptor":
        body["provider_readback"]["product_inventory"]["objects"][0]["etag"] = '"substituted"'
    else:
        inventory = "[]"
    row["seal"] = (catalog, digest, inventory, _json(body))
    with pytest.raises((PublicationSafetyError, ArtifactVerificationError)):
        fx.core.read_catalog(reference)


def test_independent_restoration_and_no_raw_provider_factory_enablement(fx):
    reference = fx.stage()
    fx.grant(fx.state, reference)
    accepted = fx.commit(fx.state, reference)
    with pytest.raises(SqlPublicationError):
        fx.commit(accepted, reference, operation="restore")
    fx.grant(accepted, reference, operation="restore")
    restored = fx.commit(accepted, reference, operation="restore")
    assert restored.active == reference
    assert len(fx.blob.writes) == 3
    with pytest.raises(PublicationSafetyError, match="not_implemented_or_qualified"):
        AzureSqlBlobAttemptBoundary(qualified=True, execution_enabled=True)


def test_actual_materializer_batch_provider_commit_reader_and_independent_restore(
    fx, tmp_path, monkeypatch,
):
    env, prior, _model, _control, candidate, _calls = materializer_fixture(tmp_path, monkeypatch)
    fx.db.expected_target = deepcopy(env.target)
    boundary = fx.server(expected_target=env.target).for_request(fx.headers())
    materializer = CandidateGenerationMaterializer(
        storage=SimpleNamespace(
            read_generation=lambda _generation: deepcopy(env.staged),
            read_pointer=lambda: pytest.fail("Legacy pointer used"),
        ),
        documents=OneLakeDocumentStore(tmp_path / "not-the-control-db"),
        service=env.service, authorizer=prior._authorizer, target_id="synthetic",
        clock=lambda: None, expected_target=env.target, output_policies=prior._output_policies,
        publication_protocol="immutable-attempt/v1", attempt_boundary=boundary,
    )
    materializer.bind_attempt(fx.state.session, attempt_id=boundary.allocate_attempt(fx.state.session))
    result = materializer(candidate)
    reference = AttemptReference.parse(result["attempt_reference"])
    fx.authority.record_grant(
        fx.db.target_id, fx.state.session.session_id, fx.state.session.epoch,
        catalog_digest=reference.catalog_digest, operation="admit",
        authority_digest=env.context.authorization_digest, evidence_digest="b" * 64,
        valid_from=NOW - timedelta(minutes=1), valid_until=NOW + timedelta(days=1),
    )
    admitted = materializer.commit_attempt(expected_revision=fx.state.revision, request_id=str(uuid4()))
    assert admitted.active == reference
    assert materializer.reader.read_ontology() == ([], [])
    release = prior._authorizer.reader.read("restore")
    prior._authorizer.authorize_restore = lambda **_: SimpleNamespace(
        **{**vars(release), "attestation_digest": RESTORE_AUTH},
    )
    fx.authority.record_grant(
        fx.db.target_id, fx.state.session.session_id, fx.state.session.epoch,
        catalog_digest=reference.catalog_digest, operation="restore",
        authority_digest=RESTORE_AUTH, evidence_digest="b" * 64,
        valid_from=NOW - timedelta(minutes=1), valid_until=NOW + timedelta(days=1),
    )
    writes = len(fx.blob.writes)
    request_id = str(uuid4())
    fx.db.fail_commit = True
    with pytest.raises(SqlPublicationError):
        materializer.restore_attempt(reference, expected_revision=admitted.revision, request_id=request_id)
    historical = boundary.read_control()
    fx.authority.revoke(
        fx.db.target_id, fx.state.session.session_id, fx.state.session.epoch,
        catalog_digest=reference.catalog_digest, operation="restore",
    )
    fx.db.now = NOW + timedelta(days=100)
    fx.blob.policy["properties"]["state"] = "Unlocked"
    materializer._attempt_protocol = ImmutableAttemptProtocol(
        fx.server(expected_target=env.target).for_request(fx.headers()),
    )
    materializer._attempt_request_digests.clear()
    prior._authorizer.authorize_restore = lambda **_: pytest.fail("Historical recovery reauthorized")
    restored = materializer.restore_attempt(
        reference, expected_revision=admitted.revision, request_id=request_id,
        authorization_digest=RESTORE_AUTH,
    )
    assert restored == historical
    assert len(fx.blob.writes) == writes  # No restoration rematerialization/upload.
    assert env.sink.calls == env.catalogs == []  # No fixed-table/catalog sinks.
