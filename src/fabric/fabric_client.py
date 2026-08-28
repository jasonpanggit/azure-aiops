from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar, Protocol

import httpx

UTC = UTC


class TokenCredential(Protocol):
    def get_token(self, *scopes: str): ...


class FabricClient:
    SCOPE = "https://api.fabric.microsoft.com/.default"
    TRANSIENT_STATUS: ClassVar[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
    #: Long-running Fabric item operations (e.g. creating an Ontology item)
    #: return a 202 Location on a regional Power BI/Fabric backend cluster
    #: (e.g. "wabi-west-us3-a-primary-redirect.analysis.windows.net"), not on
    #: api.fabric.microsoft.com itself. Trust that suffix in addition to the
    #: configured API origin so polling those URLs isn't rejected.
    TRUSTED_HOST_SUFFIXES: ClassVar[tuple[str, ...]] = (".analysis.windows.net",)

    def __init__(
        self,
        credential: TokenCredential,
        *,
        base_url: str = "https://api.fabric.microsoft.com/v1",
        http_client: httpx.Client | None = None,
        max_attempts: int = 5,
        timeout_seconds: float = 60,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.credential = credential
        self.base_url = base_url.rstrip("/")
        self._base = httpx.URL(self.base_url)
        if self._base.scheme != "https" or not self._base.host:
            raise ValueError("Fabric base_url must use a trusted HTTPS Fabric origin")
        self._origin = self._url_origin(self._base)
        self.http = http_client or httpx.Client(timeout=timeout_seconds)
        self.max_attempts = max_attempts
        self.sleep = sleep

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        json_body: object | None = None,
        wait_for_completion: bool = True,
    ) -> dict[str, Any]:
        url = self._trusted_url(path)
        response = self._send(
            method,
            url,
            params=params,
            json_body=json_body,
            request_id=str(uuid.uuid4()),
        )
        if response.status_code == 202 and wait_for_completion:
            location = response.headers.get("Location")
            if not location:
                raise RuntimeError("Fabric returned 202 without an operation Location header")
            return self._wait_for_operation(location, response.headers.get("Retry-After"))
        return self._json(response)

    def iter_items(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> Iterator[dict[str, Any]]:
        base_path = path
        query: Mapping[str, object] | None = dict(params or {})
        next_path = path
        while True:
            page = self.request("GET", next_path, params=query)
            # Most Fabric list endpoints paginate under "value", but some
            # (e.g. GET .../lakehouses/{id}/tables) use "data" instead. Accept
            # either so pagination doesn't silently yield zero items.
            items = page.get("value")
            if items is None:
                items = page.get("data")
            for item in items or []:
                if isinstance(item, dict):
                    yield item
            token = page.get("continuationToken")
            continuation_uri = page.get("continuationUri")
            if continuation_uri:
                # continuationUri is a fully-formed absolute URL that already
                # embeds its own continuationToken query string. Pass
                # params=None (not {}) -- httpx replaces the URL's existing
                # query string with whatever `params` is given, even an empty
                # dict, which would strip the embedded token and re-fetch the
                # same page forever.
                next_path = str(continuation_uri)
                query = None
            elif token:
                # Always paginate from the original path when following a
                # bare continuationToken. Reusing a previous continuationUri
                # as next_path here would append a second, conflicting
                # continuationToken query param and cause the server to
                # repeat/loop pages.
                next_path = base_path
                query = {"continuationToken": token}
            else:
                return

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        json_body: object | None = None,
        request_id: str | None = None,
    ) -> httpx.Response:
        url = self._trusted_url(url)
        last_response: httpx.Response | None = None
        stable_request_id = request_id or str(uuid.uuid4())
        for attempt in range(1, self.max_attempts + 1):
            token = self.credential.get_token(self.SCOPE).token
            try:
                response = self.http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    follow_redirects=False,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "x-ms-client-request-id": stable_request_id,
                    },
                )
            except httpx.TransportError:
                if attempt == self.max_attempts:
                    raise
                self.sleep(min(2 ** (attempt - 1), 30))
                continue
            last_response = response
            if response.status_code not in self.TRANSIENT_STATUS or attempt == self.max_attempts:
                response.raise_for_status()
                return response
            delay = _retry_delay(response.headers.get("Retry-After"), attempt)
            self.sleep(max(0, delay))
        if last_response is None:
            raise RuntimeError("Fabric request retry loop made no attempts")
        last_response.raise_for_status()
        return last_response

    def _wait_for_operation(self, location: str, retry_after: str | None) -> dict[str, Any]:
        location = self._trusted_url(location)
        delay = float(retry_after) if retry_after else 1.0
        for _ in range(120):
            self.sleep(max(0, delay))
            response = self._send("GET", location)
            payload = self._json(response)
            status = str(payload.get("status") or "").lower()
            if status in {"succeeded", "completed"}:
                resource_location = response.headers.get("Location") or payload.get("resourceLocation")
                return (
                    self.request("GET", str(resource_location))
                    if resource_location
                    else payload
                )
            if status in {"failed", "cancelled"}:
                raise RuntimeError(f"Fabric operation failed: {payload}")
            delay = float(response.headers.get("Retry-After") or delay)
        raise TimeoutError(f"Fabric operation did not complete: {location}")

    def _trusted_url(self, value: str) -> str:
        candidate = httpx.URL(value)
        if not candidate.is_absolute_url:
            candidate = httpx.URL(f"{self.base_url}/{value.lstrip('/')}")
        host = str(candidate.host or "").casefold()
        is_trusted_origin = self._url_origin(candidate) == self._origin
        is_trusted_suffix = host.endswith(self.TRUSTED_HOST_SUFFIXES)
        if (
            candidate.scheme != "https"
            or not (is_trusted_origin or is_trusted_suffix)
            or candidate.username
            or candidate.password
        ):
            raise ValueError("Fabric URL must use the trusted HTTPS Fabric origin")
        return str(candidate)

    @staticmethod
    def _url_origin(url: httpx.URL) -> tuple[str, str, int]:
        port = url.port or (443 if url.scheme == "https" else 80)
        return url.scheme.casefold(), str(url.host or "").casefold(), port

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 204 or not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Fabric API returned a non-object JSON response")
        return payload


def _retry_delay(value: str | None, attempt: int) -> float:
    if not value:
        return float(min(2 ** (attempt - 1), 30))
    try:
        return max(0.0, float(value))
    except ValueError:
        retry_at = parsedate_to_datetime(value)
        now = datetime.now(UTC)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - now).total_seconds())
