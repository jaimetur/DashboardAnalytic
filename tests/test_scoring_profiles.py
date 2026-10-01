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
        'format': 'dashboard-analytic-scoring-configuration',
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

    saved = repository.replace_scoring_profiles(collection)
    assert repository.get_scoring_profiles() == saved
    assert repository.get_scoring_configuration() == config_2026

    saved['active_profile_id'] = profile_2025['id']
    repository.replace_scoring_profiles(saved)
    assert repository.get_scoring_configuration() == config_2025

    updated_2025 = copy.deepcopy(config_2025)
    updated_2025['metrics'][0]['contexts']['DriveCity']['max_points'] = 81
    repository.replace_scoring_configuration(updated_2025)
    remaining = repository.get_scoring_profiles()
    assert remaining['active_profile_id'] == profile_2025['id']
    assert remaining['profiles'][0]['configuration'] == config_2026
    assert remaining['profiles'][1]['configuration']['metrics'][0]['contexts']['DriveCity']['max_points'] == 81
