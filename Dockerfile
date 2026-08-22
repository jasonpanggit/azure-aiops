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
    && uv sync --frozen --no-install-project --extra api


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    HERMES_HOME=/data \
    HERMES_RUNTIME_MODE=production \
    HERMES_LOCAL_SEED=0 \
    HERMES_API_HOST=0.0.0.0 \
    HERMES_API_PORT=8080

# `az` is a hard runtime dependency of the ARG extraction path, and the
# Resource Graph extension must be baked in: a scheduled sync must never
# depend on an extension install at first use.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && az extension add --name resource-graph --only-show-errors \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG SOURCE_CACHE_BUST=0
LABEL source_cache_bust="${SOURCE_CACHE_BUST}"

COPY --from=builder /app/.venv /app/.venv
COPY src/ /app/src/
COPY skills/ /app/skills/

# The API writes connection registries and synced datasets under HERMES_HOME.
RUN useradd --create-home --uid 10001 hermes \
    && mkdir -p /data \
    && chown -R hermes:hermes /data /app
USER hermes

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "python -m api.akv_bootstrap && exec uvicorn api.app:create_app --factory --host ${HERMES_API_HOST} --port ${HERMES_API_PORT}"]
