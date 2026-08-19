# Semantic Knowledge Layer architecture

The Semantic Knowledge Layer is the sole read-only operational knowledge interface exposed to future Hermes agents. Microsoft Fabric Ontology remains authoritative for entities and relationships; OneLake remains canonical persistence. The layer builds ephemeral indexes and bounded caches, not another database.

The public framework uses the exact modules `semantic_engine`, `semantic_registry`, `semantic_models`, `query_cache`, `indexes`, and `validator`. Compatibility implementations remain in the established `semantic_cache`, `semantic_indexes`, and `semantic_validator` modules without duplicating state.

Standalone architecture artifact: `docs/semantic-knowledge-layer-architecture.html`.

```mermaid
flowchart LR
  ARG[Azure Resource Graph] --> OL[(OneLake Delta)]
  OL --> FO[Microsoft Fabric Ontology]
  FO --> SNAP[Governed semantic snapshot]
  OL --> FACTS[Inventory, compliance, health facts]
  SNAP --> IDX[Semantic indexes]
  FACTS --> IDX
  IDX --> MODELS[Domain semantic models]
  MODELS --> CONTEXT[Context builder]
  MODELS --> IMPACT[Impact analysis]
  MODELS --> RISK[Risk scoring]
  MODELS --> SEARCH[Semantic search]
  CONTEXT --> CACHE[Version-aware TTL cache]
  IMPACT --> CACHE
  RISK --> CACHE
  SEARCH --> CACHE
  CACHE --> API[SemanticEngine APIs]
  API --> TOOL[operations_analysis via Operations Agent]
  TOOL --> AGENTS[Hermes Operations Agent consumers]

  AGENTS -. blocked .-> ARG
  AGENTS -. blocked .-> OL
  AGENTS -. blocked .-> FO
```

The plugin no longer registers raw Semantic, Azure, Ontology, or Fabric mutation/status tools. Agents receive only `operations_analysis`; it consumes the Semantic Layer internally while Fabric synchronization remains separate operator CLI/API functionality.

## Semantic model diagram

```mermaid
classDiagram
  class ApplicationKnowledge
  class ServiceKnowledge
  class InfrastructureKnowledge
  class ComplianceKnowledge
  class PatchingKnowledge
  class OwnershipKnowledge
  class BusinessImpactKnowledge
  class ResourceHealthKnowledge
  class OperationalRiskKnowledge
  class DependenciesKnowledge
  class LifecycleKnowledge
  class CostKnowledge
  class SecurityKnowledge

  ApplicationKnowledge --> InfrastructureKnowledge
  ApplicationKnowledge --> OwnershipKnowledge
  ApplicationKnowledge --> ComplianceKnowledge
  ApplicationKnowledge --> PatchingKnowledge
  ApplicationKnowledge --> DependenciesKnowledge
  ServiceKnowledge --> ApplicationKnowledge
  ServiceKnowledge --> BusinessImpactKnowledge
  InfrastructureKnowledge --> ResourceHealthKnowledge
  InfrastructureKnowledge --> LifecycleKnowledge
  OperationalRiskKnowledge --> ComplianceKnowledge
  OperationalRiskKnowledge --> PatchingKnowledge
  OperationalRiskKnowledge --> SecurityKnowledge
  OperationalRiskKnowledge --> OwnershipKnowledge
  CostKnowledge --> ServiceKnowledge
```

All models are registered in `SemanticRegistry` with their required Ontology and operational-fact sources.

## Query flow

```mermaid
sequenceDiagram
  participant A as Hermes agent
  participant T as operations_analysis
  participant E as SemanticEngine
  participant C as SemanticCache
  participant I as SemanticIndexes
  participant O as Fabric Ontology snapshot

  A->>T: question + subject
  T->>E: query()
  E->>C: versioned lookup
  alt cache hit
    C-->>E: compact context
  else cache miss
    E->>I: indexed semantic traversal
    I-->>E: entities, facts, paths
    E->>E: context/risk/impact assembly
    E->>C: store with knowledge version + TTL
  end
  E-->>T: safe semantic projection + freshness
  T-->>A: operational knowledge
```

## Data and security boundaries

- Raw Azure payloads, tenant IDs, subscription IDs, lineage, and ingestion IDs never appear in agent responses.
- Internal indexes contain only the current active Ontology snapshot and governed operational facts.
- Cache entries are invalidated by knowledge version and bounded by TTL and LRU capacity.
- No semantic result is persisted as a competing system of record.
- Semantic snapshot validation rejects active dangling relationships before serving knowledge.
- Source collections, traversal nodes/depth, results, cache entries, and serialized public responses are bounded. Public strings and mapping keys redact literal or encoded ARM/GUID identifiers and fail closed on sanitized-key collisions.
- Subjects without resource evidence return `score=null`, `level=Unknown`, and no invented risk factors.

Fabric Ontology definition contract: https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition
