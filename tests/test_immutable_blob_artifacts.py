"""Offline SDK/ARM seams for immutable completed Blob attempts."""

from __future__ import annotations

import hashlib
import traceback
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from azure.core import MatchConditions
from azure.core.credentials import AccessToken, TokenCredential
from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceModifiedError,
)
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.storage.blob import BlobProperties, BlobServiceClient, BlobType

from storage.immutable_blob_artifacts import (
    ArtifactVerificationError,
    AzureBlobManagementReader,
    ImmutableBlobArtifactStore,
    ImmutableBlobTarget,
)

NOW = datetime(2026, 10, 28, 4, 0, tzinfo=UTC)
ACCOUNT_ID = (
    "/subscriptions/11111111-1111-1111-1111-111111111111"
    "/resourceGroups/test-only/providers/Microsoft.Storage/storageAccounts/testartifacts"
)
TARGET = ImmutableBlobTarget(ACCOUNT_ID, "attempt-artifacts")
HORIZON = NOW + timedelta(days=2)


class Fixture:
    def __init__(self) -> None:
        self.credential = Mock(spec=TokenCredential)
        self.credential.get_token.return_value = AccessToken(
            "secret-test-token", 9999999999
        )
        self.account = {
            "id": ACCOUNT_ID,
            "kind": "StorageV2",
            "properties": {
                "isHnsEnabled": False,
                "allowSharedKeyAccess": False,
                "allowBlobPublicAccess": False,
                "primaryEndpoints": {"blob": f"{TARGET.account_url}/"},
            },
        }
        self.service_body = {
            "id": f"{ACCOUNT_ID}/blobServices/default",
            "properties": {"isVersioningEnabled": False},
        }
        self.policy = {
            "id": f"{TARGET.container_id}/immutabilityPolicies/default",
            "etag": '"policy-1"',
            "properties": {
                "state": "Locked",
                "allowProtectedAppendWrites": False,
                "allowProtectedAppendWritesAll": False,
                "immutabilityPeriodSinceCreationInDays": 10,
            },
        }
        self.status = 200
        self.date = format_datetime(NOW, usegmt=True)
        self.requests: list[httpx.Request] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.arm))
        self.reader = AzureBlobManagementReader(self.credential, client=self.client)
        self.service = Mock(spec=BlobServiceClient)
        self.service.url = TARGET.account_url
        self.blobs: dict[str, Mock] = {}
        self.data: dict[str, bytes] = {}
        self.props: dict[str, BlobProperties] = {}
        self.writes: list[tuple[str, dict]] = []
        self.downloads: list[dict] = []
        self.on_upload = None
        self.on_download = None
        self.service.get_blob_client.side_effect = self.blob
        self.store = ImmutableBlobArtifactStore(
            TARGET,
            self.credential,
            service_client=self.service,
            management_reader=self.reader,
        )

    def arm(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "management.azure.com"
        assert dict(request.url.params) == {"api-version": "2025-08-01"}
        assert request.headers["Authorization"] == "Bearer secret-test-token"
        if request.url.path == ACCOUNT_ID:
            body = self.account
        elif request.url.path == self.service_body["id"]:
            body = self.service_body
        elif request.url.path == self.policy["id"]:
            body = self.policy
        else:
            pytest.fail("Unexpected ARM resource")
        return httpx.Response(self.status, json=body, headers={"Date": self.date})

    def blob(self, container: str, name: str) -> Mock:
        assert container == TARGET.container_name
        if name in self.blobs:
            return self.blobs[name]
        client = Mock()
        client.account_name = "testartifacts"
        client.container_name = container
        client.blob_name = name
        client.url = f"{TARGET.account_url}/{container}/{name}"

        def upload(body: bytes, **kwargs: object) -> None:
            self.writes.append((name, kwargs))
            assert kwargs["overwrite"] is False
            assert kwargs["match_condition"] == MatchConditions.IfMissing
            assert kwargs["etag"] == "*"
            assert kwargs["blob_type"] == BlobType.BLOCKBLOB
            assert kwargs["length"] == len(body)
            if name in self.data:
                raise ResourceExistsError("redacted-provider-body")
            self.data[name] = body
            self.props[name] = BlobProperties(
                **{
                    "x-ms-blob-type": "BlockBlob",
                    "Content-Length": len(body),
                    "ETag": '"blob-1"',
                    "x-ms-creation-time": NOW,
                    "Last-Modified": NOW,
                    "x-ms-server-encrypted": True,
                    "metadata": {},
                }
            )
            if self.on_upload:
                self.on_upload(name)

        def properties(**kwargs: object) -> BlobProperties:
            if "raw_response_hook" in kwargs:
                kwargs["raw_response_hook"](
                    SimpleNamespace(
                        http_response=SimpleNamespace(headers={"Date": self.date})
                    )
                )
            return self.props[name]

        def download(**kwargs: object) -> Mock:
            self.downloads.append(kwargs)
            assert kwargs["etag"] == self.props[name].etag
            assert kwargs["match_condition"] == MatchConditions.IfNotModified
            if self.on_download:
                self.on_download(name)
            return Mock(readall=Mock(return_value=self.data[name]))

        client.upload_blob.side_effect = upload
        client.get_blob_properties.side_effect = properties
        client.download_blob.side_effect = download
        self.blobs[name] = client
        return client

    def upload(self, artifacts: dict[str, bytes] | None = None):
        attempt = self.store.begin_attempt()
        return self.store.upload_attempt(
            attempt,
            artifacts or {"catalog.json": b'{"ok":true}', "table.delta": b"data"},
            retain_until=HORIZON,
        )


@pytest.fixture
def fx():
    fixture = Fixture()
    yield fixture
    fixture.client.close()


def test_full_inventory_has_exact_provider_readback(fx) -> None:
    inventory = fx.upload()
    assert len(inventory.objects) == 2
    assert len(inventory.manifest_sha256) == 64
    assert {item.logical_name for item in inventory.objects} == {
        "catalog.json",
        "table.delta",
    }
    for item in inventory.objects:
        assert item.account_id == ACCOUNT_ID
        assert item.account_url == TARGET.account_url
        assert item.container_name == TARGET.container_name
        assert item.version_id is None
        assert item.etag == '"blob-1"'
        assert item.policy_etag == '"policy-1"'
        assert item.retained_until == NOW + timedelta(days=10)
        body = fx.store.read_object(item)
        assert hashlib.sha256(body).hexdigest() == item.sha256
        assert len(body) == item.size
    assert fx.requests
    assert all(request.method == "GET" for request in fx.requests)
    assert len(fx.writes) == 2


def test_namespace_unique_and_same_binding_retry_is_idempotent(fx) -> None:
    attempt = fx.store.begin_attempt()
    another = fx.store.begin_attempt()
    assert attempt != another
    inventory = fx.store.upload_attempt(
        attempt, {"table": b"complete"}, retain_until=HORIZON
    )
    retry = fx.store.upload_attempt(
        attempt, {"table": b"complete"}, retain_until=HORIZON
    )
    assert inventory == retry
    assert len(fx.data) == 1


@pytest.mark.parametrize(
    "artifacts,horizon",
    [
        ({"table": b"different"}, HORIZON),
        ({"table": b"complete", "new": b"new"}, HORIZON),
        ({"renamed": b"complete"}, HORIZON),
        ({"table": b"complete"}, HORIZON + timedelta(days=1)),
    ],
)
def test_retry_cannot_change_bound_manifest_or_horizon(fx, artifacts, horizon) -> None:
    attempt = fx.store.begin_attempt()
    fx.store.upload_attempt(attempt, {"table": b"complete"}, retain_until=HORIZON)
    with pytest.raises(ArtifactVerificationError, match="attempt_binding_mismatch"):
        fx.store.upload_attempt(attempt, artifacts, retain_until=horizon)
    assert len(fx.writes) == 1


def test_caller_cannot_supply_attempt_namespace(fx) -> None:
    with pytest.raises(ArtifactVerificationError, match="attempt_not_owned"):
        fx.store.upload_attempt(
            "11111111-1111-1111-1111-111111111111", {"x": b"x"}, retain_until=HORIZON
        )
    assert not fx.requests
    assert not fx.writes


@pytest.mark.parametrize(
    "name", ["../prod", "a/b", "/absolute", "a?sig=secret", "%2f", "A", "x\n", "a\\b"]
)
def test_request_cannot_supply_blob_paths(fx, name) -> None:
    with pytest.raises(ArtifactVerificationError, match="artifact_manifest_invalid"):
        fx.store.upload_attempt(
            fx.store.begin_attempt(), {name: b"x"}, retain_until=HORIZON
        )
    assert not fx.writes


@pytest.mark.parametrize(
    "artifacts",
    [
        {},
        {"x": "not bytes"},
        {"x": b"x" * (4 * 1024 * 1024 + 1)},
        {f"p{i}": b"x" for i in range(1025)},
    ],
)
def test_complete_manifest_validated_before_any_provider_write(fx, artifacts) -> None:
    with pytest.raises(ArtifactVerificationError):
        fx.store.upload_attempt(
            fx.store.begin_attempt(), artifacts, retain_until=HORIZON
        )
    assert not fx.writes
    assert not fx.requests


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "Unlocked"),
        ("state", None),
        ("allowProtectedAppendWrites", True),
        ("allowProtectedAppendWrites", None),
        ("allowProtectedAppendWritesAll", True),
        ("allowProtectedAppendWritesAll", None),
        ("immutabilityPeriodSinceCreationInDays", 0),
        ("immutabilityPeriodSinceCreationInDays", True),
        ("immutabilityPeriodSinceCreationInDays", 146001),
        ("immutabilityPeriodSinceCreationInDays", "10"),
    ],
)
def test_absent_or_unsafe_actual_policy_blocks_first_write(fx, field, value) -> None:
    fx.policy["properties"][field] = value
    with pytest.raises(ArtifactVerificationError):
        fx.upload()
    assert not fx.writes


