"""Collect read-only Phase 7 evidence; never qualify an unexecuted acceptance gate."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from api.scope import Scope

FAMILIES = ("os", "software", "paas", "resources")
FAILURE_CODES = {
    "delegated_token_unavailable", "delegated_token_target_mismatch",
    "inventory_rows_missing", "effective_scope_mismatch",
    "generation_or_query_version_missing", "pagination_invalid", "page_bound_invalid",
    "page_count_mismatch", "resource_outside_scope", "raw_properties_exposed",
    "source_evidence_missing", "source_clock_missing", "source_status_missing",
    "one_explicit_subscription_required", "collector_bounds_invalid",
    "generation_changed_during_collection", "duplicate_or_missing_identity",
    "offset_mismatch", "total_changed_during_collection", "silent_truncation",
    "pagination_not_advancing", "snapshot_row_budget_exhausted",
    "raw_properties_not_preserved", "snapshot_changed_during_collection",
    "browser_receipt_schema_invalid", "browser_rows_not_rendered",
    "browser_api_mismatch", "unexpected_generation", "snapshot_api_generation_mismatch",
    "snapshot_api_count_mismatch", "browser_api_origin_mismatch",
    "paas_group_budget_exhausted", "paas_detail_unavailable",
    "paas_detail_page_budget_exhausted", "paas_identity_set_mismatch",
    "snapshot_paas_identity_set_mismatch",
}


def _source_reason(row: dict[str, Any]) -> str:
    if row.get("error") == "No Log Analytics workspace was discovered in this connection's scope":
        return "no_discovered_configurationdata_destination"
    if row.get("error") == "No Azure Monitor Logs client is configured":
        return "logs_client_unconfigured"
    return "provider_error_recorded" if row.get("error") else "no_error_recorded"


def digest(value: Any) -> str:
    """Hash canonical evidence without exporting source payloads."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def summarize_response(payload: dict[str, Any], scope: Scope) -> dict[str, Any]:
    """Validate and summarize one exact scoped inventory API page."""
    data = payload["data"]
    pagination = payload["pagination"]
    rows = data.get("resources", data.get("groups"))
    if not isinstance(rows, list):
        raise TypeError("inventory_rows_missing")
    if payload.get("scope") != scope.to_dict() or data.get("requested_scope") != scope.to_dict():
        raise ValueError("effective_scope_mismatch")
    if not data.get("generation_id") or not data.get("query_version"):
        raise ValueError("generation_or_query_version_missing")
    for key in ("offset", "limit", "total"):
        if type(pagination.get(key)) is not int or pagination[key] < 0:
            raise ValueError("pagination_invalid")
    if pagination["limit"] < 1 or len(rows) > pagination["limit"]:
        raise ValueError("page_bound_invalid")
    expected = min(pagination["limit"], max(0, pagination["total"] - pagination["offset"]))
    if len(rows) != expected:
        raise ValueError("page_count_mismatch")
    for row in data.get("resources", []):
        if not scope.matches({"subscription": row.get("subscription_id")}):
            raise ValueError("resource_outside_scope")
        if any(key in row for key in ("properties", "tags", "provider_payload_json")):
            raise ValueError("raw_properties_exposed")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("source_evidence_missing")
    clocks = [
        {"timestamp": item.get("timestamp"), "freshness": item.get("freshness")}
        for item in evidence
    ]
    if any(not item["timestamp"] or not item["freshness"] for item in clocks):
        raise ValueError("source_clock_missing")
    statuses = data.get("source_status", data.get("family_availability"))
    if not isinstance(statuses, dict) or not statuses:
        raise ValueError("source_status_missing")
    # Never export provider error text, names, resource IDs, or raw properties.
    status_summary = {
        family: {
            **{key: row[key] for key in ("state", "row_count", "workspace_count") if key in row},
            "reason": _source_reason(row),
        }
        for family, row in statuses.items()
        if isinstance(row, dict)
    }
    return {
        "scope": scope.to_dict(),
        "generation_id": data["generation_id"],
        "query_version": data["query_version"],
        "pagination": pagination,
        "page_rows": len(rows),
        "rows_sha256": digest(rows),
        "source_clocks": clocks,
        "source_status": status_summary,
        "warnings_count": len(payload.get("warnings", [])),
    }


