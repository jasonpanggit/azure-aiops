# Existing Hermes/Pi Capability Inventory

## 1. Inspection baseline

This inventory was produced from the live Hermes checkout and active profile before any HOG implementation.

| Item | Observed value |
|---|---|
| Source checkout | `/Users/jasonmba/.hermes/hermes-agent` |
| Commit | `894b29df167a9789b4809316b266c6aca400f366` (2026-08-17) |
| Hermes version | `v0.20.2 (2026.8.16)` |
| Upstream state | checkout is 25 commits behind `origin/main` |
| Working tree | pre-existing modifications in `contributors/emails/agent@Agents-Mac-mini.local`, `pyproject.toml`, `setup-hermes.sh`, `uv.lock`; they were not touched |
| Tracked files | 9,514 |
| Tests | 3,129 tracked test files; strong coverage around tools, agent, gateway, cron, memory, plugins, and MCP |
| Active skills | 82 built-in enabled; 0 hub/local |
| Optional repository skills | 117 |
| Plugin manifests | 97 bundled |
| Standalone plugins explicitly enabled | 0; the CLI reports all 97 manifests as not enabled. Trusted bundled backends/providers can still auto-register, platforms load lazily, and dashboard/desktop/TUI use separate enablement systems. |
| Configured MCP servers | 0 |
| Cron | gateway ticker running; 0 jobs |
| Memory | built-in enabled; no external provider active |
| Monitoring | gateway health export disabled; OTLP unconfigured; OTel SDK optional extra not installed |

No separate Pi implementation root was found. Pi appears in ACP/client compatibility, trace formats, and architecture lessons; the inspected codebase is Hermes Agent. Hermes can expose ACP/MCP interfaces to clients including Pi-compatible consumers.

**Baseline decision:** update/reconcile the checkout and isolate the existing local changes before implementation. The artifacts are valid for this inspected commit; re-run inventory after updating.

### Focused verification caveats

Subagent verification found strong but not perfect local test health:

- state/memory/checkpoint/notepad selection: 377 passed, 1 FTS trace-optimization assertion failed even though returned context was correct;
- an additional selection had 76 passing and 3 async failures because `pytest-asyncio` was absent in this environment;
- scheduler/webhook/delegation/Kanban/monitoring/lifecycle selection: 106 passed, 3 skipped, 1 optional-dashboard test deselected;
- live `state.db` schema is version 26 while some session-storage documentation still says version 23.

These are baseline issues to reproduce after updating the checkout. They do not justify replacing the frameworks, but implementation must not claim a fully green repository baseline until resolved.

## 2. Reuse/extend/replace decision summary

