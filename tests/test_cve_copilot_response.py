from operations.cve_response import deterministic_cve_narrative


def _exposure(
    cve_id: str,
    *,
    total: int = 2,
    returned: int = 2,
    represented_workloads: int | None = 1,
    active_count: int | None = 2,
) -> dict:
    items = [
        {
            "weakness_id": cve_id,
            "severity": "Critical",
            "target_kind": "container_image",
            "current_state": "active",
            "represented_workload_count": represented_workloads,
        }
        for _ in range(returned)
    ]
    payload = {
        "query_cve_id": cve_id,
        "total_count": total,
        "returned_count": returned,
        "items": items,
    }
    if active_count is not None:
        payload["affected_active_count"] = active_count
    return payload


def _detail(cve_id: str, sources: dict, exposure: dict) -> dict:
    catalog = {
        "contract_version": "1.0.0",
        "catalog_scope": "external_public_metadata",
        "environment_membership_included": False,
        "item": {"cve_id": cve_id, "sources": sources},
    }
    return {
        **catalog,
        "cve_id": cve_id,
        "external_catalog": catalog,
        "scoped_exposure": exposure,
        "scoped_exposure_status": "ok",
    }


def _source(
    source: str,
    payload: dict | None,
    *,
    status: str = "succeeded",
    stale: bool = False,
    safe_error_code: str = "",
) -> dict:
    return {
        "source": source,
        "identifier": "CVE-2026-13221",
        "status": status,
        "stale": stale,
        "has_last_known_good": payload is not None,
        "safe_error_code": safe_error_code,
        "payload": payload,
    }


def test_live_cve_response_uses_metadata_and_scoped_coverage() -> None:
    cve_id = "CVE-2026-13221"
    exposure = _exposure(
        cve_id,
        total=32,
        returned=25,
        represented_workloads=0,
        active_count=32,
    )
    detail = _detail(
        cve_id,
        {
            "nvd": _source(
                "nvd",
                {
                    "description": (
                        "Perl fixed-string alternation trie overflow can cause "
                        "silent false-positive or false-negative regex matches."
                    ),
                    "severity": "CRITICAL",
                    "cvss": {
                        "base_score": 9.1,
                        "vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H",
                        "severity": "CRITICAL",
                    },
                    "associated_kbs": [],
                },
            ),
            "epss": _source(
                "epss",
                {"epss_score": 0.00432, "epss_percentile": 0.36545},
            ),
            "kev": _source("kev", None),
        },
        exposure,
    )

    response = deterministic_cve_narrative(cve_id, detail_data=detail)

    assert "CVE-2026-13221" in response
    assert "CVSS 9.1 Critical" in response
    assert "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H" in response
    assert "0.432%" in response
    assert "36.545th percentile" in response
    assert "no listing for CVE-2026-13221" in response
    assert "No KB association" in response
    assert "**32** matching findings" in response
    assert "**25 records were inspected**" in response
    assert "**32 are active**" in response
    assert "no represented workload mapping" in response
    assert "remaining 7 scoped findings" in response
    assert "vendor-fixed package/version" in response
    assert "External CVE metadata is current from" not in response


def test_complete_enrichment_omits_unknown_heading_and_uses_risk_signals() -> None:
    cve_id = "CVE-2026-22222"
    exposure = _exposure(cve_id, represented_workloads=2)
    detail = _detail(
        cve_id,
        {
            "nvd": _source(
                "nvd",
                {
                    "description": "Remote code execution.",
                    "severity": "Critical",
                    "cvss": {
                        "base_score": 9.8,
                        "vector": "CVSS:3.1/AV:N/AC:L",
                        "severity": "Critical",
                    },
                    "associated_kbs": ["KB600001"],
                },
            ),
            "epss": _source(
                "epss",
                {"epss_score": 0.91, "epss_percentile": 0.99},
            ),
            "kev": _source(
                "kev",
                {
                    "kev_date_added": "2026-09-01",
                    "kev_due_date": "2026-09-22",
                    "kev_ransomware_use": "Known",
                },
            ),
            "msrc:KB600001": {
                **_source(
                    "msrc",
                    {
                        "kb_id": "KB600001",
                        "title": "Security update",
                    },
                ),
                "identifier": "KB600001",
            },
        },
        exposure,
    )

    response = deterministic_cve_narrative(cve_id, detail_data=detail)

    assert "**What is not known**" not in response
    assert "remediation due 2026-09-22" in response
    assert "ransomware use Known" in response
    assert "91% EPSS probability" in response
    assert "KB600001" in response
    assert "bounded pagination" not in response


