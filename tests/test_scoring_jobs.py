from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from src.modules import scoring_jobs
from src.modules.repository import Repository, SCHEMA, SCORING_CONFIGURATION_STATE_KEY, local_now_iso
from scoring_fixtures import scoring_configuration


@pytest.fixture()
def scoring_engine(monkeypatch):
    engine = ModuleType('src.modules.scoring')
    engine.METHOD_VERSION = 'test-method-v1'
    engine.required_input_columns = lambda kind, levels: [*levels, 'score']
    calls = []
    engine.configuration_snapshots = []
    engine.baseline_alias_snapshots = []
    engine.operator_mapping_snapshots = []

    def calculate_scoring(
        frames, levels, *, baseline_operator, configuration=None, baseline_aliases=None,
        operator_mappings=None,
    ):
        calls.append((frames, levels, baseline_operator))
        engine.configuration_snapshots.append(copy.deepcopy(configuration))
        engine.baseline_alias_snapshots.append(list(baseline_aliases or []))
        engine.operator_mapping_snapshots.append(dict(operator_mappings or {}))
        return {
            'scoring': [{'Operator': 'EE', 'Score': 4}],
            'gap': [{'Operator': 'EE', 'Gap': 0}],
            'charts': [],
            'warnings': [],
        }

    engine.calculate_scoring = calculate_scoring
    monkeypatch.setattr(scoring_jobs, '_scoring_engine', lambda: engine)
    return engine, calls


@pytest.fixture()
def repository(tmp_path: Path) -> Repository:
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    repository.replace_scoring_configuration(scoring_configuration())
    return repository


def add_dataset(repository: Repository, name: str = 'UK_Q2_2026_NSA_Data.csv', *, kind: str = 'data', nr_mode: str = 'NSA') -> int:
    source = Path(repository.db_path).parent / name
    source.write_text('source', encoding='utf-8')
    dataset_id, _created = repository.add_dataset(name, str(source), 'tester')
    frame = pd.DataFrame({
        'Operator': ['EE', 'O2'],
        'Region': ['North', 'South'],
        'City': ['Leeds', 'London'],
        'Vendor': ['Nokia', 'Ericsson'],
        'Dataset_Kind': [kind, kind],
        'score': [3.0, 4.0],
        'unused_payload': ['large', 'field'],
    })
    repository.replace_dataset_rows(dataset_id, frame)
    repository.update_dataset_profile(
        dataset_id,
        status='ready', progress=100, dataset_kind=kind, nr_mode=nr_mode,
        row_count=len(frame), column_count=len(frame.columns), processed_at=local_now_iso(),
    )
    repository.replace_cdr_catalogue(
        dataset_id, vendors=['Nokia', 'Ericsson'], regions=['North', 'South'],
        cities=['Leeds', 'London'], campaigns=['2026-Q2'],
    )
    return dataset_id


def add_complete_scoring_sources(repository: Repository, prefix: str = 'Scoped') -> list[int]:
    dataset_ids = []
    for kind in ('data', 'voice', 'speech'):
        dataset_id = add_dataset(repository, f'{prefix}_NSA_{kind.title()}.csv', kind=kind)
        frame = pd.DataFrame({
            'Operator': ['VF_UK', 'VF_UK', 'O2', 'VF_UK', 'VF_UK'],
            'Region': ['North'] * 5,
            'City': ['Leeds', 'Manchester', 'Leeds', 'Leeds', 'Leeds'],
            'Vendor': ['Nokia', 'Nokia', 'Nokia', 'Ericsson', 'Nokia'],
            'Campaign': ['2026-Q2', '2026-Q2', '2026-Q2', '2026-Q2', '2026-Q1'],
            'Dataset_Kind': [kind] * 5,
            'score': [3.0, 4.0, 5.0, 6.0, 7.0],
        })
        repository.replace_dataset_rows(dataset_id, frame)
        repository.update_dataset_profile(
            dataset_id, row_count=len(frame), column_count=len(frame.columns),
        )
        dataset_ids.append(dataset_id)
    return dataset_ids