| Capability | Purpose/maturity evidence | Reusable | Replace | Extend |
|---|---|---:|---:|---:|
| Central tool registry | 87 registered built-in tools across 40 self-registering modules; schemas, handlers, availability checks, plugin override controls, TTL checks. Mature. | yes | no | register HOG service-gated tools in standalone plugin only if structured calls are necessary |
| Toolsets/narrow-waist model | 59 static definitions: 32 capability, 3 posture, 24 platform/composite; session gating and progressive disclosure. Mature. | yes | no | add HOG plugin toolset; do not add Azure tools to `_HERMES_CORE_TOOLS` |
| Plugin framework | 97 manifests across provider/platform/memory/observability categories; install/enable/doctor/capability/pack CLI. Mature framework; individual 0.x plugins vary. | yes | no | HOG should be standalone plugin/repository using generic hooks/providers |
| Skill framework | 82 active + 117 optional; load-on-demand procedural memory, curator and bundles. Mature. | yes | no | add focused HOG/Azure source skills in project/plugin, not giant core prompt |
| Native MCP client | stdio/HTTP/SSE, OAuth, reconnection, dynamic schemas, sampling, tool selection, cron/gateway integration; 79 MCP-focused tests. Mature. | yes | no | configure pinned Azure/Fabric/source MCPs and exact tool allowlists |
| MCP server/ACP | Hermes can serve conversations over MCP and ACP; Pi-compatible session replay noted. Mature integration surface. | yes | no | expose HOG reasoning only if Foundry/client needs this transport |
| Built-in memory | profile-aware `MEMORY.md`/`USER.md`, explicit memory tool and injection. Mature for stable facts/preferences. | limited | no | enforce boundary: never store operational graph facts here |
| Memory provider ABC/manager | one external provider at a time; async prefetch/sync, context fencing, provider tools; 8 bundled providers and extensive tests. Mature framework. | limited | no | optional operator knowledge retrieval; ontology remains authoritative |
| Session persistence | profile-aware SQLite/WAL `state.db` schema v26, migrations/self-healing, FTS5/trigram/CJK, sessions/messages/prompts/model usage/routing/leases/async delegation. Mature. | yes | no | investigation audit/resume only; not graph storage |
| Cron scheduler | profile-scoped JSON plus SQLite execution ledger/notepad, output, locking, claims, scripts, monitor mode, no-agent jobs, context chaining, workdir and delivery. Production-grade single-node. | yes | no | HOG scheduled reconciliation/steward jobs; use an Azure queue for volume/multi-host durability |
| Cron provider ABC | separates trigger from execution/delivery; built-in plus Chronos. Explicitly experimental until a second provider validates it. | yes with caution | replace Chronos/NAS for Azure production | reuse the provider seam; built-in for development, Azure-native scheduling/wake-up for hosted production |
| Webhook framework | HMAC routes, filters, transform scripts, idempotency, hot reload, agent/direct delivery. Mature generic input. | yes | no | managed Azure Event Grid adapter signs normalized Hermes events |
| Delegation | isolated parallel subagents, background completion, bounded roles/toolsets. Mature. | yes | no | ambiguity analysis and parallel source investigation, not event processing |
| Kanban | durable SQLite/WAL review queue with events, idempotency, dispatcher, worker isolation, attachments and review loops. Very mature single-host kernel. | yes | no | ontology steward human review; externalize leases/dispatch for multi-host production |
| Agent core | shared loop across CLI/gateway/TUI/desktop; model routing, compression, prompt caching, tool enforcement. Mature. | yes | no | HOG agents/instructions/evaluations at edge |
| Gateway/platforms | multi-channel delivery, session routing, approvals, plugin adapters. Mature. | optional | no | alerts/review notifications only |
| Gateway monitoring | content-free health/diagnostic export over OTLP; no prompts/tool payloads. Present but disabled locally. | yes | no | enable OTLP to Azure Monitor/Application Insights after security review |
| Langfuse/NeMo observability plugins | optional conversation/tool observability, disabled. Version 1.0/0.1. | optional | no | do not use by default for sensitive operations; evaluate only with explicit opt-in |
| Checkpoints/backup | session/runtime recovery and Hermes home backup. Mature operational support. | yes | no | use for Hermes recovery, not Fabric data versioning |
| Fabric/OneLake persistence | not present as a Hermes core subsystem. | no | no | new HOG adapter/publication layer required |
| Azure source adapters | no generic ARG/Arc/Defender/Sentinel/Update/ServiceNow adapter found. | partial via MCP/terminal | no | add standalone HOG source adapters; do not alter core |

## 3. Tool registry and active toolsets

### Registry architecture

- `tools/registry.py`: central `ToolRegistry`, AST-based auto-discovery, disk-cached discovery verdicts, schema/handler/check metadata, result/error bounds, plugin override policy, check TTL/flap handling.
- `model_tools.py`: imports discovered tools, resolves toolsets, dispatches calls, and supports deferred/tiered tool disclosure.
- `toolsets.py`: `_HERMES_CORE_TOOLS`, optional toolsets, webhook-safe surface, platform composites, and resolution helpers.
- `tools/mcp_tool.py`: dynamic MCP tools register into the same registry.
- Plugin tools register through the same contracts rather than a parallel dispatcher.

Repository search found 150 `registry.register()` call sites including tests; production registrations span file, terminal/process, web/browser, vision/media, skills, memory, session search, planning, clarification, code execution, delegation, cron, Kanban, platform, Home Assistant, and GUI/session tools.

### Active CLI toolsets

Enabled in the active profile:

