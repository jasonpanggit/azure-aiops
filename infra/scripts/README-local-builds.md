# Local image builds (Apple Silicon)

`build-and-push.sh` defaults to `AIOPS_BUILD_MODE=acr`, which builds natively
on amd64 inside Azure Container Registry. That is the right default and is
usually the fastest option (~90-150s per image with a warm layer cache).
These are illustrative warm-cache timings, not a release SLA.

## Bounded parallel builds

Full application builds submit two independent images at a time in ACR.
All four builds must finish successfully and all four manifests must exist
before the script records the release in `terraform.tfvars` or deploys it.
A failed batch is fully joined before its immutable source archive is removed;
the tag remains unrecorded. API-only authorization releases still build only
the API, with the same immutable-tag and source-revision checks.

Use `AIOPS_BUILD_PARALLELISM=1` for serial execution if ACR capacity is limited.
Values 1 through 4 are supported; local builds default to 1 to avoid exhausting
Docker Desktop memory. Higher concurrency can increase peak resource usage or
queue time; it does not reduce total build compute.

```bash
AIOPS_BUILD_PARALLELISM=1 ./infra/scripts/build-and-push.sh my-release
AIOPS_BUILD_PARALLELISM=2 ./infra/scripts/build-and-push.sh my-release
```

CI caches Python package downloads using `pyproject.toml` and `uv.lock` as
cache keys. Installation and every test/lint/build still run; a cache hit is
not validation evidence. Keep external release evidence tied to its exact
commit and command/environment rather than skipping checks on a changed tree.

`AIOPS_BUILD_MODE=local` builds with `docker buildx` and pushes. It only beats
ACR if the Docker VM is configured for it. Out of the box on an M-series Mac it
is *slower*, and the web image build fails outright.

## Why the default local build fails

Container Apps runs `linux/amd64`. On aarch64 hardware Docker must emulate
that. Check which emulator you have:

```bash
docker run --rm --platform linux/amd64 alpine sh -c \
  'ls /run/rosetta >/dev/null 2>&1 && echo ROSETTA || echo QEMU'
```

* `ROSETTA` — hardware-assisted, roughly 2-3x faster. Usable.
* `QEMU` — pure software emulation. `npm ci` + `next build` under QEMU
  exhausts the VM and dies with `Exit handler never called!`.

## Making local builds viable

In **Docker Desktop → Settings**:

1. **General** → enable *Use Rosetta for x86_64/amd64 emulation on Apple
   Silicon*. Requires the VirtioFS file sharing implementation.
2. **Resources** → raise **Memory to at least 12 GB**. The Next.js production
   build is the memory hog; the default (~8 GB) is not enough once emulation
   overhead is added.
3. Apply & restart, then re-run the check above and confirm it prints
   `ROSETTA`.

Install Rosetta itself if missing:

```bash
softwareupdate --install-rosetta --agree-to-license
```

## Registry layer cache

Local mode passes `--cache-from`/`--cache-to` against a `:buildcache` tag in
the registry, so an incremental build reuses the dependency stage from the
previous push instead of re-resolving `uv sync` / `npm ci` every time. The
first local build populates the cache and is therefore no faster than ACR;
subsequent ones are substantially faster.

## Usage

```bash
AIOPS_BUILD_MODE=local ./infra/scripts/build-and-push.sh
AIOPS_BUILD_MODE=local ./infra/scripts/build-and-push.sh my-fix --deploy
```

## When to still prefer ACR

* First build of the day / cold cache — ACR's cache lives next to the registry.
* Slow uplink. Local mode pushes full layers from your machine; `az acr build`
  uploads only the build context.
* CI, or any machine without Rosetta.