def test_scoring_jobs_persist_results_and_reuse_completed_cache(repository, scoring_engine):
    _engine, calls = scoring_engine
    global_kpi = {
        'campaign': '2026-Q2', 'region': 'North', 'operator': 'EE',
        'kpi_code': 'C5', 'kpi': 'CALL SUCCESS RATIO [%]', 'category': 'CLASSIC CALLS',
        'kpi_type': 'Reliable', 'value': 98.75, 'sample_count': 12,
        'environment': 'All Environments', 'complete_coverage': True, 'missing_environments': [],
    }
    original_calculate = _engine.calculate_scoring

    def calculate_with_global_kpis(*args, **kwargs):
        result = original_calculate(*args, **kwargs)
        result['global_kpis'] = [global_kpi]
        return result

    _engine.calculate_scoring = calculate_with_global_kpis
    dataset_id = add_dataset(repository)

    job, reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region', 'City'], 'NSA', username='tester',
    )
    assert not reused
    assert job['status'] == 'queued'
    assert job['aggregation_levels'] == ['Operator', 'Region', 'City']
    assert job['campaigns'] == ['2026-Q2']
    duplicate, reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region', 'City'], 'NSA', username='other-user',
    )
    assert reused
    assert duplicate['id'] == job['id']

    completed = scoring_jobs.run_scoring_job(repository, job['id'])
    assert completed['status'] == 'completed'
    assert completed['result']['scoring'] == [{'Operator': 'EE', 'Score': 4}]
    assert completed['result']['global_kpis'] == [global_kpi]
    reloaded = scoring_jobs.get_scoring_job(repository, job['id'], include_result=True)
    assert reloaded['result']['global_kpis'] == [global_kpi]
    assert len(calls) == 1
    loaded_frames, levels, baseline = calls[0]
    assert levels == ['Operator', 'Region', 'City']
    assert baseline == 'EE'
    assert 'unused_payload' not in loaded_frames['data'].columns

    cached, reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region', 'City'], 'NSA', username='tester',
    )
    assert reused
    assert cached['id'] == job['id']
    assert cached['result']['gap'] == [{'Operator': 'EE', 'Gap': 0}]
    summaries = scoring_jobs.list_scoring_jobs(repository)
    assert len(summaries) == 1
    assert summaries[0]['result'] is None
    assert 'configuration' not in summaries[0]
    assert scoring_jobs.get_scoring_job(repository, 9999) is None


def test_scoring_job_creation_requires_a_persisted_configuration(repository):
    dataset_id = add_dataset(repository)
    repository.set_workspace_state(SCORING_CONFIGURATION_STATE_KEY, '')

    with pytest.raises(ValueError, match='Import a Scoring Configuration'):
        scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')


def test_force_creates_a_fresh_calculation_and_method_baseline_are_cached(repository, scoring_engine):
    _engine, calls = scoring_engine
    dataset_id = add_dataset(repository)
    first, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA')
    scoring_jobs.run_scoring_job(repository, first['id'])

    forced, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA', force=True)
    assert not reused
    assert forced['id'] != first['id']
    assert scoring_jobs.run_scoring_job(repository, forced['id'])['status'] == 'completed'

    other_baseline, reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], [], 'NSA', baseline_operator='O2',
    )
    assert not reused
    assert other_baseline['id'] != forced['id']
    assert len(calls) == 2


def test_scoring_configuration_changes_cache_and_queued_job_keeps_its_snapshot(repository, scoring_engine):
    engine, _calls = scoring_engine
    dataset_id = add_dataset(repository)
    initial, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    original_configuration = copy.deepcopy(initial['configuration'])

    changed_configuration = scoring_configuration()
    c5 = next(metric for metric in changed_configuration['metrics'] if metric['code'] == 'K1')
    c5['contexts']['DriveCity']['thresholds']['low'] = 86
    repository.replace_scoring_configuration(changed_configuration)
    changed, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')

    assert not reused
    assert changed['id'] != initial['id']
    assert changed['configuration']['metrics'][0]['contexts']['DriveCity']['thresholds']['low'] == 86
    completed = scoring_jobs.run_scoring_job(repository, initial['id'])
    assert completed['status'] == 'completed'
    assert completed['result']['configuration'] == original_configuration
    assert engine.configuration_snapshots[0] == original_configuration


def test_legacy_job_configuration_snapshot_is_returned_without_walk_migration(repository, scoring_engine):
    engine, _calls = scoring_engine
    from src.modules.scoring import method_version_for_configuration

    engine.method_version_for_configuration = method_version_for_configuration
    dataset_id = add_dataset(repository)
    job, _reused = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA')
    legacy = copy.deepcopy(job['configuration'])
    legacy['scope']['environments'].pop('Walk')
    legacy['scope']['environment_mapping'].pop('Walk')
    for metric in legacy['metrics']:
        metric['contexts'].pop('Walk')

    with repository.connection() as connection:
        row = connection.execute(
            'SELECT source_metadata_json FROM scoring_jobs WHERE id = ?', (job['id'],),
        ).fetchone()
        snapshot = json.loads(row['source_metadata_json'])
        snapshot['configuration'] = legacy
        connection.execute(
            'UPDATE scoring_jobs SET source_metadata_json = ?, method_version = ? WHERE id = ?',
            (json.dumps(snapshot), method_version_for_configuration(legacy), job['id']),
        )

    loaded = scoring_jobs.get_scoring_job(repository, job['id'])
    assert loaded['configuration'] == legacy
    assert 'Walk' not in loaded['configuration']['scope']['environments']
    completed = scoring_jobs.run_scoring_job(repository, job['id'])
    assert completed['status'] == 'completed'
    assert completed['configuration'] == legacy
    with repository.connection() as connection:
        stored = connection.execute(
            'SELECT source_metadata_json FROM scoring_jobs WHERE id = ?', (job['id'],),
        ).fetchone()
    assert json.loads(stored['source_metadata_json'])['configuration'] == legacy


