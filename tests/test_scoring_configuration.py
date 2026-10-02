"""Validation and interpolation tests for workspace scoring configuration."""

import copy

import pytest
import pandas as pd

from src.modules.scoring import _aggregate, interpolate_score, method_version_for_configuration
from src.modules.scoring_config import (
    DEFAULT_AGGREGATION_HIERARCHY,
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
    assert first['aggregation_hierarchy'] == DEFAULT_AGGREGATION_HIERARCHY
    assert first['gap_priority'] == [item['code'] for item in first['metrics']]
    assert set(metric(first, 'K5')['contexts']['DriveCity']['score_mapping']) == {
        'low_score', 'medium_score', 'high_score', 'ultra_score',
    }
    metric(first, 'K1')['contexts']['DriveCity']['max_points'] = 0
    assert metric(second, 'K1')['contexts']['DriveCity']['max_points'] > 0


def test_legacy_configuration_defaults_hierarchy_and_custom_order_changes_identity():
    configuration = scoring_configuration()
    legacy = dict(configuration)
    legacy.pop('aggregation_hierarchy')

    validated_legacy = validate_scoring_configuration(legacy)
    reordered = dict(configuration)
    reordered['aggregation_hierarchy'] = ['Campaign', 'City', 'Region', 'Vendor', 'Operator']

    assert validated_legacy['aggregation_hierarchy'] == DEFAULT_AGGREGATION_HIERARCHY
    assert configuration_hash(validated_legacy) == configuration_hash(configuration)
    assert configuration_hash(reordered) != configuration_hash(configuration)
    assert method_version_for_configuration(reordered) != method_version_for_configuration(configuration)


def test_minimal_import_defaults_interpolation_and_uses_only_supported_methodology_fields():
    configuration = scoring_configuration()
    configuration.pop('interpolation')
    configuration.pop('title')

    validated = validate_scoring_configuration(configuration)

    assert validated['title'] == ''
    assert validated['interpolation']['method'] == 'piecewise_linear'
    assert set(validated['scope']['environments']['DriveCity']) == {
        'source_filters', 'total_points', 'weight_share',
    }
    assert validated['scope']['environments']['DriveCity']['source_filters'] == {
        'G_Level_1': 'Drive', 'G_Level_2': 'City',
    }
    assert all(set(item['calculation']) in ({'formula', 'filters'}, {'formula', 'filters', 'totalpacketlost'})
               for item in validated['metrics'])
    assert all(not isinstance(context['thresholds'].get('ultra'), dict)
               or 'source_formula' not in context['thresholds']['ultra']
               for item in validated['metrics'] for context in item['contexts'].values())


def test_empty_interpolation_object_uses_supported_default_anchors():
    configuration = scoring_configuration()
    configuration['interpolation'] = {}

    validated = validate_scoring_configuration(configuration)

    assert validated['interpolation']['medium_score'] == 0.8
    assert validated['interpolation']['high_score_without_ultra'] == 1.0
    assert validated['interpolation']['high_score_with_ultra'] == 0.95
    assert validated['interpolation']['ultra_score'] == 1.0


def test_methodology_title_is_persisted_but_does_not_change_scoring_identity():
    configuration = scoring_configuration()
    named = copy.deepcopy(configuration)
    named['title'] = 'Urban Drive Quality'

    validated = validate_scoring_configuration(named)

    assert validated['title'] == 'Urban Drive Quality'
    assert configuration_hash(validated) == configuration_hash(configuration)
    assert method_version_for_configuration(validated) == method_version_for_configuration(configuration)


def test_seed_fixture_has_kpi_specific_high_with_ultra_anchors():
    configuration = scoring_configuration()
    for code in ('K20', 'K25'):
        for context_name, context in metric(configuration, code)['contexts'].items():
            assert context['thresholds']['ultra']['rule'] == 'best_max'
            assert 'source_formula' not in context['thresholds']['ultra']
    assert configuration['interpolation']['high_score_with_ultra'] == 0.95
    assert metric(configuration, 'K26')['contexts']['DriveCity']['score_mapping'] == {
        'low_score': 0.0, 'medium_score': 0.8, 'high_score': 0.95, 'ultra_score': 1.0,
    }
    assert metric(configuration, 'K26')['contexts']['DriveCity']['thresholds']['ultra']['rule'] == 'best_min'
    assert metric(configuration, 'K26')['contexts']['DriveConnectionroad']['thresholds']['ultra']['rule'] == 'best_min'


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
    c5 = metric(configuration, 'K1')
    c5['kpi_type'] = 'Reliable'
    c5['contexts']['DriveCity']['max_points'] = 80
    c5['contexts']['DriveCity']['thresholds']['low'] = 86
    c5['contexts']['DriveCity']['score_mapping'] = {
        'low_score': 0.05, 'medium_score': 0.7, 'high_score': 0.92, 'ultra_score': 1,
    }
    c6 = metric(configuration, 'K2')
    c6['contexts']['DriveCity']['thresholds']['low'] = 11
    configuration['gap_priority'] = ['K2', 'K1', *[code for code in configuration['gap_priority'] if code not in {'K1', 'K2'}]]

    validated = validate_scoring_configuration(configuration)

    assert metric(validated, 'K1')['contexts']['DriveCity']['max_points'] == 80
    assert metric(validated, 'K1')['contexts']['DriveCity']['thresholds']['low'] == 86
    assert metric(validated, 'K1')['contexts']['DriveCity']['score_mapping']['high_score'] == 0.92
    assert validated['gap_priority'][:2] == ['K2', 'K1']
    assert validated['scope']['total_max_points'] == pytest.approx(
        sum(item['contexts'][name]['max_points'] for item in validated['metrics']
            for name in ('DriveCity', 'DriveConnectionroad')),
    )
    assert configuration_hash(validated) != configuration_hash(scoring_configuration())
    assert method_version_for_configuration(validated) != method_version_for_configuration(scoring_configuration())


def test_invalid_global_interpolation_anchor_order_is_rejected_with_explicit_context_mappings():
    configuration = scoring_configuration()
    configuration['interpolation']['high_score_with_ultra'] = 0.7

    with pytest.raises(ValueError, match='interpolation anchors must increase'):
        validate_scoring_configuration(configuration)


@pytest.mark.parametrize(
    ('edit', 'message'),
    [
        (lambda c: metric(c, 'K1')['contexts']['DriveCity'].__setitem__('max_points', float('nan')), 'finite number'),
        (lambda c: metric(c, 'K1')['contexts']['DriveCity']['thresholds'].__setitem__('low', 101), 'thresholds'),
        (lambda c: metric(c, 'K1')['contexts']['DriveCity']['score_mapping'].__setitem__('high_score', 1.1), 'at most 1'),
        (lambda c: metric(c, 'K1')['contexts']['DriveCity']['score_mapping'].__setitem__('high_score', 0.7), 'monotonic'),
        (lambda c: c.__setitem__('gap_priority', ['K1'] * 32), 'unique KPI codes'),
        (lambda c: c.__setitem__('aggregation_hierarchy', ['Operator', 'Vendor', 'Region', 'City', 'City']), 'aggregation_hierarchy'),
        (lambda c: metric(c, 'K1')['calculation'].__setitem__('formula', 'AVG(Other)'), 'unsupported voice field'),
        (lambda c: c['scope']['environments']['DriveCity']['source_filters'].__setitem__('G_Level_2', ''), 'non-empty'),
    ],
)
def test_validation_rejects_invalid_or_source_methodology_edits(edit, message):
    configuration = scoring_configuration()
    edit(configuration)

    with pytest.raises(ValueError, match=message):
        validate_scoring_configuration(configuration)


@pytest.mark.parametrize(
    ('filters', 'message'),
    [
        ({'Region': 'North'}, 'G_Level_1 and optional G_Level_2'),
        ({'G_Level_1': ''}, 'source_filters.G_Level_1'),
        ({'G_Level_1': 'Drive', 'G_Level_2': '  '}, 'source_filters.G_Level_2'),
    ],
)
def test_source_filters_require_supported_fields_and_nonempty_values(filters, message):
    configuration = scoring_configuration()
    configuration['scope']['environments']['DriveCity']['source_filters'] = filters

    with pytest.raises(ValueError, match=message):
        validate_scoring_configuration(configuration)


def test_source_filters_select_environment_rows_during_calculation():
    from src.modules.scoring import calculate_scoring

    configuration = scoring_configuration()
    configuration['scope']['environments']['DriveCity']['source_filters']['G_Level_2'] = 'Urban'
    source = pd.DataFrame({
        'Operator': ['EE', 'EE'], 'Campaign': ['2026Q2', '2026Q2'],
        'G_Level_1': ['Drive', 'Drive'], 'G_Level_2': ['Urban', 'City'],
        'Session_Type': ['CALL', 'CALL'], 'Call_Status': ['Completed', 'Failed'],
    })

    result = calculate_scoring({'voice': source}, configuration=configuration)
    city_kpi = next(row for row in result['scoring']
                    if row['kpi_code'] == 'K1' and row['environment'] == 'DriveCity')

    assert city_kpi['value'] == 100
    assert city_kpi['sample_count'] == 1


def test_validation_and_calculation_support_added_removed_and_reclassified_kpis():
    configuration = scoring_configuration()
    existing = metric(configuration, 'K26')
    added = dict(existing)
    added['contexts'] = {name: dict(context) for name, context in existing['contexts'].items()}
    added.update({
        'code': 'QOS_99',
        'source_kind': 'data',
        'direction': 'lower_is_better',
        'category': 'Custom Quality',
        'kpi': 'Completed Result Ratio',
        'kpi_type': 'Custom',
        'calculation': {
            'formula': '100 * SUM(Test_Result == "Completed") / COUNT(Test_Result)',
            'filters': {},
        },
    })
    configuration['metrics'] = [existing, added]
    configuration['gap_priority'] = ['QOS_99', 'K1']

    validated = validate_scoring_configuration(configuration)
    result = _aggregate(pd.DataFrame({'Test_Result': ['Completed', 'Failed', 'Completed']}), added)

    assert [item['code'] for item in validated['metrics']] == ['K26', 'QOS_99']
    assert validated['gap_priority'] == ['QOS_99', 'K26']
    assert result == (pytest.approx(200 / 3), 3)


def test_formula_validation_rejects_executable_python_expressions():
    configuration = scoring_configuration()
    metric(configuration, 'K1')['calculation']['formula'] = "__import__('os').system('whoami')"

    with pytest.raises(ValueError, match='formula is unsupported'):
        validate_scoring_configuration(configuration)


def test_ratio_without_percentage_multiplier_is_validated_and_calculated():
    configuration = scoring_configuration()
    selected = metric(configuration, 'K20')
    selected['calculation']['formula'] = 'SUM(Mean_Data_Rate) / COUNT(Mean_Data_Rate)'
    selected['calculation']['filters'] = {}

    validated = validate_scoring_configuration(configuration)
    result = _aggregate(pd.DataFrame({'Mean_Data_Rate': [1.0, 3.0, None]}), metric(validated, 'K20'))

    assert result == (2.0, 2)


def test_zero_weight_kpis_are_allowed_and_derived_totals_follow_configured_weights():
    configuration = scoring_configuration()
    metric(configuration, 'K1')['contexts']['DriveCity']['max_points'] = 0

    validated = validate_scoring_configuration(configuration)

    assert metric(validated, 'K1')['contexts']['DriveCity']['max_points'] == 0
    assert validated['scope']['environments']['DriveCity']['total_points'] < 650


def test_named_environments_are_dynamic_and_can_be_deleted_without_legacy_walk_migration():
    configuration = scoring_configuration()
    configuration['scope']['environments']['Indoor'] = {
        'source_filters': {'G_Level_1': 'Indoor', 'G_Level_2': 'Hall'},
    }
    for item in configuration['metrics']:
        context = dict(item['contexts']['DriveCity'])
        context['max_points'] = 0
        context['weight_share'] = item['contexts']['DriveCity']['weight_share']
        item['contexts']['Indoor'] = context

    validated = validate_scoring_configuration(configuration)

    assert list(validated['scope']['environments'])[-1] == 'Indoor'
    assert all('Indoor' in item['contexts'] for item in validated['metrics'])
    assert validated['scope']['environments']['Indoor']['total_points'] == 0
    assert sum(item['contexts']['Indoor']['weight_share'] for item in validated['metrics']) == pytest.approx(1)

    validated['scope']['environments'].pop('Walk')
    for item in validated['metrics']:
        item['contexts'].pop('Walk')
    without_walk = validate_scoring_configuration(validated)

    assert 'Walk' not in without_walk['scope']['environments']
    assert all('Walk' not in item['contexts'] for item in without_walk['metrics'])


def test_kpi_allocator_survives_deletion_and_never_reuses_a_generated_code():
    configuration = scoring_configuration()
    assert configuration['next_kpi_number'] == 33
    allocator_only_change = copy.deepcopy(configuration)
    allocator_only_change['next_kpi_number'] = 57
    assert configuration_hash(allocator_only_change) == configuration_hash(configuration)
    assert method_version_for_configuration(allocator_only_change) == method_version_for_configuration(configuration)
    configuration['metrics'].pop()
    configuration['gap_priority'].remove('K32')

    deleted = validate_scoring_configuration(configuration)
    assert deleted['next_kpi_number'] == 33

    added = dict(deleted['metrics'][-1])
    added['contexts'] = {name: dict(context) for name, context in added['contexts'].items()}
    added['code'] = 'K33'
    deleted['metrics'].append(added)
    deleted['gap_priority'].append('K33')

    validated = validate_scoring_configuration(deleted)
    assert validated['metrics'][-1]['code'] == 'K33'
    assert validated['next_kpi_number'] == 34


def test_environment_source_selectors_must_not_overlap_or_use_combined_name():
    configuration = scoring_configuration()
    configuration['scope']['environments']['Combined'] = {
        'source_filters': {'G_Level_1': 'Indoor'},
    }
    for item in configuration['metrics']:
        item['contexts']['Combined'] = dict(item['contexts']['DriveCity'])
    with pytest.raises(ValueError, match='cannot be Combined'):
        validate_scoring_configuration(configuration)

    configuration['scope']['environments'].pop('Combined')
    configuration['scope']['environments']['Indoor'] = {
        'source_filters': {'G_Level_1': 'Walk'},
    }
    for item in configuration['metrics']:
        item['contexts'].pop('Combined')
        item['contexts']['Indoor'] = dict(item['contexts']['Walk'])
    with pytest.raises(ValueError, match='overlapping source selectors'):
        validate_scoring_configuration(configuration)


def test_mapping_method_defaults_preserve_legacy_configuration_identity_and_results():
    from src.modules.scoring import calculate_scoring

    legacy = scoring_configuration()
    for item in legacy['metrics']:
        item.pop('mapping_method', None)
    original_hash = configuration_hash(legacy)
    original_version = method_version_for_configuration(legacy)
    explicit = validate_scoring_configuration(legacy)
    assert all(item['mapping_method'] == legacy['interpolation']['method'] for item in explicit['metrics'])
    assert configuration_hash(explicit) == original_hash
    assert method_version_for_configuration(explicit) == original_version
    frames = {'voice': pd.DataFrame({
        'Campaign': ['2026Q2', '2026Q2'], 'Operator': ['EE', 'EE'],
        'G_Level_1': ['Drive', 'Drive'], 'G_Level_2': ['City', 'City'],
        'Session_Type': ['CALL', 'CALL'], 'Call_Status': ['Completed', 'Failed'],
    })}
    old_result = calculate_scoring(frames, configuration=legacy)
    explicit_result = calculate_scoring(frames, configuration=explicit)
    assert old_result == explicit_result
    thresholds = metric(explicit, 'K1')['contexts']['DriveCity']['thresholds']
    assert interpolate_score(99, thresholds) == interpolate_score(99, thresholds, mapping_method='piecewise_linear')


@pytest.mark.parametrize('unsupported', ['logarithmic', '', None, [], 1])
def test_unsupported_mapping_method_is_rejected_by_validation_and_engine(unsupported):
    from src.modules.scoring import calculate_scoring

    configuration = scoring_configuration()
    metric(configuration, 'K1')['mapping_method'] = unsupported
    with pytest.raises(ValueError, match='mapping_method'):
        validate_scoring_configuration(configuration)
    with pytest.raises(ValueError, match='mapping_method'):
        calculate_scoring({}, configuration=configuration)
    with pytest.raises(ValueError, match='Unsupported scoring mapping method'):
        interpolate_score(1, {'low': 0, 'medium': 1, 'high': 2, 'ultra': None}, mapping_method=unsupported)


@pytest.mark.parametrize(('mapping_method', 'quarter', 'midpoint'), [
    ('piecewise_linear', .25, .5),
    ('piecewise_quadratic', .0625, .25),
    ('piecewise_smoothstep', .15625, .5),
])
@pytest.mark.parametrize('direction', [1, -1])
def test_selected_mapping_preserves_anchors_and_clamps_in_both_directions(mapping_method, quarter, midpoint, direction):
    thresholds = {'low': 0 * direction, 'medium': 10 * direction,
                  'high': 20 * direction, 'ultra': 30 * direction}
    anchors = {'low_score': .1, 'medium_score': .5, 'high_score': .9, 'ultra_score': 1.}
    def score(value):
        return interpolate_score(value * direction, thresholds, score_mapping=anchors, mapping_method=mapping_method)
    assert [score(x) for x in [-10, 0, 10, 20, 30, 40]] == pytest.approx([.1, .1, .5, .9, 1, 1])
    assert score(2.5) == pytest.approx(.1 + .4 * quarter)
    assert score(15) == pytest.approx(.5 + .4 * midpoint)
    assert score(22.5) == pytest.approx(.9 + .1 * quarter)
    assert score(25) == pytest.approx(.9 + .1 * midpoint)
    dynamic = {**thresholds, 'ultra': {'rule': 'best_max' if direction == 1 else 'best_min'}}
    assert interpolate_score(15 * direction, dynamic, ultra=15 * direction,
                             score_mapping=anchors, mapping_method=mapping_method) == pytest.approx(.5 + .4 * midpoint)


@pytest.mark.parametrize(('mapping_method', 'expected'), [
    ('piecewise_linear', .6), ('piecewise_quadratic', .45), ('piecewise_smoothstep', .675),
])
def test_engine_uses_each_kpi_selected_mapping_method(mapping_method, expected):
    from src.modules.scoring import calculate_scoring

    configuration = scoring_configuration()
    selected = metric(configuration, 'K1')
    selected['mapping_method'] = mapping_method
    selected['contexts']['DriveCity']['thresholds'] = {'low': 0, 'medium': 100, 'high': 200, 'ultra': None}
    selected['contexts']['DriveCity']['score_mapping'] = {'low_score': 0, 'medium_score': .8, 'high_score': 1, 'ultra_score': 1}
    frames = {'voice': pd.DataFrame({
        'Campaign': ['2026Q2'] * 4, 'Operator': ['EE'] * 4,
        'G_Level_1': ['Drive'] * 4, 'G_Level_2': ['City'] * 4,
        'Session_Type': ['CALL'] * 4, 'Call_Status': ['Completed'] * 3 + ['Failed'],
    })}
    result = calculate_scoring(frames, configuration=configuration)
    row = next(row for row in result['scoring'] if row['kpi_code'] == 'K1')
    assert row['value'] == 75
    assert row['score'] == pytest.approx(expected)
    linear = copy.deepcopy(configuration)
    metric(linear, 'K1')['mapping_method'] = 'piecewise_linear'
    if mapping_method != 'piecewise_linear':
        assert configuration_hash(configuration) != configuration_hash(linear)
