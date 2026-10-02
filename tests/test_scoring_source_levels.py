"""Cached CDR choices for scoring environment source selectors."""
import sqlite3

import pandas as pd

import src.DashboardAnalytic as app_module
from src.modules.repository import Repository
from tests.test_scoring_api import scoring_api


def test_source_level_catalogues_preserve_existing_fields_and_database_backup(scoring_api, tmp_path):
    repository = scoring_api['repository']
    dataset_id = scoring_api['dataset_id']
    frame = pd.DataFrame({'G_Level_1': ['Drive', ' Walk ', None, 'Drive'],
                          'G_Level_2': ['City', 'Train', '', 'City'], 'Operator': ['EE'] * 4})
    app_module.cache_cdr_catalogue(dataset_id, frame, repository)
    expected = {'G_Level_1': ['Drive', 'Walk'], 'G_Level_2': ['City', 'Train']}
    assert repository.cdr_source_level_values([dataset_id]) == expected
    repository.replace_cdr_catalogue(dataset_id, vendors=['Vendor'], regions=['Region'], cities=['City'])
    assert repository.cdr_source_level_values([dataset_id]) == expected
    assert repository.cdr_catalogues_by_dataset([dataset_id])[dataset_id]['operators'] == ['EE']
    destination = tmp_path / 'restored.db'
    with sqlite3.connect(repository.db_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    restored = Repository(destination)
    restored.initialize()
    assert restored.cdr_source_level_values([dataset_id]) == expected
    assert restored.missing_cdr_source_level_ids([dataset_id]) == []


def test_legacy_source_choices_backfill_once_and_subsequent_requests_only_read_cache(scoring_api, monkeypatch):
    client = scoring_api['client']
    repository = scoring_api['repository']
    response = client.get('/api/workspace-config/scoring-source-levels')
    assert response.status_code == 200
    assert set(response.json()) == {'G_Level_1', 'G_Level_2'}
    assert repository.missing_cdr_source_level_ids(scoring_api['complete_dataset_ids']) == []

    def fail_if_scanned(*args, **kwargs):
        raise AssertionError('Cached source choices must not scan CDR rows again.')

    monkeypatch.setattr(app_module, '_distinct_cdr_row_values', fail_if_scanned)
    monkeypatch.setattr(Repository, 'list_dataset_row_columns', fail_if_scanned)
    repeated = client.get('/api/workspace-config/scoring-source-levels')
    assert repeated.status_code == 200
    assert repeated.json() == response.json()
    assert repeated.headers['cache-control'] == 'no-store'


def test_existing_catalogue_schema_adds_source_level_columns(scoring_api):
    repository = scoring_api['repository']
    with repository.connection() as connection:
        connection.execute('ALTER TABLE cdr_catalogues DROP COLUMN g_level_1_json')
        connection.execute('ALTER TABLE cdr_catalogues DROP COLUMN g_level_2_json')
    repository.initialize()
    with repository.connection() as connection:
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(cdr_catalogues)')}
    assert {'g_level_1_json', 'g_level_2_json'} <= columns
