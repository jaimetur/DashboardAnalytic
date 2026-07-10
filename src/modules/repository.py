from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

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
            existing = conn.execute("SELECT username FROM users WHERE username = ?", (admin_username,)).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, active) VALUES (?, ?, 'admin', 1)",
                    (admin_username, hash_password(admin_password)),
                )
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, active) VALUES (?, ?, 'user', 1)",
                    ("demo", hash_password("demo123")),
                )

    def get_user(self, username: str) -> UserRecord | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT username, password_hash, role, active FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return None
        return UserRecord(row["username"], row["password_hash"], row["role"], bool(row["active"]))

    def create_user(self, username: str, password: str, role: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, active) VALUES (?, ?, ?, 1)",
                (username, hash_password(password), role),
            )

    def list_users(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute("SELECT id, username, role, active, created_at FROM users ORDER BY id ASC").fetchall())

    def add_dataset(self, file_name: str, stored_path: str, uploaded_by: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO datasets (file_name, stored_path, uploaded_by) VALUES (?, ?, ?)",
                (file_name, stored_path, uploaded_by),
            )

    def list_datasets(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute("SELECT id, file_name, stored_path, uploaded_by, uploaded_at FROM datasets ORDER BY uploaded_at DESC").fetchall())

    def add_log(self, username: str, action: str, details: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs (username, action, details) VALUES (?, ?, ?)",
                (username, action, details),
            )

    def list_logs(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute("SELECT id, username, action, details, created_at FROM audit_logs ORDER BY id DESC LIMIT 250").fetchall())
