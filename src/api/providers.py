"""Thread-safe lifecycle management for snapshot-backed API providers."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)

READY = "ready"
STALE = "stale"
PARTIAL = "partial"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"
DISABLED = "disabled"
LOADING = "loading"

_CACHE_KEY_UNAVAILABLE = object()


@dataclass(frozen=True)
class ProviderValue:
    """A loaded provider plus optional lifecycle metadata."""

    instance: Any
    freshness: str = ""
    ontology_version: str = ""
    state: str = READY
    degraded_reason: str = ""


@dataclass(frozen=True)
class ProviderSpec:
    """Factory definition for one runtime capability."""

    loader: Callable[[], Any | ProviderValue]
    configured: bool = True
    required: bool = True
    cache_key: Callable[[], Any] | None = None


@dataclass
class ProviderState:
    """Mutable internal state serialized by :class:`ProviderRuntime`."""

    name: str
    configured: bool
    required: bool
    state: str = LOADING
    loaded: bool = False
    freshness: str = ""
    ontology_version: str = ""
    loaded_at: str = ""
    last_attempt_at: str = ""
    last_success_at: str = ""
    degraded_reason: str = ""
    cache_key_stale: bool = False
    retry_attempts: int = 0
    next_retry_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the public, secret-free provider health contract."""
        return {
            "name": self.name,
            "configured": self.configured,
            "required": self.required,
            "state": self.state,
            "loaded": self.loaded,
            "freshness": self.freshness,
            "ontology_version": self.ontology_version,
            "loaded_at": self.loaded_at,
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "degraded_reason": self.degraded_reason,
            "cache_key_stale": self.cache_key_stale,
            "retry": {
                "attempts": self.retry_attempts,
                "next_retry_at": self.next_retry_at,
            },
        }


class ProviderUnavailableError(RuntimeError):
    """Raised when a configured capability has no safe provider to serve."""

    def __init__(self, name: str, state: ProviderState) -> None:
        self.name = name
        self.provider_state = state
        super().__init__(f"The {name} provider is {state.state}")


