from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from src.modules.auth import hash_password


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

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
"""


@dataclass(slots=True)
class UserRecord:
    username: str
    password_hash: str
    role: str
    active: bool


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

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

    def initialize(self, admin_username: str, admin_password: str) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            self._cleanup_duplicate_datasets(conn)
            conn.execute(
                """
                INSERT OR IGNORE INTO dataset_profiles (dataset_id, status, progress)
                SELECT id, 'queued', 0 FROM datasets
                """
            )
            existing = conn.execute("SELECT username FROM users WHERE username = ?", (admin_username,)).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, active) VALUES (?, ?, 'admin', 1)",
                    (admin_username, hash_password(admin_password)),
                )
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, active) VALUES (?, ?, 'user', 1)",
                    ('demo', hash_password('demo123')),
                )

    def dataset_rows_table_name(self, dataset_id: int) -> str:
        return f'dataset_rows_{int(dataset_id)}'

    def _quote_identifier(self, identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

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
        with self.connection() as conn:
            row = conn.execute(
                "SELECT username, password_hash, role, active FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return None
        return UserRecord(row['username'], row['password_hash'], row['role'], bool(row['active']))

    def get_user_by_id(self, user_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute(
                "SELECT id, username, role, active, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

    def create_user(self, username: str, password: str, role: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, active) VALUES (?, ?, ?, 1)",
                (username, hash_password(password), role),
            )

    def update_user(self, user_id: int, username: str, role: str, active: bool, password: str | None = None) -> None:
        with self.connection() as conn:
            existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if not existing:
                raise ValueError("User not found")
            if password:
                conn.execute(
                    "UPDATE users SET username = ?, password_hash = ?, role = ?, active = ? WHERE id = ?",
                    (username, hash_password(password), role, int(active), user_id),
                )
            else:
                conn.execute(
                    "UPDATE users SET username = ?, role = ?, active = ? WHERE id = ?",
                    (username, role, int(active), user_id),
                )

    def delete_user(self, user_id: int) -> None:
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if cursor.rowcount == 0:
                raise ValueError("User not found")

    def list_users(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute("SELECT id, username, role, active, created_at FROM users ORDER BY id ASC").fetchall())

    def count_active_admin_users(self) -> int:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = 'admin' AND active = 1",
            ).fetchone()
        return int(row['total']) if row else 0

    def list_active_users_by_usernames(self, usernames: list[str]) -> list[str]:
        normalized = [username.strip() for username in usernames if username and username.strip()]
        if not normalized:
            return []
        placeholders = ','.join('?' for _ in normalized)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT username FROM users WHERE active = 1 AND username IN ({placeholders})",
                normalized,
            ).fetchall()
        existing = {row['username'] for row in rows}
        return [username for username in normalized if username in existing]

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
                    SET file_name = ?, uploaded_by = ?, uploaded_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (file_name, uploaded_by, dataset_id),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dataset_profiles (dataset_id, status, progress) VALUES (?, 'queued', 0)
                    """,
                    (dataset_id,),
                )
                return dataset_id, False
            cursor = conn.execute(
                "INSERT INTO datasets (file_name, stored_path, uploaded_by) VALUES (?, ?, ?)",
                (file_name, stored_path, uploaded_by),
            )
            dataset_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO dataset_profiles (dataset_id, status, progress) VALUES (?, 'queued', 0)",
                (dataset_id,),
            )
            return dataset_id, True

    def replace_dataset_rows(self, dataset_id: int, df: pd.DataFrame) -> None:
        table_name = self.dataset_rows_table_name(dataset_id)
        safe_df = self._sqlite_safe_frame(df)
        with self.connection() as conn:
            conn.execute(f"DROP TABLE IF EXISTS {self._quote_identifier(table_name)}")
            safe_df.to_sql(table_name, conn, index=False)
            self._create_dataset_row_indexes(conn, table_name, safe_df.columns.tolist())

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
        case_matches = [column for column in existing_columns if str(column).strip().lower() == lowered]
        if case_matches:
            exact_lowercase = next((column for column in case_matches if column == lowered), None)
            return exact_lowercase or case_matches[0]

        suffixed_matches = [
            column for column in existing_columns
            if str(column).strip().lower().startswith(f'{lowered}__')
        ]
        if suffixed_matches:
            exact_lowercase = next((column for column in suffixed_matches if str(column).startswith(f'{lowered}__')), None)
            return exact_lowercase or suffixed_matches[0]
        return None

    def resolve_dataset_row_column_name(self, dataset_id: int, requested: str) -> str | None:
        existing_columns = set(self.list_dataset_row_columns(dataset_id))
        if not existing_columns:
            return None
        return self._resolve_dataset_row_column_name(existing_columns, requested)

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
        with self.connection() as conn:
            conn.execute(
                f"UPDATE dataset_profiles SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE dataset_id = ?",
                (*values, dataset_id),
            )

    def get_dataset(self, dataset_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT d.id, d.file_name, d.stored_path, d.uploaded_by, d.uploaded_at,
                       p.status, p.progress, p.dataset_kind, p.row_count, p.column_count,
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
                           p.status, p.progress, p.dataset_kind, p.row_count, p.column_count,
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
                "INSERT INTO audit_logs (username, action, details) VALUES (?, ?, ?)",
                (username, action, details),
            )

    def list_logs(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute("SELECT id, username, action, details, created_at FROM audit_logs ORDER BY id DESC LIMIT 250").fetchall())

    def list_workspace_logs(self, dataset_id: int | None = None, limit: int = 120) -> list[dict[str, Any]]:
        workspace_actions = {
            'upload_dataset',
            'reprocess_dataset',
            'process_dataset',
            'process_dataset_failed',
            'analyze_dataset_warning',
            'analyze_dataset_failed',
            'retry_dataset',
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