def test_active_profile_identity_partitions_cache_and_is_saved_with_job(repository, scoring_engine):
    dataset_id = add_dataset(repository)
    first, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    assert not reused
    assert first['scoring_profile_id'] == 'netcheck-2026'
    assert scoring_jobs.run_scoring_job(repository, first['id'])['status'] == 'completed'

    profiles = repository.get_scoring_profiles()
    second_profile = copy.deepcopy(profiles['profiles'][0])
    second_profile.update({'id': 'netcheck-alt', 'name': 'NetCheck Alternate'})
    profiles['profiles'].append(second_profile)
    profiles['active_profile_id'] = second_profile['id']
    repository.replace_scoring_profiles(profiles)

    second, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    assert not reused
    assert second['id'] != first['id']
    assert second['scoring_profile_id'] == 'netcheck-alt'
    assert second['scoring_profile_name'] == 'NetCheck Alternate'

    profiles['active_profile_id'] = 'netcheck-2026'
    repository.replace_scoring_profiles(profiles)
    cached, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    assert reused
    assert cached['id'] == first['id']


def test_explicit_inactive_profile_sets_job_snapshot_and_hierarchy_without_switching_active(
    repository, scoring_engine,
):
    engine, _calls = scoring_engine
    dataset_id = add_dataset(repository)
    profiles = repository.get_scoring_profiles()
    active_id = profiles['active_profile_id']
    active_configuration = copy.deepcopy(repository.get_scoring_configuration())
    inactive = copy.deepcopy(profiles['profiles'][0])
    inactive.update({'id': 'netcheck-2025', 'name': 'NetCheck 2025'})
    inactive['configuration']['version'] = 'NetCheck 2025'
    inactive['configuration']['aggregation_hierarchy'] = [
        'Region', 'Operator', 'Vendor', 'City', 'Campaign',
    ]
    inactive['configuration']['metrics'][0]['contexts']['DriveCity']['max_points'] = 88
    profiles['profiles'].append(inactive)
    repository.replace_scoring_profiles(profiles)

    selected, reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region', 'City'], 'NSA', scoring_profile_id='netcheck-2025',
    )

    assert not reused
    assert selected['scoring_profile_id'] == 'netcheck-2025'
    assert selected['scoring_profile_name'] == 'NetCheck 2025'
    assert selected['configuration']['metrics'][0]['contexts']['DriveCity']['max_points'] == 88
    assert selected['aggregation_hierarchy'] == inactive['configuration']['aggregation_hierarchy']
    assert selected['aggregation_levels'] == ['Region', 'Operator', 'City']
    assert repository.get_scoring_profiles()['active_profile_id'] == active_id
    assert repository.get_scoring_configuration() == active_configuration

    completed = scoring_jobs.run_scoring_job(repository, selected['id'])
    assert completed['status'] == 'completed'
    assert engine.configuration_snapshots[0]['metrics'][0]['contexts']['DriveCity']['max_points'] == 88

    default_job, default_reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region', 'City'], 'NSA',
    )
    assert not default_reused
    assert default_job['scoring_profile_id'] == active_id
    assert default_job['id'] != selected['id']


def test_explicit_same_configuration_profile_uses_separate_cache_entry(repository):
    dataset_id = add_dataset(repository)
    profiles = repository.get_scoring_profiles()
    alternate = copy.deepcopy(profiles['profiles'][0])
    alternate.update({'id': 'netcheck-copy', 'name': 'NetCheck Copy'})
    profiles['profiles'].append(alternate)
    repository.replace_scoring_profiles(profiles)

    active, reused_active = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    explicit, reused_explicit = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region'], 'NSA', scoring_profile_id='netcheck-copy',
    )

    assert not reused_active and not reused_explicit
    assert explicit['id'] != active['id']
    assert explicit['scoring_profile_id'] == 'netcheck-copy'


def test_unknown_explicit_profile_is_rejected(repository):
    dataset_id = add_dataset(repository)

    with pytest.raises(ValueError, match='was not found'):
        scoring_jobs.create_scoring_job(
            repository, [dataset_id], ['Region'], 'NSA', scoring_profile_id='missing-profile',
        )