- web, browser, terminal, file, code_execution, vision, image_gen, bfl, tts;
- skills, todo, memory, session_search, clarify, delegation, cronjob;
- computer_use.

Disabled:

- video, video_gen, x_search, stt, context_engine;
- Home Assistant, Spotify, Yuanbao;
- plugin A2A toolset.

HOG reuse:

- terminal/file/code execution for discovery and deterministic adapters during development;
- MCP for external structured tools;
- cron/webhook/delegation/Kanban for operations;
- no new core model tools unless a generic missing capability is proven.

## 4. MCP and extension infrastructure

### Native MCP client

Capabilities confirmed in code/docs:

- local stdio and remote Streamable HTTP/SSE transports;
- startup/lazy discovery and dynamic registry registration;
- tool name namespacing and tool selection;
- OAuth login/reauth and metadata handling;
- reconnect/backoff/circuit-breaker/stability safeguards;
- content types including text, structured content, images, resources;
- server-initiated sampling with model/rate/tool-round controls;
- filtered subprocess environment and error credential redaction;
- gateway/TUI reload and cron startup discovery;
- Hermes MCP server mode for external consumers.

Current source names dynamic tools as `mcp__<sanitized-server>__<sanitized-tool>` and gives each server the canonical toolset `mcp-<server>` (with raw server name as an alias). Older single-underscore naming in some guidance is stale; integration tests must inspect the live registry.

Reuse: configure pinned Azure MCP and optional Fabric Ontology MCP. Azure MCP tools should remain deferrable and allowlisted. Sampling should be disabled unless a trusted use case requires it.

### Plugin/extension framework

Supported extension types visible in manifests/source:

- browser and web providers;
- model providers;
- image/video providers;
- memory providers;
- cron providers;
- dashboard authentication providers;
- observability hooks;
- messaging/A2A platforms;
- tools, CLI hooks, lifecycle hooks, emitted/listened events;
- context engine and desktop/dashboard extension surfaces.

The project’s own Footprint Ladder explicitly prefers plugin or MCP over a new core tool. HOG fits a standalone plugin with project skills/query assets and optional MCP server.

## 5. Complete bundled plugin inventory

All 97 manifests were parsed. No standalone plugin is explicitly enabled. Trusted bundled backend/provider registration, lazy platform registration, and UI plugin defaults are separate from that CLI status.

### Browser providers (3)

`browser-browser-use@1.0.0`, `browser-browserbase@1.0.0`, `browser-firecrawl@1.0.0`.

Purpose: browser backend selection. HOG action: **keep/not directly relevant**; useful only for documentation/portal validation where APIs are unavailable.

### Cron providers (1)

`chronos@1.0.0`.

Purpose: managed NAS-mediated one-shot wake-ups for scale-to-zero agents. HOG action: **reuse conditionally** for hosted deployment; built-in scheduler first because provider ABC is marked experimental.

### Dashboard authentication (4)

`basic@1.0.0`, `drain@1.0.0`, `nous@1.0.0`, `self-hosted@1.0.0`.

Purpose: dashboard password, drain bearer-token, Nous OAuth, generic OIDC. HOG action: **reuse** if exposing an operator dashboard; prefer Entra-compatible self-hosted OIDC/gateway design and preserve least privilege.

### Housekeeping and meeting (3)

- `disk-cleanup@2.0.0`: ephemeral-file cleanup — **reuse**.
- `google_meet@0.2.0`: live meeting transcription/audio — **not MVP**.
- `teams_pipeline@0.1.0`: durable Graph-backed Teams transcript pipeline — **extend/reuse patterns** for RCA/postmortem intake, not as an incident store.

### Memory providers (8)

`byterover@1.0.0`, `hindsight@1.0.0`, `holographic@0.1.0`, `honcho@1.0.0`, `mem0@1.3.0`, `openviking@2.0.0`, `retaindb@1.0.0`, `supermemory@1.0.1`.

Purpose: external long-term memory with local/cloud/search/knowledge-graph variants. HOG action: **do not replace Fabric Ontology**. Optionally evaluate one for operator/policy knowledge after data-governance review. Built-in memory remains sufficient for preferences/procedures.

### Model providers (34)

