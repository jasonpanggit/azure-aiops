from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from intelligence.inventory.eol_repository import (
    CatalogRevisionConflict,
    DuplicateCatalogConfirmation,
    LocalEOLCatalogRepository,
)
from intelligence.inventory.eol_review import (
    CandidateResolver,
    EOLReviewService,
    LifecycleCandidate,
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
    assert calls == ["endoflife.date", "official_vendor", "web_search"]

    persisted = service.review("Windows Server", "2099-preview")
    assert len(persisted.candidates) == 3
    assert calls == ["endoflife.date", "official_vendor", "web_search"]

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
