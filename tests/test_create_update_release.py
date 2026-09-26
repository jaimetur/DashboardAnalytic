from __future__ import annotations

import subprocess

import pytest

from tools import CreateUpdateRelease as release_tool


def test_add_changelog_release_inserts_empty_sections_before_current_release():
    content = (
        '# CHANGELOG\n\n---\n\n'
        '## Release: v1.2.3\n'
        '### Release Date: 2026-09-20\n'
        '#### 🚀 Enhancements:\n'
        '- Existing change.\n'
    )

    updated = release_tool.add_changelog_release(content, '1.2.4', '2026-09-21')

    expected_release = (
        '## Release: v1.2.4\n'
        '### Release Date: 2026-09-21\n'
        '#### ⚠️ Breaking Changes:\n\n'
        '#### 🌟 New Features:\n\n'
        '#### 🚀 Enhancements:\n\n'
        '#### 🐛 Bug fixes:\n\n'
        '#### 📚 Documentation:\n\n'
        '---\n\n'
    )
    assert expected_release in updated
    assert updated.index('## Release: v1.2.4') < updated.index('## Release: v1.2.3')


def test_add_changelog_release_rejects_duplicate_version():
    content = '## Release: v1.2.4\n### Release Date: 2026-09-21\n'

    with pytest.raises(RuntimeError, match='already contains'):
        release_tool.add_changelog_release(content, '1.2.4', '2026-09-21')


def test_write_release_files_updates_version_and_adds_changelog_release(tmp_path, monkeypatch):
    version_path = tmp_path / 'version.py'
    changelog_path = tmp_path / 'CHANGELOG.md'
    version_path.write_text(
        '__version__ = "1.2.3"\n__release_date__ = "2026-09-20"\n', encoding='utf-8'
    )
    changelog_path.write_text(
        '# CHANGELOG\n\n---\n\n## Release: v1.2.3\n### Release Date: 2026-09-20\n',
        encoding='utf-8',
    )
    pyproject_path = tmp_path / 'pyproject.toml'
    pyproject_path.write_text(
        '[build-system]\nrequires = ["setuptools>=68"]\n\n[project]\nname = "demo"\nversion = "1.2.3"\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(release_tool, 'VERSION_PATH', version_path)
    monkeypatch.setattr(release_tool, 'CHANGELOG_PATH', changelog_path)
    monkeypatch.setattr(release_tool, 'PYPROJECT_PATH', pyproject_path)

    release_tool.write_release_files('1.2.4', '2026-09-21', create_changelog_release=True)

    assert 'version = "1.2.4"' in pyproject_path.read_text(encoding='utf-8')
    assert 'requires = ["setuptools>=68"]' in pyproject_path.read_text(encoding='utf-8')
    assert '__version__ = "1.2.4"' in version_path.read_text(encoding='utf-8')
    assert '__release_date__ = "2026-09-21"' in version_path.read_text(encoding='utf-8')
    changelog = changelog_path.read_text(encoding='utf-8')
    assert changelog.count('## Release: v1.2.4') == 1
    assert '## Release: v1.2.3' in changelog


@pytest.mark.parametrize('invalid_date', ['2026-02-30', '2026-13-01', '21-09-2026'])
def test_validate_inputs_rejects_invalid_calendar_dates(invalid_date):
    assert release_tool.validate_inputs('1.2.4', invalid_date)


def test_prepare_working_tree_commits_and_pushes_current_branch(monkeypatch):
    commands = []

    def fake_run_git(*arguments, **_kwargs):
        commands.append(arguments)

    monkeypatch.setattr(release_tool, 'run_git', fake_run_git)

    release_tool.prepare_working_tree(
        release_tool.DirtyTreeAction.COMMIT_AND_PUSH,
        '1.2.3',
        '1.2.4',
    )

    assert commands == [
        ('add', '--all'),
        ('commit', '-m', 'Save work before creating release v1.2.4'),
        ('push', 'origin', 'HEAD:refs/heads/1.2.3'),
    ]


def test_prepare_working_tree_discards_tracked_and_untracked_changes(monkeypatch):
    commands = []

    def fake_run_git(*arguments, **_kwargs):
        commands.append(arguments)

    monkeypatch.setattr(release_tool, 'run_git', fake_run_git)

    release_tool.prepare_working_tree(
        release_tool.DirtyTreeAction.DISCARD,
        '1.2.3',
        '1.2.4',
    )

    assert commands == [('reset', '--hard', 'HEAD'), ('clean', '-fd')]


def test_create_release_carries_changes_and_pushes_new_branch(tmp_path, monkeypatch):
    remote = tmp_path / 'remote.git'
    project = tmp_path / 'project'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    subprocess.run(['git', 'init', str(project)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(project), 'config', 'user.name', 'Release Test'], check=True)
    subprocess.run(
        ['git', '-C', str(project), 'config', 'user.email', 'release-test@example.com'], check=True
    )
    (project / 'src').mkdir()
    (project / 'src' / 'version.py').write_text(
        '__version__ = "1.2.3"\n__release_date__ = "2026-09-20"\n', encoding='utf-8'
    )
    (project / 'CHANGELOG.md').write_text(
        '# CHANGELOG\n\n---\n\n## Release: v1.2.3\n### Release Date: 2026-09-20\n',
        encoding='utf-8',
    )
    subprocess.run(['git', '-C', str(project), 'add', '--all'], check=True)
    subprocess.run(['git', '-C', str(project), 'commit', '-m', 'Initial release'], check=True)
    subprocess.run(['git', '-C', str(project), 'branch', '-M', '1.2.3'], check=True)
    subprocess.run(['git', '-C', str(project), 'remote', 'add', 'origin', str(remote)], check=True)
    subprocess.run(['git', '-C', str(project), 'push', '--set-upstream', 'origin', '1.2.3'], check=True)
    (project / 'pending.txt').write_text('Carry this change.\n', encoding='utf-8')

    monkeypatch.setattr(release_tool, 'ROOT', project)
    monkeypatch.setattr(release_tool, 'VERSION_PATH', project / 'src' / 'version.py')
    monkeypatch.setattr(release_tool, 'CHANGELOG_PATH', project / 'CHANGELOG.md')
    monkeypatch.setattr(release_tool, 'PYPROJECT_PATH', project / 'pyproject.toml')

    release_tool.create_release(
        '1.2.4',
        '2026-09-21',
        release_tool.DirtyTreeAction.CARRY_TO_NEW_BRANCH,
    )

    branch = subprocess.run(
        ['git', '-C', str(project), 'branch', '--show-current'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == '1.2.4'
    assert (project / 'pending.txt').is_file()
    assert not subprocess.run(
        ['git', '-C', str(project), 'status', '--porcelain'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    remote_branch = subprocess.run(
        ['git', '--git-dir', str(remote), 'show-ref', '--verify', 'refs/heads/1.2.4'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert 'refs/heads/1.2.4' in remote_branch
    assert '## Release: v1.2.4' in (project / 'CHANGELOG.md').read_text(encoding='utf-8')
