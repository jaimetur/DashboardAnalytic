from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.config import load_storage_paths
from src.modules.repository import Repository
from src.modules.workspaces import WorkspaceRegistry


def test_registry_connection_context_closes_its_sqlite_handle(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(
        tmp_path / 'workspace-registry.db', tmp_path / 'data', tmp_path / 'slides-templates',
    )

    with registry._connection() as connection:
        connection.execute('CREATE TABLE marker (value TEXT)')

    with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
        connection.execute('SELECT 1')


def test_storage_paths_file_loads_roots_without_overriding_environment(tmp_path: Path) -> None:
    paths_file = tmp_path / 'storage-paths.conf'
    paths_file.write_text(
        'APP_CONFIG_DIR = /shared/config\nAPP_DATA_DIR = /shared/data\nAPP_ASSETS_DIR = assets\n', encoding='utf-8'
    )
    environment = {'APP_DATA_DIR': '/deployment/data'}

    load_storage_paths(paths_file, environment)

    assert environment == {
        'APP_CONFIG_DIR': '/shared/config',
        'APP_DATA_DIR': '/deployment/data',
        'APP_ASSETS_DIR': 'assets',
    }


def test_registry_keeps_existing_workspace_database_with_external_roots(tmp_path: Path) -> None:
    config_dir = tmp_path / 'external-config'
    data_dir = tmp_path / 'external-data'
    target_database = data_dir / 'workspaces' / 'UK' / 'UK.db'
    registry_path = data_dir / 'workspaces' / 'workspace-registry.db'
    config_dir.mkdir()
    target_database.parent.mkdir(parents=True)
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
            ('default', 'UK', str(target_database), str(data_dir / 'input'), str(data_dir / 'output'),
             str(data_dir / 'output' / 'reports'), str(config_dir / 'slides-templates'), '2026-01-01', '2026-01-01'),
        )

    registry = WorkspaceRegistry(registry_path, data_dir, config_dir / 'slides-templates')
    registry.initialize()

    workspace = registry.get('default')
    assert workspace is not None
    assert workspace.database_path == target_database
    assert target_database.exists()


def test_workspace_accesses_are_consolidated_into_users_table(tmp_path: Path) -> None:
    workspace_db = tmp_path / 'workspace.db'
    application_db = tmp_path / 'application.db'
    with sqlite3.connect(application_db) as conn:
        conn.executescript(
            '''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE user_workspace_access (
                user_id INTEGER NOT NULL,
                workspace_id TEXT NOT NULL,
                PRIMARY KEY (user_id, workspace_id)
            );
            INSERT INTO users (id, username, password_hash, role, active, created_at)
            VALUES (7, 'analyst', 'hash', 'user', 1, '2026-01-01 00:00:00');
            INSERT INTO user_workspace_access (user_id, workspace_id) VALUES (7, 'germany');
            '''
        )

    repository = Repository(workspace_db, application_db)
    repository.initialize()

    assert repository.list_user_workspace_ids(7) == ['germany']
    with sqlite3.connect(application_db) as conn:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(users)')}
        assert 'workspace_ids_json' in columns
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_workspace_access'"
        ).fetchone() is None


def test_initialize_migrates_legacy_user_role_and_seeds_viewer_role(tmp_path: Path) -> None:
    application_db = tmp_path / 'application.db'
    with sqlite3.connect(application_db) as conn:
        conn.executescript(
            '''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            INSERT INTO users (username, password_hash, role, active, created_at)
            VALUES ('legacy-viewer', 'hash', 'user', 1, '2026-01-01');
            '''
        )

    repository = Repository(tmp_path / 'workspace.db', application_db)
    repository.initialize()
    repository.initialize()

    assert repository.get_user('legacy-viewer').role == 'user-viewer'


def test_new_database_seeds_demo_as_user_viewer(tmp_path: Path) -> None:
    application_db = tmp_path / 'application.db'
    repository = Repository(tmp_path / 'workspace.db', application_db)

    repository.initialize()

    assert repository.get_user('demo').role == 'user-viewer'


