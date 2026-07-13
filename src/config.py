from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(env_var: str, default: str) -> Path:
    raw_value = os.getenv(env_var, default)
    path = Path(raw_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Dashboard Analytic")
    app_release_date: str = os.getenv("APP_RELEASE_DATE", "2026-07-13")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "7278"))
    dev_port: int = int(os.getenv("APP_DEV_PORT", "7279"))
    secret_key: str = os.getenv("APP_SECRET_KEY", "change-me-dashoboard-analytic")
    admin_username: str = os.getenv("APP_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("APP_ADMIN_PASSWORD", "admin123")
    database_path: Path = project_path("APP_DATABASE_PATH", "config/app.db")
    input_dir: Path = project_path("APP_INPUT_DIR", "data/input")
    output_dir: Path = project_path("APP_OUTPUT_DIR", "data/output")
    export_dir: Path = project_path("APP_EXPORT_DIR", "data/exports")
    template_dir: Path = project_path("APP_TEMPLATE_DIR", "src/web_interface/templates")
    static_dir: Path = project_path("APP_STATIC_DIR", "src/web_interface/static")
    allowed_extensions: tuple[str, ...] = (".csv", ".xlsx", ".xls", ".xlsm")


settings = Settings()
