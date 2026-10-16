"""Bound the assessment request before JSON parsing or Pydantic traversal."""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from intelligence.predeploy.intake import MAX_BYTES, MAX_DEPTH

from .errors import ApiError, ErrorCode

MAX_REQUEST_BYTES = MAX_BYTES + 16 * 1024


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not supported.")
        result[key] = value
    return result


class _ArtifactRequest(Request):
    _artifact_body: bytes | None = None

    async def body(self) -> bytes:
        if self._artifact_body is None:
            chunks: list[bytes] = []
            size = 0
            async for chunk in self.stream():
                size += len(chunk)
                if size > MAX_REQUEST_BYTES:
                    raise ApiError(ErrorCode.INVALID_REQUEST, "Assessment request exceeds the bounded artifact envelope.")
                chunks.append(chunk)
            self._artifact_body = b"".join(chunks)
            depth = 0
            quoted = escaped = False
            for byte in self._artifact_body:
                if quoted:
                    if escaped:
                        escaped = False
                    elif byte == 92:
                        escaped = True
                    elif byte == 34:
                        quoted = False
                elif byte == 34:
                    quoted = True
                elif byte in (91, 123):
                    depth += 1
                    if depth > MAX_DEPTH + 2:
                        raise ApiError(ErrorCode.INVALID_REQUEST, "Artifact exceeds the 24-level structural limit.")
                elif byte in (93, 125):
                    depth -= 1
        return self._artifact_body

    async def json(self) -> Any:
        try:
            return json.loads((await self.body()).decode("utf-8"), object_pairs_hook=_pairs)
        except (ValueError, UnicodeError) as exc:
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                "Assessment requires valid UTF-8 JSON with unique object keys.",
            ) from exc


class ArtifactRoute(APIRoute):
    """Apply bounded request decoding only to the assessment mutation."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            if request.method == "POST" and request.url.path.rstrip("/") == "/api/v1/changes/assess":
                request = _ArtifactRequest(request.scope, request.receive)
            return await handler(request)

        return bounded
