from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from intelligence.inventory.eol_repository import (
    CatalogRevisionConflict,
    DuplicateCatalogConfirmation,
    LocalEOLCatalogRepository,
)
from intelligence.inventory.eol_review import (
    ApprovedSearchApiLifecycleProvider,
    CandidateResolver,
    EOLReviewService,
    LifecycleCandidate,
    SourceAdapterError,
    UnavailableLifecycleSearchProvider,
    _fetch_official_vendor,
)
from intelligence.lifecycle import EOLCatalog


def test_catalog_miss_returns_all_sources_and_confirmation_persists_provenance(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def source(kind: str, citation: str, value: str):
        def fetch(_name: str, _version: str):
            calls.append(kind)
            return [
                {
                    "date": value,
                    "citation": citation,
                    "retrieved_at": "2026-08-26T00:00:00Z",
                    "extracted_claim": f"{kind} claim",
                    "confidence": 0.8,
                }
            ]

        return fetch

    repository = LocalEOLCatalogRepository(tmp_path / "eol.json", base_catalog=EOLCatalog.default())
    service = EOLReviewService(
        repository,
        CandidateResolver(
            endoflife_fetch=source(
                "endoflife.date", "https://endoflife.date/api/windows-server.json", "2030-01-01"
            ),
            official_vendor_fetch=source(
                "official_vendor",
                "https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2099-preview",
                "2031-01-01",
            ),
            web_search_fetch=source("web_search", "https://example.com/lifecycle", "2032-01-01"),
        ),
        clock=lambda: datetime(2026, 8, 26, tzinfo=UTC),
    )

    review = service.review("Windows Server", "2099-preview")

    assert review.status == "review_required"
    assert len(review.candidates) == 3
    assert {candidate.source_kind for candidate in review.candidates} == {
        "endoflife.date",
        "official_vendor",
        "web_search",
    }
    assert all(candidate.citation.startswith("https://") for candidate in review.candidates)
    assert set(calls) == {"endoflife.date", "official_vendor", "web_search"}

    persisted = service.review("Windows Server", "2099-preview")
    assert len(persisted.candidates) == 3
    assert set(calls) == {"endoflife.date", "official_vendor", "web_search"}

    confirmed = service.confirm(
        os_name="Windows Server",
        os_version="2099-preview",
        normalized_os_key="windows server|2099-preview",
        expected_revision=0,
        reviewer="operator@example.com",
        candidate_id=review.candidates[0].candidate_id,
    )

    assert confirmed.status == "confirmed"
    assert confirmed.catalog_revision == 1
    assert repository.read().catalog.lookup("Windows Server", "2099-preview") is not None
    provenance = repository.read().provenance[-1]
    assert provenance["reviewer"] == "operator@example.com"
    assert provenance["selected_candidate_id"] == review.candidates[0].candidate_id
    assert provenance["source_claim"]


def test_confirmation_rejects_stale_revision_without_overwriting_newer_catalog(
    tmp_path: Path,
) -> None:
    repository = LocalEOLCatalogRepository(tmp_path / "eol.json")
    resolver = CandidateResolver(
        endoflife_fetch=lambda *_: (
            {
                "date": "2030-01-01",
                "citation": "https://endoflife.date/api/windows-server.json",
                "retrieved_at": "2026-08-26T00:00:00Z",
                "extracted_claim": "endoflife.date claim",
                "confidence": 0.8,
            },
        ),
        official_vendor_fetch=lambda *_: (),
        web_search_fetch=lambda *_: (),
    )
    service = EOLReviewService(repository, resolver)
    review = service.review("Windows Server", "2099-preview")
    service.confirm(
        os_name="Windows Server",
        os_version="2099-preview",
        normalized_os_key=review.normalized_os_key,
        expected_revision=review.catalog_revision,
        reviewer="first@example.com",
        candidate_id=review.candidates[0].candidate_id,
    )

    with pytest.raises(CatalogRevisionConflict):
        service.confirm(
            os_name="Windows Server",
            os_version="2099-preview",
            normalized_os_key=review.normalized_os_key,
            expected_revision=review.catalog_revision,
            reviewer="stale@example.com",
            candidate_id=review.candidates[0].candidate_id,
        )

    assert repository.read().provenance[-1]["reviewer"] == "first@example.com"


def test_manual_date_requires_exactly_one_selection_and_valid_https_citations(
    tmp_path: Path,
) -> None:
    repository = LocalEOLCatalogRepository(tmp_path / "eol.json")
    service = EOLReviewService(repository, CandidateResolver(
        endoflife_fetch=lambda *_: (),
        official_vendor_fetch=lambda *_: (),
        web_search_fetch=lambda *_: (),
    ))
    review = service.review("Contoso OS", "1")

    with pytest.raises(ValueError, match="exactly one"):
        service.confirm(
            os_name="Contoso OS",
            os_version="1",
            normalized_os_key=review.normalized_os_key,
            expected_revision=review.catalog_revision,
            reviewer="operator@example.com",
        )

    confirmed = service.confirm(
        os_name="Contoso OS",
        os_version="1",
        normalized_os_key=review.normalized_os_key,
        expected_revision=review.catalog_revision,
        reviewer="operator@example.com",
        manual_date="2030-02-03",
    )
    assert confirmed.classification["support_end"] == "2030-02-03"


def test_catalog_hit_is_authoritative_and_duplicate_confirmation_is_rejected(
    tmp_path: Path,
) -> None:
    repository = LocalEOLCatalogRepository(tmp_path / "eol.json")
    resolver = CandidateResolver(
        endoflife_fetch=lambda *_: (),
        official_vendor_fetch=lambda *_: (),
        web_search_fetch=lambda *_: (),
    )
    service = EOLReviewService(repository, resolver)

    hit = service.review("Windows Server", "2019")

    assert hit.status == "catalog_hit"
    assert hit.candidates == ()
    assert hit.classification["support_channel"] == "extended"

    miss = service.review("Windows Server", "2099-preview")
    service.confirm(
        os_name="Windows Server",
        os_version="2099-preview",
        normalized_os_key=miss.normalized_os_key,
        expected_revision=miss.catalog_revision,
        reviewer="operator@example.com",
        manual_date="2030-01-01",
    )
    with pytest.raises(DuplicateCatalogConfirmation):
        service.confirm(
            os_name="Windows Server",
            os_version="2099-preview",
            normalized_os_key=miss.normalized_os_key,
            expected_revision=1,
            reviewer="operator@example.com",
            manual_date="2031-01-01",
        )


def test_candidate_citations_are_https_and_bounded_to_approved_sources() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        LifecycleCandidate.from_mapping(
            {
                "date": "2030-01-01",
                "source_kind": "official_vendor",
                "citation": "http://learn.microsoft.com/lifecycle",
                "retrieved_at": "2026-08-26T00:00:00Z",
                "extracted_claim": "untrusted",
                "confidence": 0.5,
            }
        )


class _FakeHTTPClient:
    def __init__(self, response: httpx.Response | Exception, **_kwargs) -> None:
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, *_args, **_kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_official_vendor_adapter_extracts_bounded_citation(monkeypatch) -> None:
    response = httpx.Response(
        200,
        content=(
            b"<html><body>Windows Server 2099 support ends "
            b"2031-01-01.</body></html>"
        ),
        request=httpx.Request("GET", "https://learn.microsoft.com/lifecycle"),
    )
    monkeypatch.setattr(
        "intelligence.inventory.eol_review.httpx.Client",
        lambda **kwargs: _FakeHTTPClient(response, **kwargs),
    )

    [candidate] = _fetch_official_vendor(
        "Windows Server",
        "2099-preview",
        allowed_origins={"learn.microsoft.com"},
    )

    assert candidate["date"] == "2031-01-01"
    assert candidate["citation"].startswith("https://learn.microsoft.com/")
    assert candidate["retrieved_at"]
    assert len(candidate["extracted_claim"]) <= 4096


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            httpx.Response(
                503,
                request=httpx.Request("GET", "https://learn.microsoft.com/lifecycle"),
            ),
            "http_error",
        ),
        (
            httpx.Response(
                200,
                content=b"x" * (1024 * 1024 + 1),
                request=httpx.Request("GET", "https://learn.microsoft.com/lifecycle"),
            ),
            "response_too_large",
        ),
        (
            httpx.Response(
                200,
                content=b"<html><body>No lifecycle claims</body></html>",
                request=httpx.Request("GET", "https://learn.microsoft.com/lifecycle"),
            ),
            "no_date_claim",
        ),
        (
            httpx.TimeoutException("timed out"),
            "timeout",
        ),
    ],
)
def test_bounded_official_vendor_failures_are_typed(
    monkeypatch, response, code
) -> None:
    monkeypatch.setattr(
        "intelligence.inventory.eol_review.httpx.Client",
        lambda **kwargs: _FakeHTTPClient(response, **kwargs),
    )
    resolver = CandidateResolver(
        endoflife_fetch=lambda *_: (),
        official_vendor_fetch=lambda name, version: _fetch_official_vendor(
            name,
            version,
            allowed_origins={"learn.microsoft.com"},
        ),
        web_search_fetch=lambda *_: (),
    )

    result = resolver.resolve_with_status("Windows Server", "2099-preview")

    assert result.candidates == ()
    assert result.source_failures[0].source_kind == "official_vendor"
    assert result.source_failures[0].code == code


