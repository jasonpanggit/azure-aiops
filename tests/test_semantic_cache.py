from __future__ import annotations

from fabric.runtime import FabricRuntime
from semantic.semantic_cache import SemanticCache


def test_cache_expires_entries_and_tracks_hit_ratio():
    now = [100.0]
    cache = SemanticCache(max_entries=2, ttl_seconds=10, clock=lambda: now[0])
    cache.set("vm:1", {"name": "vm1"})

    assert cache.get("vm:1") == {"name": "vm1"}
    assert cache.stats().hit_ratio == 1.0

    now[0] = 111.0
    assert cache.get("vm:1") is None
    assert cache.stats().hits == 1
    assert cache.stats().misses == 1


def test_cache_is_lru_bounded_and_invalidates_by_knowledge_version():
    cache = SemanticCache(max_entries=2, ttl_seconds=60, clock=lambda: 100.0)
    cache.set("a", 1, knowledge_version="v1")
    cache.set("b", 2, knowledge_version="v1")
    assert cache.get("a", knowledge_version="v1") == 1
    cache.set("c", 3, knowledge_version="v1")

    assert cache.get("b", knowledge_version="v1") is None
    assert cache.get("a", knowledge_version="v2") is None


def test_cache_returns_defensive_copies():
    cache = SemanticCache(max_entries=2, ttl_seconds=60, clock=lambda: 100.0)
    cache.set("context", {"sections": {"items": ["safe"]}})

    first = cache.get("context")
    first["sections"]["items"].append("mutated")

    assert cache.get("context") == {"sections": {"items": ["safe"]}}


def test_fabric_runtime_reuses_engine_until_knowledge_version_changes():
    class Service:
        version = "v1"

        def semantic_snapshot(self):
            return {
                "entities": [],
                "relationships": [],
                "inventory": [],
                "compliance": [],
                "security": [],
                "cost": [],
                "knowledge_version": self.version,
                "freshness": "2026-08-17T00:00:00Z",
            }

    service = Service()
    runtime = FabricRuntime(None, {}, {}, service)

    first = runtime.semantic_engine()
    second = runtime.semantic_engine()
    service.version = "v2"
    third = runtime.semantic_engine()

    assert first is second
    assert third is not second


def test_fabric_runtime_reuses_operations_agent_until_semantic_version_changes():
    class Service:
        version = "v1"

        def semantic_version(self):
            return self.version

        def semantic_snapshot(self):
            return {
                "entities": [],
                "relationships": [],
                "inventory": [],
                "compliance": [],
                "security": [],
                "cost": [],
                "knowledge_version": self.version,
                "freshness": "2026-08-17T00:00:00Z",
            }

    service = Service()
    runtime = FabricRuntime(None, {}, {}, service)

    first = runtime.operations_agent()
    second = runtime.operations_agent()
    service.version = "v2"
    third = runtime.operations_agent()

    assert first is second
    assert third is not second
