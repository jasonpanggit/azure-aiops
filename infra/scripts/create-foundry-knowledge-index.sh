#!/usr/bin/env bash
#
# Creates (or updates) the Azure AI Search vector index backing the Foundry
# specialists' "azure_ai_search" knowledge-search tool, and pushes every
# document under KNOWLEDGE_DOCS_DIR into it.
#
# There is no Terraform resource for Azure AI Search index schema or document
# ingestion, so this runs via a local-exec provisioner (mirroring
# create-foundry-agent.sh). Idempotent: re-running updates the index
# definition in place and re-embeds/re-upserts every document, so editing or
# adding a file under infra/knowledge/ and re-applying is enough to refresh
# the knowledge base -- no manual portal steps required.
#
# Required environment (supplied by Terraform):
#   SEARCH_SERVICE_NAME      Azure AI Search service name (no .search.windows.net)
#   SEARCH_INDEX_NAME        Index name to create/update
#   KNOWLEDGE_DOCS_DIR       Directory of documents to embed and index
#   FOUNDRY_OPENAI_ENDPOINT  https://<account>.openai.azure.com (Cognitive Services account, not the project endpoint)
#   FOUNDRY_EMBEDDING_MODEL  Embedding model deployment name
#   AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
#                            required for client_credentials authentication
# Optional:
#   FOUNDRY_AUTH_MODE        client_credentials (default) or azure_cli
#
# Documents are plain text/markdown files. Each is chunked (~2000 chars, on
# paragraph boundaries where possible), embedded with the Foundry embedding
# deployment, and upserted as one search document per chunk. The `source`
# field (the file's relative path) and `title` (first line / filename) back
# the citations specialists surface when they ground a claim in this tool.

set -euo pipefail

for var in SEARCH_SERVICE_NAME SEARCH_INDEX_NAME KNOWLEDGE_DOCS_DIR \
           FOUNDRY_OPENAI_ENDPOINT FOUNDRY_EMBEDDING_MODEL; do
  if [[ -z "${!var:-}" ]]; then
    echo "create-foundry-knowledge-index: ${var} is required" >&2
    exit 1
  fi
done

auth_mode="${FOUNDRY_AUTH_MODE:-client_credentials}"
case "${auth_mode}" in
  client_credentials)
    : "${AZURE_TENANT_ID:?required for client_credentials authentication}"
    : "${AZURE_CLIENT_ID:?required for client_credentials authentication}"
    : "${AZURE_CLIENT_SECRET:?required for client_credentials authentication}"
    ;;
  azure_cli)
    if ! command -v az >/dev/null 2>&1; then
      echo "create-foundry-knowledge-index: az is required for azure_cli authentication" >&2
      exit 1
    fi
    ;;
  *)
    echo "create-foundry-knowledge-index: unsupported FOUNDRY_AUTH_MODE '${auth_mode}'" >&2
    exit 1
    ;;
esac

SEARCH_ENDPOINT="https://${SEARCH_SERVICE_NAME}.search.windows.net"
SEARCH_API_VERSION="2024-07-01"

# Two independent Entra tokens: one scoped to Azure AI Search's own data
# plane (index/document management), one scoped to the Cognitive Services
# data plane (to call the embedding deployment directly). They are different
# resources and cannot share a token.
get_token() {
  if [[ "${auth_mode}" == "azure_cli" ]]; then
    az account get-access-token --resource "$1" --query accessToken --output tsv
  else
    curl -sS --fail-with-body \
      -X POST "https://login.microsoftonline.com/${AZURE_TENANT_ID}/oauth2/v2.0/token" \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode 'grant_type=client_credentials' \
      --data-urlencode "client_id=${AZURE_CLIENT_ID}" \
      --data-urlencode "client_secret=${AZURE_CLIENT_SECRET}" \
      --data-urlencode "scope=$1/.default" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
  fi
}

search_token="$(get_token https://search.azure.com)"
foundry_token="$(get_token https://cognitiveservices.azure.com)"
if [[ -z "${search_token}" || -z "${foundry_token}" ]]; then
  echo "create-foundry-knowledge-index: authentication returned an empty token" >&2
  exit 1
fi

echo "create-foundry-knowledge-index: upserting index '${SEARCH_INDEX_NAME}' on ${SEARCH_ENDPOINT}"

