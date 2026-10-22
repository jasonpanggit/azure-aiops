"""Bounded, single-shot Fabric graph refresh chained after verified publication."""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from storage.onelake_documents import DocumentConflictError

from .fabric_client import TokenCredential

_ORIGIN = "https://api.fabric.microsoft.com/v1"
_SCOPE = "https://api.fabric.microsoft.com/.default"
_STATE = "graph-refresh/state.json"
_TERMINAL_FAILURE = frozenset({"Failed", "Cancelled", "Deduped"})
_DEFAULT_RETRY_AFTER = 5.0
# Definitive pre-acceptance rejections; every other non-202 may have started a job.
_REJECTED = frozenset({400, 401, 403, 404, 409, 429})


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

    The POST is never retried. A "requested" record is committed with CAS from
    the exact observed revision before the POST, and the terminal record only
    replaces that same record (same owner and revision). Any leftover
    "requested" state blocks later refreshes until an operator reviews it.
    A validated accepted job identity is saved before polling; it remains
    requested, not completed, if polling or the finite deadline fails.
    ``guard`` (e.g. the source lease check) runs before the POST, around every
    poll, and before every state record, and must raise when ownership is lost.
    """

    def __init__(
        self,
        credential: TokenCredential,
        *,
        workspace_id: str,
        graph_model_id: str,
        state_store: StateStore,
        http_client: httpx.Client,
        guard: Callable[[], None] = lambda: None,
        timeout_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3_300
        ):
            raise ValueError("Graph refresh timeout must be finite and within 3300 seconds")
        self._workspace = str(uuid.UUID(workspace_id))
        self._graph = str(uuid.UUID(graph_model_id))
        self._url = (
            f"{_ORIGIN}/workspaces/{self._workspace}/graphModels/{self._graph}"
            "/jobs/refreshGraph/instances"
        )
        self._job_prefix = (
            f"/v1/workspaces/{self._workspace}/items/{self._graph}/jobs/instances/"
        )
        self._credential = credential
        self._http = http_client
        self._store = state_store
        self._guard = guard
        self._timeout = timeout_seconds
        self._clock = clock
        self._sleep = sleep
        self._wall = wall_clock
        self._owner = uuid.uuid4().hex
        self._revision = 0

    def refresh(self, *, source_run_id: str) -> dict[str, Any]:
        """Run one refresh; return the persisted outcome or raise explicitly."""
        deadline = self._clock() + self._timeout
        self._guard()
        current = self._store.read(_STATE)
        if current.get("phase") == "requested":
            raise GraphRefreshAmbiguousError("graph_refresh_unresolved_intent")
        started = {"sourceRunId": source_run_id, "graphModelId": self._graph,
                   "workspaceId": self._workspace}
        self._revision = int(current.get("revision") or 0)
        self._commit({**started, "phase": "requested"}, expect_requested=False)
        try:
            headers = self._headers()
            self._guard()
            response = self._http.post(
                self._url,
                headers=headers,
                timeout=self._remaining(deadline),
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise GraphRefreshAmbiguousError("graph_refresh_post_ambiguous") from None
        if response.status_code != 202:
            if response.status_code in _REJECTED:
                self._commit({**started, "phase": "rejected",
                              "httpStatus": response.status_code})
                raise GraphRefreshError(f"graph_refresh_http_status:{response.status_code}")
            raise GraphRefreshAmbiguousError(
                f"graph_refresh_post_ambiguous_status:{response.status_code}"
            )
        location = response.headers.get("Location", "")
        job_id = self._job_id(location)
        started = {**started, "jobInstanceId": job_id}
        self._commit({**started, "phase": "requested"})
        retry = self._retry_after(response)
        while True:
            self._guard()
            if retry > self._remaining(deadline):
                raise GraphRefreshAmbiguousError("graph_refresh_deadline_exceeded")
            self._sleep(retry)
            self._guard()
            try:
                headers = self._headers()
                poll = self._http.get(
                    location,
                    headers=headers,
                    timeout=self._remaining(deadline),
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                raise GraphRefreshAmbiguousError("graph_refresh_poll_failure") from None
            if poll.status_code != 200:
                raise GraphRefreshAmbiguousError(f"graph_refresh_poll_status:{poll.status_code}")
            try:
                body = poll.json()
                status = body["status"]
                observed_id = body.get("id")
            except (ValueError, KeyError, TypeError, AttributeError):
                raise GraphRefreshAmbiguousError("graph_refresh_poll_invalid") from None
            if observed_id is not None and observed_id != job_id:
                raise GraphRefreshAmbiguousError("graph_refresh_job_mismatch")
            self._remaining(deadline)
            if status == "Completed":
                if observed_id != job_id or body.get("failureReason"):
                    raise GraphRefreshAmbiguousError("graph_refresh_completion_unverified")
                self._guard()
                return self._commit(
                    {**started, "phase": "completed", "status": "Completed",
                     "jobInstanceId": job_id}
                )
            if status in _TERMINAL_FAILURE:
                self._commit({**started, "phase": "failed", "status": status})
                raise GraphRefreshError(f"graph_refresh_{str(status).lower()}")
            retry = self._retry_after(poll)

    def _commit(self, payload: dict[str, Any], *, expect_requested: bool = True) -> dict[str, Any]:
        self._guard()
        if expect_requested:
            current = self._store.read(_STATE)
            if (
                current.get("phase") != "requested"
                or current.get("owner") != self._owner
                or int(current.get("revision") or 0) != self._revision
            ):
                raise GraphRefreshAmbiguousError("graph_refresh_state_superseded")
        record = {**payload, "owner": self._owner, "at": self._wall(),
                  "revision": self._revision + 1}
        try:
            self._store.write(_STATE, record, expected_revision=self._revision)
        except DocumentConflictError:
            raise GraphRefreshAmbiguousError("graph_refresh_state_conflict") from None
        self._revision += 1
        self._guard()
        return record

    def _job_id(self, location: str) -> str:
        parsed = urlparse(location)
        if (
            f"{parsed.scheme}://{parsed.netloc}/v1" != _ORIGIN
            or not parsed.path.startswith(self._job_prefix)
        ):
            raise GraphRefreshAmbiguousError("graph_refresh_invalid_location")
        try:
            return str(uuid.UUID(parsed.path[len(self._job_prefix):]))
        except ValueError:
            raise GraphRefreshAmbiguousError("graph_refresh_invalid_location") from None

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

    def _retry_after(self, response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After", "").strip()
        try:
            value = float(raw)
        except ValueError:
            try:
                target = parsedate_to_datetime(raw)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                value = target.timestamp() - datetime.fromtimestamp(self._wall(), UTC).timestamp()
            except (TypeError, ValueError, IndexError):
                return _DEFAULT_RETRY_AFTER
        return max(value, 1.0) if math.isfinite(value) else _DEFAULT_RETRY_AFTER
