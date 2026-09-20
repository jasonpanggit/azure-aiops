"""Deterministic hashing for the Copilot canary reviewed source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

REVIEWED_TREE_ALGORITHM = "sha256-path-length-content-v1"
AUTHORIZATION_MANIFEST_RELATIVE_PATH = (
    "src/operations/copilot_canary_authorization.v1.json"
)
REVIEWED_TREE_ROOTS = (
    ".dockerignore",
    "Dockerfile",
    "arg.config.deploy.yaml",
    "fabric.config.deploy.yaml",
    "infra/scripts/build-and-push.sh",
    "infra/scripts/deploy.sh",
    "infra/terraform/container_apps.tf",
    "infra/terraform/outputs.tf",
    "infra/terraform/variables.tf",
    "pyproject.toml",
    "scripts/benchmark_exposure_read_model.py",
    "scripts/collect_ontology_evidence.py",
    "scripts/export_copilot_provider_env.py",
    "scripts/refresh_exposure_enrichment.py",
    "scripts/validate_exposure_live.py",
    "scripts/validate_ontology_publisher_rbac.py",
    "skills",
    "src",
    "uv.lock",
)
REVIEWED_TREE_EXCLUDED_PATHS = (
    AUTHORIZATION_MANIFEST_RELATIVE_PATH,
)


class ReviewedTreeError(ValueError):
    """Raised when the reviewed tree definition or packaged files are invalid."""


def _validate_definition(
    roots: Sequence[str],
    excluded_paths: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    reviewed_roots = tuple(roots)
    reviewed_exclusions = tuple(excluded_paths)
    if reviewed_roots != REVIEWED_TREE_ROOTS:
        raise ReviewedTreeError("reviewed tree roots differ from the fixed set")
    if reviewed_exclusions != REVIEWED_TREE_EXCLUDED_PATHS:
        raise ReviewedTreeError("reviewed tree exclusions differ from the fixed set")
    for values, label in (
        (reviewed_roots, "roots"),
        (reviewed_exclusions, "exclusions"),
    ):
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ReviewedTreeError(
                f"reviewed tree {label} must be sorted and unique"
            )
        for value in values:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or str(path) != value:
                raise ReviewedTreeError(f"invalid reviewed tree path: {value}")
    if AUTHORIZATION_MANIFEST_RELATIVE_PATH not in reviewed_exclusions:
        raise ReviewedTreeError("authorization manifest must be excluded")
    return reviewed_roots, reviewed_exclusions


def reviewed_tree_paths(
    root: Path,
    roots: Sequence[str],
    excluded_paths: Sequence[str],
) -> tuple[str, ...]:
    """Expand the fixed roots into the exact deterministic regular-file set."""

    reviewed_roots, reviewed_exclusions = _validate_definition(
        roots,
        excluded_paths,
    )
    files: set[str] = set()
    for relative_root in reviewed_roots:
        candidate = root / relative_root
        if candidate.is_symlink() or not candidate.exists():
            raise ReviewedTreeError(
                f"reviewed tree root is missing or symbolic: {relative_root}"
            )
        candidates = (candidate,) if candidate.is_file() else candidate.rglob("*")
        for path in candidates:
            relative = path.relative_to(root).as_posix()
            if (
                relative in reviewed_exclusions
                or "__pycache__" in path.parts
                or path.suffix == ".pyc"
            ):
                continue
            if path.is_symlink():
                raise ReviewedTreeError(
                    f"reviewed tree contains a symbolic path: {relative}"
                )
            if path.is_file():
                files.add(relative)
    if AUTHORIZATION_MANIFEST_RELATIVE_PATH in files:
        raise ReviewedTreeError("authorization manifest must not hash itself")
    return tuple(sorted(files))


def reviewed_tree_digest(
    root: Path,
    roots: Sequence[str],
    excluded_paths: Sequence[str],
) -> str:
    """Hash path, byte length, and bytes for the fixed deterministic file set.

    Files are processed in lexicographic path order. For every file the SHA-256
    input is ``UTF8(path) + NUL + ASCII(byte_length) + NUL + file_bytes``.
    The authorization manifest is deliberately excluded to avoid self-reference.
    """

    reviewed_paths = reviewed_tree_paths(root, roots, excluded_paths)
    digest = hashlib.sha256()
    resolved_root = root.resolve()
    for relative in reviewed_paths:
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise ReviewedTreeError(f"reviewed tree file is missing: {relative}")
        if not candidate.resolve().is_relative_to(resolved_root):
            raise ReviewedTreeError(f"reviewed tree file escapes root: {relative}")
        content = candidate.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


def _manifest_tree(
    manifest_path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        tree = payload["reviewed_tree"]
        algorithm = tree["algorithm"]
        roots = tuple(tree["include_roots"])
        excluded_paths = tuple(tree["exclude_paths"])
        expected = tree["sha256"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReviewedTreeError("authorization reviewed tree is invalid") from exc
    if algorithm != REVIEWED_TREE_ALGORITHM:
        raise ReviewedTreeError("reviewed tree algorithm is unsupported")
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ReviewedTreeError("reviewed tree digest is invalid")
    reviewed_roots, reviewed_exclusions = _validate_definition(
        roots,
        excluded_paths,
    )
    return reviewed_roots, reviewed_exclusions, expected


def verify_manifest_reviewed_tree(*, root: Path, manifest_path: Path) -> str:
    """Recompute and verify the reviewed-tree digest carried by a manifest."""

    roots, excluded_paths, expected = _manifest_tree(manifest_path)
    actual = reviewed_tree_digest(root, roots, excluded_paths)
    if actual != expected:
        raise ReviewedTreeError("reviewed tree digest mismatch")
    return actual


def main() -> int:
    """Verify a source or packaged reviewed tree from the command line."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(
        verify_manifest_reviewed_tree(
            root=args.root,
            manifest_path=args.manifest,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
