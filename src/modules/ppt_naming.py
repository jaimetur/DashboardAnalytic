"""Stored names of the modules renamed to PPT Dashboards and PPT Reporting (old).

E2E Dashboards became PPT Dashboards and Reporting (old) became PPT Reporting (old). The
Dashboards of each workspace, the Features Activation rules and the Interface Settings of
the main modules are stored under the module names, so they are renamed once in the
application database and in every workspace database (also one restored or transferred
from a server that still used the former names).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

MODULE_KEYS = {'e2e-dashboards': 'ppt-dashboards', 'reporting-old': 'ppt-reporting-old'}
# Former titles of the modules, also E2E Reporting (Reporting (old) before 0.6.0), stored by Interface Settings.
MODULE_TITLES = {'E2E Dashboards': 'PPT Dashboards', 'Reporting (old)': 'PPT Reporting (old)', 'E2E Reporting': 'PPT Reporting (old)'}
WORKSPACE_STATE_PREFIXES = (('e2e_dashboard', 'ppt_dashboard'),)


def _renamed_modules(document: Any) -> tuple[Any, bool]:
    """The settings of every module under its new key, with the former titles and tab icons renamed."""
    if not isinstance(document, dict):
        return document, False
    renamed = {}
    for key, value in document.items():
        new_key = MODULE_KEYS.get(key, key)
        if new_key in MODULE_KEYS.values() and isinstance(value, dict):
            value = {**value}
            for field in ('title', 'short_title'):
                if value.get(field) in MODULE_TITLES:
                    value[field] = MODULE_TITLES[value[field]]
            if value.get('tab_icon') in MODULE_KEYS:
                value['tab_icon'] = MODULE_KEYS[value['tab_icon']]
        if key in MODULE_KEYS or new_key not in renamed:
            renamed[new_key] = value
    return renamed, renamed != document


def migrate_application_state(repository: Any, state_keys: tuple[str, ...]) -> None:
    """Rename the modules in the Features Activation rules and the Interface Settings."""
    for state_key in state_keys:
        raw = repository.get_application_state(state_key)
        try:
            document = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            continue
        renamed, changed = _renamed_modules(document)
        if changed:
            repository.set_application_state(state_key, json.dumps(renamed, sort_keys=True))


def migrate_workspace_database(database_path: Path) -> None:
    """Rename the Dashboards state of a workspace database."""
    if not Path(database_path).is_file():
        return
    with sqlite3.connect(database_path, timeout=30) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workspace_state'").fetchone():
            return
        for old, new in WORKSPACE_STATE_PREFIXES:
            rows = connection.execute('SELECT key FROM workspace_state WHERE key LIKE ?', (f'{old}%',)).fetchall()
            for (key,) in rows:
                target = new + key[len(old):]
                if connection.execute('SELECT 1 FROM workspace_state WHERE key = ?', (target,)).fetchone():
                    connection.execute('DELETE FROM workspace_state WHERE key = ?', (key,))
                else:
                    connection.execute('UPDATE workspace_state SET key = ? WHERE key = ?', (target, key))