def test_job_levels_follow_configured_hierarchy_and_snapshot_contract(repository, scoring_engine):
    engine, _calls = scoring_engine
    configuration = scoring_configuration()
    configuration['aggregation_hierarchy'] = ['Campaign', 'City', 'Operator', 'Region', 'Vendor']
    repository.replace_scoring_configuration(configuration)
    repository.replace_operator_mapping_groups([
        {'canonical': 'Vodafone UK', 'aliases': ['VF_UK'], 'color': '#FF0000'},
    ])
    dataset_ids = add_complete_scoring_sources(repository, 'Hierarchy')

    job, reused = scoring_jobs.create_scoring_job(
        repository, dataset_ids, ['Vendor', 'Region', 'City', 'Campaign'], 'NSA',
    )

    assert not reused
    assert job['levels'] == ['Campaign', 'City', 'Operator', 'Region', 'Vendor']
    assert job['aggregation_levels'] == job['levels']
    assert job['aggregation_hierarchy'] == configuration['aggregation_hierarchy']
    assert job['aggregation_contract_version'] == 2
    completed = scoring_jobs.run_scoring_job(repository, job['id'])
    assert completed['status'] == 'completed'
    assert completed['result']['aggregation_levels'] == job['levels']
    assert completed['result']['aggregation_contract_version'] == 2
    assert engine.operator_mapping_snapshots[0] == {
        'vf_uk': 'Vodafone UK', 'vodafone uk': 'Vodafone UK',
    }


def test_baseline_alias_snapshot_is_cached_and_passed_to_engine(repository, scoring_engine):
    engine, _calls = scoring_engine
    dataset_id = add_dataset(repository)
    repository.replace_operator_mapping_groups([
        {'canonical': 'Vodafone UK', 'aliases': ['VF_UK', 'VF UK'], 'color': '#FF0000'},
    ])

    job, reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region'], 'NSA', baseline_operator='Vodafone UK',
    )
    assert not reused
    assert set(job['baseline_aliases']) == {'Vodafone UK', 'VF_UK', 'VF UK'}
    completed = scoring_jobs.run_scoring_job(repository, job['id'])
    assert completed['result']['baseline_aliases'] == job['baseline_aliases']
    assert engine.baseline_alias_snapshots[0] == job['baseline_aliases']

    repository.replace_operator_mapping_groups([
        {'canonical': 'Vodafone UK', 'aliases': ['VF_UK', 'VF UK', 'Voda'], 'color': '#FF0000'},
    ])
    updated, reused = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Region'], 'NSA', baseline_operator='Vodafone UK',
    )
    assert not reused
    assert updated['id'] != job['id']
    assert 'Voda' in updated['baseline_aliases']


def test_scoring_context_filters_are_pushed_down_and_persisted(repository, scoring_engine, monkeypatch):
    _engine, calls = scoring_engine
    dataset_ids = add_complete_scoring_sources(repository)
    repository.replace_operator_mapping_groups([
        {'canonical': 'Vodafone UK', 'aliases': ['VF_UK'], 'color': '#FF0000'},
    ])
    filters = {
        'Region': ['North'], 'City': ['Leeds'], 'Operator': ['Vodafone UK'],
        'Vendor': ['Nokia'], 'Campaign': ['2026-Q2'],
    }
    load_filters = []
    original_load_dataset_rows = repository.load_dataset_rows

    def record_load(dataset_id, columns, dataset_filters):
        load_filters.append(dataset_filters)
        return original_load_dataset_rows(dataset_id, columns, dataset_filters)

    monkeypatch.setattr(repository, 'load_dataset_rows', record_load)

    job, reused = scoring_jobs.create_scoring_job(
        repository, dataset_ids, ['Region'], 'NSA', context_filters=filters,
    )

    assert not reused
    assert job['context_filters'] == filters
    assert scoring_jobs.get_scoring_job(repository, job['id'])['context_filters'] == filters
    assert scoring_jobs.list_scoring_jobs(repository)[0]['context_filters'] == filters
    completed = scoring_jobs.run_scoring_job(repository, job['id'])
    assert completed['status'] == 'completed'
    loaded_frames, _levels, _baseline = calls[0]
    assert set(loaded_frames) == {'data', 'voice', 'speech'}
    for frame in loaded_frames.values():
        assert len(frame) == 1
        assert frame.iloc[0]['Operator'] == 'VF_UK'
        assert frame.iloc[0]['Region'] == 'North'
        assert frame.iloc[0]['score'] == 3.0
    assert len(load_filters) == 3
    for dataset_filters in load_filters:
        assert dataset_filters['Region'] == ['North']
        assert dataset_filters['City'] == ['Leeds']
        assert dataset_filters['Operator'] == ['VF_UK', 'Vodafone UK']
        assert dataset_filters['Vendor'] == ['Nokia']
        assert dataset_filters['Campaign'] == ['2026-Q2']


