from pathlib import Path
import io
import json
import sqlite3
import zipfile

import pytest

from src.modules.repository import Repository
from src.modules.workspaces import WorkspaceRegistry
import src.DashboardAnalytic as app_module


def test_new_workspaces_have_empty_independent_template_libraries(tmp_path):
    legacy = tmp_path / 'shared'
    legacy.mkdir()
    (legacy / 'unused.csv').write_text('old defaults')
    registry = WorkspaceRegistry(tmp_path / 'data/workspaces/registry.db', tmp_path / 'data', legacy)
    registry.initialize()
    first = registry.get('default')
    second = registry.create('Second')
    assert first.slides_templates_dir != legacy
    assert first.slides_templates_dir != second.slides_templates_dir
    assert not list(first.slides_templates_dir.rglob('*.csv'))
    assert not list(second.slides_templates_dir.rglob('*.csv'))
    for workspace in (first, second):
        repo = Repository(workspace.database_path, tmp_path / 'application.db')
        repo.initialize()
        assert repo.list_report_templates('nsa') == []


def test_legacy_library_migration_is_independent_and_idempotent(tmp_path):
    legacy = tmp_path / 'shared'
    template = legacy / 'library/nsa/Existing.csv'
    template.parent.mkdir(parents=True)
    template.write_text('original')
    registry = WorkspaceRegistry(tmp_path / 'data/workspaces/registry.db', tmp_path / 'data', legacy)
    registry.initialize()
    original = registry.get('default')
    with registry._connection() as conn:
        conn.execute('UPDATE workspaces SET slides_templates_dir = ?', (str(legacy),))
    registry.initialize()
    migrated = registry.get('default')
    local = migrated.slides_templates_dir / 'library/nsa/Existing.csv'
    assert local.read_text() == 'original'
    local.write_text('workspace edit')
    registry.initialize()
    assert local.read_text() == 'workspace edit'
    assert template.read_text() == 'original'
    assert migrated.database_path == original.database_path


def test_template_registry_is_workspace_owned(tmp_path):
    first = Repository(tmp_path / 'a.db', tmp_path / 'app.db')
    second = Repository(tmp_path / 'b.db', tmp_path / 'app.db')
    first.initialize()
    second.initialize()
    first.add_report_template('nsa', 'Only A', is_default=True)
    assert len(first.list_report_templates('nsa')) == 1
    assert second.list_report_templates('nsa') == []
    first.initialize()
    assert first.list_report_templates('nsa')[0]['name'] == 'Only A'


def test_template_package_matches_source_and_imports_to_multiple_workspaces(client, tmp_path):
    source = app_module.active_workspace
    package, _name = app_module.build_export_archive('slides-templates')
    manifest = app_module.read_import_manifest(package)
    assert manifest['source_workspace']['name'] == source.name
    other = app_module.workspace_registry.create('Other')
    repo = Repository(other.database_path, app_module.repository.global_db_path)
    repo.initialize()
    assert repo.list_report_templates('nsa') == []
    archive_path = tmp_path / 'templates.zip'
    archive_path.write_bytes(package)
    assert app_module.matching_template_workspaces(manifest, [other, source]) == [source.id]
    app_module._apply_import_archive(archive_path, manifest, destination_workspace_ids=[source.id, other.id])
    assert repo.list_report_templates('nsa')
    copied = next((other.slides_templates_dir / 'default/nsa').glob('*.csv'))
    original = source.slides_templates_dir / copied.relative_to(other.slides_templates_dir)
    copied.write_text('independent')
    assert original.read_text() != 'independent'
    assert repo.list_datasets() == []


def test_template_import_without_matching_workspace_requires_selection(client, tmp_path):
    staging = tmp_path / 'payload'
    (staging / 'slides-templates').mkdir(parents=True)
    with pytest.raises(ValueError, match='Select at least'):
        app_module.import_slides_templates_archive(staging, manifest={'source_workspace': {'name': 'Absent'}})


def test_template_export_pins_source_when_active_workspace_changes(client, tmp_path):
    source = app_module.active_workspace
    other = app_module.workspace_registry.create('Other')
    app_module.activate_workspace(other.id)
    path = tmp_path / 'source.zip'
    app_module.build_export_archive_file('slides-templates', path, [source.id])
    with zipfile.ZipFile(path) as archive:
        assert json.loads(archive.read('manifest.json'))['source_workspace']['name'] == source.name
        assert any(name.endswith('.csv') for name in archive.namelist())
    assert app_module.report_catalogue_options('nsa') == []


def test_inspection_preselects_only_matching_workspace_and_requires_access(client, tmp_path, monkeypatch):
    source = app_module.active_workspace
    package, _name = app_module.build_export_archive('slides-templates')
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    other = app_module.workspace_registry.create('Restricted')
    result = client.post('/admin/import-export/inspect/upload', content=package,
                         headers={'Content-Type': 'application/zip'})
    assert result.status_code == 200, result.text
    assert result.json()['selected_workspace_ids'] == [source.id]
    assert other.id not in [item['id'] for item in result.json()['destination_workspaces']]
    upload_id = result.headers['X-Import-Upload-Id']
    denied = client.post('/admin/import-export/import/jobs', data={
        'upload_id': upload_id, 'confirmed_import': 'true', 'workspace_ids': other.id,
    })
    assert denied.status_code == 403


