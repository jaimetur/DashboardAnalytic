from __future__ import annotations

import copy
import json
from pathlib import Path
import zipfile

import src.DashboardAnalytic as app_module
from src.modules.repository import Repository
from src.modules.scoring_config import default_scoring_profile, validate_scoring_configuration, validate_scoring_profiles
from tests.scoring_fixtures import legacy_scoring_configuration, scoring_configuration


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
    walk_share = 1 / len(configuration['metrics'])
    for metric in configuration['metrics']:
        metric['contexts']['Walk']['weight_share'] = walk_share
    return configuration


def test_scoring_configuration_export_import_round_trip(client, tmp_path: Path) -> None:
    _login(client)
    workspace, repository = _workspace_repository()
    expected = _configuration_with_medium_score(repository, 0.81)
    repository.replace_scoring_configuration(expected)
    profiles = repository.get_scoring_profiles()
    second_profile = copy.deepcopy(profiles['profiles'][0])
    second_profile['id'] = 'netcheck-2025'
    second_profile['name'] = 'NetCheck 2025'
    second_profile['configuration'] = copy.deepcopy(expected)
    second_profile['configuration']['version'] = 'NetCheck 2025'
    second_profile['configuration']['metrics'][0]['contexts']['Walk']['max_points'] = 10
    second_profile['configuration']['metrics'][1]['contexts']['Walk']['max_points'] = 30
    profiles['profiles'].append(second_profile)
    profiles['active_profile_id'] = second_profile['id']
    expected_profiles = repository.replace_scoring_profiles(profiles)

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
    assert document['version'] == 2
    assert document['active_profile_id'] == expected_profiles['active_profile_id']
    assert document['profiles'] == expected_profiles['profiles']
    assert expected_profiles['profiles'][0]['configuration']['scope']['environments']['Walk']['total_points'] == 0
    assert expected_profiles['profiles'][1]['configuration']['scope']['environments']['Walk']['total_points'] == 40
    assert all(
        metric['contexts']['Walk']['weight_share'] == 1 / len(expected_profiles['profiles'][0]['configuration']['metrics'])
        for metric in expected_profiles['profiles'][0]['configuration']['metrics']
    )

    repository.replace_scoring_profiles({
        'active_profile_id': 'netcheck-2026',
        'profiles': [expected_profiles['profiles'][0]],
    })
    app_module._apply_import_archive(
        package_path, manifest, destination_workspace_ids=[workspace.id],
    )
    assert repository.get_scoring_profiles() == expected_profiles


def test_partial_backup_restores_only_scoring_configuration(client, tmp_path: Path) -> None:
    _login(client)
    workspace, repository = _workspace_repository()
    expected = _configuration_with_medium_score(repository, 0.81)
    repository.replace_scoring_configuration(expected)
    profiles = repository.get_scoring_profiles()
    second_profile = copy.deepcopy(profiles['profiles'][0])
    second_profile.update({'id': 'netcheck-2025', 'name': 'NetCheck 2025'})
    second_profile['configuration']['version'] = 'NetCheck 2025'
    profiles['profiles'].append(second_profile)
    profiles['active_profile_id'] = second_profile['id']
    expected_profiles = repository.replace_scoring_profiles(profiles)

    backup_path = app_module.create_recurring_database_backup({
        'components': ['scoring_configuration'],
        'workspace_ids': [workspace.id],
        'backup_path': str(tmp_path),
        'max_backups': 5,
    })
    assert app_module._backup_archive_components(backup_path) == ['scoring_configuration']

    repository.replace_scoring_profiles({
        'active_profile_id': 'netcheck-2026',
        'profiles': [expected_profiles['profiles'][0]],
    })
    app_module.restore_database_backup(backup_path, ['scoring_configuration'])

    assert repository.get_scoring_profiles() == expected_profiles


def test_deleted_walk_environment_survives_json_archive_restore(client):
    _login(client)
    workspace, repository = _workspace_repository()
    configuration = copy.deepcopy(repository.get_scoring_configuration())
    configuration['scope']['environments']['Indoor'] = {'g_level_1': 'Indoor', 'g_level_2': 'Hall'}
    configuration['scope']['environment_mapping']['Indoor + Hall'] = 'Indoor'
    for metric in configuration['metrics']:
        indoor = copy.deepcopy(metric['contexts']['DriveCity'])
        indoor['max_points'] = 0
        metric['contexts']['Indoor'] = indoor
    configuration['scope']['environments'].pop('Walk')
    configuration['scope']['environment_mapping'].pop('Walk')
    for metric in configuration['metrics']:
        metric['contexts'].pop('Walk')

    repository.replace_scoring_configuration(configuration)
    expected_profiles = repository.get_scoring_profiles()
    archive_payload = app_module._scoring_configuration_archive_payload(workspace)
    exported = json.loads(archive_payload)
    assert 'Walk' not in exported['profiles'][0]['configuration']['scope']['environments']
    assert 'Indoor' in exported['profiles'][0]['configuration']['scope']['environments']

    repository.replace_scoring_configuration(scoring_configuration())
    app_module._restore_workspace_scoring_configuration(workspace, archive_payload)

    assert repository.get_scoring_profiles() == expected_profiles
    assert 'Walk' not in repository.get_scoring_configuration()['scope']['environments']
    assert 'Indoor' in repository.get_scoring_configuration()['scope']['environments']


