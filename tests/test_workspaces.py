from __future__ import annotations

import sqlite3
from pathlib import Path

from src.modules.workspaces import WorkspaceRegistry


def test_registry_keeps_existing_workspace_database_when_migrating_external_roots(tmp_path: Path) -> None:
    config_dir = tmp_path / 'external-config'
    data_dir = tmp_path / 'external-data'
    legacy_database = config_dir / 'app.db'
    target_database = data_dir / 'workspaces' / 'UK' / 'UK.db'
    registry_path = data_dir / 'workspaces' / 'workspace-registry.db'
    config_dir.mkdir()
    target_database.parent.mkdir(parents=True)
    with sqlite3.connect(legacy_database) as conn:
        conn.execute('CREATE TABLE legacy_marker (value TEXT)')
    with sqlite3.connect(target_database) as conn:
        conn.execute('CREATE TABLE workspace_marker (value TEXT)')
    with sqlite3.connect(registry_path) as conn:
        conn.executescript(
            '''
            CREATE TABLE workspaces (
                id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                database_path TEXT NOT NULL, input_dir TEXT NOT NULL, output_dir TEXT NOT NULL,
                export_dir TEXT NOT NULL, slides_templates_dir TEXT NOT NULL,
                created_at TEXT NOT NULL, last_opened_at TEXT NOT NULL
            );
            CREATE TABLE workspace_state (key TEXT PRIMARY KEY, value TEXT);
            '''
        )
        conn.execute(
            'INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('default', 'UK', str(legacy_database), str(data_dir / 'input'), str(data_dir / 'output'),
             str(data_dir / 'exports'), str(config_dir / 'slides-templates'), '2026-01-01', '2026-01-01'),
        )

    registry = WorkspaceRegistry(registry_path, legacy_database, data_dir, config_dir / 'slides-templates')
    registry.initialize()

    workspace = registry.get('default')
    assert workspace is not None
    assert workspace.database_path == target_database
    assert target_database.exists()
    assert legacy_database.exists()
