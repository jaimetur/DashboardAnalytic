from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import uvicorn

# Allow running this file directly from PyCharm without requiring the
# project root to be preconfigured in PYTHONPATH.
if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.DashboardAnalytic import app
from src.config import settings
from src.runtime_logs import ExecutionLogHandler


class ConfiguredTimezoneFormatter(logging.Formatter):
    """Format Uvicorn entries in the configured application timezone."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timezone_name = str(os.environ.get('TZ') or 'UTC').strip() or 'UTC'
        try:
            configured_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            configured_timezone = timezone.utc
        timestamp = datetime.fromtimestamp(record.created, configured_timezone)
        return timestamp.strftime(datefmt or '%Y-%m-%d %H:%M:%S')


class ConfiguredTimezoneAccessFormatter(uvicorn.logging.AccessFormatter):
    """Keep Uvicorn's access fields while using the configured timezone."""

    formatTime = ConfiguredTimezoneFormatter.formatTime


class ConfiguredTimezoneDefaultFormatter(uvicorn.logging.DefaultFormatter):
    """Keep Uvicorn's level prefix while using the configured timezone."""

    formatTime = ConfiguredTimezoneFormatter.formatTime


def execution_log_config() -> dict[str, object]:
    """Add timestamps and App Logs capture to Uvicorn's standard log setup."""
    log_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    formatters = log_config['formatters']
    formatters['default'].update({
        '()': ConfiguredTimezoneDefaultFormatter,
        'fmt': '[%(asctime)s] %(levelprefix)s %(message)s',
        'datefmt': '%Y-%m-%d %H:%M:%S',
    })
    formatters['access'].update({
        '()': ConfiguredTimezoneAccessFormatter,
        'fmt': '[%(asctime)s] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        'datefmt': '%Y-%m-%d %H:%M:%S',
    })
    log_config['handlers']['execution_default'] = {
        '()': ExecutionLogHandler,
        'formatter': 'default',
    }
    log_config['handlers']['execution_access'] = {
        '()': ExecutionLogHandler,
        'formatter': 'access',
    }
    log_config['loggers']['uvicorn']['handlers'].append('execution_default')
    log_config['loggers']['uvicorn.access']['handlers'].append('execution_access')
    return log_config


def environment_flag(name: str) -> bool:
    """Return whether an optional server-launch environment flag is enabled."""
    return str(os.environ.get(name) or '').strip().casefold() in {'1', 'true', 'yes', 'on'}


if __name__ == "__main__":
    reload_enabled = environment_flag('DASHBOARD_ANALYTIC_RELOAD')
    bind_port = int(os.environ.get('DASHBOARD_ANALYTIC_BIND_PORT') or settings.app_port)
    uvicorn.run(
        'src.DashboardAnalytic:app' if reload_enabled else app,
        host=settings.app_host,
        port=bind_port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=execution_log_config(),
        reload=reload_enabled,
        reload_dirs=[str(Path(__file__).resolve().parent)] if reload_enabled else None,
    )
