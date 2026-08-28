"""Hermes directory-plugin entry point.

The plugin installer copies the repository directory. Add the bundled src tree
so the plugin remains importable without editing Hermes core.
"""

import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from onboarding.plugin import register

__all__ = ["register"]
