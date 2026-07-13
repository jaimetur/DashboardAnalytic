from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

# Allow running this file directly from PyCharm without requiring the
# project root to be preconfigured in PYTHONPATH.
if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.DashboardAnalytic import app
from src.config import settings


if __name__ == "__main__":
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)
