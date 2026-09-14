# API Coverage — Native Fabric IQ and Fabric Data Agent

> Full coverage by default. Opt-outs are explicit, reasoned decisions grounded
> in the Phase 03.8 boundary and research.

| capability | decision | reason |
|---|---|---|
| Fabric IQ versioned Foundry connection/toolbox provisioning | INTEGRATE | |
| Fabric IQ delegated Entra OBO authorization | INTEGRATE | |
| Fabric IQ allowed-principal ontology probe | INTEGRATE | |
| Fabric IQ denied-principal ontology probe | INTEGRATE | |
| Fabric IQ `fabric_iq_preview` topology traversal | INTEGRATE | |
| Fabric IQ `fabric_iq_preview` blast-radius traversal | INTEGRATE | |
| Fabric IQ `fabric_iq_preview` relationship traversal | INTEGRATE | |
| Fabric IQ `fabric_iq_preview` policy/governance context | INTEGRATE | |
| Fabric IQ citation and ontology-generation validation | INTEGRATE | |
| Fabric IQ pagination/truncation/partial-result handling | INTEGRATE | |
| Fabric IQ cancellation, deadline, bounded retry, and circuit-open handling | INTEGRATE | |
| Data Agent managed workload token acquisition | INTEGRATE | Uses the fixed Fabric API `.default` scope. |
| Fabric Data Agent MCP `initialize` | INTEGRATE | |
| Fabric Data Agent MCP initialized notification | INTEGRATE | |
| Fabric Data Agent MCP `tools/list` discovery | INTEGRATE | |
| Fabric Data Agent MCP `tools/call` | INTEGRATE | |
| Fabric Data Agent MCP `tasks/get` polling | INTEGRATE | |
| Fabric Data Agent MCP `tasks/cancel` cleanup | INTEGRATE | |
| Fabric Data Agent session-header lifecycle and disposal | INTEGRATE | |
| Fabric Data Agent denied/empty/stale/conflicting/unavailable handling | INTEGRATE | |
| Foundry IQ knowledge-base/Search wrapper over the ontology | OPT-OUT | Research scopes this as a later grounding option; Phase 03.8 uses the documented ontology MCP/`fabric_iq_preview` path for native traversal. |
| Azure MCP `learn:true` for traversal or grounding | OPT-OUT | Phase 03.8 explicitly uses Fabric IQ and Data Agent native surfaces and forbids Azure MCP learning calls. |
| Provider mutation/publishing tools | OPT-OUT | Phase boundary is read-only adoption; new ingestion, publication, relationship acceptance, and remediation authority are excluded. |
| Broad all-specialist or page-specific activation | OPT-OUT | Context limits initial use to topology/blast-radius and policy/governance scopes. |
