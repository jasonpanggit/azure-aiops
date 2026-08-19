# Lifecycle Intelligence Configuration Guide

## Fabric configuration

```yaml
fabric:
  lifecycle:
    enabled: true
    # Empty uses src/intelligence/lifecycle/default_catalog.json.
    # A custom path is resolved relative to this Fabric config file.
    catalog_path: ""
    approaching_months: 24
    near_months: 12
    critical_months: 6
```

Thresholds must be exact positive integers and descend: approaching > near > critical > 0. Booleans, fractional values, zero, and negative values fail closed during load and direct construction.

## Catalog schema

A governed catalog JSON file contains:

```json
{
  "schema_version": "1.0.0",
  "entries": [
    {
      "product": "Windows Server",
      "version": "2012 R2",
      "release_date": "2013-11-25",
      "mainstream_support_end": "2018-10-09",
      "extended_support_end": "2023-10-10",
      "last_update_date": "2026-08-18",
      "recommended_upgrade_path": "Windows Server 2025",
      "source_url": "https://learn.microsoft.com/lifecycle/products/windows-server-2012-r2",
      "default_support_channel": "extended",
      "notes": "Direct in-place upgrade eligibility must be validated."
    }
  ]
}
```

Dates are ISO dates. Source URLs must be HTTPS. Duplicate product/version entries, invalid dates, invalid URLs, or missing upgrade paths fail closed.

## Resource matching

The runtime consumes governed inventory fields in this order:

1. `lifecycle_product` / `lifecycle_version` stewardship overrides;
2. `os_name` / `os_version` from ARG or Arc inventory;
3. Kubernetes version from managed-cluster properties;
4. SQL version from governed SQL inventory fields;
5. otherwise `Unknown`.

Matching is exact after whitespace/case normalization. It does not infer versions from free-form names.

`support_channel` defaults to the catalog entry's governed `default_support_channel`. A resource override takes precedence. Set paid extended channels only when an authoritative entitlement or operating policy supports using the extended date; the packaged catalog does not assume Ubuntu ESM or RHEL ELS enrollment.

## Bounds

- `max_resources`: 5,000
- `max_history_rows`: 50,000
- `max_catalog_rows`: 5,000
- `max_output_items`: 100
- `max_serialized_bytes`: 1,000,000

Oversized snapshots fail before analysis.

Semantic inventory bounds are checked before resource-context enrichment, preventing source-driven work amplification. Patch compliance scores must be integer values from 0 to 100; ownership and exposure flags must be real Booleans.

## Hermes authorization

Expose only `operations_analysis` through the `azure_operational_context` toolset. Gateway/toolset authorization determines which principals may view the configured enterprise portfolio. Lifecycle commands require `subject=Enterprise` and `subject_type=LifecyclePortfolio`; arbitrary subscription/application labels are rejected rather than interpreted as authorization scopes.