def test_scoring_context_filter_cache_is_order_independent_and_scope_specific(repository, scoring_engine):
    _engine, _calls = scoring_engine
    dataset_ids = add_complete_scoring_sources(repository)

    first, reused = scoring_jobs.create_scoring_job(
        repository, dataset_ids, [], 'NSA', context_filters={'Region': ['North', 'South']},
    )
    reordered, reused_reordered = scoring_jobs.create_scoring_job(
        repository, dataset_ids, [], 'NSA', context_filters={'Region': ['South', 'North']},
    )
    different_case, reused_different_case = scoring_jobs.create_scoring_job(
        repository, dataset_ids, [], 'NSA', context_filters={'Region': ['north', 'south']},
    )
    narrowed, reused_narrowed = scoring_jobs.create_scoring_job(
        repository, dataset_ids, [], 'NSA', context_filters={'Region': ['North']},
    )

    assert not reused
    assert reused_reordered
    assert reordered['id'] == first['id']
    assert reused_different_case
    assert different_case['id'] == first['id']
    assert not reused_narrowed
    assert narrowed['id'] != first['id']


def test_scoring_context_filters_skip_empty_sources_and_fail_when_a_type_has_no_matches(repository, scoring_engine):
    _engine, _calls = scoring_engine
    dataset_ids = add_complete_scoring_sources(repository, 'Rows')
    data_empty_id = add_dataset(repository, 'Rows_Empty_NSA_Data.csv', kind='data')
    frame = pd.DataFrame({
        'Operator': ['O2'], 'Region': ['South'], 'City': ['London'],
        'Vendor': ['Ericsson'], 'Campaign': ['2026-Q2'], 'score': [5.0],
    })
    repository.replace_dataset_rows(data_empty_id, frame)
    repository.update_dataset_profile(data_empty_id, row_count=1, column_count=len(frame.columns))
    voice_missing_region_id = add_dataset(repository, 'Rows_No_Region_NSA_Voice.csv', kind='voice')
    missing_region_frame = pd.DataFrame({
        'Operator': ['EE'], 'City': ['Leeds'], 'Vendor': ['Nokia'],
        'Campaign': ['2026-Q2'], 'score': [8.0],
    })
    repository.replace_dataset_rows(voice_missing_region_id, missing_region_frame)
    repository.update_dataset_profile(
        voice_missing_region_id, row_count=1, column_count=len(missing_region_frame.columns),
    )

    job, _ = scoring_jobs.create_scoring_job(
        repository, [*dataset_ids, data_empty_id, voice_missing_region_id], [], 'NSA',
        context_filters={'Region': ['North']},
    )
    completed = scoring_jobs.run_scoring_job(repository, job['id'])
    assert completed['status'] == 'completed'
    assert len(completed['result']['scoring']) == 1

    no_matches, _ = scoring_jobs.create_scoring_job(
        repository, dataset_ids, [], 'NSA', context_filters={'Region': ['Nowhere']},
    )
    failed = scoring_jobs.run_scoring_job(repository, no_matches['id'])
    assert failed['status'] == 'failed'
    assert 'Missing: Data, Voice, Speech' in failed['error']


def test_scoring_geography_filters_resolve_legacy_g_level_columns(repository, scoring_engine):
    _engine, calls = scoring_engine
    dataset_ids = []
    for kind in ('data', 'voice', 'speech'):
        dataset_id = add_dataset(repository, f'Legacy_Geography_NSA_{kind.title()}.csv', kind=kind)
        frame = pd.DataFrame({
            'Operator': ['EE', 'O2'], 'G_Level_2': ['North', 'South'],
            'G_Level_4': ['Leeds', 'London'], 'score': [3.0, 4.0],
        })
        repository.replace_dataset_rows(dataset_id, frame)
        repository.update_dataset_profile(
            dataset_id, row_count=len(frame), column_count=len(frame.columns),
        )
        dataset_ids.append(dataset_id)

    job, _ = scoring_jobs.create_scoring_job(
        repository, dataset_ids, [], 'NSA', context_filters={
            'Region': ['North'], 'City': ['Leeds'],
        },
    )
    completed = scoring_jobs.run_scoring_job(repository, job['id'])

    assert completed['status'] == 'completed'
    loaded_frames, _levels, _baseline = calls[0]
    assert all(len(frame) == 1 for frame in loaded_frames.values())


def test_campaign_completeness_checks_only_selected_campaigns(repository):
    data_q1 = add_dataset(repository, 'Campaign_Q1_NSA_Data.csv', kind='data')
    data_q2 = add_dataset(repository, 'Campaign_Q2_NSA_Data.csv', kind='data')
    voice_q1 = add_dataset(repository, 'Campaign_Q1_NSA_Voice.csv', kind='voice')
    speech_q1 = add_dataset(repository, 'Campaign_Q1_NSA_Speech.csv', kind='speech')
    for dataset_id, campaign in (
        (data_q1, '2026-Q1'), (data_q2, '2026-Q2'),
        (voice_q1, '2026-Q1'), (speech_q1, '2026-Q1'),
    ):
        repository.replace_cdr_catalogue(
            dataset_id, vendors=['Nokia', 'Ericsson'], regions=['North', 'South'],
            cities=['Leeds', 'London'], campaigns=[campaign],
        )

    with pytest.raises(ValueError, match=r'2026-Q2 \(Voice, Speech\)'):
        scoring_jobs.validate_complete_scoring_cdr_selection(
            repository, [data_q1, data_q2, voice_q1, speech_q1], 'NSA',
        )

    selected = scoring_jobs.validate_complete_scoring_cdr_selection(
        repository, [data_q1, data_q2, voice_q1, speech_q1], 'NSA',
        context_filters={'Campaign': ['2026-Q1']},
    )
    assert selected == [data_q1, data_q2, voice_q1, speech_q1]


