"""Offline classification, preservation and comparison of captured ontology definitions.

This module never calls Fabric.  It operates on definitions previously captured
through the public getDefinition operation (``{"parts": [{path, payload,
payloadType}]}``).  Two first-party formats exist and must not be confused:

* ``legacy-json``: ``definition.json`` plus ``EntityTypes/``/``RelationshipTypes/``
  JSON parts (what :class:`ontology.ontology_publisher.OntologyPublisher` emits).
* ``ontology-tmdl``: TMDL/TMSL++ parts (``*.tmdl``) with ontology-specific
  extensions.  Unknown syntax is retained as opaque text; nothing here rewrites
  or serializes TMDL.

Fingerprints are exact-content digests, not a Fabric-native concurrency token.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

DefinitionFormat = Literal["legacy-json", "ontology-tmdl", "mixed", "unknown", "empty"]

MAX_PARTS = 1_000
MAX_PATH_LENGTH = 512
MAX_PART_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024

_LEGACY_PATTERNS = (
    re.compile(r"^definition\.json$"),
    re.compile(r"^EntityTypes/[^/]+/definition\.json$"),
    re.compile(r"^EntityTypes/[^/]+/DataBindings/[^/]+\.json$"),
    re.compile(r"^RelationshipTypes/[^/]+/definition\.json$"),
    re.compile(r"^RelationshipTypes/[^/]+/Contextualizations/[^/]+\.json$"),
)
_NEUTRAL_PATHS = frozenset({".platform"})
_BINDING_PATH = re.compile(r"/(DataBindings|Contextualizations)/")
_LINEAGE_TAG = re.compile(r"^\s*lineageTag:\s*(\S+)\s*$", re.MULTILINE)


class DefinitionBoundsError(ValueError):
    """Captured definition exceeds the strict part/path/byte bounds."""


class DefinitionFormatMismatch(RuntimeError):
    """The legacy publisher refused an incompatible or unknown native target."""

    def __init__(self, message: str, *, detected: str) -> None:
        super().__init__(message)
        self.detected = detected


@dataclass(frozen=True)
class DecodedPart:
    path: str
    payload_type: str
    raw: bytes


def decode_parts(definition: Mapping[str, Any]) -> dict[str, DecodedPart]:
    """Decode parts with strict bounds.  Raises :class:`DefinitionBoundsError`."""

    parts = definition.get("parts") or []
    if not isinstance(parts, list):
        raise DefinitionBoundsError("definition parts must be a list")
    if len(parts) > MAX_PARTS:
        raise DefinitionBoundsError(f"definition has more than {MAX_PARTS} parts")
    decoded: dict[str, DecodedPart] = {}
    total = 0
    for part in parts:
        if not isinstance(part, Mapping):
            raise DefinitionBoundsError("definition part must be an object")
        path = part.get("path")
        if not isinstance(path, str) or not path or len(path) > MAX_PATH_LENGTH:
            raise DefinitionBoundsError("definition part path is invalid")
        segments = path.split("/")
        if path.startswith("/") or "\\" in path or ".." in segments or "" in segments:
            raise DefinitionBoundsError(f"definition part path is not contained: {path!r}")
        if path in decoded:
            raise DefinitionBoundsError(f"duplicate definition part path: {path!r}")
        payload_type = str(part.get("payloadType") or "")
        payload = part.get("payload")
        if payload_type != "InlineBase64" or not isinstance(payload, str):
            raise DefinitionBoundsError(f"unsupported payload encoding for {path!r}")
        if len(payload) > (MAX_PART_BYTES * 4) // 3 + 8:
            raise DefinitionBoundsError(f"definition part exceeds byte bound: {path!r}")
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DefinitionBoundsError(f"invalid base64 payload: {path!r}") from exc
        if len(raw) > MAX_PART_BYTES:
            raise DefinitionBoundsError(f"definition part exceeds byte bound: {path!r}")
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise DefinitionBoundsError("definition exceeds total byte bound")
        decoded[path] = DecodedPart(path, payload_type, raw)
    return decoded


def classify_definition(definition: Mapping[str, Any]) -> DefinitionFormat:
    """Classify a captured definition by its part paths (bounded decode first)."""

    decoded = decode_parts(definition)
    paths = [p for p in decoded if p not in _NEUTRAL_PATHS]
    if not paths:
        return "empty"
    legacy = tmdl = other = 0
    for path in paths:
        if any(pattern.match(path) for pattern in _LEGACY_PATTERNS):
            legacy += 1
        elif path.endswith((".tmdl", ".pbism")):
            tmdl += 1
        else:
            other += 1
    if other:
        return "unknown"
    if legacy and tmdl:
        return "mixed"
    return "legacy-json" if legacy else "ontology-tmdl"


def definition_fingerprint(definition: Mapping[str, Any]) -> str:
    """Exact-content digest of the decoded parts (path, type, raw bytes)."""

    digest = hashlib.sha256()
    for path, part in sorted(decode_parts(definition).items()):
        digest.update(hashlib.sha256(path.encode()).digest())
        digest.update(hashlib.sha256(part.payload_type.encode()).digest())
        digest.update(hashlib.sha256(part.raw).digest())
    return f"sha256:{digest.hexdigest()}"


def _elide(value: Any) -> Any:
    """Documented default elision: null/empty properties are equivalent to absent."""

    if isinstance(value, dict):
        out = {k: _elide(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, [], {})}
    if isinstance(value, list):
        return [_elide(v) for v in value]
    return value


def _normalize_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def semantic_projection(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Normalized per-part projection.  Not a byte-equality claim.

    JSON parts: parsed with default elision.  Everything else: opaque text with
    line-ending/trailing whitespace normalization only.
    """

    projection: dict[str, Any] = {}
    for path, part in decode_parts(definition).items():
        if path.endswith(".json") or path == ".platform":
            try:
                projection[path] = _elide(json.loads(part.raw))
                continue
            except (ValueError, UnicodeDecodeError):
                pass
        projection[path] = {"opaque": _normalize_text(part.raw)}
    return projection


