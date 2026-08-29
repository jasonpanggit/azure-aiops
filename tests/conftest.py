"""Pytest configuration and fixtures."""

import sys
from pathlib import Path

# Add src directory to Python path so imports like `from operations import X` work
repo_root = Path(__file__).parent.parent
src_path = repo_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
