# Local SQL control engine tests

The **SQL Server engine tests (Linux x64)** workflow runs the opt-in SQL control
integration, adversarial transaction/permission, ownership-chain and reserved
identifier suites against a disposable Microsoft SQL Server Developer container
on a native `ubuntu-24.04` x86-64 GitHub-hosted runner. The image is pinned by
digest. ODBC Driver 18 is installed in the runner; the server's randomly assigned
host port is bound only to `127.0.0.1`.

The workflow creates only `publication_protocol_test` inside that new container.
Its `FABRIC_PUBLICATION_SQL_REQUIRED=1` setting turns missing connection
configuration, an unavailable ODBC driver or an unreachable engine into failures
instead of skips. A JUnit gate also rejects skipped, failed or missing cases.
The disposable container is removed by an unconditional cleanup step.
Pytest stops on the first failure, emits verbose traces and a 60-second
faulthandler stack, and is bounded by a ten-minute timeout with a 30-second
termination grace. Logs and JUnit are uploaded even after a step failure;
external hard cancellation can still prevent artifact upload.
The local fixture disables ODBC pooling before opening any connection to isolate
transactional bootstrap sessions from autocommit runtime sessions. An engine
regression checks zero entry transaction count across that lifecycle; catalog
coverage rejects coherent destination substitution and conflicting reseals of
the same attempt while preserving the target and the original seal.
The suite also executes a five-second `WAITFOR` through the production SQL
client with a one-second statement timeout and requires the expected ODBC
timeout, one execution, a sanitized failure and closed resources.

These are real SQL-engine checks of the local control schema, stored procedures,
role permissions, transaction behavior, locking/concurrency and rollback. Fixture
resource IDs, storage descriptors and provider-readback values are explicitly
synthetic and test-local. The workflow performs no Azure, Fabric, Blob or Entra
operations and grants no deployed identity. Its artifacts are test reports, not
publication, WORM, runtime, deployment or production-acceptance evidence.

The SQL/Blob broker metadata engine test is intentionally excluded until its
composition module and associated tests are integrated into the same source
revision. The workflow cannot qualify code that is absent from that revision.