@pytest.mark.parametrize(
    "field", ["allowProtectedAppendWrites", "allowProtectedAppendWritesAll", "state"]
)
def test_missing_policy_field_never_defaults_to_safe(fx, field) -> None:
    del fx.policy["properties"][field]
    with pytest.raises(ArtifactVerificationError):
        fx.upload()
    assert not fx.writes


@pytest.mark.parametrize("versioning", [True, None, "false", 0])
def test_versioning_must_be_explicit_provider_false(fx, versioning) -> None:
    fx.service_body["properties"]["isVersioningEnabled"] = versioning
    with pytest.raises(ArtifactVerificationError, match="versioning_unverified"):
        fx.upload()
    assert not fx.writes


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowSharedKeyAccess", True),
        ("allowSharedKeyAccess", None),
        ("isHnsEnabled", True),
        ("isHnsEnabled", None),
        ("allowBlobPublicAccess", True),
        ("primaryEndpoints", {"blob": "https://exampleaccount.blob.core.windows.net/"}),
    ],
)
def test_provider_account_must_match_constructor_owned_target(fx, field, value) -> None:
    fx.account["properties"][field] = value
    with pytest.raises(
        ArtifactVerificationError, match="account_configuration_unverified"
    ):
        fx.upload()
    assert not fx.writes


