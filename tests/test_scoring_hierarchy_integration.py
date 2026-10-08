from __future__ import annotations

import json
import re

import src.DriveTestAnalyzer as app_module
from src.modules import scoring_jobs
from tests.test_scoring_api import scoring_api


DEFAULT_HIERARCHY = ['Operator', 'Vendor', 'Region', 'City', 'Campaign']
CUSTOM_HIERARCHY = ['Campaign', 'Operator', 'Region', 'Vendor', 'City']
# Cluster follows Region when a hierarchy does not place it.
SAVED_HIERARCHY = ['Campaign', 'Operator', 'Region', 'Cluster', 'Vendor', 'City']


def page_hierarchy(client) -> list[str]:
    page = client.get('/scoring')
    config = re.search(r'<script type="application/json" data-scoring-config>(.*?)</script>', page.text, re.DOTALL)
    return json.loads(config.group(1))['aggregation_hierarchy']


def test_scoring_hierarchy_controls_and_saved_job_order(scoring_api):
    client = scoring_api['client']
    page = client.get('/scoring')
    assert page.status_code == 200
    assert 'value="Dataset Type" data-aggregation-level' not in page.text
    for selector in ('data-aggregation-level', 'data-scoring-context-filter'):
        positions = [page.text.index(f'{selector}="{level}"') if selector.endswith('filter')
                     else page.text.index(f'value="{level}" data-aggregation-level') for level in DEFAULT_HIERARCHY]
        assert positions == sorted(positions)
    saved = client.put('/api/scoring/aggregation-hierarchy', json={'levels': CUSTOM_HIERARCHY})
    assert saved.status_code == 200, saved.text
    assert saved.json()['aggregation_hierarchy'] == SAVED_HIERARCHY
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
    assert job['aggregation_hierarchy'] == SAVED_HIERARCHY
    assert client.put('/api/scoring/aggregation-hierarchy', json={'levels': DEFAULT_HIERARCHY}).status_code == 200
    historical = scoring_jobs.get_scoring_job(scoring_api['repository'], job['id'])
    assert historical['aggregation_hierarchy'] == SAVED_HIERARCHY


def test_hierarchy_is_an_application_setting_outside_the_methodologies(scoring_api):
    client, repository = scoring_api['client'], scoring_api['repository']
    assert client.put('/api/scoring/aggregation-hierarchy', json={'levels': ['Operator', 'Operator']}).status_code == 400
    assert client.put('/api/scoring/aggregation-hierarchy', json={'levels': CUSTOM_HIERARCHY}).status_code == 200
    assert page_hierarchy(client) == SAVED_HIERARCHY
    # Methodologies neither save nor export a hierarchy, and a hierarchy in an imported methodology is ignored.
    configuration = repository.get_scoring_configuration()
    assert 'aggregation_hierarchy' not in configuration
    configuration['aggregation_hierarchy'] = DEFAULT_HIERARCHY
    assert client.put('/api/workspace-config/scoring-configuration', json=configuration).status_code == 200
    assert 'aggregation_hierarchy' not in repository.get_scoring_configuration()
    document = client.get('/api/workspace-config/scoring-configuration/export').json()
    assert 'aggregation_hierarchy' not in document['profiles'][0]['configuration']
    assert page_hierarchy(client) == SAVED_HIERARCHY


def test_reporting_follows_scoring_in_module_and_help_navigation(scoring_api):
    client = scoring_api['client']
    # Reporting (old) is off by default; turn it on to check its place in the navigation.
    rules = app_module.feature_activation_settings()
    rules['reporting-old'] = {'default': 'all'}
    app_module.save_feature_activation_settings(rules)
    token = 'scoring-navigation-super-admin'
    app_module.SESSIONS[token] = app_module.SessionUser(username='super', role='super-admin')
    client.cookies.set(app_module.SESSION_COOKIE, token)
    page = client.get('/scoring')
    assert page.status_code == 200
    main_tabs = page.text.split('class="module-tabs-primary"', 1)[1].split('class="module-tabs-secondary"', 1)[0]
    assert main_tabs.index('href="/e2e-dashboards"') < main_tabs.index('href="/reporting-old"') < main_tabs.index('href="/scoring"') < main_tabs.index('href="/reporting"')
    modules = page.text.split('aria-label="Main modules"', 1)[1].split('</nav>', 1)[0]
    assert modules.index('href="/e2e-dashboards"') < modules.index('href="/reporting-old"') < modules.index('href="/scoring"') < modules.index('href="/reporting"')
    documents = client.get('/api/documents/help-index').json()['documents']
    paths = [document['relative_path'] for document in documents]
    # Network Insights follows Scoring, then Non-Qualified Calls and Reporting, as in the main tabs.
    assert paths.index('network-insights.md') == paths.index('scoring-gap-analysis.md') + 1
    assert paths.index('non-qualified-calls.md') == paths.index('network-insights.md') + 1
    assert paths.index('reporting.md') == paths.index('non-qualified-calls.md') + 1
    # Reporting (old) follows E2E Dashboards, as in the main tabs.
    assert paths.index('reporting-old.md') == paths.index('e2e-dashboards.md') + 1
    assert paths.index('scoring-gap-analysis.md') == paths.index('reporting-old.md') + 1
    help_page = client.get('/documents/view/help')
    group_function = help_page.text.split('function helpDocumentGroup(relativePath) {', 1)[1].split("return 'Main Modules';", 1)[0]
    assert "'scoring-gap-analysis.md'" in group_function
