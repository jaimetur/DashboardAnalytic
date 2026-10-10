"""Scoring History: the KPI components of every CDR per day and area, and the scoring calculated from them."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd
import pytest

from src.modules import scoring, scoring_history, scoring_jobs
from src.modules.repository import Repository, local_now_iso
from tests.scoring_fixtures import load_initial_scoring_configuration

OPERATORS = ('EE', 'Vodafone UK', 'Three UK')
PLACES = (('London', 'South', 'C1'), ('Leeds', 'North', 'C2'), ('Glasgow', 'North', 'C3'))
DAYS = ('2026-07-06 10:00:00', '2026-07-07 11:00:00', '2026-07-15 09:30:00')
# Medians and 90th percentiles come from sketches, within a quarter of a percent.
APPROXIMATE = {'K20', 'K25', 'K32'}


def _base(generator, operator, place, day):
    city, region, cluster = place
    return {'Operator': operator, 'Campaign': '2026-Q3', 'G_Level_1': 'Drive',
            'G_Level_2': generator.choice(['City', 'Connectionroad']), 'City': city, 'Region': region,
            'Cluster': cluster, 'Vendor': generator.choice(['Nokia', 'Ericsson']), 'Event_Start_Time': day}


def _rows(kind: str, seed: int = 3) -> pd.DataFrame:
    generator = random.Random(seed)
    rows = []
    for operator in OPERATORS:
        for place in PLACES:
            for day in DAYS:
                for _ in range(12):
                    row = _base(generator, operator, place, day)
                    if kind == 'voice':
                        row.update({'Session_Type': generator.choice(['CALL', 'MultiRAB CALL', 'WhatsApp CALL']),
                                    'Call_Status': generator.choice(['Completed'] * 8 + ['Dropped', 'Failed']),
                                    'Call_Setup_Time': round(generator.uniform(1, 14), 2),
                                    'Disturbed_and_Impaired_Call': generator.choice(['Yes', None, None]),
                                    'Test_Status': generator.choice(['Successful', 'Failed'])})
                    elif kind == 'speech':
                        row.update({'Session_Type': generator.choice(['CALL', 'MultiRAB CALL', 'WhatsApp CALL']),
                                    'LQ': generator.choice([None, round(generator.uniform(1, 4.8), 2)])})
                    else:
                        test = generator.choice(['FDFS DL', 'FDFS UL', 'FDTT DL', 'UDP UL', 'httpBrowser',
                                                 'VideoStreaming', 'Interactivity'])
                        row.update({'Test_Result': generator.choice(['Completed'] * 5 + ['Failed'])})
                        if test.startswith(('FDFS', 'FDTT', 'UDP')):
                            row.update({'Test_Name': test, 'Transfer_Duration': round(generator.uniform(1, 20), 2),
                                        'Mean_Data_Rate': round(generator.uniform(1, 800), 2)})
                        elif test == 'httpBrowser':
                            row.update({'Type_of_Test': test, 'http_Browser_Transferred_Bytes': generator.choice([10, 1000000]),
                                        'http_Browser_1MB_Reached_Duration': generator.randint(500, 9000)})
                        elif test == 'VideoStreaming':
                            row.update({'Type_of_Test': test, 'VideoStream_Time_to_First_Picture': generator.randint(1, 20),
                                        'Irritating_Video_Playout': generator.choice(['No', None])})
                        else:
                            row.update({'Type_of_Test': test, 'Packets_Lost': generator.randint(0, 3),
                                        'Packets_Discarded': generator.choice([None, 1]), 'Packets_Corrupted': 1.5,
                                        'Packets_Not_Sent': 0, 'Packets_Sent': 100,
                                        'Interactivity_RTT_Median': round(generator.uniform(15, 80), 1)})
                    rows.append(row)
    return pd.DataFrame(rows)


def _add_cdr(repository: Repository, tmp_path: Path, kind: str, name: str | None = None) -> int:
    name = name or f'NetCheck_UK_CDR_{kind.title()}_2026_Q3.xlsx'
    frame = _rows(kind)
    source = tmp_path / name
    source.write_text(f'{kind} source', encoding='utf-8')
    dataset_id, _created = repository.add_dataset(name, str(source), 'super')
    repository.replace_dataset_rows(dataset_id, frame)
    repository.update_dataset_profile(dataset_id, status='ready', progress=100, dataset_kind=kind, nr_mode='NSA',
                                      row_count=len(frame), column_count=len(frame.columns), processed_at=local_now_iso())
    return dataset_id


@pytest.fixture
def history_repository(tmp_path):
    repository = Repository(tmp_path / 'workspace.db', global_db_path=tmp_path / 'global.db')
    repository.initialize()
    repository.replace_scoring_configuration(load_initial_scoring_configuration())
    ids = [_add_cdr(repository, tmp_path, kind) for kind in ('data', 'voice', 'speech')]
    return repository, ids, repository.get_scoring_profile()['configuration']


def _by_rows(repository, ids, levels, configuration, context_filters=None, time_split=None):
    sources, _campaigns, _fingerprint = scoring_jobs._source_snapshot(repository, ids)
    for source in sources:
        source['levels'] = [*levels, *(scoring.START_TIME_COLUMNS if time_split else ())]
    frames = scoring_jobs._load_source_frames(repository, sources, lambda *args: None, scoring.load_input_columns,
                                              context_filters or {})
    return scoring.calculate_scoring(frames, levels, baseline_operator='EE', configuration=configuration,
                                     time_split=time_split)


def _assert_same(rows_result, history_result):
    for part, fields in (('scoring', ('value', 'sample_count', 'weighted_points')), ('global_kpis', ('value', 'sample_count')),
                         ('totals', ('weighted_points', 'max_points'))):
        def key(row):
            return tuple(sorted((name, str(value)) for name, value in row.items()
                                if name in {'campaign', 'operator', 'vendor', 'region', 'cluster', 'city', 'environment',
                                            'kpi_code', 'category', 'dataset_type'}))
        left = {key(row): row for row in rows_result[part]}
        right = {key(row): row for row in history_result[part]}
        assert set(left) == set(right), part
        for row_key, row in left.items():
            approximate = row.get('kpi_code') in APPROXIMATE or part == 'totals'
            for field in fields:
                expected, actual = row.get(field), right[row_key].get(field)
                if expected is None or actual is None:
                    assert expected is None and actual is None, (part, field, row_key)
                elif field == 'value' and approximate:
                    assert actual == pytest.approx(expected, rel=0.01), (part, field, row_key)
                elif field == 'weighted_points' and approximate:
                    assert actual == pytest.approx(expected, abs=1.5), (part, field, row_key)
                else:
                    assert actual == pytest.approx(expected, rel=1e-9, abs=1e-9), (part, field, row_key)
    assert sorted(rows_result['warnings']) == sorted(history_result['warnings'])


def test_sketches_give_medians_and_percentiles_within_a_quarter_of_a_percent():
    generator = random.Random(5)
    values = pd.Series([generator.uniform(0.5, 900) for _ in range(500)] + [0.0, 0.0])
    sketch = {}
    for key in scoring_history._sketch_keys(values):
        sketch[key] = sketch.get(key, 0) + 1
    for quantile in (0.5, 0.9):
        assert scoring_history._sketch_quantile(sketch, quantile) == pytest.approx(values.quantile(quantile), rel=0.0025)


@pytest.mark.parametrize('levels, context_filters, time_split', [
    (['Operator', 'Campaign'], None, None),
    (['Operator', 'Vendor', 'Campaign'], None, None),
    (['Operator', 'Region', 'Cluster'], None, None),
    (['Operator', 'City'], {'City': ['London', 'leeds']}, None),
    (['Operator', 'Campaign'], {'Region': ['North']}, 'Weekly'),
    (['Operator', 'Campaign'], None, 'Daily'),
    (['Operator', 'Dataset Type'], None, None),
])
def test_the_history_scores_as_the_rows_of_the_cdrs(history_repository, levels, context_filters, time_split):
    repository, ids, configuration = history_repository
    assert scoring_history.sync_history(repository) == {'indexed': 3}
    assert scoring_history.history_covers(repository, ids, levels, configuration, context_filters or {})
    by_rows = _by_rows(repository, ids, levels, configuration, context_filters, time_split)
    from_history = scoring_history.calculate_scoring_from_history(
        repository, ids, levels, configuration=configuration, context_filters=context_filters, time_split=time_split)
    assert by_rows['scoring'] and from_history['source'] == 'history'
    _assert_same(by_rows, from_history)


def test_a_cdr_is_identified_by_its_file_and_processing_not_its_name(history_repository, tmp_path):
    repository, ids, configuration = history_repository
    scoring_history.sync_history(repository)
    data_id = ids[0]
    # A new name keeps the history: the CDR is identified by the SHA-256 of its file.
    with repository.connection() as connection:
        connection.execute('UPDATE datasets SET file_name = ? WHERE id = ?', ('Renamed data CDR.xlsx', data_id))
    changed, _metrics = scoring_history.history_changes(repository)
    assert changed == []
    # Processing it again replaces the history of its former processing.
    with repository.connection() as connection:
        old_keys = {row[0] for row in connection.execute('SELECT source_key FROM scoring_history_sources').fetchall()}
    repository.update_dataset_profile(data_id, processed_at=local_now_iso() + 'x')
    assert scoring_history.sync_history(repository) == {'indexed': 1}
    with repository.connection() as connection:
        keys = {row[0] for row in connection.execute('SELECT source_key FROM scoring_history_sources').fetchall()}
        sources = connection.execute('SELECT COUNT(*) FROM scoring_history_sources').fetchone()[0]
    assert sources == 3 and len(keys - old_keys) == 1
    # A deleted CDR keeps its history.
    repository.delete_dataset(ids[2])
    scoring_history.sync_history(repository)
    with repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM scoring_history_sources').fetchone()[0] == 3
    # A split the history does not keep reads the rows of the CDRs.
    assert not scoring_history.history_covers(repository, ids[:2], ['Operator', 'Unknown level'], configuration)


def test_a_job_is_calculated_from_the_history_and_gets_its_points_lost_map(history_repository):
    repository, ids, _configuration = history_repository
    scoring_history.sync_history(repository)
    job, cached = scoring_jobs.create_scoring_job(repository, ids, ['Operator', 'Campaign'], 'NSA')
    assert not cached
    finished = scoring_jobs.run_scoring_job(repository, job['id'])
    assert finished['status'] == 'completed'
    result = finished['result']
    assert result['source'] == 'history' and result['scoring']
    # The Points Lost Map is added from the rows of the tests once the scores are saved.
    assert 'pending' not in result['points_loss'] and 'shares' in result['points_loss']
    assert finished['message'] == 'Scoring tables, GAP analysis and Points Lost Map are ready'
    # Without the history the same job reads the rows, with the same scores.
    by_rows = _by_rows(repository, ids, ['Operator', 'Campaign'], result['configuration'])
    _assert_same(by_rows, result)
