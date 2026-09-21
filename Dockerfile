# Operations API image.
#
# Two stages: the builder resolves dependencies into a virtualenv with uv (the
# same resolver used locally, so the deployed dependency set matches uv.lock),
# and the runtime stage carries only the venv plus the source. The Azure CLI is
# installed in the runtime image because AzureCliArgClient shells out to
# `az graph query` for Resource Graph extraction — without it every connection
# sync fails at runtime.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Resolve dependencies before copying the source so a source-only change does
# not invalidate the (slow) dependency layer.
COPY pyproject.toml uv.lock ./
# No --mount=type=cache here: ACR Tasks' classic builder doesn't run with
# BuildKit enabled, so a cache mount fails the build outright there. This
# layer is still cached normally by Docker's layer cache between builds.
RUN uv venv /app/.venv \
    && uv sync --frozen --no-install-project --extra api --extra fabric-sql


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    AIOPS_HOME=/data \
    AIOPS_RUNTIME_MODE=production \
    AIOPS_LOCAL_SEED=0 \
    AIOPS_API_HOST=0.0.0.0 \
    AIOPS_API_PORT=8080 \
    AIOPS_ARG_CONFIG=/app/config.yaml \
    AIOPS_FABRIC_CONFIG=/app/fabric.config.yaml

# `az` is a hard runtime dependency of the ARG extraction path, and the
# Resource Graph extension must be baked in: a scheduled sync must never
# depend on an extension install at first use. Fabric SQL additionally
# requires Microsoft's signed package repository and ODBC Driver 18.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && . /etc/os-release \
    && curl -fsSLo /tmp/packages-microsoft-prod.deb \
        "https://packages.microsoft.com/config/debian/${VERSION_ID}/packages-microsoft-prod.deb" \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm -f /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql18 libgssapi-krb5-2 \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && az extension add --name resource-graph --only-show-errors \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG SOURCE_CACHE_BUST=0
ARG AIOPS_SOURCE_REVISION
LABEL source_cache_bust="${SOURCE_CACHE_BUST}"

COPY --from=builder /app/.venv /app/.venv
COPY .dockerignore pyproject.toml uv.lock Dockerfile Dockerfile.default-promotion /app/
COPY infra/scripts/build-and-push.sh infra/scripts/deploy.sh /app/infra/scripts/
COPY infra/terraform/container_apps.tf infra/terraform/outputs.tf infra/terraform/variables.tf /app/infra/terraform/
COPY src/ /app/src/
COPY skills/ /app/skills/
COPY scripts/export_copilot_provider_env.py /app/scripts/export_copilot_provider_env.py
COPY scripts/benchmark_exposure_read_model.py /app/scripts/benchmark_exposure_read_model.py
COPY scripts/refresh_exposure_enrichment.py /app/scripts/refresh_exposure_enrichment.py
COPY scripts/validate_exposure_live.py /app/scripts/validate_exposure_live.py
COPY scripts/validate_ontology_publisher_rbac.py /app/scripts/validate_ontology_publisher_rbac.py
COPY scripts/collect_ontology_evidence.py /app/scripts/collect_ontology_evidence.py
COPY arg.config.deploy.yaml fabric.config.deploy.yaml /app/
COPY arg.config.deploy.yaml /app/config.yaml
COPY fabric.config.deploy.yaml /app/fabric.config.yaml

# The specialist contract is the deployment's single source of truth for agent
# identity, grants, and versions. Fail the image build -- not a production
# request -- if it is missing or unparseable at the loader's stable path.
RUN python -c "import json, pathlib; json.loads(pathlib.Path('/app/src/operations/specialists.v1.json').read_text(encoding='utf-8'))"
RUN python -c 'import json,pathlib,re,sys; source=sys.argv[1]; assert re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?",source), "AIOPS_SOURCE_REVISION must be an exact Git revision"; pathlib.Path("/app/build-metadata.json").write_text(json.dumps({"schema_version":"copilot-build-metadata.v1","source_revision":source},sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")' "${AIOPS_SOURCE_REVISION}"
# Baked-in default connector configs so the inventory-refresh trigger endpoint
# (POST /api/v1/inventory/refresh, called by the Fabric Data Pipeline Web
# activity) has a config to load without needing a mounted volume. Neither
# file contains secrets -- the ARG service-principal secret is supplied via
# AZURE_CLIENT_SECRET at runtime, not stored in these YAML files. Production
# points directly at these reviewed paths so runtime behavior remains covered
# by the packaged-tree recomputation.

# The API writes connection registries and synced datasets under AIOPS_HOME.
RUN useradd --create-home --uid 10001 aiops \
    && mkdir -p /data \
    && chown -R aiops:aiops /data /app
USER aiops

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "python -m api.akv_bootstrap && exec uvicorn api.app:create_app --factory --host ${AIOPS_API_HOST} --port ${AIOPS_API_PORT}"]