`actual-provider`, `ai-gateway-provider`, `alibaba-provider`, `alibaba-coding-plan-provider`, `anthropic-provider`, `arcee-provider`, `azure-foundry-provider`, `bedrock-provider`, `copilot-provider`, `copilot-acp-provider`, `custom-provider`, `deepinfra-provider`, `deepseek-provider`, `fireworks-provider`, `gemini-provider`, `gmi-provider`, `huggingface-provider`, `kilocode-provider`, `kimi-coding-provider`, `minimax-provider`, `nous-provider`, `novita-provider`, `nvidia-provider`, `ollama-cloud-provider`, `openai-codex-provider`, `opencode-zen-provider`, `openrouter-provider`, `qwen-oauth-provider`, `stepfun-provider`, `upstage-provider`, `vertex-provider`, `xai-provider`, `xiaomi-provider`, `zai-provider` (all 1.0.0).

Purpose: inference routing. HOG action: **reuse `azure-foundry-provider` only as a model provider where appropriate**; it supports Foundry endpoint/auth patterns but is not a Foundry Agent Service tool integration or an Azure operations client. Keep provider-agnostic fallback/evaluation. Existing `tools/microsoft_graph_auth.py` and `tools/microsoft_graph_client.py` provide reusable token-cache, retry, pagination, and async HTTP patterns for Teams/Entra work, but Microsoft Graph must not be confused with Azure Resource Graph. ARM/ARG, Microsoft Graph, Monitor, and Foundry use distinct audiences/scopes.

### Observability (2)

`langfuse@1.0.0`, `nemo_relay@0.1.0`.

Purpose: optional conversation/LLM/tool observability. HOG action: **not default** due operational/security content; prefer built-in content-free OTLP gateway health and HOG OpenTelemetry. Evaluate with explicit opt-in/redaction only.

### Messaging/A2A platforms (22)

`a2a-platform`, `buzz-platform`, `dingtalk-platform`, `discord-platform`, `email-platform`, `feishu-platform`, `google_chat-platform`, `homeassistant-platform`, `irc-platform`, `line-platform`, `matrix-platform`, `mattermost-platform`, `ntfy-platform`, `photon-platform`, `raft-platform`, `simplex-platform`, `slack-platform`, `sms-platform`, `teams-platform`, `telegram-platform`, `wecom-platform`, `whatsapp-platform`.

Purpose: inbound/outbound channels and inter-agent tasks. HOG action: **reuse Teams/Slack/email/ntfy or existing enterprise channel for steward notifications and approvals**; A2A is optional for agent federation. Do not use messaging as context persistence.

### Security/tool integration (2)

- `security-guidance@0.1.0`: non-blocking dangerous-pattern warnings — **reuse during implementation**, not a full security gate.
- `spotify@1.0.0`: unrelated — **keep/no HOG use**.

### Image generation (7)

`deepinfra`, `fal`, `krea`, `openai`, `openai-codex`, `openrouter`, `xai`.

### Video generation (3)

`deepinfra`, `fal`, `xai`.

### Web search providers (8)

`web-brave-free`, `web-ddgs`, `web-exa`, `web-firecrawl`, `web-parallel`, `web-searxng`, `web-tavily`, `web-xai`.

Image/video/web purpose: creative generation or external research. HOG action: **no runtime role**; web is useful for architecture/documentation research only. Do not use web content as operational evidence.

### Other extension surfaces inspected

- **Desktop plugins (3):** `hermes-bots` (default on), `kanban` (default off), and `example` SDK fixture under `apps/desktop/src/plugins/`.
- **Dashboard plugins (2):** Kanban and Hermes Achievements manifests under `plugins/*/dashboard/`; bundled dashboard plugins are active unless hidden/disabled.
- **TUI widget apps (4):** weather, ticker, grid-test, dialog-test under `ui-tui/src/sdk/apps/`; the latter two are SDK/demo apps.
- **User/project extensions:** no user Python plugins, entry-point plugins, desktop plugins, TUI widgets, or project `.hermes/plugins` were found. Project plugins are explicitly gated.

Python plugins run in-process as trusted code. Capability declarations are consent/API gates, not a security sandbox. Plugin profile state is atomic JSON with a 10 MiB quota per plugin, which is unsuitable for the operational graph.