def stable_ids(definition: Mapping[str, Any]) -> frozenset[str]:
    """Stable identifiers: JSON ``id`` values, path-derived IDs and TMDL lineage tags."""

    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "id" and isinstance(item, (str, int)) and str(item):
                    found.add(str(item))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for path, part in decode_parts(definition).items():
        if path.endswith(".json"):
            try:
                walk(json.loads(part.raw))
            except (ValueError, UnicodeDecodeError):
                continue
        elif path.endswith(".tmdl"):
            found.update(_LINEAGE_TAG.findall(part.raw.decode("utf-8", errors="replace")))
    return frozenset(found)


@dataclass(frozen=True)
class ComparisonResult:
    semantically_equal: bool
    byte_identical_parts: tuple[str, ...]
    changed_paths: tuple[str, ...]
    violations: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.violations


def compare_definitions(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    allowed_changed_paths: Iterable[str] = (),
) -> ComparisonResult:
    """Fail-closed comparison of a candidate against a captured base.

    Violation codes: ``dropped_part``, ``unexpected_part``, ``changed_stable_id``,
    ``unexpected_binding_change``, ``unmodeled_semantic_edit``.
    """

    allowed = set(allowed_changed_paths)
    base_parts = decode_parts(base)
    cand_parts = decode_parts(candidate)
    base_proj = semantic_projection(base)
    cand_proj = semantic_projection(candidate)
    violations: list[str] = []
    changed: list[str] = []
    identical: list[str] = []
    for path in sorted(base_parts):
        if path not in cand_parts:
            violations.append(f"dropped_part:{path}")
            changed.append(path)
        elif base_parts[path].raw == cand_parts[path].raw:
            identical.append(path)
        elif base_proj[path] != cand_proj[path] and path not in allowed:
            changed.append(path)
            violations.append(
                f"unexpected_binding_change:{path}"
                if _BINDING_PATH.search(path)
                else f"unmodeled_semantic_edit:{path}"
            )
        elif base_proj[path] != cand_proj[path]:
            changed.append(path)
    for path in sorted(set(cand_parts) - set(base_parts)):
        changed.append(path)
        if path not in allowed:
            violations.append(f"unexpected_part:{path}")
    lost = stable_ids(base) - stable_ids(candidate)
    violations.extend(f"changed_stable_id:{value}" for value in sorted(lost))
    equal = base_proj == cand_proj
    return ComparisonResult(
        semantically_equal=equal,
        byte_identical_parts=tuple(identical),
        changed_paths=tuple(sorted(set(changed))),
        violations=tuple(violations),
    )