def test_global_database_replacement_migrates_legacy_user_role(tmp_path: Path) -> None:
    application_db = tmp_path / 'application.db'
    snapshot_db = tmp_path / 'imported-application.db'
    with sqlite3.connect(snapshot_db) as conn:
        conn.executescript(
            '''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            INSERT INTO users (username, password_hash, role, active, created_at)
            VALUES ('imported-viewer', 'hash', 'user', 1, '2026-01-01');
            '''
        )

    repository = Repository(tmp_path / 'workspace.db', application_db)
    repository.replace_global_database_snapshot(snapshot_db)

    assert repository.get_user('imported-viewer').role == 'user-viewer'


def test_global_database_replacement_preserves_local_transfer_offers(tmp_path: Path) -> None:
    application_db = tmp_path / 'application.db'
    snapshot_db = tmp_path / 'imported-application.db'
    offer = {
        'id': 'active-transfer',
        'status': 'importing',
        'secret_hash': 'local-secret',
    }
    with sqlite3.connect(application_db) as conn:
        conn.executescript(
            '''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE transfer_offers (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            '''
        )
        conn.execute(
            'INSERT INTO transfer_offers (id, payload_json, updated_at) VALUES (?, ?, ?)',
            (offer['id'], json.dumps(offer), 1.0),
        )
    with sqlite3.connect(snapshot_db) as conn:
        conn.executescript(
            '''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            INSERT INTO users (username, password_hash, role, active, created_at)
            VALUES ('imported', 'hash', 'admin', 1, '2026-09-21 00:00:00');
            '''
        )

    repository = Repository(tmp_path / 'workspace.db', application_db)
    repository.replace_global_database_snapshot(snapshot_db)

    assert repository.list_transfer_offers() == [offer]
    with sqlite3.connect(application_db) as conn:
        assert conn.execute('SELECT username FROM users').fetchone() == ('imported',)


def test_a_new_workspace_never_takes_the_id_of_a_deleted_one(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(
        tmp_path / 'workspace-registry.db', tmp_path / 'data', tmp_path / 'slides-templates',
    )
    registry.initialize()
    first = registry.create('First')
    second = registry.create('Second')
    registry.delete(second.id, delete_files=True)
    # Otherwise the Workspace page takes the new workspace for the deleted one and removes its row.
    third = registry.create('Third')
    assert third.id not in {first.id, second.id}
    assert int(third.id.removeprefix('workspace-')) == int(second.id.removeprefix('workspace-')) + 1


def test_deleting_a_workspace_never_removes_a_new_one_with_the_same_name(client, monkeypatch) -> None:
    import src.DriveTestAnalyzer as app_module

    client.post('/login', data={'username': 'super', 'password': 'super123'})
    original = app_module.active_workspace
    twin = app_module.workspace_registry.create('Twin')
    app_module.activate_workspace(twin.id)
    app_module.activate_workspace(original.id)
    (twin.input_dir / 'old.csv').write_text('old', encoding='utf-8')
    # A large workspace: its files are removed by a background job, which runs later here.
    pending = []
    monkeypatch.setattr(app_module, 'workspace_disk_usage', lambda _workspace: 10 * 1024 ** 3)
    monkeypatch.setattr(app_module, 'submit_background_task', lambda callback, *args: pending.append((callback, args)))
    deleted = client.post('/workspace/delete', data={'workspace_id': twin.id, 'delete_workspace_files': 'true'},
                          follow_redirects=False)
    assert deleted.status_code == 303
    # The folder left its name at once, so a new workspace can take it.
    assert not twin.database_path.parent.exists()
    created = client.post('/workspace/create', data={'name': 'Twin'}, follow_redirects=False)
    assert created.status_code == 303
    new = next(item for item in app_module.workspace_registry.list() if item.name == 'Twin')
    assert new.id != twin.id and new.database_path == twin.database_path and new.database_path.exists()
    for callback, args in pending:
        callback(*args)
    # The deletion removed the old files only.
    assert new.database_path.exists() and not (new.input_dir / 'old.csv').exists()
    assert not any(app_module.workspace_trash_root().iterdir())
