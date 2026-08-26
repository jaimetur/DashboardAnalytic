#!/usr/bin/env python3
"""Update Dashboard Analytic's application version and release date.

This small desktop utility keeps the runtime metadata in ``src/version.py`` and
the current release header in ``CHANGELOG.md`` in sync. GitHub workflows read
the version module directly, so no download-link maintenance is required.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / 'src' / 'version.py'
CHANGELOG_PATH = ROOT / 'CHANGELOG.md'
VERSION_PATTERN = r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?'
DATE_PATTERN = r'\d{4}-\d{2}-\d{2}'


def read_release_metadata() -> tuple[str, str]:
    """Return the current application version and release date."""
    if not VERSION_PATH.exists():
        raise FileNotFoundError(f'Missing version module: {VERSION_PATH}')

    content = VERSION_PATH.read_text(encoding='utf-8')
    version_match = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', content, flags=re.MULTILINE)
    date_match = re.search(r'^__release_date__\s*=\s*"([^"]+)"\s*$', content, flags=re.MULTILINE)
    if not version_match or not date_match:
        raise RuntimeError('Unable to find __version__ and __release_date__ in src/version.py.')
    return version_match.group(1), date_match.group(1)


def update_release_metadata(version: str, release_date: str) -> None:
    """Update the runtime version module and the first changelog release header."""
    version_content = VERSION_PATH.read_text(encoding='utf-8')
    version_content, version_count = re.subn(
        r'^(__version__\s*=\s*")[^"]+("\s*)$',
        rf'\g<1>{version}\g<2>',
        version_content,
        count=1,
        flags=re.MULTILINE,
    )
    version_content, date_count = re.subn(
        r'^(__release_date__\s*=\s*")[^"]+("\s*)$',
        rf'\g<1>{release_date}\g<2>',
        version_content,
        count=1,
        flags=re.MULTILINE,
    )
    if version_count != 1 or date_count != 1:
        raise RuntimeError('Unable to update version metadata in src/version.py.')

    if not CHANGELOG_PATH.exists():
        raise FileNotFoundError(f'Missing changelog: {CHANGELOG_PATH}')
    changelog_content = CHANGELOG_PATH.read_text(encoding='utf-8')
    changelog_content, release_count = re.subn(
        r'^## Release: v[^\s]+\s*$',
        f'## Release: v{version}',
        changelog_content,
        count=1,
        flags=re.MULTILINE,
    )
    changelog_content, changelog_date_count = re.subn(
        r'^### Release Date: \d{4}-\d{2}-\d{2}\s*$',
        f'### Release Date: {release_date}',
        changelog_content,
        count=1,
        flags=re.MULTILINE,
    )
    if release_count != 1 or changelog_date_count != 1:
        raise RuntimeError('Unable to update the current release header in CHANGELOG.md.')

    VERSION_PATH.write_text(version_content, encoding='utf-8')
    CHANGELOG_PATH.write_text(changelog_content, encoding='utf-8')


def validate_inputs(version: str, release_date: str) -> str | None:
    if not re.fullmatch(VERSION_PATTERN, version):
        return 'Version must use X.Y.Z or X.Y.Z-prerelease format.'
    if not re.fullmatch(DATE_PATTERN, release_date):
        return 'Release date must use YYYY-MM-DD format.'
    return None


def main() -> None:
    current_version, current_date = read_release_metadata()
    root = tk.Tk()
    root.title('Update Dashboard Analytic release metadata')
    root.geometry('580x250')
    root.resizable(False, False)

    frame = tk.Frame(root, padx=18, pady=18)
    frame.pack(fill='both', expand=True)
    tk.Label(frame, text=f'Current version: {current_version}', anchor='w').pack(fill='x')
    tk.Label(frame, text=f'Current release date: {current_date}', anchor='w').pack(fill='x', pady=(0, 14))

    version_var = tk.StringVar(value=current_version)
    date_var = tk.StringVar(value=current_date)
    tk.Label(frame, text='New version (X.Y.Z):', anchor='w').pack(fill='x')
    tk.Entry(frame, textvariable=version_var).pack(fill='x', pady=(0, 10))
    tk.Label(frame, text='New release date (YYYY-MM-DD):', anchor='w').pack(fill='x')
    tk.Entry(frame, textvariable=date_var).pack(fill='x', pady=(0, 18))

    def apply_update() -> None:
        version = version_var.get().strip()
        release_date = date_var.get().strip()
        error = validate_inputs(version, release_date)
        if error:
            messagebox.showerror('Invalid release metadata', error, parent=root)
            return
        try:
            update_release_metadata(version, release_date)
        except Exception as exc:
            messagebox.showerror('Update failed', str(exc), parent=root)
            return
        messagebox.showinfo('Release metadata updated', 'src/version.py and CHANGELOG.md were updated.', parent=root)
        root.destroy()

    actions = tk.Frame(frame)
    actions.pack(fill='x')
    tk.Button(actions, text='Cancel', command=root.destroy).pack(side='right')
    tk.Button(actions, text='Update Version and Date', command=apply_update).pack(side='right', padx=(0, 8))
    root.mainloop()


if __name__ == '__main__':
    main()