def test_legacy_scoring_jobs_default_to_no_context_filters(repository):
    dataset_id = add_dataset(repository)
    job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA')
    with repository.connection() as connection:
        connection.execute(
            'UPDATE scoring_jobs SET source_metadata_json = ? WHERE id = ?',
            ('[{"name":"Legacy CDR"}]', job['id']),
        )

    reloaded = scoring_jobs.get_scoring_job(repository, job['id'])

    assert reloaded['context_filters'] == {}
    assert reloaded['aggregation_contract_version'] == 1
    assert reloaded['aggregation_hierarchy'] == []


def test_scoring_cache_invalidates_when_materialized_cdr_changes(repository, scoring_engine):
    _engine, calls = scoring_engine
    dataset_id = add_dataset(repository)
    job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    scoring_jobs.run_scoring_job(repository, job['id'])

    repository.update_dataset_profile(dataset_id, processed_at=local_now_iso())
    refreshed, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    assert not reused
    assert refreshed['id'] != job['id']

    repository.update_dataset_profile(dataset_id, processed_at=local_now_iso())
    with repository.connection() as connection:
        connection.execute(
            "UPDATE dataset_profiles SET updated_at = '2099-01-01T00:00:00+00:00' WHERE dataset_id = ?",
            (dataset_id,),
        )
    edited, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    assert not reused
    assert edited['id'] != refreshed['id']
    assert len(calls) == 1


def test_scoring_cache_survives_dataset_reordering(repository, scoring_engine):
    _engine, _calls = scoring_engine
    first_id = add_dataset(repository, 'First_NSA_Data.csv')
    second_id = add_dataset(repository, 'Second_NSA_Voice.csv', kind='voice')
    job, _ = scoring_jobs.create_scoring_job(repository, [first_id, second_id], ['Region'], 'NSA')
    scoring_jobs.run_scoring_job(repository, job['id'])

    id_mapping = repository.reorder_dataset_ids([second_id, first_id])
    assert id_mapping == {first_id: 2, second_id: 1}
    reordered, reused = scoring_jobs.create_scoring_job(repository, [1, 2], ['Region'], 'NSA')

    assert reused
    assert reordered['id'] == job['id']
    assert reordered['dataset_ids'] == [2, 1]


def test_database_management_row_edits_invalidate_the_scoring_cache(repository, scoring_engine):
    _engine, _calls = scoring_engine
    dataset_id = add_dataset(repository)
    job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    scoring_jobs.run_scoring_job(repository, job['id'])

    repository.update_database_table_row(
        repository.dataset_rows_table_name(dataset_id), 1, {'score': 99.0},
    )
    edited, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')

    assert not reused
    assert edited['id'] != job['id']


@pytest.mark.parametrize(
    ('ids', 'mode', 'levels', 'expected_error'),
    [
        ([], 'NSA', ['Region'], 'Select at least one'),
        ([1], 'SA', ['Region'], 'does not match'),
        ([1], 'NSA', ['Unknown Dimension'], 'not available'),
    ],
)
def test_scoring_job_validates_cdr_mode_and_levels(repository, scoring_engine, ids, mode, levels, expected_error):
    _engine, _calls = scoring_engine
    add_dataset(repository)
    with pytest.raises(ValueError, match=expected_error):
        scoring_jobs.create_scoring_job(repository, ids, levels, mode)


def test_scoring_jobs_are_visible_and_interrupted_jobs_become_retryable(repository, scoring_engine):
    _engine, _calls = scoring_engine
    dataset_id = add_dataset(repository)
    job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], [], 'NSA')

    assert 'scoring_jobs' in repository.list_database_tables()
    interrupted_datasets, interrupted_reports = repository.fail_interrupted_background_jobs(fail_datasets=False)

    assert interrupted_datasets == []
    assert interrupted_reports == []
    recovered = scoring_jobs.get_scoring_job(repository, job['id'])
    assert recovered['status'] == 'failed'
    assert 'application restarted' in recovered['error']


