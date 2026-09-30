from __future__ import annotations

import copy
import json
from pathlib import Path
import zipfile

import src.DashboardAnalytic as app_module
from src.modules.repository import Repository
from tests.scoring_fixtures import scoring_configuration


def _login(client) -> None:
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert response.status_code == 303


def _workspace_repository() -> tuple[object, Repository]:
    workspace = app_module.active_workspace
    assert workspace is not None
    task_repository = Repository(
        workspace.database_path,
        global_db_path=app_module.repository.db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    task_repository.initialize()
    task_repository.replace_scoring_configuration(scoring_configuration())
    return workspace, task_repository


def _configuration_with_medium_score(repository: Repository, value: float) -> dict:
    configuration = copy.deepcopy(repository.get_scoring_configuration())
    configuration['metrics'][0]['contexts']['DriveCity']['score_mapping']['medium_score'] = value
    return configuration


def test_scoring_configuration_export_import_round_trip(client, tmp_path: Path) -> None:
    _login(client)
    workspace, repository = _workspace_repository()
    expected = _configuration_with_medium_score(repository, 0.81)
    repository.replace_scoring_configuration(expected)

    package_path = tmp_path / 'scoring-configuration.zip'
    app_module._build_single_export_archive_file(
        'scoring-configuration', package_path, [workspace.id],
    )
    manifest = app_module.read_import_manifest(package_path)
    assert manifest['kind'] == 'scoring-configuration'
    assert manifest['workspace_components'] == ['scoring_configuration']
    with zipfile.ZipFile(package_path) as archive:
        member = manifest['archive_path']
        document = json.loads(archive.read(member))
    assert document['format'] == 'dashboard-analytic-scoring-configuration'
    assert document['version'] == 1
    assert document['configuration'] == expected

    overwritten = _configuration_with_medium_score(repository, 0.82)
    repository.replace_scoring_configuration(overwritten)
    app_module._apply_import_archive(
        package_path, manifest, destination_workspace_ids=[workspace.id],
    )
    assert repository.get_scoring_configuration() == expected


def test_partial_backup_restores_only_scoring_configuration(client, tmp_path: Path) -> None:
    _login(client)
    workspace, repository = _workspace_repository()
    expected = _configuration_with_medium_score(repository, 0.81)
    repository.replace_scoring_configuration(expected)

    backup_path = app_module.create_recurring_database_backup({
        'components': ['scoring_configuration'],
        'workspace_ids': [workspace.id],
        'backup_path': str(tmp_path),
        'max_backups': 5,
    })
    assert app_module._backup_archive_components(backup_path) == ['scoring_configuration']

    overwritten = _configuration_with_medium_score(repository, 0.82)
    repository.replace_scoring_configuration(overwritten)
    app_module.restore_database_backup(backup_path, ['scoring_configuration'])

    assert repository.get_scoring_configuration() == expected


def test_legacy_workspace_backup_does_not_claim_scoring_configuration(tmp_path: Path) -> None:
    package_path = tmp_path / 'legacy-workspace-backup.zip'
    manifest = app_module.archive_manifest(
        'database-backup',
        components=['workspace_components'],
        workspace_components=['workspace_database', 'main_cities'],
    )
    with zipfile.ZipFile(package_path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))

    assert app_module._backup_archive_components(package_path) == ['workspace_database', 'main_cities']


def test_scoring_json_import_export_uses_workspace_database(client):
    _login(client)
    workspace = app_module.active_workspace
    repository = Repository(workspace.database_path, app_module.repository.global_db_path,
                            app_module.workspace_registry.registry_path)
    repository.set_workspace_state('scoring_configuration', '')
    assert client.get('/api/workspace-config/scoring-configuration').status_code == 409
    assert 'Import a Scoring Configuration' in client.get('/scoring').text
    document = {'format': 'dashboard-analytic-scoring-configuration', 'version': 1,
                'configuration': scoring_configuration()}
    response = client.post('/api/workspace-config/scoring-configuration/import', files={
        'package': ('scoring.json', json.dumps(document).encode(), 'application/json'),
    })
    assert response.status_code == 200
    saved = repository.get_scoring_configuration()
    saved['metrics'][0]['contexts']['DriveCity']['max_points'] = 80
    assert client.put('/api/workspace-config/scoring-configuration', json=saved).status_code == 200
    exported = client.get('/api/workspace-config/scoring-configuration/export')
    assert exported.status_code == 200
    assert exported.json()['configuration'] == repository.get_scoring_configuration()
    assert exported.json()['configuration']['metrics'][0]['contexts']['DriveCity']['max_points'] == 80


def test_admin_importer_accepts_scoring_configuration_json(client):
    _login(client)
    document = {'format': 'dashboard-analytic-scoring-configuration', 'version': 1,
                'configuration': scoring_configuration()}
    response = client.post('/admin/import-export/inspect', files={
        'package': ('scoring.json', json.dumps(document).encode(), 'application/json'),
    })
    assert response.status_code == 200
    assert response.json()['kind'] == 'scoring-configuration'
    assert response.json()['requires_destination_workspaces'] is True
    upload = app_module.IMPORT_UPLOADS[response.headers['X-Import-Upload-Id']]
    app_module._apply_import_archive(upload['path'], upload['manifest'],
                                     destination_workspace_ids=[app_module.active_workspace.id])
    repository = Repository(app_module.active_workspace.database_path, app_module.repository.global_db_path,
                            app_module.workspace_registry.registry_path)
    assert repository.get_scoring_configuration()['metrics'][0]['code'] == 'C5'


def test_unconfigured_workspace_configuration_backup_round_trip(client):
    _login(client)
    workspace = app_module.active_workspace
    repository = Repository(workspace.database_path, app_module.repository.global_db_path,
                            app_module.workspace_registry.registry_path)
    repository.set_workspace_state('scoring_configuration', '')
    payload = app_module._scoring_configuration_archive_payload(workspace)
    assert json.loads(payload)['configuration'] is None
    repository.replace_scoring_configuration(scoring_configuration())
    app_module._restore_workspace_scoring_configuration(workspace, payload)
    assert not repository.get_workspace_state('scoring_configuration')
