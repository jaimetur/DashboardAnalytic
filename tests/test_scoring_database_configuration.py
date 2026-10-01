"""Database authority and import behavior for workspace scoring configuration."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.modules import scoring_config
from src.modules.repository import Repository, SCORING_CONFIGURATION_STATE_KEY
from src.modules.scoring_config import (
    CONFIGURATION_FORMAT,
    load_initial_scoring_configuration,
    validate_scoring_configuration,
)
from tests.scoring_fixtures import legacy_scoring_configuration, scoring_configuration


@pytest.fixture()
def repository(tmp_path: Path) -> Repository:
    instance = Repository(tmp_path / 'workspace.db')
    instance.initialize()
    return instance


def _metric(configuration: dict, code: str) -> dict:
    return next(metric for metric in configuration['metrics'] if metric['code'] == code)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def test_workspace_initialization_does_not_seed_scoring_or_read_the_reference(monkeypatch, tmp_path):
    def unexpected_seed_read(*_args, **_kwargs):
        raise AssertionError('Workspace initialization must not read a scoring seed file.')

    monkeypatch.setattr(scoring_config, 'load_initial_scoring_configuration', unexpected_seed_read)
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()

    assert repository.get_workspace_state(SCORING_CONFIGURATION_STATE_KEY) is None
    with pytest.raises(ValueError, match='Import a Scoring Configuration before calculating scoring'):
        repository.get_scoring_configuration()


@pytest.mark.parametrize('enveloped', [False, True])
def test_explicit_loader_accepts_bare_and_enveloped_configurations(tmp_path, enveloped):
    seed = scoring_configuration()
    payload = {
        'format': CONFIGURATION_FORMAT,
        'version': 1,
        'configuration': copy.deepcopy(seed),
    } if enveloped else seed
    path = tmp_path / 'scoring-seed.json'
    _write_json(path, payload)

    loaded = load_initial_scoring_configuration(path)

    assert len(loaded['metrics']) == 32
    assert loaded['scope']['total_max_points'] == pytest.approx(
        sum(metric['contexts'][environment]['max_points']
            for metric in loaded['metrics'] for environment in ('DriveCity', 'DriveConnectionroad')),
    )
    assert _metric(loaded, 'K1')['contexts']['DriveCity']['score_mapping']['high_score'] == pytest.approx(1.0)


def test_imported_workspace_config_survives_seed_file_unavailable_and_keeps_editable_values(
    repository, monkeypatch, tmp_path,
):
    configuration = scoring_configuration()
    c5 = _metric(configuration, 'K1')
    c5['contexts']['DriveCity']['max_points'] = 82.5
    c5['contexts']['DriveCity']['thresholds']['low'] = 87
    c5['contexts']['DriveCity']['score_mapping'] = {
        'low_score': 0.05, 'medium_score': 0.65, 'high_score': 0.95, 'ultra_score': 1.0,
    }
    configuration['gap_priority'] = [
        'K2', 'K1', *[code for code in configuration['gap_priority'] if code not in {'K1', 'K2'}],
    ]
    seed_path = tmp_path / 'explicit-import.json'
    _write_json(seed_path, {
        'format': CONFIGURATION_FORMAT,
        'version': 1,
        'configuration': configuration,
    })
    imported = load_initial_scoring_configuration(seed_path)
    repository.replace_scoring_configuration(imported)

    def deny_file_reads(*_args, **_kwargs):
        raise AssertionError('Reading a stored workspace configuration must not access JSON files.')

    monkeypatch.setattr(Path, 'read_text', deny_file_reads)
    loaded = repository.get_scoring_configuration()

    stored_c5 = _metric(loaded, 'K1')['contexts']['DriveCity']
    assert stored_c5['max_points'] == pytest.approx(82.5)
    assert stored_c5['thresholds']['low'] == pytest.approx(87)
    assert stored_c5['score_mapping']['high_score'] == pytest.approx(0.95)
    assert loaded['gap_priority'][:2] == ['K2', 'K1']
    assert loaded['scope']['total_max_points'] == pytest.approx(
        sum(metric['contexts'][environment]['max_points']
            for metric in loaded['metrics'] for environment in ('DriveCity', 'DriveConnectionroad')),
    )


def test_invalid_stored_configuration_fails_without_resetting_database_value(repository):
    invalid = scoring_configuration()
    _metric(invalid, 'K1')['calculation']['formula'] = 'AVG(__import__("os"))'
    raw = json.dumps(invalid, ensure_ascii=False)
    repository.set_workspace_state(SCORING_CONFIGURATION_STATE_KEY, raw)

    with pytest.raises(ValueError, match='Stored workspace scoring configuration is invalid'):
        repository.get_scoring_configuration()

    assert repository.get_workspace_state(SCORING_CONFIGURATION_STATE_KEY) == raw


@pytest.mark.parametrize(
    ('edit', 'message'),
    [
        (lambda config: _metric(config, 'K1')['calculation'].__setitem__('formula', 'AVG(__import__("os"))'), 'formula'),
        (lambda config: _metric(config, 'K1')['calculation']['filters'].__setitem__('Unknown_Field', ['x']), 'filter'),
        (lambda config: _metric(config, 'K20')['calculation']['filters'].__setitem__('Test_Name contains', 'FDTT'), 'list of text fragments'),
        (lambda config: config['scope']['environments'].__setitem__('Unknown', {}), 'g_level_1'),
        (lambda config: config['metrics'][0].__setitem__('direction', 'unknown'), 'direction'),
    ],
)
def test_validator_rejects_unsupported_calculations_filters_and_scope(edit, message):
    configuration = scoring_configuration()
    edit(configuration)

    with pytest.raises(ValueError, match=message):
        validate_scoring_configuration(configuration)


def test_configuration_import_envelope_with_null_payload_is_not_a_scoring_config():
    with pytest.raises(ValueError, match='does not contain a scoring configuration'):
        validate_scoring_configuration({
            'format': CONFIGURATION_FORMAT,
            'version': 1,
            'configuration': None,
        })


def test_workspace_configuration_derives_omitted_context_anchors_from_saved_interpolation(repository):
    configuration = scoring_configuration()
    configuration['interpolation'].update({
        'medium_score': .7, 'high_score_with_ultra': .9,
        'high_score_without_ultra': .98, 'ultra_score': 1,
    })
    for metric in configuration['metrics']:
        for context in metric['contexts'].values():
            context.pop('score_mapping', None)
    repository.replace_scoring_configuration(configuration)

    stored = repository.get_scoring_configuration()
    context = _metric(stored, 'K20')['contexts']['DriveCity']
    assert context['score_mapping']['medium_score'] == .7
    assert context['score_mapping']['high_score'] == .9
    assert _metric(stored, 'K1')['contexts']['DriveCity']['score_mapping']['high_score'] == .98


def test_bare_legacy_configuration_save_returns_migrated_k_codes(repository):
    repository.set_workspace_state(SCORING_CONFIGURATION_STATE_KEY, '')

    saved = repository.replace_scoring_configuration(legacy_scoring_configuration())

    assert saved['metrics'][0]['code'] == 'K1'
    assert repository.get_scoring_configuration()['metrics'][0]['code'] == 'K1'
