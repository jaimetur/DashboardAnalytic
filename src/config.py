from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATHS_FILE = PROJECT_ROOT / 'storage-paths.conf'
STORAGE_ROOT_VARIABLES = frozenset({'APP_CONFIG_DIR', 'APP_DATA_DIR', 'APP_ASSETS_DIR'})


def load_storage_paths(path: Path = STORAGE_PATHS_FILE, environ: dict[str, str] | None = None) -> None:
    """Load storage roots from the editable project-root configuration file.

    Real environment variables retain precedence so Docker and deployment
    tooling can override the local defaults without modifying the file.
    """
    environment = os.environ if environ is None else environ
    if not path.is_file():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        if '=' not in line:
            raise ValueError(f'{path.name}:{line_number} must use KEY = value syntax.')
        key, value = (part.strip() for part in line.split('=', 1))
        if key not in STORAGE_ROOT_VARIABLES:
            raise ValueError(f'{path.name}:{line_number} has unsupported setting {key!r}.')
        value = value.strip('"\'')
        if not value:
            raise ValueError(f'{path.name}:{line_number} requires a path value.')
        # The checked-in file may contain an absolute path from the machine
        # where it was edited (for example ``/Users/...`` on macOS).  Ignore
        # such a host-specific value when its filesystem root is unavailable,
        # so CI and container deployments fall back to project-local paths.
        configured_path = Path(os.path.expandvars(os.path.expanduser(value)))
        if path.resolve() == STORAGE_PATHS_FILE.resolve() and configured_path.is_absolute():
            top_level = configured_path.anchor
            if len(configured_path.parts) > 1:
                top_level = str(Path(configured_path.anchor) / configured_path.parts[1])
            if not Path(top_level).exists():
                continue
        environment.setdefault(key, value)


load_storage_paths()


def project_path(env_var: str, default: str) -> Path:
    raw_value = os.getenv(env_var, default)
    path = Path(os.path.expandvars(os.path.expanduser(raw_value)))
    return path if path.is_absolute() else PROJECT_ROOT / path


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

    # These three roots are the only storage-path settings. All application
    # databases, templates and workspace directories derive from them.
    config_dir: Path = project_path("APP_CONFIG_DIR", "config")
    data_dir: Path = project_path("APP_DATA_DIR", "data")
    assets_dir: Path = project_path("APP_ASSETS_DIR", "assets")

    database_path: Path = config_dir / "app.db"
    slides_templates_dir: Path = config_dir / "slides-templates"
    ppt_templates_dir: Path = assets_dir / "ppt-templates"
    input_dir: Path = data_dir / "input"
    output_dir: Path = data_dir / "output"
    export_dir: Path = data_dir / "exports"

settings = Settings()