## 6. Complete skill inventory

### Active built-in skills (82)

- **apple (4):** apple-notes, apple-reminders, findmy, imessage.
- **autonomous-ai-agents (6):** claude-code, codex, computer-use, hermes-agent, merge-reconciler, opencode.
- **creative (16):** architecture-diagram, ascii-art, ascii-video, baoyu-infographic, claude-design, comfyui, design-md, excalidraw, humanizer, manim-video, p5js, popular-web-designs, pretext, sketch, songwriting-and-ai-music, touchdesigner-mcp.
- **devops (1):** sdlc-review.
- **email (2):** email-inbox-triage, himalaya.
- **github (7):** codebase-inspection, github-auth, github-code-review, github-issue-to-pr, github-issues, github-pr-workflow, github-repo-management.
- **media (3):** gif-search, songsee, youtube-content.
- **mlops (5):** evaluating-llms-harness, huggingface-hub, llama-cpp, serving-llms-vllm, weights-and-biases.
- **note-taking (1):** obsidian.
- **productivity (17):** airtable, box, document-to-action-items, docx, google-workspace, maps, meeting-action-items, nano-pdf, notion, ocr-and-documents, pdf, powerpoint, product-price-monitor, session-librarian, teams-meeting-pipeline, weekly-review-planning, xlsx.
- **research (7):** arxiv, blocked-page-recovery, blogwatcher, competitor-news-monitor, grounded-citations, llm-wiki, research-paper-writing.
- **smart-home (1):** openhue.
- **social-media (1):** xurl.
- **software-development (11):** dogfood, hermes-agent-skill-authoring, inspecting-hermes-desktop-dom, node-inspect-debugger, plan, python-debugpy, requesting-code-review, simplify-code, spike, systematic-debugging, test-driven-development.

### Optional repository skills (117)

- **autonomous-ai-agents (5):** antigravity-cli, blackbox, grok, honcho, openhands.
- **blockchain (3):** evm, hyperliquid, solana.
- **communication (1):** one-three-one-rule.
- **creative (15):** audiocraft-audio-generation, baoyu-article-illustrator, baoyu-comic, concept-diagrams, creative-ideation, draw-your-font, heartmula, hyperframes, kanban-video-orchestrator, meme-generation, pixel-art, simple-english, social-media-content-calendar, tldraw-offline, unreal-mcp.
- **data-science (1):** jupyter-notebook.
- **devops (6):** actual-setup, docker-management, hermes-s6-container-supervision, inference-sh-cli, pinggy-tunnel, watchers.
- **dogfood (1):** adversarial-ux-test.
- **email (1):** agentmail.
- **finance (9):** 3-statement-model, comps-analysis, dcf-model, excel-author, lbo-model, merger-model, polymarket, pptx-author, stocks.
- **gaming (2):** minecraft-modpack-server, pokemon-player.
- **health (2):** fitness-nutrition, neuroskill-bci.
- **mcp (3):** fastmcp, mcp-oauth-remote-gateway, mcporter.
- **migration (1):** openclaw-migration.
- **mlops (31):** accelerate, axolotl, chroma, clip, dspy, faiss, flash-attention, guidance, huggingface-tokenizers, instructor, lambda-labs, llava, modal, nemo-curator, obliteratus, outlines, peft, pinecone, pytorch-fsdp, pytorch-lightning, qdrant, saelens, segment-anything-model, simpo, slime, stable-diffusion, tensorrt-llm, torchtitan, trl-fine-tuning, unsloth, whisper.
- **payments (3):** mpp-agent, stripe-link-cli, stripe-projects.
- **productivity (7):** canvas, here-now, memento-flashcards, shop, shopify, siyuan, telephony.
- **research (12):** bioinformatics, darwinian-evolver, domain-intel, drug-discovery, duckduckgo-search, gitnexus-explorer, osint-investigation, parallel-cli, pinecone-research, qmd, scrapling, searxng-search.
- **security (6):** 1password, godmode, oss-forensics, sherlock, unbroker, web-pentest.
- **software-development (4):** ast-grep, code-wiki, rest-graphql-debug, subagent-driven-development.
- **web-development (3):** cloudflare-temporary-deploy, har-derived-api-client, page-agent.
- **yuanbao (1):** yuanbao.

