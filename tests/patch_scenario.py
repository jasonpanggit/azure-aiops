from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intelligence.patch.patch_intelligence import PatchIntelligence


def patch_engine(**kwargs) -> PatchIntelligence:
    scenario = json.loads(Path("tests/fixtures/mock_patch_intelligence.json").read_text())
    return PatchIntelligence.from_semantic_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        **kwargs,
    )
