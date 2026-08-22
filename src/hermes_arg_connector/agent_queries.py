from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class ContextQueryService:
    SUPPORTED = (
        "show me all vms",
        "show me non-compliant servers",
        "show servers approaching os eol",
        "show patch failures",
    )

    def __init__(self, output_dir: str) -> None:
        self._is_local = urlparse(str(output_dir)).scheme not in ("abfss", "abfs", "az")
        if self._is_local:
            # Preserve the original local behaviour, including the symlink
            # containment checks in `_load` below.
            self.root = Path(output_dir).expanduser().resolve()
            self.current = self.root / "current"
        else:
            # Remote (ADLS Gen2) root: no symlinks, delegate to DatasetStore's
            # `current.json` pointer mechanism instead.
            from .storage import DatasetStore

            self._store = DatasetStore(output_dir)

    def answer(self, question: str) -> dict[str, Any]:
        intent = " ".join(question.lower().strip().rstrip(".?").split())
        if intent == "show me all vms":
            items = [_public_server(row) for row in self._load("entities/VirtualMachine")]
        elif intent == "show me non-compliant servers":
            items = self._non_compliant()
        elif intent == "show servers approaching os eol":
            items = self._eol_servers()
        elif intent == "show patch failures":
            items = [_public_assessment(row) for row in self._load("entities/PatchAssessment") if _failed(row)]
        else:
            raise ValueError("Supported questions: " + "; ".join(self.SUPPORTED))
        return {"question": question, "count": len(items), "items": sorted(items, key=lambda row: (row.get("name") or row.get("displayName") or row.get("id") or ""))}

    def _non_compliant(self) -> list[dict]:
        servers = self._servers_by_id()
        output: list[dict] = []
        for assessment in self._load("entities/PatchAssessment"):
            status = str(assessment.get("status") or "").lower()
            counts = assessment.get("availablePatchCountByClassification") or {}
            if isinstance(counts, str):
                counts = json.loads(counts or "{}")
            missing = sum(int(value or 0) for value in counts.values()) if isinstance(counts, dict) else 0
            non_compliant_status = any(
                term in status for term in ("noncompliant", "non-compliant", "fail", "error")
            )
            if non_compliant_status or missing > 0 or _has_failure_error(assessment.get("errorDetails")):
                server = dict(servers.get(str(assessment.get("targetResourceId") or ""), {}))
                if server:
                    server["patchStatus"] = assessment.get("status")
                    server["missingPatchCount"] = missing
                    output.append(_public_server(server))
        return _dedupe(output)

    def _eol_servers(self) -> list[dict]:
        servers = self._servers_by_id()
        terms = ("end of support", "end-of-support", "end of life", "eol", "retire")
        output: list[dict] = []
        for recommendation in self._load("entities/AdvisorRecommendation"):
            text = f"{recommendation.get('problem', '')} {recommendation.get('solution', '')}".lower()
            if any(term in text for term in terms):
                server = dict(servers.get(str(recommendation.get("targetResourceId") or ""), {}))
                if server:
                    server["advisorProblem"] = recommendation.get("problem")
                    server["advisorSolution"] = recommendation.get("solution")
                    output.append(_public_server(server))
        return _dedupe(output)

    def _servers_by_id(self) -> dict[str, dict]:
        rows = self._load("entities/VirtualMachine") + self._load("entities/ArcServer")
        return {str(row.get("id") or ""): row for row in rows}

    def _load(self, name: str) -> list[dict]:
        if not self._is_local:
            return self._store.read_dataset(name)

        root = self.current.resolve(strict=True)
        try:
            root.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"Current dataset pointer resolves outside configured data root: {self.current}"
            ) from exc
        path = (self.current / name).with_suffix(".jsonl")
        if not path.exists():
            return []
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Dataset path resolves outside configured data root: {path}") from exc
        if not resolved.is_file():
            raise ValueError(f"Dataset path is not a regular file: {path}")
        return [json.loads(line) for line in resolved.read_text().splitlines() if line.strip()]


def _failed(row: dict) -> bool:
    status = str(row.get("status") or "").lower()
    errors = row.get("errorDetails") or []
    if isinstance(errors, str):
        errors = json.loads(errors or "[]")
    return any(term in status for term in ("fail", "error")) or _has_failure_error(errors)


def _has_failure_error(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, list):
        return any(_has_failure_error(item) for item in value)
    if isinstance(value, dict):
        code = str(value.get("code") or "").lower()
        if code and code not in {"success", "succeeded", "ok", "0"}:
            return True
        return _has_failure_error(value.get("details"))
    return False


def _public_server(row: dict) -> dict:
    keys = (
        "id", "name", "entityType", "resourceType", "subscriptionId", "resourceGroup",
        "location", "status", "osName", "osVersion", "osType", "vmSize",
        "patchStatus", "missingPatchCount", "advisorProblem", "advisorSolution",
        "lastObservedTimestamp",
    )
    return {key: row[key] for key in keys if key in row and row[key] not in (None, "")}


def _public_assessment(row: dict) -> dict:
    errors = row.get("errorDetails") or {}
    if isinstance(errors, str):
        errors = json.loads(errors or "{}")
    result = {
        key: row[key]
        for key in ("id", "name", "targetResourceId", "status", "lastModifiedDateTime", "lastObservedTimestamp")
        if key in row and row[key] not in (None, "")
    }
    if isinstance(errors, dict):
        if errors.get("code"):
            result["errorCode"] = errors["code"]
        if errors.get("message"):
            result["errorMessage"] = errors["message"]
    return result


def _dedupe(rows: list[dict]) -> list[dict]:
    return list({str(row.get("id")): row for row in rows}.values())
