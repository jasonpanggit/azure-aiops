"""Lifecycle candidate resolution and governed operator confirmation."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import httpx

from intelligence.lifecycle import EOLCatalog, LifecycleCatalogEntry

from .eol_repository import (
    CatalogRevisionConflict,
    CatalogSnapshot,
    DuplicateCatalogConfirmation,
    EOLCatalogRepository,
    LocalEOLCatalogRepository,
)

_LOGGER = logging.getLogger(__name__)
_DATE_RE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024
_MAX_CLAIM_CHARS = 4 * 1024
_MAX_REDIRECTS = 3
_CANDIDATE_SOURCES = frozenset({"endoflife.date", "official_vendor", "web_search"})
_OFFICIAL_DOMAINS = frozenset(
    {
        "learn.microsoft.com",
        "techcommunity.microsoft.com",
        "ubuntu.com",
        "www.ubuntu.com",
        "access.redhat.com",
        "debian.org",
        "www.debian.org",
        "kubernetes.io",
        "www.kubernetes.io",
    }
)


@dataclass(frozen=True)
class LifecycleCandidate:
    """One advisory answer with enough provenance for operator review."""

    candidate_id: str
    date: str
    source_kind: str
    citation: str
    retrieved_at: str
    extracted_claim: str
    confidence: float
    support_channel: str = "mainstream"

    def __post_init__(self) -> None:
        _iso_date(self.date, "candidate date")
        if self.source_kind not in _CANDIDATE_SOURCES:
            raise ValueError("Candidate source_kind is not supported")
        _https_url(
            self.citation,
            allow_endoflife=self.source_kind == "endoflife.date",
            allow_any_https=self.source_kind == "web_search",
        )
        if not _timestamp(self.retrieved_at):
            raise ValueError("Candidate retrieved_at must be an ISO timestamp")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Candidate confidence must be between 0 and 1")
        if self.support_channel not in {"mainstream", "extended"}:
            raise ValueError("Candidate support_channel must be mainstream or extended")
        _bounded_url(self.citation)
        if not 1 <= len(self.extracted_claim.strip()) <= _MAX_CLAIM_CHARS:
            raise ValueError(
                "Candidate extracted_claim must be between 1 and 4096 characters"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(
        cls,
        row: Mapping[str, Any],
        *,
        os_key: str = "",
        source_kind: str = "",
    ) -> LifecycleCandidate:
        source = str(row.get("source_kind") or source_kind).strip()
        citation = str(row.get("citation") or row.get("source_url") or "").strip()
        value = str(row.get("date") or row.get("eol_date") or "").strip()
        claim = str(row.get("extracted_claim") or row.get("claim") or "").strip()
        candidate_id = str(row.get("candidate_id") or "").strip()
        if not candidate_id:
            candidate_id = _candidate_id(os_key, source, value, citation, claim)
        return cls(
            candidate_id=candidate_id,
            date=value,
            source_kind=source,
            citation=citation,
            retrieved_at=str(row.get("retrieved_at") or "").strip(),
            extracted_claim=claim,
            confidence=float(row.get("confidence", 0)),
            support_channel=str(row.get("support_channel") or "mainstream").casefold(),
        )


@dataclass(frozen=True)
class LifecycleReviewResult:
    normalized_os_key: str
    os_name: str
    os_version: str
    status: str
    catalog_revision: int
    classification: dict[str, Any]
    candidates: tuple[LifecycleCandidate, ...] = ()
    source_failures: tuple[SourceFailure, ...] = ()
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        payload["source_failures"] = [
            failure.to_dict() for failure in self.source_failures
        ]
        return payload


@dataclass(frozen=True)
class SourceFailure:
    """A safe, typed explanation for one unavailable candidate source."""

    source_kind: str
    status: str
    code: str
    message: str

    def __post_init__(self) -> None:
        if self.source_kind not in _CANDIDATE_SOURCES:
            raise ValueError("Source failure source_kind is not supported")
        if self.status not in {"unavailable", "failed"}:
            raise ValueError("Source failure status is not supported")
        if not 1 <= len(self.code) <= 64 or not re.fullmatch(
            r"[a-z0-9_]+", self.code
        ):
            raise ValueError("Source failure code is not bounded")
        if not 1 <= len(self.message) <= 240:
            raise ValueError("Source failure message is not bounded")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateResolution:
    candidates: tuple[LifecycleCandidate, ...]
    source_failures: tuple[SourceFailure, ...]


class SourceAdapterError(RuntimeError):
    """Expected, operator-safe failure from a candidate source adapter."""

    def __init__(self, code: str, message: str, *, status: str = "failed") -> None:
        self.code = code
        self.status = status
        super().__init__(message)


class LifecycleSearchProvider(Protocol):
    """Server-side boundary for an approved web/LLM lifecycle provider."""

    def resolve(
        self, os_name: str, os_version: str
    ) -> Iterable[Mapping[str, Any]]: ...


class UnavailableLifecycleSearchProvider:
    """Safe default when no approved external lifecycle provider is configured."""

    def resolve(
        self, _os_name: str, _os_version: str
    ) -> Iterable[Mapping[str, Any]]:
        raise SourceAdapterError(
            "provider_not_configured",
            "External web or LLM lifecycle resolution is unavailable until an approved provider is configured.",
            status="unavailable",
        )


class ApprovedSearchApiLifecycleProvider:
    """Bounded adapter for a server-configured approved search API.

    The adapter deliberately sends only a normalized OS identity and a fixed
    lifecycle lookup operation. Browser input, inventory rows, scopes, and
    provider credentials never enter the request body.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        credential: str = "",
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 256_000,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes < 1024:
            raise ValueError("Lifecycle provider bounds must be positive")
        self.endpoint = _https_url(endpoint, allow_endoflife=False, allow_any_https=True)
        self.credential = credential.strip()
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def resolve(
        self, os_name: str, os_version: str
    ) -> Iterable[Mapping[str, Any]]:
        key = normalize_os_key(os_name, os_version)
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=self.timeout_seconds,
            read=self.timeout_seconds,
            write=self.timeout_seconds,
            pool=self.timeout_seconds,
        )
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.credential:
            headers["Authorization"] = f"Bearer {self.credential}"
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.post(
                    self.endpoint,
                    json={"operation": "lifecycle_lookup", "normalized_os_key": key},
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SourceAdapterError(
                "timeout", "Approved lifecycle provider request timed out.", status="unavailable"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise SourceAdapterError(
                "http_error",
                f"Approved lifecycle provider returned HTTP {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceAdapterError(
                "network_error",
                "Approved lifecycle provider request failed.",
                status="unavailable",
            ) from exc
        if len(response.content) > self.max_response_bytes:
            raise SourceAdapterError(
                "response_too_large",
                "Approved lifecycle provider response exceeded the byte limit.",
            )
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceAdapterError(
                "malformed_content", "Approved lifecycle provider returned malformed JSON."
            ) from exc
        rows = payload.get("candidates") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise SourceAdapterError(
                "malformed_content",
                "Approved lifecycle provider response must contain candidate objects.",
            )
        return tuple(dict(row) for row in rows)


class CandidateResolver:
    """Run all configured candidate sources without selecting a winner."""

    def __init__(
        self,
        *,
        endoflife_fetch: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None,
        official_vendor_fetch: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None,
        web_search_fetch: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        official_vendor_origins: Iterable[str] | None = None,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes < 1024:
            raise ValueError("Candidate resolver bounds must be positive")
        self.endoflife_fetch = endoflife_fetch or (
            lambda name, version: _fetch_endoflife(
                name,
                version,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
                allowed_origins=official_vendor_origins or _OFFICIAL_DOMAINS,
            )
        )
        self.official_vendor_fetch = official_vendor_fetch or (
            lambda name, version: _fetch_official_vendor(
                name,
                version,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
                allowed_origins=official_vendor_origins or _OFFICIAL_DOMAINS,
            )
        )
        self.web_search_fetch = web_search_fetch or (
            UnavailableLifecycleSearchProvider().resolve
        )
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.official_vendor_origins = frozenset(
            origin.casefold().strip().rstrip("/")
            for origin in (official_vendor_origins or _OFFICIAL_DOMAINS)
        )

    def resolve(self, os_name: str, os_version: str) -> tuple[LifecycleCandidate, ...]:
        return self.resolve_with_status(os_name, os_version).candidates

    def resolve_with_status(
        self, os_name: str, os_version: str
    ) -> CandidateResolution:
        key = normalize_os_key(os_name, os_version)
        found: list[LifecycleCandidate] = []
        failures: list[SourceFailure] = []
        sources = (
            ("endoflife.date", self.endoflife_fetch),
            ("official_vendor", self.official_vendor_fetch),
            ("web_search", self.web_search_fetch),
        )
        def resolve_source(
            source: str, fetch: Callable[[str, str], Iterable[Mapping[str, Any]]]
        ) -> tuple[str, tuple[LifecycleCandidate, ...], SourceFailure | None]:
            try:
                rows = fetch(os_name, os_version)
                candidates = tuple(
                    LifecycleCandidate.from_mapping(
                        row, os_key=key, source_kind=source
                    )
                    for row in rows
                )
                return source, candidates, None
            except Exception as exc:  # noqa: BLE001 - isolate each untrusted source
                _LOGGER.warning("eol_candidate_source_failed source=%s error=%s", source, exc)
                return source, (), _source_failure(source, exc)

        with ThreadPoolExecutor(
            max_workers=len(sources), thread_name_prefix="eol-source"
        ) as executor:
            futures = {
                executor.submit(resolve_source, source, fetch): source
                for source, fetch in sources
            }
            for future in as_completed(futures):
                _source, candidates, failure = future.result()
                found.extend(candidates)
                if failure is not None:
                    failures.append(failure)
        unique: dict[str, LifecycleCandidate] = {}
        for candidate in found:
            unique[candidate.candidate_id] = candidate
        unique_failures = {
            (failure.source_kind, failure.code): failure for failure in failures
        }
        return CandidateResolution(
            candidates=tuple(unique[key] for key in sorted(unique)),
            source_failures=tuple(
                unique_failures[key] for key in sorted(unique_failures)
            ),
        )


class EOLReviewService:
    """Request-time lifecycle lookup and revision-checked confirmation."""

    def __init__(
        self,
        repository: EOLCatalogRepository | None = None,
        resolver: CandidateResolver | None = None,
        *,
        catalog: EOLCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or LocalEOLCatalogRepository(base_catalog=catalog)
        self.resolver = resolver or CandidateResolver()
        self.clock = clock or (lambda: datetime.now(UTC))

    def catalog(self) -> CatalogSnapshot:
        return self.repository.read()

    def review(self, os_name: str, os_version: str) -> LifecycleReviewResult:
        product = _bounded_text(os_name, "OS name")
        version = _bounded_text(os_version, "OS version")
        key = normalize_os_key(product, version)
        snapshot = self.repository.read()
        entry = snapshot.catalog.lookup(product, version)
        if entry is not None:
            classification = snapshot.catalog.classify(
                entry, now=self.clock(), support_channel=entry.default_support_channel
            )
            return LifecycleReviewResult(
                normalized_os_key=key,
                os_name=product,
                os_version=version,
                status="catalog_hit",
                catalog_revision=snapshot.revision,
                classification=classification.to_dict(),
                provenance=_latest_provenance(snapshot, key),
            )

        candidates = tuple(
            LifecycleCandidate.from_mapping(row, os_key=key)
            for row in (snapshot.candidates or {}).get(key, ())
        )
        cached_failures = tuple(
            SourceFailure(**row)
            for row in (snapshot.source_failures or {}).get(key, ())
        )
        if key not in (snapshot.candidates or {}) and key not in (
            snapshot.source_failures or {}
        ):
            resolution = self.resolver.resolve_with_status(product, version)
            candidates = resolution.candidates
            cached_failures = resolution.source_failures
            self.repository.save_candidates(
                key,
                [item.to_dict() for item in candidates],
                [item.to_dict() for item in cached_failures],
            )
            snapshot = self.repository.read()
        return LifecycleReviewResult(
            normalized_os_key=key,
            os_name=product,
            os_version=version,
            status="review_required",
            catalog_revision=snapshot.revision,
            classification=snapshot.catalog.classify_product(
                product, version, now=self.clock()
            ).to_dict(),
            candidates=candidates,
            source_failures=cached_failures,
            provenance=_latest_provenance(snapshot, key),
        )

    def confirm(
        self,
        *,
        os_name: str,
        os_version: str,
        normalized_os_key: str,
        expected_revision: int,
        reviewer: str,
        candidate_id: str | None = None,
        manual_date: str | date | None = None,
        support_channel: str = "mainstream",
    ) -> LifecycleReviewResult:
        product = _bounded_text(os_name, "OS name")
        version = _bounded_text(os_version, "OS version")
        key = normalize_os_key(product, version)
        if normalize_key(normalized_os_key) != key:
            raise ValueError("normalized_os_key does not match the reviewed OS")
        if (candidate_id is None) == (manual_date is None):
            raise ValueError("Confirm exactly one candidate_id or manual_date")
        if isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        channel = str(support_channel or "mainstream").casefold()
        if channel not in {"mainstream", "extended"}:
            raise ValueError("support_channel must be mainstream or extended")
        snapshot = self.repository.read()
        if snapshot.revision != expected_revision:
            raise CatalogRevisionConflict(expected_revision, snapshot.revision)
        if snapshot.catalog.lookup(product, version) is not None:
            raise DuplicateCatalogConfirmation(f"Lifecycle entry for {key} has already been confirmed")

        selected: LifecycleCandidate | None = None
        if candidate_id is not None:
            selected = _candidate_by_id(snapshot, key, str(candidate_id))
            if selected is None:
                # Re-resolve so a fresh request can confirm a candidate that was
                # not cached by an earlier process.
                selected = next(
                    (
                        item
                        for item in self.resolver.resolve(product, version)
                        if item.candidate_id == candidate_id
                    ),
                    None,
                )
            if selected is None:
                raise ValueError("candidate_id is not present in the server candidate set")
            selected_date = selected.date
            citation = _catalog_citation(product, version, selected)
            claim = selected.extracted_claim
            channel = selected.support_channel
        else:
            selected_date = _iso_date(manual_date, "manual_date")
            citation = _manual_citation(product)
            claim = "Operator entered a lifecycle date without selecting a candidate."

        entry = LifecycleCatalogEntry(
            product=product,
            version=version,
            release_date="1970-01-01",
            mainstream_support_end=selected_date,
            extended_support_end=selected_date,
            last_update_date=self.clock().astimezone(UTC).date().isoformat(),
            recommended_upgrade_path="Review the next supported operating-system release.",
            source_url=citation,
            notes=claim,
            default_support_channel=channel,
        )
        provenance = {
            "normalized_os_key": key,
            "reviewer": _bounded_text(reviewer, "reviewer"),
            "selected_candidate_id": selected.candidate_id if selected else "",
            "manual_date": selected_date if selected is None else "",
            "source_kind": selected.source_kind if selected else "manual",
            "citation": citation,
            "source_claim": claim,
            "reviewed_at": self.clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "catalog_revision": expected_revision + 1,
        }
        saved = self.repository.confirm(
            key, entry, provenance, expected_revision=expected_revision
        )
        classification = saved.catalog.classify(
            entry, now=self.clock(), support_channel=channel
        )
        return LifecycleReviewResult(
            normalized_os_key=key,
            os_name=product,
            os_version=version,
            status="confirmed",
            catalog_revision=saved.revision,
            classification=classification.to_dict(),
            provenance=provenance,
        )


def normalize_os_key(os_name: str, os_version: str) -> str:
    return normalize_key(f"{_bounded_text(os_name, 'OS name')}|{_bounded_text(os_version, 'OS version')}")


def normalize_key(value: str) -> str:
    parts = str(value or "").split("|")
    if len(parts) != 2:
        return ""
    product, version = (" ".join(part.casefold().split()) for part in parts)
    return f"{product}|{version}" if product and version else ""


def _fetch_endoflife(
    os_name: str,
    os_version: str,
    *,
    timeout_seconds: float = 5.0,
    max_response_bytes: int = 256_000,
) -> Iterable[Mapping[str, Any]]:
    slug = _EOL_SLUGS.get(" ".join(os_name.casefold().split()))
    if not slug:
        return ()
    url = f"https://endoflife.date/api/{slug}.json"
    payload = _bounded_json_get(
        url,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )
    if not isinstance(payload, list):
        return ()
    candidates = []
    for row in payload:
        if not isinstance(row, dict) or str(row.get("cycle") or "").casefold() != os_version.casefold():
            continue
        value = row.get("eol")
        if value in (None, False, ""):
            continue
        candidates.append(
            {
                "date": str(value),
                "citation": url,
                "retrieved_at": _now(),
                "extracted_claim": f"endoflife.date reports {os_name} {os_version} end of life as {value}.",
                "confidence": 0.8,
                "support_channel": "mainstream",
            }
        )
    return candidates


def _fetch_official_vendor(
    os_name: str,
    os_version: str,
    *,
    timeout_seconds: float = 5.0,
    max_response_bytes: int = _MAX_RESPONSE_BYTES,
    allowed_origins: Iterable[str] = _OFFICIAL_DOMAINS,
) -> Iterable[Mapping[str, Any]]:
    product = " ".join(os_name.casefold().split())
    url = _VENDOR_URLS.get(product, lambda version: "")(os_version)
    if not url:
        raise SourceAdapterError(
            "not_configured",
            f"No official vendor URL is configured for {os_name}.",
            status="unavailable",
        )
    body = _bounded_text_get(
        url,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        allowed_origins=allowed_origins,
    )
    extractor = _TextExtractor()
    extractor.feed(body)
    text = " ".join(extractor.text)
    if not text:
        raise SourceAdapterError(
            "malformed_content",
            "Official vendor response contained no readable text.",
        )
    values = sorted(
        {
            date(int(year), int(month), int(day)).isoformat()
            for year, month, day in _DATE_RE.findall(html.unescape(text))
            if _valid_date(year, month, day)
        }
    )
    if not values:
        raise SourceAdapterError(
            "no_date_claim",
            "Official vendor content contained no valid lifecycle date claim.",
        )
    return [
        {
            "date": value,
            "citation": url,
            "retrieved_at": _now(),
            "extracted_claim": _claim_excerpt(text, value),
            "confidence": 0.75,
            "support_channel": "mainstream",
        }
        for value in values
    ]


def _bounded_json_get(
    url: str, *, timeout_seconds: float = 5.0, max_response_bytes: int = 256_000
) -> Any:
    _https_url(url, allow_endoflife=True)
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        content = response.content
        if len(content) > max_response_bytes:
            raise ValueError("Candidate response exceeded the byte limit")
        return response.json()


def _bounded_text_get(
        url: str,
        *,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        allowed_origins: Iterable[str] = _OFFICIAL_DOMAINS,
) -> str:
        allowed_hosts = _configured_hosts(allowed_origins)
        current_url = _https_url(
            url, allow_endoflife=False, allowed_hosts=allowed_hosts
        )
        initial_host = urlparse(current_url).hostname
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for redirect_count in range(_MAX_REDIRECTS + 1):
                response = client.get(current_url, headers={"Accept": "text/html"})
                if response.is_redirect or 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        raise SourceAdapterError(
                            "malformed_content",
                            "Official vendor redirect did not provide a location.",
                        )
                    if redirect_count >= _MAX_REDIRECTS:
                        raise SourceAdapterError(
                            "redirect_limit",
                            "Official vendor redirect limit was exceeded.",
                        )
                    redirected_url = urljoin(current_url, location)
                    redirected_host = urlparse(redirected_url).hostname
                    if redirected_host != initial_host:
                        raise SourceAdapterError(
                            "cross_domain_redirect",
                            "Official vendor redirect crossed the approved origin.",
                        )
                    current_url = _https_url(
                        redirected_url,
                        allow_endoflife=False,
                        allowed_hosts=allowed_hosts,
                    )
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise SourceAdapterError(
                        "http_error",
                        f"Official vendor returned HTTP {exc.response.status_code}.",
                    ) from exc
                content = response.content
                if len(content) > max_response_bytes:
                    raise SourceAdapterError(
                        "response_too_large",
                        "Official vendor response exceeded the byte limit.",
                    )
                try:
                    return content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise SourceAdapterError(
                        "malformed_content",
                        "Official vendor response was not valid UTF-8 content.",
                    ) from exc
            raise SourceAdapterError(
                "redirect_limit",
                "Official vendor redirect limit was exceeded.",
            )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())


def _candidate_by_id(
    snapshot: CatalogSnapshot, key: str, candidate_id: str
) -> LifecycleCandidate | None:
    for row in (snapshot.candidates or {}).get(key, ()):
        candidate = LifecycleCandidate.from_mapping(row, os_key=key)
        if candidate.candidate_id == candidate_id:
            return candidate
    return None


def _latest_provenance(snapshot: CatalogSnapshot, key: str) -> dict[str, Any] | None:
    return next(
        (
            dict(item)
            for item in reversed(snapshot.provenance)
            if str(item.get("normalized_os_key") or "") == key
        ),
        None,
    )


def _candidate_id(key: str, source: str, value: str, citation: str, claim: str) -> str:
    digest = hashlib.sha256(f"{key}|{source}|{value}|{citation}|{claim}".encode()).hexdigest()
    return f"eol-{digest[:24]}"


def _bounded_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not 1 <= len(text) <= 120 or any(ord(char) < 32 for char in text):
        raise ValueError(f"{field_name} must be between 1 and 120 characters")
    if any(separator in text for separator in ("|", "/", "\\")):
        raise ValueError(f"{field_name} contains a forbidden separator")
    return text


def _iso_date(value: Any, field_name: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def _https_url(
    value: str,
    *,
    allow_endoflife: bool,
    allow_any_https: bool = False,
    allowed_hosts: Iterable[str] | None = None,
) -> str:
    parsed = urlparse(str(value or ""))
    host = parsed.hostname.casefold() if parsed.hostname else ""
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Lifecycle citation must be an HTTPS URL")
    if allow_any_https:
        allowed = None
    elif allow_endoflife:
        allowed = _OFFICIAL_DOMAINS | {"endoflife.date", "www.endoflife.date"}
    else:
        allowed = _OFFICIAL_DOMAINS
    if allowed_hosts is not None:
        allowed = set(allowed_hosts)
    if allowed is not None and host not in allowed:
        raise ValueError("Lifecycle citation is not from an approved source domain")
    try:
        if ipaddress.ip_address(host):
            raise ValueError("Lifecycle citation cannot use an IP address")
    except ValueError:
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", host) or ":" in host:
            raise
    return str(value)


def _bounded_url(value: str) -> str:
    text = str(value or "").strip()
    if not 1 <= len(text) <= 2048 or any(ord(char) < 32 for char in text):
        raise ValueError("Lifecycle citation must be a bounded HTTPS URL")
    return text


def _configured_hosts(origins: Iterable[str]) -> frozenset[str]:
    hosts: set[str] = set()
    for origin in origins:
        text = str(origin or "").strip()
        parsed = urlparse(text if "://" in text else f"https://{text}")
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Official vendor origins must be HTTPS hosts")
        hosts.add(parsed.hostname.casefold())
    if not hosts:
        raise ValueError("At least one official vendor origin must be configured")
    return frozenset(hosts)


def _claim_excerpt(text: str, value: str) -> str:
    """Return bounded surrounding source text rather than an unbounded page."""
    position = text.find(value)
    if position < 0:
        return f"Official vendor content contains lifecycle date {value}."
    excerpt = text[max(0, position - 512) : position + len(value) + 512].strip()
    return excerpt[:_MAX_CLAIM_CHARS]


def _source_failure(source: str, exc: Exception) -> SourceFailure:
    if isinstance(exc, SourceAdapterError):
        return SourceFailure(source, exc.status, exc.code, str(exc))
    if isinstance(exc, httpx.TimeoutException):
        return SourceFailure(
            source, "unavailable", "timeout", "The source request timed out."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        return SourceFailure(
            source, "failed", "http_error", "The source returned an HTTP error."
        )
    if isinstance(exc, httpx.HTTPError):
        return SourceFailure(
            source, "unavailable", "network_error", "The source request failed."
        )
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return SourceFailure(
            source, "failed", "malformed_content", "The source content was malformed."
        )
    if isinstance(exc, ValueError):
        return SourceFailure(source, "failed", "invalid_content", str(exc)[:240])
    return SourceFailure(
        source, "unavailable", "source_error", "The source could not be queried."
    )


def _catalog_citation(
    product: str, version: str, candidate: LifecycleCandidate
) -> str:
    """Keep catalog rows on authoritative vendor domains.

    endoflife.date and search results remain in review provenance, but the
    existing lifecycle catalog contract intentionally permits only vendor URLs
    for known products.
    """
    if candidate.source_kind == "official_vendor":
        return candidate.citation
    product_key = " ".join(product.casefold().split())
    return _VENDOR_URLS.get(product_key, lambda _version: "")(version) or _manual_citation(
        product
    )


def _manual_citation(product: str) -> str:
    if "ubuntu" in product.casefold():
        return "https://ubuntu.com/about/release-cycle"
    if "red hat" in product.casefold():
        return "https://access.redhat.com/support/policy/updates/errata"
    if "debian" in product.casefold():
        return "https://www.debian.org/releases/"
    if "kubernetes" in product.casefold():
        return "https://kubernetes.io/releases/"
    return "https://learn.microsoft.com/en-us/lifecycle/"


def _valid_date(year: str, month: str, day: str) -> bool:
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        return False
    return True


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


_EOL_SLUGS = {
    "windows server": "windows-server",
    "ubuntu": "ubuntu",
    "red hat enterprise linux": "rhel",
    "debian": "debian",
    "kubernetes": "kubernetes",
}
_VENDOR_URLS = {
    "windows server": lambda version: f"https://learn.microsoft.com/en-us/lifecycle/products/windows-server-{version}",
    "ubuntu": lambda _version: "https://ubuntu.com/about/release-cycle",
    "red hat enterprise linux": lambda _version: "https://access.redhat.com/support/policy/updates/errata",
    "debian": lambda _version: "https://www.debian.org/releases/",
    "kubernetes": lambda _version: "https://kubernetes.io/releases/",
}
