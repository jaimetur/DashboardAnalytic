"""Removing scoring jobs drops cached results and stops subsequent checkpoints."""
from types import SimpleNamespace

import pandas as pd
import pytest

from src.modules import scoring_jobs
from src.modules.repository import Repository, local_now_iso
from scoring_fixtures import scoring_configuration


@pytest.fixture()
def deletion_context(tmp_path, monkeypatch):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    repository.replace_scoring_configuration(scoring_configuration())
    source = tmp_path / 'Data_NSA.csv'
    source.write_text('source', encoding='utf-8')
    dataset_id, _ = repository.add_dataset(source.name, str(source), 'tester')
    repository.replace_dataset_rows(dataset_id, pd.DataFrame({'Operator': ['EE'], 'score': [4]}))
    repository.update_dataset_profile(dataset_id, status='ready', progress=100, dataset_kind='data',
                                      nr_mode='NSA', row_count=1, column_count=2, processed_at=local_now_iso())
    repository.replace_cdr_catalogue(dataset_id, campaigns=['2026-Q2'], vendors=[], regions=[], cities=[])
    calls = []

    def calculate(frames, levels, *, baseline_operator, configuration):
        calls.append(frames)
        return {'scoring': [{'operator': 'EE', 'weighted_points': 4}], 'gap': [], 'warnings': []}

    engine = SimpleNamespace(METHOD_VERSION='deletion-test-v1',
                             required_input_columns=lambda kind, levels: ['Operator', 'score'],
                             calculate_scoring=calculate)
    monkeypatch.setattr(scoring_jobs, '_scoring_engine', lambda: engine)
    return repository, dataset_id, engine, calls


@pytest.mark.parametrize('job_status', ['queued', 'completed', 'failed'])
def test_delete_job_removes_results_cache_and_preserves_sources(deletion_context, job_status):
    repository, dataset_id, engine, calls = deletion_context
    job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA')
    if job_status == 'completed':
        completed = scoring_jobs.run_scoring_job(repository, job['id'])
        assert completed['result']['scoring']
    elif job_status == 'failed':
        def fail(*args, **kwargs):
            raise ValueError('Test failure')
        engine.calculate_scoring = fail
        assert scoring_jobs.run_scoring_job(repository, job['id'])['status'] == 'failed'
    assert scoring_jobs.delete_scoring_job(repository, job['id']) is True
    assert scoring_jobs.get_scoring_job(repository, job['id'], include_result=True) is None
    assert scoring_jobs.list_scoring_jobs(repository) == []
    with repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM scoring_jobs WHERE id = ?', (job['id'],)).fetchone()[0] == 0
    assert repository.get_dataset(dataset_id) is not None
    assert repository.dataset_row_count(dataset_id) == 1
    fresh, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA')
    assert not reused and fresh['id'] != job['id']
    if job_status == 'queued':
        assert scoring_jobs.run_scoring_job(repository, job['id']) is None
        assert calls == []
    assert scoring_jobs.delete_scoring_job(repository, job['id']) is False


def test_deleted_during_calculation_is_never_recreated(deletion_context):
    repository, dataset_id, engine, calls = deletion_context
    job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA')

    def delete_while_calculating(frames, levels, *, baseline_operator, configuration):
        assert scoring_jobs.get_scoring_job(repository, job['id'])['status'] == 'processing'
        assert scoring_jobs.delete_scoring_job(repository, job['id'])
        return {'scoring': [{'operator': 'EE', 'weighted_points': 1000}]}

    engine.calculate_scoring = delete_while_calculating
    assert scoring_jobs.run_scoring_job(repository, job['id']) is None
    assert scoring_jobs.get_scoring_job(repository, job['id'], include_result=True) is None
    assert scoring_jobs.list_scoring_jobs(repository) == []


def test_deleted_during_loading_stops_before_calculation(deletion_context, monkeypatch):
    repository, dataset_id, engine, calls = deletion_context
    second_source = repository.db_path.parent / 'Second_NSA.csv'
    second_source.write_text('source', encoding='utf-8')
    second_id, _ = repository.add_dataset(second_source.name, str(second_source), 'tester')
    repository.replace_dataset_rows(second_id, pd.DataFrame({'Operator': ['EE'], 'score': [5]}))
    repository.update_dataset_profile(second_id, status='ready', progress=100, dataset_kind='data',
                                      nr_mode='NSA', row_count=1, column_count=2, processed_at=local_now_iso())
    repository.replace_cdr_catalogue(second_id, campaigns=['2026-Q2'], vendors=[], regions=[], cities=[])
    job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id, second_id], [], 'NSA')
    original_load = repository.load_dataset_rows
    loads = []

    def delete_while_loading(*args, **kwargs):
        result = original_load(*args, **kwargs)
        loads.append(args[0])
        assert scoring_jobs.delete_scoring_job(repository, job['id'])
        return result

    monkeypatch.setattr(repository, 'load_dataset_rows', delete_while_loading)
    assert scoring_jobs.run_scoring_job(repository, job['id']) is None
    assert loads == [dataset_id]
    assert calls == []
    assert scoring_jobs.get_scoring_job(repository, job['id']) is None
