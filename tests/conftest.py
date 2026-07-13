from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.DashboardAnalytic as app_module
from src.config import settings


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    input_dir = data_dir / "input"
    output_dir = data_dir / "output"
    export_dir = data_dir / "exports"

    for directory in (config_dir, input_dir, output_dir, export_dir):
        directory.mkdir(parents=True, exist_ok=True)

    object.__setattr__(settings, "database_path", config_dir / "app.db")
    object.__setattr__(settings, "input_dir", input_dir)
    object.__setattr__(settings, "output_dir", output_dir)
    object.__setattr__(settings, "export_dir", export_dir)
    app_module.repository.db_path = settings.database_path
    app_module.SESSIONS.clear()

    with TestClient(app_module.app) as test_client:
        yield test_client
