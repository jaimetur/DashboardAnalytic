from __future__ import annotations

import copy

import pandas as pd
import pytest

from src.modules.scoring import METHOD_VERSION, calculate_scoring, method_version_for_configuration
from src.modules.scoring_config import configuration_hash, validate_scoring_configuration
from tests.scoring_fixtures import legacy_scoring_configuration, scoring_configuration


def _legacy_configuration() -> dict:
    return legacy_scoring_configuration()


def test_legacy_configuration_migrates_walk_with_zero_points_and_city_rules():
    legacy = _legacy_configuration()
    original = copy.deepcopy(legacy)

    migrated = validate_scoring_configuration(legacy)

    assert legacy == original
    assert migrated['scope']['environments']['Walk'] == {
        'source_filters': {'G_Level_1': 'Walk'}, 'total_points': 0.0, 'weight_share': 0.0,
    }
    for source, result in zip(legacy['metrics'], migrated['metrics']):
        city = result['contexts']['DriveCity']
        walk = result['contexts']['Walk']
        assert walk['max_points'] == 0
        assert walk['thresholds'] == city['thresholds']
        assert walk['score_mapping'] == city['score_mapping']
        assert walk['weight_share'] == pytest.approx(city['weight_share'])
        assert result['calculation']['formula'] == source['calculation']['formula']
        assert result['calculation']['filters'] == source['calculation']['filters']
    assert method_version_for_configuration(legacy) == (
        f"{legacy['version']}-{METHOD_VERSION}-{configuration_hash(legacy)[:16]}"
    )


def test_walk_zero_shares_survive_validation_and_become_weights_when_enabled():
    configuration = scoring_configuration()
    configuration['metrics'] = copy.deepcopy(configuration['metrics'][:2])
    first, second = configuration['metrics']
    first['contexts']['Walk']['weight_share'] = 0.25
    second['contexts']['Walk']['weight_share'] = 0.75

    zero_weight = validate_scoring_configuration(configuration)
    assert [metric['contexts']['Walk']['weight_share'] for metric in zero_weight['metrics']] == [0.25, 0.75]
    assert zero_weight['scope']['environments']['Walk']['total_points'] == 0

    for metric in configuration['metrics']:
        metric['contexts']['Walk']['max_points'] = metric['contexts']['Walk']['weight_share'] * 20
    enabled = validate_scoring_configuration(configuration)
    assert [metric['contexts']['Walk']['weight_share'] for metric in enabled['metrics']] == [0.25, 0.75]
    assert [metric['contexts']['Walk']['max_points'] for metric in enabled['metrics']] == [5, 15]
    assert enabled['scope']['environments']['Walk']['total_points'] == 20


def test_walk_matches_only_level_one_and_is_excluded_from_combined_weight():
    configuration = scoring_configuration()
    metric = copy.deepcopy(next(item for item in configuration['metrics'] if item['code'] == 'K12'))
    metric['contexts']['DriveCity']['max_points'] = 60
    metric['contexts']['DriveConnectionroad']['max_points'] = 40
    metric['contexts']['Walk']['max_points'] = 0
    configuration['metrics'] = [metric]
    configuration['gap_priority'] = ['K12']
    configuration = validate_scoring_configuration(configuration)
    frame = pd.DataFrame([
        {'Campaign': '2026-Q2', 'G_Level_1': 'Drive', 'G_Level_2': 'City', 'Operator': 'EE',
         'Test_Name': 'FDFS DL', 'Test_Result': 'Completed'},
        {'Campaign': '2026-Q2', 'G_Level_1': 'Drive', 'G_Level_2': 'Connectionroad', 'Operator': 'EE',
         'Test_Name': 'FDFS DL', 'Test_Result': 'Completed'},
        {'Campaign': '2026-Q2', 'G_Level_1': 'Walk', 'G_Level_2': 'Any location', 'Operator': 'EE',
         'Test_Name': 'FDFS DL', 'Test_Result': 'Completed'},
    ])

    result = calculate_scoring({'data': frame}, configuration=configuration, baseline_operator='EE')

    walk_row = next(row for row in result['scoring'] if row['environment'] == 'Walk')
    assert walk_row['score'] == 1
    assert walk_row['max_points'] == 0
    assert walk_row['weighted_points'] == 0
    combined = next(
        row for row in result['totals']
        if row['environment'] == 'Combined' and row['category'] == 'Overall'
    )
    assert combined['weighted_points'] == 100
    assert combined['max_points'] == 100
    assert combined['complete_coverage'] is True
    assert combined['score'] == 1


def test_initial_methodology_includes_zero_weight_walk_context():
    configuration = validate_scoring_configuration(scoring_configuration())

    assert configuration['scope']['environments']['Walk']['total_points'] == 0
    assert configuration['scope']['environments']['Walk']['weight_share'] == 0
    assert all(metric['contexts']['Walk']['max_points'] == 0 for metric in configuration['metrics'])
    assert all(0 <= metric['contexts']['Walk']['weight_share'] <= 1 for metric in configuration['metrics'])
