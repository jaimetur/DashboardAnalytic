from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import src.DashboardAnalytic as app_module
from src.modules import scoring_jobs
from src.modules.repository import Repository, local_now_iso
from tests.scoring_fixtures import scoring_configuration


def _login(client) -> None:
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert response.status_code == 303


def _add_ready_cdr(
    repository: Repository,
    tmp_path: Path,
    *,
    name: str,
    kind: str,
    nr_mode: str = 'NSA',
    campaign: str = '2026-Q2',
) -> int:
    source = tmp_path / name
    source.write_text('test source', encoding='utf-8')
    dataset_id, _created = repository.add_dataset(name, str(source), 'admin')
    rows = pd.DataFrame({
        'Operator': ['EE'],
        'Campaign': [campaign],
        'score': [4.2],
    })
    repository.replace_dataset_rows(dataset_id, rows)
    repository.update_dataset_profile(
        dataset_id,
        status='ready', progress=100, dataset_kind=kind, nr_mode=nr_mode,
        row_count=len(rows), column_count=len(rows.columns), processed_at=local_now_iso(),
    )
    repository.replace_cdr_catalogue(
        dataset_id, vendors=[], regions=[], cities=[], campaigns=[campaign],
    )
    return dataset_id


@pytest.fixture()
def cdr_selection_workspace(client, tmp_path, monkeypatch):
    _login(client)
    workspace = app_module.active_workspace
    repository = Repository(
        workspace.database_path,
        global_db_path=app_module.repository.db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    repository.initialize()
    repository.replace_scoring_configuration(scoring_configuration())
    submitted = []

    def record_submission(task_repository, callback, *args, **kwargs):
        submitted.append((task_repository, callback, args, kwargs))

    monkeypatch.setattr(app_module, '_submit_workspace_job', record_submission)
    dataset_ids = [
        _add_ready_cdr(repository, tmp_path, name='UK_Q2_NSA_Data.csv', kind='data'),
        _add_ready_cdr(repository, tmp_path, name='UK_Q2_NSA_Voice.csv', kind='voice'),
        _add_ready_cdr(repository, tmp_path, name='UK_Q2_NSA_Speech.csv', kind='speech'),
    ]
    return {
        'client': client,
        'repository': repository,
        'dataset_ids': dataset_ids,
        'submitted': submitted,
        'add_cdr': lambda **kwargs: _add_ready_cdr(repository, tmp_path, **kwargs),
    }


def test_manual_scoring_requires_all_three_cdr_types_before_queueing(cdr_selection_workspace):
    client = cdr_selection_workspace['client']
    data_id, voice_id, speech_id = cdr_selection_workspace['dataset_ids']

    for selected_ids, missing_label in (([data_id], 'Voice, Speech'), ([data_id, voice_id], 'Speech')):
        response = client.post('/api/scoring/jobs', json={
            'dataset_ids': selected_ids,
            'aggregation_levels': ['Operator'],
            'nr_mode': 'NSA',
        })
        assert response.status_code == 400
        assert missing_label in response.json()['detail']

    assert scoring_jobs.list_scoring_jobs(cdr_selection_workspace['repository']) == []
    assert cdr_selection_workspace['submitted'] == []

    accepted = client.post('/api/scoring/jobs', json={
        'dataset_ids': [data_id, voice_id, speech_id],
        'aggregation_levels': ['Operator'],
        'nr_mode': 'NSA',
    })
    assert accepted.status_code == 200, accepted.text
    assert set(accepted.json()['job']['dataset_ids']) == {data_id, voice_id, speech_id}


def test_latest_companions_match_anchor_campaign_and_ignore_profile_recency(cdr_selection_workspace):
    repository = cdr_selection_workspace['repository']
    anchor_id, old_voice_id, speech_id = cdr_selection_workspace['dataset_ids']
    newer_voice_id = cdr_selection_workspace['add_cdr'](
        name='UK_Q2_NSA_Voice_New.csv', kind='voice',
    )
    unrelated_voice_id = cdr_selection_workspace['add_cdr'](
        name='UK_Q1_NSA_Voice.csv', kind='voice', campaign='2026-Q1',
    )
    with repository.connection() as connection:
        connection.execute(
            "UPDATE dataset_profiles SET updated_at = '2999-01-01T00:00:00' WHERE dataset_id = ?",
            (old_voice_id,),
        )

    selected = scoring_jobs.select_latest_companion_cdrs(repository, anchor_id)

    assert selected == [anchor_id, newer_voice_id, speech_id]
    assert unrelated_voice_id not in selected


def test_auto_scoring_waits_for_matching_campaign_companions(cdr_selection_workspace):
    repository = cdr_selection_workspace['repository']
    newer_data_id = cdr_selection_workspace['add_cdr'](
        name='UK_Q3_NSA_Data.csv', kind='data', campaign='2026-Q3',
    )

    app_module.queue_dataset_scoring(repository, newer_data_id, 'admin')

    assert scoring_jobs.list_scoring_jobs(repository) == []
    assert cdr_selection_workspace['submitted'] == []


def test_scoring_api_rejects_mixed_campaign_coverage(cdr_selection_workspace):
    client = cdr_selection_workspace['client']
    data_id, voice_id, _speech_id = cdr_selection_workspace['dataset_ids']
    speech_id = cdr_selection_workspace['add_cdr'](
        name='UK_Q1_NSA_Speech.csv', kind='speech', campaign='2026-Q1',
    )

    response = client.post('/api/scoring/jobs', json={
        'dataset_ids': [data_id, voice_id, speech_id],
        'aggregation_levels': ['Operator'],
        'nr_mode': 'NSA',
    })

    assert response.status_code == 400
    assert 'must cover each campaign with Data, Voice and Speech' in response.json()['detail']
    assert scoring_jobs.list_scoring_jobs(cdr_selection_workspace['repository']) == []
