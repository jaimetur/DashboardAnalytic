"""Product identifiers shared by exports, backups and deployment settings.

The application was previously named Dashboard Analytic. Files, backups and
environment variables written with that name remain supported: their legacy
identifiers are mapped to the current ones when they are read.
"""
from __future__ import annotations

import os
from collections.abc import MutableMapping
from typing import Any

APP_SLUG = 'drivetest-analyzer'
LEGACY_APP_SLUG = 'dashboard-analytic'
ENVIRONMENT_PREFIX = 'DRIVETEST_ANALYZER_'
LEGACY_ENVIRONMENT_PREFIX = 'DASHBOARD_ANALYTIC_'
BACKUP_FILE_PATTERNS = (f'{APP_SLUG}-backup-*.zip', f'{LEGACY_APP_SLUG}-backup-*.zip')
# Database snapshot folders written next to a backup ZIP while it is being built.
BACKUP_SCRATCH_PATTERNS = (f'{APP_SLUG}-export-*', f'{LEGACY_APP_SLUG}-export-*')


def canonical_format(value: Any) -> Any:
    """Return a file-format identifier with the legacy product prefix replaced by the current one."""
    legacy_prefix = f'{LEGACY_APP_SLUG}-'
    if isinstance(value, str) and value.startswith(legacy_prefix):
        return f'{APP_SLUG}-{value[len(legacy_prefix):]}'
    return value


def apply_legacy_environment(environ: MutableMapping[str, str] | None = None) -> None:
    """Expose legacy DASHBOARD_ANALYTIC_* variables under their current names unless those are already set."""
    environment = os.environ if environ is None else environ
    for key, value in list(environment.items()):
        if key.startswith(LEGACY_ENVIRONMENT_PREFIX):
            environment.setdefault(f'{ENVIRONMENT_PREFIX}{key[len(LEGACY_ENVIRONMENT_PREFIX):]}', value)