def test_partial_and_absent_metadata_report_only_unresolved_dimensions() -> None:
    cve_id = "CVE-2026-33333"
    exposure = _exposure(cve_id, represented_workloads=1)
    partial = _detail(
        cve_id,
        {
            "nvd": _source(
                "nvd",
                None,
                status="failed",
                safe_error_code="rate_limited",
            ),
            "epss": _source(
                "epss",
                {"epss_score": 0.2, "epss_percentile": 0.8},
            ),
            "kev": _source("kev", None),
        },
        exposure,
    )

    partial_response = deterministic_cve_narrative(cve_id, detail_data=partial)
    absent_response = deterministic_cve_narrative(
        cve_id,
        exposure_data=exposure,
        exposure_status="ok",
    )

    assert "NVD metadata is unresolved because the provider reported rate limited" in partial_response
    assert "EPSS probability and percentile are unavailable" not in partial_response
    assert "CISA KEV listing status is unavailable" not in partial_response
    assert "CVSS severity and vector are unavailable" in absent_response
    assert "EPSS probability and percentile are unavailable" in absent_response
    assert "CISA KEV listing status is unavailable" in absent_response


def test_mismatched_cve_payload_is_never_narrated() -> None:
    response = deterministic_cve_narrative(
        "CVE-2026-44444",
        detail_data=_detail(
            "CVE-2026-55555",
            {},
            _exposure("CVE-2026-55555"),
        ),
    )

    assert response == ""


def test_stale_last_known_good_payload_is_not_presented_as_current() -> None:
    cve_id = "CVE-2026-66666"
    exposure = _exposure(cve_id, represented_workloads=1)
    detail = _detail(
        cve_id,
        {
            "nvd": _source(
                "nvd",
                {
                    "description": "Stale description",
                    "severity": "Critical",
                    "cvss": {
                        "base_score": 9.9,
                        "vector": "CVSS:3.1/STALE",
                        "severity": "Critical",
                    },
                    "associated_kbs": ["KBSTALE"],
                },
                status="failed",
                stale=True,
            ),
            "epss": _source(
                "epss",
                {"epss_score": 0.99, "epss_percentile": 0.999},
                status="failed",
                stale=True,
            ),
            "msrc:KBSTALE": {
                **_source(
                    "msrc",
                    {"kb_id": "KBSTALE", "title": "Stale update"},
                    status="failed",
                    stale=True,
                ),
                "identifier": "KBSTALE",
            },
        },
        exposure,
    )

    response = deterministic_cve_narrative(cve_id, detail_data=detail)

    assert "Stale description" not in response
    assert "CVSS 9.9" not in response
    assert "99%" not in response
    assert "Associated Microsoft security update" not in response
    assert "KBSTALE" not in response
    assert "only last-known-good metadata is retained" in response
    assert "critical remediation priority" not in response
    assert "EPSS probability as elevated" not in response


def test_explicit_empty_scope_suppresses_workload_and_target_actions() -> None:
    cve_id = "CVE-2026-77777"
    response = deterministic_cve_narrative(
        cve_id,
        exposure_data={
            "query_cve_id": cve_id,
            "total_count": 0,
            "returned_count": 0,
            "items": [],
        },
        exposure_status="empty",
    )

    assert "no scoped findings for CVE-2026-77777" in response
    assert "running workload impact" not in response
    assert "Map affected" not in response
    assert "affected scoped targets" not in response
    assert "No scoped remediation target is established" in response