def test_cross_domain_vendor_redirect_is_rejected(monkeypatch) -> None:
    redirect = httpx.Response(
        302,
        headers={"location": "https://attacker.example/eol"},
        request=httpx.Request("GET", "https://learn.microsoft.com/lifecycle"),
    )
    monkeypatch.setattr(
        "intelligence.inventory.eol_review.httpx.Client",
        lambda **kwargs: _FakeHTTPClient(redirect, **kwargs),
    )

    with pytest.raises(SourceAdapterError, match="crossed"):
        _fetch_official_vendor(
            "Windows Server",
            "2099-preview",
            allowed_origins={"learn.microsoft.com"},
        )
    with pytest.raises(ValueError, match="approved"):
        LifecycleCandidate.from_mapping(
            {
                "date": "2030-01-01",
                "source_kind": "official_vendor",
                "citation": "https://example.com/lifecycle",
                "retrieved_at": "2026-08-26T00:00:00Z",
                "extracted_claim": "untrusted",
                "confidence": 0.5,
            }
        )


def test_unconfigured_external_search_is_explicitly_unavailable() -> None:
    resolver = CandidateResolver(
        endoflife_fetch=lambda *_: (),
        official_vendor_fetch=lambda *_: (),
        web_search_fetch=UnavailableLifecycleSearchProvider().resolve,
    )

    result = resolver.resolve_with_status("Contoso OS", "1")

    assert result.candidates == ()
    assert result.source_failures == (
        result.source_failures[0],
    )
    assert result.source_failures[0].source_kind == "web_search"
    assert result.source_failures[0].status == "unavailable"
    assert result.source_failures[0].code == "provider_not_configured"


