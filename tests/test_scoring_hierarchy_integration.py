from __future__ import annotations

import json
from pathlib import Path

import src.DriveTestAnalyzer as app_module
from src.modules import scoring_jobs
from tests.test_scoring_api import scoring_api


DEFAULT_HIERARCHY = ['Operator', 'Vendor', 'Region', 'City', 'Campaign']
CUSTOM_HIERARCHY = ['Campaign', 'Operator', 'Region', 'Vendor', 'City']


def test_scoring_hierarchy_controls_and_saved_job_order(scoring_api):
    client = scoring_api['client']
    page = client.get('/scoring')
    assert page.status_code == 200
    assert 'value="Dataset Type" data-aggregation-level' not in page.text
    for selector in ('data-aggregation-level', 'data-scoring-context-filter'):
        positions = [page.text.index(f'{selector}="{level}"') if selector.endswith('filter')
                     else page.text.index(f'value="{level}" data-aggregation-level') for level in DEFAULT_HIERARCHY]
        assert positions == sorted(positions)
    configuration = scoring_api['repository'].get_scoring_configuration()
    configuration['aggregation_hierarchy'] = CUSTOM_HIERARCHY
    saved = client.put('/api/workspace-config/scoring-configuration', json=configuration)
    assert saved.status_code == 200, saved.text
    page = client.get('/scoring')
    positions = [page.text.index(f'data-scoring-context-filter="{level}"') for level in CUSTOM_HIERARCHY]
    assert positions == sorted(positions)
    payload = {'dataset_ids': scoring_api['complete_dataset_ids'], 'nr_mode': 'NSA',
               'aggregation_levels': ['Region', 'Operator', 'Campaign']}
    response = client.post('/api/scoring/jobs', json=payload)
    assert response.status_code == 200, response.text
    job = response.json()['job']
    assert job['aggregation_levels'] == ['Campaign', 'Operator', 'Region']
    assert job['aggregation_contract_version'] == 2
    assert job['aggregation_hierarchy'] == CUSTOM_HIERARCHY
    configuration['aggregation_hierarchy'] = DEFAULT_HIERARCHY
    assert client.put('/api/workspace-config/scoring-configuration', json=configuration).status_code == 200
    historical = scoring_jobs.get_scoring_job(scoring_api['repository'], job['id'])
    assert historical['aggregation_hierarchy'] == CUSTOM_HIERARCHY
    assert historical['configuration']['aggregation_hierarchy'] == CUSTOM_HIERARCHY


def test_hierarchy_round_trip_json_zip_and_configuration_backup(scoring_api, tmp_path: Path):
    client, repository = scoring_api['client'], scoring_api['repository']
    configuration = repository.get_scoring_configuration()
    configuration['aggregation_hierarchy'] = CUSTOM_HIERARCHY
    assert client.put('/api/workspace-config/scoring-configuration', json=configuration).status_code == 200
    document = client.get('/api/workspace-config/scoring-configuration/export').json()
    assert document['profiles'][0]['configuration']['aggregation_hierarchy'] == CUSTOM_HIERARCHY
    workspace = app_module.active_workspace
    package = tmp_path / 'scoring-hierarchy.zip'
    app_module._build_single_export_archive_file('scoring-configuration', package, [workspace.id])
    manifest = app_module.read_import_manifest(package)
    backup = app_module.create_recurring_database_backup({
        'components': ['scoring_configuration'], 'workspace_ids': [workspace.id],
        'backup_path': str(tmp_path), 'max_backups': 5,
    })
    default = dict(configuration, aggregation_hierarchy=DEFAULT_HIERARCHY)
    repository.replace_scoring_configuration(default)
    app_module._apply_import_archive(package, manifest, destination_workspace_ids=[workspace.id])
    assert repository.get_scoring_configuration()['aggregation_hierarchy'] == CUSTOM_HIERARCHY
    repository.replace_scoring_configuration(default)
    app_module.restore_database_backup(backup, ['scoring_configuration'])
    assert repository.get_scoring_configuration()['aggregation_hierarchy'] == CUSTOM_HIERARCHY
    repository.replace_scoring_configuration(default)
    imported = client.post('/api/workspace-config/scoring-configuration/import', files={
        'package': ('hierarchy.json', json.dumps(document).encode(), 'application/json'),
    })
    assert imported.status_code == 200, imported.text
    assert imported.json()['profiles'][0]['configuration']['aggregation_hierarchy'] == CUSTOM_HIERARCHY


def test_reporting_follows_scoring_in_module_and_help_navigation(scoring_api):
    client = scoring_api['client']
    token = 'scoring-navigation-super-admin'
    app_module.SESSIONS[token] = app_module.SessionUser(username='super', role='super-admin')
    client.cookies.set(app_module.SESSION_COOKIE, token)
    page = client.get('/scoring')
    assert page.status_code == 200
    main_tabs = page.text.split('class="module-tabs-primary"', 1)[1].split('class="module-tabs-secondary"', 1)[0]
    assert main_tabs.index('href="/scoring"') < main_tabs.index('href="/reporting"') < main_tabs.index('href="/reporting-old"')
    modules = page.text.split('aria-label="Main modules"', 1)[1].split('</nav>', 1)[0]
    assert modules.index('href="/scoring"') < modules.index('href="/reporting"') < modules.index('href="/reporting-old"')
    documents = client.get('/api/documents/help-index').json()['documents']
    paths = [document['relative_path'] for document in documents]
    # Non-Qualified Calls sits between Scoring and Reporting, as in the main tabs.
    assert paths.index('non-qualified-calls.md') == paths.index('scoring-gap-analysis.md') + 1
    assert paths.index('reporting.md') == paths.index('non-qualified-calls.md') + 1
    assert paths.index('reporting-old.md') == paths.index('reporting.md') + 1
    help_page = client.get('/documents/view/help')
    group_function = help_page.text.split('function helpDocumentGroup(relativePath) {', 1)[1].split("return 'Main Modules';", 1)[0]
    assert "'scoring-gap-analysis.md'" in group_function
