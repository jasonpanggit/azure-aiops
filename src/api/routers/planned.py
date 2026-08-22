"""Roadmap routes not yet graduated into implementation.

Network topology, traffic-flow validation, and design-gap detection graduated
out of this module in Prompt 16; they are now served by ``routers/network.py``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["planned"])
