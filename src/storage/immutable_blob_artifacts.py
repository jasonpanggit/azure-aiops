"""Create-only, provider-verified Blob artifacts; no publication/SQL authority."""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Protocol
from uuid import uuid4

import httpx
from azure.core import MatchConditions
from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceModifiedError
from azure.storage.blob import BlobClient, BlobServiceClient, BlobType

_API_VERSION = "2025-08-01"
_MAX_OBJECT_BYTES = 4 * 1024 * 1024
_MAX_ATTEMPT_BYTES = 64 * 1024 * 1024
_MAX_OBJECTS = 1024
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ACCOUNT_ID = re.compile(
    rf"/subscriptions/{_UUID}/resourceGroups/[A-Za-z0-9_.()-]{{1,90}}"
    r"/providers/Microsoft.Storage/storageAccounts/(?P<account>[a-z0-9]{3,24})"
)


class ArtifactVerificationError(RuntimeError):
    """Sanitized failure code; never contains provider URLs, bodies or tokens."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ArtifactVerificationError(code)


def _aware(value: object, code: str) -> datetime:
    _require(isinstance(value, datetime), code)
    if not isinstance(value, datetime):
        raise ArtifactVerificationError(code)
    _require(value.tzinfo is not None and value.utcoffset() is not None, code)
    return value.astimezone(UTC)


def _server_date(value: object) -> datetime:
    _require(isinstance(value, str), "provider_date_missing")
    try:
        return _aware(parsedate_to_datetime(str(value)), "provider_date_invalid")
    except (ValueError, TypeError, OverflowError):
        raise ArtifactVerificationError("provider_date_invalid") from None


def _etag(value: object) -> str:
    _require(
        isinstance(value, str) and bool(re.fullmatch(r'"[A-Za-z0-9_-]{1,128}"', value)),
        "provider_etag_invalid",
    )
    return str(value)


@dataclass(frozen=True)
class ImmutableBlobTarget:
    """Trusted configuration target; public Azure GPv2 only, no SAS/custom roots."""

    account_id: str
    container_name: str

    def __post_init__(self) -> None:
        _require(bool(_ACCOUNT_ID.fullmatch(self.account_id)), "target_account_invalid")
        _require(
            bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.container_name))
            and "--" not in self.container_name,
            "target_container_invalid",
        )

    @property
    def account_url(self) -> str:
        """Return the sole allowed provider endpoint, derived from the ARM ID."""
        return f"https://{self.account_id.rsplit('/', 1)[1]}.blob.core.windows.net"

    @property
    def container_id(self) -> str:
        """Return the exact container management identity."""
        return (
            f"{self.account_id}/blobServices/default/containers/{self.container_name}"
        )


@dataclass(frozen=True)
class _ProviderRead:
    body: Mapping[str, object]
    server_time: datetime


class _ManagementReader(Protocol):
    def get(self, resource_id: str) -> _ProviderRead: ...


class AzureBlobManagementReader:
    """Authenticated GET-only ARM reader; transport injection is a trusted test seam."""

    def __init__(
        self,
        credential: TokenCredential,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._credential = credential
        self._client = client or httpx.Client(
            timeout=30, follow_redirects=False, trust_env=False
        )
        self._owns_client = client is None

    def close(self) -> None:
        """Close the owned HTTP transport without closing an injected transport."""
        if self._owns_client:
            self._client.close()

    def get(self, resource_id: str) -> _ProviderRead:
        """Read one canonical Storage ARM resource, never redirect or echo failures."""
        _require(
            bool(
                re.fullmatch(
                    _ACCOUNT_ID.pattern
                    + r"(?:/blobServices/default(?:/containers/[a-z0-9-]{3,63}/immutabilityPolicies/default)?)?",
                    resource_id,
                )
            ),
            "management_target_invalid",
        )
        try:
            token = self._credential.get_token("https://management.azure.com/.default")
            response = self._client.get(
                f"https://management.azure.com{resource_id}",
                params={"api-version": _API_VERSION},
                headers={"Authorization": f"Bearer {token.token}"},
                follow_redirects=False,
            )
            _require(response.status_code == 200, "management_read_failed")
            body = response.json()
            _require(isinstance(body, dict), "management_response_invalid")
            return _ProviderRead(body, _server_date(response.headers.get("Date")))
        except (AzureError, httpx.HTTPError, ValueError):
            raise ArtifactVerificationError("management_read_failed") from None


@dataclass(frozen=True)
class _Policy:
    resource_id: str
    etag: str
    retention_days: int
    server_time: datetime


@dataclass(frozen=True)
class SealedBlobObject:
    """Exact readback identity/evidence; a value object, not an authenticated grant."""

    account_id: str
    account_url: str
    container_name: str
    attempt_id: str
    logical_name: str
    blob_name: str
    etag: str
    size: int
    sha256: str
    creation_time: datetime
    verified_at: datetime
    retained_until: datetime
    policy_id: str
    policy_etag: str
    policy_retention_days: int
    version_id: None = None


@dataclass(frozen=True)
class SealedBlobInventory:
    """All expected objects verified; no partial inventory or active-pointer update."""

    attempt_id: str
    retain_until: datetime
    manifest_sha256: str
    objects: tuple[SealedBlobObject, ...]


def _manifest(artifacts: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, body in sorted(artifacts.items()):
        # Length framing avoids ambiguous joins without a JSON serialization contract.
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(4, "big") + encoded)
        digest.update(len(body).to_bytes(8, "big") + hashlib.sha256(body).digest())
    return digest.hexdigest()


def _blob_name(attempt_id: str, logical_name: str) -> str:
    return f"attempts/{attempt_id}/{hashlib.sha256(logical_name.encode('ascii')).hexdigest()}.blob"


class ImmutableBlobArtifactStore:
    """Standalone bounded Blob SDK adapter; no broker transport or permission proof."""

    def __init__(
        self,
        target: ImmutableBlobTarget,
        credential: TokenCredential,
        *,
        service_client: BlobServiceClient | None = None,
        management_reader: _ManagementReader | None = None,
    ) -> None:
        _require(
            callable(getattr(credential, "get_token", None)),
            "token_credential_required",
        )
        self.target = target
        self._service = service_client or BlobServiceClient(
            target.account_url,
            credential=credential,
            max_single_put_size=_MAX_OBJECT_BYTES,
            retry_total=0,
            connection_timeout=10,
            read_timeout=30,
        )
        _require(
            self._service.url.rstrip("/") == target.account_url, "sdk_target_mismatch"
        )
        self._management = management_reader or AzureBlobManagementReader(credential)
        self._owns_management = management_reader is None
        self._owns_service = service_client is None
        self._attempts: dict[str, tuple[str, datetime] | None] = {}
        self._verified: dict[str, dict[str, SealedBlobObject]] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        """Close owned SDK/ARM transports; injected clients remain caller-owned."""
        if self._owns_service:
            self._service.close()
        if self._owns_management and isinstance(
            self._management, AzureBlobManagementReader
        ):
            self._management.close()

    def begin_attempt(self) -> str:
        """Allocate a process-owned UUID namespace; no caller-supplied attempt roots."""
        with self._lock:
            attempt_id = str(uuid4())
            _require(attempt_id not in self._attempts, "attempt_collision")
            self._attempts[attempt_id] = None
            self._verified[attempt_id] = {}
            return attempt_id

    def _policy(self) -> _Policy:
        account = self._management.get(self.target.account_id)
        service_id = f"{self.target.account_id}/blobServices/default"
        service = self._management.get(service_id)
        policy_id = f"{self.target.container_id}/immutabilityPolicies/default"
        policy = self._management.get(policy_id)
        _require(
            account.body.get("id") == self.target.account_id,
            "account_identity_mismatch",
        )
        _require(service.body.get("id") == service_id, "service_identity_mismatch")
        _require(policy.body.get("id") == policy_id, "policy_identity_mismatch")
        properties = account.body.get("properties")
        svc_properties = service.body.get("properties")
        policy_properties = policy.body.get("properties")
        _require(
            isinstance(properties, Mapping)
            and isinstance(svc_properties, Mapping)
            and isinstance(policy_properties, Mapping),
            "provider_properties_missing",
        )
        if not (
            isinstance(properties, Mapping)
            and isinstance(svc_properties, Mapping)
            and isinstance(policy_properties, Mapping)
        ):
            raise ArtifactVerificationError("provider_properties_missing")
        endpoints = properties.get("primaryEndpoints")
        _require(
            account.body.get("kind") == "StorageV2"
            and properties.get("isHnsEnabled") is False
            and properties.get("allowSharedKeyAccess") is False
            and properties.get("allowBlobPublicAccess") is False
            and isinstance(endpoints, Mapping)
            and endpoints.get("blob") == f"{self.target.account_url}/",
            "account_configuration_unverified",
        )
        _require(
            svc_properties.get("isVersioningEnabled") is False, "versioning_unverified"
        )
        _require(
            policy_properties.get("state") == "Locked"
            and policy_properties.get("allowProtectedAppendWrites") is False
            and policy_properties.get("allowProtectedAppendWritesAll") is False,
            "immutable_policy_unverified",
        )
        days = policy_properties.get("immutabilityPeriodSinceCreationInDays")
        _require(type(days) is int and 1 <= days <= 146000, "retention_unverified")
        if not isinstance(days, int):
            raise ArtifactVerificationError("retention_unverified")
        times = tuple(
            _aware(item.server_time, "provider_date_invalid")
            for item in (account, service, policy)
        )
        _require(
            max(times) - min(times) <= timedelta(minutes=2), "provider_reads_incoherent"
        )
        return _Policy(policy_id, _etag(policy.body.get("etag")), days, max(times))

    def _client(self, blob_name: str) -> BlobClient:
        client = self._service.get_blob_client(self.target.container_name, blob_name)
        _require(
            client.account_name
            == self.target.account_url.split("//", 1)[1].split(".")[0]
            and client.container_name == self.target.container_name
            and client.blob_name == blob_name
            and client.url
            == f"{self.target.account_url}/{self.target.container_name}/{blob_name}",
            "blob_client_identity_mismatch",
        )
        return client

    def _verified_object(
        self,
        attempt_id: str,
        logical_name: str,
        expected: bytes | SealedBlobObject,
        retain_until: datetime,
    ) -> tuple[SealedBlobObject, bytes]:
        policy = self._policy()
        name = _blob_name(attempt_id, logical_name)
        client = self._client(name)
        response_headers: dict[str, str] = {}

        def capture(response: object) -> None:
            http_response = getattr(response, "http_response", None)
            headers = getattr(http_response, "headers", {})
            response_headers.update(
                {key.lower(): value for key, value in headers.items()}
            )

        properties = client.get_blob_properties(raw_response_hook=capture)
        now = _server_date(response_headers.get("date"))
        created = _aware(properties.creation_time, "blob_creation_time_invalid")
        modified = _aware(properties.last_modified, "blob_modified_time_invalid")
        _require(
            now >= policy.server_time - timedelta(minutes=2)
            and now <= policy.server_time + timedelta(minutes=2)
            and created <= modified <= now,
            "blob_time_incoherent",
        )
        _require(
            properties.blob_type == BlobType.BLOCKBLOB
            and properties.version_id is None
            and properties.snapshot is None
            and properties.server_encrypted is True
            and properties.copy.id is None
            and properties.metadata == {}
            and properties.content_settings.content_encoding is None,
            "blob_properties_unverified",
        )
        size = properties.size
        _require(
            type(size) is int and 0 <= size <= _MAX_OBJECT_BYTES, "blob_size_invalid"
        )
        etag = _etag(properties.etag)
        try:
            retained_until = created + timedelta(days=policy.retention_days)
        except OverflowError:
            raise ArtifactVerificationError("retention_overflow") from None
        _require(
            retain_until > max(now, policy.server_time), "retention_horizon_expired"
        )
        _require(retained_until >= retain_until, "retention_horizon_insufficient")
        if isinstance(expected, SealedBlobObject):
            _require(
                expected.etag == etag
                and expected.size == size
                and expected.creation_time == created
                and expected.retained_until <= retained_until,
                "sealed_properties_mismatch",
            )
        else:
            _require(size == len(expected), "uploaded_size_mismatch")
        body = client.download_blob(
            etag=etag, match_condition=MatchConditions.IfNotModified, max_concurrency=1
        ).readall()
        _require(isinstance(body, bytes) and len(body) == size, "readback_incomplete")
        digest = hashlib.sha256(body).hexdigest()
        _require(
            (digest == expected.sha256)
            if isinstance(expected, SealedBlobObject)
            else body == expected,
            "readback_content_mismatch",
        )
        # Recheck the ETag after the conditional read and the actual provider policy.
        after = client.get_blob_properties()
        _require(
            after.etag == etag and after.version_id is None,
            "readback_properties_changed",
        )
        latest = self._policy()
        _require(
            latest.retention_days >= policy.retention_days
            and retain_until > latest.server_time,
            "policy_changed_during_verification",
        )
        return (
            SealedBlobObject(
                self.target.account_id,
                self.target.account_url,
                self.target.container_name,
                attempt_id,
                logical_name,
                name,
                etag,
                size,
                digest,
                created,
                now,
                retained_until,
                policy.resource_id,
                policy.etag,
                policy.retention_days,
            ),
            body,
        )

    def upload_attempt(
        self,
        attempt_id: str,
        artifacts: Mapping[str, bytes],
        *,
        retain_until: datetime,
    ) -> SealedBlobInventory:
        """Create/verify the exact bound product set; retries cannot change its manifest."""
        horizon = _aware(retain_until, "retention_horizon_invalid")
        _require(isinstance(artifacts, Mapping), "artifact_manifest_invalid")
        bodies = dict(artifacts)
        _require(1 <= len(bodies) <= _MAX_OBJECTS, "artifact_count_invalid")
        _require(
            all(
                isinstance(name, str)
                and bool(re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", name))
                and isinstance(body, bytes)
                and len(body) <= _MAX_OBJECT_BYTES
                for name, body in bodies.items()
            ),
            "artifact_manifest_invalid",
        )
        _require(
            sum(map(len, bodies.values())) <= _MAX_ATTEMPT_BYTES, "attempt_size_invalid"
        )
        manifest = _manifest(bodies)
        with self._lock:
            _require(attempt_id in self._attempts, "attempt_not_owned")
            binding = (manifest, horizon)
            _require(
                self._attempts[attempt_id] in (None, binding),
                "attempt_binding_mismatch",
            )
            self._attempts[attempt_id] = binding
        try:
            for logical_name, body in sorted(bodies.items()):
                with self._lock:
                    prior = self._verified[attempt_id].get(logical_name)
                if prior is not None:
                    self._verified_object(attempt_id, logical_name, prior, horizon)
                    continue
                policy = self._policy()
                _require(horizon > policy.server_time, "retention_horizon_expired")
                _require(
                    policy.server_time + timedelta(days=policy.retention_days)
                    >= horizon,
                    "retention_horizon_insufficient",
                )
                client = self._client(_blob_name(attempt_id, logical_name))
                try:
                    client.upload_blob(
                        body,
                        blob_type=BlobType.BLOCKBLOB,
                        length=len(body),
                        overwrite=False,
                        etag="*",
                        match_condition=MatchConditions.IfMissing,
                        validate_content=True,
                        max_concurrency=1,
                        metadata={},
                    )
                except (ResourceExistsError, ResourceModifiedError):
                    # Existing content is accepted only through the same full readback below.
                    pass
                verified = self._verified_object(
                    attempt_id, logical_name, body, horizon
                )[0]
                with self._lock:
                    concurrent = self._verified[attempt_id].setdefault(
                        logical_name, verified
                    )
                _require(
                    concurrent.etag == verified.etag
                    and concurrent.creation_time == verified.creation_time,
                    "concurrent_object_mismatch",
                )
            objects = tuple(
                self._verified_object(
                    attempt_id, name, self._verified[attempt_id][name], horizon
                )[0]
                for name in sorted(bodies)
            )
            latest = self._policy()
            _require(horizon > latest.server_time, "retention_horizon_expired")
            _require(
                all(
                    latest.retention_days >= item.policy_retention_days
                    for item in objects
                ),
                "policy_changed_during_verification",
            )
            return SealedBlobInventory(attempt_id, horizon, manifest, objects)
        except (AzureError, ValueError):
            raise ArtifactVerificationError("blob_provider_operation_failed") from None

    def read_object(self, sealed: SealedBlobObject) -> bytes:
        """Reverify exact target/name/ETag/bytes and current policy; never trust a seal boolean."""
        _require(
            sealed.account_id == self.target.account_id
            and sealed.account_url == self.target.account_url
            and sealed.container_name == self.target.container_name
            and bool(re.fullmatch(_UUID, sealed.attempt_id))
            and bool(re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", sealed.logical_name))
            and sealed.blob_name == _blob_name(sealed.attempt_id, sealed.logical_name)
            and sealed.policy_id
            == f"{self.target.container_id}/immutabilityPolicies/default"
            and sealed.version_id is None,
            "sealed_identity_mismatch",
        )
        try:
            return self._verified_object(
                sealed.attempt_id,
                sealed.logical_name,
                sealed,
                _aware(sealed.retained_until, "sealed_retention_invalid"),
            )[1]
        except (AzureError, ValueError):
            raise ArtifactVerificationError("blob_provider_operation_failed") from None