def test_recover_interrupted_scoring_jobs_on_workspace_reopen(repository, scoring_engine):
    _engine, _calls = scoring_engine
    dataset_id = add_dataset(repository)

    completed_job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    scoring_jobs.run_scoring_job(repository, completed_job['id'])
    completed_before = scoring_jobs.get_scoring_job(
        repository, completed_job['id'], include_result=True,
    )

    queued_job, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], ['City'], 'NSA')
    processing_job, _ = scoring_jobs.create_scoring_job(
        repository, [dataset_id], ['Vendor'], 'NSA', baseline_operator='O2',
    )
    with repository.connection() as connection:
        connection.execute(
            "UPDATE scoring_jobs SET status = 'processing', progress = 45 WHERE id = ?",
            (processing_job['id'],),
        )

    reopened_repository = Repository(Path(repository.db_path))
    reopened_repository.initialize()
    recovered_ids = scoring_jobs.recover_interrupted_scoring_jobs(reopened_repository)

    assert recovered_ids == sorted([queued_job['id'], processing_job['id']])
    for job_id in recovered_ids:
        recovered = scoring_jobs.get_scoring_job(reopened_repository, job_id)
        assert recovered['status'] == 'failed'
        assert 'application restarted' in recovered['error']

    completed_after = scoring_jobs.get_scoring_job(
        reopened_repository, completed_job['id'], include_result=True,
    )
    assert completed_after == completed_before
    assert scoring_jobs.recover_interrupted_scoring_jobs(reopened_repository) == []


def test_initialize_migrates_legacy_scoring_job_status_constraint(repository):
    table_definition = re.search(
        r"CREATE TABLE IF NOT EXISTS scoring_jobs \(.*?\n\);", SCHEMA, re.DOTALL,
    )
    assert table_definition is not None
    legacy_ddl = table_definition.group(0).replace(
        "('queued', 'processing', 'completed', 'failed', 'stopped')",
        "('queued', 'processing', 'ready', 'failed', 'stopped')",
    ).replace('CREATE TABLE IF NOT EXISTS scoring_jobs', 'CREATE TABLE scoring_jobs', 1)
    assert "'ready'" in legacy_ddl and "'completed'" not in legacy_ddl

    result_json = '{"scoring":[{"Operator":"EE","Score":4}],"gap":[],"charts":[],"warnings":[]}'
    legacy_jobs = [
        {
            'id': 7, 'cache_key': 'legacy-ready', 'method_version': 'method-v1',
            'source_fingerprint': 'fingerprint-ready', 'dataset_ids_json': '[3,5]',
            'source_metadata_json': '[{"name":"Q2 CDR"}]', 'nr_mode': 'NSA',
            'levels_json': '["Region"]', 'baseline_operator': 'O2', 'status': 'ready',
            'progress': 100, 'message': 'Finished before upgrade', 'result_json': result_json,
            'last_error': None, 'created_by': 'tester', 'created_at': '2026-09-29T10:00:00+00:00',
            'started_at': '2026-09-29T10:01:00+00:00', 'updated_at': '2026-09-29T10:02:00+00:00',
            'finished_at': '2026-09-29T10:02:00+00:00',
        },
        {
            'id': 11, 'cache_key': 'legacy-processing', 'method_version': 'method-v1',
            'source_fingerprint': 'fingerprint-processing', 'dataset_ids_json': '[9]',
            'source_metadata_json': '[]', 'nr_mode': 'SA', 'levels_json': '["City"]',
            'baseline_operator': 'EE', 'status': 'processing', 'progress': 45,
            'message': 'Calculating KPIs', 'result_json': None, 'last_error': None,
            'created_by': 'tester', 'created_at': '2026-09-29T11:00:00+00:00',
            'started_at': '2026-09-29T11:01:00+00:00', 'updated_at': '2026-09-29T11:02:00+00:00',
            'finished_at': None,
        },
        {
            'id': 13, 'cache_key': 'legacy-failed', 'method_version': 'method-v1',
            'source_fingerprint': 'fingerprint-failed', 'dataset_ids_json': '[10]',
            'source_metadata_json': '[]', 'nr_mode': 'NSA', 'levels_json': '["Vendor"]',
            'baseline_operator': 'EE', 'status': 'failed', 'progress': 60,
            'message': 'Earlier failure', 'result_json': None, 'last_error': 'Source error',
            'created_by': 'tester', 'created_at': '2026-09-29T12:00:00+00:00',
            'started_at': '2026-09-29T12:01:00+00:00', 'updated_at': '2026-09-29T12:02:00+00:00',
            'finished_at': '2026-09-29T12:02:00+00:00',
        },
    ]
    with repository.connection() as connection:
        connection.execute('DROP TABLE scoring_jobs')
        connection.execute(legacy_ddl)
        columns = list(legacy_jobs[0])
        quoted_columns = ', '.join(f'"{column}"' for column in columns)
        placeholders = ', '.join('?' for _ in columns)
        for job in legacy_jobs:
            connection.execute(
                f'INSERT INTO scoring_jobs ({quoted_columns}) VALUES ({placeholders})',
                [job[column] for column in columns],
            )
        connection.execute("UPDATE sqlite_sequence SET seq = 42 WHERE name = 'scoring_jobs'")
        connection.execute(
            'CREATE INDEX idx_scoring_jobs_cache_key ON scoring_jobs(cache_key, id DESC)'
        )
        connection.execute(
            "CREATE UNIQUE INDEX idx_scoring_jobs_active_cache ON scoring_jobs(cache_key) "
            "WHERE status IN ('queued', 'processing')"
        )

    repository.initialize()

    with repository.connection() as connection:
        migrated_jobs = [
            dict(row) for row in connection.execute('SELECT * FROM scoring_jobs ORDER BY id').fetchall()
        ]
        index_rows = connection.execute('PRAGMA index_list(scoring_jobs)').fetchall()
        index_metadata = {row['name']: (int(row['unique']), int(row['partial'])) for row in index_rows}
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'scoring_jobs'"
        ).fetchone()['sql']

    expected_jobs = [
        {**job, 'status': 'completed'} if job['status'] == 'ready' else job
        for job in legacy_jobs
    ]
    assert migrated_jobs == expected_jobs
    assert result_json == migrated_jobs[0]['result_json']
    assert "'completed'" in table_sql and "'ready'" not in table_sql
    assert index_metadata['idx_scoring_jobs_cache_key'] == (0, 0)
    assert index_metadata['idx_scoring_jobs_active_cache'] == (1, 1)

    repository.initialize()
    with repository.connection() as connection:
        repeated_jobs = [
            dict(row) for row in connection.execute('SELECT * FROM scoring_jobs ORDER BY id').fetchall()
        ]
        cursor = connection.execute(
            "INSERT INTO scoring_jobs (cache_key, method_version, source_fingerprint, nr_mode) "
            "VALUES ('new-after-migration', 'method-v1', 'new-source', 'NSA')"
        )
    assert repeated_jobs == expected_jobs
    assert cursor.lastrowid == 43