def assert_legacy_publisher_compatible(
    current: Mapping[str, Any], *, item_id: str = "", expected_item_id: str | None = None
) -> DefinitionFormat:
    """Deny a legacy replacement for TMDL, mixed, unknown or wrong-target items."""

    if expected_item_id is not None and item_id != expected_item_id:
        raise DefinitionFormatMismatch(
            "Legacy ontology publisher target does not match the bound item",
            detected="wrong-target",
        )
    try:
        detected = classify_definition(current)
    except DefinitionBoundsError as exc:
        raise DefinitionFormatMismatch(
            f"Captured ontology definition is not safely classifiable: {exc}",
            detected="unknown",
        ) from exc
    if detected not in ("legacy-json", "empty"):
        raise DefinitionFormatMismatch(
            "Legacy ontology publisher refuses to replace a "
            f"{detected} definition; migration requires separate approval",
            detected=detected,
        )
    return detected


@dataclass(frozen=True)
class MaterializationPlan:
    """Offline, unexecuted, approval-bound plan.  Never authorizes a write."""

    status: str
    reason: str
    base_fingerprint: str
    format: str
    replaced_paths: tuple[str, ...] = ()
    retained_paths: tuple[str, ...] = ()
    candidate: dict[str, Any] | None = None
    restore_definition: dict[str, Any] | None = None
    requires_exclusive_writer: bool = True
    requires_pre_write_base_recheck: bool = True
    requires_post_readback_comparison: bool = True
    native_cas_claimed: bool = False
    migration_approved: bool = False
    executed: bool = False
    format_migration_requires_separate_approval: bool = True
    binding_migration_requires_separate_approval: bool = True


def _denied(reason: str, base: Mapping[str, Any], fmt: str) -> MaterializationPlan:
    return MaterializationPlan(
        status="denied", reason=reason, base_fingerprint=definition_fingerprint(base), format=fmt
    )


def plan_binding_change(
    base: Mapping[str, Any], *, binding_path: str, before_table: str, after_table: str
) -> MaterializationPlan:
    """Plan a legacy DataBindings/Contextualization source-table edit.

    Only the documented ``sourceTableName`` field of one existing binding part is
    rewritten; every other part is retained byte-for-byte.  Other operation
    classes (descriptions, declarations, TMDL edits) are denied as unmodeled.
    """

    fmt = classify_definition(base)
    if fmt != "legacy-json":
        return _denied(f"unmodeled_operation_for_format:{fmt}", base, fmt)
    parts = decode_parts(base)
    part = parts.get(binding_path)
    if part is None or not _BINDING_PATH.search(binding_path):
        return _denied("binding_part_not_found", base, fmt)
    payload = json.loads(part.raw)

    def locate(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            if value.get("sourceTableName") == before_table:
                return value
            for item in value.values():
                hit = locate(item)
                if hit is not None:
                    return hit
        return None

    target = locate(payload)
    if target is None:
        return _denied("base_binding_before_value_mismatch", base, fmt)
    target["sourceTableName"] = after_table
    new_payload = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    candidate_parts = []
    for original in base.get("parts") or []:
        if original.get("path") == binding_path:
            candidate_parts.append({**original, "payload": new_payload})
        else:
            candidate_parts.append(dict(original))
    candidate = {"parts": candidate_parts}
    result = compare_definitions(base, candidate, allowed_changed_paths=[binding_path])
    if not result.ok:
        return _denied("candidate_failed_preservation:" + ",".join(result.violations), base, fmt)
    return MaterializationPlan(
        status="approval_required",
        reason="typed binding change planned offline; unexecuted",
        base_fingerprint=definition_fingerprint(base),
        format=fmt,
        replaced_paths=(binding_path,),
        retained_paths=tuple(p for p in sorted(parts) if p != binding_path),
        candidate=candidate,
        restore_definition=json.loads(json.dumps(base)),
    )


def plan_operation(base: Mapping[str, Any], operation: Mapping[str, Any]) -> MaterializationPlan:
    """Dispatch a typed schema operation; unrecognized semantics deny."""

    fmt = classify_definition(base)
    if operation.get("op") == "binding_change" and operation.get("binding_path"):
        return plan_binding_change(
            base,
            binding_path=str(operation["binding_path"]),
            before_table=str(operation.get("before") or ""),
            after_table=str(operation.get("after") or ""),
        )
    return _denied(f"unmodeled_operation:{operation.get('op')!s}", base, fmt)
