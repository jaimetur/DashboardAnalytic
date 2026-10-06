from __future__ import annotations

import copy

from src.modules.repository import Repository
from src.modules.scoring_config import (
    default_scoring_profile,
    unwrap_scoring_profiles_payload,
    validate_scoring_profiles,
)
from tests.scoring_fixtures import scoring_configuration


def test_legacy_single_configuration_import_becomes_one_named_profile():
    configuration = scoring_configuration()

    profiles = unwrap_scoring_profiles_payload({
        'format': 'drivetest-analyzer-scoring-configuration',
        'version': 1,
        'configuration': configuration,
    })

    assert profiles['active_profile_id'] == 'netcheck-2026'
    assert profiles['profiles'] == [default_scoring_profile(configuration)]


def test_workspace_persists_multiple_profiles_and_active_selection(tmp_path):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    config_2026 = scoring_configuration()
    config_2025 = copy.deepcopy(config_2026)
    config_2025['version'] = 'NetCheck 2025'
    profile_2026 = default_scoring_profile(config_2026)
    profile_2025 = default_scoring_profile(config_2025)
    collection = validate_scoring_profiles({
        'active_profile_id': profile_2026['id'],
        'profiles': [profile_2026, profile_2025],
    })

    repository.replace_scoring_profiles(collection)
    saved = repository.get_scoring_profiles()
    migrated_2026 = saved['profiles'][0]['configuration']
    assert 'Drive Connecting Roads' in migrated_2026['scope']['environments']
    assert repository.get_scoring_configuration() == migrated_2026

    saved['active_profile_id'] = profile_2025['id']
    repository.replace_scoring_profiles(saved)
    assert repository.get_scoring_configuration() == config_2025

    updated_2025 = copy.deepcopy(config_2025)
    updated_2025['metrics'][0]['contexts']['DriveCity']['max_points'] = 81
    repository.replace_scoring_configuration(updated_2025)
    remaining = repository.get_scoring_profiles()
    assert remaining['active_profile_id'] == profile_2025['id']
    assert remaining['profiles'][0]['configuration'] == migrated_2026
    assert remaining['profiles'][1]['configuration']['metrics'][0]['contexts']['DriveCity']['max_points'] == 81


def test_workspace_profile_read_migrates_only_the_known_2026_environment(tmp_path):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    current = scoring_configuration()
    historical = copy.deepcopy(current)
    historical['version'] = 'NetCheck 2025'
    profiles = validate_scoring_profiles({
        'active_profile_id': 'netcheck-2026',
        'profiles': [default_scoring_profile(current), default_scoring_profile(historical)],
    })
    repository.replace_scoring_profiles(profiles)

    loaded = repository.get_scoring_profiles()
    current_profile = next(profile for profile in loaded['profiles'] if profile['id'] == 'netcheck-2026')
    current_config = current_profile['configuration']
    source = current_config['scope']['environments']['Drive Connecting Roads']
    assert source['source_filters'] == {'G_Level_1': 'Drive', 'G_Level_2': 'Connecting Roads'}
    assert source['display_name'] == 'Drive Connecting Roads'
    assert 'DriveConnectionroad' not in current_config['scope']['environments']

    for original, migrated in zip(current['metrics'], current_config['metrics']):
        assert migrated['contexts']['Drive Connecting Roads'] == original['contexts']['DriveConnectionroad']
        assert migrated['contexts']['DriveCity'] == original['contexts']['DriveCity']
        assert migrated['contexts']['Walk'] == original['contexts']['Walk']

    historical_profile = next(profile for profile in loaded['profiles'] if profile['id'] == 'netcheck-2025')
    assert historical_profile['configuration']['scope']['environments']['DriveConnectionroad']['source_filters'] == {
        'G_Level_1': 'Drive', 'G_Level_2': 'Connectionroad',
    }
    assert 'DriveConnectionroad' in historical_profile['configuration']['metrics'][0]['contexts']


def test_workspace_profile_read_migrates_legacy_key_with_correct_selector(tmp_path):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    configuration = scoring_configuration()
    configuration['scope']['environments']['DriveConnectionroad']['source_filters']['G_Level_2'] = 'Connecting Roads'
    repository.replace_scoring_profiles({
        'active_profile_id': 'netcheck-2026',
        'profiles': [default_scoring_profile(configuration)],
    })

    loaded = repository.get_scoring_profiles()['profiles'][0]['configuration']
    assert loaded['scope']['environments']['Drive Connecting Roads']['source_filters'] == {
        'G_Level_1': 'Drive', 'G_Level_2': 'Connecting Roads',
    }
    assert loaded['metrics'][0]['contexts']['Drive Connecting Roads'] == configuration['metrics'][0]['contexts']['DriveConnectionroad']


def test_workspace_profile_read_preserves_a_custom_road_selector(tmp_path):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    configuration = scoring_configuration()
    configuration['scope']['environments']['DriveConnectionroad']['source_filters']['G_Level_2'] = 'Alternative Road'
    repository.replace_scoring_profiles({
        'active_profile_id': 'netcheck-2026',
        'profiles': [default_scoring_profile(configuration)],
    })

    loaded = repository.get_scoring_profiles()['profiles'][0]['configuration']
    assert loaded['scope']['environments']['DriveConnectionroad']['source_filters'] == {
        'G_Level_1': 'Drive', 'G_Level_2': 'Alternative Road',
    }
    assert 'Drive Connecting Roads' not in loaded['scope']['environments']