def test_workspace_database_backup_restore_keeps_completed_scoring_results(client, tmp_path: Path, scoring_engine):
    import src.DashboardAnalytic as app_module

    _engine, _calls = scoring_engine
    workspace = app_module.active_workspace
    assert workspace is not None
    app_module.repository.replace_scoring_configuration(scoring_configuration())
    dataset_id = add_dataset(app_module.repository, 'Backup_NSA_Data.csv')
    job, _ = scoring_jobs.create_scoring_job(
        app_module.repository, [dataset_id], ['Region'], 'NSA', username='tester',
    )
    completed = scoring_jobs.run_scoring_job(app_module.repository, job['id'])
    assert completed['status'] == 'completed'

    backup_path = app_module.create_recurring_database_backup({
        'components': ['workspace_database'],
        'workspace_ids': [workspace.id],
        'backup_path': str(tmp_path / 'scoring-backups'),
        'max_backups': 2,
    })
    with app_module.repository.connection() as connection:
        connection.execute('DELETE FROM scoring_jobs WHERE id = ?', (job['id'],))
    assert scoring_jobs.get_scoring_job(app_module.repository, job['id']) is None

    app_module.restore_database_backup(backup_path, ['workspace_database'])

    restored = scoring_jobs.get_scoring_job(app_module.repository, job['id'], include_result=True)
    assert restored is not None
    assert restored['status'] == 'completed'
    assert restored['result']['scoring'] == completed['result']['scoring']


def test_historical_jobs_use_current_environment_labels_without_rewriting_snapshots(repository, scoring_engine):
    dataset_id = add_dataset(repository)
    created, _ = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    scoring_jobs.run_scoring_job(repository, created['id'])
    original = scoring_jobs.get_scoring_job(repository, created['id'], include_result=True)
    configuration = repository.get_scoring_configuration()
    scope = configuration['scope']
    scope['environments']['Drive - City'] = scope['environments'].pop('DriveCity')
    scope['environments']['Drive - City']['display_name'] = 'Drive - City'
    scope['environment_mapping'] = {
        source: 'Drive - City' if target == 'DriveCity' else target
        for source, target in scope['environment_mapping'].items()
    }
    for metric in configuration['metrics']:
        metric['contexts']['Drive - City'] = metric['contexts'].pop('DriveCity')
    repository.replace_scoring_configuration(configuration)

    displayed = scoring_jobs.get_scoring_job(repository, created['id'], include_result=True)
    assert displayed['configuration']['scope']['environments']['DriveCity']['display_name'] == 'Drive - City'
    assert displayed['result']['configuration']['scope']['environments']['DriveCity']['display_name'] == 'Drive - City'
    assert displayed['result']['scoring'] == original['result']['scoring']
    assert displayed['configuration']['metrics'] == original['configuration']['metrics']
    stored = scoring_jobs.get_scoring_job(repository, created['id'], include_result=True,
                                           include_internal_snapshot=True)
    assert stored['configuration'] == original['configuration']
    assert stored['result'] == original['result']
    new, reused = scoring_jobs.create_scoring_job(repository, [dataset_id], ['Region'], 'NSA')
    assert not reused
    assert 'Drive - City' in new['configuration']['scope']['environments']