### Skills relevant to HOG

| Skill | Reuse |
|---|---|
| hermes-agent | framework configuration, MCP/plugins/cron/webhooks/background systems |
| grounded-citations | source-grounded architecture and RCA/postmortem extraction |
| document-to-action-items / meeting-action-items | structured extraction patterns for RCA/postmortem obligations and decisions |
| teams-meeting-pipeline | Graph subscription/transcript/replay patterns |
| ocr-and-documents, docx, pdf | approved RCA/postmortem extraction |
| evaluating-llms-harness | model evaluation pattern; HOG needs custom graph-grounding evals |
| systematic-debugging | incident investigation procedure pattern |
| test-driven-development / requesting-code-review / sdlc-review | implementation quality gates |
| architecture-diagram / excalidraw | architecture communication only |
| optional fastmcp / mcp-oauth-remote-gateway / mcporter | HOG MCP spike and secured remote MCP patterns |
| optional watchers | change-watch pattern only; Azure-native events preferred |
| Azure-specific skill | **missing**; create focused project skills after implementation procedures stabilize |

Do not overload skills with live operational state. Skills are procedures; OneLake/Fabric is context state.

## 7. Memory framework

### Built-in

- `$HERMES_HOME/memories/MEMORY.md` and `$HERMES_HOME/memories/USER.md`, profile-scoped and injected into sessions.
- Explicit memory tool with batched add/replace/remove.
- Stable preferences, environment facts, and lessons only.

### Provider framework

- `agent/memory_provider.py`: provider ABC.
- `agent/memory_manager.py`: one external provider maximum, async prefetch/sync, tool schema normalization, context fencing/scrubbing, provider shutdown.
- Bundled providers listed above; none active.

### HOG decision

Reuse memory for operator preferences, vocabulary aliases, and reusable source quirks. **Do not use it for Resources, Incidents, Findings, Patches, dependencies, confidence, or ontology truth.** External graph-capable memory providers do not replace Fabric’s governed operational context.

## 8. Scheduler and event framework

### Cron

- Store: `$HERMES_HOME/cron/jobs.json`.
- Output: `$HERMES_HOME/cron/output/{job_id}/{timestamp}.md`.
- Execution ledger: `$HERMES_HOME/cron/executions.db` with immutable terminal attempts and interrupted-run recovery.
- Durable notepad: `$HERMES_HOME/cron/notepad.db`, capped at 16 KiB/value and 64 KiB/job; use only for compact cursors/watermarks.
- Profile isolation, atomic writes, process/file locks, ticker heartbeat/success/error, running claims, stale recovery, execution history.
- Built-in 60-second ticker; external provider ABC; Chronos optional.
- Jobs support scripts, no-agent mode, monitor hashing, skills, context chaining, continuity, workdir, toolsets, delivery, durable notepad.

HOG use: deterministic source reconciliation, confidence/staleness scans, publication verification, quality watchdogs. Do not put bulk event payloads in jobs/notepad.

### Webhooks

- Dynamic subscriptions and config routes.
- HMAC-SHA256, filters, transform scripts, idempotency, prompt templating, delivery-only.
- Persisted subscription registry.

Limitations: inbound dedupe/rate-limit state is process-local, accepted agent requests are not first committed to a durable queue, and Azure Event Grid validation/Entra authentication/Service Bus settlement are not native. Use Azure Function/APIM/Service Bus in front for production durability and identity validation.

HOG use: receive compact, normalized, signed Azure/source event hints through a managed source adapter. Native Azure Event Grid validation/signatures should terminate before the Hermes HMAC route unless a generic plugin adapter is built.

## 9. Agent infrastructure

