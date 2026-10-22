"""Bounded, single-shot Fabric graph refresh chained after verified publication."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

import httpx

from .fabric_client import TokenCredential

_ORIGIN = "https://api.fabric.microsoft.com/v1"
_SCOPE = "https://api.fabric.microsoft.com/.default"
_TERMINAL_FAILURE = frozenset({"Failed", "Cancelled", "Deduped"})
_MAX_RETRY_AFTER = 30.0
_STATE = "graph-refresh/state.json"


class StateStore(Protocol):
    def read(self, name: str) -> dict[str, Any]: ...

    def write(
        self, name: str, payload: dict[str, Any], *, expected_revision: int
    ) -> None: ...


class GraphRefreshError(RuntimeError):
    """Refresh failed; messages never include tokens or service response text."""


class GraphRefreshAmbiguousError(GraphRefreshError):
    """A refresh may have started; operator review is required before another."""


class GraphRefresher:
    """Request one refreshGraph run and poll it with a finite deadline.

    The POST is never retried. An intent record is persisted before the POST and
    an outcome record after; a leftover intent blocks later refreshes until an
    operator reviews it. Callers must only invoke this after a verified
    successful publication.
    """

    def __init__(
        self,
        credential: TokenCredential,
        *,
        workspace_id: str,
        graph_model_id: str,
        state_store: StateStore,
        http_client: httpx.Client,
        timeout_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3_300
        ):
            raise ValueError("Graph refresh timeout must be finite and within 3300 seconds")
        self._workspace = str(UUID(workspace_id))
        self._graph = str(UUID(graph_model_id))
        self._url = (
            f"{_ORIGIN}/workspaces/{self._workspace}/graphModels/{self._graph}"
            "/jobs/refreshGraph/instances"
        )
        self._credential = credential
        self._http = http_client
        self._store = state_store
        self._timeout = timeout_seconds
        self._clock = clock
        self._sleep = sleep

    def refresh(self, *, source_run_id: str) -> dict[str, object]:
        """Run one refresh; return the persisted outcome or raise explicitly."""
        if self._store.read(_STATE).get("phase") == "requested":
            raise GraphRefreshAmbiguousError("graph_refresh_unresolved_intent")
        deadline = self._clock() + self._timeout
        started = {"sourceRunId": source_run_id, "graphModelId": self._graph}
        self._record({**started, "phase": "requested", "at": time.time()})
        try:
            response = self._http.post(
                self._url,
                headers=self._headers(),
                timeout=self._remaining(deadline),
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise GraphRefreshAmbiguousError("graph_refresh_post_ambiguous") from None
        if response.status_code != 202:
            self._record({**started, "phase": "rejected", "httpStatus": response.status_code,
                          "at": time.time()})
            raise GraphRefreshError(f"graph_refresh_http_status:{response.status_code}")
        location = response.headers.get("Location", "")
        if not location.startswith(_ORIGIN + "/") or self._graph not in location:
            raise GraphRefreshAmbiguousError("graph_refresh_missing_location")
        retry = self._retry_after(response)
        status = "Unknown"
        while True:
            self._sleep(min(retry, self._remaining(deadline)))
            try:
                poll = self._http.get(
                    location,
                    headers=self._headers(),
                    timeout=self._remaining(deadline),
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                raise GraphRefreshAmbiguousError("graph_refresh_poll_failure") from None
            if poll.status_code != 200:
                raise GraphRefreshAmbiguousError(f"graph_refresh_poll_status:{poll.status_code}")
            try:
                body = poll.json()
                status = str(body.get("status"))
            except (ValueError, AttributeError):
                raise GraphRefreshAmbiguousError("graph_refresh_poll_invalid") from None
            if status == "Completed":
                result = {**started, "phase": "completed", "status": "Completed",
                          "jobInstanceId": body.get("id"), "at": time.time()}
                self._record(result)
                return result
            if status in _TERMINAL_FAILURE:
                self._record({**started, "phase": "failed", "status": status, "at": time.time()})
                raise GraphRefreshError(f"graph_refresh_{status.lower()}")
            retry = self._retry_after(poll)

    def _headers(self) -> dict[str, str]:
        token = self._credential.get_token(_SCOPE).token
        return {
            "Authorization": f"Bearer {token}",
            "x-ms-fabric-skill": "fabriciq-ontology-cli",
            "Accept": "application/json",
        }

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise GraphRefreshAmbiguousError("graph_refresh_deadline_exceeded")
        return remaining

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        try:
            value = float(response.headers.get("Retry-After", "5"))
        except ValueError:
            return 5.0
        return min(max(value, 1.0), _MAX_RETRY_AFTER) if math.isfinite(value) else 5.0

    def _record(self, payload: dict[str, Any]) -> None:
        revision = int(self._store.read(_STATE).get("revision") or 0)
        self._store.write(
            _STATE, {**payload, "revision": revision + 1}, expected_revision=revision
        )