@dataclass
class ProviderRuntime:
    """Atomically refresh and serve the latest good provider set.

    Failed refreshes never replace a working provider. They mark it degraded and
    schedule a bounded retry, allowing requests to continue against the last
    published ontology snapshot while health accurately reports the failure.
    """

    specs: Mapping[str, ProviderSpec]
    metadata_loader: Callable[[], Mapping[str, Any]] | None = None
    refresh_interval_seconds: int = 30
    stale_after_hours: int = 24
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    monotonic: Callable[[], float] = time.monotonic
    _instances: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _states: dict[str, ProviderState] = field(default_factory=dict, init=False, repr=False)
    _cache_keys: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _metadata: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_refresh: float = field(default=float("-inf"), init=False, repr=False)
    # `_state_lock` only ever guards in-memory dict/attribute mutation, never
    # loader I/O, so `health()`/`get()` reads can never block behind a slow
    # (or NVD-rate-limited) provider loader. `_refresh_lock` is a separate,
    # non-reentrant lock that serializes actual refresh *execution* so two
    # concurrent callers (e.g. a probe and the background timer) don't run
    # loaders twice at once; it is acquired without blocking readers.
    _state_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _refresh_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.refresh_interval_seconds < 1:
            raise ValueError("Provider refresh interval must be positive")
        if self.stale_after_hours < 1:
            raise ValueError("Provider stale threshold must be positive")
        self._states = {
            name: ProviderState(
                name=name,
                configured=spec.configured,
                required=spec.required,
                state=LOADING if spec.configured else DISABLED,
            )
            for name, spec in self.specs.items()
        }

    def refresh(self, *, force: bool = False, blocking: bool = True) -> dict[str, Any]:
        """Refresh due providers and atomically retain every successful result.

        Provider loaders may perform slow, rate-limited network I/O (e.g. NVD
        CVE enrichment). Refreshes must never run on a request-serving thread
        that a Container Apps liveness/readiness probe is also waiting on, or
        a single slow/throttled loader can starve the probe past its timeout
        and get the whole container killed. `blocking=False` (used by
        `/health` and `/ready`) skips the refresh entirely when another
        refresh is already in flight, so probes always return immediately
        against the last known state instead of queueing behind it.
        """
        if not force and self.monotonic() - self._last_refresh < self.refresh_interval_seconds:
            return self.health(refresh=False)
        acquired = self._refresh_lock.acquire(blocking=blocking)
        if not acquired:
            return self.health(refresh=False)
        try:
            return self._refresh_locked(force=force)
        finally:
            self._refresh_lock.release()

    def _refresh_locked(self, *, force: bool) -> dict[str, Any]:
        # `_refresh_lock` (held by the caller) already prevents two refreshes
        # from running concurrently, so `_last_refresh`/looping here is safe
        # without `_state_lock`; that lock is only taken around the small
        # state-dict mutations below, never around `spec.loader()` I/O.
        now_mono = self.monotonic()
        if not force and now_mono - self._last_refresh < self.refresh_interval_seconds:
            return self.health(refresh=False)
        self._last_refresh = now_mono
        now = self.clock().astimezone(UTC)
        now_iso = _iso(now)

        for name, spec in self.specs.items():
            self._refresh_provider(name, spec, now=now, now_iso=now_iso, force=force)

        if self.metadata_loader is not None:
            try:
                metadata = dict(self.metadata_loader())
            except Exception:
                _LOGGER.exception("provider_metadata_refresh_failed")
                with self._state_lock:
                    self._metadata = {
                        **self._metadata,
                        "degraded_reason": "runtime metadata refresh failed",
                    }
            else:
                with self._state_lock:
                    self._metadata = metadata
        return self.health(refresh=False)

    def _refresh_provider(
        self,
        name: str,
        spec: ProviderSpec,
        *,
        now: datetime,
        now_iso: str,
        force: bool,
    ) -> None:
        state = self._states[name]
        if not spec.configured:
            with self._state_lock:
                state.state = DISABLED
            return
        if not force and state.next_retry_at:
            retry_at = _parse(state.next_retry_at)
            if retry_at is not None and now < retry_at:
                return

        cache_key_before = self._read_cache_key(name, spec)
        if cache_key_before is _CACHE_KEY_UNAVAILABLE:
            with self._state_lock:
                loaded = name in self._instances
            if loaded:
                _LOGGER.warning(
                    "provider_refresh_skipped_cache_key_unavailable provider=%s",
                    name,
                )
                return
        if not force and spec.cache_key is not None:
            with self._state_lock:
                unchanged = (
                    name in self._instances
                    and self._cache_keys.get(name) == cache_key_before
                )
                if unchanged:
                    state.cache_key_stale = False
            if unchanged:
                return
        with self._state_lock:
            state.last_attempt_at = now_iso
        try:
            raw = spec.loader()
            value = raw if isinstance(raw, ProviderValue) else ProviderValue(raw)
            if value.instance is None:
                with self._state_lock:
                    state.retry_attempts += 1
                    delay = min(2 ** min(state.retry_attempts, 8), 300)
                    state.next_retry_at = _iso(now + timedelta(seconds=delay))
                    state.loaded = name in self._instances
                    state.state = DEGRADED if state.loaded else UNAVAILABLE
                    state.degraded_reason = f"{name} has no published provider data"
                _LOGGER.warning(
                    "provider_loader_returned_empty provider=%s "
                    "(loader completed without raising but produced no instance; "
                    "check upstream fabric()/with_fabric() short-circuit conditions)",
                    name,
                )
                return
            freshness = value.freshness or _provider_freshness(value.instance)
            lifecycle = value.state if value.state in {READY, PARTIAL, STALE} else READY
            if lifecycle == READY and _is_stale(
                freshness, now=now, stale_after_hours=self.stale_after_hours
            ):
                lifecycle = STALE
            cache_key_after = self._read_cache_key(name, spec)
            if cache_key_after is _CACHE_KEY_UNAVAILABLE:
                with self._state_lock:
                    loaded = name in self._instances
                if loaded:
                    _LOGGER.warning(
                        "provider_publish_skipped_cache_key_unavailable provider=%s",
                        name,
                    )
                    return
            with self._state_lock:
                self._instances[name] = value.instance
                if spec.cache_key is not None:
                    if cache_key_before == cache_key_after:
                        self._cache_keys[name] = cache_key_after
                    else:
                        self._cache_keys.pop(name, None)
                state.state = lifecycle
                state.loaded = True
                state.freshness = freshness
                state.ontology_version = (
                    value.ontology_version or _provider_version(value.instance)
                )
                state.loaded_at = now_iso
                state.last_success_at = now_iso
                state.degraded_reason = value.degraded_reason
                state.cache_key_stale = False
                state.retry_attempts = 0
                state.next_retry_at = ""
        except Exception as exc:
            with self._state_lock:
                state.retry_attempts += 1
                delay = min(2 ** min(state.retry_attempts, 8), 300)
                state.next_retry_at = _iso(now + timedelta(seconds=delay))
                state.loaded = name in self._instances
                state.state = DEGRADED if state.loaded else UNAVAILABLE
                state.degraded_reason = (
                    f"{name} refresh failed ({exc.__class__.__name__})"
                )
                state.cache_key_stale = bool(
                    state.loaded
                    and spec.cache_key is not None
                    and cache_key_before is not _CACHE_KEY_UNAVAILABLE
                    and self._cache_keys.get(name) != cache_key_before
                )
            _LOGGER.exception("provider_refresh_failed provider=%s", name)

    @staticmethod
    def _read_cache_key(name: str, spec: ProviderSpec | None) -> Any:
        """Resolve a cache key without turning freshness I/O into an outage."""
        if spec is None or spec.cache_key is None:
            return None
        try:
            return spec.cache_key()
        except Exception:
            _LOGGER.warning(
                "provider_cache_key_unavailable provider=%s",
                name,
                exc_info=True,
            )
            return _CACHE_KEY_UNAVAILABLE

    def _refresh_changed_cache_key(self, name: str) -> None:
        spec = self.specs.get(name)
        if spec is None or spec.cache_key is None or not spec.configured:
            return
        current = self._read_cache_key(name, spec)
        if current is _CACHE_KEY_UNAVAILABLE:
            return
        now = self.clock().astimezone(UTC)
        with self._state_lock:
            loaded = name in self._instances
            unchanged = loaded and self._cache_keys.get(name) == current
            state = self._states[name]
            retry_at = _parse(state.next_retry_at)
            retry_pending = (
                loaded
                and state.cache_key_stale
                and retry_at is not None
                and now < retry_at
            )
            if loaded and not unchanged:
                state.cache_key_stale = True
        if not loaded or unchanged or retry_pending:
            return

        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            current = self._read_cache_key(name, spec)
            if current is _CACHE_KEY_UNAVAILABLE:
                return
            now = self.clock().astimezone(UTC)
            with self._state_lock:
                loaded = name in self._instances
                unchanged = loaded and self._cache_keys.get(name) == current
                state = self._states[name]
                retry_at = _parse(state.next_retry_at)
                retry_pending = (
                    loaded
                    and state.cache_key_stale
                    and retry_at is not None
                    and now < retry_at
                )
                if loaded and not unchanged:
                    state.cache_key_stale = True
            if not loaded or unchanged or retry_pending:
                return
            self._refresh_provider(
                name,
                spec,
                now=now,
                now_iso=_iso(now),
                force=True,
            )
        finally:
            self._refresh_lock.release()

    def get(self, name: str, *, optional: bool = False) -> Any:
        """Resolve the current provider instance from the last completed refresh.

        Never blocks a request thread behind loader I/O: the dedicated
        background timer thread (see `_start_background_refresh` in
        `api.app`) is the only caller that performs blocking refreshes.
        Here we opportunistically nudge a refresh with `blocking=False`
        (a no-op if the timer is already running or not yet due) purely so
        a request arriving right after startup does not need to wait a
        full `refresh_interval_seconds` for the timer's next tick, then
        immediately serve whatever the last completed refresh published.
        """
        self._refresh_changed_cache_key(name)
        self.refresh(blocking=False)
        # A revision can advance while the ordinary refresh is loading. Check
        # once more, but retain an explicitly degraded last-good instance when
        # the newer body cannot be loaded.
        self._refresh_changed_cache_key(name)
        spec = self.specs.get(name)
        current_cache_key = self._read_cache_key(name, spec)
        with self._state_lock:
            instance = self._instances.get(name)
            cache_key_matches = (
                spec is None
                or spec.cache_key is None
                or current_cache_key is _CACHE_KEY_UNAVAILABLE
                or self._cache_keys.get(name) == current_cache_key
            )
            state = self._states.get(name)
            serving_last_good = bool(
                state is not None
                and state.cache_key_stale
            )
            if instance is not None and (
                cache_key_matches or serving_last_good
            ):
                return instance
            if optional or state is None or not state.configured:
                return None
            raise ProviderUnavailableError(name, state)

    def health(self, *, refresh: bool = True, blocking: bool = True) -> dict[str, Any]:
        """Return aggregate readiness, ontology, freshness, and retry state."""
        if refresh:
            self.refresh(blocking=blocking)
        with self._state_lock:
            providers = {
                name: state.to_dict() for name, state in sorted(self._states.items())
            }
            required = [
                state
                for state in self._states.values()
                if state.required and state.configured
            ]
            unavailable = [
                state.name
                for state in required
                if state.state in {UNAVAILABLE, DEGRADED, LOADING}
            ]
            stale = [state.name for state in required if state.state == STALE]
            partial = [state.name for state in required if state.state == PARTIAL]
            readiness = (
                DEGRADED
                if unavailable
                else STALE
                if stale
                else PARTIAL
                if partial
                else READY
            )
            ontology_version = str(
                self._metadata.get("ontology_version")
                or next(
                    (
                        state.ontology_version
                        for state in self._states.values()
                        if state.ontology_version
                    ),
                    "",
                )
            )
            freshness = str(
                self._metadata.get("freshness")
                or next(
                    (
                        state.freshness
                        for state in self._states.values()
                        if state.freshness
                    ),
                    "",
                )
            )
            return {
                "readiness": readiness,
                "ontology_version": ontology_version,
                "freshness": freshness,
                "last_discovery_run": str(
                    self._metadata.get("last_discovery_run") or ""
                ),
                "last_ontology_publication": str(
                    self._metadata.get("last_ontology_publication") or ""
                ),
                "degraded_reason": str(
                    self._metadata.get("degraded_reason")
                    or (
                        "Unavailable providers: " + ", ".join(unavailable)
                        if unavailable
                        else ""
                    )
                ),
                "providers": providers,
            }

    def record_failure(self, name: str, error: Exception) -> None:
        """Mark a runtime call degraded without discarding its loaded provider."""
        with self._state_lock:
            state = self._states.get(name)
            if state is None:
                return
            now = self.clock().astimezone(UTC)
            state.retry_attempts += 1
            state.state = DEGRADED if state.loaded else UNAVAILABLE
            state.degraded_reason = (
                f"{name} runtime call failed ({error.__class__.__name__})"
            )
            state.next_retry_at = _iso(
                now + timedelta(seconds=min(2 ** min(state.retry_attempts, 8), 300))
            )


def _provider_freshness(instance: Any) -> str:
    return str(
        getattr(instance, "freshness", "")
        or getattr(getattr(instance, "snapshot", None), "observed_at", "")
        or ""
    )


def _provider_version(instance: Any) -> str:
    return str(getattr(instance, "knowledge_version", "") or "")


def _is_stale(value: str, *, now: datetime, stale_after_hours: int) -> bool:
    parsed = _parse(value)
    return parsed is not None and now - parsed > timedelta(hours=stale_after_hours)


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "DEGRADED",
    "DISABLED",
    "LOADING",
    "PARTIAL",
    "READY",
    "STALE",
    "UNAVAILABLE",
    "ProviderRuntime",
    "ProviderSpec",
    "ProviderState",
    "ProviderUnavailableError",
    "ProviderValue",
]
