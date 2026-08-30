# AIOps Operations Graph — Repository Structure

## 1. Intent

This is the target repository layout for delivery. The discovery phase creates documentation only; the directories below are planned, not an instruction to generate implementation scaffolding now.

```text
aiops-operations-graph/
├── ARCHITECTURE.md
├── ONTOLOGY_SCHEMA.md
├── DATA_SOURCES.md
├── AZURE_MCP_CAPABILITIES.md
├── FABRIC_INTEGRATION.md
├── IMPLEMENTATION_PLAN.md
├── REPOSITORY_STRUCTURE.md
├── BACKLOG.md
├── README.md                         # project entry point (future)
├── SECURITY.md                       # threat/reporting model (future)
├── docs/
│   ├── adr/                          # numbered architecture decisions
│   ├── operations/                   # SLOs, support, recovery, stewardship
│   ├── privacy/                      # data classification and minimization
│   └── diagrams/                     # source-controlled diagrams
├── ontology/
│   ├── logical/                      # versioned logical entity/edge contracts
│   ├── physical/                     # Fabric physical-name/type mappings
│   ├── mappings/                     # source-to-ontology mapping specifications
│   ├── policies/                     # confidence, precedence, expiry, review
│   └── examples/                     # synthetic examples only
├── queries/
│   ├── arg/                          # versioned read-only ARG discovery queries
│   ├── kql/                          # read-only aggregate KQL queries
│   └── validation/                   # source/curated reconciliation queries
├── infrastructure/
│   ├── bicep/                        # Azure managed-service provisioning
│   │   ├── modules/
│   │   └── environments/
│   ├── fabric/                       # Fabric item/deployment definitions
│   └── policy/                       # Azure Policy/RBAC definitions
├── src/
│   ├── resource-discovery/
│   ├── dependency-discovery/
│   ├── business-mapping/
│   ├── incident-learning/
│   ├── ontology-steward/
│   ├── fabric-ontology-writer/
│   ├── foundry-agent-integration/
│   └── shared-contracts/
├── tests/
│   ├── contract/
│   ├── unit/
│   ├── integration/
│   ├── data-quality/
│   ├── security/
│   └── evaluation/                   # agent grounding/answer evaluations
├── pipelines/
│   ├── templates/
│   ├── validation/
│   └── release/
├── runbooks/
│   ├── source-failure/
│   ├── stale-graph/
│   ├── rollback/
│   └── stewardship/
└── samples/
    └── synthetic/                    # no production exports or secrets
```

## 2. Ownership boundaries

| Area | Owns | Must not own |
|---|---|---|
| `ontology/` | semantic contract, mappings, scoring policy | source credentials or copied production data |
| `queries/` | reviewed read-only query definitions | generic telemetry ingestion |
| `infrastructure/` | managed Azure/Fabric configuration | manually exported secrets |
| engine folders | adapters and domain decisions | duplicate source systems of record |
| `shared-contracts/` | small stable event/assertion contracts | shared business logic dumping ground |
| `tests/evaluation/` | grounded-agent and confidence evaluation sets | real sensitive incidents |
| `runbooks/` | operating this platform | replacing enterprise operational runbooks |

## 3. Component packaging rule

Each future component should be independently deployable and contain:

- a narrow source adapter;
- contract validation;
- idempotency/watermark behavior;
- OpenTelemetry instrumentation;
- health and reconciliation checks;
- no raw secret or production payload fixtures.

Business rules that define ontology semantics belong under `ontology/policies`, not embedded independently in every adapter.

## 4. Environment strategy

- `dev`: synthetic or approved non-production sources; preview feature experimentation.
- `test`: representative scale and contract tests; no live production mutations.
- `prod`: least-privilege read identities, controlled Fabric publication, steward workflow.

Environment configuration references managed identities, Key Vault secret names, scopes, and Fabric workspace/item IDs. Secret values never enter Git.

## 5. Branching and release

Recommended trunk-based flow:

- short-lived feature branches;
- required contract/data-quality/security checks;
- architecture decision record for source-of-truth or ontology semantic changes;
- immutable release artifact and schema version;
- staged deployment: dev → test → production;
- rollback of both runtime and ontology projection version.

## 6. Documentation rules

- Root artifacts describe current approved architecture.
- ADRs record decisions and supersession.
- Source capabilities include “last verified” date and official references.
- Preview features are visibly labeled.
- Examples are explicitly synthetic.
- No document claims a connector/tool exists without a tested capability or authoritative reference.

## 7. Data and generated-artifact policy

Do not commit:

- ARG/LAW/App Insights/Sentinel exports from production;
- ServiceNow tickets or Entra directory dumps;
- credentials, tokens, connection strings, or MCP client configs containing secrets;
- generated OneLake data files;
- model prompts containing sensitive incident content;
- agent traces with unredacted source payloads.

Commit schemas, mappings, safe query definitions, synthetic fixtures, quality expectations, and evaluation rubrics.

## 8. Initial documentation-only state

At the end of architectural discovery, the repository should contain exactly the requested root architecture artifacts. Implementation folders are created only when the corresponding implementation phase begins and after the relevant decision gates in `IMPLEMENTATION_PLAN.md` are approved.
