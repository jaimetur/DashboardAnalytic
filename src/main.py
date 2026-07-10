from __future__ import annotations

import uvicorn

from src.BenchAutomations import app
from src.config import settings


if __name__ == "__main__":
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)
