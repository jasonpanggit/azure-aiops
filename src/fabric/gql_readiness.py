"""Read-only GQL endpoint readiness; not graph freshness or schema admission."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from uuid import UUID

import httpx

from .fabric_client import TokenCredential

_ORIGIN = "https://api.fabric.microsoft.com/v1"
_QUERY = "RETURN 1 AS probe LIMIT 1"
_MAX_RESPONSE_BYTES = 65_536


class GqlReadinessError(RuntimeError):
    """A bounded probe failed; the reason never includes tokens or service text."""


class GqlReadinessProbe:
    """Probe a server-selected graph without creating, refreshing or editing it.

    No query or destination is accepted at invocation. A successful probe proves
    endpoint queryability only, not data membership, freshness or authorization
    for another consumer. This class is not registered in application runtime.
    """

    def __init__(
        self,
        credential: TokenCredential,
        *,
        workspace_id: str,
        graph_model_id: str,
        http_client: httpx.Client,
        timeout_seconds: float = 30,
        max_requests: int = 4,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("GQL readiness timeout must be finite and within 60 seconds")
        if type(max_requests) is not int or not 1 <= max_requests <= 10:
            raise ValueError("GQL readiness request budget must be within 1..10")
        workspace, graph = str(UUID(workspace_id)), str(UUID(graph_model_id))
        self._url = f"{_ORIGIN}/workspaces/{workspace}/graphModels/{graph}/executeQuery"
        self._credential = credential
        self._http = http_client
        self._timeout = timeout_seconds
        self._max_requests = max_requests
        self._clock = clock
        self._sleep = sleep

    def check(self) -> None:
        """Require a complete, warning-free constant result or raise explicitly.

        Continuations reuse the exact query and destination. Transport failures
        are not retried. Deadline checks include credential acquisition and the
        completed body; HTTP timeouts also bound individual network phases.
        """
        deadline = self._clock() + self._timeout
        continuation: str | None = None
        total_bytes = 0
        for _ in range(self._max_requests):
            self._remaining(deadline)
            token = self._credential.get_token(
                "https://api.fabric.microsoft.com/.default"
            ).token
            params = {"beta": "true"}
            if continuation is not None:
                params["continuationToken"] = continuation
            try:
                with self._http.stream(
                    "POST",
                    self._url,
                    params=params,
                    json={"query": _QUERY},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "x-ms-fabric-skill": "fabriciq-ontology-cli",
                        "Accept": "application/json",
                    },
                    timeout=self._remaining(deadline),
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise GqlReadinessError(f"gql_http_status:{response.status_code}")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        self._remaining(deadline)
                        total_bytes += len(chunk)
                        if total_bytes > _MAX_RESPONSE_BYTES:
                            raise GqlReadinessError("gql_response_too_large")
                        body.extend(chunk)
                self._remaining(deadline)
            except httpx.HTTPError:
                raise GqlReadinessError("gql_transport_failure") from None
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                raise GqlReadinessError("gql_invalid_json") from None
            continuation = self._validate(payload)
            self._remaining(deadline)
            if continuation is None:
                return
            delay = min(1.0, self._remaining(deadline))
            self._sleep(delay)
        raise GqlReadinessError("gql_continuation_budget_exhausted")

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise GqlReadinessError("gql_deadline_exceeded")
        return remaining

    @staticmethod
    def _validate(payload: object) -> str | None:
        if not isinstance(payload, Mapping):
            raise GqlReadinessError("gql_invalid_response")
        status, result = payload.get("status"), payload.get("result")
        if not isinstance(status, Mapping) or not isinstance(result, Mapping):
            raise GqlReadinessError("gql_invalid_response")
        if payload.get("errors") or payload.get("additionalStatuses") or status.get("cause"):
            raise GqlReadinessError("gql_warning_or_cause")
        if result.get("kind") != "TABLE":
            raise GqlReadinessError("gql_invalid_result")
        code = status.get("code")
        if code == "02000":
            token = result.get("nextPage")
            if (
                not isinstance(token, str)
                or not token
                or len(token) > 8_192
                or result.get("data") != []
                or not isinstance(result.get("columns"), list)
            ):
                raise GqlReadinessError("gql_incomplete_result")
            return token
        if code != "00000":
            raise GqlReadinessError("gql_execution_failed")
        if "nextPage" in result:
            raise GqlReadinessError("gql_incomplete_result")
        columns, rows = result.get("columns"), result.get("data")
        if (
            not isinstance(columns, list)
            or len(columns) != 1
            or not isinstance(columns[0], Mapping)
            or columns[0].get("name") != "probe"
            or columns[0].get("gqlType") != "INT64"
            or not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], Mapping)
            or set(rows[0]) != {"probe"}
            or type(rows[0]["probe"]) is not int
            or rows[0]["probe"] != 1
        ):
            raise GqlReadinessError("gql_unexpected_probe_result")
        return None