def test_renamed_environments_survive_profile_and_workspace_database_round_trips(client, tmp_path: Path):
    _login(client)
    workspace, repository = _workspace_repository()
    configuration = repository.get_scoring_configuration()
    original_road_contexts = [copy.deepcopy(metric['contexts']['Drive Connecting Roads']) for metric in configuration['metrics']]
    original_walk_contexts = [copy.deepcopy(metric['contexts']['Walk']) for metric in configuration['metrics']]

    walk = configuration['scope']['environments'].pop('Walk')
    walk['display_name'] = 'Walk QA'
    configuration['scope']['environments']['Walk QA'] = walk
    for metric in configuration['metrics']:
        metric['contexts']['Walk QA'] = metric['contexts'].pop('Walk')
    configuration['scope']['environment_mapping'] = {
        (f"{environment['g_level_1']} + {environment['g_level_2']}"
         if environment.get('g_level_2') else environment['g_level_1']): name
        for name, environment in configuration['scope']['environments'].items()
    }
    repository.replace_scoring_configuration(configuration)
    expected_profiles = repository.get_scoring_profiles()
    expected_configuration = expected_profiles['profiles'][0]['configuration']

    assert 'Walk QA' in expected_configuration['scope']['environments']
    assert 'Walk' not in expected_configuration['scope']['environments']
    assert 'DriveConnectionroad' not in expected_configuration['scope']['environments']
    assert expected_configuration['scope']['environments']['Drive Connecting Roads']['g_level_2'] == 'Connecting Roads'
    assert expected_configuration['scope']['environments']['Walk QA']['display_name'] == 'Walk QA'
    for index, metric in enumerate(expected_configuration['metrics']):
        assert metric['contexts']['Drive Connecting Roads'] == original_road_contexts[index]
        assert metric['contexts']['Walk QA'] == original_walk_contexts[index]
        assert 'Walk' not in metric['contexts']

    exported = client.get('/api/workspace-config/scoring-configuration/export')
    assert exported.status_code == 200
    document = exported.json()
    assert document['version'] == 2
    assert document['profiles'] == expected_profiles['profiles']

    repository.set_workspace_state('scoring_configuration', '')
    imported = client.post('/api/workspace-config/scoring-configuration/import', files={
        'package': ('renamed-scoring-configuration.json', exported.content, 'application/json'),
    })
    assert imported.status_code == 200, imported.text
    assert imported.json() == expected_profiles

    backup_path = app_module.create_recurring_database_backup({
        'components': ['workspace_database'],
        'workspace_ids': [workspace.id],
        'backup_path': str(tmp_path),
        'max_backups': 5,
    })
    repository.set_workspace_state('scoring_configuration', '')
    app_module.restore_database_backup(backup_path, ['workspace_database'])
    restored_profiles = repository.get_scoring_profiles()
    assert restored_profiles == expected_profiles
    restored_configuration = restored_profiles['profiles'][0]['configuration']
    assert 'Walk' not in restored_configuration['scope']['environments']
    assert 'Walk' not in restored_configuration['metrics'][0]['contexts']


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
    assert exported.json()['version'] == 2
    assert exported.json()['profiles'][0]['configuration'] == repository.get_scoring_configuration()
    assert exported.json()['profiles'][0]['configuration']['metrics'][0]['contexts']['DriveCity']['max_points'] == 80


