# Graph Report - src  (2026-08-22)

## Corpus Check
- 208 files · ~118,019 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2649 nodes · 7647 edges · 103 communities (90 shown, 13 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 1103 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Predictive Intelligence
- Address Spec
- Semantic Engine
- Operational Reasoner
- Normalize py
- Get
- Network Snapshot
- Credential Reference
- Fabric Sync Service
- Network init py
- Connections py
- Load
- Network Security Rule
- Dependencies py
- Credential Resolver
- Semantic Indexes
- Api runtime py
- Onboarding runtime py
- Value Error
- Network models py
- Incident intelligence py
- Patch intelligence py
- Onboarding init py
- Api Error
- Fabric runtime py
- CVE
- Scope
- Onboarding service py
- Network Gap Analyzer
- Operations Agent
- Patch Intelligence
- EOL Catalog
- Incident Intelligence
- Remediation planner py
- Context py
- Registry Store
- Lifecycle Intelligence
- Foundry agent py
- Vulnerability py
- Delta Writer
- Ontology Validator
- Sync py
- Dataset mapper py
- Dataset Store
- Subscription Connection
- Entity builder py
- Change intelligence py
- Ontology Query Service
- Ingestion Service
- Vulnerability models py
- Any
- One Lake Writer
- Change Intelligence
- Remediation Planner
- Port Spec
- Any
- Lifecycle intelligence py
- Get requested scope
- Query Spec
- Relationship builder py
- Evidence
- Init
- Predictive Context Builder
- Incident engine py
- Event Timeline Engine
- Ontology Publisher
- Evidence py
- Ask
- Context Query Service
- Quality Report
- Plan Repository
- Any
- Semantic Cache
- Normalize
- Hermes arg connector service
- Run Lock
- Change Classifier
- Incident Engine
- Read scope
- Change Correlator
- Ontology Manager
- Root Cause Engine
- Remediation Opportunity Engine
- Resolve fs
- Blast Radius Engine
- Causality Graph
- Approval Engine
- Change Summary Engine
- Change Trend Engine
- Lifecycle Trend Engine
- Modernization Engine
- Resource compliance
- Dependency Analyzer
- Lifecycle Summary Engine
- Patch Correlator
- Risk Analyzer
- Scrub
- Baseline Engine
- Analyze
- Window
- Generate ontology metadata
- Build
- Agents init py

## God Nodes (most connected - your core abstractions)
1. `SubscriptionConnection` - 81 edges
2. `SemanticEngine` - 79 edges
3. `IncidentIntelligence` - 70 edges
4. `_get()` - 57 edges
5. `AddressSpec` - 55 edges
6. `NetworkSnapshot` - 55 edges
7. `ApiError` - 50 edges
8. `CredentialReference` - 49 edges
9. `Scope` - 47 edges
10. `SyncState` - 45 edges

## Surprising Connections (you probably didn't know these)
- `OperationsTelemetry` --uses--> `IncidentIntelligence`  [INFERRED]
  agents/operations/operations_agent.py → intelligence/incident/incident_intelligence.py
- `OperationsAgent` --uses--> `IncidentIntelligence`  [INFERRED]
  agents/operations/operations_agent.py → intelligence/incident/incident_intelligence.py
- `ApiContext` --uses--> `SemanticEngine`  [INFERRED]
  api/dependencies.py → semantic/semantic_engine.py
- `Pagination` --uses--> `SemanticEngine`  [INFERRED]
  api/dependencies.py → semantic/semantic_engine.py
- `ErrorCode` --uses--> `SecretNotFoundError`  [INFERRED]
  api/errors.py → onboarding/credentials.py

## Import Cycles
- None detected.

## Communities (103 total, 13 thin omitted)

### Community 0 - "Predictive Intelligence"
Cohesion: 0.05
Nodes (23): FailurePredictionEngine, Builds explainable resource failure-risk projections., ForecastEngine, IncidentProbabilityEngine, Transparent evidence-weighted incident likelihood estimate., OperationalDebtEngine, Calculates explainable patch, lifecycle, ownership, configuration, and security…, PredictionSummary (+15 more)

### Community 1 - "Address Spec"
Cohesion: 0.06
Nodes (28): AddressSpec, Network address primitives. Deliberately dependency-free (no ``ipaddress``…, Whether two specs can describe an overlapping address set., A rule's source or destination address expression. Exactly one interpretation…, True when the spec spans the whole address space (``0.0.0.0/0``)., Smallest prefix length across the spec's networks (``None`` for tags)., EndpointResolver, FlowEndpoint (+20 more)

### Community 2 - "Semantic Engine"
Cohesion: 0.08
Nodes (19): _collection_metadata(), _entity_payload(), _int_value(), _pick(), Any, Network context for one VNet, traversed through the ontology. This is the read…, Resolve a subject to its safe, scope-bearing public projection., Single read-only knowledge interface over Fabric Ontology projections. (+11 more)

### Community 3 - "Operational Reasoner"
Cohesion: 0.06
Nodes (19): ComplianceAnalyzer, Any, HealthAnalyzer, Any, Computes deterministic 0-100 operational health from semantic evidence., ImpactAnalyzer, Any, IncidentAnalyzer (+11 more)

### Community 4 - "Normalize py"
Cohesion: 0.10
Nodes (60): _address_prefixes(), _child_base(), _list(), _lower(), normalize_firewall(), normalize_firewall_policy(), normalize_gateway(), normalize_load_balancer() (+52 more)

### Community 5 - "Get"
Cohesion: 0.12
Nodes (43): _evidence(), firewall_bypass(), hub_dependents(), network_gaps(), _network_scope(), network_summary(), network_topology(), Any (+35 more)

### Community 6 - "Network Snapshot"
Cohesion: 0.08
Nodes (33): AzureFirewall, FirewallPolicy, NetworkSnapshot, A hub-hosted common service that spokes are expected to consume. Derived, not…, The complete network estate assembled across every connection., SharedService, VNet, _attached_workload_nodes() (+25 more)

### Community 7 - "Credential Reference"
Cohesion: 0.17
Nodes (36): Microsoft Fabric Ontology construction and synchronization., BusinessServiceLinkage, ConnectionHealth, CredentialReference, EnvironmentMapping, SyncState, Authoritative operational knowledge interface over Fabric Ontology., datetime (+28 more)

### Community 8 - "Fabric Sync Service"
Cohesion: 0.08
Nodes (23): ontology_entity_table(), ontology_relationship_table(), _slug(), Schema, schema_for(), _catalog_metadata(), FabricSyncResult, FabricSyncService (+15 more)

### Community 9 - "Network init py"
Cohesion: 0.07
Nodes (32): ApprovedPeering, _bool(), load_design_policy(), NetworkDesignPolicy, _parse(), Any, Path, Customer-defined hub-spoke design policy. The platform cannot infer what a… (+24 more)

### Community 10 - "Connections py"
Cohesion: 0.09
Nodes (51): ApiModel, BusinessMetadataModel, ConnectionCreateRequest, ConnectionMetadataRequest, ConnectionSyncRequest, ConnectionUpdateRequest, ConnectionValidateRequest, CredentialReferenceModel (+43 more)

### Community 11 - "Load"
Cohesion: 0.07
Nodes (42): ArgumentParser, FabricAuthConfig, FabricCommandService, Any, ChangeIntelligenceRuntimeConfig, FabricRuntimeConfig, IncidentCausalityRuntimeConfig, LifecycleRuntimeConfig (+34 more)

### Community 12 - "Network Security Rule"
Cohesion: 0.08
Nodes (24): FirewallRule, FirewallRuleCollection, NetworkSecurityGroup, NetworkSecurityRule, A single NSG rule, with parsed address/port/protocol specs., Observed rules plus Azure's implicit defaults when they were not ingested.…, Rules in Azure evaluation order (ascending priority)., _synthesize_default_rules() (+16 more)

### Community 13 - "Dependencies py"
Cohesion: 0.06
Nodes (35): _correlation_id(), create_app(), _error_body(), Any, Request, Operations API application factory. Builds the FastAPI app that fronts Hermes…, Build the API. When no context is supplied one is assembled from the…, Templated path (not the concrete URL) to keep telemetry low-cardinality. (+27 more)

### Community 14 - "Credential Resolver"
Cohesion: 0.07
Nodes (28): CredentialResolver, LookupError, Turns a :class:`CredentialReference` into an Azure credential. The resolved…, Safe, log-ready description of a credential reference., Raised when a secret reference cannot be resolved by any provider., SecretNotFoundError, HealthEvaluator, _iso() (+20 more)

### Community 15 - "Semantic Indexes"
Cohesion: 0.09
Nodes (18): _canonical_id(), _connection_id_from_source(), _contains_fact(), _fact_identity(), _fact_order(), _normalize_fact_value(), _public_payload(), Any (+10 more)

### Community 16 - "Api runtime py"
Cohesion: 0.08
Nodes (43): add_risk_exception(), _attach_business_context(), build_authenticator(), build_context(), _gateway_grants(), hermes_home(), list_risk_exceptions(), _load_foundry_agent() (+35 more)

### Community 17 - "Onboarding runtime py"
Cohesion: 0.09
Nodes (34): ConnectorConfig, join_root(), Filesystem abstraction so dataset storage works identically against the local…, Join path segments onto a root produced by :func:`resolve_root`., FixtureAzureResourceGraphSource, inject_local_spn_connection(), _iso(), Any (+26 more)

### Community 18 - "Value Error"
Cohesion: 0.06
Nodes (13): Any, Any, Any, canonical_resource_key(), public_subscription_label(), Any, Any, _require_count() (+5 more)

### Community 19 - "Network models py"
Cohesion: 0.11
Nodes (19): ProtocolSpec, A rule's protocol expression., Builds a typed :class:`NetworkSnapshot` from ontology entity rows. The…, LoadBalancingResource, _lower(), _mapping(), NetworkGateway, NetworkInterface (+11 more)

### Community 20 - "Incident intelligence py"
Cohesion: 0.09
Nodes (18): CausalityEngine, Any, datetime, Deterministic evidence-strength model; it never asserts confirmed causation., IncidentAnalyzer, Any, IncidentContextBuilder, Any (+10 more)

### Community 21 - "Patch intelligence py"
Cohesion: 0.18
Nodes (31): Patch and vulnerability intelligence package., PatchAnalyzer, Runs one explainable analysis pass across the semantic patch snapshot., PatchComplianceEngine, Calculates resource and roll-up compliance from governed patch facts., PatchContextBuilder, Builds bounded public context from semantic resource projections., CriticalUpdate (+23 more)

### Community 22 - "Onboarding init py"
Cohesion: 0.08
Nodes (28): ChainedSecretProvider, default_secret_provider(), EnvironmentSecretProvider, key_vault_secret_name(), KeyVaultSecretProvider, KeyVaultSecretWriter, Any, Protocol (+20 more)

### Community 23 - "Api Error"
Cohesion: 0.08
Nodes (29): Authenticator, _bearer_token(), HeaderPrincipalAuthenticator, Protocol, Authentication for the Operations API. Ships a pluggable :class:`Authenticator`…, Resolves request headers into an authenticated principal., Bearer tokens mapped to principals from an in-memory table. Comparison is…, Consumes a principal assertion from a trusted upstream gateway. The gateway is… (+21 more)

### Community 24 - "Fabric runtime py"
Cohesion: 0.11
Nodes (17): Client, build_credential(), build_delta_storage_options(), Create short-lived delta-rs options without exposing client secrets., FabricClient, Any, Protocol, Response (+9 more)

### Community 25 - "CVE"
Cohesion: 0.08
Nodes (25): _cve_from_nvd(), enrich_cves(), enrich_cves_with_epss_and_kev(), EpssScoreConnector, _exploit_reference_source(), _extract_exploit_references(), KevCatalogConnector, MicrosoftSecurityUpdateGuideConnector (+17 more)

### Community 26 - "Scope"
Cohesion: 0.13
Nodes (14): An immutable, multi-dimensional selector over the estate. An empty dimension…, Scope, VulnerabilityFinding, _now_iso(), Any, A multi-hop exposure graph for a CVE: internet/attacker origin, the…, KB drilldown: every CVE this security update resolves (real CVE ids from MSRC,…, Returns a new service with findings flagged for accepted risk. Findings covered… (+6 more)

### Community 27 - "Onboarding service py"
Cohesion: 0.15
Nodes (17): Business metadata assigned to a subscription connection., DuplicateConnectionError, Durable registry of subscription connections. Persistence is secret-free by…, Raised when creating a connection id that already exists., _business_linkages(), _ensure_addable(), _environment_mappings(), _iso() (+9 more)

### Community 28 - "Network Gap Analyzer"
Cohesion: 0.15
Nodes (13): _gap_id(), NetworkGap, NetworkGapAnalyzer, Any, A spoke subnet with no default route to the firewall egresses directly., A spoke subnet with no route table at all., PaaS services the design requires behind Private Link but are not. Reported per…, A divergence between the observed estate and the intended design. (+5 more)

### Community 29 - "Operations Agent"
Cohesion: 0.15
Nodes (9): ContextRouter, Maps the bounded command contract to Semantic Layer views., RoutedContext, _find_unsafe_fields(), OperationsAgent, OperationsTelemetry, Any, Primary read-only operational reasoning interface over SemanticEngine. (+1 more)

### Community 30 - "Patch Intelligence"
Cohesion: 0.15
Nodes (7): Enterprise read-only intelligence over governed patch projections., PatchIntelligence, Any, Read-only business-aware patch intelligence over governed semantic facts., Construct from OneLake/semantic projections; performs no Azure calls., Correlate OneLake patch facts through public Semantic Engine contexts., Internal canonical-key posture for other governed intelligence layers.

### Community 31 - "EOL Catalog"
Cohesion: 0.13
Nodes (15): date, _lifecycle_catalog(), Any, _add_months(), _date_string(), EOLCatalog, LifecycleCatalogEntry, LifecycleClassification (+7 more)

### Community 32 - "Incident Intelligence"
Cohesion: 0.19
Nodes (4): IncidentIntelligence, Any, Canonical incident recurrence counts for governed peer intelligence., Read-only correlation and probabilistic causality over governed evidence.

### Community 33 - "Remediation planner py"
Cohesion: 0.14
Nodes (13): ExecutionSimulator, Any, Produces declarative before/after estimates without touching infrastructure., ImpactEstimator, Summarizes business impact from risk and dependency evidence., PlanPrioritizer, Prioritizes planning candidates without authorizing execution., Any (+5 more)

### Community 34 - "Context py"
Cohesion: 0.18
Nodes (27): not_found(), Derive evidence from a SemanticEngine context payload., application_context(), _authorize_subject(), business_service_context(), environment_context(), _evidence(), _filter_scoped() (+19 more)

### Community 35 - "Registry Store"
Cohesion: 0.11
Nodes (15): _atomic_text(), Local-disk atomic write helper, still used by callers that are guaranteed to…, default_store(), PostgresRegistryStore, Any, Path, Protocol, RuntimeError (+7 more)

### Community 36 - "Lifecycle Intelligence"
Cohesion: 0.20
Nodes (7): LifecycleIntelligence, Any, datetime, Build lifecycle context through public Semantic Engine APIs only., Internal Fabric projection retaining canonical resource identity., Canonical-key lifecycle posture for governed peer intelligence layers., Read-only business-aware lifecycle intelligence over semantic projections.

### Community 37 - "Foundry agent py"
Cohesion: 0.12
Nodes (19): AgentAnswer, _build_prompt(), _extract_text(), FoundryAgentError, FoundryAgentNotConfigured, FoundryPromptAgent, Any, RuntimeError (+11 more)

### Community 38 - "Vulnerability py"
Cohesion: 0.24
Nodes (26): Accept risk for a CVE, optionally scoped to a single server. Omitting…, RiskExceptionCreateRequest, create_risk_exception(), cve_attack_path(), cve_detail(), cves(), _evidence(), kb_articles() (+18 more)

### Community 39 - "Delta Writer"
Cohesion: 0.16
Nodes (12): Governed incident, alert, and ARG change evidence for causality analysis., Governed change, drift, policy, security, identity, and IaC evidence., DeltaWriteMode, DeltaWriter, DeltaWriteResult, _is_transient(), Any, Exception (+4 more)

### Community 40 - "Ontology Validator"
Cohesion: 0.18
Nodes (18): _canonical_id(), _health(), _normalize_entity(), _normalize_relationship(), OntologyGraphResult, OntologyGraphSynchronizer, Any, Versions graph snapshots and preserves removed entities as retired records. (+10 more)

### Community 41 - "Sync py"
Cohesion: 0.12
Nodes (17): _connection_dataset_dir(), Mirror `ConnectionSyncCoordinator.connection_output_dir()` without constructing…, Path, Normalize a dataset root: keep remote URIs intact, resolve local paths. Local…, resolve_root(), datetime, ConnectionSyncCoordinator, _iso() (+9 more)

### Community 42 - "Dataset mapper py"
Cohesion: 0.24
Nodes (23): _asset_row(), _base(), _canonical(), _change_row(), _compliance_row(), _dedupe_entity_rows(), _entity_row(), _health_row() (+15 more)

### Community 43 - "Dataset Store"
Cohesion: 0.18
Nodes (13): DatasetStore, _is_remote_root(), _parquet_value(), Any, Path, Return the absolute path/URI of the active generation, or ``None``. Only…, Write ``content`` to remote storage. ADLS/fsspec rename operations can fail for…, Publishes complete immutable generations and atomically switches `current`.… (+5 more)

### Community 44 - "Subscription Connection"
Cohesion: 0.17
Nodes (12): ConnectionNotFoundError, ConnectionRegistry, _persistable(), Any, LookupError, RuntimeError, Serialize a connection while guaranteeing no secret material is written., Raised when a connection id is not present in the registry. (+4 more)

### Community 45 - "Entity builder py"
Cohesion: 0.21
Nodes (21): _canonical(), _classify(), _connection_field(), _connection_id(), _connection_key(), _connection_lineage(), EntityBuilder, _payload() (+13 more)

### Community 46 - "Change intelligence py"
Cohesion: 0.15
Nodes (10): ChangeAnalyzer, ChangeTelemetry, datetime, ChangeRiskEngine, Any, DriftDetectionEngine, ConfigurationDriftEngine, Any (+2 more)

### Community 47 - "Ontology Query Service"
Cohesion: 0.27
Nodes (6): _extract_subject(), _failed(), OntologyQueryService, _public_entity(), Any, Read-only deterministic traversals over Fabric-backed ontology projections.

### Community 48 - "Ingestion Service"
Cohesion: 0.18
Nodes (10): AzureCliArgClient, AzureMcpClient, CommandResult, CommandRunner, _load_json(), Thin process adapter over the official Azure MCP CLI., ARG query fallback because Azure MCP has no arbitrary ARG query tool., SubprocessRunner (+2 more)

### Community 49 - "Vulnerability models py"
Cohesion: 0.21
Nodes (17): Protocol, Approved metadata source; implementations must return public metadata., SecurityUpdateMetadataConnector, KB-to-CVE enrichment and vulnerability exposure intelligence., AffectedProduct, CVSSScore, ExploitabilitySignal, ExploitReference (+9 more)

### Community 50 - "Any"
Cohesion: 0.15
Nodes (3): _coerce_string(), _normalize_optional(), Any

### Community 51 - "One Lake Writer"
Cohesion: 0.16
Nodes (9): DataLakeServiceClient, OneLakeWriter, Any, Path, _safe_relative(), _table_component(), _table_name(), ParquetWriter (+1 more)

### Community 53 - "Remediation Planner"
Cohesion: 0.28
Nodes (3): Any, datetime, RemediationPlanner

### Community 54 - "Port Spec"
Cohesion: 0.14
Nodes (9): normalize_token(), PortSpec, Any, Whether ``address`` falls inside this spec. Returns ``None`` when undecidable —…, A rule's port expression: ``*``, a single port, or ranges., Number of ports the spec admits; 65536 for ``*``., Sensitive ports this spec exposes (all of them when ``*``)., Casefolds and trims an address/port/protocol token. (+1 more)

### Community 55 - "Any"
Cohesion: 0.18
Nodes (3): _first(), Any, Reads the first present key, accepting snake_case and camelCase.

### Community 56 - "Lifecycle intelligence py"
Cohesion: 0.18
Nodes (10): LifecycleAnalyzer, Any, datetime, Correlates catalog lifecycle state with governed operational context., LifecycleContextBuilder, Builds bounded public lifecycle context keyed by canonical resource identity., LifecycleTelemetry, LifecycleRiskEngine (+2 more)

### Community 57 - "Get requested scope"
Cohesion: 0.11
Nodes (13): get_requested_scope(), Parse scope from repeated query parameters, e.g.…, Any, Drop rows that fall outside a scope., ScopeApplication, ScopeBusinessService, ScopeCriticality, ScopeEnvironment (+5 more)

### Community 58 - "Query Spec"
Cohesion: 0.16
Nodes (12): AzureResourceGraphClient, HttpRequester, Any, Protocol, Response, Query Azure Resource Graph with the connection's token credential., _network_specs(), datetime (+4 more)

### Community 59 - "Relationship builder py"
Cohesion: 0.24
Nodes (14): _group_id(), _lineage(), _management_group_ancestors(), _of_type(), _payload(), _pick(), Any, Infers deterministic structural, operational, and tag-derived relationships. (+6 more)

### Community 60 - "Evidence"
Cohesion: 0.32
Nodes (15): Evidence, Provenance for one fact or one response section., _filter_rows(), incident_detail(), list_incidents(), Any, Context, Page (+7 more)

### Community 62 - "Predictive Context Builder"
Cohesion: 0.19
Nodes (4): PredictionContextBuilder, Requested public name for the governed predictive context builder., PredictiveContextBuilder, Any

### Community 63 - "Incident engine py"
Cohesion: 0.18
Nodes (4): IncidentSummary, Produces audience-specific evidence-backed incident summaries., OperationalPatterns, Detects recurring governed event and risk patterns.

### Community 65 - "Ontology Publisher"
Cohesion: 0.26
Nodes (7): _definitions_equal(), _numeric_id(), OntologyPublisher, _part(), Any, Publishes Fabric-native Ontology definitions bound to Lakehouse Delta tables., Public Fabric Ontology publisher contract.

### Community 66 - "Evidence py"
Cohesion: 0.21
Nodes (10): classify_freshness(), Envelope, Any, datetime, Evidence envelope. Every API response wraps its payload in an envelope that…, A response body: the data, its evidence, and the scope it was read under., Convenience constructor returning a serialized envelope., Surface bounded semantic results so callers never mistake them for complete. (+2 more)

### Community 67 - "Ask"
Cohesion: 0.18
Nodes (13): ask(), CopilotRequest, _filter_scoped(), Any, BaseModel, Context, post, ReadScope (+5 more)

### Community 68 - "Context Query Service"
Cohesion: 0.38
Nodes (7): ContextQueryService, _dedupe(), _failed(), _has_failure_error(), _public_assessment(), _public_server(), Any

### Community 69 - "Quality Report"
Cohesion: 0.32
Nodes (6): DataQualityValidator, _failure(), Any, Schema, QualityReport, _schema_error()

### Community 70 - "Plan Repository"
Cohesion: 0.27
Nodes (3): PlanRepository, Any, Read-only projection repository for generated draft plans and ontology rows.

### Community 71 - "Any"
Cohesion: 0.38
Nodes (3): Any, _strings(), _text()

### Community 72 - "Semantic Cache"
Cohesion: 0.24
Nodes (4): CacheStats, _Entry, Any, SemanticCache

### Community 73 - "Normalize"
Cohesion: 0.27
Nodes (5): _normalize(), _normalize_many(), Any, True when an entity's attributes fall inside this scope., Narrow this scope by another. Used to fold a principal's granted scope into a…

### Community 74 - "Hermes arg connector service"
Cohesion: 0.33
Nodes (7): Azure Resource Graph connector for Hermes Operations Graph. Heavy connector…, _iso(), _max_change_watermark(), _merge_changes(), _parse_time(), _preserve_created_timestamps(), datetime

### Community 75 - "Run Lock"
Cohesion: 0.20
Nodes (5): _is_remote_root(), Path, Cross-process, non-blocking writer lock for one connector data root. Locking…, RunLock, Self

### Community 76 - "Change Classifier"
Cohesion: 0.24
Nodes (6): ChangeClassifier, Any, Deterministically classifies governed change evidence., ChangeCollector, Any, Collects already-governed source projections; it never queries Azure directly.

### Community 78 - "Read scope"
Cohesion: 0.24
Nodes (10): get_principal(), Context, Request, The second RBAC enforcement point for read routes. Returns the requested scope…, Authenticate the caller. Raises 401 when the caller cannot be identified., read_scope(), require_operate(), require_write() (+2 more)

### Community 79 - "Change Correlator"
Cohesion: 0.31
Nodes (5): ChangeCorrelator, Adds portfolio pattern summaries to probabilistic incident correlation., ChangeIncidentCorrelator, Any, datetime

### Community 80 - "Ontology Manager"
Cohesion: 0.29
Nodes (3): OntologyManager, Any, Thin manager over Microsoft Fabric's public Ontology item APIs.

### Community 82 - "Remediation Opportunity Engine"
Cohesion: 0.50
Nodes (3): Any, Matches governed evidence to declarative remediation catalog entries., RemediationOpportunityEngine

### Community 83 - "Resolve fs"
Cohesion: 0.29
Nodes (5): AbstractFileSystem, Return ``(filesystem, root_path)`` for the given root path or URI., resolve_fs(), Any, StateStore

### Community 86 - "Approval Engine"
Cohesion: 0.46
Nodes (3): ApprovalEngine, Any, Evaluates configurable approval policy and stage-gate requirements.

### Community 87 - "Change Summary Engine"
Cohesion: 0.38
Nodes (4): ChangeSummary, ChangeSummaryEngine, Any, Requested summary surface for change, governance, and risk reports.

### Community 88 - "Change Trend Engine"
Cohesion: 0.43
Nodes (3): ChangeTrendEngine, Any, datetime

### Community 89 - "Lifecycle Trend Engine"
Cohesion: 0.62
Nodes (3): LifecycleTrendEngine, Any, datetime

### Community 90 - "Modernization Engine"
Cohesion: 0.43
Nodes (3): ModernizationEngine, Any, Produces advisory-only modernization priorities from catalog evidence.

### Community 92 - "Dependency Analyzer"
Cohesion: 0.48
Nodes (3): DependencyAnalyzer, Any, Builds bounded public dependency context from governed graph projections.

### Community 94 - "Patch Correlator"
Cohesion: 0.40
Nodes (3): PatchCorrelator, Any, Correlates patch evidence to application and business graph context.

### Community 95 - "Risk Analyzer"
Cohesion: 0.53
Nodes (3): Any, Calculates explainable planning risk; it does not authorize execution., RiskAnalyzer

### Community 96 - "Scrub"
Cohesion: 0.50
Nodes (3): Any, Strip anything secret-looking out of a human-readable error message.…, scrub()

### Community 97 - "Baseline Engine"
Cohesion: 0.40
Nodes (3): BaselineEngine, Any, Creates governed, auditable configuration baseline projections.

### Community 100 - "Generate ontology metadata"
Cohesion: 0.83
Nodes (3): generate_ontology_metadata(), Any, _type_name()

## Knowledge Gaps
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `IncidentIntelligence` connect `Incident Intelligence` to `Predictive Intelligence`, `Remediation planner py`, `Semantic Engine`, `Lifecycle Intelligence`, `Credential Reference`, `Incident Engine`, `Api runtime py`, `Incident intelligence py`, `Patch intelligence py`, `Remediation Planner`, `Fabric runtime py`, `Lifecycle intelligence py`, `Operations Agent`, `Patch Intelligence`, `Incident engine py`?**
  _High betweenness centrality (0.148) - this node is a cross-community bridge._
- **Why does `SemanticEngine` connect `Semantic Engine` to `Incident Intelligence`, `Credential Reference`, `Fabric Sync Service`, `Semantic Cache`, `Dependencies py`, `Semantic Indexes`, `Api runtime py`, `Value Error`, `Api Error`, `Fabric runtime py`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Why does `FlowQuery` connect `Address Spec` to `Get`, `Network Snapshot`, `Network init py`, `Network Security Rule`, `Api runtime py`, `Network models py`, `Blast Radius Engine`, `Port Spec`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 193 inferred relationships involving `ValueError` (e.g. with `.analyze()` and `._count()`) actually correct?**
  _`ValueError` has 193 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `SubscriptionConnection` (e.g. with `FixtureAzureResourceGraphSource` and `HealthEvaluator`) actually correct?**
  _`SubscriptionConnection` has 35 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `SemanticEngine` (e.g. with `ApiContext` and `Pagination`) actually correct?**
  _`SemanticEngine` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 32 inferred relationships involving `IncidentIntelligence` (e.g. with `OperationsAgent` and `OperationsTelemetry`) actually correct?**
  _`IncidentIntelligence` has 32 INFERRED edges - model-reasoned connections that need verification._