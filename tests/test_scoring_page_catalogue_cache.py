from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import src.DashboardAnalytic as app_module
from src.modules.repository import Repository, local_now_iso
from tests.scoring_fixtures import scoring_configuration


def _login(client) -> None:
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.parametrize(
    ('catalogue_state', 'notice_expected'),
    [('cached', False), ('missing', True), ('incomplete', True)],
)
def test_scoring_page_uses_cached_catalogues_without_scanning_cdr_rows(
    client, tmp_path: Path, monkeypatch, catalogue_state: str, notice_expected: bool,
) -> None:
    _login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    repository = Repository(
        workspace.database_path,
        global_db_path=app_module.repository.db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    repository.initialize()
    repository.replace_scoring_configuration(scoring_configuration())

    dataset_name = f'{catalogue_state}_NSA_Data.csv'
    source_path = tmp_path / dataset_name
    source_path.write_text('source', encoding='utf-8')
    dataset_id, _created = repository.add_dataset(dataset_name, str(source_path), 'admin')
    frame = pd.DataFrame({
        'Campaign': ['2026-Q2'], 'Operator': ['EE'], 'Vendor': ['Nokia'],
        'G_Level_2': ['North'], 'G_Level_4': ['Leeds'], 'score': [4.0],
    })
    repository.replace_dataset_rows(dataset_id, frame)
    repository.update_dataset_profile(
        dataset_id, status='ready', progress=100, dataset_kind='data', nr_mode='NSA',
        row_count=len(frame), column_count=len(frame.columns), processed_at=local_now_iso(),
    )
    if catalogue_state != 'missing':
        repository.replace_cdr_catalogue(
            dataset_id,
            vendors=['Nokia'], regions=['North'], cities=['Leeds'],
            vendors_only=['Nokia'] if catalogue_state == 'cached' else None,
            campaigns=['2026-Q2'] if catalogue_state == 'cached' else None,
            operators=['EE'] if catalogue_state == 'cached' else None,
        )

    def fail_if_rows_are_scanned(*_args, **_kwargs):
        raise AssertionError('Opening Scoring must not scan materialized CDR rows.')

    monkeypatch.setattr(Repository, 'list_dataset_row_columns', fail_if_rows_are_scanned)
    monkeypatch.setattr(Repository, 'load_dataset_rows', fail_if_rows_are_scanned)
    monkeypatch.setattr(app_module, '_distinct_cdr_row_values', fail_if_rows_are_scanned)

    response = client.get('/scoring')

    assert response.status_code == 200
    assert dataset_name in response.text
    notice = 'Some CDR filter catalogues are incomplete.'
    assert (notice in response.text) is notice_expected
    if notice_expected:
        assert dataset_name in response.text.split(notice, 1)[1]
    else:
        assert '2026-Q2' in response.text
