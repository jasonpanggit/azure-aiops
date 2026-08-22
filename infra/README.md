# Deploying Hermes to Azure

Terraform for the Operations Workbench: two Container Apps (the FastAPI
Operations API and the Next.js workbench), an Azure AI Foundry project whose
prompt agent narrates Copilot answers, and an optional Microsoft Fabric
workspace.

For real subscription discovery, Fabric ontology activation, provider health,
and hub/spoke validation, follow
[`docs/PRODUCTION_RUNTIME_ACTIVATION.md`](../docs/PRODUCTION_RUNTIME_ACTIVATION.md).

Everything lands in a single, self-contained resource group. Nothing outside
that group is read or modified.

## What gets created

| Resource | Purpose |
| --- | --- |
| Resource group | Owns every resource below. |
| Container registry (Basic) | Holds the two images. Admin account disabled; pulls use managed identity. |
| User-assigned identity | Shared by both apps. Holds `AcrPull`, `Key Vault Secrets User`, and `Azure AI User`. |
| Log Analytics + Application Insights | Container Apps logs and app telemetry. |
| Key Vault | Reserved for secret storage. RBAC authorization; secret writes are deferred when subscription policy blocks public access. |
| AI Foundry account (`AIServices`) | Project-based Foundry with a custom subdomain, needed for Entra auth and the agent data plane. |
| Foundry project | Hosts the prompt agent. |
| Model deployment | `gpt-5-mini`, `GlobalStandard`, 50K TPM. |
| Prompt agent | `operations-copilot`. Created post-apply via the data plane. |
| Container Apps environment + 2 apps | The API (port 8080) and the web workbench (port 3000). |
| Fabric capacity, workspace, lakehouse | **Only when `enable_fabric = true`.** |

## Prerequisites

- Terraform >= 1.9, Azure CLI, Docker with buildx.
- A service principal with **Owner** on the target subscription — needed to
  create role assignments. Credentials are read from `web/.env.local`
  (`AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
  `AZURE_CLIENT_SECRET`). That file is gitignored; the scripts export the
  values into the process and never write them to disk.

## Deploying

The registry is created empty, so the container apps have nothing to pull on a
first apply. Deployment is therefore three steps.

```bash
# 1. Provision the platform. Apps start on a placeholder image.
./infra/scripts/deploy.sh apply

# 2. Build and push both images (linux/amd64, as Container Apps requires).
./infra/scripts/build-and-push.sh v1

# 3. Point the apps at the real images.
./infra/scripts/deploy.sh apply -var deploy_images=true -var image_tag=v1

./infra/scripts/deploy.sh output
```

Subsequent releases are steps 2 and 3 with a new tag.

`deploy.sh` also accepts `plan`, `destroy`, `validate`, `fmt`, and `output`,
and forwards any extra arguments to Terraform.

## The Copilot's LLM

`POST /api/v1/copilot/ask` retrieves from the governed knowledge layer, filters
the result to the caller's scope, and only then asks the Foundry prompt agent to
narrate what was retrieved. The agent never queries anything itself, and the
retrieved records are passed in the user turn rather than appended to the
system prompt, so knowledge-layer content cannot override the agent's
instructions.

The agent is wired in through two environment variables set on the API app:

- `FOUNDRY_PROJECT_ENDPOINT`
- `FOUNDRY_AGENT_NAME`

Narration is optional by construction. If the agent is unreachable or
unconfigured, the endpoint still returns the retrieved records with a warning
rather than failing — a narration outage must not take down a surface that
already has evidenced answers.

Foundry prompt agents have no ARM resource type, so the agent is created after
apply by `create-foundry-agent.sh` through the data-plane REST API. Re-running
it is safe: it adds a version rather than failing. To change the agent's
instructions, edit `local.agent_instructions` in `foundry.tf` and re-apply — the
hash of the instructions is a replace trigger.

## Fabric

`enable_fabric` defaults to **false**, because a Fabric capacity bills
continuously from the moment it is created, whether or not anything uses it.
The rest of the platform deploys and runs without it.

```bash
./infra/scripts/deploy.sh apply -var enable_fabric=true
```

Two things to know before enabling it:

- The workspace and lakehouse need the tenant setting *"Service principals can
  use Fabric APIs"* to be enabled for the deploying principal. Without it,
  those two resources fail even though the capacity is created.
- Pause the capacity when idle to stop it billing.

### Digital Twin Builder semantic canvas

The lakehouse tables written by `fabric sync` are the application's
system-of-record ontology. Fabric's native visual canvas is a separate
Digital Twin Builder item that can be generated from those live tables:

```bash
# Read the live lakehouse with the deployment SPN.
export AZURE_TENANT_ID=...
export AZURE_CLIENT_ID=...
export AZURE_CLIENT_SECRET=...
python3 infra/scripts/generate_digital_twin_builder.py \
  --workspace-id <workspace-id> \
  --lakehouse-id <lakehouse-id> \
  --output /tmp/digital-twin-builder-definition.json

# Create or update the canvas with an interactively authenticated user.
az login
python3 infra/scripts/push_digital_twin_builder.py \
  --workspace-id <workspace-id> \
  --definition /tmp/digital-twin-builder-definition.json \
  --display-name "Operational Context Graph"
```

Enable the Fabric tenant setting **Digital Twin Builder (preview)** first.
The generator discovers entity and relationship types from the lakehouse, so
new subscription rows do not require regeneration. Re-run it only when the
ontology's types change. Fabric's Digital Twin Builder create/update API
currently supports user identity only; service principals and managed
identities cannot push the canvas.

## Notable configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `enable_fabric` | `false` | See above. |
| `deploy_images` | `false` | Set true only after the first push. |
| `image_tag` | `v1` | Deliberately not `latest`: a mutable tag makes the running revision unidentifiable. |
| `foundry_model_capacity` | `50` | Thousands of TPM. The provider default of 1 throttles almost immediately. |
| `api_external_ingress` | `true` | The browser currently calls the API directly. Set false once calls are proxied through the web tier. |
| `create_foundry_agent` | `true` | Requires bash and curl on the machine running Terraform. |

## Security notes

- The API bearer token is generated and injected as a Container Apps secret.
  Retrieve it with
  acquire an Entra access token for the configured Operations API audience.
- The subscription policy currently forces Key Vault public access off, so the
  bootstrap secret is not written there from the local machine. Add a private
  endpoint or an approved network path before storing it in Key Vault.
- Foundry key authentication is disabled (`local_auth_enabled = false`); the
  apps authenticate with their managed identity.
- The apps hold `Azure AI User`, not `Azure AI Project Manager`: they can invoke
  the agent but cannot create or modify one.
- The web tier currently authenticates to the API with a single shared token
  granting `admin`. Front the API with Entra
  (`HERMES_API_AUTH=gateway`) and carry end-user identity through before
  exposing this beyond a demo.