@pytest.mark.parametrize("which", ["account", "service_body", "policy"])
def test_arm_identity_mismatch_blocks_writes(fx, which) -> None:
    getattr(fx, which)["id"] = "/wrong/resource"
    # Keep route dispatch on the constructor-owned URLs for malformed returned IDs.
    fx.client.close()

    def wrong(_request):
        body = (
            fx.account
            if _request.url.path == ACCOUNT_ID
            else (
                fx.service_body
                if _request.url.path.endswith("/blobServices/default")
                else fx.policy
            )
        )
        return httpx.Response(200, json=body, headers={"Date": fx.date})

    fx.reader._client = httpx.Client(transport=httpx.MockTransport(wrong))
    with pytest.raises(ArtifactVerificationError, match="identity_mismatch"):
        fx.upload()
    assert not fx.writes
    fx.reader._client.close()


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 404, 429, 500])
def test_management_denial_absence_redirects_fail_closed(fx, status) -> None:
    fx.status = status
    with pytest.raises(ArtifactVerificationError, match="management_read_failed"):
        fx.upload()
    assert not fx.writes


@pytest.mark.parametrize("date", ["", "invalid-date"])
def test_provider_clock_required_not_local_fallback(fx, date) -> None:
    fx.date = date
    with pytest.raises(ArtifactVerificationError, match="provider_date"):
        fx.upload()
    assert not fx.writes


