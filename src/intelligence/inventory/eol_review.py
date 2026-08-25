"""Lifecycle candidate resolution and governed operator confirmation."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

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
        if not 1 <= len(self.extracted_claim.strip()) <= 2000:
            raise ValueError("Candidate extracted_claim must be between 1 and 2000 characters")

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
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload


class CandidateResolver:
    """Run all configured candidate sources without selecting a winner."""

    def __init__(
        self,
        *,
        endoflife_fetch: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None,
        official_vendor_fetch: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None,
        web_search_fetch: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 256_000,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes < 1024:
            raise ValueError("Candidate resolver bounds must be positive")
        self.endoflife_fetch = endoflife_fetch or _fetch_endoflife
        self.official_vendor_fetch = official_vendor_fetch or _fetch_official_vendor
        self.web_search_fetch = web_search_fetch or _empty_web_search
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def resolve(self, os_name: str, os_version: str) -> tuple[LifecycleCandidate, ...]:
        key = normalize_os_key(os_name, os_version)
        found: list[LifecycleCandidate] = []
        sources = (
            ("endoflife.date", self.endoflife_fetch),
            ("official_vendor", self.official_vendor_fetch),
            ("web_search", self.web_search_fetch),
        )
        for source, fetch in sources:
            try:
                rows = fetch(os_name, os_version)
                for row in rows:
                    candidate = LifecycleCandidate.from_mapping(
                        row, os_key=key, source_kind=source
                    )
                    found.append(candidate)
            except (OSError, RuntimeError, TypeError, ValueError, httpx.HTTPError) as exc:
                _LOGGER.warning("eol_candidate_source_failed source=%s error=%s", source, exc)
        unique: dict[str, LifecycleCandidate] = {}
        for candidate in found:
            unique[candidate.candidate_id] = candidate
        return tuple(unique[key] for key in sorted(unique))


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
        if not candidates:
            candidates = self.resolver.resolve(product, version)
            self.repository.save_candidates(key, [item.to_dict() for item in candidates])
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


def _fetch_endoflife(os_name: str, os_version: str) -> Iterable[Mapping[str, Any]]:
    slug = _EOL_SLUGS.get(" ".join(os_name.casefold().split()))
    if not slug:
        return ()
    url = f"https://endoflife.date/api/{slug}.json"
    payload = _bounded_json_get(url)
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


def _fetch_official_vendor(os_name: str, os_version: str) -> Iterable[Mapping[str, Any]]:
    product = " ".join(os_name.casefold().split())
    url = _VENDOR_URLS.get(product, lambda version: "")(os_version)
    if not url:
        return ()
    body = _bounded_text_get(url)
    text = " ".join(_TextExtractor().feed(body))
    values = sorted(
        {
            date(year, int(month), int(day)).isoformat()
            for year, month, day in _DATE_RE.findall(html.unescape(text))
            if _valid_date(year, month, day)
        }
    )
    return [
        {
            "date": value,
            "citation": url,
            "retrieved_at": _now(),
            "extracted_claim": f"Official vendor page for {os_name} {os_version} contains lifecycle date {value}.",
            "confidence": 0.75,
            "support_channel": "mainstream",
        }
        for value in values
    ]


def _empty_web_search(_os_name: str, _os_version: str) -> Iterable[Mapping[str, Any]]:
    return ()


def _bounded_json_get(url: str) -> Any:
    _https_url(url, allow_endoflife=True)
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        content = response.content
        if len(content) > 256_000:
            raise ValueError("Candidate response exceeded the byte limit")
        return response.json()


def _bounded_text_get(url: str) -> str:
    _https_url(url, allow_endoflife=False)
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
        response = client.get(url, headers={"Accept": "text/html"})
        response.raise_for_status()
        content = response.content
        if len(content) > 256_000:
            raise ValueError("Official vendor response exceeded the byte limit")
        return content.decode("utf-8", errors="replace")


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
    if not 1 <= len(text) <= 120:
        raise ValueError(f"{field_name} must be between 1 and 120 characters")
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
    value: str, *, allow_endoflife: bool, allow_any_https: bool = False
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
    if allowed is not None and host not in allowed:
        raise ValueError("Lifecycle citation is not from an approved source domain")
    try:
        if ipaddress.ip_address(host):
            raise ValueError("Lifecycle citation cannot use an IP address")
    except ValueError:
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", host) or ":" in host:
            raise
    return str(value)


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
