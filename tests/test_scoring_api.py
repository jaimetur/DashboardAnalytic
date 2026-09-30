from __future__ import annotations

import csv
from copy import deepcopy
from io import BytesIO
from io import StringIO
import json
from pathlib import Path
import sqlite3
import time
from types import ModuleType

import pandas as pd
import pytest
from pptx import Presentation

import src.DashboardAnalytic as app_module
from src.modules import scoring_jobs
from src.modules.repository import Repository, local_now_iso
from tests.scoring_fixtures import scoring_configuration


def _login(client) -> None:
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert response.status_code == 303


def _mark_scoring_result_as_legacy(repository: Repository, job_id: int) -> None:
    result = scoring_jobs.get_scoring_job(repository, job_id, include_result=True)['result']
    result.pop('gap_direction', None)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            'UPDATE scoring_jobs SET result_json = ? WHERE id = ?',
            (json.dumps(result, ensure_ascii=False), job_id),
        )


def _add_ready_cdr(
    repository: Repository,
    tmp_path: Path,
    *,
    name: str,
    nr_mode: str = 'NSA',
    kind: str = 'data',
    campaign: str = '2026-Q2',
) -> int:
    source = tmp_path / name
    source.write_text('test source', encoding='utf-8')
    dataset_id, _created = repository.add_dataset(name, str(source), 'admin')
    rows = pd.DataFrame({
        'Operator': ['EE', 'O2'],
        'Region': ['North', 'North'],
        'City': ['Leeds', 'Leeds'],
        'Vendor': ['Nokia', 'Nokia'],
        'Dataset_Kind': [kind, kind],
        'Environment': ['City', 'City'],
        'Campaign': [campaign, campaign],
        'score': [4.2, 3.6],
    })
    repository.replace_dataset_rows(dataset_id, rows)
    repository.update_dataset_profile(
        dataset_id,
        status='ready', progress=100, dataset_kind=kind, nr_mode=nr_mode,
        row_count=len(rows), column_count=len(rows.columns), processed_at=local_now_iso(),
    )
    repository.replace_cdr_catalogue(
        dataset_id, vendors=['Nokia'], regions=['North'], cities=['Leeds'], campaigns=[campaign],
    )
    return dataset_id


