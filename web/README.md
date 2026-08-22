# Azure AI Operations Workbench (Prompt 15)

Next.js 14 (App Router) + TypeScript + Fluent UI v9 + MSAL frontend for the
Hermes Operations API (`docs/OPERATIONS_API.md`). This is the UI foundation
only — it renders what the API can already answer and is explicit ("Not
Found In Codebase" style messaging) about the parts it cannot, rather than
fabricating data.

## Structure

```
web/
  src/
    app/                 # App Router routes
      page.tsx            # Operations dashboard (health, incidents, remediation, gaps)
      connections/        # Subscription connection health list
      search/             # Intent-driven operational search
      copilot/            # Operational Q&A shell (routes through /search today)
      layout.tsx           # Root layout: Providers -> ScopeProvider -> AppShell
    components/
      Providers.tsx        # MSAL provider + Fluent theme + error boundary composition root
      AuthGate.tsx          # Sign-in gate (or dev-token banner when MSAL isn't configured)
      AppShell.tsx           # Header, nav, scope selector, account badge
      ScopeSelector.tsx        # Global scope selector (9 dimensions)
      DataCard.tsx              # Standard loading/error/501/data tile shell
      ErrorBoundary.tsx          # Top-level React error boundary
      RequirePermission.tsx       # RBAC-gated UI affordance wrapper
    hooks/
      useApi.ts             # Fetch-on-deps-change hook, scope-aware
      useTelemetry.ts        # trackEvent/trackError (App Insights if present, console otherwise)
    lib/
      api-client.ts         # Envelope/error contract fetch wrapper (correlation ID, auth header)
      auth.ts                # MSAL config + getAccessToken() (falls back to dev token)
      permissions.ts          # Client-side mirror of reader/operator/admin roles
      scope.ts                 # SCOPE_DIMENSIONS + query serialization
      scope-context.tsx         # Global scope React context
      services.ts                # Typed wrappers per endpoint group (connections/context/operations/planned)
      types.ts                    # TS mirrors of api/models.py DTOs
```

## Running locally

```bash
cp .env.local.example .env.local
npm install
npm run start
```

The lockfile and local `.npmrc` use the public npm registry. If Defender prompts
for `ms-feed-*.pkgs.visualstudio.com`, refresh dependencies with the repo `.npmrc`
in effect so npm does not use a machine-level Azure DevOps registry override.

`npm run start` starts the web app. It does not start the API. In a second
terminal, start the local API from `web/`:

```bash
npm run start:api
```

`npm run start:api` reads `web/.env.local`. If `AZURE_SUBSCRIPTION_ID`,
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET` are set, it
injects a single local subscription connection that references the secret as
`env://AZURE_CLIENT_SECRET`, removes any previous fixture-only demo connection,
and runs initial discovery/sync against that subscription without persisting the
secret. If those values are absent or still placeholders, it falls back to
seeding `.hermes-local` from `tests/fixtures/mock_arg_responses.json`.

Both paths use token auth and local file-backed registry storage. Set
`HERMES_DEV_TOKEN=local-dev-token-1234` in `.env.local` to avoid `401`
responses from the browser.

Override `HERMES_API_HOST`, `HERMES_API_PORT`, `HERMES_API_TOKENS`, or
`HERMES_API_CORS_ORIGINS` when needed. For live Azure-backed local development,
run `HERMES_LOCAL_SEED=0 npm run start:api`; that preserves the existing
Postgres-backed registry path and live connection sync behavior.
Set `HERMES_LOCAL_AUTO_SYNC=0` to inject the SPN connection without syncing at
startup.

Without `NEXT_PUBLIC_ENTRA_CLIENT_ID` set, the app runs in **dev-token
mode**: a banner is shown and `HERMES_DEV_TOKEN` is sent as the
bearer token on every call. This must match a key configured in the API's
`HERMES_API_TOKENS` (see `docs/OPERATIONS_API.md`). Never use dev-token mode
against a production API.

## Testing

```bash
npm test        # vitest run — unit + component tests
npm run lint     # next lint
npm run build     # typecheck + production build
```

## Known gaps (by design, not oversight)

- **Search is intent-driven**, not free text — only ~7 phrases are
  supported server-side. The Search and Copilot pages surface the
  supported-phrase list and the API's actual 400 response rather than
  pretending to support arbitrary queries.
- **Network topology, traffic flow, network gaps, KBs, and CVEs** are
  501 contract stubs on the backend (Prompt 16/17 roadmap) — corresponding
  UI states show a roadmap-aware "not yet available" message via
  `DataCard`/`ErrorState`, never a fabricated value.
- **Patch exposure, lifecycle exposure, and predictive risk** have no
  backing endpoint at all (Not Found In Codebase) — their dashboard tiles
  say so explicitly.
- **Copilot** is not a conversational AI backend; it is a thin UI shell over
  the same `/search` intent endpoint, documented as such in the page itself.