def test_legacy_bare_json_and_v1_zip_import_create_a_single_default_profile(client, tmp_path: Path) -> None:
    _login(client)
    workspace, repository = _workspace_repository()
    configuration = legacy_scoring_configuration()

    response = client.post('/api/workspace-config/scoring-configuration/import', files={
        'package': ('legacy.json', json.dumps(configuration).encode(), 'application/json'),
    })
    assert response.status_code == 200, response.text
    assert response.json()['profiles'] == [default_scoring_profile(configuration)]
    assert response.json()['profiles'][0]['configuration']['scope']['environments']['Walk']['total_points'] == 0

    legacy_archive = tmp_path / 'legacy-scoring-config.zip'
    archive_path = 'workspaces/Imported/scoring-configuration/scoring-configuration.json'
    manifest = app_module.archive_manifest(
        'scoring-configuration', source_workspace={'id': '', 'name': 'Imported'},
        workspace_components=['scoring_configuration'], archive_path=archive_path,
    )
    with zipfile.ZipFile(legacy_archive, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr(archive_path, json.dumps({
            'format': 'dashboard-analytic-scoring-configuration',
            'version': 1,
            'configuration': configuration,
        }))
    legacy_manifest = app_module.read_import_manifest(legacy_archive)
    app_module._apply_import_archive(
        legacy_archive, legacy_manifest, destination_workspace_ids=[workspace.id],
    )
    restored = repository.get_scoring_profiles()
    assert restored['active_profile_id'] == 'netcheck-2026'
    restored_configuration = restored['profiles'][0]['configuration']
    assert restored_configuration['scope']['environments']['Drive Connecting Roads']['g_level_2'] == 'Connecting Roads'
    assert restored_configuration['scope']['environment_mapping']['Drive + Connecting Roads'] == 'Drive Connecting Roads'
    assert restored_configuration['metrics'][0]['contexts']['Drive Connecting Roads'] == (
        default_scoring_profile(configuration)['configuration']['metrics'][0]['contexts']['DriveConnectionroad']
    )


def test_legacy_kpi_ids_migrate_to_sequential_codes_without_changing_gap_order(client):
    _login(client)
    workspace, repository = _workspace_repository()
    legacy = legacy_scoring_configuration()
    legacy_codes = [metric['code'] for metric in legacy['metrics']]
    legacy['gap_priority'] = ['C17', 'C5', *[
        code for code in legacy_codes if code not in {'C5', 'C17'}
    ]]
    raw = json.dumps(legacy)
    repository.set_workspace_state('scoring_configuration', raw)

    profiles = repository.get_scoring_profiles()
    migrated = profiles['profiles'][0]['configuration']

    assert [metric['code'] for metric in migrated['metrics']] == [f'K{index}' for index in range(1, 33)]
    assert migrated['gap_priority'][:2] == ['K12', 'K1']
    assert migrated['next_kpi_number'] == 33
    assert migrated['validation_examples']['mapping_workbook_samples'][0]['kpi_code'] == 'K1'
    assert repository.get_workspace_state('scoring_configuration') == raw
    assert [metric['code'] for metric in legacy['metrics']] == legacy_codes


def test_named_legacy_profile_codes_migrate_without_rewriting_snapshot_validation():
    legacy = legacy_scoring_configuration()
    legacy['gap_priority'] = ['C17', 'C5', *[
        metric['code'] for metric in legacy['metrics'] if metric['code'] not in {'C5', 'C17'}
    ]]
    profiles = validate_scoring_profiles({
        'active_profile_id': 'legacy',
        'profiles': [{'id': 'legacy', 'name': 'Legacy', 'configuration': legacy}],
    })
    historic = validate_scoring_configuration(legacy)

    assert profiles['profiles'][0]['configuration']['metrics'][0]['code'] == 'K1'
    assert profiles['profiles'][0]['configuration']['gap_priority'][:2] == ['K12', 'K1']
    assert historic['metrics'][0]['code'] == 'C5'


def test_legacy_migration_does_not_collide_with_an_existing_sequential_custom_code():
    legacy = legacy_scoring_configuration()
    custom = copy.deepcopy(legacy['metrics'][0])
    custom['code'] = 'K1'
    legacy['metrics'].append(custom)
    legacy['gap_priority'] = [metric['code'] for metric in legacy['metrics']]

    profile = default_scoring_profile(legacy)

    assert profile['configuration']['metrics'][0]['code'] == 'C5'
    assert profile['configuration']['metrics'][-1]['code'] == 'K1'


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
    assert repository.get_scoring_configuration()['metrics'][0]['code'] == 'K1'


def test_unconfigured_workspace_configuration_backup_round_trip(client):
    _login(client)
    workspace = app_module.active_workspace
    repository = Repository(workspace.database_path, app_module.repository.global_db_path,
                            app_module.workspace_registry.registry_path)
    repository.set_workspace_state('scoring_configuration', '')
    payload = app_module._scoring_configuration_archive_payload(workspace)
    assert json.loads(payload)['profiles'] is None
    repository.replace_scoring_configuration(scoring_configuration())
    app_module._restore_workspace_scoring_configuration(workspace, payload)
    assert not repository.get_workspace_state('scoring_configuration')

    legacy_empty_payload = json.dumps({
        'format': 'dashboard-analytic-scoring-configuration',
        'version': 1,
        'configuration': None,
    }).encode('utf-8')
    repository.replace_scoring_configuration(scoring_configuration())
    app_module._restore_workspace_scoring_configuration(workspace, legacy_empty_payload)
    assert not repository.get_workspace_state('scoring_configuration')