def test_workspace_archive_and_duplicate_include_templates(client, tmp_path):
    source = app_module.active_workspace
    package, _name = app_module.build_export_archive(f'workspace:{source.id}')
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert any(name.startswith('workspace/slides-templates/') and name.endswith('.csv')
                   for name in archive.namelist())
        snapshot = tmp_path / 'snapshot.db'
        snapshot.write_bytes(archive.read('workspace/database.sqlite'))
    with sqlite3.connect(snapshot) as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_templates').fetchone()[0] > 0
    duplicate = app_module.workspace_registry.duplicate(source.id)
    assert list(duplicate.slides_templates_dir.rglob('*.csv'))
    repo = Repository(duplicate.database_path, app_module.repository.global_db_path)
    repo.initialize()
    assert repo.list_report_templates('nsa')


def test_workspace_duplicate_optionally_copies_generated_reports_and_chart_sets(tmp_path):
    registry = WorkspaceRegistry(tmp_path / 'data/workspaces/registry.db', tmp_path / 'data', tmp_path / 'shared')
    registry.initialize()
    source = registry.get('default')
    assert source is not None
    source_repository = Repository(source.database_path, tmp_path / 'application.db')
    source_repository.initialize()
    report = source.export_dir / 'generated.pptx'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b'report')
    chart = source.output_dir / 'charts' / '20260910-120000' / 'chart-1.png'
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_bytes(b'chart')
    with sqlite3.connect(source.database_path) as connection:
        connection.execute(
            """INSERT INTO generated_jobs (job_type, technology, scope, template_name, output_file, created_by, output_path)
               VALUES ('report', 'nsa', 'single', 'Template', 'generated.pptx', 'admin', ?)""",
            (str(report),),
        )

    copied = registry.duplicate(source.id, include_generated_outputs=True)
    assert (copied.export_dir / 'generated.pptx').read_bytes() == b'report'
    assert (copied.output_dir / 'charts' / '20260910-120000' / 'chart-1.png').read_bytes() == b'chart'
    with sqlite3.connect(copied.database_path) as connection:
        copied_path = connection.execute('SELECT output_path FROM generated_jobs').fetchone()[0]
    assert copied_path == str(copied.export_dir / 'generated.pptx')

    without_outputs = registry.duplicate(source.id)
    assert not (without_outputs.export_dir / 'generated.pptx').exists()
    assert not (without_outputs.output_dir / 'charts').exists()
    with sqlite3.connect(without_outputs.database_path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM generated_jobs').fetchone()[0] == 0


def test_template_transfer_requires_and_retains_multiple_destinations(client):
    source = app_module.active_workspace
    other = app_module.workspace_registry.create('Second destination')
    headers = {'X-Dashboard-Transfer-Secret': 'template-transfer-secret-with-sufficient-length'}
    offered = client.post('/api/import-export/transfers/offers', headers=headers, json={
        'source': 'Template test source', 'archive_version': 1, 'kind': 'slides-templates',
        'content': 'Slides Templates', 'workspaces': [source.name],
    })
    assert offered.status_code == 200
    offer_id = offered.json()['offer_id']
    client.post('/login', data={'username': 'super', 'password': 'super123'}, follow_redirects=False)
    try:
        assert client.post(f'/admin/import-export/transfers/offers/{offer_id}/accept', json={}).status_code == 400
        selected = [source.id, other.id]
        accepted = client.post(f'/admin/import-export/transfers/offers/{offer_id}/accept',
                               json={'workspace_ids': selected})
        assert accepted.status_code == 200
        assert app_module.TRANSFER_OFFERS[offer_id]['destination_workspace_ids'] == selected
    finally:
        client.delete(f'/api/import-export/transfers/offers/{offer_id}', headers=headers)


def test_auto_field_package_preselects_source_workspace(client):
    source = app_module.active_workspace
    other = app_module.workspace_registry.create('Additional destination')
    app_module.repository.grant_all_workspace_access(other.id)
    package, _name = app_module.build_export_archive('auto-calculated-fields')
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    response = client.post('/admin/import-export/inspect/upload', content=package,
                           headers={'Content-Type': 'application/zip'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['selected_workspace_ids'] == [source.id]
    assert {item['id'] for item in payload['destination_workspaces']} >= {source.id, other.id}


def test_database_management_groups_template_registry_with_workspace_tables(client, monkeypatch):
    import re

    monkeypatch.setattr(app_module, 'asset_version', lambda path: 'test')
    # A legacy global registry must not shadow the new workspace registry.
    with app_module.repository.global_connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS report_templates (name TEXT)')
        conn.execute("INSERT INTO report_templates (name) VALUES ('Legacy global')")
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    response = client.get('/admin')
    assert response.status_code == 200
    groups = dict(re.findall(r'<optgroup label="([^"]+)">(.*?)</optgroup>', response.text, re.S))
    assert 'value="report_templates"' in groups['Workspace Tables']
    assert 'Slides Templates registry' in groups['Workspace Tables']
    assert 'value="report_templates"' not in groups['Config Tables']
