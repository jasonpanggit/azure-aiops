"""Bounded artifact inspection; credentials are rejected, never silently retained."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from .models import CHANGE_SOURCES

MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 24
MAX_NODES = 50_000
MAX_CHANGES = 500
REDACTED = "[REDACTED]"
_CREDENTIAL = re.compile(
    r"password|passwd|secret|token|privatekey|connectionstring|authorization|"
    r"accesskey|accountkey|clientkey|sharedaccesssignature|^sas$"
)


def _sensitive_name(value: str) -> bool:
    return bool(_CREDENTIAL.search(re.sub(r"[^a-z0-9]", "", value.casefold())))


def _present(value: Any) -> bool:
    return value is not None and value != ""


def inspect_artifact(source: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate bounded JSON and return provenance without retaining its values.

    Detection covers credential-like keys, named environment values and Terraform
    sensitivity masks, not arbitrary secrets embedded in prose or source code.
    """
    if source not in CHANGE_SOURCES:
        raise ValueError("Unsupported change source.")
    if not isinstance(payload, dict):
        raise TypeError("The artifact must be a JSON object.")
    nodes = 0
    withheld = 0
    sensitive = 0

    def visit(value: Any, depth: int, mask: Any = None, credential: bool = False, metadata: bool = False) -> None:
        nonlocal nodes, withheld, sensitive
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError("Artifact exceeds the 24-level or 50000-value structural limit.")
        if metadata and value is not None and not isinstance(value, (bool, dict, list)):
            raise ValueError("Terraform sensitivity masks must contain only boolean, null, object or array values.")
        if isinstance(value, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise ValueError("Artifact contains invalid Unicode.")
            if value == REDACTED and not metadata:
                withheld += 1
                return
        if not metadata and (mask is True or credential) and _present(value):
            sensitive += 1
        if isinstance(value, dict):
            named_credential = isinstance(value.get("name"), str) and _sensitive_name(value["name"])
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > 256:
                    raise ValueError("Artifact object keys must be strings of at most 256 characters.")
                if any(0xD800 <= ord(char) <= 0xDFFF for char in key):
                    raise ValueError("Artifact contains invalid Unicode.")
                child_mask = mask.get(key) if isinstance(mask, dict) else None
                if key in ("before", "after"):
                    child_mask = value.get(f"{key}_sensitive", child_mask)
                is_mask = key in ("before_sensitive", "after_sensitive")
                visit(
                    child, depth + 1, child_mask,
                    not is_mask and (_sensitive_name(key) or (named_credential and key == "value")),
                    metadata or is_mask,
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                child_mask = mask[index] if isinstance(mask, list) and index < len(mask) else None
                visit(child, depth + 1, child_mask, metadata=metadata)
        elif value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError("Artifact contains a non-JSON value.")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if (isinstance(value, int) and abs(value) > 9_007_199_254_740_991) or (
                isinstance(value, float) and (
                    not math.isfinite(value) or (value.is_integer() and abs(value) > 9_007_199_254_740_991)
                )
            ):
                raise ValueError("Artifact numbers must be finite and integers must be JavaScript-safe.")

    visit(payload, 0)
    array_key = "resource_changes" if source == "terraform_plan" else "files" if source == "github_pull_request" else "changes"
    arrays = [payload[array_key]] if array_key in payload else []
    if source in ("bicep_what_if", "arm_diff") and "properties" in payload:
        properties = payload["properties"]
        if not isinstance(properties, dict):
            raise ValueError("Artifact properties must be an object.")
        if "changes" in properties:
            arrays.append(properties["changes"])
    for entries in arrays:
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise ValueError(f"Artifact {array_key} must be an array of objects.")
        if len(entries) > MAX_CHANGES:
            raise ValueError("Artifact may contain at most 500 changes or files.")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("Artifact exceeds the 2 MiB UTF-8 limit.")
    if sensitive:
        raise ValueError("Detected sensitive values must be redacted locally before assessment.")
    canonical = json.dumps(
        {"schema_version": 1, "source": source, "payload": payload},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("ascii")
    return {
        "schema_version": 1,
        "source": source,
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "canonicalization": "python-json-ascii-sorted-v1",
        "utf8_bytes": len(encoded),
        "withheld_value_count": withheld,
        "interpretation": (
            "Digest of the submitted JSON values and source, not original file bytes or source authenticity. "
            "Credential detection is heuristic, not comprehensive DLP. No deployment is authorized."
        ),
    }