@pytest.mark.parametrize(
    "horizon,code",
    [
        (NOW, "retention_horizon_expired"),
        (NOW - timedelta(seconds=1), "retention_horizon_expired"),
        (NOW + timedelta(days=11), "retention_horizon_insufficient"),
        (NOW.replace(tzinfo=None), "retention_horizon_invalid"),
    ],
)
def test_retention_horizon_rejected_before_upload(fx, horizon, code) -> None:
    with pytest.raises(ArtifactVerificationError, match=code):
        fx.store.upload_attempt(
            fx.store.begin_attempt(), {"x": b"x"}, retain_until=horizon
        )
    assert not fx.writes


@pytest.mark.parametrize(
    "field,value",
    [
        ("blob_type", BlobType.APPENDBLOB),
        ("blob_type", BlobType.PAGEBLOB),
        ("version_id", "new-version"),
        ("snapshot", "snapshot"),
        ("server_encrypted", False),
        ("etag", None),
        ("size", -1),
        ("size", 0),
        ("size", 4 * 1024 * 1024 + 1),
        ("creation_time", None),
        ("creation_time", NOW.replace(tzinfo=None)),
        ("creation_time", NOW + timedelta(seconds=1)),
    ],
)
def test_bad_blob_properties_never_seal(fx, field, value) -> None:
    fx.on_upload = lambda name: setattr(fx.props[name], field, value)
    with pytest.raises(ArtifactVerificationError):
        fx.upload({"table": b"complete"})


def test_copy_or_encoded_object_not_completed_direct_block_blob(fx) -> None:
    fx.on_upload = lambda name: setattr(fx.props[name].copy, "id", "copy-id")
    with pytest.raises(ArtifactVerificationError, match="blob_properties_unverified"):
        fx.upload()
    fx.on_upload = None


@pytest.mark.parametrize("value", [b"", b"corrupt", b"x" * 100])
def test_partial_or_wrong_bytes_never_seal(fx, value) -> None:
    fx.on_download = lambda name: fx.data.__setitem__(name, value)
    with pytest.raises(ArtifactVerificationError, match="readback_"):
        fx.upload({"table": b"complete"})


def test_failed_second_upload_returns_no_inventory_and_no_cleanup(fx) -> None:
    def fail(name):
        if len(fx.writes) == 2:
            raise HttpResponseError("https://secret-host?sig=secret")

    fx.on_upload = fail
    with pytest.raises(
        ArtifactVerificationError, match="blob_provider_operation_failed"
    ) as failure:
        fx.upload()
    assert "secret" not in "".join(traceback.format_exception(failure.value))
    assert all(not client.delete_blob.called for client in fx.blobs.values())
    assert len(fx.data) == 2


def test_exact_existing_bytes_required_after_ambiguous_retry(fx) -> None:
    attempt = fx.store.begin_attempt()
    fx.store.upload_attempt(attempt, {"table": b"complete"}, retain_until=HORIZON)
    name = next(iter(fx.data))
    fx.data[name] = b"WRONG!!!"
    with pytest.raises(ArtifactVerificationError, match="readback_content_mismatch"):
        fx.store.upload_attempt(attempt, {"table": b"complete"}, retain_until=HORIZON)


def test_policy_is_rechecked_after_each_write_before_inventory(fx) -> None:
    fx.on_upload = lambda name: fx.policy["properties"].__setitem__(
        "allowProtectedAppendWritesAll", True
    )
    with pytest.raises(ArtifactVerificationError, match="immutable_policy_unverified"):
        fx.upload()
    assert len(fx.writes) == 1


def test_policy_is_rechecked_after_conditional_byte_read(fx) -> None:
    fx.on_download = lambda name: fx.service_body["properties"].__setitem__(
        "isVersioningEnabled", True
    )
    with pytest.raises(ArtifactVerificationError, match="versioning_unverified"):
        fx.upload({"table": b"complete"})