def collect_api(
    client: httpx.Client, scope: Scope, *, page_size: int = 25, max_pages: int = 20
) -> dict[str, Any]:
    """Read bounded complete pages and detect generation drift, duplicates, and truncation."""
    if set(scope.to_dict()) != {"subscription"} or len(scope.values("subscription")) != 1:
        raise ValueError("one_explicit_subscription_required")
    if not 1 <= page_size <= 100 or not 1 <= max_pages <= 100:
        raise ValueError("collector_bounds_invalid")
    params: dict[str, Any] = {
        "subscription": next(iter(scope.values("subscription"))), "limit": page_size,
    }
    receipts: dict[str, Any] = {}
    generation = None
    paas_keys: list[str] = []
    paas_resource_ids: set[str] = set()
    for family in FAMILIES:
        pages = []
        seen: set[str] = set()
        offset = 0
        for _ in range(max_pages):
            response = client.get(f"/api/v1/inventory/{family}", params={**params, "offset": offset})
            if response.status_code != 200:
                receipts[family] = {"status": "blocked", "http_status": response.status_code}
                break
            payload = response.json()
            receipt = summarize_response(payload, scope)
            current = (receipt["generation_id"], receipt["query_version"])
            if generation is None:
                generation = current
            if current != generation:
                raise ValueError("generation_changed_during_collection")
            rows = payload["data"].get("resources", payload["data"].get("groups"))
            if family == "paas":
                paas_keys.extend(str(row.get("key") or "") for row in rows)
            if family == "resources":
                paas_resource_ids.update(
                    str(row["resource_id"]).casefold() for row in rows if row.get("family") == "paas"
                )
            keys = [str(row.get("resource_id") or row.get("key") or "").casefold() for row in rows]
            if any(not key for key in keys) or len(set(keys)) != len(keys) or seen.intersection(keys):
                raise ValueError("duplicate_or_missing_identity")
            seen.update(keys)
            if receipt["pagination"]["offset"] != offset:
                raise ValueError("offset_mismatch")
            if pages and receipt["pagination"]["total"] != pages[0]["pagination"]["total"]:
                raise ValueError("total_changed_during_collection")
            pages.append(receipt)
            next_offset = receipt["pagination"].get("next_offset")
            if next_offset is None:
                if len(seen) != receipt["pagination"]["total"]:
                    raise ValueError("silent_truncation")
                receipts[family] = {"status": "observed", "pages": pages, "total": len(seen)}
                break
            if next_offset != offset + len(rows) or next_offset <= offset:
                raise ValueError("pagination_not_advancing")
            offset = next_offset
        else:
            receipts[family] = {"status": "blocked", "reason": "page_budget_exhausted", "pages": pages}
    if all(receipts[family]["status"] == "observed" for family in ("paas", "resources")):
        detail_ids: set[str] = set()
        if len(paas_keys) > 100:
            raise ValueError("paas_group_budget_exhausted")
        for key in paas_keys:
            offset = 0
            group_total = None
            for _ in range(max_pages):
                response = client.get(
                    f"/api/v1/inventory/paas/{quote(key, safe='')}",
                    params={**params, "offset": offset},
                )
                if response.status_code != 200:
                    raise ValueError("paas_detail_unavailable")
                payload = response.json()
                data = payload["data"]
                # This existing detail route can carry raw properties. They
                # stay in memory; only identity-set hashes leave the collector.
                public = {**payload, "data": {**data, "resources": [
                    {name: value for name, value in row.items()
                     if name not in ("properties", "tags", "provider_payload_json")}
                    for row in data["resources"]
                ]}}
                receipt = summarize_response(public, scope)
                if (receipt["generation_id"], receipt["query_version"]) != generation:
                    raise ValueError("generation_changed_during_collection")
                if receipt["pagination"]["offset"] != offset:
                    raise ValueError("offset_mismatch")
                if group_total is not None and receipt["pagination"]["total"] != group_total:
                    raise ValueError("total_changed_during_collection")
                group_total = receipt["pagination"]["total"]
                ids = [str(row["resource_id"]).casefold() for row in data["resources"]]
                if len(set(ids)) != len(ids) or detail_ids.intersection(ids):
                    raise ValueError("duplicate_or_missing_identity")
                detail_ids.update(ids)
                next_offset = receipt["pagination"].get("next_offset")
                if next_offset is None:
                    if offset + len(ids) != receipt["pagination"]["total"]:
                        raise ValueError("silent_truncation")
                    break
                if next_offset != offset + len(ids) or next_offset <= offset:
                    raise ValueError("pagination_not_advancing")
                offset = next_offset
            else:
                raise ValueError("paas_detail_page_budget_exhausted")
        if detail_ids != paas_resource_ids:
            raise ValueError("paas_identity_set_mismatch")
        receipts["paas"]["identity_comparison"] = {
            "groups": len(paas_keys), "detail_resources": len(detail_ids),
            "resources_family_count": len(paas_resource_ids),
            "identity_set_sha256": digest(sorted(detail_ids)), "exact_match": True,
        }
    return receipts


