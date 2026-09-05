"""Record and load the fail-closed Phase 12 default-path API baseline."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from api.dependencies import Pagination
from api.routers.network import network_gaps, network_topology, rule_findings
from api.scope import Scope
from network.models import NetworkSnapshot
from network.service import NetworkIntelligenceService
from tests.network_scale_fixtures import g4_baseline_estate

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    REPOSITORY_ROOT
    / ".planning"
    / "phases"
    / "12-network-topology-integrity-and-scale"
    / "12-PRE-PHASE-BASELINE.json"
)
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


class BaselineArtifactMissingError(FileNotFoundError):
    """Raised when a compatibility gate has no recorded comparison target."""


class BaselineArtifactInvalidError(ValueError):
    """Raised when a baseline cannot prove which pre-phase commit it records."""


class _NetworkContext:
    """Small router context exposing only the provider seam those routes use."""

    hybrid_network_provider = None

    def __init__(self, service: NetworkIntelligenceService) -> None:
        self._service = service

    def resolve_provider(self, name: str) -> NetworkIntelligenceService:
        if name != "network":
            raise AssertionError(f"unexpected provider requested: {name}")
        return self._service


def _serialized(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _representative_item(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    data = body["data"]
    if endpoint == "topology":
        items = data["topology"]["resources"]
    elif endpoint == "gaps":
        items = data["gaps"]
    else:
        items = data["findings"]
    return dict(items[0]) if items else {}


def _response_record(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    serialized = _serialized(body)
    return {
        "body": serialized,
        "byte_length": len(serialized.encode("utf-8")),
        "top_level_keys": sorted(body),
        "representative_item_keys": sorted(_representative_item(endpoint, body)),
    }


def capture_default_responses(snapshot: NetworkSnapshot) -> dict[str, dict[str, Any]]:
    """Invoke all three router functions with their pre-phase default inputs."""
    context = _NetworkContext(NetworkIntelligenceService(snapshot))
    scope = Scope.unrestricted()
    page = Pagination()
    bodies = {
        "topology": network_topology(context, scope),
        "gaps": network_gaps(context, scope, page, severity=None, category=None),
        "rule_findings": rule_findings(
            context, scope, page, severity=None, category=None
        ),
    }
    return {
        endpoint: _response_record(endpoint, body)
        for endpoint, body in bodies.items()
    }


def without_allowed_additive_keys(
    endpoint: str,
    body: dict[str, Any],
    allowed_additive_keys: list[dict[str, Any]],
) -> dict[str, Any]:
    """Remove explicitly registered additive fields for baseline comparison."""
    normalized = deepcopy(body)

    def remove_path(parent: Any, path: list[str]) -> None:
        segment = path[0]
        if segment == "*":
            if not isinstance(parent, list):
                raise BaselineArtifactInvalidError(
                    f"registered additive wildcard requires a list: {'.'.join(path)}"
                )
            for child in parent:
                remove_path(child, path[1:])
            return
        if not isinstance(parent, dict) or segment not in parent:
            raise BaselineArtifactInvalidError(
                f"registered additive key path is absent: {'.'.join(path)}"
            )
        if len(path) == 1:
            del parent[segment]
            return
        remove_path(parent[segment], path[1:])

    for addition in allowed_additive_keys:
        if addition.get("endpoint") != endpoint:
            continue
        path = addition.get("path")
        if not isinstance(path, list) or not path or not all(
            isinstance(segment, str) and segment for segment in path
        ):
            raise BaselineArtifactInvalidError(
                "allowed_additive_keys entries require a non-empty string path"
            )
        remove_path(normalized, path)
    return normalized


def record_baseline(
    path: Path = BASELINE_PATH,
    *,
    phase_base_commit: str,
    backend_pass_count: int,
    web_pass_count: int,
    canvas_interactivity: dict[str, Any],
    recording_environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record the pinned G-4 fixture and its detached-worktree measurements."""
    if not _FULL_SHA.fullmatch(phase_base_commit):
        raise BaselineArtifactInvalidError(
            "phase_base_commit must be a full 40-character lowercase hexadecimal SHA"
        )
    if backend_pass_count < 0 or web_pass_count < 0:
        raise BaselineArtifactInvalidError("suite pass counts must be non-negative")
    measured_ceiling = canvas_interactivity.get("measured_ceiling_nodes")
    if not isinstance(measured_ceiling, int) or not 0 < measured_ceiling <= 1_500:
        raise BaselineArtifactInvalidError(
            "canvas measured_ceiling_nodes must be an integer from 1 through 1500"
        )

    snapshot = g4_baseline_estate()
    endpoints = capture_default_responses(snapshot)
    topology_body = json.loads(endpoints["topology"]["body"])
    topology = topology_body["data"]["topology"]
    artifact = {
        "schema_version": 1,
        "phase_base_commit": phase_base_commit,
        "recording_environment": dict(recording_environment or {"git_mode": "replay"}),
        "fixture": {
            "name": "g4_baseline_estate",
            "private_link_resource_count": len(snapshot.private_link_resources),
            "frozen": True,
        },
        "endpoints": endpoints,
        "topology": {
            "node_count": len(topology["resources"]),
            "edge_count": len(topology["relationships"]),
            "collection_counts": dict(topology["counts"]),
        },
        "suite_pass_counts": {
            "backend": int(backend_pass_count),
            "web": int(web_pass_count),
        },
        "allowed_additive_nodes": [],
        "allowed_additive_keys": [],
        "canvas_interactivity": dict(canvas_interactivity),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return artifact


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any]:
    """Load the baseline or fail closed when its provenance is unavailable."""
    if not path.is_file():
        raise BaselineArtifactMissingError(
            f"Pre-phase baseline artifact is missing: {path}"
        )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    phase_base_commit = str(artifact.get("phase_base_commit") or "")
    if not _FULL_SHA.fullmatch(phase_base_commit):
        raise BaselineArtifactInvalidError(
            "Pre-phase baseline has an invalid phase_base_commit"
        )
    return artifact


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("record",))
    parser.add_argument("--output", type=Path, default=BASELINE_PATH)
    parser.add_argument("--phase-base-commit", required=True)
    parser.add_argument("--backend-pass-count", type=int, required=True)
    parser.add_argument("--web-pass-count", type=int, required=True)
    parser.add_argument("--canvas-measurement", type=Path, required=True)
    return parser.parse_args()


def _detached_recording_environment(phase_base_commit: str) -> dict[str, Any]:
    symbolic = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if symbolic.returncode == 0 or actual != phase_base_commit:
        raise BaselineArtifactInvalidError(
            "baseline recording must run at the phase base commit in a detached worktree"
        )
    return {
        "git_mode": "detached_worktree",
        "head_commit": actual,
        "platform": platform.platform(),
    }


def main() -> None:
    args = _parse_args()
    measurement = json.loads(args.canvas_measurement.read_text(encoding="utf-8"))
    measurement.setdefault("machine", platform.platform())
    recording_environment = _detached_recording_environment(args.phase_base_commit)
    artifact = record_baseline(
        args.output,
        phase_base_commit=args.phase_base_commit,
        backend_pass_count=args.backend_pass_count,
        web_pass_count=args.web_pass_count,
        canvas_interactivity=measurement,
        recording_environment=recording_environment,
    )
    print(
        json.dumps(
            {
                "path": str(args.output),
                "node_count": artifact["topology"]["node_count"],
                "edge_count": artifact["topology"]["edge_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
