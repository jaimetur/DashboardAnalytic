from __future__ import annotations

import sqlite3
import shutil
import re
import csv
import io
from datetime import datetime
from contextlib import closing, contextmanager
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from threading import Lock, RLock
from time import monotonic
from typing import Any, Iterable, Iterator

import pandas as pd

from src.modules.auth import hash_password
from src.modules.column_names import MAIN_CDR_FIELDS, clean_column_name, column_identity
from src.modules.runtime_config import ignore_event_time_filtering


DATABASE_BLANK_FILTER = '__database_blank__'
WORKSPACE_REGISTRY_TABLE = '__workspace_registry__'

_WORKSPACE_WRITE_LOCKS: dict[str, RLock] = {}
_WORKSPACE_WRITE_LOCKS_GUARD = Lock()
_SQLITE_WRITE_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
    sqlite3.SQLITE_TRANSACTION,
}
logger = logging.getLogger(__name__)


def workspace_write_lock(db_path: Path | str) -> RLock:
    """Return the process-wide write coordinator for one Workspace database."""
    key = str(Path(db_path).resolve())
    with _WORKSPACE_WRITE_LOCKS_GUARD:
        return _WORKSPACE_WRITE_LOCKS.setdefault(key, RLock())


class _CoordinatedConnection(sqlite3.Connection):
    """Acquire a per-Workspace lock lazily when a connection starts writing."""

    _workspace_lock: RLock | None = None
    _workspace_key = ''
    _workspace_lock_acquired = False
    _workspace_lock_acquired_at = 0.0

    def configure_workspace_write_coordinator(self, db_path: Path | str) -> None:
        self._workspace_key = str(Path(db_path).resolve())
        self._workspace_lock = workspace_write_lock(db_path)
        self.set_authorizer(self._authorize_statement)

    def _authorize_statement(self, action, _argument_1, _argument_2, _database, _trigger):
        if action in _SQLITE_WRITE_ACTIONS and not self._workspace_lock_acquired:
            wait_started = monotonic()
            assert self._workspace_lock is not None
            self._workspace_lock.acquire()
            acquired_at = monotonic()
            self._workspace_lock_acquired = True
            self._workspace_lock_acquired_at = acquired_at
            waited = acquired_at - wait_started
            if waited >= 1.0:
                logger.warning('Workspace database writer waited %.3fs: %s', waited, self._workspace_key)
        return sqlite3.SQLITE_OK

    def _release_workspace_lock(self) -> None:
        if not self._workspace_lock_acquired:
            return
        held = monotonic() - self._workspace_lock_acquired_at
        self._workspace_lock_acquired = False
        assert self._workspace_lock is not None
        self._workspace_lock.release()
        if held >= 2.0:
            logger.warning('Workspace database writer held lock for %.3fs: %s', held, self._workspace_key)

    def commit(self) -> None:
        try:
            super().commit()
        finally:
            self._release_workspace_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_workspace_lock()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._release_workspace_lock()


def local_now_iso() -> str:
    """Return an offset-aware timestamp in the server's local timezone."""
    return datetime.now().astimezone().isoformat(timespec='microseconds')


TEMPLATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_templates (
    technology TEXT NOT NULL,
    name TEXT NOT NULL,
    content BLOB NOT NULL DEFAULT X'',
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (technology, name),
    CHECK (technology IN ('nsa', 'sa'))
);
"""

SCHEMA = TEMPLATE_SCHEMA + """
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
    region_mapping_applied INTEGER NOT NULL DEFAULT 0,
    region_mapping_dataset_id INTEGER,
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
    processing_queued_at TEXT,
    processing_started_at TEXT,
    processed_at TEXT,
    processing_options_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dataset_source_columns (
    dataset_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    column_name TEXT NOT NULL,
    column_identity TEXT NOT NULL,
    PRIMARY KEY (dataset_id, position),
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dataset_source_columns_identity
ON dataset_source_columns(dataset_id, column_identity);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dashboard_filter_selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    options_json TEXT NOT NULL DEFAULT '{}',
    row_counts_json TEXT NOT NULL DEFAULT '{}',
    universe_row_counts_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE IF NOT EXISTS autocalculated_fields (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    definition_json TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operator_mappings (
    source_value TEXT PRIMARY KEY COLLATE NOCASE,
    canonical_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_mappings (
    source_value TEXT PRIMARY KEY COLLATE NOCASE,
    canonical_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chart_mapping_groups (
    mapping_type TEXT NOT NULL CHECK(mapping_type IN ('operator', 'vendor')),
    canonical_value TEXT NOT NULL COLLATE NOCASE,
    position INTEGER NOT NULL DEFAULT 0,
    color TEXT NOT NULL,
    PRIMARY KEY (mapping_type, canonical_value)
);

CREATE TABLE IF NOT EXISTS generated_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL CHECK(job_type IN ('report', 'chart_set')),
    report_type TEXT NOT NULL DEFAULT '',
    technology TEXT NOT NULL,
    scope TEXT NOT NULL,
    data_dataset_id INTEGER,
    voice_dataset_id INTEGER,
    speech_dataset_id INTEGER,
    mapping_dataset_id INTEGER,
    vodafone_mapping_dataset_id INTEGER,
    three_mapping_dataset_id INTEGER,
    template_name TEXT NOT NULL,
    output_file TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    dataset_ids_json TEXT NOT NULL DEFAULT '{}',
    dataset_names_json TEXT NOT NULL DEFAULT '{}',
    slide_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ready',
    progress INTEGER NOT NULL DEFAULT 100,
    last_error TEXT,
    output_path TEXT,
    chart_count INTEGER NOT NULL DEFAULT 0,
    generation TEXT,
    generate_tooltips INTEGER NOT NULL DEFAULT 1,
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

CREATE TABLE IF NOT EXISTS application_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transfer_offers (
    id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at REAL NOT NULL
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
    def __init__(self, db_path: Path, global_db_path: Path | None = None, workspace_registry_db_path: Path | None = None) -> None:
        self.db_path = db_path
        self.global_db_path = global_db_path or db_path
        self.workspace_registry_db_path = workspace_registry_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0, factory=_CoordinatedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.configure_workspace_write_coordinator(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def global_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.global_db_path, timeout=30.0, factory=_CoordinatedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.configure_workspace_write_coordinator(self.global_db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def set_global_database(self, path: Path) -> None:
        self.global_db_path = path
        self.global_db_path.parent.mkdir(parents=True, exist_ok=True)

    def set_workspace_registry_database(self, path: Path) -> None:
        self.workspace_registry_db_path = path
        self.workspace_registry_db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def workspace_registry_connection(self) -> Iterator[sqlite3.Connection]:
        if self.workspace_registry_db_path is None:
            raise ValueError('The workspace registry database is not available.')
        conn = sqlite3.connect(
            self.workspace_registry_db_path, timeout=30.0, factory=_CoordinatedConnection,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.configure_workspace_write_coordinator(self.workspace_registry_db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def replace_global_database_snapshot(self, snapshot_path: Path) -> None:
        """Replace the global database while preserving local transfer state."""
        source = Path(snapshot_path)
        if not source.is_file():
            raise ValueError('The configuration archive does not contain application.db.')
        try:
            with closing(sqlite3.connect(f'file:{source}?mode=ro', uri=True)) as conn, conn:
                users_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValueError('The configuration archive contains an invalid application.db.') from exc
        if not users_table:
            raise ValueError('The configuration archive application.db does not contain the users table.')
        destination = self.global_db_path
        temporary = destination.with_name(f'.{destination.name}.importing')
        with workspace_write_lock(destination):
            local_transfer_offers: list[tuple[str, str, float]] = []
            if destination.is_file():
                with closing(sqlite3.connect(destination)) as current:
                    has_transfer_offers = current.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transfer_offers'"
                    ).fetchone()
                    if has_transfer_offers:
                        local_transfer_offers = current.execute(
                            "SELECT id, payload_json, updated_at FROM transfer_offers"
                        ).fetchall()
            try:
                shutil.copy2(source, temporary)
                with closing(sqlite3.connect(temporary)) as imported, imported:
                    imported.execute(
                        """
                        CREATE TABLE IF NOT EXISTS transfer_offers (
                            id TEXT PRIMARY KEY,
                            payload_json TEXT NOT NULL,
                            updated_at REAL NOT NULL
                        )
                        """
                    )
                    imported.execute("DELETE FROM transfer_offers")
                    imported.executemany(
                        "INSERT INTO transfer_offers (id, payload_json, updated_at) VALUES (?, ?, ?)",
                        local_transfer_offers,
                    )
                for suffix in ('-wal', '-shm'):
                    Path(f'{destination}{suffix}').unlink(missing_ok=True)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)

    def remove_legacy_global_tables(self) -> list[str]:
        """Remove global-only tables left inside an old workspace database.

        Users and workspace access are owned only
        by ``config/application.db``.  Old workspace copies must never be
        available to confuse manual inspection or a future code path.
        """
        if self.db_path.resolve() == self.global_db_path.resolve() or not self.db_path.exists():
            return []
        removed: list[str] = []
        with self.connection() as conn:
            for table_name in ('user_workspace_access', 'users'):
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
                ).fetchone()
                if exists:
                    conn.execute(f'DROP TABLE {self._quote_identifier(table_name)}')
                    removed.append(table_name)
        return removed

    @staticmethod
    def _migrate_calculated_dimensions_table(conn: sqlite3.Connection) -> None:
        """Rename the former table without losing existing field definitions."""
        tables = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('calculated_dimensions', 'autocalculated_fields')"
            )
        }
        if 'calculated_dimensions' not in tables:
            return
        if 'autocalculated_fields' not in tables:
            conn.execute('ALTER TABLE calculated_dimensions RENAME TO autocalculated_fields')
            return
        conn.execute(
            """INSERT OR REPLACE INTO autocalculated_fields (name, definition_json, position, updated_at)
               SELECT name, definition_json, position, updated_at FROM calculated_dimensions"""
        )
        conn.execute('DROP TABLE calculated_dimensions')

    @staticmethod
    def _ensure_dashboard_filter_selection_columns(conn: sqlite3.Connection) -> None:
        columns = {str(row['name']) for row in conn.execute('PRAGMA table_info(dashboard_filter_selections)').fetchall()}
        if 'options_json' not in columns:
            conn.execute("ALTER TABLE dashboard_filter_selections ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'")
        if 'row_counts_json' not in columns:
            conn.execute("ALTER TABLE dashboard_filter_selections ADD COLUMN row_counts_json TEXT NOT NULL DEFAULT '{}'")
        if 'universe_row_counts_json' not in columns:
            conn.execute("ALTER TABLE dashboard_filter_selections ADD COLUMN universe_row_counts_json TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def _remove_legacy_dashboard_selection_rows(conn: sqlite3.Connection) -> None:
        """Remove the unused row-key cache retained by older workspaces."""
        conn.execute('DROP TABLE IF EXISTS dashboard_filter_selection_rows')
        columns = {str(row['name']) for row in conn.execute('PRAGMA table_info(dashboard_filter_selections)').fetchall()}
        if 'materialized' in columns:
            conn.execute('ALTER TABLE dashboard_filter_selections DROP COLUMN materialized')

    def initialize(self) -> None:
        self.remove_legacy_global_tables()
        with self.connection() as conn:
            self._configure_database_journal(conn)
            self._migrate_calculated_dimensions_table(conn)
            conn.executescript(SCHEMA)
            self._ensure_chart_mapping_groups(conn)
            self._ensure_dashboard_filter_selection_columns(conn)
            self._remove_legacy_dashboard_selection_rows(conn)
            # Functional indexes are created when reporting rows are imported
            # or refreshed. Building every newly introduced index over all
            # legacy CDR tables here can block application startup for minutes
            # on large workspaces.
            self._ensure_report_template_columns(conn)
            self._ensure_dataset_profile_columns(conn)
            self._ensure_generated_job_columns(conn)
            self._migrate_generated_jobs(conn)
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
            self._configure_database_journal(conn)
            conn.executescript(GLOBAL_SCHEMA)
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
            # in the bootstrap workspace. Add the membership idempotently.
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
    def _ensure_chart_mapping_groups(conn: sqlite3.Connection) -> None:
        """Migrate the former hardcoded chart order and colours into workspace data."""
        defaults = {
            'operator': (
                ('VF', '#E15759', ('Vodafone', 'Vodafone UK', 'VFUK')),
                ('3', '#F28E2B', ('Three', 'Three UK', '3 UK')),
                ('EE', '#76B7B2', ('EE UK', 'Everything Everywhere')),
                ('O2', '#4E79A7', ('Telefonica', 'Telefonica O2')),
            ),
            'vendor': (
                ('Ericsson', '#2E8B57', ()), ('Huawei', '#E15759', ()),
                ('Samsung', '#7B3FB5', ()), ('NSN', '#4E79A7', ()),
                ('Mixed Vendor', '#D9A514', ('Mixed',)),
                ('Other Vendor', '#D9A514', ('Other',)),
                ('(blank)', '#7A8791', ('Blank', 'nan', 'none')),
            ),
        }
        defaults_seeded = conn.execute(
            "SELECT 1 FROM workspace_state WHERE key = 'chart_mapping_defaults_v1'"
        ).fetchone()
        for mapping_type, entries in defaults.items():
            alias_table = f'{mapping_type}_mappings'
            if not defaults_seeded:
                for position, (canonical, color, aliases) in enumerate(entries):
                    conn.execute(
                        'INSERT OR IGNORE INTO chart_mapping_groups '
                        '(mapping_type, canonical_value, position, color) VALUES (?, ?, ?, ?)',
                        (mapping_type, canonical, position, color),
                    )
                    conn.executemany(
                        f'INSERT OR IGNORE INTO {alias_table} (source_value, canonical_value) VALUES (?, ?)',
                        [(source, canonical) for source in (canonical, *aliases)],
                    )
            existing = conn.execute(
                f'SELECT DISTINCT canonical_value FROM {alias_table} ORDER BY canonical_value COLLATE NOCASE'
            ).fetchall()
            next_position = int(conn.execute(
                'SELECT COALESCE(MAX(position), -1) + 1 FROM chart_mapping_groups WHERE mapping_type = ?',
                (mapping_type,),
            ).fetchone()[0])
            for row in existing:
                canonical = str(row['canonical_value']).strip()
                inserted = conn.execute(
                    'INSERT OR IGNORE INTO chart_mapping_groups '
                    '(mapping_type, canonical_value, position, color) VALUES (?, ?, ?, ?)',
                    (mapping_type, canonical, next_position, '#6F42C1'),
                )
                if inserted.rowcount:
                    next_position += 1
        if not defaults_seeded:
            conn.execute(
                "INSERT INTO workspace_state (key, value) VALUES ('chart_mapping_defaults_v1', '1')"
            )
    @staticmethod
    def _configure_database_journal(conn: sqlite3.Connection) -> None:
        """Enable concurrent readers once, outside request-time connections.

        Changing ``synchronous`` on every connection can itself fail while a
        background writer owns the database.  WAL is persistent, so database
        initialization is the appropriate place to select it; NORMAL then
        applies to the initialization and migration work performed by this
        connection without turning ordinary reads into configuration writes.
        """
        current_mode = str(conn.execute('PRAGMA journal_mode').fetchone()[0]).casefold()
        if current_mode != 'wal':
            selected_mode = str(conn.execute('PRAGMA journal_mode=WAL').fetchone()[0]).casefold()
            if selected_mode != 'wal':
                raise sqlite3.OperationalError(f'Unable to enable WAL journal mode (selected {selected_mode}).')
        conn.execute('PRAGMA synchronous=NORMAL')

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
        if 'region_mapping_applied' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN region_mapping_applied INTEGER NOT NULL DEFAULT 0")
        if 'region_mapping_dataset_id' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN region_mapping_dataset_id INTEGER")
        if 'processing_started_at' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN processing_started_at TEXT")
        if 'processing_queued_at' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN processing_queued_at TEXT")
        if 'processing_options_json' not in existing_columns:
            conn.execute("ALTER TABLE dataset_profiles ADD COLUMN processing_options_json TEXT NOT NULL DEFAULT '{}'")

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

    def _migrate_generated_jobs(self, conn: sqlite3.Connection) -> None:
        """Merge the two legacy job tables into the single generated-jobs table."""
        tables = {str(row['name']) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()}
        if 'report_runs' in tables:
            self._ensure_legacy_report_run_columns(conn)
            conn.execute(
                """
                INSERT INTO generated_jobs (
                    id, job_type, report_type, technology, scope, data_dataset_id, voice_dataset_id,
                    speech_dataset_id, mapping_dataset_id, vodafone_mapping_dataset_id,
                    three_mapping_dataset_id, template_name, output_file, created_by, created_at,
                    dataset_ids_json, dataset_names_json, slide_count, status, progress,
                    last_error, output_path, updated_at, finished_at
                )
                SELECT id, 'report', report_type, technology, scope, data_dataset_id, voice_dataset_id,
                    speech_dataset_id, mapping_dataset_id, vodafone_mapping_dataset_id,
                    three_mapping_dataset_id, template_name, output_file, created_by, created_at,
                    dataset_ids_json, dataset_names_json, slide_count, status, progress,
                    last_error, output_path, COALESCE(updated_at, created_at), finished_at
                FROM report_runs ORDER BY id
                """
            )
            conn.execute('DROP TABLE report_runs')
        if 'report_chart_jobs' in tables:
            self._ensure_legacy_report_chart_job_columns(conn)
            conn.execute(
                """
                INSERT INTO generated_jobs (
                    job_type, technology, scope, dataset_ids_json, dataset_names_json,
                    template_name, chart_count, generation, created_by, created_at,
                    status, progress, last_error, updated_at, finished_at
                )
                SELECT 'chart_set', technology, scope, dataset_ids_json, dataset_names_json,
                    template_name, chart_count, generation, created_by, created_at,
                    status, progress, last_error, COALESCE(updated_at, created_at), finished_at
                FROM report_chart_jobs ORDER BY id
                """
            )
            conn.execute('DROP TABLE report_chart_jobs')

    def _ensure_generated_job_columns(self, conn: sqlite3.Connection) -> None:
        """Keep persisted job options available after schema upgrades."""
        tables = {str(row['name']) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        if 'generated_jobs' not in tables:
            return
        columns = {str(row['name']) for row in conn.execute("PRAGMA table_info(generated_jobs)").fetchall()}
        if 'generate_tooltips' not in columns:
            conn.execute("ALTER TABLE generated_jobs ADD COLUMN generate_tooltips INTEGER NOT NULL DEFAULT 1")
        if 'started_at' not in columns:
            conn.execute("ALTER TABLE generated_jobs ADD COLUMN started_at TEXT")

    def _ensure_legacy_report_run_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row['name'] for row in conn.execute("PRAGMA table_info(report_runs)").fetchall()}
        migrations = {
            'vodafone_mapping_dataset_id': 'INTEGER', 'three_mapping_dataset_id': 'INTEGER',
            'dataset_ids_json': "TEXT NOT NULL DEFAULT '{}'", 'dataset_names_json': "TEXT NOT NULL DEFAULT '{}'",
            'slide_count': 'INTEGER NOT NULL DEFAULT 0', 'status': "TEXT NOT NULL DEFAULT 'ready'",
            'progress': 'INTEGER NOT NULL DEFAULT 100', 'last_error': 'TEXT', 'output_path': 'TEXT',
            'updated_at': 'TEXT', 'finished_at': 'TEXT',
        }
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE report_runs ADD COLUMN {column} {definition}")

    def _ensure_legacy_report_chart_job_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row['name'] for row in conn.execute("PRAGMA table_info(report_chart_jobs)").fetchall()}
        migrations = {
            'dataset_ids_json': "TEXT NOT NULL DEFAULT '{}'", 'dataset_names_json': "TEXT NOT NULL DEFAULT '{}'",
            'template_name': "TEXT NOT NULL DEFAULT ''", 'chart_count': 'INTEGER NOT NULL DEFAULT 0',
            'generation': 'TEXT', 'created_by': "TEXT NOT NULL DEFAULT ''", 'created_at': 'TEXT',
            'status': "TEXT NOT NULL DEFAULT 'queued'", 'progress': 'INTEGER NOT NULL DEFAULT 0',
            'last_error': 'TEXT', 'updated_at': 'TEXT', 'finished_at': 'TEXT',
        }
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE report_chart_jobs ADD COLUMN {column} {definition}")

    def _ensure_report_template_columns(self, conn: sqlite3.Connection) -> None:
        """Keep template storage complete and one promoted template per technology."""
        columns = {row['name'] for row in conn.execute("PRAGMA table_info(report_templates)").fetchall()}
        if 'content' not in columns:
            conn.execute("ALTER TABLE report_templates ADD COLUMN content BLOB NOT NULL DEFAULT X''")
        if 'created_at' not in columns:
            conn.execute("ALTER TABLE report_templates ADD COLUMN created_at TEXT")
        if 'updated_at' not in columns:
            conn.execute("ALTER TABLE report_templates ADD COLUMN updated_at TEXT")
        now = local_now_iso()
        if conn.execute("SELECT 1 FROM report_templates WHERE created_at IS NULL LIMIT 1").fetchone():
            conn.execute("UPDATE report_templates SET created_at = ? WHERE created_at IS NULL", (now,))
        if conn.execute("SELECT 1 FROM report_templates WHERE updated_at IS NULL LIMIT 1").fetchone():
            conn.execute(
                "UPDATE report_templates SET updated_at = COALESCE(created_at, ?) WHERE updated_at IS NULL",
                (now,),
            )
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

    def initialize_template_registry(self) -> None:
        """Prepare template metadata without scanning datasets or global users."""
        with self.connection() as conn:
            conn.executescript(TEMPLATE_SCHEMA)
            self._ensure_report_template_columns(conn)

    def list_report_templates(self, technology: str) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT technology, name, content, is_default, created_at, updated_at FROM report_templates WHERE technology = ? ORDER BY name COLLATE NOCASE",
                (technology,),
            ).fetchall()

    def add_report_template(self, technology: str, name: str, content: bytes = b'', *, is_default: bool = False) -> None:
        with self.connection() as conn:
            if is_default:
                conn.execute("UPDATE report_templates SET is_default = 0 WHERE technology = ?", (technology,))
            now = local_now_iso()
            conn.execute(
                "INSERT INTO report_templates (technology, name, content, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (technology, name, sqlite3.Binary(content), int(is_default), now, now),
            )

    def set_report_template_content(self, technology: str, name: str, content: bytes) -> None:
        with self.connection() as conn:
            result = conn.execute(
                "UPDATE report_templates SET content = ?, updated_at = ? WHERE technology = ? AND name = ?",
                (sqlite3.Binary(content), local_now_iso(), technology, name),
            )
            if not result.rowcount:
                raise ValueError('Report Template was not found.')

    def report_template_content(self, technology: str, name: str) -> bytes:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT content FROM report_templates WHERE technology = ? AND name = ?", (technology, name),
            ).fetchone()
        if not row:
            raise ValueError('Report Template was not found.')
        return bytes(row['content'] or b'')

    def set_default_report_template(self, technology: str, name: str) -> None:
        with self.connection() as conn:
            template = conn.execute(
                "SELECT is_default FROM report_templates WHERE technology = ? AND name = ?", (technology, name)
            ).fetchone()
            if not template:
                raise ValueError('Report Template was not found.')
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
        with self.connection() as conn:
            conn.execute(
                "UPDATE report_templates SET name = ?, updated_at = ? WHERE technology = ? AND name = ?",
                (new_name, local_now_iso(), technology, name),
            )

    def move_report_template(self, technology: str, name: str, target_technology: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE report_templates SET technology = ?, updated_at = ? WHERE technology = ? AND name = ?",
                (target_technology, local_now_iso(), technology, name),
            )

    def touch_report_template(self, technology: str, name: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE report_templates SET updated_at = ? WHERE technology = ? AND name = ?",
                (local_now_iso(), technology, name),
            )

    def delete_report_template(self, technology: str, name: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM report_templates WHERE technology = ? AND name = ?", (technology, name))

    def dataset_rows_table_name(self, dataset_id: int) -> str:
        return f'dataset_rows_{int(dataset_id)}'

    def _quote_identifier(self, identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    def _table_connection(self, table_name: str):
        """Select the owning database for workspace and global tables."""
        if table_name == 'report_templates':
            return self.connection
        if table_name == WORKSPACE_REGISTRY_TABLE:
            return self.workspace_registry_connection
        return self.global_connection if table_name in self.list_global_database_tables() else self.connection

    @staticmethod
    def _physical_database_table_name(table_name: str) -> str:
        """Map the Database Management registry alias to its real SQLite table."""
        return 'workspaces' if table_name == WORKSPACE_REGISTRY_TABLE else table_name

    def list_global_database_tables(self) -> list[str]:
        """Return every user table physically stored in application.db."""
        with self.global_connection() as conn:
            rows = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
        return [str(row['name']) for row in rows]

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
        # Discover every real global configuration table instead of maintaining
        # a partial UI whitelist. This keeps Database Management aligned with
        # schema additions such as persisted transfer offers.
        for name in self.list_global_database_tables():
            if name not in names:
                names.append(name)
        if self.workspace_registry_db_path is not None and self.workspace_registry_db_path.is_file():
            names.append(WORKSPACE_REGISTRY_TABLE)
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

    def _database_table_has_rowid(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,),
        ).fetchone()
        return bool(row) and not re.search(r'\bWITHOUT\s+ROWID\b', str(row['sql'] or ''), flags=re.I)

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
        """Return one bounded page, including tables that deliberately omit rowid."""
        if table_name not in self.list_database_tables():
            raise ValueError('The selected table does not exist in the active workspace database.')
        page_size = max(1, min(int(limit), 250))
        page_offset = max(0, int(offset))
        physical_table_name = self._physical_database_table_name(table_name)
        quoted_table = self._quote_identifier(physical_table_name)
        with self._table_connection(table_name)() as conn:
            column_rows = self._database_table_metadata(conn, physical_table_name)
            has_rowid = self._database_table_has_rowid(conn, physical_table_name)
            where_clause, parameters = self._database_filter_clause(column_rows, filters)
            columns = [
                {
                    'name': str(row['name']),
                    'type': str(row['type'] or ''),
                    # Workspace registry paths and identifiers are maintained
                    # atomically by Workspace Management; Database Management
                    # exposes the table for inspection only.
                    'primary_key': bool(row['pk']) or table_name == WORKSPACE_REGISTRY_TABLE,
                    'not_null': bool(row['notnull']),
                }
                for row in column_rows
            ]
            primary_key_columns = [
                str(row['name']) for row in sorted(column_rows, key=lambda item: int(item['pk']) or 10_000)
                if int(row['pk']) > 0
            ]
            if has_rowid:
                select_query = (
                    f"SELECT rowid AS __database_rowid__, * FROM {quoted_table}{where_clause} "
                    "ORDER BY rowid DESC LIMIT ? OFFSET ?"
                )
            else:
                order_columns = primary_key_columns or [str(row['name']) for row in column_rows]
                order_clause = ', '.join(
                    f'{self._quote_identifier(column)} DESC' for column in order_columns
                )
                select_query = (
                    f"SELECT * FROM {quoted_table}{where_clause} ORDER BY {order_clause} LIMIT ? OFFSET ?"
                )
            rows = [
                {
                    key: (value.decode('utf-8', errors='replace') if isinstance(value, (bytes, memoryview)) else value)
                    for key, value in dict(row).items()
                }
                for row in conn.execute(
                    select_query,
                    (*parameters, page_size, page_offset),
                ).fetchall()
            ]
            if not has_rowid:
                for index, row in enumerate(rows, start=page_offset):
                    row['__database_rowid__'] = f'read-only-{index}'
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
            'editable': has_rowid and table_name != WORKSPACE_REGISTRY_TABLE,
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
        physical_table_name = self._physical_database_table_name(table_name)
        quoted_table = self._quote_identifier(physical_table_name)
        result_limit = max(1, min(int(limit), 500))
        with self._table_connection(table_name)() as conn:
            metadata = self._database_table_metadata(conn, physical_table_name)
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
        if table_name == WORKSPACE_REGISTRY_TABLE:
            raise ValueError('Use Workspace Management to change workspace registry records.')
        if not isinstance(updates, dict) or not updates:
            raise ValueError('Enter at least one changed value before saving.')
        quoted_table = self._quote_identifier(table_name)
        with self._table_connection(table_name)() as conn:
            if not self._database_table_has_rowid(conn, table_name):
                raise ValueError('This internal table is read-only because it does not have SQLite row identifiers.')
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
        if table_name == WORKSPACE_REGISTRY_TABLE:
            raise ValueError('Use Workspace Management to remove workspace registry records.')
        quoted_table = self._quote_identifier(table_name)
        with self._table_connection(table_name)() as conn:
            if not self._database_table_has_rowid(conn, table_name):
                raise ValueError('This internal table is read-only because it does not have SQLite row identifiers.')
            result = conn.execute(f"DELETE FROM {quoted_table} WHERE rowid = ?", (int(rowid),))
            if result.rowcount != 1:
                raise ValueError('The row no longer exists. Refresh the table and try again.')

    def _index_name(self, table_name: str, column_name: str, suffix: str) -> str:
        return f'idx_{table_name}_{column_name}_{suffix}'

    def _sqlite_safe_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        positions: dict[str, list[int]] = {}
        original_names = [str(column).strip() or 'Column' for column in df.columns]
        names = [clean_column_name(column) for column in original_names]
        for index, name in enumerate(names):
            positions.setdefault(name.casefold(), []).append(index)
        if all(len(indices) == 1 for indices in positions.values()) and names == list(df.columns):
            return df
        selected_indices: list[int] = []
        selected_names: list[str] = []
        for normalized, indices in positions.items():
            selected_index = (
                next((index for index in reversed(indices) if original_names[index] == 'vendor'), indices[0])
                if normalized == 'vendor' else indices[0]
            )
            selected_indices.append(selected_index)
            selected_names.append('Vendor' if normalized == 'vendor' else names[indices[0]])
        ordered = sorted(zip(selected_indices, selected_names, strict=False), key=lambda item: item[0])
        safe_df = df.iloc[:, [index for index, _name in ordered]].copy()
        safe_df.columns = [name for _index, name in ordered]
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

    def remap_workspace_access(self, workspace_id_map: dict[str, str]) -> None:
        """Translate imported workspace grants from source ids to local ids."""
        normalized = {
            str(source).strip(): str(destination).strip()
            for source, destination in workspace_id_map.items()
            if str(source).strip() and str(destination).strip()
        }
        if not normalized:
            return
        with self.global_connection() as conn:
            self._ensure_user_workspace_columns(conn)
            for row in conn.execute('SELECT id, workspace_ids_json FROM users').fetchall():
                workspace_ids = [
                    normalized.get(workspace_id, workspace_id)
                    for workspace_id in self._workspace_ids_from_json(row['workspace_ids_json'])
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

    def get_workspace_state(self, key: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute('SELECT value FROM workspace_state WHERE key = ?', (key,)).fetchone()
            return str(row['value']) if row else None

    def set_workspace_state(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                'INSERT INTO workspace_state (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                (key, value),
            )

    def try_set_workspace_state(self, key: str, value: str, *, timeout_seconds: float = 0.25) -> bool:
        """Best-effort state update that never waits behind a long Workspace writer."""
        try:
            with closing(sqlite3.connect(self.db_path, timeout=timeout_seconds)) as conn, conn:
                conn.execute(f"PRAGMA busy_timeout = {max(1, int(timeout_seconds * 1000))}")
                conn.execute(
                    'INSERT INTO workspace_state (key, value) VALUES (?, ?) '
                    'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                    (key, value),
                )
            return True
        except sqlite3.OperationalError:
            return False

    def get_application_state(self, key: str) -> str | None:
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            row = conn.execute('SELECT value FROM application_state WHERE key = ?', (key,)).fetchone()
            return str(row['value']) if row else None

    def set_application_state(self, key: str, value: str) -> None:
        with self.global_connection() as conn:
            conn.executescript(GLOBAL_SCHEMA)
            conn.execute(
                'INSERT INTO application_state (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                (key, value),
            )

    def list_calculated_dimensions(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT name, definition_json, position, updated_at FROM autocalculated_fields ORDER BY position, name COLLATE NOCASE'
            ).fetchall()
        return [json.loads(str(row['definition_json'])) for row in rows]

    def list_operator_mappings(self) -> dict[str, str]:
        return self._list_chart_mappings('operator')

    def list_vendor_mappings(self) -> dict[str, str]:
        return self._list_chart_mappings('vendor')

    def _list_chart_mappings(self, mapping_type: str) -> dict[str, str]:
        table = self._chart_mapping_table(mapping_type)
        with self.connection() as conn:
            rows = conn.execute(
                f'SELECT source_value, canonical_value FROM {table} ORDER BY source_value COLLATE NOCASE'
            ).fetchall()
        return {str(row['source_value']).strip().casefold(): str(row['canonical_value']).strip() for row in rows}

    def list_operator_mapping_groups(self) -> list[dict[str, Any]]:
        return self._list_chart_mapping_groups('operator')

    def list_vendor_mapping_groups(self) -> list[dict[str, Any]]:
        return self._list_chart_mapping_groups('vendor')

    @staticmethod
    def _chart_mapping_table(mapping_type: str) -> str:
        if mapping_type not in {'operator', 'vendor'}:
            raise ValueError('Unknown chart mapping type.')
        return f'{mapping_type}_mappings'

    def _list_chart_mapping_groups(self, mapping_type: str) -> list[dict[str, Any]]:
        """Return editable aliases, colour and explicit chart order."""
        table = self._chart_mapping_table(mapping_type)
        with self.connection() as conn:
            rows = conn.execute(
                f'SELECT m.source_value, m.canonical_value, g.position, g.color FROM {table} m '
                'JOIN chart_mapping_groups g ON g.mapping_type = ? '
                'AND g.canonical_value = m.canonical_value COLLATE NOCASE '
                'ORDER BY g.position, g.canonical_value COLLATE NOCASE, m.source_value COLLATE NOCASE',
                (mapping_type,),
            ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            canonical = str(row['canonical_value']).strip()
            key = canonical.casefold()
            group = grouped.setdefault(key, {
                'canonical': canonical, 'aliases': [], 'position': int(row['position']),
                'color': str(row['color']),
            })
            source = str(row['source_value']).strip()
            if source.casefold() != key:
                group['aliases'].append(source)
        return list(grouped.values())

    def chart_mapping_settings(self) -> dict[str, Any]:
        return {
            'operator_mappings': self.list_operator_mappings(),
            'operator_mapping_groups': self.list_operator_mapping_groups(),
            'vendor_mappings': self.list_vendor_mappings(),
            'vendor_mapping_groups': self.list_vendor_mapping_groups(),
        }

    def replace_operator_mapping_group(
        self, original_canonical: str | None, canonical_value: str, aliases: Iterable[object],
        color: str | None = None,
    ) -> None:
        self._replace_chart_mapping_group('operator', original_canonical, canonical_value, aliases, color)

    def replace_vendor_mapping_group(
        self, original_canonical: str | None, canonical_value: str, aliases: Iterable[object],
        color: str | None = None,
    ) -> None:
        self._replace_chart_mapping_group('vendor', original_canonical, canonical_value, aliases, color)

    def _replace_chart_mapping_group(
        self, mapping_type: str, original_canonical: str | None, canonical_value: str,
        aliases: Iterable[object], color: str | None,
    ) -> None:
        """Create or replace one canonical chart identity and its aliases."""
        table = self._chart_mapping_table(mapping_type)
        label = mapping_type.title()
        canonical = str(canonical_value).strip()
        if not canonical:
            raise ValueError(f'Canonical {label} is required.')
        normalized_color = str(color or '').strip().upper()
        if normalized_color and not re.fullmatch(r'#[0-9A-F]{6}', normalized_color):
            raise ValueError('Colour must use the #RRGGBB format.')
        original = str(original_canonical or '').strip()
        desired_sources: dict[str, str] = {canonical.casefold(): canonical}
        for raw_alias in aliases:
            alias = str(raw_alias).strip()
            if alias:
                desired_sources.setdefault(alias.casefold(), alias)

        with self.connection() as conn:
            rows = conn.execute(
                f'SELECT source_value, canonical_value FROM {table}'
            ).fetchall()
            if not original and any(
                str(row['canonical_value']).strip().casefold() == canonical.casefold() for row in rows
            ):
                original = canonical
            if original and not any(
                str(row['canonical_value']).strip().casefold() == original.casefold() for row in rows
            ):
                raise ValueError(f'The {label} Mapping group no longer exists.')
            if any(
                str(row['canonical_value']).strip().casefold() == canonical.casefold()
                and str(row['canonical_value']).strip().casefold() != original.casefold()
                for row in rows
            ):
                raise ValueError(f'Another {label} Mapping already uses this canonical label.')
            conflicts = sorted({
                str(row['source_value']).strip()
                for row in rows
                if str(row['source_value']).strip().casefold() in desired_sources
                and str(row['canonical_value']).strip().casefold() != original.casefold()
            }, key=str.casefold)
            if conflicts:
                raise ValueError(
                    f"These aliases already belong to another canonical {label}: {', '.join(conflicts)}."
                )
            previous = conn.execute(
                'SELECT position, color FROM chart_mapping_groups '
                'WHERE mapping_type = ? AND canonical_value = ? COLLATE NOCASE',
                (mapping_type, original or canonical),
            ).fetchone()
            position = int(previous['position']) if previous else int(conn.execute(
                'SELECT COALESCE(MAX(position), -1) + 1 FROM chart_mapping_groups WHERE mapping_type = ?',
                (mapping_type,),
            ).fetchone()[0])
            selected_color = normalized_color or (str(previous['color']) if previous else '#6F42C1')
            if original:
                conn.execute(
                    f'DELETE FROM {table} WHERE canonical_value = ? COLLATE NOCASE',
                    (original,),
                )
                conn.execute(
                    'DELETE FROM chart_mapping_groups WHERE mapping_type = ? AND canonical_value = ? COLLATE NOCASE',
                    (mapping_type, original),
                )
            conn.execute(
                'INSERT INTO chart_mapping_groups (mapping_type, canonical_value, position, color) VALUES (?, ?, ?, ?)',
                (mapping_type, canonical, position, selected_color),
            )
            conn.executemany(
                f'INSERT INTO {table} (source_value, canonical_value) VALUES (?, ?)',
                [(source, canonical) for source in desired_sources.values()],
            )

    def delete_operator_mapping_group(self, canonical_value: str) -> None:
        self._delete_chart_mapping_group('operator', canonical_value)

    def delete_vendor_mapping_group(self, canonical_value: str) -> None:
        self._delete_chart_mapping_group('vendor', canonical_value)

    def _delete_chart_mapping_group(self, mapping_type: str, canonical_value: str) -> None:
        table = self._chart_mapping_table(mapping_type)
        canonical = str(canonical_value).strip()
        if not canonical:
            raise ValueError(f'Canonical {mapping_type.title()} is required.')
        with self.connection() as conn:
            result = conn.execute(
                f'DELETE FROM {table} WHERE canonical_value = ? COLLATE NOCASE',
                (canonical,),
            )
            if result.rowcount < 1:
                raise ValueError(f'The {mapping_type.title()} Mapping group no longer exists.')
            conn.execute(
                'DELETE FROM chart_mapping_groups WHERE mapping_type = ? AND canonical_value = ? COLLATE NOCASE',
                (mapping_type, canonical),
            )
            self._compact_chart_mapping_positions(conn, mapping_type)

    def move_chart_mapping_group(self, mapping_type: str, canonical_value: str, direction: str) -> None:
        if direction not in {'up', 'down'}:
            raise ValueError('Choose a valid mapping direction.')
        canonical = str(canonical_value).strip()
        with self.connection() as conn:
            groups = conn.execute(
                'SELECT canonical_value, position FROM chart_mapping_groups WHERE mapping_type = ? '
                'ORDER BY position, canonical_value COLLATE NOCASE',
                (mapping_type,),
            ).fetchall()
            index = next((i for i, row in enumerate(groups) if str(row['canonical_value']).casefold() == canonical.casefold()), None)
            if index is None:
                raise ValueError(f'The {mapping_type.title()} Mapping group no longer exists.')
            target = index - 1 if direction == 'up' else index + 1
            if target < 0 or target >= len(groups):
                return
            current_row, target_row = groups[index], groups[target]
            temporary_position = max(int(row['position']) for row in groups) + 1
            conn.execute(
                'UPDATE chart_mapping_groups SET position = ? WHERE mapping_type = ? AND canonical_value = ?',
                (temporary_position, mapping_type, current_row['canonical_value']),
            )
            conn.execute(
                'UPDATE chart_mapping_groups SET position = ? WHERE mapping_type = ? AND canonical_value = ?',
                (int(current_row['position']), mapping_type, target_row['canonical_value']),
            )
            conn.execute(
                'UPDATE chart_mapping_groups SET position = ? WHERE mapping_type = ? AND canonical_value = ?',
                (int(target_row['position']), mapping_type, current_row['canonical_value']),
            )

    @staticmethod
    def _compact_chart_mapping_positions(conn: sqlite3.Connection, mapping_type: str) -> None:
        rows = conn.execute(
            'SELECT canonical_value FROM chart_mapping_groups WHERE mapping_type = ? '
            'ORDER BY position, canonical_value COLLATE NOCASE',
            (mapping_type,),
        ).fetchall()
        for position, row in enumerate(rows):
            conn.execute(
                'UPDATE chart_mapping_groups SET position = ? WHERE mapping_type = ? AND canonical_value = ?',
                (position, mapping_type, row['canonical_value']),
            )

    def replace_operator_mapping_groups(self, groups: Iterable[dict[str, Any]]) -> None:
        self._replace_chart_mapping_groups('operator', groups)

    def replace_vendor_mapping_groups(self, groups: Iterable[dict[str, Any]]) -> None:
        self._replace_chart_mapping_groups('vendor', groups)

    def _replace_chart_mapping_groups(self, mapping_type: str, groups: Iterable[dict[str, Any]]) -> None:
        """Replace every mapping group with one validated portable payload."""
        table = self._chart_mapping_table(mapping_type)
        label = mapping_type.title()
        rows: list[tuple[str, str]] = []
        group_rows: list[tuple[str, str, int, str]] = []
        assigned_sources: dict[str, str] = {}
        canonical_labels: set[str] = set()
        for position, group in enumerate(groups):
            if not isinstance(group, dict):
                raise ValueError(f'Each {label} Mapping group must be an object.')
            canonical = str(group.get('canonical') or '').strip()
            if not canonical:
                raise ValueError(f'Every {label} Mapping group requires a canonical label.')
            canonical_key = canonical.casefold()
            if canonical_key in canonical_labels:
                raise ValueError(f'Duplicate canonical {label} Mapping: {canonical}.')
            canonical_labels.add(canonical_key)
            aliases = group.get('aliases')
            if not isinstance(aliases, list):
                raise ValueError(f'{label} Mapping aliases for {canonical} must be a list.')
            color = str(group.get('color') or '#6F42C1').strip().upper()
            if not re.fullmatch(r'#[0-9A-F]{6}', color):
                raise ValueError(f'Colour for {canonical} must use the #RRGGBB format.')
            group_rows.append((mapping_type, canonical, position, color))
            for source in [canonical, *(str(value).strip() for value in aliases)]:
                if not source:
                    continue
                source_key = source.casefold()
                previous = assigned_sources.get(source_key)
                if previous and previous.casefold() != canonical_key:
                    raise ValueError(f'{label} alias {source} belongs to more than one canonical label.')
                if previous:
                    continue
                assigned_sources[source_key] = canonical
                rows.append((source, canonical))
        with self.connection() as conn:
            conn.execute(f'DELETE FROM {table}')
            conn.execute('DELETE FROM chart_mapping_groups WHERE mapping_type = ?', (mapping_type,))
            conn.executemany(
                'INSERT INTO chart_mapping_groups (mapping_type, canonical_value, position, color) '
                'VALUES (?, ?, ?, ?)', group_rows,
            )
            conn.executemany(
                f'INSERT INTO {table} (source_value, canonical_value) VALUES (?, ?)', rows,
            )

    def invalidate_cdr_normalization(self) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE dataset_profiles SET normalization_version = 0, updated_at = ? "
                "WHERE dataset_kind IN ('data', 'voice', 'speech') AND status = 'ready'",
                (local_now_iso(),),
            )

    def replace_calculated_dimensions(
        self, definitions: list[dict[str, Any]], *, materialization_state: str = '1',
    ) -> None:
        timestamp = local_now_iso()
        with self.connection() as conn:
            conn.execute('DELETE FROM autocalculated_fields')
            conn.executemany(
                'INSERT INTO autocalculated_fields (name, definition_json, position, updated_at) VALUES (?, ?, ?, ?)',
                [
                    (str(item['name']), json.dumps(item, ensure_ascii=False), position, timestamp)
                    for position, item in enumerate(definitions)
                ],
            )
            conn.execute(
                'INSERT INTO workspace_state (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                ('calculated_dimensions_initialized', '1'),
            )
            # Persist the requested materialization state in the same
            # transaction as the definitions. This keeps both deferred saves
            # and queued rebuilds crash-safe without a second Workspace write
            # racing a materialization worker.
            conn.execute(
                'INSERT INTO workspace_state (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                ('calculated_dimensions_need_materialization', materialization_state),
            )

    def drop_reporting_table(self, dataset_kind: str) -> None:
        table_name = self.reporting_rows_table_name(dataset_kind)
        with self.connection() as conn:
            conn.execute(f'DROP TABLE IF EXISTS {self._quote_identifier(table_name)}')

    def replace_dataset_rows(self, dataset_id: int, df: pd.DataFrame) -> None:
        table_name = self.dataset_rows_table_name(dataset_id)
        safe_df = self._sqlite_safe_frame(df)
        with self.connection() as conn:
            # Reserve the writer before dropping the old materialisation.  A
            # background refresh can otherwise create the same table during
            # pandas' replace path between its DROP and CREATE statements.
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(f"DROP TABLE IF EXISTS {self._quote_identifier(table_name)}")
            # The table has just been removed under the writer lock.  Appending
            # makes pandas create it without issuing a second DROP/commit,
            # leaving no window for another connection to recreate it first.
            safe_df.to_sql(table_name, conn, if_exists='append', index=False)
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
        return column_identity(column)

    REPORTING_CORE_COLUMNS = (
        'source_sheet', *MAIN_CDR_FIELDS, 'vendor', 'Sample_RAT_A',
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
        # SQLite itself compares identifiers case-insensitively. Keep that
        # guard in addition to the semantic identity map: a source can retain
        # punctuation that distinguishes two logical aliases while still
        # colliding with a physical column name already created by an earlier
        # dataset.
        target_sql_names = {str(column).casefold() for column in target_columns}
        source_lookup = {self._column_identity(column): column for column in source_columns}
        for requested in requested_columns:
            source = source_lookup.get(self._column_identity(requested))
            source_key = self._column_identity(source) if source else ''
            if (not source or source_key in {'datasetid', 'sourcerowid'}
                    or source_key in target_lookup or str(source).casefold() in target_sql_names):
                continue
            # A reporting projection can be requested by concurrent preview
            # preparations. Refresh the physical schema immediately before
            # adding a column because SQLite treats names case-insensitively.
            # This also covers legacy tables containing an equivalent heading
            # with a different case or separator.
            current_columns = self._table_columns(conn, table_name)
            current_sql_names = {str(column).casefold() for column in current_columns}
            current_lookup = {self._column_identity(column): column for column in current_columns}
            if source_key in current_lookup or str(source).casefold() in current_sql_names:
                target_columns = current_columns
                target_lookup = current_lookup
                target_sql_names = current_sql_names
                continue
            try:
                conn.execute(f"ALTER TABLE {self._quote_identifier(table_name)} ADD COLUMN {self._quote_identifier(source)}")
            except sqlite3.OperationalError as exc:
                # Another preview or materialization can add this projection
                # after the schema probe above. SQLite then rejects the same
                # ALTER TABLE; refresh the physical metadata and continue.
                if 'duplicate column name' not in str(exc).casefold():
                    raise
                target_columns = self._table_columns(conn, table_name)
                target_lookup = {self._column_identity(column): column for column in target_columns}
                target_sql_names = {str(column).casefold() for column in target_columns}
            else:
                target_columns.append(source)
                target_lookup[source_key] = source
                target_sql_names.add(str(source).casefold())
        return target_columns

    def replace_reporting_rows(self, dataset_id: int, dataset_kind: str, df: pd.DataFrame) -> None:
        """Replace one CDR's rows in the shared, queryable reporting table.

        Only core reporting fields are stored at ingestion. Template-specific
        columns are materialised on demand from the individual CDR table.
        """
        table_name = self.reporting_rows_table_name(dataset_kind)
        safe_df = self._sqlite_safe_frame(df)
        with self.connection() as conn:
            # A combined-table recreation may run concurrently with dataset
            # ingestion. Hold the writer lock while this operation creates or
            # extends its reporting table, so a DROP TABLE cannot land between
            # the schema probe and a following ALTER or INSERT.
            conn.execute('BEGIN IMMEDIATE')
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
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self._quote_identifier(self._index_name(table_name, 'dataset_source_row', 'lookup'))} "
            f"ON {quoted_table} (dataset_id, source_row_id)"
        )
        self._create_dataset_row_indexes(conn, table_name, columns)
        event_time_column = self._resolve_dataset_row_column_name(set(columns), 'event_start_time')
        if event_time_column:
            quoted_column = self._quote_identifier(event_time_column)
            quoted_index = self._quote_identifier(self._index_name(table_name, 'dataset_event_time', 'date'))
            # Dashboard cache validation obtains the oldest and newest date
            # for a selected Dataset Universe.  Keeping dataset_id first lets
            # SQLite restrict that MIN/MAX query to the selected CDRs.
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {quoted_index} "
                f"ON {quoted_table} (dataset_id, date(CAST({quoted_column} AS TEXT)))"
            )

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

    def dataset_row_count(self, dataset_id: int) -> int:
        table_name = self.dataset_rows_table_name(dataset_id)
        with self.connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
            ).fetchone()
            if not exists:
                return 0
            return int(conn.execute(
                f"SELECT COUNT(*) AS count FROM {self._quote_identifier(table_name)}"
            ).fetchone()['count'] or 0)

    def resolve_reporting_row_column_name(self, dataset_kind: str, requested: str) -> str | None:
        columns = set(self.list_reporting_row_columns(dataset_kind))
        return self._resolve_dataset_row_column_name(columns, requested) if columns else None

    def list_distinct_reporting_row_values(
        self, dataset_kind: str, column: str, limit: int = 200,
    ) -> list[str]:
        table_name = self.reporting_rows_table_name(dataset_kind)
        resolved = self.resolve_reporting_row_column_name(dataset_kind, column)
        if not resolved:
            return []
        quoted_column = self._quote_identifier(resolved)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT TRIM(CAST({quoted_column} AS TEXT)) AS value "
                f"FROM {self._quote_identifier(table_name)} "
                f"WHERE {quoted_column} IS NOT NULL AND TRIM(CAST({quoted_column} AS TEXT)) <> '' "
                "ORDER BY LOWER(TRIM(CAST(value AS TEXT))) LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [str(row['value']).strip() for row in rows if str(row['value']).strip()]

    def load_reporting_preview_rows(
        self, dataset_kind: str, columns: list[str], filters: dict[str, Any], row_limit: int,
    ) -> pd.DataFrame:
        table_name = self.reporting_rows_table_name(dataset_kind)
        existing_columns = set(self.list_reporting_row_columns(dataset_kind))
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
            resolved = self._resolve_dataset_row_column_name(existing_columns, key)
            values = value if isinstance(value, (list, tuple, set)) else [value]
            normalized = [str(item).strip().lower() for item in values if str(item).strip()]
            if not resolved or not normalized:
                continue
            placeholders = ', '.join('?' for _value in normalized)
            where_clauses.append(
                f"LOWER(TRIM(CAST({self._quote_identifier(resolved)} AS TEXT))) IN ({placeholders})"
            )
            params.extend(normalized)
        select_clause = ', '.join(
            f"{self._quote_identifier(actual)} AS {self._quote_identifier(requested)}"
            if actual != requested else self._quote_identifier(actual)
            for requested, actual in selected_columns
        )
        query = f"SELECT {select_clause} FROM {self._quote_identifier(table_name)}"
        if where_clauses:
            query += f" WHERE {' AND '.join(where_clauses)}"
        query += " LIMIT ?"
        params.append(max(1, int(row_limit)))
        with self.connection() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def _load_table_preview_page(
        self, table_name: str, existing_columns: set[str], columns: list[str],
        filters: dict[str, list[str]], page: int, page_size: int,
        filter_column: str | None = None,
    ) -> tuple[pd.DataFrame, int, list[str] | None]:
        selected_columns: list[tuple[str, str]] = []
        for column in columns:
            resolved = self._resolve_dataset_row_column_name(existing_columns, column)
            if resolved:
                selected_columns.append((column, resolved))
        if not selected_columns:
            return pd.DataFrame(), 0, [] if filter_column else None

        where_clauses: list[str] = []
        params: list[Any] = []
        for key, raw_values in filters.items():
            resolved = self._resolve_dataset_row_column_name(existing_columns, key)
            if not resolved:
                continue
            values = [str(value).strip().lower() for value in raw_values]
            if not values:
                where_clauses.append('0 = 1')
                continue
            placeholders = ', '.join('?' for _ in values)
            where_clauses.append(
                f"LOWER(COALESCE(TRIM(CAST({self._quote_identifier(resolved)} AS TEXT)), '')) IN ({placeholders})"
            )
            params.extend(values)

        quoted_table = self._quote_identifier(table_name)
        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
        with self.connection() as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) AS count FROM {quoted_table}{where_sql}", params,
            ).fetchone()['count'] or 0)
            select_clause = ', '.join(
                f"{self._quote_identifier(actual)} AS {self._quote_identifier(requested)}"
                if actual != requested else self._quote_identifier(actual)
                for requested, actual in selected_columns
            )
            query_params = [*params, max(1, int(page_size)), max(0, int(page)) * max(1, int(page_size))]
            frame = pd.read_sql_query(
                f"SELECT {select_clause} FROM {quoted_table}{where_sql} ORDER BY rowid LIMIT ? OFFSET ?",
                conn,
                params=query_params,
            )
            filter_values: list[str] | None = None
            resolved_filter_column = (
                self._resolve_dataset_row_column_name(existing_columns, filter_column)
                if filter_column else None
            )
            if resolved_filter_column:
                quoted_column = self._quote_identifier(resolved_filter_column)
                facet_clauses: list[str] = []
                facet_params: list[Any] = []
                for key, raw_values in filters.items():
                    resolved = self._resolve_dataset_row_column_name(existing_columns, key)
                    if not resolved or resolved == resolved_filter_column:
                        continue
                    values = [str(value).strip().lower() for value in raw_values]
                    if not values:
                        facet_clauses.append('0 = 1')
                        continue
                    placeholders = ', '.join('?' for _ in values)
                    facet_clauses.append(
                        f"LOWER(COALESCE(TRIM(CAST({self._quote_identifier(resolved)} AS TEXT)), '')) "
                        f"IN ({placeholders})"
                    )
                    facet_params.extend(values)
                facet_where = f" WHERE {' AND '.join(facet_clauses)}" if facet_clauses else ''
                rows = conn.execute(
                    f"SELECT DISTINCT COALESCE(TRIM(CAST({quoted_column} AS TEXT)), '') AS value "
                    f"FROM {quoted_table}{facet_where} ORDER BY value COLLATE NOCASE",
                    facet_params,
                ).fetchall()
                filter_values = [str(row['value'] or '') for row in rows]
            elif filter_column:
                filter_values = []
        return frame, total, filter_values

    def load_dataset_preview_page(
        self, dataset_id: int, columns: list[str], filters: dict[str, list[str]],
        page: int, page_size: int, filter_column: str | None = None,
    ) -> tuple[pd.DataFrame, int, list[str] | None]:
        return self._load_table_preview_page(
            self.dataset_rows_table_name(dataset_id), set(self.list_dataset_row_columns(dataset_id)),
            columns, filters, page, page_size, filter_column,
        )

    def load_reporting_preview_page(
        self, dataset_kind: str, columns: list[str], filters: dict[str, list[str]],
        page: int, page_size: int, filter_column: str | None = None,
    ) -> tuple[pd.DataFrame, int, list[str] | None]:
        return self._load_table_preview_page(
            self.reporting_rows_table_name(dataset_kind), set(self.list_reporting_row_columns(dataset_kind)),
            columns, filters, page, page_size, filter_column,
        )

    def _stream_table_preview_csv(
        self, table_name: str, existing_columns: set[str], columns: list[str],
        filters: dict[str, list[str]],
    ) -> Iterator[str]:
        """Stream all preview rows as CSV without materializing the dataset in memory."""
        selected_columns = [
            (column, self._resolve_dataset_row_column_name(existing_columns, column))
            for column in columns
        ]
        where_clauses: list[str] = []
        params: list[Any] = []
        for key, raw_values in filters.items():
            resolved = self._resolve_dataset_row_column_name(existing_columns, key)
            if not resolved:
                continue
            values = [str(value).strip().lower() for value in raw_values]
            if not values:
                where_clauses.append('0 = 1')
                continue
            placeholders = ', '.join('?' for _ in values)
            where_clauses.append(
                f"LOWER(COALESCE(TRIM(CAST({self._quote_identifier(resolved)} AS TEXT)), '')) IN ({placeholders})"
            )
            params.extend(values)
        select_clause = ', '.join(
            f"{self._quote_identifier(actual)} AS {self._quote_identifier(requested)}"
            if actual else f"'' AS {self._quote_identifier(requested)}"
            for requested, actual in selected_columns
        )
        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(columns)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        with self.connection() as conn:
            cursor = conn.execute(
                f"SELECT {select_clause} FROM {self._quote_identifier(table_name)}{where_sql} ORDER BY rowid",
                params,
            )
            while rows := cursor.fetchmany(1000):
                writer.writerows(tuple('' if value is None else value for value in row) for row in rows)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

    def stream_dataset_preview_csv(
        self, dataset_id: int, columns: list[str], filters: dict[str, list[str]],
    ) -> Iterator[str]:
        return self._stream_table_preview_csv(
            self.dataset_rows_table_name(dataset_id), set(self.list_dataset_row_columns(dataset_id)), columns, filters,
        )

    def stream_reporting_preview_csv(
        self, dataset_kind: str, columns: list[str], filters: dict[str, list[str]],
    ) -> Iterator[str]:
        return self._stream_table_preview_csv(
            self.reporting_rows_table_name(dataset_kind), set(self.list_reporting_row_columns(dataset_kind)), columns, filters,
        )

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

    def reporting_row_count(self, dataset_kind: str, dataset_id: int | None = None) -> int:
        table_name = self.reporting_rows_table_name(dataset_kind)
        with self.connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
            ).fetchone()
            if not exists:
                return 0
            if dataset_id is None:
                row = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {self._quote_identifier(table_name)}"
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {self._quote_identifier(table_name)} WHERE dataset_id = ?",
                    (int(dataset_id),),
                ).fetchone()
            return int(row['count'] or 0)

    def copy_dataset_rows_to_reporting(self, dataset_id: int, dataset_kind: str, columns: list[str] | None = None) -> bool:
        """Backfill a shared table entirely inside SQLite, without pandas RAM use."""
        source_table = self.dataset_rows_table_name(dataset_id)
        target_table = self.reporting_rows_table_name(dataset_kind)
        with self.connection() as conn:
            # See replace_reporting_rows: the complete schema-and-copy step
            # must be atomic relative to a background combined-table rebuild.
            conn.execute('BEGIN IMMEDIATE')
            source_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (source_table,)
            ).fetchone()
            if not source_exists:
                return False
            target_table, target_columns = self._ensure_reporting_table(conn, dataset_kind)
            quoted_target = self._quote_identifier(target_table)
            source_columns = self._table_columns(conn, source_table)
            desired = list(dict.fromkeys([*self.REPORTING_CORE_COLUMNS, *(columns or [])]))
            previous_columns = {self._column_identity(column) for column in target_columns}
            source_lookup = {self._column_identity(column): column for column in source_columns}
            target_columns = self._ensure_reporting_columns(conn, target_table, source_columns, desired)
            # Schema changes need the writer reservation above, but the
            # following presence checks can scan hundreds of thousands of
            # rows. Release the writer before those read-only scans so other
            # background jobs can record progress and interactive writes do
            # not queue behind the complete validation pass.
            conn.commit()
            existing_rows = conn.execute(
                f"SELECT 1 FROM {quoted_target} WHERE dataset_id = ? LIMIT 1", (dataset_id,)
            ).fetchone()
            # A column can already exist in the shared table because another
            # dataset introduced it, while this dataset's older cached rows
            # still contain only NULL for that column. Validate every field
            # requested by the chart, not just derived dimensions.
            target_lookup = {self._column_identity(column): column for column in target_columns}
            columns_to_refresh: list[tuple[str, str]] = []
            if existing_rows:
                existing_pairs: list[tuple[str, str]] = []
                for requested in desired:
                    identity = self._column_identity(requested)
                    if identity not in source_lookup or identity not in target_lookup:
                        continue
                    source = source_lookup[identity]
                    target = target_lookup[identity]
                    if identity not in previous_columns:
                        columns_to_refresh.append((target, source))
                        continue
                    existing_pairs.append((target, source))
                # Checking each requested field separately made an all-NULL
                # field scan the same large CDR once per column. Inspect every
                # existing field in one pass through the selected dataset and,
                # only when needed, one pass through its source table.
                if existing_pairs:
                    target_presence = conn.execute(
                        f"SELECT {', '.join(f'MAX(CASE WHEN {self._quote_identifier(target)} IS NOT NULL THEN 1 ELSE 0 END) AS present_{index}' for index, (target, _source) in enumerate(existing_pairs))} "
                        f"FROM {quoted_target} WHERE dataset_id = ?",
                        (dataset_id,),
                    ).fetchone()
                    missing_pairs = [
                        pair for index, pair in enumerate(existing_pairs)
                        if not int(target_presence[f'present_{index}'] or 0)
                    ]
                    if missing_pairs:
                        source_presence = conn.execute(
                            f"SELECT {', '.join(f'MAX(CASE WHEN {self._quote_identifier(source)} IS NOT NULL THEN 1 ELSE 0 END) AS present_{index}' for index, (_target, source) in enumerate(missing_pairs))} "
                            f"FROM {self._quote_identifier(source_table)}"
                        ).fetchone()
                        columns_to_refresh.extend(
                            pair for index, pair in enumerate(missing_pairs)
                            if int(source_presence[f'present_{index}'] or 0)
                        )
                if not columns_to_refresh:
                    return False
                # Adding a template field used to delete and recreate every
                # shared CDR row, including columns that were already ready.
                # Fill only the newly required or incomplete columns by their
                # stable source-row id, keeping large dashboard preparations
                # proportional to the added data rather than table width.
                conn.execute('BEGIN IMMEDIATE')
                for target, source in dict.fromkeys(columns_to_refresh):
                    conn.execute(
                        f"UPDATE {quoted_target} SET {self._quote_identifier(target)} = "
                        f"(SELECT {self._quote_identifier(source)} FROM {self._quote_identifier(source_table)} "
                        f"WHERE {self._quote_identifier(source_table)}.rowid = {quoted_target}.source_row_id) "
                        "WHERE dataset_id = ?",
                        (dataset_id,),
                    )
                self._create_reporting_row_indexes(conn, target_table, target_columns)
                return True
            conn.execute('BEGIN IMMEDIATE')
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
            return True

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

    def load_filtered_reporting_rows(
        self, dataset_kind: str, columns: list[str], where_sql: str, parameters: list[Any],
    ) -> pd.DataFrame:
        """Load a SQL-filtered projection from one combined CDR table."""
        table_name = self.reporting_rows_table_name(dataset_kind)
        existing_columns = set(self.list_reporting_row_columns(dataset_kind))
        selected_columns: list[tuple[str, str]] = []
        for column in columns:
            resolved = self._resolve_dataset_row_column_name(existing_columns, column)
            if resolved and all(actual != resolved for _requested, actual in selected_columns):
                selected_columns.append((column, resolved))
        if not selected_columns:
            return pd.DataFrame()
        select_clause = ', '.join(
            f"{self._quote_identifier(actual)} AS {self._quote_identifier(requested)}"
            if actual != requested else self._quote_identifier(actual)
            for requested, actual in selected_columns
        )
        query = f"SELECT {select_clause} FROM {self._quote_identifier(table_name)} WHERE {where_sql}"
        with self.connection() as conn:
            return pd.read_sql_query(query, conn, params=parameters)

    def _create_dataset_row_indexes(self, conn: sqlite3.Connection, table_name: str, columns: list[str]) -> None:
        indexed_dimensions = [
            'market', 'period', 'operator', 'vendor', 'test_name', 'region', 'city',
            'g_level_2', 'g_level_4', 'campaign', 'rat', 'rat_a', 'sample_rat_a',
            'session_type', 'direction', 'technology_primary', 'source_sheet',
            'call_status', 'status',
        ]
        for requested_name in indexed_dimensions:
            actual_name = self._resolve_dataset_row_column_name(set(columns), requested_name)
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

        event_time_column = self._resolve_dataset_row_column_name(set(columns), 'event_start_time')
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
        if resolved_event_time and not ignore_event_time_filtering():
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
            f"SUM(CASE WHEN {self._quote_identifier(metric)} IS NOT NULL "
            f"AND TRIM(CAST({self._quote_identifier(metric)} AS TEXT)) != '' "
            f"THEN 1 ELSE 0 END) AS {self._quote_identifier(alias)}"
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

    def replace_dataset_source_columns(self, dataset_id: int, columns: Iterable[object]) -> None:
        """Persist the physical source headers captured during dataset ingestion."""
        unique_columns = list(dict.fromkeys(str(column) for column in columns))
        with self.connection() as conn:
            conn.execute('DELETE FROM dataset_source_columns WHERE dataset_id = ?', (dataset_id,))
            conn.executemany(
                """
                INSERT INTO dataset_source_columns (dataset_id, position, column_name, column_identity)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (dataset_id, position, column, self._column_identity(column))
                    for position, column in enumerate(unique_columns)
                ],
            )

    def list_dataset_source_columns(self, dataset_id: int) -> list[str]:
        """Return physical source headers without reopening the uploaded file."""
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT column_name FROM dataset_source_columns WHERE dataset_id = ? ORDER BY position',
                (dataset_id,),
            ).fetchall()
        return [str(row['column_name']) for row in rows]

    def get_dataset(self, dataset_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT d.id, d.file_name, d.stored_path, d.uploaded_by, d.uploaded_at,
                       p.status, p.progress, p.normalization_version, p.vendor_mapping_applied, p.vendor_values_complete, p.region_mapping_applied, p.region_mapping_dataset_id, p.dataset_kind, p.row_count, p.column_count,
                       p.default_metric, p.default_aggregation, p.available_metrics_json,
                       p.available_aggregations_json, p.filter_options_json, p.summary_json,
                       p.kpis_json, p.last_error, p.processing_started_at, p.processed_at,
                       p.processing_options_json, p.updated_at
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
                           p.status, p.progress, p.normalization_version, p.vendor_mapping_applied, p.vendor_values_complete, p.region_mapping_applied, p.region_mapping_dataset_id, p.dataset_kind, p.row_count, p.column_count,
                           p.default_metric, p.default_aggregation, p.available_metrics_json,
                           p.available_aggregations_json, p.filter_options_json, p.summary_json,
                           p.kpis_json, p.last_error, p.processing_started_at, p.processed_at,
                           p.processing_options_json, p.updated_at
                    FROM datasets d
                    LEFT JOIN dataset_profiles p ON p.dataset_id = d.id
                    ORDER BY d.uploaded_at DESC, d.id DESC
                    """
                ).fetchall()
            )

    @staticmethod
    def _remap_dataset_ids_in_json(value: Any, id_mapping: dict[int, int], *, dataset_scope: bool = False) -> Any:
        """Rewrite dataset identifiers in persisted JSON without touching unrelated numbers."""
        if isinstance(value, dict):
            remapped: dict[str, Any] = {}
            for key, child in value.items():
                normalized_key = str(key).casefold()
                child_scope = dataset_scope or normalized_key in {
                    'dataset_id', 'dataset_ids', 'dataset_ids_by_source', 'datasets',
                    'data_dataset_id', 'voice_dataset_id', 'speech_dataset_id',
                    'mapping_dataset_id', 'vodafone_mapping_dataset_id', 'three_mapping_dataset_id',
                } or normalized_key.endswith('_dataset_id')
                remapped[key] = Repository._remap_dataset_ids_in_json(
                    child, id_mapping, dataset_scope=child_scope,
                )
            return remapped
        if isinstance(value, list):
            return [
                Repository._remap_dataset_ids_in_json(item, id_mapping, dataset_scope=dataset_scope)
                for item in value
            ]
        if not dataset_scope or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return id_mapping.get(value, value)
        if isinstance(value, str) and value.strip().isdigit():
            mapped = id_mapping.get(int(value.strip()))
            return str(mapped) if mapped is not None else value
        return value

    def reorder_dataset_ids(self, ordered_dataset_ids: list[int]) -> dict[int, int]:
        """Renumber datasets to match the requested order and propagate every persisted reference."""
        requested_ids = [int(value) for value in ordered_dataset_ids]
        if len(requested_ids) != len(set(requested_ids)):
            raise ValueError('Dataset order contains duplicate IDs.')

        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current_rows = conn.execute('SELECT id FROM datasets ORDER BY id').fetchall()
            current_ids = [int(row['id']) for row in current_rows]
            if set(requested_ids) != set(current_ids) or len(requested_ids) != len(current_ids):
                raise ValueError('Dataset order must contain every current dataset exactly once.')
            if not current_ids:
                return {}
            busy = conn.execute(
                "SELECT 1 FROM dataset_profiles WHERE status IN ('queued', 'processing') LIMIT 1"
            ).fetchone()
            if busy:
                raise ValueError('Stop or wait for every queued or processing dataset before reordering IDs.')

            id_mapping = {old_id: position for position, old_id in enumerate(requested_ids, start=1)}
            changed_mapping = {
                old_id: new_id for old_id, new_id in id_mapping.items() if old_id != new_id
            }
            if not changed_mapping:
                return id_mapping

            max_id = max(current_ids)
            temporary_ids = {
                old_id: -(max_id + position)
                for position, old_id in enumerate(changed_mapping, start=1)
            }
            conn.execute('PRAGMA defer_foreign_keys = ON')

            table_names = [
                str(row['name']) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            dataset_row_tables = {
                int(table_name.removeprefix('dataset_rows_')): table_name
                for table_name in table_names
                if table_name.removeprefix('dataset_rows_').isdigit()
                and int(table_name.removeprefix('dataset_rows_')) in changed_mapping
            }
            temporary_table_names: dict[int, str] = {}
            for old_id, table_name in dataset_row_tables.items():
                temporary_name = f'__dataset_rows_reorder_{old_id}'
                conn.execute(f'DROP TABLE IF EXISTS {self._quote_identifier(temporary_name)}')
                conn.execute(
                    f'ALTER TABLE {self._quote_identifier(table_name)} '
                    f'RENAME TO {self._quote_identifier(temporary_name)}'
                )
                temporary_table_names[old_id] = temporary_name

            reference_columns: list[tuple[str, str, bool]] = []
            for table_name in table_names:
                if table_name == 'datasets' or table_name in dataset_row_tables.values():
                    continue
                metadata = conn.execute(
                    f'PRAGMA table_info({self._quote_identifier(table_name)})'
                ).fetchall()
                unique_columns: set[str] = {
                    str(column['name']) for column in metadata if int(column['pk']) > 0
                }
                for index in conn.execute(
                    f'PRAGMA index_list({self._quote_identifier(table_name)})'
                ).fetchall():
                    if not int(index['unique']):
                        continue
                    unique_columns.update(
                        str(column['name']) for column in conn.execute(
                            f'PRAGMA index_info({self._quote_identifier(str(index["name"]))})'
                        ).fetchall()
                        if column['name'] is not None
                    )
                for column in metadata:
                    column_name = str(column['name'])
                    normalized = column_name.casefold()
                    if normalized == 'dataset_id' or normalized.endswith('_dataset_id'):
                        reference_columns.append((table_name, column_name, column_name in unique_columns))

            for table_name, column_name, requires_temporary_id in reference_columns:
                if not requires_temporary_id:
                    continue
                quoted_table = self._quote_identifier(table_name)
                quoted_column = self._quote_identifier(column_name)
                for old_id, temporary_id in temporary_ids.items():
                    conn.execute(
                        f'UPDATE {quoted_table} SET {quoted_column} = ? WHERE {quoted_column} = ?',
                        (temporary_id, old_id),
                    )
            for table_name, column_name, requires_temporary_id in reference_columns:
                if requires_temporary_id:
                    continue
                quoted_table = self._quote_identifier(table_name)
                quoted_column = self._quote_identifier(column_name)
                cases = ' '.join('WHEN ? THEN ?' for _ in changed_mapping)
                placeholders = ', '.join('?' for _ in changed_mapping)
                case_parameters = [
                    value
                    for old_id, new_id in changed_mapping.items()
                    for value in (old_id, new_id)
                ]
                conn.execute(
                    f'UPDATE {quoted_table} SET {quoted_column} = '
                    f'CASE {quoted_column} {cases} ELSE {quoted_column} END '
                    f'WHERE {quoted_column} IN ({placeholders})',
                    (*case_parameters, *changed_mapping.keys()),
                )
            for old_id, temporary_id in temporary_ids.items():
                conn.execute('UPDATE datasets SET id = ? WHERE id = ?', (temporary_id, old_id))
            for old_id, new_id in changed_mapping.items():
                conn.execute('UPDATE datasets SET id = ? WHERE id = ?', (new_id, temporary_ids[old_id]))
            for table_name, column_name, requires_temporary_id in reference_columns:
                if not requires_temporary_id:
                    continue
                quoted_table = self._quote_identifier(table_name)
                quoted_column = self._quote_identifier(column_name)
                for old_id, new_id in changed_mapping.items():
                    conn.execute(
                        f'UPDATE {quoted_table} SET {quoted_column} = ? WHERE {quoted_column} = ?',
                        (new_id, temporary_ids[old_id]),
                    )

            for old_id, temporary_name in temporary_table_names.items():
                new_name = self.dataset_rows_table_name(id_mapping[old_id])
                conn.execute(
                    f'ALTER TABLE {self._quote_identifier(temporary_name)} '
                    f'RENAME TO {self._quote_identifier(new_name)}'
                )

            json_columns = {
                'dataset_profiles': [('processing_options_json', False)],
                'generated_jobs': [('dataset_ids_json', True)],
                'audit_logs': [('details', False)],
                'workspace_state': [('value', False)],
            }
            for table_name, columns in json_columns.items():
                if table_name not in table_names:
                    continue
                available_columns = {
                    str(column['name']) for column in conn.execute(
                        f'PRAGMA table_info({self._quote_identifier(table_name)})'
                    ).fetchall()
                }
                for column_name, dataset_scope in columns:
                    if column_name not in available_columns:
                        continue
                    rows = conn.execute(
                        f'SELECT rowid AS __rowid__, {self._quote_identifier(column_name)} AS payload '
                        f'FROM {self._quote_identifier(table_name)}'
                    ).fetchall()
                    for row in rows:
                        try:
                            payload = json.loads(str(row['payload'] or ''))
                        except (TypeError, ValueError):
                            continue
                        remapped = self._remap_dataset_ids_in_json(
                            payload, changed_mapping, dataset_scope=dataset_scope,
                        )
                        if remapped != payload:
                            conn.execute(
                                f'UPDATE {self._quote_identifier(table_name)} '
                                f'SET {self._quote_identifier(column_name)} = ? WHERE rowid = ?',
                                (json.dumps(remapped, ensure_ascii=False), int(row['__rowid__'])),
                            )

            if 'dashboard_filter_selections' in table_names:
                conn.execute('DELETE FROM dashboard_filter_selections')
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'datasets'")
            conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('datasets', ?)", (len(current_ids),))
            foreign_key_errors = conn.execute('PRAGMA foreign_key_check').fetchall()
            if foreign_key_errors:
                raise ValueError('Dataset IDs could not be reordered without breaking database references.')
            return id_mapping

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

    def try_add_log(self, username: str, action: str, details: str, *, timeout_seconds: float = 0.25) -> bool:
        """Write non-critical diagnostics without waiting behind a long-running writer."""
        try:
            with closing(sqlite3.connect(self.db_path, timeout=timeout_seconds)) as conn, conn:
                conn.execute(f"PRAGMA busy_timeout = {max(1, int(timeout_seconds * 1000))}")
                conn.execute(
                    "INSERT INTO audit_logs (username, action, details, created_at) VALUES (?, ?, ?, ?)",
                    (username, action, details, local_now_iso()),
                )
            return True
        except sqlite3.OperationalError:
            return False

    def add_report_run(self, *, report_type: str, technology: str, scope: str, data_dataset_id: int,
                       voice_dataset_id: int, speech_dataset_id: int, vodafone_mapping_dataset_id: int | None,
                       three_mapping_dataset_id: int | None,
                       template_name: str, output_file: str, created_by: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO generated_jobs (
                    job_type, report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                    mapping_dataset_id, vodafone_mapping_dataset_id, three_mapping_dataset_id, template_name, output_file, created_by
                ) VALUES ('report', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                 None, vodafone_mapping_dataset_id, three_mapping_dataset_id, template_name, output_file, created_by),
            )

    def list_report_runs(self, limit: int | None = 50) -> list[sqlite3.Row]:
        with self.connection() as conn:
            if limit is None:
                return list(conn.execute("SELECT * FROM generated_jobs WHERE job_type = 'report' ORDER BY id DESC").fetchall())
            return list(conn.execute(
                "SELECT * FROM generated_jobs WHERE job_type = 'report' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall())

    def create_report_job(
        self, *, report_type: str, technology: str, scope: str,
        data_dataset_id: int | None, voice_dataset_id: int | None, speech_dataset_id: int | None,
        dataset_ids: dict[str, list[int]], dataset_names: dict[str, list[str]],
        slide_count: int, template_name: str, output_file: str, output_path: Path,
        created_by: str, generate_tooltips: bool = True,
    ) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO generated_jobs (
                    job_type, report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                    template_name, output_file, created_by, created_at, dataset_ids_json, dataset_names_json,
                    slide_count, status, progress, output_path, generate_tooltips, updated_at
                ) VALUES ('report', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?)
                """,
                (
                    report_type, technology, scope, data_dataset_id, voice_dataset_id, speech_dataset_id,
                    template_name, output_file, created_by, local_now_iso(), json.dumps(dataset_ids), json.dumps(dataset_names),
                    slide_count, str(output_path), int(generate_tooltips), local_now_iso(),
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
            if status == 'processing':
                assignments.append('started_at = COALESCE(started_at, ?)')
                values.append(local_now_iso())
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
            conn.execute(f"UPDATE generated_jobs SET {', '.join(assignments)} WHERE id = ? AND job_type = 'report' AND status <> 'stopped'", values)

    def stop_report_job(self, report_id: int) -> bool:
        """Stop a queued or running report job without deleting its audit row."""
        now = local_now_iso()
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE generated_jobs SET status = 'stopped', last_error = '', updated_at = ?, finished_at = ? "
                "WHERE id = ? AND job_type = 'report' AND status IN ('queued', 'processing')",
                (now, now, report_id),
            )
            return cursor.rowcount == 1

    def retry_report_job(self, report_id: int) -> bool:
        """Reset a completed, failed or stopped report job for reuse."""
        now = local_now_iso()
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE generated_jobs SET status = 'queued', progress = 0, last_error = '', finished_at = NULL, "
                "started_at = NULL, created_at = ?, updated_at = ? "
                "WHERE id = ? AND job_type = 'report' AND status IN ('failed', 'stopped', 'ready')",
                (now, now, report_id),
            )
            return cursor.rowcount == 1

    def fail_interrupted_background_jobs(self, *, fail_datasets: bool = True) -> tuple[list[int], list[int]]:
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
                "SELECT id FROM generated_jobs WHERE job_type = 'report' AND status IN ('queued', 'processing')"
            ).fetchall() if 'generated_jobs' in tables else []
            dataset_ids = [int(row['dataset_id']) for row in dataset_rows] if fail_datasets else []
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
                    f"UPDATE generated_jobs SET status = 'failed', progress = 100, last_error = ?, updated_at = ?, finished_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (message, now, now, *report_ids),
                )
        return dataset_ids, report_ids

    def get_report_run(self, report_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM generated_jobs WHERE id = ? AND job_type = 'report'", (report_id,)).fetchone()

    def delete_report_run(self, report_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            report = conn.execute("SELECT * FROM generated_jobs WHERE id = ? AND job_type = 'report'", (report_id,)).fetchone()
            if report:
                conn.execute("DELETE FROM generated_jobs WHERE id = ? AND job_type = 'report'", (report_id,))
            return report

    def create_report_chart_job(
        self, *, technology: str, scope: str, dataset_ids: dict[str, list[int]],
        dataset_names: dict[str, list[str]], template_name: str, created_by: str, generate_tooltips: bool = True,
    ) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO generated_jobs (
                    job_type, technology, scope, dataset_ids_json, dataset_names_json, template_name,
                    created_by, created_at, status, progress, generate_tooltips, updated_at
                ) VALUES ('chart_set', ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
                """,
                (
                    technology, scope, json.dumps(dataset_ids), json.dumps(dataset_names), template_name,
                    created_by, local_now_iso(), int(generate_tooltips), local_now_iso(),
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
            if status == 'processing':
                assignments.append('started_at = COALESCE(started_at, ?)')
                values.append(local_now_iso())
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
            conn.execute(f"UPDATE generated_jobs SET {', '.join(assignments)} WHERE id = ? AND job_type = 'chart_set' AND status <> 'stopped'", values)

    def stop_report_chart_job(self, job_id: int) -> bool:
        """Stop a queued or running Chart Set job."""
        now = local_now_iso()
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE generated_jobs SET status = 'stopped', last_error = '', updated_at = ?, finished_at = ? "
                "WHERE id = ? AND job_type = 'chart_set' AND status IN ('queued', 'processing')",
                (now, now, job_id),
            )
            return cursor.rowcount == 1

    def retry_report_chart_job(self, job_id: int) -> bool:
        """Reset one failed, stopped or completed Chart Set job for reuse."""
        now = local_now_iso()
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE generated_jobs SET status = 'queued', progress = 0, last_error = '', chart_count = 0, started_at = NULL, "
                "generation = CASE WHEN status = 'ready' THEN NULL ELSE generation END, finished_at = NULL, created_at = ?, updated_at = ? "
                "WHERE id = ? AND job_type = 'chart_set' AND status IN ('failed', 'stopped', 'ready')",
                (now, now, job_id),
            )
            return cursor.rowcount == 1

    def list_report_chart_jobs(self, limit: int | None = 50) -> list[sqlite3.Row]:
        with self.connection() as conn:
            if limit is None:
                return list(conn.execute("SELECT * FROM generated_jobs WHERE job_type = 'chart_set' ORDER BY id DESC").fetchall())
            return list(conn.execute("SELECT * FROM generated_jobs WHERE job_type = 'chart_set' ORDER BY id DESC LIMIT ?", (limit,)).fetchall())

    def get_report_chart_job(self, job_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM generated_jobs WHERE id = ? AND job_type = 'chart_set'", (job_id,)).fetchone()

    def delete_report_chart_job(self, job_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            job = conn.execute("SELECT * FROM generated_jobs WHERE id = ? AND job_type = 'chart_set'", (job_id,)).fetchone()
            if job:
                conn.execute("DELETE FROM generated_jobs WHERE id = ? AND job_type = 'chart_set'", (job_id,))
            return job

    def delete_report_chart_jobs_for_generations(self, generations: list[str]) -> int:
        """Remove ready Chart Set jobs whose generated files were deleted."""
        unique_generations = [value for value in dict.fromkeys(generations) if value]
        if not unique_generations:
            return 0
        placeholders = ','.join('?' for _ in unique_generations)
        with self.connection() as conn:
            cursor = conn.execute(
                f"DELETE FROM generated_jobs WHERE job_type = 'chart_set' AND generation IN ({placeholders})",
                unique_generations,
            )
            return int(cursor.rowcount)

    def fail_interrupted_report_chart_jobs(self) -> list[int]:
        """Make in-process Report Charts work retryable after an app restart."""
        message = 'Interrupted because the application restarted. Retry the job to run it again.'
        now = local_now_iso()
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM generated_jobs WHERE job_type = 'chart_set' AND status IN ('queued', 'processing')"
            ).fetchall()
            job_ids = [int(row['id']) for row in rows]
            if job_ids:
                placeholders = ','.join('?' for _ in job_ids)
                conn.execute(
                    f"UPDATE generated_jobs SET status = 'failed', progress = 100, last_error = ?, updated_at = ?, finished_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (message, now, now, *job_ids),
                )
        return job_ids

    def save_transfer_offer(self, offer: dict[str, Any]) -> None:
        """Persist destination transfer handshake state in the global DB."""
        offer_id = str(offer['id'])
        updated_at = float(offer.get('updated_at') or offer.get('created_at') or 0)
        with self.global_connection() as conn:
            self._ensure_transfer_offers_table(conn)
            conn.execute(
                """
                INSERT INTO transfer_offers (id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (offer_id, json.dumps(offer, sort_keys=True, default=str), updated_at),
            )

    def replace_pending_transfer_offers(self, offer: dict[str, Any]) -> list[str]:
        """Atomically supersede same-source pending offers and insert a new one."""
        source_address = str(offer.get('source_address') or '')
        now = float(offer.get('created_at') or datetime.now().timestamp())
        superseded: list[str] = []
        with self.global_connection() as conn:
            self._ensure_transfer_offers_table(conn)
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("SELECT id, payload_json FROM transfer_offers").fetchall()
            for row in rows:
                try:
                    existing = json.loads(row['payload_json'])
                except (TypeError, json.JSONDecodeError):
                    continue
                if (
                    not isinstance(existing, dict)
                    or existing.get('status') != 'pending'
                    or str(existing.get('source_address') or '') != source_address
                ):
                    continue
                existing.update({
                    'status': 'cancelled',
                    'phase': 'superseded by newer request',
                    'error': 'This transfer offer was replaced by a newer request from the same server.',
                    'finished_at': now,
                    'updated_at': now,
                })
                existing_id = str(row['id'])
                conn.execute(
                    "UPDATE transfer_offers SET payload_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(existing, sort_keys=True, default=str), now, existing_id),
                )
                superseded.append(existing_id)
            conn.execute(
                "INSERT OR REPLACE INTO transfer_offers (id, payload_json, updated_at) VALUES (?, ?, ?)",
                (str(offer['id']), json.dumps(offer, sort_keys=True, default=str), now),
            )
        return superseded

    def list_transfer_offers(self) -> list[dict[str, Any]]:
        with self.global_connection() as conn:
            self._ensure_transfer_offers_table(conn)
            rows = conn.execute(
                "SELECT payload_json FROM transfer_offers ORDER BY updated_at"
            ).fetchall()
        offers: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row['payload_json'])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get('id'):
                offers.append(payload)
        return offers

    def delete_transfer_offer(self, offer_id: str) -> None:
        with self.global_connection() as conn:
            self._ensure_transfer_offers_table(conn)
            conn.execute("DELETE FROM transfer_offers WHERE id = ?", (str(offer_id),))

    def _ensure_transfer_offers_table(self, conn: sqlite3.Connection) -> None:
        """Repair pre-migration persistent application databases on demand."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transfer_offers (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )

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
