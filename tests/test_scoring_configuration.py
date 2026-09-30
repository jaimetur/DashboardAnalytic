"""Validation and interpolation tests for workspace scoring configuration."""

import pytest

from src.modules.scoring import interpolate_score, method_version_for_configuration
from src.modules.scoring_config import (
    configuration_hash,
    validate_scoring_configuration,
)
from tests.scoring_fixtures import scoring_configuration


def metric(configuration, code):
    return next(item for item in configuration['metrics'] if item['code'] == code)


def test_test_configuration_fixture_is_complete_and_independent():
    first = scoring_configuration()
    second = scoring_configuration()

    assert len(first['metrics']) == 32
    assert first['gap_priority'] == [item['code'] for item in first['metrics']]
    assert set(metric(first, 'C9')['contexts']['DriveCity']['score_mapping']) == {
        'low_score', 'medium_score', 'high_score', 'ultra_score',
    }
    metric(first, 'C5')['contexts']['DriveCity']['max_points'] = 0
    assert metric(second, 'C5')['contexts']['DriveCity']['max_points'] > 0


def test_seed_fixture_has_kpi_specific_high_with_ultra_anchors():
    configuration = scoring_configuration()
    expected = {'low_score': 0.0, 'medium_score': 0.8, 'high_score': 0.9, 'ultra_score': 1.0}
    expected_source_formulas = {
        'C25': {'DriveCity': '=MAX(M23:O23)', 'DriveConnectionroad': '=MAX(K23:O23)'},
        'C30': {'DriveCity': '=MAX(M28:O28)', 'DriveConnectionroad': '=MAX(K28:O28)'},
    }

    for code in ('C25', 'C30'):
        for context_name, context in metric(configuration, code)['contexts'].items():
            assert context['score_mapping'] == expected
            assert context['thresholds']['ultra']['source_formula'] == expected_source_formulas[code][context_name]
    assert configuration['interpolation']['high_score_with_ultra'] == 0.95
    assert metric(configuration, 'C31')['contexts']['DriveCity']['score_mapping'] == {
        'low_score': 0.0, 'medium_score': 0.8, 'high_score': 0.95, 'ultra_score': 1.0,
    }
    assert metric(configuration, 'C31')['contexts']['DriveCity']['thresholds']['ultra']['source_formula'] == '=MIN(M29:O29)'
    assert metric(configuration, 'C31')['contexts']['DriveConnectionroad']['thresholds']['ultra']['source_formula'] == '=MIN(K29:O29)'


def test_piecewise_interpolation_uses_custom_mapping_anchors_for_both_directions():
    anchors = {'low_score': 0.1, 'medium_score': 0.55, 'high_score': 0.85, 'ultra_score': 1.0}
    higher = {'low': 0, 'medium': 10, 'high': 20, 'ultra': 30}
    lower = {'low': 10, 'medium': 5, 'high': 1, 'ultra': None}

    assert interpolate_score(5, higher, score_mapping=anchors) == pytest.approx(0.325)
    assert interpolate_score(25, higher, score_mapping=anchors) == pytest.approx(0.925)
    assert interpolate_score(7.5, lower, score_mapping=anchors) == pytest.approx(0.325)
    assert interpolate_score(1, lower, score_mapping=anchors) == pytest.approx(0.85)


def test_validation_accepts_editable_thresholds_weights_types_anchors_and_priority():
    configuration = scoring_configuration()
    c5 = metric(configuration, 'C5')
    c5['kpi_type'] = 'Reliable'
    c5['contexts']['DriveCity']['max_points'] = 80
    c5['contexts']['DriveCity']['thresholds']['low'] = 86
    c5['contexts']['DriveCity']['score_mapping'] = {
        'low_score': 0.05, 'medium_score': 0.7, 'high_score': 0.92, 'ultra_score': 1,
    }
    c6 = metric(configuration, 'C6')
    c6['contexts']['DriveCity']['thresholds']['low'] = 11
    configuration['gap_priority'] = ['C6', 'C5', *[code for code in configuration['gap_priority'] if code not in {'C5', 'C6'}]]

    validated = validate_scoring_configuration(configuration)

    assert metric(validated, 'C5')['contexts']['DriveCity']['max_points'] == 80
    assert metric(validated, 'C5')['contexts']['DriveCity']['thresholds']['low'] == 86
    assert metric(validated, 'C5')['contexts']['DriveCity']['score_mapping']['high_score'] == 0.92
    assert validated['gap_priority'][:2] == ['C6', 'C5']
    assert validated['scope']['total_max_points'] == pytest.approx(
        sum(item['contexts'][name]['max_points'] for item in validated['metrics']
            for name in ('DriveCity', 'DriveConnectionroad')),
    )
    assert configuration_hash(validated) != configuration_hash(scoring_configuration())
    assert method_version_for_configuration(validated) != method_version_for_configuration(scoring_configuration())


@pytest.mark.parametrize(
    ('edit', 'message'),
    [
        (lambda c: metric(c, 'C5')['contexts']['DriveCity'].__setitem__('max_points', float('nan')), 'finite number'),
        (lambda c: metric(c, 'C5')['contexts']['DriveCity']['thresholds'].__setitem__('low', 101), 'thresholds'),
        (lambda c: metric(c, 'C5')['contexts']['DriveCity']['score_mapping'].__setitem__('high_score', 1.1), 'at most 1'),
        (lambda c: metric(c, 'C5')['contexts']['DriveCity']['score_mapping'].__setitem__('high_score', 0.7), 'monotonic'),
        (lambda c: c.__setitem__('gap_priority', ['C5'] * 32), 'every supported KPI code exactly once'),
        (lambda c: metric(c, 'C5')['calculation'].__setitem__('formula', 'AVG(Other)'), 'unsupported voice field'),
        (lambda c: c['scope']['environments']['DriveCity'].__setitem__('g_level_2', 'Road'), 'is unsupported'),
    ],
)
def test_validation_rejects_invalid_or_source_methodology_edits(edit, message):
    configuration = scoring_configuration()
    edit(configuration)

    with pytest.raises(ValueError, match=message):
        validate_scoring_configuration(configuration)


def test_zero_weight_kpis_are_allowed_and_derived_totals_follow_configured_weights():
    configuration = scoring_configuration()
    metric(configuration, 'C5')['contexts']['DriveCity']['max_points'] = 0

    validated = validate_scoring_configuration(configuration)

    assert metric(validated, 'C5')['contexts']['DriveCity']['max_points'] == 0
    assert validated['scope']['environments']['DriveCity']['total_points'] < 650
