from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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

    def add_log(self, username: str, action: str, details: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs (username, action, details) VALUES (?, ?, ?)",
                (username, action, details),
            )

    def list_logs(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute("SELECT id, username, action, details, created_at FROM audit_logs ORDER BY id DESC LIMIT 250").fetchall())