def test_etag_change_during_read_rejected(fx) -> None:
    fx.on_download = lambda name: setattr(fx.props[name], "etag", '"changed"')
    with pytest.raises(ArtifactVerificationError, match="readback_properties_changed"):
        fx.upload({"table": b"complete"})


def test_read_revalidates_current_provider_not_old_inventory(fx) -> None:
    sealed = fx.upload({"table": b"complete"}).objects[0]
    fx.policy["properties"]["state"] = "Unlocked"
    with pytest.raises(ArtifactVerificationError, match="immutable_policy_unverified"):
        fx.store.read_object(sealed)


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": ACCOUNT_ID + "-other"},
        {"account_url": "https://evil"},
        {"container_name": "production"},
        {"blob_name": "../production"},
        {"version_id": "version"},
        {"policy_id": "/substitute"},
        {"attempt_id": "../attempt"},
        {"logical_name": "../table"},
    ],
)
def test_reader_rejects_retargeted_inventory_before_provider_calls(fx, changes) -> None:
    sealed = fx.upload({"table": b"complete"}).objects[0]
    calls = len(fx.requests)
    with pytest.raises(ArtifactVerificationError, match="sealed_identity_mismatch"):
        fx.store.read_object(replace(sealed, **changes))
    assert len(fx.requests) == calls


@pytest.mark.parametrize(
    "changes",
    [
        {"etag": '"other"'},
        {"size": 1},
        {"sha256": "0" * 64},
        {"creation_time": NOW - timedelta(seconds=1)},
        {"retained_until": NOW + timedelta(days=11)},
    ],
)
def test_reader_never_trusts_forged_evidence_values(fx, changes) -> None:
    sealed = fx.upload({"table": b"complete"}).objects[0]
    with pytest.raises(ArtifactVerificationError):
        fx.store.read_object(replace(sealed, **changes))


def test_reader_rejects_expired_retention_even_if_bytes_still_exist(fx) -> None:
    sealed = fx.upload({"table": b"complete"}).objects[0]
    fx.date = format_datetime(NOW + timedelta(days=10), usegmt=True)
    with pytest.raises(ArtifactVerificationError, match="retention_horizon_expired"):
        fx.store.read_object(sealed)


@pytest.mark.parametrize(
    "account,container",
    [
        (ACCOUNT_ID + "?sig=x", "attempts"),
        (ACCOUNT_ID, "../attempts"),
        (ACCOUNT_ID, "ab"),
        (ACCOUNT_ID, "a--b"),
        ("https://evil", "attempts"),
    ],
)
def test_target_accepts_no_urls_sas_or_arbitrary_paths(account, container) -> None:
    with pytest.raises(ArtifactVerificationError):
        ImmutableBlobTarget(account, container)


def test_sas_key_and_substituted_service_are_not_constructor_credentials(fx) -> None:
    with pytest.raises(ArtifactVerificationError, match="token_credential_required"):
        ImmutableBlobArtifactStore(TARGET, "account-key")
    fx.service.url += "?sig=secret"
    with pytest.raises(ArtifactVerificationError, match="sdk_target_mismatch"):
        ImmutableBlobArtifactStore(
            TARGET,
            fx.credential,
            service_client=fx.service,
            management_reader=fx.reader,
        )


class StorageStream:
    def __init__(self, body, response):
        self._chunks = iter([body])
        self.content_length = len(body)
        self.response = response

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)


class StorageResponse(HttpResponse):
    def __init__(self, request, status=201):
        super().__init__(request, None)
        self.status_code = status
        self.headers = {
            "ETag": '"blob-1"',
            "Last-Modified": format_datetime(NOW, usegmt=True),
        }
        self.reason = "Created"
        self.content_type = "application/octet-stream"

    def body(self):
        return getattr(self, "payload", b"")

    def read(self):
        return self.body()

    def stream_download(self, pipeline, **kwargs):
        return StorageStream(self.body(), self)


