#!/usr/bin/env python3
"""Create releases or update Dashboard Analytic release metadata."""

from __future__ import annotations

import re
import subprocess
import tkinter as tk
from datetime import date
from enum import Enum
from pathlib import Path
from tkinter import messagebox


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / 'src' / 'version.py'
CHANGELOG_PATH = ROOT / 'CHANGELOG.md'
VERSION_PATTERN = r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?'
DATE_PATTERN = r'\d{4}-\d{2}-\d{2}'

RELEASE_SECTIONS = (
    '#### ⚠️ Breaking Changes:',
    '#### 🌟 New Features:',
    '#### 🚀 Enhancements:',
    '#### 🐛 Bug fixes:',
    '#### 📚 Documentation:',
)


class DirtyTreeAction(Enum):
    """Available ways to handle uncommitted work before creating a branch."""

    COMMIT_AND_PUSH = 'commit_and_push'
    CARRY_TO_NEW_BRANCH = 'carry_to_new_branch'
    DISCARD = 'discard'
    CANCEL = 'cancel'


class GitCommandError(RuntimeError):
    """Raised when a Git command cannot be completed."""


def run_git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git in the project root and return its completed process."""
    result = subprocess.run(
        ['git', *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or 'Unknown Git error.'
        raise GitCommandError(f"git {' '.join(arguments)} failed:\n{detail}")
    return result


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


def replace_version_metadata(content: str, version: str, release_date: str) -> str:
    """Return version-module content with updated release metadata."""
    content, version_count = re.subn(
        r'^(__version__\s*=\s*")[^"]+("\s*)$',
        rf'\g<1>{version}\g<2>',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content, date_count = re.subn(
        r'^(__release_date__\s*=\s*")[^"]+("\s*)$',
        rf'\g<1>{release_date}\g<2>',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if version_count != 1 or date_count != 1:
        raise RuntimeError('Unable to update version metadata in src/version.py.')
    return content


def replace_current_changelog_metadata(content: str, version: str, release_date: str) -> str:
    """Return changelog content with its current release header updated."""
    content, release_count = re.subn(
        r'^## Release: v[^\s]+\s*$',
        f'## Release: v{version}',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content, date_count = re.subn(
        r'^### Release Date: \d{4}-\d{2}-\d{2}\s*$',
        f'### Release Date: {release_date}',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if release_count != 1 or date_count != 1:
        raise RuntimeError('Unable to update the current release header in CHANGELOG.md.')
    return content


def add_changelog_release(content: str, version: str, release_date: str) -> str:
    """Insert a new empty release before the current changelog release."""
    if re.search(rf'^## Release: v{re.escape(version)}\s*$', content, flags=re.MULTILINE):
        raise RuntimeError(f'CHANGELOG.md already contains release v{version}.')

    first_release = re.search(r'^## Release: v[^\s]+\s*$', content, flags=re.MULTILINE)
    if not first_release:
        raise RuntimeError('Unable to find the current release in CHANGELOG.md.')

    section_text = '\n\n'.join(RELEASE_SECTIONS)
    release_block = (
        f'## Release: v{version}\n'
        f'### Release Date: {release_date}\n'
        f'{section_text}\n\n'
        '---\n\n'
    )
    return content[:first_release.start()] + release_block + content[first_release.start():]


def release_file_contents(
    version: str, release_date: str, *, create_changelog_release: bool
) -> tuple[str, str]:
    """Build and validate both release files without changing the working tree."""
    if not CHANGELOG_PATH.exists():
        raise FileNotFoundError(f'Missing changelog: {CHANGELOG_PATH}')

    version_content = replace_version_metadata(
        VERSION_PATH.read_text(encoding='utf-8'), version, release_date
    )
    changelog_content = CHANGELOG_PATH.read_text(encoding='utf-8')
    if create_changelog_release:
        changelog_content = add_changelog_release(changelog_content, version, release_date)
    else:
        changelog_content = replace_current_changelog_metadata(changelog_content, version, release_date)

    return version_content, changelog_content


def write_release_files(version: str, release_date: str, *, create_changelog_release: bool) -> None:
    """Update the version module and either create or update a changelog release."""
    version_content, changelog_content = release_file_contents(
        version, release_date, create_changelog_release=create_changelog_release
    )

    VERSION_PATH.write_text(version_content, encoding='utf-8')
    CHANGELOG_PATH.write_text(changelog_content, encoding='utf-8')


def update_release_metadata(version: str, release_date: str) -> None:
    """Update runtime metadata and the current changelog release header."""
    write_release_files(version, release_date, create_changelog_release=False)


def validate_inputs(version: str, release_date: str) -> str | None:
    if not re.fullmatch(VERSION_PATTERN, version):
        return 'Version must use X.Y.Z or X.Y.Z-prerelease format.'
    if not re.fullmatch(DATE_PATTERN, release_date):
        return 'Release date must use YYYY-MM-DD format.'
    try:
        date.fromisoformat(release_date)
    except ValueError:
        return 'Release date is not a valid calendar date.'
    return None


def current_branch() -> str:
    """Return the checked-out branch, failing clearly for a detached HEAD."""
    result = run_git('symbolic-ref', '--quiet', '--short', 'HEAD', check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise GitCommandError('A named Git branch must be checked out before creating a release.')
    return result.stdout.strip()


def working_tree_changes() -> str:
    """Return porcelain status for tracked, staged and untracked files."""
    return run_git('status', '--porcelain=v1').stdout.rstrip()


def ensure_release_branch_is_available(branch: str) -> None:
    """Ensure a branch does not already exist locally or on origin."""
    local = run_git('show-ref', '--verify', '--quiet', f'refs/heads/{branch}', check=False)
    if local.returncode == 0:
        raise GitCommandError(f'Local branch {branch!r} already exists.')
    if local.returncode not in (0, 1):
        raise GitCommandError(f'Unable to check whether local branch {branch!r} exists.')

    run_git('remote', 'get-url', 'origin')
    remote = run_git('ls-remote', '--exit-code', '--heads', 'origin', branch, check=False)
    if remote.returncode == 0:
        raise GitCommandError(f'Remote branch origin/{branch} already exists.')
    if remote.returncode != 2:
        detail = remote.stderr.strip() or remote.stdout.strip() or 'Unknown Git error.'
        raise GitCommandError(f'Unable to check origin/{branch}:\n{detail}')


def prepare_working_tree(action: DirtyTreeAction, source_branch: str, version: str) -> None:
    """Apply the selected policy to pending work on the source branch."""
    if action is DirtyTreeAction.COMMIT_AND_PUSH:
        run_git('add', '--all')
        run_git('commit', '-m', f'Save work before creating release v{version}')
        run_git('push', 'origin', f'HEAD:refs/heads/{source_branch}')
    elif action is DirtyTreeAction.DISCARD:
        run_git('reset', '--hard', 'HEAD')
        run_git('clean', '-fd')
    elif action is DirtyTreeAction.CANCEL:
        raise RuntimeError('Release creation cancelled.')


def create_release(version: str, release_date: str, dirty_action: DirtyTreeAction) -> None:
    """Create, commit and publish a new release branch."""
    error = validate_inputs(version, release_date)
    if error:
        raise ValueError(error)

    source_branch = current_branch()
    run_git('check-ref-format', '--branch', version)
    ensure_release_branch_is_available(version)

    has_changes = bool(working_tree_changes())
    if has_changes:
        prepare_working_tree(dirty_action, source_branch, version)
    release_file_contents(version, release_date, create_changelog_release=True)

    run_git('switch', '--create', version)
    write_release_files(version, release_date, create_changelog_release=True)
    run_git('add', '--all')
    run_git('commit', '-m', f'Create release v{version}')
    run_git('push', '--set-upstream', 'origin', version)


def ask_dirty_tree_action(parent: tk.Misc, changes: str) -> DirtyTreeAction:
    """Ask how pending work should be handled and return the selected action."""
    selection = DirtyTreeAction.CANCEL
    dialog = tk.Toplevel(parent)
    dialog.title('Uncommitted changes found')
    dialog.geometry('760x430')
    dialog.minsize(620, 360)
    dialog.transient(parent)
    dialog.grab_set()

    frame = tk.Frame(dialog, padx=18, pady=18)
    frame.pack(fill='both', expand=True)
    tk.Label(
        frame,
        text='Choose what to do with the current branch changes before creating the release:',
        anchor='w',
        justify='left',
    ).pack(fill='x', pady=(0, 10))

    status = tk.Text(frame, height=10, wrap='none')
    status.insert('1.0', changes)
    status.configure(state='disabled')
    status.pack(fill='both', expand=True, pady=(0, 14))

    warning = tk.Label(
        frame,
        text='Discard permanently resets tracked files and removes untracked files.',
        anchor='w',
        fg='#9a3412',
    )
    warning.pack(fill='x', pady=(0, 10))

    def choose(action: DirtyTreeAction) -> None:
        nonlocal selection
        selection = action
        dialog.destroy()

    actions = tk.Frame(frame)
    actions.pack(fill='x')
    tk.Button(actions, text='Cancel', command=lambda: choose(DirtyTreeAction.CANCEL)).pack(side='right')
    tk.Button(actions, text='Discard Changes', command=lambda: choose(DirtyTreeAction.DISCARD)).pack(
        side='right', padx=(0, 8)
    )
    tk.Button(
        actions,
        text='Carry to New Branch',
        command=lambda: choose(DirtyTreeAction.CARRY_TO_NEW_BRANCH),
    ).pack(side='right', padx=(0, 8))
    tk.Button(
        actions,
        text='Commit and Push Current Branch',
        command=lambda: choose(DirtyTreeAction.COMMIT_AND_PUSH),
    ).pack(side='right', padx=(0, 8))

    dialog.protocol('WM_DELETE_WINDOW', lambda: choose(DirtyTreeAction.CANCEL))
    parent.wait_window(dialog)
    return selection


def main() -> None:
    current_version, current_date = read_release_metadata()
    root = tk.Tk()
    root.title('Create or update Dashboard Analytic release')
    root.geometry('650x290')
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

    def input_values() -> tuple[str, str] | None:
        version = version_var.get().strip()
        release_date = date_var.get().strip()
        error = validate_inputs(version, release_date)
        if error:
            messagebox.showerror('Invalid release metadata', error, parent=root)
            return None
        return version, release_date

    def apply_update() -> None:
        values = input_values()
        if values is None:
            return
        try:
            update_release_metadata(*values)
        except Exception as exc:
            messagebox.showerror('Update failed', str(exc), parent=root)
            return
        messagebox.showinfo('Release metadata updated', 'src/version.py and CHANGELOG.md were updated.', parent=root)
        root.destroy()

    def apply_create_release() -> None:
        values = input_values()
        if values is None:
            return
        version, release_date = values

        try:
            changes = working_tree_changes()
        except Exception as exc:
            messagebox.showerror('Git check failed', str(exc), parent=root)
            return

        action = DirtyTreeAction.CARRY_TO_NEW_BRANCH
        if changes:
            action = ask_dirty_tree_action(root, changes)
            if action is DirtyTreeAction.CANCEL:
                return

        try:
            create_release(version, release_date, action)
        except Exception as exc:
            messagebox.showerror('Release creation failed', str(exc), parent=root)
            return

        messagebox.showinfo(
            'Release created',
            f'Release v{version} was committed and pushed to origin/{version}.',
            parent=root,
        )
        root.destroy()

    actions = tk.Frame(frame)
    actions.pack(fill='x')
    tk.Button(actions, text='Cancel', command=root.destroy).pack(side='right')
    tk.Button(actions, text='Update Current Release', command=apply_update).pack(side='right', padx=(0, 8))
    tk.Button(actions, text='Create New Release', command=apply_create_release).pack(side='right', padx=(0, 8))
    root.mainloop()


if __name__ == '__main__':
    main()
