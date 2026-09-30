from __future__ import annotations

from io import BytesIO
import re
from urllib.parse import unquote
import sqlite3

from pptx import Presentation

import src.DashboardAnalytic as app_module
from src.modules import scoring_jobs
from src.modules.repository import Repository
from tests.test_scoring_api import scoring_api


def test_scoring_filter_catalogues_backfill_once_and_then_use_cache(scoring_api, monkeypatch):
    repository = scoring_api['repository']
    repository.set_main_cities(['Leeds', 'London'])
    reads = []
    original = app_module._distinct_cdr_row_values

    def record_read(*args):
        reads.append(args[1])
        return original(*args)

    monkeypatch.setattr(app_module, '_distinct_cdr_row_values', record_read)
    first = scoring_api['client'].get('/scoring')
    assert first.status_code == 200
    assert len(reads) == 3
    assert 'Main Cities' in first.text
    cached = repository.cdr_catalogues_by_dataset(scoring_api['complete_dataset_ids'])
    assert all(item['operators'] == ['EE', 'O2'] for item in cached.values())
    assert repository.cdr_catalogues_by_dataset([]) == {}
    reads.clear()
    assert scoring_api['client'].get('/scoring').status_code == 200
    assert reads == []


def test_operator_catalogue_replacement_preserves_unspecified_values_and_database_copy(scoring_api, tmp_path):
    repository = scoring_api['repository']
    dataset_id = scoring_api['dataset_id']
    app_module.cache_cdr_catalogue(
        dataset_id, repository.load_dataset_rows(dataset_id, ['Operator', 'City', 'Campaign'], {}), repository,
    )
    repository.replace_cdr_catalogue(dataset_id, vendors=['Ericsson'], regions=['West'], cities=['York'])
    catalogue = repository.cdr_catalogues_by_dataset([dataset_id])[dataset_id]
    assert catalogue['operators'] == ['EE', 'O2']
    assert catalogue['campaigns'] == ['2026-Q2']
    job, _ = scoring_jobs.create_scoring_job(
        repository, scoring_api['complete_dataset_ids'], ['Operator'], 'NSA',
        context_filters={'City': ['York']},
    )
    destination = tmp_path / 'restored.db'
    with sqlite3.connect(repository.db_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    restored = Repository(destination)
    restored.initialize()
    assert restored.cdr_catalogues_by_dataset([dataset_id])[dataset_id] == catalogue
    restored_job = scoring_jobs.get_scoring_job(restored, job['id'])
    assert restored_job['context_filters']['City'] == ['York']
    assert restored_job['configuration'] == job['configuration']


def test_scoring_api_filters_before_calculation_and_ppt_preserves_scope(scoring_api):
    response = scoring_api['client'].post('/api/scoring/jobs', json={
        'dataset_ids': scoring_api['complete_dataset_ids'], 'nr_mode': 'NSA',
        'aggregation_levels': ['Operator'],
        'context_filters': {'Region': ['North'], 'City': ['Leeds'], 'Operator': ['O2'],
                            'Vendor': ['Nokia'], 'Campaign': ['2026-Q2']},
    })
    assert response.status_code == 200, response.text
    job = response.json()['job']
    assert job['context_filters']['City'] == ['Leeds']
    completed = scoring_jobs.run_scoring_job(scoring_api['repository'], job['id'])
    assert completed['status'] == 'completed', completed.get('last_error')
    frames = scoring_api['calls'][0]['frames']
    source_frames = frames.values() if isinstance(frames, dict) else [item[-1] for item in frames]
    assert all(set(frame['Operator']) == {'O2'} for frame in source_frames)
    exported = scoring_api['client'].get(f'/scoring/jobs/{job["id"]}/export/ppt')
    assert exported.status_code == 200, exported.text
    assert re.search(r'\d{8}_\d{6}.*NSA.*Scoring', unquote(exported.headers['content-disposition']))
    deck = Presentation(BytesIO(exported.content))
    for slide in list(deck.slides)[:2]:
        text = '\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame)
        assert 'Leeds' in text and 'North' in text and 'Nokia' in text and 'O2' in text
    saved = scoring_jobs.get_scoring_job(scoring_api['repository'], job['id'])
    assert saved['context_filters'] == job['context_filters']