class StorageTransport(HttpTransport):
    def __init__(self):
        self.requests = []
        self.bodies = {}

    def open(self):
        pass

    def close(self):
        pass

    def __exit__(self, *args):
        pass

    def send(self, request, **kwargs):
        self.requests.append(request)
        if request.method == "PUT":
            assert request.headers["If-None-Match"] == "*"
            assert request.headers["x-ms-blob-type"] == "BlockBlob"
            assert "comp=" not in request.url
            self.bodies[request.url] = request.body
            return StorageResponse(request)
        response = StorageResponse(request, 200)
        body = self.bodies[request.url]
        response.headers.update(
            {
                "Date": format_datetime(NOW, usegmt=True),
                "x-ms-creation-time": format_datetime(NOW, usegmt=True),
                "Content-Length": str(len(body)),
                "x-ms-blob-type": "BlockBlob",
                "x-ms-server-encrypted": "true",
            }
        )
        if request.method == "GET":
            assert request.headers["If-Match"] == '"blob-1"'
            response.payload = body
            if not body and request.headers.get("x-ms-range"):
                response.status_code = 416
                response.headers["x-ms-error-code"] = "InvalidRange"
            # The SDK requests ranges; the response must describe completed bytes.
            if body:
                response.status_code = 206
                response.headers["Content-Range"] = (
                    f"bytes 0-{len(body) - 1}/{len(body)}"
                )
        else:
            assert request.method == "HEAD"
        return response


@pytest.mark.parametrize(
    "body",
    [b"", b"complete", b"x" * (4 * 1024 * 1024)],
    ids=["empty", "small", "max-single-put"],
)
def test_full_store_with_actual_sdk_transport_uploads_reads_and_verifies(
    fx, body
) -> None:
    transport = StorageTransport()
    service = BlobServiceClient(
        TARGET.account_url,
        credential=fx.credential,
        transport=transport,
        max_single_put_size=4 * 1024 * 1024,
        retry_total=0,
    )
    store = ImmutableBlobArtifactStore(
        TARGET, fx.credential, service_client=service, management_reader=fx.reader
    )
    inventory = store.upload_attempt(
        store.begin_attempt(), {"table": body}, retain_until=HORIZON
    )
    assert inventory.objects[0].sha256 == hashlib.sha256(body).hexdigest()
    assert store.read_object(inventory.objects[0]) == body
    puts = [r for r in transport.requests if r.method == "PUT"]
    assert len(puts) == 1
    assert all(r.method in {"PUT", "HEAD", "GET"} for r in transport.requests)
    service.close()


@pytest.mark.parametrize("conflict", [ResourceExistsError, ResourceModifiedError])
def test_ambiguous_first_upload_retries_only_verified_complete_bytes(
    fx, conflict
) -> None:
    attempt = fx.store.begin_attempt()

    def fail_after_provider_create(name):
        raise HttpResponseError("secret-provider-response")

    fx.on_upload = fail_after_provider_create
    with pytest.raises(
        ArtifactVerificationError, match="blob_provider_operation_failed"
    ):
        fx.store.upload_attempt(attempt, {"table": b"complete"}, retain_until=HORIZON)
    fx.on_upload = None
    client = next(iter(fx.blobs.values()))
    client.upload_blob.side_effect = conflict("conflict-secret")
    inventory = fx.store.upload_attempt(
        attempt, {"table": b"complete"}, retain_until=HORIZON
    )
    assert inventory.objects[0].sha256 == hashlib.sha256(b"complete").hexdigest()
    assert not client.delete_blob.called


def test_retry_rejects_changed_previously_verified_etag(fx) -> None:
    attempt = fx.store.begin_attempt()
    fx.store.upload_attempt(attempt, {"table": b"complete"}, retain_until=HORIZON)
    fx.props[next(iter(fx.props))].etag = '"substituted"'
    with pytest.raises(ArtifactVerificationError, match="sealed_properties_mismatch"):
        fx.store.upload_attempt(attempt, {"table": b"complete"}, retain_until=HORIZON)
    assert len(fx.writes) == 1


def test_retention_uses_actual_blob_creation_not_current_time(fx) -> None:
    fx.on_upload = lambda name: setattr(
        fx.props[name], "creation_time", NOW - timedelta(days=9)
    )
    with pytest.raises(
        ArtifactVerificationError, match="retention_horizon_insufficient"
    ):
        fx.upload({"table": b"complete"})