class _FakeProviderHTTPClient:
    def __init__(self, response: httpx.Response, **_kwargs) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, *, json, headers):
        self.requests.append({"url": url, "json": json, "headers": headers})
        return self.response


def test_approved_search_provider_sends_only_normalized_identity(monkeypatch) -> None:
    response = httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "date": "2030-01-01",
                    "source_kind": "web_search",
                    "citation": "https://vendor.example/lifecycle",
                    "retrieved_at": "2026-08-26T00:00:00Z",
                    "extracted_claim": "Approved provider claim",
                    "confidence": 0.7,
                }
            ]
        },
        request=httpx.Request("POST", "https://search.example/lookup"),
    )
    fake = _FakeProviderHTTPClient(response)
    monkeypatch.setattr(
        "intelligence.inventory.eol_review.httpx.Client",
        lambda **kwargs: fake,
    )

    provider = ApprovedSearchApiLifecycleProvider(
        "https://search.example/lookup", credential="secret-not-in-body"
    )
    [candidate] = provider.resolve("Windows Server", "2099-preview")

    assert candidate["citation"] == "https://vendor.example/lifecycle"
    assert fake.requests[0]["json"] == {
        "operation": "lifecycle_lookup",
        "normalized_os_key": "windows server|2099-preview",
    }
    assert "secret-not-in-body" not in str(fake.requests[0]["json"])


def test_document_backed_catalog_persists_seed_provenance_and_audit(tmp_path) -> None:
    from storage.onelake_documents import OneLakeDocumentStore

    document_store = OneLakeDocumentStore(tmp_path)
    repository = LocalEOLCatalogRepository(
        base_catalog=EOLCatalog.default(),
        document_store=document_store,
    )
    service = EOLReviewService(
        repository,
        CandidateResolver(
            endoflife_fetch=lambda *_: (),
            official_vendor_fetch=lambda *_: (),
            web_search_fetch=lambda *_: (),
        ),
    )
    review = service.review("Contoso OS", "1")
    confirmed = service.confirm(
        os_name="Contoso OS",
        os_version="1",
        normalized_os_key=review.normalized_os_key,
        expected_revision=review.catalog_revision,
        reviewer="operator@example.com",
        manual_date="2030-02-03",
    )

    document = document_store.read("state/eol_catalog.json")
    restarted = LocalEOLCatalogRepository(
        base_catalog=EOLCatalog.default(),
        document_store=OneLakeDocumentStore(tmp_path),
    )

    assert document["catalog_seed"]
    assert document["revision"] == 1
    assert restarted.read().catalog.lookup("Contoso OS", "1") is not None
    assert restarted.read().audit_events[-1]["action"] == "lifecycle.confirmed"
    assert restarted.read().audit_events[-1]["source_references"]
    assert confirmed.catalog_revision == 1
