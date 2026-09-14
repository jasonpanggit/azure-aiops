"""Evidence-grounded deterministic narration for one CVE."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

_CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
_CURRENT_SOURCE_STATUSES = frozenset({"ok", "succeeded", "success"})
_DEGRADED_SOURCE_STATUSES = frozenset({"failed", "partial", "stale", "unavailable"})
_UNKNOWN_ACTIVITY_STATES = frozenset({"", "unknown", "unavailable", "not_available"})


def canonical_cve_id(value: object) -> str:
    """Return an uppercase CVE identifier, or an empty string when invalid."""

    candidate = str(value or "").strip().upper()
    return candidate if _CVE_PATTERN.fullmatch(candidate) else ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _count(value: Any) -> int | None:
    result = _number(value)
    if result is None or result < 0 or not result.is_integer():
        return None
    return int(result)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _percent(value: float) -> str:
    percent = value * 100
    precision = 3 if percent < 1 else 1
    return f"{percent:.{precision}f}".rstrip("0").rstrip(".")


def _catalog(detail: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = _mapping(detail.get("external_catalog"))
    if nested:
        return nested
    item = _mapping(detail.get("item"))
    return detail if isinstance(item.get("sources"), Mapping) else {}


def _legacy_detail(detail: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = _mapping(detail.get("vulnerability_detail"))
    if nested:
        return nested
    return detail if isinstance(detail.get("cve"), Mapping) else {}


def _source_records(catalog: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    records: dict[str, list[Mapping[str, Any]]] = {}
    for value in _mapping(_mapping(catalog.get("item")).get("sources")).values():
        record = _mapping(value)
        source = _text(record.get("source")).casefold()
        if source:
            records.setdefault(source, []).append(record)
    return records


def _source_is_current(record: Mapping[str, Any]) -> bool:
    return (
        _text(record.get("status")).casefold() in _CURRENT_SOURCE_STATUSES
        and not bool(record.get("stale"))
    )


def _source_gap(source: str, record: Mapping[str, Any]) -> str:
    label = source.upper() if source != "kev" else "CISA KEV"
    status = _text(record.get("status")).casefold() or "unknown"
    safe_error = _text(record.get("safe_error_code"))
    if bool(record.get("stale")):
        reason = "its latest record is stale"
    elif safe_error:
        reason = f"the provider reported {safe_error.replace('_', ' ')}"
    elif status in _DEGRADED_SOURCE_STATUSES:
        reason = f"the provider status is {status}"
    else:
        reason = "no current provider result is available"
    if record.get("has_last_known_good") and _mapping(record.get("payload")):
        reason += "; only last-known-good metadata is retained"
    return f"{label} metadata is unresolved because {reason}."


def _matching_rows(data: Mapping[str, Any], cve_id: str) -> list[Mapping[str, Any]]:
    rows = [
        _mapping(row)
        for row in _sequence(data.get("items") or data.get("findings"))
        if isinstance(row, Mapping)
    ]
    matching: list[Mapping[str, Any]] = []
    for row in rows:
        row_cve = canonical_cve_id(row.get("weakness_id") or row.get("cve_id"))
        if row_cve and row_cve != cve_id:
            continue
        matching.append(row)
    return matching


def _catalog_cve_id(catalog: Mapping[str, Any]) -> str:
    return canonical_cve_id(_mapping(catalog.get("item")).get("cve_id"))


def deterministic_cve_narrative(
    requested_cve_id: object,
    *,
    detail_data: Any = None,
    exposure_data: Any = None,
    exposure_status: str = "",
    snapshot_coverage: Mapping[str, Any] | None = None,
    source_statuses: Mapping[str, str] | None = None,
) -> str:
    """Build a bounded CVE answer only from supplied durable/scoped evidence."""

    cve_id = canonical_cve_id(requested_cve_id)
    if not cve_id:
        return ""
    detail = _mapping(detail_data)
    catalog = _catalog(detail)
    catalog_id = _catalog_cve_id(catalog)
    if catalog_id and catalog_id != cve_id:
        return ""
    detail_id = canonical_cve_id(detail.get("cve_id"))
    if detail_id and detail_id != cve_id:
        return ""

    legacy = _legacy_detail(detail)
    legacy_cve = _mapping(legacy.get("cve"))
    legacy_id = canonical_cve_id(legacy_cve.get("cve_id"))
    if legacy_id and legacy_id != cve_id:
        legacy = {}
        legacy_cve = {}

    sources = _source_records(catalog)
    nvd_record = next(iter(sources.get("nvd", ())), {})
    epss_record = next(iter(sources.get("epss", ())), {})
    kev_record = next(iter(sources.get("kev", ())), {})
    nvd_current = bool(nvd_record and _source_is_current(nvd_record))
    epss_current = bool(epss_record and _source_is_current(epss_record))
    nvd = _mapping(nvd_record.get("payload")) if nvd_current else {}
    epss = _mapping(epss_record.get("payload")) if epss_current else {}
    kev = _mapping(kev_record.get("payload"))

    cvss = _mapping(nvd.get("cvss")) or (
        _mapping(legacy_cve.get("cvss")) if not nvd_record else {}
    )
    severity = (
        _text(nvd.get("severity"))
        or _text(cvss.get("severity"))
        or (_text(legacy_cve.get("severity")) if not nvd_record else "")
    )
    description = _text(nvd.get("description")) or (
        _text(legacy_cve.get("description")) if not nvd_record else ""
    )
    base_score = _number(cvss.get("base_score"))
    vector = _text(cvss.get("vector"))
    epss_score = _number(epss.get("epss_score"))
    if epss_score is None and not epss_record:
        epss_score = _number(legacy_cve.get("epss_score"))
    epss_percentile = _number(epss.get("epss_percentile"))
    if epss_percentile is None and not epss_record:
        epss_percentile = _number(legacy_cve.get("epss_percentile"))

    known: list[str] = []
    unknowns: list[str] = []
    recommendations: list[str] = []

    if base_score is not None or severity or vector:
        score = f"CVSS {base_score:g}" if base_score is not None else "CVSS score unavailable"
        severity_text = f" {severity.title()}" if severity else ""
        vector_text = f" with vector `{vector}`" if vector else ""
        known.append(f"NVD reports **{score}{severity_text}**{vector_text}.")
    elif nvd_record and not _source_is_current(nvd_record):
        unknowns.append(_source_gap("nvd", nvd_record))
    else:
        unknowns.append("CVSS severity and vector are unavailable.")
    if description:
        known.append(f"NVD description: {description}")
    elif not nvd_record:
        unknowns.append("A current external CVE description is unavailable.")

    if epss_score is not None:
        percentile = (
            " at the "
            f"{epss_percentile * 100:.3f}".rstrip("0").rstrip(".")
            + "th percentile"
            if epss_percentile is not None
            else ""
        )
        known.append(
            f"EPSS estimates **{_percent(epss_score)}%** exploitation probability"
            f"{percentile}."
        )
    elif epss_record and not _source_is_current(epss_record):
        unknowns.append(_source_gap("epss", epss_record))
    elif not epss_record:
        unknowns.append("EPSS probability and percentile are unavailable.")

    kev_listed = False
    if kev_record and _source_is_current(kev_record):
        kev_listed = bool(kev)
        if kev_listed:
            details = [
                value
                for value in (
                    (
                        f"added {_text(kev.get('kev_date_added'))}"
                        if _text(kev.get("kev_date_added"))
                        else ""
                    ),
                    (
                        f"remediation due {_text(kev.get('kev_due_date'))}"
                        if _text(kev.get("kev_due_date"))
                        else ""
                    ),
                    (
                        f"ransomware use {_text(kev.get('kev_ransomware_use'))}"
                        if _text(kev.get("kev_ransomware_use"))
                        else ""
                    ),
                )
                if value
            ]
            suffix = f" ({'; '.join(details)})" if details else ""
            known.append(f"CISA KEV lists **{cve_id}** as known exploited{suffix}.")
        else:
            known.append(
                f"The current CISA KEV lookup has **no listing for {cve_id}**."
            )
    elif kev_record:
        unknowns.append(_source_gap("kev", kev_record))
    else:
        unknowns.append("CISA KEV listing status is unavailable.")

    associated_kbs = {
        _text(value).upper()
        for value in _sequence(nvd.get("associated_kbs"))
        if _text(value)
    }
    if not nvd_record:
        associated_kbs.update(
            _text(value).upper()
            for value in _sequence(legacy_cve.get("associated_kbs"))
            if _text(value)
        )
    for record in sources.get("msrc", ()):
        payload = _mapping(record.get("payload"))
        if _source_is_current(record):
            kb_id = _text(payload.get("kb_id") or record.get("identifier")).upper()
            if kb_id:
                associated_kbs.add(kb_id)
        else:
            unknowns.append(_source_gap("msrc", record))
    if associated_kbs:
        known.append(
            "Associated Microsoft security update"
            f"{'s' if len(associated_kbs) != 1 else ''}: "
            + ", ".join(sorted(associated_kbs))
            + "."
        )
    elif nvd_record and _source_is_current(nvd_record):
        known.append("No KB association is present in the current CVE metadata.")

    scoped_exposure = _mapping(detail.get("scoped_exposure")) or _mapping(
        exposure_data
    )
    scoped_status = (
        _text(detail.get("scoped_exposure_status"))
        or _text(exposure_status)
    ).casefold()
    query_cve = canonical_cve_id(
        scoped_exposure.get("query_cve_id")
        or _mapping(detail.get("source_state")).get("query_cve_id")
    )
    if query_cve and query_cve != cve_id:
        return ""
    rows = _matching_rows(scoped_exposure, cve_id)
    total_count = _count(scoped_exposure.get("total_count"))
    returned_count = _count(scoped_exposure.get("returned_count"))
    if returned_count is None:
        returned_count = len(rows)
    active_count = _count(scoped_exposure.get("affected_active_count"))
    target_kinds: set[str] = set()
    activity_states = [
        _text(row.get("current_state")).casefold()
        for row in rows
    ]
    known_activity = [
        state for state in activity_states if state not in _UNKNOWN_ACTIVITY_STATES
    ]
    if active_count is None and known_activity:
        active_count = sum(state == "active" for state in known_activity)

    scoped_empty = scoped_status == "empty"
    if scoped_empty:
        known.append(
            f"The authenticated scoped Exposure query reports no scoped findings "
            f"for {cve_id}; the submitted page snapshot may be stale."
        )
    elif scoped_status in {"ok", "partial"} or rows or total_count is not None:
        coverage_text = (
            f"The current scope contains **{total_count}** matching findings; "
            f"**{returned_count} records were inspected**."
            if total_count is not None
            else "The current scope has matching findings, but the total count is "
            f"unavailable; **{returned_count} records were inspected**."
        )
        active_text = (
            f" **{active_count} are active**."
            if active_count is not None
            else " The affected active count is unavailable."
        )
        known.append(coverage_text + active_text)
        severities = sorted(
            {
                _text(row.get("severity")).title()
                for row in rows
                if _text(row.get("severity"))
            }
        )
        if severities:
            known.append(
                "The inspected findings are "
                + ", ".join(f"**{item}**" for item in severities)
                + " severity."
            )
        target_kinds = {
            _text(row.get("target_kind")).casefold()
            for row in rows
            if _text(row.get("target_kind"))
        }
        if target_kinds == {"server"}:
            known.append("The inspected evidence identifies affected servers.")
        elif target_kinds == {"container_image"}:
            known.append(
                "The inspected records target container image findings."
            )
        if rows and not known_activity:
            unknowns.append(
                "Activity state is unavailable for the inspected findings."
            )
        workload_counts = [
            _count(row.get("represented_workload_count"))
            for row in rows
        ]
        known_workload_rows = [count for count in workload_counts if count is not None]
        represented_workloads = sum(known_workload_rows)
        unknown_workload_rows = len(rows) - len(known_workload_rows)
        if represented_workloads:
            known.append(
                f"The inspected findings contain **{represented_workloads}** "
                "represented workload associations; repeated workloads may appear "
                "across findings."
            )
        else:
            unknowns.append(
                "The running workload impact is unknown because the inspected findings "
                "contain no represented workload mapping."
            )
        if unknown_workload_rows:
            unknowns.append(
                f"Workload relationship counts are unavailable for "
                f"{unknown_workload_rows} inspected findings."
            )
        if total_count is None:
            unknowns.append("Total scoped finding coverage is unavailable.")
        elif returned_count < total_count:
            unknowns.append(
                f"{total_count - returned_count} scoped findings were not inspected "
                "in this bounded response."
            )
    else:
        coverage = _mapping(snapshot_coverage)
        visible = _count(coverage.get("visible_count"))
        total = _count(coverage.get("total_count"))
        unknowns.append(
            f"The current evidence cannot determine whether {cve_id} affects "
            "resources in this scope because scoped exposure and affected active "
            "finding counts are unavailable."
        )
        if visible is not None or total is not None:
            unknowns.append(
                "The page snapshot is retained only as non-authoritative visible "
                f"context ({visible or 0} visible of {total or 0} reported)."
            )

    for source, status in sorted((source_statuses or {}).items()):
        normalized_source = _text(source).casefold()
        normalized_status = _text(status).casefold()
        if (
            normalized_source in {"cve", "findings", "attack_path"}
            or normalized_status == "fresh"
            or normalized_source in sources
        ):
            continue
        unknowns.append(
            f"{normalized_source.upper()} metadata is unresolved because the page "
            f"reports {normalized_status or 'unknown'} freshness."
        )

    recommended_patch = _text(legacy.get("recommended_patch"))
    if kev_listed and not scoped_empty:
        due = _text(kev.get("kev_due_date"))
        recommendations.append(
            "Prioritize governed remediation for the known-exploited CVE"
            + (f" before the KEV due date {due}" if due else "")
            + "; validate the fix before rollout."
        )
    if epss_score is not None and epss_score >= 0.5 and not scoped_empty:
        recommendations.append(
            f"Treat the {_percent(epss_score)}% EPSS probability as elevated and "
            "prioritize active, reachable, or internet-exposed targets."
        )
    if base_score is not None and base_score >= 9 and not scoped_empty:
        recommendations.append(
            f"Treat CVSS {base_score:g} as critical remediation priority; verify "
            "the vendor-fixed package/version, rebuild affected images where "
            "applicable, and validate replacement deployment."
        )
    if associated_kbs and not scoped_empty:
        recommendations.append(
            "Validate the applicable associated update"
            f"{'s' if len(associated_kbs) != 1 else ''} "
            f"({', '.join(sorted(associated_kbs))}) through the governed remediation "
            "workflow."
        )
    elif recommended_patch and not scoped_empty:
        recommendations.append(
            f"Validate the scoped recommended fix `{recommended_patch}` before "
            "deployment."
        )
    if (
        epss_score is not None
        and epss_score < 0.5
        and kev_record
        and _source_is_current(kev_record)
        and not kev_listed
        and base_score is not None
        and base_score >= 9
        and not scoped_empty
    ):
        recommendations.append(
            "Do not treat the current low EPSS score and absent KEV listing as "
            "absence of risk; keep priority aligned to the critical CVSS impact."
        )
    if (
        not scoped_empty
        and any("workload impact is unknown" in item.casefold() for item in unknowns)
    ):
        if target_kinds == {"container_image"}:
            recommendations.append(
                "Map the affected image digests to deployed workloads before "
                "assigning production impact."
            )
        elif target_kinds == {"server"}:
            recommendations.append(
                "Map affected servers to business services and validate reachability "
                "before assigning production impact."
            )
        else:
            recommendations.append(
                "Map affected targets to deployed workloads before assigning "
                "production impact."
            )
    if not scoped_empty and total_count is not None and returned_count < total_count:
        recommendations.append(
            f"Inspect the remaining {total_count - returned_count} scoped findings "
            "through bounded pagination before declaring environment coverage complete."
        )
    if not recommendations:
        if scoped_empty:
            recommendations.append(
                "No scoped remediation target is established; continue monitoring "
                "the current CVE metadata and Exposure generation."
            )
        elif scoped_status not in {"ok", "partial"} and not rows:
            recommendations.append(
                "Restore the scoped Exposure query and unavailable external metadata "
                "before assigning impact or approving remediation."
            )
        else:
            recommendations.append(
                "Validate the available vendor fix against the affected scoped targets "
                "before approving remediation."
            )

    known = list(dict.fromkeys(known))
    unknowns = list(dict.fromkeys(unknowns))
    recommendations = list(dict.fromkeys(recommendations))
    sections = [
        f"**{cve_id}: what is known**\n\n"
        + "\n".join(f"- {item}" for item in known)
    ]
    if unknowns:
        sections.append(
            "**What is not known**\n\n"
            + "\n".join(f"- {item}" for item in unknowns)
        )
    sections.append(
        "**Recommended next steps**\n\n"
        + "\n".join(
            f"{index}. {item}"
            for index, item in enumerate(recommendations, 1)
        )
    )
    return "\n\n".join(sections)


__all__ = ["canonical_cve_id", "deterministic_cve_narrative"]