def test_legacy_ontology_sized_product_inventory_is_not_truncated(fx) -> None:
    bodies = {f"ontology_product_{index}": b"" for index in range(708)}
    inventory = fx.upload(bodies)
    assert len(inventory.objects) == 708
    assert {item.logical_name for item in inventory.objects} == set(bodies)
    assert len(fx.writes) == 708


def test_total_attempt_size_rejected_before_provider_calls(fx) -> None:
    bodies = {f"product_{index}": b"x" * (4 * 1024 * 1024) for index in range(17)}
    with pytest.raises(ArtifactVerificationError, match="attempt_size_invalid"):
        fx.upload(bodies)
    assert not fx.requests
    assert not fx.writes


@pytest.mark.parametrize(
    "error",
    [
        HttpResponseError("https://secret-host?sig=secret"),
        ValueError("https://secret-host?sig=secret"),
    ],
)
def test_read_provider_errors_and_traceback_are_sanitized(fx, error) -> None:
    sealed = fx.upload({"table": b"complete"}).objects[0]
    client = fx.blobs[sealed.blob_name]
    client.download_blob.side_effect = error
    with pytest.raises(
        ArtifactVerificationError, match="blob_provider_operation_failed"
    ) as failure:
        fx.store.read_object(sealed)
    assert "secret" not in "".join(traceback.format_exception(failure.value))


def test_management_network_and_token_errors_are_sanitized(fx) -> None:
    fx.credential.get_token.side_effect = HttpResponseError("token-secret")
    with pytest.raises(
        ArtifactVerificationError, match="management_read_failed"
    ) as failure:
        fx.upload()
    assert "secret" not in "".join(traceback.format_exception(failure.value))
    assert not fx.writes


def test_explicit_content_encoding_and_extra_metadata_reject(fx) -> None:
    fx.on_upload = lambda name: setattr(
        fx.props[name].content_settings, "content_encoding", "gzip"
    )
    with pytest.raises(ArtifactVerificationError, match="blob_properties_unverified"):
        fx.upload({"table": b"complete"})
    fx.on_upload = lambda name: setattr(fx.props[name], "metadata", {"sealed": "true"})
    with pytest.raises(ArtifactVerificationError, match="blob_properties_unverified"):
        fx.upload({"table": b"complete"})


def test_same_bytes_with_substituted_sdk_blob_target_are_rejected(fx) -> None:
    original = fx.service.get_blob_client.side_effect

    def substituted(container, name):
        blob = original(container, name)
        blob.url = blob.url.replace(TARGET.container_name, "production")
        return blob

    fx.service.get_blob_client.side_effect = substituted
    with pytest.raises(
        ArtifactVerificationError, match="blob_client_identity_mismatch"
    ):
        fx.upload()
    assert not fx.writes


def test_real_sdk_emits_single_completed_put_with_if_none_match_star(fx) -> None:
    transport = StorageTransport()
    service = BlobServiceClient(
        TARGET.account_url,
        credential=fx.credential,
        transport=transport,
        max_single_put_size=4 * 1024 * 1024,
        retry_total=0,
    )
    store = ImmutableBlobArtifactStore(
        TARGET, fx.credential, service_client=service, management_reader=fx.reader
    )
    # Exercise the actual SDK upload kwargs without performing a network request.
    client = store._client("attempts/11111111-1111-1111-1111-111111111111/file.blob")
    body = b"complete"
    client.upload_blob(
        body,
        blob_type=BlobType.BLOCKBLOB,
        length=len(body),
        overwrite=False,
        etag="*",
        match_condition=MatchConditions.IfMissing,
        validate_content=True,
        max_concurrency=1,
    )
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.method == "PUT"
    assert request.headers["If-None-Match"] == "*"
    assert request.headers["x-ms-blob-type"] == "BlockBlob"
    assert request.headers["Content-Length"] == str(len(body))
    assert request.body == body
    assert "comp=" not in request.url
    assert "sig=" not in request.url
    service.close()
