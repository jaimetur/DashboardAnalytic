"""Source matching for the migrated NetCheck 2026 road environment."""
import pytest
import pandas as pd

from src.modules.repository import Repository
from src.modules.scoring import calculate_scoring
from src.modules.scoring_config import default_scoring_profile
from tests.scoring_fixtures import scoring_configuration


def test_explicit_legacy_road_name_is_retained_after_user_rename(tmp_path):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    profile = default_scoring_profile(scoring_configuration())
    environment = profile['configuration']['scope']['environments']['DriveConnectionroad']
    environment['display_name'] = 'DriveConnectionroad'
    environment['g_level_2'] = 'Connecting Roads'
    profile['configuration']['scope']['environment_mapping'] = {
        'Drive + City': 'DriveCity', 'Drive + Connecting Roads': 'DriveConnectionroad', 'Walk': 'Walk',
    }
    repository.replace_scoring_profiles({
        'active_profile_id': profile['id'], 'profiles': [profile],
    })

    restored = repository.get_scoring_configuration()
    assert 'DriveConnectionroad' in restored['scope']['environments']
    assert 'Drive Connecting Roads' not in restored['scope']['environments']
    assert all('DriveConnectionroad' in metric['contexts'] for metric in restored['metrics'])


def test_migrated_road_selector_scores_connecting_roads_and_keeps_350_point_allocation(tmp_path):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    legacy_profile = default_scoring_profile(scoring_configuration())
    repository.replace_scoring_profiles({
        'active_profile_id': legacy_profile['id'],
        'profiles': [legacy_profile],
    })
    configuration = repository.get_scoring_configuration()

    road_name = 'Drive Connecting Roads'
    road_environment = configuration['scope']['environments'][road_name]
    assert road_environment['g_level_1'] == 'Drive'
    assert road_environment['g_level_2'] == 'Connecting Roads'
    assert road_environment['total_points'] == pytest.approx(350)
    assert sum(metric['contexts'][road_name]['max_points'] for metric in configuration['metrics']) == pytest.approx(350)

    source = pd.DataFrame([
        {
            'Campaign': '2026-Q2', 'Operator': 'EE', 'G_Level_1': 'Drive',
            'G_Level_2': 'Connecting Roads', 'Session_Type': 'CALL', 'Call_Status': 'Completed',
        },
        {
            'Campaign': '2026-Q2', 'Operator': 'EE', 'G_Level_1': 'Drive',
            'G_Level_2': 'Connecting Roads', 'Session_Type': 'CALL', 'Call_Status': 'Completed',
        },
        {
            'Campaign': '2026-Q2', 'Operator': 'EE', 'G_Level_1': 'Drive',
            'G_Level_2': 'Connectionroad', 'Session_Type': 'CALL', 'Call_Status': 'Dropped',
        },
    ])
    result = calculate_scoring(
        {'voice': source}, ['Operator'], baseline_operator='EE', configuration=configuration,
    )

    assert {row['environment'] for row in result['scoring']} == {road_name}
    call_success = next(row for row in result['scoring'] if row['kpi_code'] == 'K1')
    assert call_success['value'] == pytest.approx(100)
    assert call_success['score'] == pytest.approx(1)
    assert call_success['sample_count'] == 2
    assert call_success['max_points'] == pytest.approx(
        next(metric for metric in configuration['metrics'] if metric['code'] == 'K1')
        ['contexts'][road_name]['max_points'],
    )
    road_total = next(
        row for row in result['totals']
        if row['environment'] == road_name and row['category'] == 'Overall'
    )
    assert road_total['max_points'] == pytest.approx(350)
    assert any('unsupported or missing environment' in warning for warning in result['warnings'])