@pytest.fixture()
def scoring_api(client, tmp_path, monkeypatch):
    _login(client)
    workspace = app_module.active_workspace
    repository = Repository(
        workspace.database_path,
        global_db_path=app_module.repository.db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    repository.initialize()
    repository.replace_scoring_configuration(scoring_configuration())

    calls = []
    engine = ModuleType('src.modules.scoring')
    engine.METHOD_VERSION = 'scoring-api-test-v1'
    engine.required_input_columns = lambda kind, levels: [*levels, 'score']

    def calculate_scoring(frames, levels, *, baseline_operator, configuration=None):
        calls.append({'frames': frames, 'levels': levels, 'baseline_operator': baseline_operator})
        scoring = [{
            'campaign': '2026-Q2', 'region': 'North', 'city': 'Leeds', 'vendor': 'Nokia',
            'dataset_type': 'data', 'environment': 'City', 'operator': operator,
            'kpi': 'Download Throughput', 'category': 'Data', 'value': 4.2,
            'score': 4.2, 'weighted_points': 4.2, 'max_points': 5.0, 'sample_count': 1,
        } for operator in ('EE', 'O2', 'Three UK', 'Vodafone UK')]
        charts = [{
            'campaign': '2026-Q2', 'region': 'North', 'city': 'Leeds', 'vendor': 'Nokia',
            'dataset_type': 'data', 'environment': 'City', 'operator': 'EE',
            'category': 'Overall', 'weighted_points': 4.2, 'max_points': 5.0, 'complete': True,
        }]
        gap = [{'operator': 'O2', 'baseline_operator': baseline_operator, 'gap_points': 0.6}]
        return {'scoring': scoring, 'charts': charts, 'gap': gap, 'warnings': []}

    engine.calculate_scoring = calculate_scoring
    monkeypatch.setattr(scoring_jobs, '_scoring_engine', lambda: engine)
    submitted = []

    def record_submission(task_repository, callback, *args, **kwargs):
        submitted.append((task_repository, callback, args, kwargs))
        return None

    monkeypatch.setattr(app_module, '_submit_workspace_job', record_submission)
    dataset_id = _add_ready_cdr(repository, tmp_path, name='UK_Q2_2026_NSA_Data.csv')
    voice_id = _add_ready_cdr(repository, tmp_path, name='UK_Q2_2026_NSA_Voice.csv', kind='voice')
    speech_id = _add_ready_cdr(repository, tmp_path, name='UK_Q2_2026_NSA_Speech.csv', kind='speech')
    return {
        'client': client,
        'repository': repository,
        'calls': calls,
        'submitted': submitted,
        'dataset_id': dataset_id,
        'complete_dataset_ids': [dataset_id, voice_id, speech_id],
        'add_ready_cdr': lambda **kwargs: _add_ready_cdr(repository, tmp_path, **kwargs),
        'tmp_path': tmp_path,
    }


def test_scoring_page_requires_login_and_renders_workspace_controls(client, scoring_api):
    client.get('/logout', follow_redirects=False)
    assert client.get('/scoring', follow_redirects=False).status_code == 303
    _login(client)
    page = client.get('/scoring')

    assert page.status_code == 200
    assert 'Scoring &amp; GAP Analysis' in page.text
    assert 'href="/scoring"' in page.text
    assert 'data-scoring-workspace' in page.text
    assert 'UK_Q2_2026_NSA_Data.csv' in page.text
    assert 'value="EE"' in page.text and 'value="O2"' in page.text
    assert '2026-Q2' in page.text
    assert 'Operator is required' in page.text
    assert 'data-calculate-scoring' in page.text
    assert 'data-recalculate-scoring' in page.text
    assert 'Scoring Tables' in page.text and 'Scoring Chart' in page.text and 'GAP Analysis' in page.text
    assert 'Best Network Chart' in page.text


def test_scoring_baseline_options_follow_mapping_without_scanning_cdr_rows(scoring_api, monkeypatch):
    repository = scoring_api['repository']
    repository.replace_operator_mapping_groups([
        {'canonical': 'O2', 'aliases': ['O2 UK'], 'color': '#112233'},
        {'canonical': 'EE', 'aliases': ['EE UK'], 'color': '#445566'},
    ])

    def fail_if_cdr_rows_are_scanned(*_args, **_kwargs):
        raise AssertionError('Opening Scoring must not query dataset rows.')

    monkeypatch.setattr(Repository, 'list_distinct_dataset_row_values', fail_if_cdr_rows_are_scanned)
    page = scoring_api['client'].get('/scoring')

    assert page.status_code == 200
    baseline_select = page.text.split('<select data-baseline-operator', 1)[1].split('</select>', 1)[0]
    assert baseline_select.index('value="O2"') < baseline_select.index('value="EE"')
    assert 'value="O2" data-operator-color="#112233"' in baseline_select
    assert 'value="EE" data-operator-color="#445566"' in baseline_select


def test_scoring_api_validates_auth_mode_and_missing_jobs(client, scoring_api):
    assert client.get('/api/scoring/jobs').status_code == 200
    assert client.get('/api/scoring/jobs/999999').status_code == 404
    assert client.get('/scoring/jobs/999999/export/scoring').status_code == 404

    sa_id = _add_ready_cdr(
        scoring_api['repository'], scoring_api['tmp_path'], name='UK_Q2_2026_SA_Data.csv', nr_mode='SA',
    )
    response = client.post('/api/scoring/jobs', json={
        'dataset_ids': [scoring_api['dataset_id'], sa_id],
        'aggregation_levels': ['Operator'], 'nr_mode': 'NSA',
    })
    assert response.status_code == 400
    assert 'does not match the selected NSA NR Mode' in response.json()['detail']

    client.get('/logout', follow_redirects=False)
    assert client.get('/scoring', follow_redirects=False).status_code == 303
    assert client.get('/api/scoring/jobs').status_code == 401


def test_scoring_configuration_api_round_trips_complete_validated_document(scoring_api):
    client = scoring_api['client']
    repository = scoring_api['repository']
    original = repository.get_scoring_configuration()

    fetched = client.get('/api/workspace-config/scoring-configuration')
    assert fetched.status_code == 200
    assert fetched.json() == original
    assert 'configuration' not in fetched.json()

    updated = deepcopy(original)
    updated['gap_priority'] = list(reversed(updated['gap_priority']))
    saved = client.put('/api/workspace-config/scoring-configuration', json=updated)
    assert saved.status_code == 200, saved.text
    assert saved.json() == repository.get_scoring_configuration()
    assert saved.json()['gap_priority'] == updated['gap_priority']

    invalid = deepcopy(updated)
    invalid['gap_priority'].pop()
    rejected = client.put('/api/workspace-config/scoring-configuration', json=invalid)
    assert rejected.status_code == 400
    assert repository.get_scoring_configuration() == saved.json()


def test_workspace_config_renders_kpi_and_gap_priority_panels(scoring_api):
    page = scoring_api['client'].get('/workspace-config')

    assert page.status_code == 200
    assert '<h2>Scoring KPI Configuration</h2>' in page.text
    assert '<h2>GAP KPI Priority</h2>' in page.text
    assert 'data-scoring-environment' in page.text
    assert 'data-scoring-kpi-rows' in page.text
    assert 'data-scoring-priority-rows' in page.text
    assert '/static/js/scoring_config.js?v=' in page.text
    assert 'data-no-persist' in page.text
    assert 'Import or export this configuration in Admin' in page.text


def test_scoring_job_results_cache_force_and_exports(scoring_api):
    client = scoring_api['client']
    dataset_id = scoring_api['dataset_id']
    payload = {
        'dataset_ids': scoring_api['complete_dataset_ids'],
        'aggregation_levels': ['Operator', 'Region'],
        'nr_mode': 'NSA',
        'baseline_operator': 'EE',
    }
    created = client.post('/api/scoring/jobs', json=payload)
    assert created.status_code == 200, created.text
    job_id = created.json()['job']['id']
    assert created.json()['job']['status'] == 'queued'
    assert len(scoring_api['submitted']) == 1

    unfinished_export = client.get(f'/scoring/jobs/{job_id}/export/scoring')
    assert unfinished_export.status_code == 409

    completed = scoring_jobs.run_scoring_job(scoring_api['repository'], job_id)
    assert completed['status'] == 'completed'
    assert scoring_api['calls'][0]['levels'] == ['Operator', 'Region']
    assert scoring_api['calls'][0]['baseline_operator'] == 'EE'

    cached = client.post('/api/scoring/jobs', json=payload)
    assert cached.status_code == 200
    assert cached.json()['cached'] is True
    assert cached.json()['job']['id'] == job_id
    assert len(scoring_api['submitted']) == 1

    _mark_scoring_result_as_legacy(scoring_api['repository'], job_id)

    scoring_api['repository'].replace_operator_mapping_groups([
        {'canonical': 'Three UK', 'aliases': ['3'], 'color': '#AABBCC'},
        {'canonical': 'O2', 'aliases': ['O2 UK'], 'color': '#112233'},
        {'canonical': 'Vodafone UK', 'aliases': ['VF'], 'color': '#445566'},
        {'canonical': 'EE', 'aliases': ['EE (UK)'], 'color': '#778899'},
    ])

    result = client.get(f'/api/scoring/jobs/{job_id}')
    assert result.status_code == 200
    assert result.json()['job']['status'] == 'completed'
    assert result.json()['scoring'][0]['weighted_points'] == 4.2
    assert result.json()['charts'][0]['category'] == 'Overall'
    assert result.json()['gap'][0]['gap_points'] == -0.6
    assert result.json()['gap_direction'] == 'operator_minus_reference'
    stored_result = scoring_jobs.get_scoring_job(scoring_api['repository'], job_id, include_result=True)['result']
    assert stored_result['gap'][0]['gap_points'] == 0.6
    assert 'gap_direction' not in stored_result
    assert [row['operator'] for row in result.json()['scoring']] == ['EE', 'O2', 'Three UK', 'Vodafone UK']
    score_table = result.json()['views']['score_tables'][0]
    assert score_table['operators'] == ['Three UK', 'O2', 'Vodafone UK', 'EE']
    assert score_table['operator_styles']['Three UK']['color'] == '#AABBCC'
    assert score_table['operator_styles']['EE']['color'] == '#778899'

    csv_response = client.get(f'/scoring/jobs/{job_id}/export/scoring')
    assert csv_response.status_code == 200
    assert csv_response.headers['content-type'].startswith('text/csv')
    assert 'Download Throughput' in csv_response.content.decode('utf-8-sig')
    gap_csv = client.get(f'/scoring/jobs/{job_id}/export/gap')
    assert gap_csv.status_code == 200
    assert 'gap_points' in gap_csv.content.decode('utf-8-sig')
    gap_csv_rows = pd.read_csv(StringIO(gap_csv.content.decode('utf-8-sig')))
    assert gap_csv_rows.loc[0, 'gap_points'] == -0.6

    ppt_response = client.get(f'/scoring/jobs/{job_id}/export/ppt')
    assert ppt_response.status_code == 200, ppt_response.text
    presentation = Presentation(BytesIO(ppt_response.content))
    slide_text = '\n'.join(
        shape.text for slide in presentation.slides for shape in slide.shapes if shape.has_text_frame
    )
    assert 'Scoring & GAP Analysis' in slide_text
    assert '2026-Q2' in slide_text
    scoring_slide = next(
        slide for slide in presentation.slides
        if any(shape.has_text_frame and 'Scoring Tables' in shape.text for shape in slide.shapes)
    )
    scoring_table = next(shape.table for shape in scoring_slide.shapes if shape.has_table)
    # New multi-level jobs use nested headers; legacy GAP normalization does not change the hierarchy contract.
    assert [scoring_table.cell(0, column).text for column in range(4, 12, 2)] == [
        'Three UK', 'O2', 'Vodafone UK', 'EE',
    ]
    assert all(scoring_table.cell(1, column).text == 'North' for column in range(4, 12, 2))
    assert str(scoring_table.cell(0, 4).fill.fore_color.rgb) == 'AABBCC'

    forced = client.post('/api/scoring/jobs', json={**payload, 'force': True})
    assert forced.status_code == 200
    assert forced.json()['job']['id'] != job_id
    assert forced.json()['cached'] is False
    assert len(scoring_api['submitted']) == 2


def test_scoring_ppt_export_normalizes_legacy_gap_without_mutating_saved_result(scoring_api, monkeypatch):
    client = scoring_api['client']
    response = client.post('/api/scoring/jobs', json={
        'dataset_ids': scoring_api['complete_dataset_ids'],
        'aggregation_levels': ['Operator'],
        'nr_mode': 'NSA',
        'baseline_operator': 'EE',
    })
    assert response.status_code == 200, response.text
    job_id = response.json()['job']['id']
    scoring_jobs.run_scoring_job(scoring_api['repository'], job_id)
    _mark_scoring_result_as_legacy(scoring_api['repository'], job_id)

    from src.modules import scoring_exports
    captured = {}

    def capture_export(job, result, *_args, **_kwargs):
        captured['result'] = deepcopy(result)
        return b'ppt'

    monkeypatch.setattr(scoring_exports, 'export_scoring_powerpoint', capture_export)
    exported = client.get(f'/scoring/jobs/{job_id}/export/ppt')
    assert exported.status_code == 200
    assert exported.content == b'ppt'
    assert captured['result']['gap'][0]['gap_points'] == -0.6
    assert captured['result']['gap_direction'] == 'operator_minus_reference'

    stored = scoring_jobs.get_scoring_job(scoring_api['repository'], job_id, include_result=True)['result']
    assert stored['gap'][0]['gap_points'] == 0.6
    assert 'gap_direction' not in stored


def test_scoring_dataset_recalculate_and_automatic_queue_hook(scoring_api):
    client = scoring_api['client']
    dataset_id = scoring_api['dataset_id']

    response = client.post(f'/scoring/datasets/{dataset_id}/recalculate', follow_redirects=False)
    assert response.status_code == 303
    job_id = response.headers['location'].split('job_id=', 1)[1]
    job = scoring_jobs.get_scoring_job(scoring_api['repository'], int(job_id))
    assert job['status'] == 'queued'
    assert job['aggregation_levels'] == ['Operator']
    assert len(scoring_api['submitted']) == 1

    scoring_api['submitted'].clear()
    second_dataset_id = _add_ready_cdr(
        scoring_api['repository'], scoring_api['tmp_path'], name='UK_Q2_2026_NSA_Voice.csv', kind='voice',
    )
    app_module.queue_dataset_scoring(scoring_api['repository'], second_dataset_id, 'admin')
    queued = scoring_jobs.list_scoring_jobs(scoring_api['repository'])[0]
    assert queued['status'] == 'queued'
    assert second_dataset_id in queued['dataset_ids']
    assert len(queued['dataset_ids']) == 3
    assert queued['aggregation_levels'] == ['Operator']
    assert queued['baseline_operator'] == 'EE'
    assert len(scoring_api['submitted']) == 1
    assert scoring_api['submitted'][0][1] is scoring_jobs.run_scoring_job


def test_real_cdr_ingestion_automatically_scores_kpi_and_reuses_cache(client):
    _login(client)
    workspace = app_module.active_workspace
    configured_repository = Repository(workspace.database_path, app_module.repository.global_db_path,
                                       app_module.workspace_registry.registry_path)
    configured_repository.replace_scoring_configuration(scoring_configuration())
    uploads = [
        (
            'tiny_2026-Q2_NSA_data.csv',
            'data',
            'Campaign,G_Level_1,G_Level_2,Operator,Test_Name,Test_Result,Transfer_Duration\n'
            'UK_Q2_2026,Drive,City,EE,FDFS DL,Completed,10\n'
            'UK_Q2_2026,Drive,City,O2,FDFS DL,Completed,20\n'
            'UK_Q2_2026,Drive,City,O2,FDFS DL,Failed,30\n',
        ),
        (
            'tiny_2026-Q2_NSA_voice.csv',
            'voice',
            'Campaign,G_Level_1,G_Level_2,Operator,Session_Type,Call_Status,Call_Setup_Time\n'
            'UK_Q2_2026,Drive,City,EE,Voice,Completed,2\n',
        ),
        (
            'tiny_2026-Q2_NSA_speech.csv',
            'speech',
            'Campaign,G_Level_1,G_Level_2,Operator,Session_Type,LQ\n'
            'UK_Q2_2026,Drive,City,EE,Voice,4.2\n',
        ),
    ]
    for filename, kind, content in uploads:
        upload = client.post(
            '/datasets-analysis/upload',
            data={'dataset_kinds': kind, 'nr_modes': 'NSA'},
            files={'dataset_files': (filename, BytesIO(content.encode('utf-8')), 'text/csv')},
            follow_redirects=False,
        )
        assert upload.status_code == 303, upload.text

    workspace = app_module.active_workspace
    repository = Repository(
        workspace.database_path,
        global_db_path=app_module.repository.db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    deadline = time.monotonic() + 10
    datasets_by_name = {}
    while time.monotonic() < deadline:
        datasets_by_name = {row['file_name']: row for row in repository.list_datasets()}
        if all(
            filename in datasets_by_name and datasets_by_name[filename]['status'] == 'ready'
            for filename, _kind, _content in uploads
        ):
            break
        time.sleep(0.05)
    selected_datasets = [datasets_by_name[filename] for filename, _kind, _content in uploads]
    assert all(dataset['status'] == 'ready' for dataset in selected_datasets)
    dataset_id = int(datasets_by_name[uploads[0][0]]['id'])
    expected_dataset_ids = [int(dataset['id']) for dataset in selected_datasets]

    deadline = time.monotonic() + 10
    automatic_job = None
    while time.monotonic() < deadline:
        response = client.get('/api/scoring/jobs')
        assert response.status_code == 200, response.text
        automatic_job = next((
            job for job in response.json()['jobs']
            if set(job['dataset_ids']) == set(expected_dataset_ids)
            and job['aggregation_levels'] == ['Operator']
        ), None)
        if automatic_job and automatic_job['status'] in {'completed', 'failed'}:
            break
        time.sleep(0.05)

    assert automatic_job is not None, 'The completed CDR did not queue its default scoring job.'
    assert automatic_job['status'] == 'completed', automatic_job
    result_response = client.get(f"/api/scoring/jobs/{automatic_job['id']}")
    assert result_response.status_code == 200, result_response.text
    result = result_response.json()

    c17_rows = [row for row in result['scoring'] if row['kpi_code'] == 'C17']
    assert {row['operator']: row['value'] for row in c17_rows} == {'EE': 100.0, 'O2': 50.0}
    assert any('Incomplete KPI or environment coverage' in warning for warning in result['warnings'])

    csv_response = client.get(f"/scoring/jobs/{automatic_job['id']}/export/scoring")
    assert csv_response.status_code == 200, csv_response.text
    exported_rows = list(csv.DictReader(StringIO(csv_response.content.decode('utf-8-sig'))))
    exported_c17 = {row['operator']: float(row['value']) for row in exported_rows if row['kpi_code'] == 'C17'}
    assert exported_c17 == {'EE': 100.0, 'O2': 50.0}

    cached = client.post('/api/scoring/jobs', json={
        'dataset_ids': expected_dataset_ids, 'aggregation_levels': ['Operator'], 'nr_mode': 'NSA',
        'baseline_operator': 'EE',
    })
    assert cached.status_code == 200, cached.text
    assert cached.json()['cached'] is True
    assert cached.json()['job']['id'] == automatic_job['id']


@pytest.mark.parametrize('job_status', ['queued', 'completed', 'failed'])
def test_scoring_delete_api_removes_job_and_recompute_uses_new_id(scoring_api, job_status):
    client = scoring_api['client']
    payload = {'dataset_ids': scoring_api['complete_dataset_ids'], 'aggregation_levels': ['Operator'], 'nr_mode': 'NSA'}
    response = client.post('/api/scoring/jobs', json=payload)
    assert response.status_code == 200, response.text
    job_id = response.json()['job']['id']
    repository = scoring_api['repository']
    if job_status == 'completed':
        assert scoring_jobs.run_scoring_job(repository, job_id)['status'] == 'completed'
        assert client.get(f'/api/scoring/jobs/{job_id}').json()['scoring']
    elif job_status == 'failed':
        scoring_jobs._update_scoring_job(repository, job_id, status='failed', last_error='Test failure')
    response = client.delete(f'/api/scoring/jobs/{job_id}')
    assert response.status_code == 200, response.text
    assert response.json() == {'deleted': job_id}
    assert client.get(f'/api/scoring/jobs/{job_id}').status_code == 404
    assert client.get(f'/scoring/jobs/{job_id}/export/scoring').status_code == 404
    assert client.delete(f'/api/scoring/jobs/{job_id}').status_code == 404
    assert client.get('/api/scoring/jobs').json()['jobs'] == []
    assert repository.get_dataset(scoring_api['dataset_id']) is not None
    recreated = client.post('/api/scoring/jobs', json=payload)
    assert recreated.status_code == 200, recreated.text
    assert recreated.json()['cached'] is False
    assert recreated.json()['job']['id'] != job_id


def test_scoring_delete_requires_login_and_workspace_access(scoring_api, monkeypatch):
    client = scoring_api['client']
    created = client.post('/api/scoring/jobs', json={
        'dataset_ids': scoring_api['complete_dataset_ids'], 'aggregation_levels': ['Operator'], 'nr_mode': 'NSA',
    })
    job_id = created.json()['job']['id']
    client.get('/logout', follow_redirects=False)
    assert client.delete(f'/api/scoring/jobs/{job_id}').status_code == 401
    assert scoring_jobs.get_scoring_job(scoring_api['repository'], job_id) is not None
    _login(client)
    monkeypatch.setattr(app_module.repository, 'user_has_workspace_access', lambda username, workspace_id: False)
    denied = client.delete(f'/api/scoring/jobs/{job_id}')
    assert denied.status_code == 403
    assert scoring_jobs.get_scoring_job(scoring_api['repository'], job_id) is not None
