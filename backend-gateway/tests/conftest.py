"""Conftest for backend-gateway tests.

Adds the project root to sys.path so that imports like
``from src.ingestion.market_data_collector import ...`` resolve when
tests are executed from the backend-gateway directory.
"""

import sys
from pathlib import Path

# Project root is two levels up from backend-gateway/tests/
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