def collect_snapshot(root: str, scope: Scope) -> dict[str, Any]:
    """Compare a stable source snapshot to its internal read-port projection, without writes."""
    from intelligence.inventory.models import ResourceObservation
    from intelligence.inventory.read_port import InventoryReadPort
    from intelligence.inventory.service import InventoryService
    from storage.datasets import DatasetStore

    store = DatasetStore(root)
    before = store.current_generation()
    if before is None:
        return {"status": "blocked", "reason": "snapshot_absent"}
    service = InventoryService.from_store(store)
    if service is None:
        return {"status": "blocked", "reason": "snapshot_empty"}
    port = InventoryReadPort(service)
    logical = "inventory/resource_observations"
    source_rows = store.read_datasets([logical], generation=before)[logical]
    if not source_rows:
        physical = "inventory_resource_observations"
        source_rows = store.read_datasets([physical], generation=before)[physical]
    raw = [row for row in source_rows if scope.matches({"subscription": row.get("subscription_id")})]
    if len(raw) > 5000:
        raise ValueError("snapshot_row_budget_exhausted")
    matches = 0
    temporal_complete = 0
    for raw_row in raw:
        row = ResourceObservation.from_fabric_row(raw_row)
        projected = port.get_resource(scope, row.resource_id)
        if projected is None or projected.get("properties") != row.provider_payload:
            raise ValueError("raw_properties_not_preserved")
        matches += 1
        if all(raw_row.get(key) for key in ("timestamp", "change_version", "ingestion_run_id", "observed_at")):
            temporal_complete += 1
    resources = service.resources(scope, limit=None)["data"]["resources"]
    if store.current_generation() != before:
        raise ValueError("snapshot_changed_during_collection")
    return {
        "status": "observed",
        "generation_id": service.generation_id,
        "query_version": service.query_version,
        "scope": scope.to_dict(),
        "resource_count": len(resources),
        "paas_identity_set_sha256": digest(sorted(
            str(row["resource_id"]).casefold() for row in resources if row.get("family") == "paas"
        )),
        "raw_properties_compared": matches,
        "temporal_identity_complete": temporal_complete,
        "temporal_identity_total": len(raw),
        "provider_watermark_advancement": "unproved",
        "graph_pipeline_viability": "unproved",
    }


def compare_browser(browser: dict[str, Any], api: dict[str, Any]) -> dict[str, Any]:
    """Compare actual browser-captured first pages, not a synthetic success flag."""
    if browser.get("schema") != "inventory-browser-v1":
        raise ValueError("browser_receipt_schema_invalid")
    compared = []
    for family in FAMILIES:
        capture = browser.get("families", {}).get(family)
        observed = api.get(family, {})
        if not capture or observed.get("status") != "observed":
            continue
        if capture.get("rendered_rows_match") is not True:
            raise ValueError("browser_rows_not_rendered")
        first = observed["pages"][0]
        for key in ("scope", "generation_id", "query_version", "pagination", "rows_sha256"):
            if capture.get(key) != first.get(key):
                raise ValueError("browser_api_mismatch")
        compared.append(family)
    return {"status": "observed" if compared else "unproved", "families_compared": compared,
            "all_four_families": len(compared) == len(FAMILIES), "screen_reader_acceptance": "unproved"}


