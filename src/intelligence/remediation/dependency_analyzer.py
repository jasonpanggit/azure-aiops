from __future__ import annotations

from typing import Any


class DependencyAnalyzer:
    """Builds bounded public dependency context from governed graph projections."""

    def __init__(self, *, max_dependencies: int = 100) -> None:
        if isinstance(max_dependencies, bool) or not isinstance(max_dependencies, int):
            raise TypeError("max_dependencies must be an integer")
        if max_dependencies < 1:
            raise ValueError("max_dependencies must be positive")
        self.max_dependencies = max_dependencies

    def analyze(self, resource: dict[str, Any]) -> dict[str, Any]:
        upstream = self._names(resource.get("upstream_dependencies"))
        downstream = self._names(resource.get("downstream_dependencies"))
        return {
            "affected_applications": self._known(resource.get("application")),
            "affected_services": self._known(resource.get("business_service")),
            "owners": self._known(resource.get("owner")),
            "service_owners": self._known(resource.get("service_owner")),
            "support_teams": self._known(resource.get("support_team")),
            "upstream_dependencies": upstream,
            "downstream_dependencies": downstream,
            "dependency_count": len(upstream) + len(downstream),
            "traversal_bounded": True,
        }

    def _names(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        names = sorted(
            {
                str(item.get("name") if isinstance(item, dict) else item).strip()[:512]
                for item in value
                if str(item.get("name") if isinstance(item, dict) else item).strip()
            }
        )
        if len(names) > self.max_dependencies:
            raise ValueError("Dependency traversal exceeds configured bound")
        return names

    @staticmethod
    def _known(value: Any) -> list[str]:
        text = str(value or "").strip()[:512]
        return [] if not text or text.casefold() == "unknown" else [text]
