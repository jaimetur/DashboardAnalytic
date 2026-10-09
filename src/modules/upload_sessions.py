"""Resumable dataset uploads: files sent in chunks to a workspace, which survive leaving the page.

The browser keeps the chosen files and their classification until the upload ends, and sends each
file in chunks. Every chunk is appended to the upload session of the workspace the upload started in
(``.upload-sessions/<id>`` beside its database), so the upload continues after changing page, module
or workspace and from where it stopped. When every file is complete the files move to the input
folder of that workspace and are processed there.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

SESSIONS_FOLDER = '.upload-sessions'
MANIFEST = 'manifest.json'
# Sessions nobody resumed for this long are removed.
STALE_SECONDS = 7 * 24 * 3600
_ID = re.compile(r'[0-9a-f]{32}')


def sessions_root(workspace_folder: Path) -> Path:
    return Path(workspace_folder) / SESSIONS_FOLDER


def _folder(root: Path, upload_id: str) -> Path:
    if not _ID.fullmatch(str(upload_id or '')):
        raise ValueError('Unknown upload.')
    return root / upload_id


def _part(folder: Path, index: int) -> Path:
    return folder / f'{int(index)}.part'


def create_session(root: Path, username: str, files: list[dict[str, Any]], form: dict[str, Any]) -> dict[str, Any]:
    """Start an upload of the given files (name and size in bytes) with their classification."""
    cleanup_stale(root)
    entries = []
    for item in files:
        name = Path(str(item.get('name') or '')).name
        size = int(item.get('size') or 0)
        if not name or size < 0:
            raise ValueError('Every uploaded file needs a name and a size.')
        entries.append({'name': name, 'size': size})
    if not entries:
        raise ValueError('No files were provided.')
    upload_id = uuid.uuid4().hex
    folder = root / upload_id
    folder.mkdir(parents=True)
    for index in range(len(entries)):
        _part(folder, index).touch()
    manifest = {'id': upload_id, 'username': username, 'created_at': time.time(), 'files': entries, 'form': form}
    (folder / MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    return status(root, upload_id)


def load_session(root: Path, upload_id: str) -> dict[str, Any]:
    folder = _folder(root, upload_id)
    try:
        return json.loads((folder / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Unknown upload.') from exc


def status(root: Path, upload_id: str) -> dict[str, Any]:
    """The upload with the bytes received of every file."""
    manifest = load_session(root, upload_id)
    folder = _folder(root, upload_id)
    received = [_part(folder, index).stat().st_size if _part(folder, index).exists() else 0
                for index in range(len(manifest['files']))]
    # The session is touched while it is used, so it is not removed as stale.
    (folder / MANIFEST).touch()
    return {'upload_id': manifest['id'], 'files': manifest['files'], 'received': received,
            'complete': all(size >= item['size'] for size, item in zip(received, manifest['files']))}


def append_chunk(root: Path, upload_id: str, index: int, offset: int, data: bytes) -> int:
    """Append the bytes of a file that start at ``offset``; returns the bytes received of that file."""
    manifest = load_session(root, upload_id)
    if not 0 <= int(index) < len(manifest['files']):
        raise ValueError('Unknown file of the upload.')
    part = _part(_folder(root, upload_id), index)
    received = part.stat().st_size if part.exists() else 0
    size = int(manifest['files'][index]['size'])
    if offset > received:
        raise LookupError(received)
    # A chunk sent again after an interruption only adds what is missing.
    new = data[received - offset:] if offset < received else data
    if received + len(new) > size:
        raise ValueError('The upload is larger than the file.')
    if new:
        with part.open('ab') as handle:
            handle.write(new)
    return received + len(new)


def take_files(root: Path, upload_id: str, destination_folder: Path, destination) -> list[tuple[str, Path]]:
    """Move the complete files of an upload to their destinations; ``destination(folder, name)`` names each."""
    manifest = load_session(root, upload_id)
    current = status(root, upload_id)
    if not current['complete']:
        raise ValueError('The upload has not finished.')
    folder = _folder(root, upload_id)
    moved = []
    for index, item in enumerate(manifest['files']):
        target = destination(destination_folder, item['name'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(_part(folder, index)), str(target))
        moved.append((item['name'], target))
    return moved


def delete_session(root: Path, upload_id: str) -> None:
    shutil.rmtree(_folder(root, upload_id), ignore_errors=True)


def cleanup_stale(root: Path, now: float | None = None) -> int:
    now = time.time() if now is None else now
    removed = 0
    for folder in root.glob('*') if root.is_dir() else []:
        manifest = folder / MANIFEST
        try:
            modified = manifest.stat().st_mtime
        except OSError:
            modified = folder.stat().st_mtime
        if folder.is_dir() and _ID.fullmatch(folder.name) and now - modified > STALE_SECONDS:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed
