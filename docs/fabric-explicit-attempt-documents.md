# Explicit credentials for immutable-attempt documents

This is a non-activated source capability, not production composition or proof
of access. Legacy `OneLakeDocumentStore(root)` behavior is unchanged.

`OneLakeDocumentStore.remote(root, credential=...)` requires an application-owned,
synchronous token credential. It never constructs `DefaultAzureCredential` or
falls back after authentication, transport, or SDK construction failures. Root
identity is pinned to canonical
`abfss://<lowercase-workspace-UUID>@onelake.dfs.fabric.microsoft.com/<lowercase-item-UUID>/Files/<namespace>`.
Namespace components contain only ASCII letters, digits, underscores and hyphens.
Names, alternate schemes/hosts, traversal, encoding, query/fragment, empty
components and trailing separators are refused before opening an SDK client.
Document operations retain the existing ETag-pinned reads, create-only and
conditional-replace semantics. Explicit reads propagate failures rather than
returning empty successful state.

Use the store as a context manager or call `close()`. The SDK client is created
lazily, owned by the store and closed once; the borrowed application credential
is never closed. Shutdown serializes with document/directory operations.
Operations on a closed store refuse without contacting the provider. Credentials
and stores must not escape their application-owned lifetime.

`bind_remote_attempt_documents(...)` borrows two credentials and requires exact
stage/journal roots plus distinct canonical declared owner object IDs. It refuses
equal, ancestor/descendant and case-aliased roots before SDK use. Its context owns
both explicit stores and exposes a narrow `StagedGenerationReader` for staged
generation/authority reads, plus separate journal documents usable by
`OneLakeAttemptLifecycleJournal`. The reader shares the publisher's existing exact
read implementation without constructing `DatasetStore`, `resolve_fs`, or a
mutation publisher. The journal's per-target CAS, dispatch receipts, HOLD and
exact-pin recovery rules are unchanged.

Declared owner IDs are trusted application inputs, not token/RBAC evidence.
Python credential object equality or inequality proves nothing about principal
identity. Stage and journal owner declarations are separate from the broker
worker identity. Commissioning must independently establish actual token
principals, staged read-only permissions, journal CAS permissions and exact
namespace access. The narrow Python reader is a capability interface, not a
provider privilege sandbox.

No runtime factory, CLI, legacy worker, pointer/reader/graph integration, grants,
provider actions or activation is added. Existing local-root mutation guards,
fixed-table defaults and production gates remain unchanged. Historical recovery
does not establish current active authority or read access.
