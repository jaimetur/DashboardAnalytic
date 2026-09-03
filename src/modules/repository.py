from __future__ import annotations

import sqlite3
import shutil
import re
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from src.modules.auth import hash_password


DATABASE_BLANK_FILTER = '__database_blank__'


def local_now_iso() -> str:
    """Return an offset-aware timestamp in the server's local timezone."""
    return datetime.now().astimezone().isoformat(timespec='microseconds')


SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dataset_profiles (
    dataset_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    normalization_version INTEGER NOT NULL DEFAULT 1,
    vendor_mapping_applied INTEGER NOT NULL DEFAULT 0,
    vendor_values_complete INTEGER NOT NULL DEFAULT 0,
    dataset_kind TEXT,
    row_count INTEGER,
    column_count INTEGER,
    default_metric TEXT,
    default_aggregation TEXT,
    available_metrics_json TEXT NOT NULL DEFAULT '[]',
    available_aggregations_json TEXT NOT NULL DEFAULT '[]',
    filter_options_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    kpis_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT,
    processed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL,
    technology TEXT NOT NULL,
    scope TEXT NOT NULL,
    data_dataset_id INTEGER NOT NULL,
    voice_dataset_id INTEGER NOT NULL,
    speech_dataset_id INTEGER NOT NULL,
    mapping_dataset_id INTEGER,
    vodafone_mapping_dataset_id INTEGER,
    three_mapping_dataset_id INTEGER,
    template_name TEXT NOT NULL,
    output_file TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dataset_ids_json TEXT NOT NULL DEFAULT '{}',
    dataset_names_json TEXT NOT NULL DEFAULT '{}',
    slide_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ready',
    progress INTEGER NOT NULL DEFAULT 100,
    last_error TEXT,
    output_path TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS report_chart_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    technology TEXT NOT NULL,
    scope TEXT NOT NULL,
    dataset_ids_json TEXT NOT NULL DEFAULT '{}',
    dataset_names_json TEXT NOT NULL DEFAULT '{}',
    template_name TEXT NOT NULL,
    chart_count INTEGER NOT NULL DEFAULT 0,
    generation TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

"""

GLOBAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    workspace_ids_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS report_templates (
    technology TEXT NOT NULL,
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (technology, name),
    CHECK (technology IN ('nsa', 'sa'))
);

CREATE TABLE IF NOT EXISTS application_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase
ON users(username COLLATE NOCASE);
"""


@dataclass(slots=True)
class UserRecord:
    username: str
    password_hash: str
    role: str
    active: bool


class Repository:
    def __init__(self, db_path: Path, global_db_path: Path | None = None) -> None:
        self.db_path = db_path
        self.global_db_path = global_db_path or db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def global_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.global_db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def set_global_database(self, path: Path) -> None:
        self.global_db_path = path
        self.global_db_path.parent.mkdir(parents=True, exist_ok=True)

    def replace_global_database_snapshot(self, snapshot_path: Path) -> None:
        """Replace the global database and discard stale SQLite sidecars."""
        source = Path(snapshot_path)
        if not source.is_file():
            raise ValueError('The configuration archive does not contain application.db.')
        try:
            with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as conn:
                users_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValueError('The configuration archive contains an invalid application.db.') from exc
        if not users_table:
            raise ValueError('The configuration archive application.db does not contain the users table.')
        destination = self.global_db_path
        temporary = destination.with_name(f'.{destination.name}.importing')
        shutil.copy2(source, temporary)
        for suffix in ('-wal', '-shm'):
            Path(f'{destination}{suffix}').unlink(missing_ok=True)
        temporary.replace(destination)

    def remove_legacy_global_tables(self) -> list[str]:
        """Remove global-only tables left inside an old workspace database.

        Users, template registry data and workspace access are now owned only
        by ``config/application.db``.  Old workspace copies must never be
        available to confuse manual inspection or a future code path.
        """
        if self.db_path.resolve() == self.global_db_path.resolve() or not self.db_path.exists():
            return []
        removed: list[str] = []
        with self.connection() as conn:
            for table_name in ('user_workspace_access', 'report_templates', 'users'):
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
                ).fetchone()
                if exists:
                    conn.execute(f'DROP TABLE {self._quote_identifier(table_name)}')
                    removed.append(table_name)
        return removed

    def initialize(self) -> None:
        self.remove_legacy_global_tables()
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            self._ensure_dataset_profile_columns(conn)
            self._ensure_report_run_columns(conn)
            self._ensure_report_chart_job_columns(conn)
            self._cleanup_duplicate_datasets(conn)
            self._migrate_legacy_vendor_mapping_profiles(conn)
            conn.execute(
                """
                INSERT OR IGNORE INTO dataset_profiles (dataset_id, status, progress, updated_at)
                SELECT id, 'queued', 0, ? FROM datasets
                """,
                (local_now_iso(),),
            )
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            self._ensure_report_template_columns(conn)
            self._ensure_user_workspace_columns(conn)
            # Seed the three local accounts exactly once, for a brand-new
            # empty application database.  Later starts must never recreate
            # deleted or renamed accounts, nor reset roles or passwords.
            bootstrap_done = conn.execute(
                "SELECT 1 FROM application_state WHERE key = 'bootstrap_users_created'"
            ).fetchone()
            has_users = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if not bootstrap_done and not has_users:
                for username, password, role in (
                    ('super', 'super123', 'super-admin'),
                    ('admin', 'admin123', 'admin'),
                    ('demo', 'demo123', 'user'),
                ):
                    conn.execute(
                        "INSERT INTO users (username, password_hash, role, active, created_at) VALUES (?, ?, ?, 1, ?)",
                        (username, hash_password(password), role, local_now_iso()),
                    )
            if not bootstrap_done:
                conn.execute(
                    "INSERT INTO application_state (key, value) VALUES ('bootstrap_users_created', '1')"
                )
            # The three shipped accounts are intended to be usable immediately
            # in the bootstrap workspace.  Add the membership idempotently on
            # every startup so older installations are repaired without
            # recreating deleted users or changing any other access grants.
            for username in ('super', 'admin', 'demo'):
                row = conn.execute(
                    'SELECT id, workspace_ids_json FROM users WHERE username COLLATE NOCASE = ?',
                    (username,),
                ).fetchone()
                if not row:
                    continue
                workspace_ids = self._workspace_ids_from_json(row['workspace_ids_json'])
                if 'default' not in workspace_ids:
                    workspace_ids.append('default')
                    conn.execute(
                        'UPDATE users SET workspace_ids_json = ? WHERE id = ?',
                        (self._workspace_ids_json(workspace_ids), int(row['id'])),
                    )

    @staticmethod
    def _workspace_ids_from_json(value: object) -> list[str]:
        try:
            values = json.loads(str(value or '[]'))
        except (TypeError, ValueError):
            values = []
        if not isinstance(values, list):
            return []
        return sorted({str(item).strip() for item in values if str(item).strip()})

    @classmethod
    def _workspace_ids_json(cls, workspace_ids: list[str]) -> str:
        return json.dumps(sorted({str(item).strip() for item in workspace_ids if str(item).strip()}))

    def _ensure_user_workspace_columns(self, conn: sqlite3.Connection) -> None:
        user_columns = {str(row['name']) for row in conn.execute('PRAGMA table_info(users)').fetchall()}
        if 'workspace_ids_json' not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN workspace_ids_json TEXT NOT NULL DEFAULT '[]'")
        old_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_workspace_access'"
        ).fetchone()
        if not old_table:
            return
        for row in conn.execute(
            'SELECT user_id, workspace_id FROM user_workspace_access ORDER BY user_id, workspace_id'
        ).fetchall():
            current = conn.execute(
                'SELECT workspace_ids_json FROM users WHERE id = ?', (int(row['user_id']),)
            ).fetchone()
            if not current:
                continue
            workspace_ids = self._workspace_ids_from_json(current['workspace_ids_json'])
            workspace_ids.append(str(row['workspace_id']))
            conn.execute(
                'UPDATE users SET workspace_ids_json = ? WHERE id = ?',
                (self._workspace_ids_json(workspace_ids), int(row['user_id'])),
            )
        conn.execute('DROP TABLE user_workspace_access')

    def list_user_workspace_ids(self, user_id: int) -> list[str]:
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            self._ensure_user_workspace_columns(conn)
            row = conn.execute('SELECT workspace_ids_json FROM users WHERE id = ?', (user_id,)).fetchone()
            return self._workspace_ids_from_json(row['workspace_ids_json']) if row else []

    def user_has_workspace_access(self, username: str, workspace_id: str) -> bool:
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            self._ensure_user_workspace_columns(conn)
            row = conn.execute(
                'SELECT workspace_ids_json FROM users WHERE username COLLATE NOCASE = ?',
                (username.strip(),),
            ).fetchone()
        return bool(row) and str(workspace_id) in self._workspace_ids_from_json(row['workspace_ids_json'])

    def set_user_workspace_access(self, user_id: int, workspace_ids: list[str]) -> None:
        unique_ids = sorted({str(item).strip() for item in workspace_ids if str(item).strip()})
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            self._ensure_user_workspace_columns(conn)
            user = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
            if user and str(user['username']).casefold() in {'super', 'admin', 'demo'} and 'default' not in unique_ids:
                unique_ids.append('default')
                unique_ids.sort()
            conn.execute('UPDATE users SET workspace_ids_json = ? WHERE id = ?', (json.dumps(unique_ids), user_id))

    def set_workspace_user_access(self, workspace_id: str, usernames: list[str]) -> None:
        """Replace one workspace's membership using current, case-insensitive usernames."""
        normalized_workspace_id = str(workspace_id).strip()
        selected_usernames = {str(username).strip().casefold() for username in usernames if str(username).strip()}
        if normalized_workspace_id == 'default':
            selected_usernames.update({'super', 'admin', 'demo'})
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            self._ensure_user_workspace_columns(conn)
            for row in conn.execute('SELECT id, username, workspace_ids_json FROM users').fetchall():
                workspace_ids = self._workspace_ids_from_json(row['workspace_ids_json'])
                workspace_ids = [item for item in workspace_ids if item != normalized_workspace_id]
                if str(row['username']).casefold() in selected_usernames:
                    workspace_ids.append(normalized_workspace_id)
                conn.execute(
                    'UPDATE users SET workspace_ids_json = ? WHERE id = ?',
                    (self._workspace_ids_json(workspace_ids), int(row['id'])),
                )

    def grant_all_workspace_access(self, workspace_id: str) -> None:
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            self._ensure_user_workspace_columns(conn)
            for row in conn.execute('SELECT id, workspace_ids_json FROM users').fetchall():
                workspace_ids = self._workspace_ids_from_json(row['workspace_ids_json'])
                workspace_ids.append(str(workspace_id))
                conn.execute('UPDATE users SET workspace_ids_json = ? WHERE id = ?', (self._workspace_ids_json(workspace_ids), int(row['id'])))

    def has_workspace_access_entries(self) -> bool:
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            self._ensure_user_workspace_columns(conn)
            return any(self._workspace_ids_from_json(row['workspace_ids_json']) for row in conn.execute('SELECT workspace_ids_json FROM users'))

    def _ensure_dataset_profile_columns(self, conn: sqlite3.Connection) -> None:
        existing_columns = {row['name'] for row in conn.execute("PRAGMA table_info(dataset_profiles)").fetchall()}
        if 'normalization_version' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN normalization_version INTEGER NOT NULL DEFAULT 1")
        if 'vendor_mapping_applied' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN vendor_mapping_applied INTEGER NOT NULL DEFAULT 0")
        if 'vendor_values_complete' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN vendor_values_complete INTEGER NOT NULL DEFAULT 0")

    def _migrate_legacy_vendor_mapping_profiles(self, conn: sqlite3.Connection) -> None:
        """Mark pre-profile mappings once, without reopening source CDR files."""
        candidates = conn.execute(
            """
            SELECT p.dataset_id
            FROM dataset_profiles p
            WHERE p.status = 'ready'
              AND p.dataset_kind IN ('data', 'voice', 'speech')
              AND COALESCE(p.vendor_mapping_applied, 0) = 0
            """
        ).fetchall()
        for candidate in candidates:
            dataset_id = int(candidate['dataset_id'])
            table_name = self.dataset_rows_table_name(dataset_id)
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            if not exists:
                continue
            columns = [row['name'] for row in conn.execute(f"PRAGMA table_info({self._quote_identifier(table_name)})").fetchall()]
            vendor_column = next((column for column in columns if column == 'vendor'), None)
            if not vendor_column:
                continue
            quoted_table = self._quote_identifier(table_name)
            quoted_vendor = self._quote_identifier(vendor_column)
            mapped = conn.execute(
                f"""
                SELECT 1 FROM {quoted_table}
                WHERE LOWER(TRIM(CAST({quoted_vendor} AS TEXT))) LIKE 'vodafone_%'
                   OR LOWER(TRIM(CAST({quoted_vendor} AS TEXT))) LIKE '3_%'
                LIMIT 1
                """
            ).fetchone()
            if mapped:
                conn.execute(
                    "UPDATE dataset_profiles SET vendor_mapping_applied = 1 WHERE dataset_id = ?",
                    (dataset_id,),
                )

    def _ensure_report_run_columns(self, conn: sqlite3.Connection) -> None:
        existing_columns = {row['name'] for row in conn.execute("PRAGMA table_info(report_runs)").fetchall()}
        if 'vodafone_mapping_dataset_id' not in existing_columns:
            conn.execute("ALTER TABLE report_runs ADD COLUMN vodafone_mapping_dataset_id INTEGER")
        if 'three_mapping_dataset_id' not in existing_columns:
            conn.execute("ALTER TABLE report_runs ADD COLUMN three_mapping_dataset_id INTEGER")
        migrations = {
            'dataset_ids_json': "TEXT NOT NULL DEFAULT '{}'",
            'dataset_names_json': "TEXT NOT NULL DEFAULT '{}'",
            'slide_count': 'INTEGER NOT NULL DEFAULT 0',
            'status': "TEXT NOT NULL DEFAULT 'ready'",
            'progress': 'INTEGER NOT NULL DEFAULT 100',
            'last_error': 'TEXT',
            'output_path': 'TEXT',
            'updated_at': 'TEXT',
            'finished_at': 'TEXT',
        }
        for column, definition in migrations.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE report_runs ADD COLUMN {column} {definition}")
        conn.execute("UPDATE report_runs SET updated_at = COALESCE(updated_at, created_at)")

    def _ensure_report_chart_job_columns(self, conn: sqlite3.Connection) -> None:
        """Keep independently persisted Report Charts jobs complete."""
        columns = {row['name'] for row in conn.execute("PRAGMA table_info(report_chart_jobs)").fetchall()}
        migrations = {
            'dataset_ids_json': "TEXT NOT NULL DEFAULT '{}'",
            'dataset_names_json': "TEXT NOT NULL DEFAULT '{}'",
            'template_name': "TEXT NOT NULL DEFAULT ''",
            'chart_count': 'INTEGER NOT NULL DEFAULT 0',
            'generation': 'TEXT',
            'created_by': "TEXT NOT NULL DEFAULT ''",
            'created_at': 'TEXT',
            'status': "TEXT NOT NULL DEFAULT 'queued'",
            'progress': 'INTEGER NOT NULL DEFAULT 0',
            'last_error': 'TEXT',
            'updated_at': 'TEXT',
            'finished_at': 'TEXT',
        }
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE report_chart_jobs ADD COLUMN {column} {definition}")
        conn.execute("UPDATE report_chart_jobs SET updated_at = COALESCE(updated_at, created_at)")

    def _ensure_report_template_columns(self, conn: sqlite3.Connection) -> None:
        """Keep template metadata complete and one promoted template per technology."""
        columns = {row['name'] for row in conn.execute("PRAGMA table_info(report_templates)").fetchall()}
        if 'created_at' not in columns:
            conn.execute("ALTER TABLE report_templates ADD COLUMN created_at TEXT")
        if 'updated_at' not in columns:
            conn.execute("ALTER TABLE report_templates ADD COLUMN updated_at TEXT")
        now = local_now_iso()
        conn.execute("UPDATE report_templates SET created_at = COALESCE(created_at, ?)", (now,))
        conn.execute("UPDATE report_templates SET updated_at = COALESCE(updated_at, created_at, ?)", (now,))
        for technology in ('nsa', 'sa'):
            defaults = conn.execute(
                "SELECT name FROM report_templates WHERE technology = ? AND is_default = 1 ORDER BY name",
                (technology,),
            ).fetchall()
            for row in defaults[1:]:
                conn.execute(
                    "UPDATE report_templates SET is_default = 0 WHERE technology = ? AND name = ?",
                    (technology, row['name']),
                )

    def list_report_templates(self, technology: str) -> list[sqlite3.Row]:
        with self.global_connection() as conn:
            return conn.execute(
                "SELECT technology, name, is_default, created_at, updated_at FROM report_templates WHERE technology = ? ORDER BY name COLLATE NOCASE",
                (technology,),
            ).fetchall()

    def add_report_template(self, technology: str, name: str, *, is_default: bool = False) -> None:
        with self.global_connection() as conn:
            if is_default:
                conn.execute("UPDATE report_templates SET is_default = 0 WHERE technology = ?", (technology,))
            now = local_now_iso()
            conn.execute(
                "INSERT INTO report_templates (technology, name, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (technology, name, int(is_default), now, now),
            )

    def set_default_report_template(self, technology: str, name: str) -> None:
        with self.global_connection() as conn:
            template = conn.execute(
                "SELECT is_default FROM report_templates WHERE technology = ? AND name = ?", (technology, name)
            ).fetchone()
            if not template:
                raise ValueError('Slides Template was not found.')
            defaults = conn.execute(
                "SELECT name FROM report_templates WHERE technology = ? AND is_default = 1", (technology,)
            ).fetchall()
            if bool(template['is_default']) and len(defaults) == 1:
                return
            now = local_now_iso()
            conn.execute("UPDATE report_templates SET is_default = 0, updated_at = ? WHERE technology = ?", (now, technology))
            conn.execute(
                "UPDATE report_templates SET is_default = 1, updated_at = ? WHERE technology = ? AND name = ?", (now, technology, name)
            )

    def rename_report_template(self, technology: str, name: str, new_name: str) -> None:
        with self.global_connection() as conn:
            conn.execute(
                "UPDATE report_templates SET name = ?, updated_at = ? WHERE technology = ? AND name = ?",
                (new_name, local_now_iso(), technology, name),
            )

    def move_report_template(self, technology: str, name: str, target_technology: str) -> None:
        with self.global_connection() as conn:
            conn.execute(
                "UPDATE report_templates SET technology = ?, updated_at = ? WHERE technology = ? AND name = ?",
                (target_technology, local_now_iso(), technology, name),
            )

    def touch_report_template(self, technology: str, name: str) -> None:
        with self.global_connection() as conn:
            conn.execute(
                "UPDATE report_templates SET updated_at = ? WHERE technology = ? AND name = ?",
                (local_now_iso(), technology, name),
            )

    def delete_report_template(self, technology: str, name: str) -> None:
        with self.global_connection() as conn:
            conn.execute("DELETE FROM report_templates WHERE technology = ? AND name = ?", (technology, name))

    def dataset_rows_table_name(self, dataset_id: int) -> str:
        return f'dataset_rows_{int(dataset_id)}'

    def _quote_identifier(self, identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    def _table_connection(self, table_name: str):
        """Select the owning database for workspace and global tables."""
        return self.global_connection if table_name in {'users', 'report_templates'} else self.connection

    def list_database_tables(self) -> list[str]:
        """Return the editable user tables in the currently configured workspace database."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
        names = [str(row['name']) for row in rows]
        # Users and Slides Template metadata are global configuration tables;
        # expose their names in the admin editor without duplicating them in
        # the workspace database.
        with self.global_connection() as global_conn:
            for name in ('users', 'report_templates'):
                if global_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)).fetchone() and name not in names:
                    names.append(name)
        return sorted(names, key=str.casefold)

    def remove_orphaned_dataset_row_tables(self) -> list[str]:
        """Remove legacy materialised tables whose dataset record no longer exists."""
        with self.connection() as conn:
            dataset_ids = {int(row['id']) for row in conn.execute('SELECT id FROM datasets').fetchall()}
            table_names = [
                str(row['name'])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'dataset_rows_%'"
                ).fetchall()
            ]
            orphaned = [
                table_name for table_name in table_names
                if table_name.removeprefix('dataset_rows_').isdigit()
                and int(table_name.removeprefix('dataset_rows_')) not in dataset_ids
            ]
            for table_name in orphaned:
                conn.execute(f'DROP TABLE {self._quote_identifier(table_name)}')
        return orphaned

    def remove_orphaned_reporting_rows(self) -> int:
        """Remove combined CDR rows whose source dataset is no longer registered."""
        deleted_rows = 0
        with self.connection() as conn:
            for dataset_kind in ('data', 'voice', 'speech'):
                table_name = self.reporting_rows_table_name(dataset_kind)
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
                ).fetchone()
                if not exists:
                    continue
                result = conn.execute(
                    f"DELETE FROM {self._quote_identifier(table_name)} "
                    "WHERE dataset_id IS NULL OR dataset_id NOT IN (SELECT id FROM datasets)"
                )
                deleted_rows += max(0, int(result.rowcount))
        return deleted_rows

    def _database_table_metadata(self, conn: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
        return conn.execute(f"PRAGMA table_info({self._quote_identifier(table_name)})").fetchall()

    def _database_filter_clause(
        self,
        metadata: list[sqlite3.Row],
        filters: dict[str, list[str]] | None,
    ) -> tuple[str, list[str]]:
        known_columns = {str(row['name']) for row in metadata}
        clauses: list[str] = []
        parameters: list[str] = []
        for column, raw_values in (filters or {}).items():
            if column not in known_columns:
                raise ValueError('The filter contains an unknown column.')
            if not isinstance(raw_values, list):
                raise ValueError('Each database filter must contain a list of values.')
            values = list(dict.fromkeys(str(value) for value in raw_values))
            if not values:
                continue
            quoted_column = self._quote_identifier(column)
            has_blank = DATABASE_BLANK_FILTER in values
            concrete_values = [value for value in values if value != DATABASE_BLANK_FILTER]
            alternatives: list[str] = []
            if concrete_values:
                alternatives.append(f"CAST({quoted_column} AS TEXT) IN ({', '.join('?' for _ in concrete_values)})")
                parameters.extend(concrete_values)
            if has_blank:
                alternatives.append(f"({quoted_column} IS NULL OR TRIM(CAST({quoted_column} AS TEXT)) = '')")
            clauses.append(f"({' OR '.join(alternatives)})")
        return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', parameters

    def database_table_page(
        self,
        table_name: str,
        *,
        limit: int = 100,
        offset: int = 0,
        filters: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Return one bounded page of a workspace table, addressed by SQLite rowid."""
        if table_name not in self.list_database_tables():
            raise ValueError('The selected table does not exist in the active workspace database.')
        page_size = max(1, min(int(limit), 250))
        page_offset = max(0, int(offset))
        quoted_table = self._quote_identifier(table_name)
        with self._table_connection(table_name)() as conn:
            column_rows = self._database_table_metadata(conn, table_name)
            where_clause, parameters = self._database_filter_clause(column_rows, filters)
            columns = [
                {
                    'name': str(row['name']),
                    'type': str(row['type'] or ''),
                    'primary_key': bool(row['pk']),
                    'not_null': bool(row['notnull']),
                }
                for row in column_rows
            ]
            rows = [
                dict(row)
                for row in conn.execute(
                    f"SELECT rowid AS __database_rowid__, * FROM {quoted_table}{where_clause} ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (*parameters, page_size, page_offset),
                ).fetchall()
            ]
            total_rows = int(conn.execute(f"SELECT COUNT(*) AS total FROM {quoted_table}{where_clause}", parameters).fetchone()['total'])
            all_rows = total_rows if not where_clause else int(
                conn.execute(f"SELECT COUNT(*) AS total FROM {quoted_table}").fetchone()['total']
            )
        return {
            'columns': columns,
            'rows': rows,
            'total_rows': total_rows,
            'all_rows': all_rows,
            'limit': page_size,
            'offset': page_offset,
        }

    def database_table_distinct_values(
        self,
        table_name: str,
        column_name: str,
        *,
        filters: dict[str, list[str]] | None = None,
        search: str = '',
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return globally distinct values for an Excel-like server-side filter."""
        if table_name not in self.list_database_tables():
            raise ValueError('The selected table does not exist in the active workspace database.')
        quoted_table = self._quote_identifier(table_name)
        result_limit = max(1, min(int(limit), 500))
        with self._table_connection(table_name)() as conn:
            metadata = self._database_table_metadata(conn, table_name)
            if column_name not in {str(row['name']) for row in metadata}:
                raise ValueError('The selected filter column does not exist in the active workspace database.')
            where_clause, parameters = self._database_filter_clause(metadata, filters)
            quoted_column = self._quote_identifier(column_name)
            normalized_search = str(search or '').strip()
            if normalized_search:
                search_clause = f"LOWER(CAST({quoted_column} AS TEXT)) LIKE LOWER(?)"
                where_clause = f"{where_clause} AND {search_clause}" if where_clause else f" WHERE {search_clause}"
                parameters.append(f'%{normalized_search}%')
            rows = conn.execute(
                f"SELECT {quoted_column} AS value FROM {quoted_table}{where_clause} GROUP BY {quoted_column} ORDER BY CAST({quoted_column} AS TEXT) COLLATE NOCASE LIMIT ?",
                (*parameters, result_limit + 1),
            ).fetchall()
        has_more = len(rows) > result_limit
        values = [DATABASE_BLANK_FILTER if row['value'] is None or str(row['value']).strip() == '' else str(row['value']) for row in rows[:result_limit]]
        return {'values': values, 'has_more': has_more}

    def update_database_table_row(self, table_name: str, rowid: int, updates: dict[str, Any]) -> None:
        """Persist safe, non-key cell edits made by an administrator."""
        if table_name not in self.list_database_tables():
            raise ValueError('The selected table does not exist in the active workspace database.')
        if not isinstance(updates, dict) or not updates:
            raise ValueError('Enter at least one changed value before saving.')
        quoted_table = self._quote_identifier(table_name)
        with self._table_connection(table_name)() as conn:
            metadata = conn.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            columns = {str(row['name']): row for row in metadata}
            unknown_columns = set(updates) - set(columns)
            if unknown_columns:
                raise ValueError('The update contains an unknown column.')
            protected_columns = {str(row['name']) for row in metadata if row['pk']}
            if protected_columns.intersection(updates):
                raise ValueError('Primary-key values cannot be edited in Database Management.')
            assignments = ', '.join(f"{self._quote_identifier(column)} = ?" for column in updates)
            values = [updates[column] for column in updates]
            result = conn.execute(
                f"UPDATE {quoted_table} SET {assignments} WHERE rowid = ?",
                (*values, int(rowid)),
            )
            if result.rowcount != 1:
                raise ValueError('The row no longer exists. Refresh the table and try again.')

    def delete_database_table_row(self, table_name: str, rowid: int) -> None:
        """Delete one row selected in Database Management by its SQLite rowid."""
        if table_name not in self.list_database_tables():
            raise ValueError('The selected table does not exist in the active workspace database.')
        quoted_table = self._quote_identifier(table_name)
        with self._table_connection(table_name)() as conn:
            result = conn.execute(f"DELETE FROM {quoted_table} WHERE rowid = ?", (int(rowid),))
            if result.rowcount != 1:
                raise ValueError('The row no longer exists. Refresh the table and try again.')

    def _index_name(self, table_name: str, column_name: str, suffix: str) -> str:
        return f'idx_{table_name}_{column_name}_{suffix}'

    def _sqlite_safe_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        renamed_columns: list[str] = []
        seen: dict[str, int] = {}
        for column in df.columns:
            base = str(column).strip() or 'column'
            normalized = base.lower()
            occurrence = seen.get(normalized, 0)
            if occurrence == 0:
                renamed_columns.append(base)
            else:
                renamed_columns.append(f'{base}__{occurrence + 1}')
            seen[normalized] = occurrence + 1
        if renamed_columns == list(df.columns):
            return df
        safe_df = df.copy()
        safe_df.columns = renamed_columns
        return safe_df

    def _cleanup_duplicate_datasets(self, conn: sqlite3.Connection) -> None:
        duplicate_groups = conn.execute(
            """
            SELECT stored_path
            FROM datasets
            GROUP BY stored_path
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for group in duplicate_groups:
            stored_path = group['stored_path']
            ids = [
                row['id'] for row in conn.execute(
                    "SELECT id FROM datasets WHERE stored_path = ? ORDER BY uploaded_at DESC, id DESC",
                    (stored_path,),
                ).fetchall()
            ]
            keep_id = ids[0]
            stale_ids = ids[1:]
            if stale_ids:
                placeholders = ','.join('?' for _ in stale_ids)
                conn.execute(f"DELETE FROM dataset_profiles WHERE dataset_id IN ({placeholders})", stale_ids)
                conn.execute(f"DELETE FROM datasets WHERE id IN ({placeholders})", stale_ids)

    def get_user(self, username: str) -> UserRecord | None:
        with self.global_connection() as conn:
            row = conn.execute(
                "SELECT username, password_hash, role, active FROM users WHERE username COLLATE NOCASE = ?",
                (username.strip(),),
            ).fetchone()
        if not row:
            return None
        return UserRecord(row['username'], row['password_hash'], row['role'], bool(row['active']))

    def get_user_by_id(self, user_id: int) -> sqlite3.Row | None:
        with self.global_connection() as conn:
            return conn.execute(
                "SELECT id, username, role, active, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

    def create_user(self, username: str, password: str, role: str) -> None:
        normalized_username = username.strip()
        with self.global_connection() as conn:
            duplicate = conn.execute(
                "SELECT id FROM users WHERE username COLLATE NOCASE = ?",
                (normalized_username,),
            ).fetchone()
            if duplicate:
                raise ValueError('A user with that username already exists.')
            conn.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (normalized_username, hash_password(password), role, local_now_iso()),
            )

    def update_user(self, user_id: int, username: str, role: str, active: bool, password: str | None = None) -> None:
        normalized_username = username.strip()
        with self.global_connection() as conn:
            existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if not existing:
                raise ValueError("User not found")
            duplicate = conn.execute(
                "SELECT id FROM users WHERE username COLLATE NOCASE = ?",
                (normalized_username,),
            ).fetchone()
            if duplicate and int(duplicate['id']) != int(user_id):
                raise ValueError('A user with that username already exists.')
            if password:
                conn.execute(
                    "UPDATE users SET username = ?, password_hash = ?, role = ?, active = ? WHERE id = ?",
                    (normalized_username, hash_password(password), role, int(active), user_id),
                )
            else:
                conn.execute(
                    "UPDATE users SET username = ?, role = ?, active = ? WHERE id = ?",
                    (normalized_username, role, int(active), user_id),
                )

    def update_password(self, username: str, password: str) -> None:
        with self.global_connection() as conn:
            result = conn.execute(
                "UPDATE users SET password_hash = ? WHERE username COLLATE NOCASE = ?",
                (hash_password(password), username.strip()),
            )
            if result.rowcount != 1:
                raise ValueError('User not found')

    def delete_user(self, user_id: int) -> None:
        with self.global_connection() as conn:
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if cursor.rowcount == 0:
                raise ValueError("User not found")

    def list_users(self) -> list[sqlite3.Row]:
        with self.global_connection() as conn:
            return list(conn.execute("SELECT id, username, role, active, created_at FROM users ORDER BY id ASC").fetchall())

    def count_active_admin_users(self) -> int:
        with self.global_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role IN ('admin', 'super-admin') AND active = 1",
            ).fetchone()
        return int(row['total']) if row else 0

    def count_super_admin_users(self, *, active_only: bool = False) -> int:
        query = "SELECT COUNT(*) AS total FROM users WHERE role = 'super-admin'"
        if active_only:
            query += ' AND active = 1'
        with self.global_connection() as conn:
            row = conn.execute(query).fetchone()
        return int(row['total']) if row else 0

    def remove_workspace_access(self, workspace_id: str) -> None:
        with self.global_connection() as conn:
            self._ensure_user_workspace_columns(conn)
            for row in conn.execute('SELECT id, workspace_ids_json FROM users').fetchall():
                workspace_ids = [
                    item for item in self._workspace_ids_from_json(row['workspace_ids_json'])
                    if item != str(workspace_id)
                ]
                conn.execute(
                    'UPDATE users SET workspace_ids_json = ? WHERE id = ?',
                    (self._workspace_ids_json(workspace_ids), int(row['id'])),
                )

    def list_active_users_by_usernames(self, usernames: list[str]) -> list[str]:
        normalized = [username.strip() for username in usernames if username and username.strip()]
        if not normalized:
            return []
        placeholders = ','.join('?' for _ in normalized)
        with self.global_connection() as conn:
            rows = conn.execute(
                f"SELECT username FROM users WHERE active = 1 AND username COLLATE NOCASE IN ({placeholders})",
                normalized,
            ).fetchall()
        existing = {str(row['username']).casefold() for row in rows}
        return [username for username in normalized if username.casefold() in existing]

    def add_dataset(self, file_name: str, stored_path: str, uploaded_by: str) -> tuple[int, bool]:
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM datasets WHERE stored_path = ? ORDER BY uploaded_at DESC, id DESC LIMIT 1",
                (stored_path,),
            ).fetchone()
            if existing:
                dataset_id = int(existing['id'])
                conn.execute(
                    """
                    UPDATE datasets
                    SET file_name = ?
                    WHERE id = ?
                    """,
                    (file_name, dataset_id),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dataset_profiles (dataset_id, status, progress, updated_at) VALUES (?, 'queued', 0, ?)
                    """,
                    (dataset_id, local_now_iso()),
                )
                return dataset_id, False
            cursor = conn.execute(
                "INSERT INTO datasets (file_name, stored_path, uploaded_by, uploaded_at) VALUES (?, ?, ?, ?)",
                (file_name, stored_path, uploaded_by, local_now_iso()),
            )
            dataset_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO dataset_profiles (dataset_id, status, progress, updated_at) VALUES (?, 'queued', 0, ?)",
                (dataset_id, local_now_iso()),
            )
            return dataset_id, True

    def rename_dataset_file(self, dataset_id: int, file_name: str, stored_path: str) -> sqlite3.Row:
        """Update a dataset's source metadata and all materialised source-file labels."""
        with self.connection() as conn:
            dataset = conn.execute(
                "SELECT id, file_name, stored_path FROM datasets WHERE id = ?", (dataset_id,)
            ).fetchone()
            if not dataset:
                raise ValueError('Dataset not found.')
            duplicate = conn.execute(
                "SELECT id FROM datasets WHERE stored_path = ? AND id != ?", (stored_path, dataset_id)
            ).fetchone()
            if duplicate:
                raise ValueError('Another dataset already uses that file path.')

            conn.execute(
                "UPDATE datasets SET file_name = ?, stored_path = ? WHERE id = ?",
                (file_name, stored_path, dataset_id),
            )

            def update_source_file(table_name: str, *, scoped_to_dataset: bool) -> None:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
                ).fetchone()
                if not exists:
                    return
                columns = self._table_columns(conn, table_name)
                source_column = next((column for column in columns if column.casefold() == 'source_file'), None)
                if not source_column:
                    return
                where_clause = ' WHERE dataset_id = ?' if scoped_to_dataset else ''
                parameters: tuple[Any, ...] = (file_name, dataset_id) if scoped_to_dataset else (file_name,)
                conn.execute(
                    f"UPDATE {self._quote_identifier(table_name)} "
                    f"SET {self._quote_identifier(source_column)} = ?{where_clause}",
                    parameters,
                )

            update_source_file(self.dataset_rows_table_name(dataset_id), scoped_to_dataset=False)
            for dataset_kind in ('data', 'voice', 'speech'):
                update_source_file(self.reporting_rows_table_name(dataset_kind), scoped_to_dataset=True)
            return dataset

    def replace_dataset_rows(self, dataset_id: int, df: pd.DataFrame) -> None:
        table_name = self.dataset_rows_table_name(dataset_id)
        safe_df = self._sqlite_safe_frame(df)
        with self.connection() as conn:
            conn.execute(f"DROP TABLE IF EXISTS {self._quote_identifier(table_name)}")
            safe_df.to_sql(table_name, conn, index=False)
            self._create_dataset_row_indexes(conn, table_name, safe_df.columns.tolist())

    def reporting_rows_table_name(self, dataset_kind: str) -> str:
        if dataset_kind not in {'data', 'voice', 'speech'}:
            raise ValueError('A reporting table is only available for CDR Data, Voice or Speech.')
        return f'reporting_rows_{dataset_kind}'

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> list[str]:
        return [row['name'] for row in conn.execute(f"PRAGMA table_info({self._quote_identifier(table_name)})").fetchall()]

    @staticmethod
    def _column_identity(column: str) -> str:
        """Match CDR headings regardless of case or harmless separators.

        NetCheck exports use both forms such as ``G_Level_4`` and
        ``G Level 4``.  Reporting templates use the readable form, while the
        shared reporting table must retain the physical source name.
        """
        return re.sub(r'[^a-z0-9]+', '', str(column).casefold())

    REPORTING_CORE_COLUMNS = (
        'Campaign', 'Operator', 'vendor', 'report_vendor', 'RAT', 'RAT_A', 'Sample_RAT_A',
        'technology_primary', 'L1_Call_Mode_A', 'L2_Call_Mode_A', 'Session_Type',
        'session_type', 'Type_of_Test', 'Test_Name', 'test_name', 'Test_Type', 'test_type',
    )

    def _ensure_reporting_table(self, conn: sqlite3.Connection, dataset_kind: str) -> tuple[str, list[str]]:
        table_name = self.reporting_rows_table_name(dataset_kind)
        quoted_table = self._quote_identifier(table_name)
        conn.execute(f"CREATE TABLE IF NOT EXISTS {quoted_table} (dataset_id INTEGER NOT NULL, source_row_id INTEGER NOT NULL)")
        columns = self._table_columns(conn, table_name)
        # Discard the short-lived first implementation, which copied every raw
        # column and did not have a stable source-row key for incremental fills.
        if 'source_row_id' not in columns:
            conn.execute(f"DROP TABLE {quoted_table}")
            conn.execute(f"CREATE TABLE {quoted_table} (dataset_id INTEGER NOT NULL, source_row_id INTEGER NOT NULL)")
            columns = self._table_columns(conn, table_name)
        return table_name, columns

    def _ensure_reporting_columns(
        self, conn: sqlite3.Connection, table_name: str, source_columns: list[str], requested_columns: list[str]
    ) -> list[str]:
        target_columns = self._table_columns(conn, table_name)
        target_lookup = {self._column_identity(column): column for column in target_columns}
        source_lookup = {self._column_identity(column): column for column in source_columns}
        for requested in requested_columns:
            source = source_lookup.get(self._column_identity(requested))
            source_key = self._column_identity(source) if source else ''
            if not source or source_key in {'datasetid', 'sourcerowid'} or source_key in target_lookup:
                continue
            conn.execute(f"ALTER TABLE {self._quote_identifier(table_name)} ADD COLUMN {self._quote_identifier(source)}")
            target_columns.append(source)
            target_lookup[source_key] = source
        return target_columns

    def replace_reporting_rows(self, dataset_id: int, dataset_kind: str, df: pd.DataFrame) -> None:
        """Replace one CDR's rows in the shared, queryable reporting table.

        Only core reporting fields are stored at ingestion. Template-specific
        columns are materialised on demand from the individual CDR table.
        """
        table_name = self.reporting_rows_table_name(dataset_kind)
        safe_df = self._sqlite_safe_frame(df)
        with self.connection() as conn:
            table_name, existing = self._ensure_reporting_table(conn, dataset_kind)
            quoted_table = self._quote_identifier(table_name)
            existing = self._ensure_reporting_columns(conn, table_name, safe_df.columns.tolist(), list(self.REPORTING_CORE_COLUMNS))
            source_lookup = {self._column_identity(str(column)): str(column) for column in safe_df.columns}
            conn.execute(f"DELETE FROM {quoted_table} WHERE dataset_id = ?", (dataset_id,))
            payload_columns: dict[str, Any] = {'dataset_id': int(dataset_id), 'source_row_id': range(1, len(safe_df) + 1)}
            for target in existing:
                if target in {'dataset_id', 'source_row_id'}:
                    continue
                source = source_lookup.get(self._column_identity(target))
                payload_columns[target] = safe_df[source] if source else None
            payload = pd.DataFrame(payload_columns, index=safe_df.index)
            payload.to_sql(table_name, conn, if_exists='append', index=False)
            self._create_reporting_row_indexes(conn, table_name, existing)

    def _create_reporting_row_indexes(self, conn: sqlite3.Connection, table_name: str, columns: list[str]) -> None:
        quoted_table = self._quote_identifier(table_name)
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self._quote_identifier(self._index_name(table_name, 'dataset_id', 'rows'))} "
            f"ON {quoted_table} (dataset_id)"
        )
        self._create_dataset_row_indexes(conn, table_name, columns)

    def drop_reporting_rows(self, dataset_id: int, dataset_kind: str | None = None) -> None:
        kinds = [dataset_kind] if dataset_kind in {'data', 'voice', 'speech'} else ['data', 'voice', 'speech']
        with self.connection() as conn:
            for kind in kinds:
                table_name = self.reporting_rows_table_name(kind)
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
                ).fetchone()
                if exists:
                    conn.execute(f"DELETE FROM {self._quote_identifier(table_name)} WHERE dataset_id = ?", (dataset_id,))

    def list_reporting_row_columns(self, dataset_kind: str) -> list[str]:
        table_name = self.reporting_rows_table_name(dataset_kind)
        with self.connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
            ).fetchone()
            return self._table_columns(conn, table_name) if exists else []

    def reporting_rows_exist_for_dataset(self, dataset_id: int, dataset_kind: str) -> bool:
        table_name = self.reporting_rows_table_name(dataset_kind)
        with self.connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
            ).fetchone()
            if not exists:
                return False
            return conn.execute(
                f"SELECT 1 FROM {self._quote_identifier(table_name)} WHERE dataset_id = ? LIMIT 1", (dataset_id,)
            ).fetchone() is not None

    def copy_dataset_rows_to_reporting(self, dataset_id: int, dataset_kind: str, columns: list[str] | None = None) -> None:
        """Backfill a shared table entirely inside SQLite, without pandas RAM use."""
        source_table = self.dataset_rows_table_name(dataset_id)
        target_table = self.reporting_rows_table_name(dataset_kind)
        with self.connection() as conn:
            source_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (source_table,)
            ).fetchone()
            if not source_exists:
                return
            target_table, target_columns = self._ensure_reporting_table(conn, dataset_kind)
            quoted_target = self._quote_identifier(target_table)
            source_columns = self._table_columns(conn, source_table)
            desired = list(dict.fromkeys([*self.REPORTING_CORE_COLUMNS, *(columns or [])]))
            previous_columns = {self._column_identity(column) for column in target_columns}
            source_lookup = {self._column_identity(column): column for column in source_columns}
            needs_new_columns = any(
                self._column_identity(requested) in source_lookup
                and self._column_identity(requested) not in previous_columns
                for requested in desired
            )
            target_columns = self._ensure_reporting_columns(conn, target_table, source_columns, desired)
            existing_rows = conn.execute(
                f"SELECT 1 FROM {quoted_target} WHERE dataset_id = ? LIMIT 1", (dataset_id,)
            ).fetchone()
            # CDR derived dimensions can be materialised after an earlier
            # reporting-table copy.  Refresh only when a populated derived
            # source value is missing from its cached counterpart; otherwise
            # preserve the fast path for repeated large-report generation.
            derived_columns = {'callfamily', 'testfamily'}
            target_lookup = {self._column_identity(column): column for column in target_columns}
            needs_derived_refresh = False
            if existing_rows and not needs_new_columns:
                for requested in desired:
                    identity = self._column_identity(requested)
                    if identity not in derived_columns or identity not in source_lookup or identity not in target_lookup:
                        continue
                    source = source_lookup[identity]
                    target = target_lookup[identity]
                    stale = conn.execute(
                        f"SELECT 1 FROM {quoted_target} AS target "
                        f"JOIN {self._quote_identifier(source_table)} AS source ON source.rowid = target.source_row_id "
                        f"WHERE target.dataset_id = ? "
                        f"AND source.{self._quote_identifier(source)} IS NOT NULL "
                        f"AND target.{self._quote_identifier(target)} IS NULL LIMIT 1",
                        (dataset_id,),
                    ).fetchone()
                    if stale:
                        needs_derived_refresh = True
                        break
            if existing_rows and not needs_new_columns and not needs_derived_refresh:
                return
            conn.execute(f"DELETE FROM {quoted_target} WHERE dataset_id = ?", (dataset_id,))
            insert_columns = ['dataset_id', 'source_row_id', *(column for column in target_columns if column not in {'dataset_id', 'source_row_id'})]
            select_columns = ['?', 'rowid']
            for target in insert_columns[1:]:
                if target == 'source_row_id':
                    continue
                source = source_lookup.get(self._column_identity(target))
                select_columns.append(self._quote_identifier(source) if source else 'NULL')
            conn.execute(
                f"INSERT INTO {quoted_target} ({', '.join(self._quote_identifier(column) for column in insert_columns)}) "
                f"SELECT {', '.join(select_columns)} FROM {self._quote_identifier(source_table)}",
                (dataset_id,),
            )
            self._create_reporting_row_indexes(conn, target_table, target_columns)

    def load_reporting_rows(self, dataset_kind: str, dataset_ids: list[int], columns: list[str]) -> pd.DataFrame:
        if not dataset_ids:
            return pd.DataFrame()
        table_name = self.reporting_rows_table_name(dataset_kind)
        existing_columns = set(self.list_reporting_row_columns(dataset_kind))
        selected_columns: list[tuple[str, str]] = []
        for column in columns:
            resolved = self._resolve_dataset_row_column_name(existing_columns, column)
            if resolved:
                selected_columns.append((column, resolved))
        if not selected_columns:
            return pd.DataFrame()
        placeholders = ', '.join('?' for _ in dataset_ids)
        select_clause = ', '.join(
            f"{self._quote_identifier(actual)} AS {self._quote_identifier(requested)}"
            if actual != requested else self._quote_identifier(actual)
            for requested, actual in selected_columns
        )
        query = f"SELECT {select_clause} FROM {self._quote_identifier(table_name)} WHERE dataset_id IN ({placeholders})"
        with self.connection() as conn:
            return pd.read_sql_query(query, conn, params=[int(dataset_id) for dataset_id in dataset_ids])

    def _create_dataset_row_indexes(self, conn: sqlite3.Connection, table_name: str, columns: list[str]) -> None:
        normalized_columns = {str(column).strip().lower(): column for column in columns}
        indexed_dimensions = [
            'market', 'period', 'operator', 'vendor', 'test_name', 'region', 'city',
            'session_type', 'direction', 'technology_primary', 'source_sheet', 'status',
        ]
        for requested_name in indexed_dimensions:
            actual_name = normalized_columns.get(requested_name)
            if not actual_name:
                continue
            quoted_table = self._quote_identifier(table_name)
            quoted_column = self._quote_identifier(actual_name)
            quoted_index = self._quote_identifier(self._index_name(table_name, requested_name, 'norm'))
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {quoted_index}
                ON {quoted_table} (LOWER(TRIM(CAST({quoted_column} AS TEXT))))
                """
            )

        event_time_column = normalized_columns.get('event_start_time')
        if event_time_column:
            quoted_table = self._quote_identifier(table_name)
            quoted_column = self._quote_identifier(event_time_column)
            quoted_index = self._quote_identifier(self._index_name(table_name, 'event_start_time', 'date'))
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {quoted_index}
                ON {quoted_table} (date(CAST({quoted_column} AS TEXT)))
                """
            )

    def ensure_dataset_row_indexes(self, dataset_id: int) -> None:
        table_name = self.dataset_rows_table_name(dataset_id)
        columns = self.list_dataset_row_columns(dataset_id)
        if not columns:
            return
        with self.connection() as conn:
            self._create_dataset_row_indexes(conn, table_name, columns)

    def drop_dataset_rows(self, dataset_id: int) -> None:
        table_name = self.dataset_rows_table_name(dataset_id)
        with self.connection() as conn:
            conn.execute(f"DROP TABLE IF EXISTS {self._quote_identifier(table_name)}")

    def dataset_rows_table_exists(self, dataset_id: int) -> bool:
        table_name = self.dataset_rows_table_name(dataset_id)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def list_dataset_row_columns(self, dataset_id: int) -> list[str]:
        table_name = self.dataset_rows_table_name(dataset_id)
        with self.connection() as conn:
            rows = conn.execute(f"PRAGMA table_info({self._quote_identifier(table_name)})").fetchall()
        return [row['name'] for row in rows]

    def _resolve_dataset_row_column_name(self, existing_columns: set[str], requested: str) -> str | None:
        if requested in existing_columns:
            return requested

        lowered = str(requested).strip().lower()
        requested_identity = self._column_identity(requested)
        # Pandas preserves an original source column (for example ``Operator``)
        # and stores the normalised equivalent as ``operator__2`` when their
        # names collide case-insensitively.  A request for the normalised lower
        # case field must prefer that generated column.
        suffixed_matches = sorted(
            column for column in existing_columns
            if str(column).strip().lower().startswith(f'{lowered}__')
        )
        if suffixed_matches:
            return suffixed_matches[0]

        case_matches = [column for column in existing_columns if str(column).strip().lower() == lowered]
        if case_matches:
            exact_lowercase = next((column for column in case_matches if column == lowered), None)
            return exact_lowercase or sorted(case_matches)[0]
        normalized_matches = [
            column for column in existing_columns
            if self._column_identity(column) == requested_identity
        ]
        if normalized_matches:
            return sorted(normalized_matches)[0]
        return None

    def resolve_dataset_row_column_name(self, dataset_id: int, requested: str) -> str | None:
        existing_columns = set(self.list_dataset_row_columns(dataset_id))
        if not existing_columns:
            return None
        return self._resolve_dataset_row_column_name(existing_columns, requested)

    def list_distinct_dataset_row_values(self, dataset_id: int, column: str, limit: int = 200) -> list[str]:
        table_name = self.dataset_rows_table_name(dataset_id)
        existing_columns = set(self.list_dataset_row_columns(dataset_id))
        resolved = self._resolve_dataset_row_column_name(existing_columns, column)
        if not resolved:
            return []
        quoted_table = self._quote_identifier(table_name)
        quoted_column = self._quote_identifier(resolved)
        query = f"""
            SELECT DISTINCT TRIM(CAST({quoted_column} AS TEXT)) AS value
            FROM {quoted_table}
            WHERE {quoted_column} IS NOT NULL AND TRIM(CAST({quoted_column} AS TEXT)) <> ''
            ORDER BY LOWER(TRIM(CAST({quoted_column} AS TEXT)))
            LIMIT ?
        """
        with self.connection() as conn:
            rows = conn.execute(query, (int(limit),)).fetchall()
        return [str(row['value']).strip() for row in rows if str(row['value']).strip()]

    def refresh_dataset_row_normalized_dimensions(self, dataset_id: int) -> bool:
        table_name = self.dataset_rows_table_name(dataset_id)
        existing_columns = set(self.list_dataset_row_columns(dataset_id))
        normalised_sources = {
            'operator': ['Operator_A', 'Operator', 'Home_Operator_A', 'Home_Operator'],
            'session_type': ['Session_Type_A', 'Session_Type', 'Type_of_Test'],
            'test_name': ['Test_Name', 'Session_Type_A', 'Session_Type', 'Type_of_Test'],
            'direction': ['Direction_A', 'Direction', 'Call_Direction'],
            'status': ['Call_Status_A', 'Call_Status', 'Test_Result', 'Test_Status'],
            'technology_primary': ['RAT_A', 'RAT', 'L2_call_Mode_A', 'Playing_Technology'],
        }
        quoted_table = self._quote_identifier(table_name)
        updates: list[tuple[str, list[str]]] = []
        for target, candidates in normalised_sources.items():
            target_column = self._resolve_dataset_row_column_name(existing_columns, target)
            if not target_column:
                continue
            sources: list[str] = []
            for candidate in candidates:
                source = self._resolve_dataset_row_column_name(existing_columns, candidate)
                if source and source != target_column and source not in sources:
                    sources.append(source)
            if sources:
                updates.append((target_column, sources))

        if not updates:
            return False

        with self.connection() as conn:
            for target_column, sources in updates:
                coalesce_expression = ', '.join(
                    f"NULLIF(TRIM(CAST({self._quote_identifier(column)} AS TEXT)), '')"
                    for column in sources
                )
                quoted_target = self._quote_identifier(target_column)
                conn.execute(
                    f"""
                    UPDATE {quoted_table}
                    SET {quoted_target} = COALESCE(
                        NULLIF(TRIM(CAST({quoted_target} AS TEXT)), ''),
                        {coalesce_expression}
                    )
                    """
                )
        return True

    def refresh_dataset_row_technology_primary(self, dataset_id: int) -> bool:
        """Backward-compatible alias for callers before dimension backfill v5."""
        return self.refresh_dataset_row_normalized_dimensions(dataset_id)

    def materialize_cdr_derived_dimensions(self, dataset_id: int) -> bool:
        """Backfill stable report dimensions without re-reading the source file."""
        table_name = self.dataset_rows_table_name(dataset_id)
        existing_columns = set(self.list_dataset_row_columns(dataset_id))
        if not existing_columns:
            return False

        session_column = self._resolve_dataset_row_column_name(existing_columns, 'Session_Type')
        call_mode_column = next((
            self._resolve_dataset_row_column_name(existing_columns, candidate)
            for candidate in ('L1_Call_Mode_A', 'L1_Call_Mode_B', 'Call_Mode')
            if self._resolve_dataset_row_column_name(existing_columns, candidate)
        ), None)
        type_column = next((
            self._resolve_dataset_row_column_name(existing_columns, candidate)
            for candidate in ('Type_of_Test', 'Test_Type')
            if self._resolve_dataset_row_column_name(existing_columns, candidate)
        ), None)
        name_column = self._resolve_dataset_row_column_name(existing_columns, 'Test_Name')
        required = {
            'Call Family': bool(session_column),
            'Test Family': bool(type_column or name_column),
        }
        missing = [name for name, needed in required.items() if needed and name not in existing_columns]
        if not missing:
            return False

        quoted_table = self._quote_identifier(table_name)
        with self.connection() as conn:
            for column in missing:
                conn.execute(f"ALTER TABLE {quoted_table} ADD COLUMN {self._quote_identifier(column)} TEXT")

            if 'Call Family' in missing and session_column:
                session = f"LOWER(COALESCE(CAST({self._quote_identifier(session_column)} AS TEXT), ''))"
                mode = (
                    f"LOWER(COALESCE(CAST({self._quote_identifier(call_mode_column)} AS TEXT), ''))"
                    if call_mode_column else "''"
                )
                conn.execute(
                    f"""
                    UPDATE {quoted_table}
                    SET {self._quote_identifier('Call Family')} = CASE
                        WHEN {session} LIKE '%multirab%' THEN 'MultiRAB'
                        WHEN {session} LIKE '%whatsapp%' THEN 'WhatsApp'
                        WHEN {session} LIKE '%volte%' OR {mode} LIKE '%volte%' THEN 'VoLTE'
                        WHEN {session} LIKE '%vonr%' OR {mode} LIKE '%vonr%' THEN 'VoNR'
                        ELSE 'CALL'
                    END
                    """
                )
            if 'Test Family' in missing:
                test_type = (
                    f"COALESCE(CAST({self._quote_identifier(type_column)} AS TEXT), '')"
                    if type_column else "''"
                )
                test_name = (
                    f"LOWER(COALESCE(CAST({self._quote_identifier(name_column)} AS TEXT), ''))"
                    if name_column else "''"
                )
                conn.execute(
                    f"""
                    UPDATE {quoted_table}
                    SET {self._quote_identifier('Test Family')} = CASE
                        WHEN {test_name} LIKE '%youtube%' THEN 'YouTube'
                        WHEN {test_name} LIKE '%fdfs%' THEN 'FDFS'
                        WHEN {test_name} LIKE '%fdtt%' THEN 'FDTT'
                        ELSE {test_type}
                    END
                    """
                )
            self._create_dataset_row_indexes(conn, table_name, self._table_columns(conn, table_name))
        return True

    def load_dataset_rows(self, dataset_id: int, columns: list[str], filters: dict[str, Any]) -> pd.DataFrame:
        table_name = self.dataset_rows_table_name(dataset_id)
        existing_columns = set(self.list_dataset_row_columns(dataset_id))
        selected_columns: list[tuple[str, str]] = []
        for column in columns:
            resolved = self._resolve_dataset_row_column_name(existing_columns, column)
            if resolved:
                selected_columns.append((column, resolved))
        if not selected_columns:
            return pd.DataFrame()

        where_clauses: list[str] = []
        params: list[Any] = []
        for key, value in filters.items():
            resolved_key = self._resolve_dataset_row_column_name(existing_columns, key)
            if key in {'aggregation', 'extra_filters', 'date_from', 'date_to'} or value in (None, '') or not resolved_key:
                continue
            values = value if isinstance(value, (list, tuple, set)) else [value]
            if str(key).casefold() == 'gcid':
                integer_values: list[int] = []
                for item in values:
                    try:
                        numeric_value = float(str(item).strip())
                    except (TypeError, ValueError):
                        continue
                    if numeric_value.is_integer():
                        integer_values.append(int(numeric_value))
                if integer_values:
                    placeholders = ', '.join('?' for _ in integer_values)
                    where_clauses.append(f"CAST({self._quote_identifier(resolved_key)} AS INTEGER) IN ({placeholders})")
                    params.extend(integer_values)
                continue
            normalized_values = [str(item).strip().lower() for item in values if str(item).strip()]
            if not normalized_values:
                continue
            placeholders = ', '.join('?' for _ in normalized_values)
            where_clauses.append(f"LOWER(TRIM(CAST({self._quote_identifier(resolved_key)} AS TEXT))) IN ({placeholders})")
            params.extend(normalized_values)

        resolved_event_time = self._resolve_dataset_row_column_name(existing_columns, 'event_start_time')
        if resolved_event_time:
            date_from = filters.get('date_from')
            date_to = filters.get('date_to')
            if date_from:
                where_clauses.append(f"date(CAST({self._quote_identifier(resolved_event_time)} AS TEXT)) >= date(?)")
                params.append(str(date_from))
            if date_to:
                where_clauses.append(f"date(CAST({self._quote_identifier(resolved_event_time)} AS TEXT)) <= date(?)")
                params.append(str(date_to))

        for key, value in (filters.get('extra_filters') or {}).items():
            resolved_key = self._resolve_dataset_row_column_name(existing_columns, key)
            if value in (None, '') or not resolved_key:
                continue
            values = value if isinstance(value, (list, tuple, set)) else [value]
            normalized_values = [str(item).strip().lower() for item in values if str(item).strip()]
            if not normalized_values:
                continue
            placeholders = ', '.join('?' for _ in normalized_values)
            where_clauses.append(f"LOWER(TRIM(CAST({self._quote_identifier(resolved_key)} AS TEXT))) IN ({placeholders})")
            params.extend(normalized_values)

        select_clause = ', '.join(
            f"{self._quote_identifier(actual_column)} AS {self._quote_identifier(requested_column)}"
            if actual_column != requested_column else self._quote_identifier(actual_column)
            for requested_column, actual_column in selected_columns
        )
        query = f"SELECT {select_clause} FROM {self._quote_identifier(table_name)}"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        with self.connection() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def list_metrics_with_non_null_data(self, dataset_id: int, metrics: list[str]) -> list[str]:
        table_name = self.dataset_rows_table_name(dataset_id)
        existing_columns = set(self.list_dataset_row_columns(dataset_id))
        selected_metrics = [metric for metric in metrics if metric in existing_columns]
        if not selected_metrics:
            return []

        aliases = [f"metric_count_{index}" for index, _ in enumerate(selected_metrics)]
        count_expressions = ", ".join(
            f"SUM(CASE WHEN {self._quote_identifier(metric)} IS NOT NULL THEN 1 ELSE 0 END) AS {self._quote_identifier(alias)}"
            for metric, alias in zip(selected_metrics, aliases, strict=False)
        )
        query = f"SELECT {count_expressions} FROM {self._quote_identifier(table_name)}"
        with self.connection() as conn:
            row = conn.execute(query).fetchone()
        if not row:
            return []
        return [
            metric for metric, alias in zip(selected_metrics, aliases, strict=False)
            if int(row[alias] or 0) > 0
        ]

    def update_dataset_profile(self, dataset_id: int, **fields: Any) -> None:
        if not fields:
            return
        assignments = ', '.join(f"{column} = ?" for column in fields)
        values = list(fields.values())
        assignments += ', updated_at = ?'
        values.append(local_now_iso())
        with self.connection() as conn:
            conn.execute(
                f"UPDATE dataset_profiles SET {assignments} WHERE dataset_id = ?",
                (*values, dataset_id),
            )

    def get_dataset(self, dataset_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT d.id, d.file_name, d.stored_path, d.uploaded_by, d.uploaded_at,
                       p.status, p.progress, p.normalization_version, p.vendor_mapping_applied, p.vendor_values_complete, p.dataset_kind, p.row_count, p.column_count,
                       p.default_metric, p.default_aggregation, p.available_metrics_json,
                       p.available_aggregations_json, p.filter_options_json, p.summary_json,
                       p.kpis_json, p.last_error, p.processed_at, p.updated_at
                FROM datasets d
                LEFT JOIN dataset_profiles p ON p.dataset_id = d.id
                WHERE d.id = ?
                """,
                (dataset_id,),
            ).fetchone()

    def list_datasets(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(
                conn.execute(
                    """
                    SELECT d.id, d.file_name, d.stored_path, d.uploaded_by, d.uploaded_at,
                           p.status, p.progress, p.normalization_version, p.vendor_mapping_applied, p.vendor_values_complete, p.dataset_kind, p.row_count, p.column_count,
                           p.default_metric, p.default_aggregation, p.available_metrics_json,
                           p.available_aggregations_json, p.filter_options_json, p.summary_json,
                           p.kpis_json, p.last_error, p.processed_at, p.updated_at
                    FROM datasets d
                    LEFT JOIN dataset_profiles p ON p.dataset_id = d.id
                    ORDER BY d.uploaded_at DESC, d.id DESC
                    """
                ).fetchall()
            )

    def delete_dataset(self, dataset_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            dataset = conn.execute(
                "SELECT id, file_name, stored_path, uploaded_by, uploaded_at FROM datasets WHERE id = ?",
                (dataset_id,),
            ).fetchone()
            if not dataset:
                return None
            conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
            return dataset

    def add_log(self, username: str, action: str, details: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs (username, action, details, created_at) VALUES (?, ?, ?, ?)",
                (username, action, details, local_now_iso()),
            )

    def add_report_run(self, *, report_type: str, technology: str, scope: str, data_dataset_id: int,
                       voice_dataset_id: int, speech_dataset_id: int, vodafone_mapping_dataset_id: int | None,
                       three_mapping_dataset_id: int | None,
                       template_name: str, output_file: str, created_by: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO report_runs (
                    report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                    mapping_dataset_id, vodafone_mapping_dataset_id, three_mapping_dataset_id, template_name, output_file, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                 None, vodafone_mapping_dataset_id, three_mapping_dataset_id, template_name, output_file, created_by),
            )

    def list_report_runs(self, limit: int | None = 50) -> list[sqlite3.Row]:
        with self.connection() as conn:
            if limit is None:
                return list(conn.execute("SELECT * FROM report_runs ORDER BY id DESC").fetchall())
            return list(conn.execute(
                "SELECT * FROM report_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall())

    def create_report_job(
        self, *, report_type: str, technology: str, scope: str,
        data_dataset_id: int, voice_dataset_id: int, speech_dataset_id: int,
        dataset_ids: dict[str, list[int]], dataset_names: dict[str, list[str]],
        slide_count: int, template_name: str, output_file: str, output_path: Path,
        created_by: str,
    ) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO report_runs (
                    report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                    template_name, output_file, created_by, created_at, dataset_ids_json, dataset_names_json,
                    slide_count, status, progress, output_path, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
                """,
                (
                    report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                    template_name, output_file, created_by, local_now_iso(), json.dumps(dataset_ids), json.dumps(dataset_names),
                    slide_count, str(output_path), local_now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def update_report_job(
        self, report_id: int, *, status: str | None = None, progress: int | None = None,
        last_error: str | None = None, finished: bool = False,
    ) -> None:
        assignments = ['updated_at = ?']
        values: list[Any] = [local_now_iso()]
        if status is not None:
            assignments.append('status = ?')
            values.append(status)
        if progress is not None:
            assignments.append('progress = ?')
            values.append(max(0, min(100, int(progress))))
        if last_error is not None:
            assignments.append('last_error = ?')
            values.append(last_error)
        if finished:
            assignments.append('finished_at = ?')
            values.append(local_now_iso())
        values.append(report_id)
        with self.connection() as conn:
            # A user can stop a worker between any two progress updates.  Do
            # not let a late update from that worker revive the stopped job.
            conn.execute(f"UPDATE report_runs SET {', '.join(assignments)} WHERE id = ? AND status <> 'stopped'", values)

    def stop_report_job(self, report_id: int) -> bool:
        """Stop a queued or running report job without deleting its audit row."""
        now = local_now_iso()
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE report_runs SET status = 'stopped', last_error = '', updated_at = ?, finished_at = ? "
                "WHERE id = ? AND status IN ('queued', 'processing')",
                (now, now, report_id),
            )
            return cursor.rowcount == 1

    def retry_report_job(self, report_id: int) -> bool:
        """Reset a completed, failed or stopped report job for reuse."""
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE report_runs SET status = 'queued', progress = 0, last_error = '', finished_at = NULL, updated_at = ? "
                "WHERE id = ? AND status IN ('failed', 'stopped', 'ready')",
                (local_now_iso(), report_id),
            )
            return cursor.rowcount == 1

    def fail_interrupted_background_jobs(self) -> tuple[list[int], list[int]]:
        """Fail jobs left running when the application process stopped.

        In-process workers cannot survive an application restart.  Persisted
        queued/processing rows must therefore become retryable failures rather
        than looking like live work forever.
        """
        message = 'Interrupted because the application restarted. Retry the job to run it again.'
        now = local_now_iso()
        with self.connection() as conn:
            tables = {str(row['name']) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
            dataset_rows = conn.execute(
                "SELECT dataset_id FROM dataset_profiles WHERE status IN ('queued', 'processing')"
            ).fetchall() if 'dataset_profiles' in tables else []
            report_rows = conn.execute(
                "SELECT id FROM report_runs WHERE status IN ('queued', 'processing')"
            ).fetchall() if 'report_runs' in tables else []
            dataset_ids = [int(row['dataset_id']) for row in dataset_rows]
            report_ids = [int(row['id']) for row in report_rows]
            if dataset_ids:
                placeholders = ','.join('?' for _ in dataset_ids)
                conn.execute(
                    f"UPDATE dataset_profiles SET status = 'failed', progress = 100, last_error = ?, processed_at = ?, updated_at = ? "
                    f"WHERE dataset_id IN ({placeholders})",
                    (message, now, now, *dataset_ids),
                )
            if report_ids:
                placeholders = ','.join('?' for _ in report_ids)
                conn.execute(
                    f"UPDATE report_runs SET status = 'failed', progress = 100, last_error = ?, updated_at = ?, finished_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (message, now, now, *report_ids),
                )
        return dataset_ids, report_ids

    def get_report_run(self, report_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM report_runs WHERE id = ?", (report_id,)).fetchone()

    def delete_report_run(self, report_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            report = conn.execute("SELECT * FROM report_runs WHERE id = ?", (report_id,)).fetchone()
            if report:
                conn.execute("DELETE FROM report_runs WHERE id = ?", (report_id,))
            return report

    def create_report_chart_job(
        self, *, technology: str, scope: str, dataset_ids: dict[str, list[int]],
        dataset_names: dict[str, list[str]], template_name: str, created_by: str,
    ) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO report_chart_jobs (
                    technology, scope, dataset_ids_json, dataset_names_json, template_name,
                    created_by, created_at, status, progress, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?)
                """,
                (
                    technology, scope, json.dumps(dataset_ids), json.dumps(dataset_names), template_name,
                    created_by, local_now_iso(), local_now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def update_report_chart_job(
        self, job_id: int, *, status: str | None = None, progress: int | None = None,
        last_error: str | None = None, chart_count: int | None = None,
        generation: str | None = None, finished: bool = False,
    ) -> None:
        assignments = ['updated_at = ?']
        values: list[Any] = [local_now_iso()]
        if status is not None:
            assignments.append('status = ?')
            values.append(status)
        if progress is not None:
            assignments.append('progress = ?')
            values.append(max(0, min(100, int(progress))))
        if last_error is not None:
            assignments.append('last_error = ?')
            values.append(last_error)
        if chart_count is not None:
            assignments.append('chart_count = ?')
            values.append(max(0, int(chart_count)))
        if generation is not None:
            assignments.append('generation = ?')
            values.append(generation)
        if finished:
            assignments.append('finished_at = ?')
            values.append(local_now_iso())
        values.append(job_id)
        with self.connection() as conn:
            # See update_report_job: stopped work must remain stopped even if
            # its in-process thread reaches a later progress checkpoint.
            conn.execute(f"UPDATE report_chart_jobs SET {', '.join(assignments)} WHERE id = ? AND status <> 'stopped'", values)

    def stop_report_chart_job(self, job_id: int) -> bool:
        """Stop a queued or running Chart Set job."""
        now = local_now_iso()
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE report_chart_jobs SET status = 'stopped', last_error = '', updated_at = ?, finished_at = ? "
                "WHERE id = ? AND status IN ('queued', 'processing')",
                (now, now, job_id),
            )
            return cursor.rowcount == 1

    def retry_report_chart_job(self, job_id: int) -> bool:
        """Reset one failed, stopped or completed Chart Set job for reuse."""
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE report_chart_jobs SET status = 'queued', progress = 0, last_error = '', chart_count = 0, "
                "generation = NULL, finished_at = NULL, updated_at = ? WHERE id = ? AND status IN ('failed', 'stopped', 'ready')",
                (local_now_iso(), job_id),
            )
            return cursor.rowcount == 1

    def list_report_chart_jobs(self, limit: int | None = 50) -> list[sqlite3.Row]:
        with self.connection() as conn:
            if limit is None:
                return list(conn.execute("SELECT * FROM report_chart_jobs ORDER BY id DESC").fetchall())
            return list(conn.execute("SELECT * FROM report_chart_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall())

    def get_report_chart_job(self, job_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM report_chart_jobs WHERE id = ?", (job_id,)).fetchone()

    def delete_report_chart_job(self, job_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            job = conn.execute("SELECT * FROM report_chart_jobs WHERE id = ?", (job_id,)).fetchone()
            if job:
                conn.execute("DELETE FROM report_chart_jobs WHERE id = ?", (job_id,))
            return job

    def delete_report_chart_jobs_for_generations(self, generations: list[str]) -> int:
        """Remove ready Chart Set jobs whose generated files were deleted."""
        unique_generations = [value for value in dict.fromkeys(generations) if value]
        if not unique_generations:
            return 0
        placeholders = ','.join('?' for _ in unique_generations)
        with self.connection() as conn:
            cursor = conn.execute(
                f"DELETE FROM report_chart_jobs WHERE generation IN ({placeholders})",
                unique_generations,
            )
            return int(cursor.rowcount)

    def fail_interrupted_report_chart_jobs(self) -> list[int]:
        """Make in-process Report Charts work retryable after an app restart."""
        message = 'Interrupted because the application restarted. Retry the job to run it again.'
        now = local_now_iso()
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM report_chart_jobs WHERE status IN ('queued', 'processing')"
            ).fetchall()
            job_ids = [int(row['id']) for row in rows]
            if job_ids:
                placeholders = ','.join('?' for _ in job_ids)
                conn.execute(
                    f"UPDATE report_chart_jobs SET status = 'failed', progress = 100, last_error = ?, updated_at = ?, finished_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (message, now, now, *job_ids),
                )
        return job_ids

    def list_logs(self, limit: int | None = 1000) -> list[sqlite3.Row]:
        with self.connection() as conn:
            if limit is None:
                return list(conn.execute("SELECT id, username, action, details, created_at FROM audit_logs ORDER BY id DESC").fetchall())
            return list(conn.execute(
                "SELECT id, username, action, details, created_at FROM audit_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall())

    def list_workspace_logs(self, dataset_id: int | None = None, limit: int = 120) -> list[dict[str, Any]]:
        workspace_actions = {
            'upload_dataset',
            'reprocess_dataset',
            'process_dataset',
            'process_dataset_failed',
            'analyze_dataset_warning',
            'analyze_dataset_failed',
            'retry_dataset',
            'queue_vendor_mapping',
            'recover_vendor_mapping_dataset',
            'vendor_mapping_skipped',
            'map_dataset_vendors',
            'map_dataset_vendors_failed',
            'queue_vendor_clearing',
            'clear_dataset_vendors',
            'clear_dataset_vendors_failed',
            'stop_vendor_mapping',
            'stop_vendor_clearing',
            'stop_dataset',
            'stop_dataset_requested',
            'delete_dataset',
            'analyze_dataset',
            'export_word',
            'export_powerpoint',
        }
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id, username, action, details, created_at FROM audit_logs ORDER BY id DESC LIMIT ?",
                (max(limit * 3, limit),),
            ).fetchall()

        logs: list[dict[str, Any]] = []
        for row in rows:
            action = row['action']
            if action not in workspace_actions:
                continue
            details_raw = row['details']
            parsed_details: Any = details_raw
            related_dataset_id: int | None = None
            try:
                parsed_details = json.loads(details_raw)
                if isinstance(parsed_details, dict):
                    raw_dataset_id = parsed_details.get('dataset_id')
                    if raw_dataset_id not in (None, ''):
                        related_dataset_id = int(raw_dataset_id)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed_details = details_raw

            if dataset_id is not None and related_dataset_id not in {None, dataset_id}:
                continue

            logs.append({
                'id': row['id'],
                'username': row['username'],
                'action': action,
                'details': parsed_details,
                'details_text': details_raw,
                'created_at': row['created_at'],
                'dataset_id': related_dataset_id,
            })
            if len(logs) >= limit:
                break

        return logs