def _token(tenant: str, subscription: str, audience: str) -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--subscription", subscription,
         "--resource", audience, "-o", "json"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        raise ValueError("delegated_token_unavailable")
    token = json.loads(result.stdout)["accessToken"]
    part = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    # A target-confusion guard only; the API, not this decode, verifies authentication.
    allowed_audiences = {audience}
    if audience.startswith("api://"):
        allowed_audiences.add(audience.removeprefix("api://"))
    if claims.get("tid") != tenant or claims.get("aud") not in allowed_audiences:
        raise ValueError("delegated_token_target_mismatch")
    return token


def main() -> int:
    """Collect explicit-target evidence with bounded GET-only transport and sanitized output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--expected-generation", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--snapshot-root")
    parser.add_argument("--browser-receipt", type=Path)
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = urlsplit(args.api_base)
    if target.scheme != "https" or not target.hostname or target.username or target.query or target.fragment or target.path not in ("", "/"):
        parser.error("--api-base must be an explicit HTTPS origin")
    scope = Scope.from_mapping({"subscription": [args.subscription]})
    record: dict[str, Any] = {
        "schema": "inventory-evidence-v1", "collected_at": datetime.now(UTC).isoformat(),
        "target": {"api_origin": args.api_base, "tenant": args.tenant, "revision": args.revision,
                   "image_digest": args.image_digest, "binding": "operator_supplied"},
        "scope": scope.to_dict(), "phase7_acceptance": "unproved",
        "snapshot": {"status": "unproved"}, "browser": {"status": "unproved"},
        "refresh_and_lkg": "unproved", "graph_pipeline_viability": "unproved",
    }
    try:
        token = _token(args.tenant, args.subscription, args.audience)
        with httpx.Client(base_url=args.api_base, headers={"Authorization": f"Bearer {token}"},
                          timeout=30, follow_redirects=False) as client:
            record["api"] = collect_api(client, scope, page_size=args.page_size, max_pages=args.max_pages)
        for value in record["api"].values():
            if any(page["generation_id"] != args.expected_generation for page in value.get("pages", [])):
                raise ValueError("unexpected_generation")
        if args.snapshot_root:
            record["snapshot"] = collect_snapshot(args.snapshot_root, scope)
            if record["snapshot"].get("generation_id") != args.expected_generation:
                raise ValueError("snapshot_api_generation_mismatch")
            resources = record["api"].get("resources", {})
            if resources.get("status") != "observed" or record["snapshot"]["resource_count"] != resources["total"]:
                raise ValueError("snapshot_api_count_mismatch")
            paas = record["api"].get("paas", {}).get("identity_comparison", {})
            if record["snapshot"]["paas_identity_set_sha256"] != paas.get("identity_set_sha256"):
                raise ValueError("snapshot_paas_identity_set_mismatch")
        if args.browser_receipt:
            browser = json.loads(args.browser_receipt.read_text())
            if browser.get("api_origin") != args.api_base.rstrip("/"):
                raise ValueError("browser_api_origin_mismatch")
            record["browser"] = compare_browser(browser, record["api"])
        record["collection_status"] = (
            "observed" if all(value["status"] == "observed" for value in record["api"].values()) else "blocked"
        )
    except (ValueError, KeyError, TypeError, httpx.HTTPError, OSError, subprocess.TimeoutExpired) as exc:
        record["collection_status"] = "blocked"
        record["failure_type"] = type(exc).__name__
        # Only code-owned errors can enter the persisted evidence.
        record["failure_code"] = str(exc) if str(exc) in FAILURE_CODES else "collection_failed"
    args.output.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    return 0 if record["collection_status"] == "observed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