- `run_agent.py`: core conversation/tool loop.
- `agent/`: prompt builder, model routing, memory, compression, skills, transports, credentials.
- `tools/delegate_tool.py`: isolated leaf/orchestrator subagents with bounded toolsets and heartbeat/stale detection.
- `plugins/kanban` plus `tools/kanban_tools.py`: durable collaborative task/review system.
- `gateway/`: long-lived multi-platform routing and delivery.
- `acp_adapter/` and `mcp_serve.py`: external agent/client protocols.
- `apps/`, `ui-tui/`, `web/`, `tui_gateway/`: desktop/TUI/dashboard surfaces.

HOG use: deterministic engines run as scripts/adapters; agents handle ambiguity, causal extraction, explanations, and steward summaries. Kanban handles human review. Foundry consumes Fabric IQ rather than directly sharing Hermes conversation state.

Running delegated children and background agents are host-process threads and cannot resume after process exit; durable records preserve completion/delivery state, not resumable execution. Use Azure queues/jobs or Kanban for durable production work.

## 10. Telemetry infrastructure

### Built-in gateway monitoring

- Optional OTLP export of gateway service-health metrics and redacted diagnostics.
- Content-free by construction: no prompts, messages, tool args/results, or usage analytics.
- Currently disabled; OTel SDK extra not installed.

The monitoring emitter is an in-memory bounded queue and has no durable telemetry spool or end-to-end trace propagation across webhook → cron/Kanban → agent → Azure. Extend with content-free HOG spans/metrics and a shared correlation ID; do not add resource IDs as high-cardinality metric labels.

HOG action: enable in deployment and route to Azure Monitor/Application Insights after verifying signals and redaction. Add HOG-specific OpenTelemetry spans/metrics for source runs, watermarks, data quality, publication, and agent evaluations through a plugin/app instrumentation layer.

### Optional observability plugins

Langfuse and NeMo Relay are disabled. They can expose conversation/tool traces and require separate privacy review. They are not necessary for the first operational platform and should not receive sensitive incident/source payloads by default.

## 11. Persistence infrastructure

| Store | Existing use | HOG use |
|---|---|---|
| `$HERMES_HOME/state.db` | SQLite sessions/messages/system prompts/tool/session state, FTS5/trigram/CJK search, migrations | investigation audit/resume and session search |
| `MEMORY.md` / `USER.md` | stable cross-session facts/preferences | operator preferences only |
| cron JSON/output/execution/notepad | schedules, run attempts/results, bounded durable KV | schedule/watermark coordination, not graph data |
| webhook subscription JSON | dynamic route registry | normalized source trigger registration |
| Kanban SQLite board | durable work/review queue | steward review workflow |
| checkpoints/backups | Hermes session/home recovery | runtime recovery only |
| Fabric/OneLake | absent in core | **new authoritative HOG context projection** |

Do not extend `state.db` into an operational graph store. Keep HOG canonical data in governed OneLake tables bound to Fabric Ontology.

## 12. Recommended implementation placement

1. Create a standalone HOG repository/plugin package, not a core fork.
2. Use project-local skills, query assets, Fabric mappings, and infrastructure definitions.
3. Register only a small HOG plugin toolset with `check_fn`; prefer CLI + skills for setup/operations.
4. Use native MCP client for Azure/Fabric/enterprise MCPs.
5. Use generic webhook/cron/Kanban/memory/provider interfaces unchanged.
6. Propose core changes only when a generic extension gap is demonstrated by a working HOG consumer and is broadly reusable.

## 13. Capability gaps requiring new work

- arbitrary ARG query adapter;
- Azure Resource Notifications/Event Grid normalization and signing path;
- Arc and Update Manager adapters;
- Defender/Sentinel/ServiceNow/Azure DevOps/Entra adapters where no approved MCP exists;
- OneLake canonical publication and Fabric Ontology lifecycle adapter;
- ontology identity/assertion/confidence/steward policy engine;
- graph-grounded Foundry integration and evaluations;
- focused Azure/HOG skills after procedures are validated.

These are edge integrations, not reasons to replace Hermes core systems.

## References

- Source architecture: `/Users/jasonmba/.hermes/hermes-agent/AGENTS.md` and inspected modules named above.
- Hermes documentation: https://hermes-agent.nousresearch.com/docs/
- Plugin guide: https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins
- Cron guide: https://hermes-agent.nousresearch.com/docs/user-guide/features/cron
