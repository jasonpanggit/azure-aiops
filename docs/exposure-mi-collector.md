# Fixed Exposure MI collector

`scripts/exposure_mi_collector.py` is a corrected-target, read-only diagnostic
collector. Unified Deployment owns its immutable image, fixed manual Job and
execution receipts. It must not run through production container exec or with
execution-time identity, command or environment overrides.

The collector requires the exact roots, Fabric target, application managed
identity and immutable source revision encoded in `validate_runtime`. It uses
`ManagedIdentityCredential` directly, never a delegated credential or fallback.
Malformed configuration fails before any source read.

OneLake reads use the actual Data Lake SDK with `offset=0`, a maximum requested
range of 4 MiB plus one sentinel byte, one download worker, no retries, a 10-second
connection timeout and a 20-second read timeout. Both reported and downloaded
document sizes must stay within 4 MiB.

The existing SQL readiness probe retains its 30-second connection/statement
timeout. Subsequent aggregate and benchmark SQL use 20-second connection/statement
timeouts, encrypted TLS with server-certificate verification, bound parameters and
bounded result transfers. These provider timeouts are not the two-second Exposure
latency SLO. A 900-second process alarm bounds the whole collector; the fixed Job
also needs its independently configured hard replica deadline.

The CLI emits one sanitized JSON report and exits zero only for collected,
unchanged observations. Readiness, configuration, transport, deadline and SQL
failures exit nonzero. Aggregate and benchmark provider errors retain SQLSTATE
without exporting provider error text. Pointer and registry hashes are checked
again after collection, including after a benchmark SQL failure.
ODBC date/datetime values are emitted as ISO strings without inventing a timezone.
Decimal values are explicit decimal strings preserving all precision and scale,
never binary floats; nonfinite decimals fail closed. Null values remain JSON null.
Unsupported output types fail closed with a sanitized nonzero report rather than
being stringified or escaping as a serialization traceback.
HTTP provider failures retain a numeric status when present and only an allowlisted
service error code. Error messages, unknown codes, tokens and config are omitted.
An exception type alone, unavailable MI endpoint, absent source or missing table
does not establish a provider authorization denial.

Run the offline runtime contracts with:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:. .venv/bin/pytest \
  -o addopts='' -q tests/test_exposure_mi_collector.py \
  tests/test_exposure_mi_collector_runtime.py
```

These tests exercise the real CLI, managed-identity constructor, Data Lake SDK
HEAD/ranged-GET pipeline, SQL reader, readiness and benchmark compiler. Only token
acquisition, HTTP transport and DBAPI are supplied offline. They need no native
ODBC driver and do not prove cloud identity authorization or MI execution.
The 185-image/zero-server live corpus cannot qualify the 100k benchmark.
Fixture scale qualification, live source coverage and operator acceptance remain
separate evidence. Reports always retain `production_certified=false` and
`phase4_ready=false`.
