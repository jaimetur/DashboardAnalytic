from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(env_var: str, default: str) -> Path:
    raw_value = os.getenv(env_var, default)
    path = Path(raw_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def configured_path(env_var: str, base_dir: Path, default_name: str) -> Path:
    """Use an explicit path override, otherwise resolve below its storage root."""
    override = os.getenv(env_var)
    return project_path(env_var, override) if override else base_dir / default_name


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Dashboard Analytic")
    app_release_date: str = os.getenv("APP_RELEASE_DATE", "2026-07-14")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "7278"))
    dev_port: int = int(os.getenv("APP_DEV_PORT", "7279"))
    secret_key: str = os.getenv("APP_SECRET_KEY", "change-me-dashoboard-analytic")
    admin_username: str = os.getenv("APP_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("APP_ADMIN_PASSWORD", "admin123")
    template_dir: Path = project_path("APP_TEMPLATE_DIR", "src/web_interface/templates")
    static_dir: Path = project_path("APP_STATIC_DIR", "src/web_interface/static")
    allowed_extensions: tuple[str, ...] = (".csv", ".xlsx", ".xls", ".xlsm")

    # These three roots can point outside the project. Individual APP_* paths
    # remain available when a deployment needs a more specific override.
    config_dir: Path = project_path("CONFIG_DIR", "config")
    data_dir: Path = project_path("DATA_DIR", "data")
    assets_dir: Path = project_path("ASSETS_DIR", "assets")

    database_path: Path = configured_path("APP_DATABASE_PATH", config_dir, "app.db")
    slides_templates_dir: Path = configured_path("APP_SLIDES_TEMPLATES_DIR", config_dir, "slides-templates")
    ppt_templates_dir: Path = configured_path("APP_PPT_TEMPLATES_DIR", assets_dir, "ppt-templates")
    input_dir: Path = configured_path("APP_INPUT_DIR", data_dir, "input")
    output_dir: Path = configured_path("APP_OUTPUT_DIR", data_dir, "output")
    export_dir: Path = configured_path("APP_EXPORT_DIR", data_dir, "exports")

settings = Settings()
