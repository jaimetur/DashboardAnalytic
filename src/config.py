from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Bench Automations")
    app_version: str = os.getenv("APP_VERSION", "0.1.0")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "7278"))
    dev_port: int = int(os.getenv("APP_DEV_PORT", "7279"))
    secret_key: str = os.getenv("APP_SECRET_KEY", "change-me-bench-automations")
    admin_username: str = os.getenv("APP_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("APP_ADMIN_PASSWORD", "admin123")
    database_path: Path = Path(os.getenv("APP_DATABASE_PATH", "config/app.db"))
    input_dir: Path = Path(os.getenv("APP_INPUT_DIR", "data/input"))
    output_dir: Path = Path(os.getenv("APP_OUTPUT_DIR", "data/output"))
    export_dir: Path = Path(os.getenv("APP_EXPORT_DIR", "data/exports"))
    template_dir: Path = Path(os.getenv("APP_TEMPLATE_DIR", "src/web_interface/templates"))
    static_dir: Path = Path(os.getenv("APP_STATIC_DIR", "src/web_interface/static"))
    allowed_extensions: tuple[str, ...] = (".csv", ".xlsx", ".xls")


settings = Settings()
