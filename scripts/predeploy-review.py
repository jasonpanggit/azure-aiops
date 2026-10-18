"""Read-only CI review of a locally inspected artifact against its retained receipt."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

import httpx

from intelligence.predeploy.intake import MAX_BYTES, inspect_artifact
from intelligence.predeploy.models import CHANGE_SOURCES
from operations.predeploy_review import CIReviewContract, review_digest

MAX_RESPONSE_BYTES = 512 * 1024


class _ReviewParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        """Invalid arguments must not use the review-required exit code or echo values."""
        self.print_usage(sys.stderr)
        self.exit(
            1,
            "Predeploy review arguments are invalid; use --help. No deployment is authorized.\n",
        )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys")
        result[key] = value
    return result


def _json(raw: bytes):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)


def _checkout_commit() -> str:
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        raise ValueError("Invalid checkout identity")
    subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--"], check=True, capture_output=True
    )
    if any(
        os.environ.get(name, head) != head
        for name in ("GITHUB_SHA", "BUILD_SOURCEVERSION")
    ):
        raise ValueError("Checkout differs from the CI revision")
    return head


def fetch_review(
    client: httpx.Client,
    api_url: str,
    token: str,
    assessment_id: str,
    artifact_sha256: str,
    scope: dict[str, list[str]],
) -> CIReviewContract:
    """Use one bounded authenticated GET; never follow redirects, replay or send an artifact."""
    query = [(name, value) for name, values in scope.items() for value in values]
    query.append(("artifact_sha256", artifact_sha256))
    with client.stream(
        "GET",
        f"{api_url}/api/v1/changes/retained-assessments/{assessment_id}/review-contract",
        params=query,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    ) as response:
        if response.status_code != 200:
            raise ValueError("Review endpoint did not confirm the requested evidence")
        if (
            response.headers.get("content-type", "").split(";")[0] != "application/json"
            or response.headers.get("content-encoding", "identity") != "identity"
        ):
            raise ValueError("Review response must be uncompressed JSON")
        raw = bytearray()
        for chunk in response.iter_bytes(chunk_size=8192):
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Review response exceeds its byte limit")
    envelope = _json(bytes(raw))
    contract = CIReviewContract.model_validate(envelope["data"])
    if (
        envelope.get("scope") != scope
        or contract.scope != scope
        or contract.receipt.assessment_id != assessment_id
        or contract.receipt.artifact_sha256 != artifact_sha256
    ):
        raise ValueError(
            "Review evidence identity differs from the requested scope or artifact"
        )
    return contract


def main(argv: list[str] | None = None) -> int:
    """Emit a review-only JSON report; return 0 advisory-clear, 2 review-required, 1 failure."""
    parser = _ReviewParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source", choices=CHANGE_SOURCES, required=True)
    parser.add_argument("--assessment-id", required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--scope-json", default="{}")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)
    stage = "local identity and scope validation"
    try:
        # Local validation must precede any request carrying the configured reader token.
        from api.scope import Scope

        if not re.fullmatch(r"[0-9a-f]{32}", args.assessment_id):
            raise ValueError("Invalid assessment identity")
        if not re.fullmatch(r"[0-9a-f]{64}", args.review_sha256):
            raise ValueError("A reviewed immutable contract digest is required")
        if not re.fullmatch(
            r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){1,2}", args.repository
        ):
            raise ValueError("Repository identity is required")
        raw_scope = _json(args.scope_json.encode("utf-8"))
        if not isinstance(raw_scope, dict) or any(
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value.strip() for value in values)
            for values in raw_scope.values()
        ):
            raise ValueError("Invalid scope declaration")
        scope = Scope.from_mapping(raw_scope).to_dict()
        stage = "clean checkout verification"
        commit = _checkout_commit()
        stage = "bounded local artifact inspection"
        if not args.artifact.is_file():
            raise ValueError("Artifact must be a regular JSON file")
        with args.artifact.open("rb") as artifact:
            raw = artifact.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Artifact exceeds its byte limit")
        artifact_digest = inspect_artifact(args.source, _json(raw))["sha256"]
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary and Path(summary).resolve() == args.artifact.resolve():
            raise ValueError("The summary output must not replace the source artifact")
        stage = "HTTPS reader configuration"
        api_url = os.environ.get("AIOPS_PREDEPLOY_API_URL", "").rstrip("/")
        parsed = urlsplit(api_url)
        if (
            any(ord(char) < 33 or ord(char) > 126 for char in api_url)
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise ValueError("A trusted HTTPS API origin is required")
        token = os.environ.get("AIOPS_PREDEPLOY_REVIEW_TOKEN", "")
        if not token or any(char.isspace() for char in token):
            raise ValueError("A configured reader token is required")
        stage = "retained review request and integrity verification"
        with httpx.Client(
            timeout=30.0,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept-Encoding": "identity"},
        ) as client:
            contract = fetch_review(
                client, api_url, token, args.assessment_id, artifact_digest, scope
            )
        if contract.receipt.source != args.source:
            raise ValueError("Review source format differs from the local artifact")
        if contract.review_sha256 != args.review_sha256:
            raise ValueError(
                "The returned review differs from the explicitly pinned evidence"
            )
        stage = "final checkout verification"
        if _checkout_commit() != commit:
            raise ValueError("Checkout changed while the review was being read")
        data = {
            "schema_version": 1,
            "contract": contract.model_dump(),
            "local_checkout": {"repository": args.repository, "commit": commit},
            "interpretation": "Local checkout binding, not proof that this artifact was generated by that commit or an authenticated remote CI attestation. No deployment is authorized.",
        }
        report = {**data, "binding_sha256": review_digest(data)}
        stage = "review report output"
        if summary:
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write(
                    "## Predeploy advisory review\n\n"
                    f"Disposition: **{contract.disposition}**. No deployment authority.\n\n"
                    f"Assessment: `{args.assessment_id}`\n\n"
                    f"Local checkout: `{commit}`\n\n"
                    f"Artifact SHA-256: `{artifact_digest}`\n\n"
                    f"Receipt SHA-256: `{contract.receipt_sha256}`\n\n"
                    f"Review SHA-256: `{contract.review_sha256}`\n\n"
                    f"Binding SHA-256: `{report['binding_sha256']}`\n\n"
                    "JSON integrity only, not a signature, applied fix or runtime guarantee.\n"
                )
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
        return 2 if contract.disposition == "review_required" else 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        subprocess.CalledProcessError,
        httpx.HTTPError,
        httpx.InvalidURL,
    ):
        print(
            f"Predeploy review not confirmed during {stage}. Check the local reviewed artifact, clean checkout, "
            "exact personal scope, retained receipt and configured HTTPS reader access. "
            "No deployment is authorized; no retry or write was attempted.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
