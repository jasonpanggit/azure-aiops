# Manual publication-review validation

`aiops-publication-validate` is a default-off, read-only operator command. It
validates one fresh `admit` review against the live signed maintenance release,
revocation state, SQL session, and sealed attempt catalog. It does not expose
grant or revoke operations, and a successful result is diagnostic only; it is
not reusable authorization. Grant issuance always repeats validation through a
separate authority composition.

The command requires the `fabric-sql` optional dependency and these environment
variables:

- `ONTOLOGY_PUBLICATION_VALIDATION_CONFIG`: absolute path to strict
  `publication-authority-validation/v1` JSON.
- Exactly one existing trust source: `ONTOLOGY_MAINTENANCE_TRUST_CONFIG` or
  `ONTOLOGY_MAINTENANCE_TRUST_CONFIG_SECRET_ID`, using the existing production
  trust format. A Key Vault source is read with the configured reader identity.
- `AZURE_CLIENT_ID`, if set, must match the reader UAI client ID in the
  validation config.

The validation JSON has exactly these fields:

```json
{
  "schema": "publication-authority-validation/v1",
  "reader_client_id": "<reader user-assigned managed identity client ID>",
  "target_id": "<canonical ontology target UUID>",
  "sql_target": {
    "workspace_id": "<Fabric workspace UUID>",
    "item_id": "<Fabric SQLDatabase item UUID>",
    "server": "<SQLDatabase server FQDN>",
    "database": "<SQLDatabase name>"
  },
  "fabric_item_metadata": {
    "type": "SQLDatabase",
    "id": "<same SQLDatabase item UUID>",
    "workspaceId": "<same Fabric workspace UUID>",
    "properties": {
      "databaseName": "<same SQLDatabase name>",
      "serverFqdn": "<same SQLDatabase server FQDN>"
    }
  },
  "expected_target": {
    "tenant_id": "<tenant UUID>",
    "subscription_id": "<subscription UUID>",
    "connection_id": "<Fabric connection ID>",
    "workspace_id": "<ontology workspace UUID>",
    "item_id": "<ontology item UUID>",
    "definition_fingerprint": "<pinned definition fingerprint>"
  },
  "review_path": "<absolute path to operator-owned signed review JSON>",
  "revocation_path": "<absolute path to operator-owned revocation JSON>"
}
```

Obtain `fabric_item_metadata` from the exact Fabric SQLDatabase item and keep
the configuration and source files in operator-owned, read-only mounts. Do not
copy example, test, or prior-session trust, review, revocation, session, or
catalog values into production. Missing or stale inputs fail closed.

Run manually in a fresh process with only the reader UAI and registry-pull
identity available. ODBC pooling is disabled before any database connection;
the SQL client also checks the database and server-observed client SID on every
connection. The SQL principal must remain limited to `ReadControl` and
`ReadAttempt`. No authority identity is configured or available to this
command.

```sh
aiops-publication-validate
```

Exit code `0` with `{"status":"PASS", ...}` means only that this exact read-only
validation completed. Exit code `1` or `2` with `{"status":"FAIL", ...}` means
validation did not pass. This command does not deploy an image, create a job,
start a job, change Azure permissions, or qualify grant/revocation, retention,
or publication behavior.
