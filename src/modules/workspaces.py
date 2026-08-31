from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Workspace:
    id: str
    name: str
    database_path: Path
    input_dir: Path
    output_dir: Path
    export_dir: Path
    slides_templates_dir: Path
    created_at: str
    last_opened_at: str


class WorkspaceRegistry:
    """Persistent workspace catalogue kept separate from workspace data."""

    def __init__(
        self,
        registry_path: Path,
        legacy_database_path: Path,
        legacy_data_dir: Path,
        legacy_slides_templates_dir: Path,
        legacy_registry_path: Path | None = None,
    ) -> None:
        self.registry_path = registry_path
        self.legacy_database_path = legacy_database_path
        self.legacy_data_dir = legacy_data_dir
        self.legacy_slides_templates_dir = legacy_slides_templates_dir
        self.legacy_registry_path = legacy_registry_path

    def _connection(self) -> sqlite3.Connection:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.registry_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        self._migrate_legacy_registry_file()
        created_default = False
        default_slides_templates_dir: Path | None = None
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    database_path TEXT NOT NULL,
                    input_dir TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    export_dir TEXT NOT NULL,
                    slides_templates_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE TABLE IF NOT EXISTS workspace_state (key TEXT PRIMARY KEY, value TEXT)")
            if not conn.execute("SELECT 1 FROM workspaces LIMIT 1").fetchone():
                created_default = True
                now = self._now()
                default_root = self._workspace_root('Default Workspace')
                default_slides_templates_dir = default_root / 'slides-templates'
                conn.execute(
                    """INSERT INTO workspaces (
                        id, name, database_path, input_dir, output_dir, export_dir,
                        slides_templates_dir, created_at, last_opened_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        'default', 'Default Workspace', str(default_root / 'Default Workspace.db'),
                        str(default_root / 'input'), str(default_root / 'output'),
                        str(default_root / 'exports'), str(default_root / 'slides-templates'), now, now,
                    ),
                )
                conn.execute("INSERT OR REPLACE INTO workspace_state (key, value) VALUES ('active_workspace_id', 'default')")
            elif not conn.execute("SELECT 1 FROM workspace_state WHERE key = 'active_workspace_id'").fetchone():
                latest = conn.execute('SELECT id FROM workspaces ORDER BY last_opened_at DESC LIMIT 1').fetchone()
                conn.execute("INSERT INTO workspace_state (key, value) VALUES ('active_workspace_id', ?)", (latest['id'] if latest else None,))
        if created_default and default_slides_templates_dir and self.legacy_slides_templates_dir.exists():
            shutil.copytree(self.legacy_slides_templates_dir, default_slides_templates_dir, dirs_exist_ok=True)
        self._migrate_default_database()
        self._migrate_workspace_directories()

    def _migrate_legacy_registry_file(self) -> None:
        """Retain registry state while replacing the ambiguous old filename."""
        source = self.legacy_registry_path
        if not source or source == self.registry_path or not source.exists() or self.registry_path.exists():
            return
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(self.registry_path))
        for suffix in ('-wal', '-shm'):
            sidecar = Path(f'{source}{suffix}')
            if sidecar.exists():
                shutil.move(str(sidecar), str(Path(f'{self.registry_path}{suffix}')))

    @staticmethod
    def _now() -> str:
        # Opening several workspaces in quick succession must retain a stable
        # chronology for the Login default, not collapse to the same second.
        return datetime.now(timezone.utc).isoformat(timespec='microseconds')

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized_name = ' '.join(name.split())
        if not normalized_name:
            raise ValueError('Workspace name is required.')
        if len(normalized_name) > 100:
            raise ValueError('Workspace name must be 100 characters or fewer.')
        if normalized_name in {'.', '..'} or any(character in normalized_name for character in '<>:"/\\|?*\0'):
            raise ValueError('Workspace name contains characters that cannot be used in a database filename.')
        return normalized_name

    @staticmethod
    def _move_database_bundle(source: Path, destination: Path) -> None:
        if source == destination:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            if destination.exists():
                raise ValueError(f'The database file "{destination.name}" already exists.')
            shutil.move(str(source), str(destination))
            for suffix in ('-wal', '-shm'):
                sidecar = Path(f'{source}{suffix}')
                if sidecar.exists():
                    shutil.move(str(sidecar), str(Path(f'{destination}{suffix}')))

    def _workspace_root(self, name: str) -> Path:
        return self.legacy_data_dir / 'workspaces' / name

    @staticmethod
    def _relocate_path(path: Path, old_root: Path, new_root: Path) -> Path:
        try:
            return new_root / path.relative_to(old_root)
        except ValueError:
            return path

    def _migrate_default_database(self) -> None:
        """Relocate the legacy config DB without changing its existing data."""
        workspace = self.get('default')
        if not workspace:
            return
        target = self._workspace_root(workspace.name) / f'{workspace.name}.db'
        source = workspace.database_path
        # Older registry versions referenced config/app.db; a fresh registry
        # already points at target, so use that legacy source when needed.
        if not source.exists() and self.legacy_database_path.exists():
            source = self.legacy_database_path
        if source != target and source.exists():
            self._move_database_bundle(source, target)
            if source.parent.parent == self.legacy_data_dir / 'workspaces':
                try:
                    source.parent.rmdir()
                except OSError:
                    pass
        with self._connection() as conn:
            conn.execute('UPDATE workspaces SET database_path = ? WHERE id = ?', (str(target), 'default'))

    def _migrate_workspace_directories(self) -> None:
        """Move earlier ID-based folders to their human-readable names."""
        managed_root = self.legacy_data_dir / 'workspaces'
        for workspace in self.list():
            old_root = workspace.database_path.parent
            new_root = self._workspace_root(workspace.name)
            if old_root.parent != managed_root:
                continue
            if old_root != new_root:
                if new_root.exists():
                    raise ValueError(f'Workspace directory "{new_root.name}" already exists.')
                if old_root.exists():
                    shutil.move(str(old_root), str(new_root))
            moved_database = new_root / workspace.database_path.name
            new_database = new_root / f'{workspace.name}.db'
            self._move_database_bundle(moved_database, new_database)
            input_dir = self._relocate_path(workspace.input_dir, old_root, new_root)
            output_dir = self._relocate_path(workspace.output_dir, old_root, new_root)
            export_dir = self._relocate_path(workspace.export_dir, old_root, new_root)
            slides_templates_dir = self._relocate_path(workspace.slides_templates_dir, old_root, new_root)
            for source_path, target_path in (
                (input_dir, new_root / 'input'), (output_dir, new_root / 'output'), (export_dir, new_root / 'exports'),
            ):
                if source_path != target_path and source_path.exists() and not target_path.exists():
                    shutil.move(str(source_path), str(target_path))
                if source_path != target_path:
                    if source_path == input_dir:
                        input_dir = target_path
                    elif source_path == output_dir:
                        output_dir = target_path
                    else:
                        export_dir = target_path
            workspace_templates_dir = new_root / 'slides-templates'
            has_workspace_templates = workspace_templates_dir.exists() and any(workspace_templates_dir.rglob('*.csv'))
            if not has_workspace_templates:
                # Older workspaces pointed to the shared application assets.
                # Each workspace now owns its editable copy, so preserve an
                # existing copy when available or rebuild it from the config
                # seed if the legacy assets have already been removed.
                template_source = next(
                    (
                        candidate
                        for candidate in (slides_templates_dir, self.legacy_slides_templates_dir)
                        if candidate.exists() and any(candidate.rglob('*.csv'))
                    ),
                    None,
                )
                if template_source:
                    shutil.copytree(template_source, workspace_templates_dir, dirs_exist_ok=True)
            if slides_templates_dir != workspace_templates_dir:
                slides_templates_dir = workspace_templates_dir
            if input_dir != workspace.input_dir and new_database.exists():
                with sqlite3.connect(new_database) as conn:
                    conn.execute(
                        'UPDATE datasets SET stored_path = REPLACE(stored_path, ?, ?)',
                        (str(workspace.input_dir), str(input_dir)),
                    )
            with self._connection() as conn:
                conn.execute(
                    '''UPDATE workspaces
                       SET database_path = ?, input_dir = ?, output_dir = ?, export_dir = ?, slides_templates_dir = ?
                       WHERE id = ?''',
                    (str(new_database), str(input_dir), str(output_dir), str(export_dir), str(slides_templates_dir), workspace.id),
                )

    def _row_to_workspace(self, row: sqlite3.Row) -> Workspace:
        return Workspace(
            id=str(row['id']), name=str(row['name']), database_path=Path(row['database_path']),
            input_dir=Path(row['input_dir']), output_dir=Path(row['output_dir']),
            export_dir=Path(row['export_dir']), slides_templates_dir=Path(row['slides_templates_dir']),
            created_at=str(row['created_at']), last_opened_at=str(row['last_opened_at']),
        )

    def list(self) -> list[Workspace]:
        with self._connection() as conn:
            rows = conn.execute('SELECT * FROM workspaces ORDER BY name COLLATE NOCASE').fetchall()
        return [self._row_to_workspace(row) for row in rows]

    def get(self, workspace_id: str) -> Workspace | None:
        with self._connection() as conn:
            row = conn.execute('SELECT * FROM workspaces WHERE id = ?', (workspace_id,)).fetchone()
        return self._row_to_workspace(row) if row else None

    def most_recent(self) -> Workspace:
        with self._connection() as conn:
            row = conn.execute('SELECT * FROM workspaces ORDER BY last_opened_at DESC, name COLLATE NOCASE LIMIT 1').fetchone()
        if not row:
            raise RuntimeError('Workspace registry was not initialized')
        return self._row_to_workspace(row)

    def active_id(self) -> str | None:
        with self._connection() as conn:
            row = conn.execute("SELECT value FROM workspace_state WHERE key = 'active_workspace_id'").fetchone()
        return str(row['value']) if row and row['value'] else None

    def create(self, name: str) -> Workspace:
        normalized_name = self._validate_name(name)
        with self._connection() as conn:
            workspace_id = str(conn.execute('SELECT COALESCE(MAX(CAST(substr(id, 11) AS INTEGER)), 0) + 1 AS next_id FROM workspaces WHERE id GLOB "workspace-*"').fetchone()['next_id'])
            workspace_id = f'workspace-{workspace_id}'
            now = self._now()
            data_root = self._workspace_root(normalized_name)
            db_path = data_root / f'{normalized_name}.db'
            slides_templates_dir = data_root / 'slides-templates'
            try:
                conn.execute(
                    """INSERT INTO workspaces (
                        id, name, database_path, input_dir, output_dir, export_dir,
                        slides_templates_dir, created_at, last_opened_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (workspace_id, normalized_name, str(db_path), str(data_root / 'input'), str(data_root / 'output'),
                     str(data_root / 'exports'), str(slides_templates_dir), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'A workspace named "{normalized_name}" already exists.') from exc
        # New workspaces start with the bundled/default slide templates but do
        # not share their mutable template files with the existing workspace.
        if self.legacy_slides_templates_dir.exists():
            shutil.copytree(self.legacy_slides_templates_dir, slides_templates_dir, dirs_exist_ok=True)
        return self.get(workspace_id)  # type: ignore[return-value]

    def duplicate(self, workspace_id: str) -> Workspace:
        source = self.get(workspace_id)
        if not source:
            raise ValueError('Workspace not found.')
        base_name = f'{source.name} - Copy'
        duplicate_name = base_name
        names = {workspace.name.casefold() for workspace in self.list()}
        copy_number = 2
        while duplicate_name.casefold() in names:
            duplicate_name = f'{source.name} - Copy {copy_number}'
            copy_number += 1

        duplicate = self.create(duplicate_name)
        target_root = duplicate.database_path.parent
        try:
            # ``create`` has prepared the target directories and a template
            # snapshot. Replace that snapshot with an exact data copy, while
            # SQLite's backup API gives the duplicate a consistent DB image.
            shutil.rmtree(target_root)
            for source_path, target_path in (
                (source.input_dir, duplicate.input_dir),
                (source.output_dir, duplicate.output_dir),
                (source.export_dir, duplicate.export_dir),
                (source.slides_templates_dir, duplicate.slides_templates_dir),
            ):
                if source_path.exists():
                    shutil.copytree(source_path, target_path)
                else:
                    target_path.mkdir(parents=True, exist_ok=True)
            duplicate.database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(source.database_path) as source_conn, sqlite3.connect(duplicate.database_path) as duplicate_conn:
                source_conn.backup(duplicate_conn)
                duplicate_conn.execute(
                    'UPDATE datasets SET stored_path = REPLACE(stored_path, ?, ?)',
                    (str(source.input_dir), str(duplicate.input_dir)),
                )
        except Exception:
            with self._connection() as conn:
                conn.execute('DELETE FROM workspaces WHERE id = ?', (duplicate.id,))
            shutil.rmtree(target_root, ignore_errors=True)
            raise
        # A duplicate is created but not opened. Do not let it replace the
        # actual last-opened workspace in Login's default selection.
        with self._connection() as conn:
            conn.execute("UPDATE workspaces SET last_opened_at = '' WHERE id = ?", (duplicate.id,))
        return self.get(duplicate.id)  # type: ignore[return-value]

    def rename(self, workspace_id: str, name: str) -> Workspace:
        normalized_name = self._validate_name(name)
        workspace = self.get(workspace_id)
        if not workspace:
            raise ValueError('Workspace not found.')
        old_root = workspace.database_path.parent
        new_root = self._workspace_root(normalized_name)
        new_database_path = new_root / f'{normalized_name}.db'
        with self._connection() as conn:
            duplicate = conn.execute(
                'SELECT 1 FROM workspaces WHERE name = ? COLLATE NOCASE AND id != ?', (normalized_name, workspace_id),
            ).fetchone()
            if duplicate:
                raise ValueError(f'A workspace named "{normalized_name}" already exists.')
            if old_root != new_root:
                if new_root.exists():
                    raise ValueError(f'Workspace directory "{new_root.name}" already exists.')
                if old_root.exists():
                    shutil.move(str(old_root), str(new_root))
            moved_database_path = new_root / workspace.database_path.name
            if new_database_path != moved_database_path:
                self._move_database_bundle(moved_database_path, new_database_path)
            input_dir = self._relocate_path(workspace.input_dir, old_root, new_root)
            output_dir = self._relocate_path(workspace.output_dir, old_root, new_root)
            export_dir = self._relocate_path(workspace.export_dir, old_root, new_root)
            slides_templates_dir = self._relocate_path(workspace.slides_templates_dir, old_root, new_root)
            if input_dir != workspace.input_dir and new_database_path.exists():
                with sqlite3.connect(new_database_path) as workspace_conn:
                    workspace_conn.execute(
                        'UPDATE datasets SET stored_path = REPLACE(stored_path, ?, ?)',
                        (str(workspace.input_dir), str(input_dir)),
                    )
            result = conn.execute(
                '''UPDATE workspaces
                   SET name = ?, database_path = ?, input_dir = ?, output_dir = ?, export_dir = ?, slides_templates_dir = ?
                   WHERE id = ?''',
                (normalized_name, str(new_database_path), str(input_dir), str(output_dir), str(export_dir), str(slides_templates_dir), workspace_id),
            )
            if result.rowcount != 1:
                raise ValueError('Workspace not found.')
        return self.get(workspace_id)  # type: ignore[return-value]

    def mark_opened(self, workspace_id: str) -> Workspace:
        with self._connection() as conn:
            result = conn.execute('UPDATE workspaces SET last_opened_at = ? WHERE id = ?', (self._now(), workspace_id))
            if result.rowcount != 1:
                raise ValueError('Workspace not found.')
            conn.execute("INSERT OR REPLACE INTO workspace_state (key, value) VALUES ('active_workspace_id', ?)", (workspace_id,))
        return self.get(workspace_id)  # type: ignore[return-value]

    def close_active(self, workspace_id: str) -> None:
        with self._connection() as conn:
            row = conn.execute("SELECT value FROM workspace_state WHERE key = 'active_workspace_id'").fetchone()
            if not row or row['value'] != workspace_id:
                raise ValueError('Only the open workspace can be closed.')
            conn.execute("UPDATE workspace_state SET value = NULL WHERE key = 'active_workspace_id'")

    def delete(self, workspace_id: str) -> Workspace:
        workspace = self.get(workspace_id)
        if not workspace:
            raise ValueError('Workspace not found.')
        workspaces = self.list()
        with self._connection() as conn:
            conn.execute('DELETE FROM workspaces WHERE id = ?', (workspace_id,))
        # Both targets are deterministic paths registered by create(), never
        # a path supplied by the request.
        shutil.rmtree(workspace.database_path.parent, ignore_errors=True)
        return self.most_recent()