# 1536 dims matches text-embedding-3-small/ada-002. If a larger embedding
# model is configured, the index create call below will fail with a clear
# dimension-mismatch error rather than silently truncating vectors.
#
# The vectorizer (azureOpenAIParameters below) is what makes
# query_type=vector_semantic_hybrid usable from Foundry's azure_ai_search
# tool: Foundry sends the raw query text and expects Azure AI Search itself
# to embed it using this configuration, since Foundry does not separately
# call an embedding model to vectorize the query on the caller's behalf.
# Document vectors are still embedded and upserted explicitly below (not via
# the vectorizer), since ingestion runs as this script/the deploying
# principal rather than the search service's own identity -- but the field
# and the vectorizer must still agree on the same embedding deployment/model
# so query and document vectors are comparable.
index_body=$(cat <<JSON
{
  "name": "${SEARCH_INDEX_NAME}",
  "fields": [
    {"name": "id", "type": "Edm.String", "key": true, "filterable": true},
    {"name": "content", "type": "Edm.String", "searchable": true, "retrievable": true},
    {"name": "title", "type": "Edm.String", "searchable": true, "retrievable": true, "filterable": true},
    {"name": "source", "type": "Edm.String", "retrievable": true, "filterable": true},
    {"name": "content_vector", "type": "Collection(Edm.Single)", "searchable": true,
      "retrievable": false, "dimensions": 1536, "vectorSearchProfile": "default-profile"}
  ],
  "vectorSearch": {
    "algorithms": [{"name": "default-algo", "kind": "hnsw"}],
    "profiles": [{"name": "default-profile", "algorithm": "default-algo", "vectorizer": "default-vectorizer"}],
    "vectorizers": [{
      "name": "default-vectorizer",
      "kind": "azureOpenAI",
      "azureOpenAIParameters": {
        "resourceUri": "${FOUNDRY_OPENAI_ENDPOINT}",
        "deploymentId": "${FOUNDRY_EMBEDDING_MODEL}",
        "modelName": "${FOUNDRY_EMBEDDING_MODEL}"
      }
    }]
  },
  "semantic": {
    "configurations": [{
      "name": "default-semantic",
      "prioritizedFields": {
        "titleField": {"fieldName": "title"},
        "prioritizedContentFields": [{"fieldName": "content"}]
      }
    }]
  }
}
JSON
)

curl -sS --fail-with-body \
  -X PUT "${SEARCH_ENDPOINT}/indexes/${SEARCH_INDEX_NAME}?api-version=${SEARCH_API_VERSION}" \
  -H "Authorization: Bearer ${search_token}" \
  -H 'Content-Type: application/json' \
  -d "${index_body}" >/dev/null

echo "create-foundry-knowledge-index: index ready, chunking and embedding documents from ${KNOWLEDGE_DOCS_DIR}"

FOUNDRY_OPENAI_ENDPOINT="$FOUNDRY_OPENAI_ENDPOINT" \
FOUNDRY_EMBEDDING_MODEL="$FOUNDRY_EMBEDDING_MODEL" \
FOUNDRY_TOKEN="$foundry_token" \
SEARCH_ENDPOINT="$SEARCH_ENDPOINT" \
SEARCH_INDEX_NAME="$SEARCH_INDEX_NAME" \
SEARCH_API_VERSION="$SEARCH_API_VERSION" \
SEARCH_TOKEN="$search_token" \
KNOWLEDGE_DOCS_DIR="$KNOWLEDGE_DOCS_DIR" \
python3 - <<'PY'
import hashlib
import json
import os
import re
import urllib.request

docs_dir = os.environ["KNOWLEDGE_DOCS_DIR"]
openai_endpoint = os.environ["FOUNDRY_OPENAI_ENDPOINT"].rstrip("/")
embedding_model = os.environ["FOUNDRY_EMBEDDING_MODEL"]
foundry_token = os.environ["FOUNDRY_TOKEN"]
search_endpoint = os.environ["SEARCH_ENDPOINT"]
index_name = os.environ["SEARCH_INDEX_NAME"]
api_version = os.environ["SEARCH_API_VERSION"]
search_token = os.environ["SEARCH_TOKEN"]

CHUNK_SIZE = 2000


def chunk(text: str):
    paragraphs = re.split(r"\n\s*\n", text)
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > CHUNK_SIZE and current:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def embed(text: str):
    # Cognitive Services account's own OpenAI-compatible data plane (not the
    # Foundry project endpoint -- that endpoint's /embeddings route 404s).
    url = f"{openai_endpoint}/openai/deployments/{embedding_model}/embeddings?api-version=2024-02-01"
    body = json.dumps({"input": text}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {foundry_token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["data"][0]["embedding"]


def upsert(documents):
    url = f"{search_endpoint}/indexes/{index_name}/docs/index?api-version={api_version}"
    body = json.dumps({"value": documents}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {search_token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        result = json.load(resp)
        failed = [r for r in result.get("value", []) if not r.get("status")]
        if failed:
            raise RuntimeError(f"document upsert failures: {failed}")


documents = []
if os.path.isdir(docs_dir):
    for root, _dirs, files in sorted(os.walk(docs_dir)):
        for fname in sorted(files):
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, docs_dir)
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            if not text.strip():
                continue
            first_line = next((l.strip("# ").strip() for l in text.splitlines() if l.strip()), fname)
            for i, piece in enumerate(chunk(text)):
                doc_id = hashlib.sha256(f"{rel}:{i}".encode()).hexdigest()
                documents.append({
                    "@search.action": "mergeOrUpload",
                    "id": doc_id,
                    "content": piece,
                    "title": first_line if i == 0 else f"{first_line} (part {i + 1})",
                    "source": rel,
                    "content_vector": embed(piece),
                })

if not documents:
    print("create-foundry-knowledge-index: no documents found under "
          f"{docs_dir}; index created empty, nothing to upsert.")
else:
    # Batch to stay well under the Search API's per-request document limit.
    for start in range(0, len(documents), 50):
        upsert(documents[start:start + 50])
    print(f"create-foundry-knowledge-index: upserted {len(documents)} chunks "
          f"from {docs_dir}")
PY
