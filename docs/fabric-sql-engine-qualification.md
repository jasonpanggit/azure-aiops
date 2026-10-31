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
