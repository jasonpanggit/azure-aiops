#!/usr/bin/env python3
"""Validate one immutable Operations Copilot coordinator version."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from operations.foundry_agent import validate_executive_synthesis
from operations.orchestration_contract import CandidatePlan


def _request_json(
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=(
            json.dumps(payload, separators=(",", ":")).encode()
            if payload is not None
            else None
        ),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise TypeError("Foundry returned a non-object response")
    return value


def _token() -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["AZURE_CLIENT_ID"],
            "client_secret": os.environ["AZURE_CLIENT_SECRET"],
            "scope": "https://ai.azure.com/.default",
        }
    ).encode()
    request = urllib.request.Request(
        (
            "https://login.microsoftonline.com/"
            f"{os.environ['AZURE_TENANT_ID']}/oauth2/v2.0/token"
        ),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("Foundry token response omitted access_token")
    return token


def _answer_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    fragments: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, dict):
                text = text.get("value")
            if isinstance(text, str) and text.strip():
                fragments.append(text.strip())
    return "\n".join(fragments)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validation_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--provider-version-id", required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    token = _token()
    endpoint = args.endpoint.rstrip("/")
    version = args.provider_version_id.rsplit(":", 1)[-1]
    metadata = _request_json(
        (
            f"{endpoint}/agents/{args.agent_name}/versions/{version}"
            "?api-version=v1"
        ),
        token=token,
    )
    definition = metadata.get("definition") or {}
    if (
        metadata.get("status") != "active"
        or metadata.get("name") != args.agent_name
        or str(metadata.get("version") or "") != version
        or definition.get("model") != args.expected_model
    ):
        raise RuntimeError("Coordinator metadata does not match activation contract")

    plan_payload = {
        "agent_reference": {
            "type": "agent_reference",
            "name": args.agent_name,
            "version": version,
        },
        "input": [{
            "role": "user",
            "content": (
                "Return ONLY this JSON planning object with no markdown: "
                '{"steps":[{"specialist_id":"network","tool_calls":'
                '[{"tool":"firewall_nsg_gaps","arguments":'
                '{"category":"firewall_bypass"},"citation_ids":'
                '["snapshot:coverage"],"mutation":false}],'
                '"depends_on":[]}],"estimated_tokens":0,'
                '"max_wall_seconds":30,"mutation_intent":false}'
            ),
        }],
        "max_output_tokens": 2_000,
    }
    response = _request_json(
        f"{endpoint}/openai/v1/responses",
        token=token,
        payload=plan_payload,
    )
    text = _answer_text(response)
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
        if text.casefold().startswith("json\n"):
            text = text[5:].strip()
    plan = CandidatePlan.model_validate_json(text)
    call = plan.steps[0].tool_calls[0]
    if (
        len(plan.steps) != 1
        or len(plan.steps[0].tool_calls) != 1
        or plan.steps[0].specialist_id != "network"
        or call.tool != "firewall_nsg_gaps"
        or call.arguments != {"category": "firewall_bypass"}
        or call.mutation
        or plan.mutation_intent
    ):
        raise RuntimeError("Coordinator live planning response changed the bounded probe")

    evidence_ref = "tool:coordinator-validation:0"
    synthesis_payload = {
        "agent_reference": {
            "type": "agent_reference",
            "name": args.agent_name,
            "version": version,
        },
        "input": [{
            "role": "user",
            "content": (
                "Return ONLY JSON with shape {\"findings\":[...]}. Include "
                "exactly one finding with finding_id=\"validation-network\", "
                f"evidence_refs=[\"{evidence_ref}\"], confidence=\"high\", "
                "uncertainty=[], freshness=\"fresh\", actionable=false, "
                "next_check=\"Review the cited subnet route.\", and a concise "
                "summary that states the payments subnet bypasses inspection."
            ),
        }],
        "max_output_tokens": 2_000,
    }
    synthesis_response = _request_json(
        f"{endpoint}/openai/v1/responses",
        token=token,
        payload=synthesis_payload,
    )
    synthesis_text = _answer_text(synthesis_response)
    claims = validate_executive_synthesis(
        synthesis_text,
        evidence_refs={evidence_ref},
    )
    if (
        len(claims) != 1
        or evidence_ref not in claims[0]["evidence_refs"]
        or "bypasses inspection" not in claims[0]["summary"].casefold()
    ):
        raise RuntimeError("Coordinator live synthesis response failed validation")

    artifact = {
        "status": "validated",
        "manifest_digest": args.manifest_digest,
        "agent_name": args.agent_name,
        "provider_version_id": args.provider_version_id,
        "model": args.expected_model,
        "planning_probe": "pass",
        "synthesis_probe": "pass",
        "supersedes_unusable_versions": ["1", "2", "3", "4"],
    }
    artifact["validation_digest"] = _validation_digest(artifact)
    _atomic_write(Path(args.out), artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
