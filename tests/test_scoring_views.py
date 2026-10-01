"""Reference-style table projection tests for saved scoring results."""
import copy

import pytest

from scoring_fixtures import scoring_configuration
from src.modules.scoring_config import validate_scoring_configuration
from src.modules.scoring_views import (
    THRESHOLD_COLORS, build_scoring_views as _build_scoring_views, gap_color, normalize_result_gaps,
)


CONFIG = scoring_configuration()
METRICS = CONFIG['metrics']
OPERATOR_MAPPING_GROUPS = [
    {'canonical': 'Vodafone UK', 'aliases': [], 'position': 0, 'color': '#DA291C'},
    {'canonical': 'O2 UK', 'aliases': [], 'position': 1, 'color': '#1174E6'},
    {'canonical': 'Three UK', 'aliases': [], 'position': 2, 'color': '#000000'},
    {'canonical': 'EE', 'aliases': ['EE (UK)'], 'position': 3, 'color': '#17A09F'},
]


def build_scoring_views(job, result, operator_mapping_groups=None):
    """Supply the same explicit workspace configuration as the application caller."""
    return _build_scoring_views(
        job, result, operator_mapping_groups, workspace_configuration=CONFIG,
    )


def metric_row(metric, operator, environment='DriveCity', *, score=1.0, value=10.0, region='North', **extra):
    maximum = metric['contexts'][environment]['max_points']
    return {
        'campaign': '2026Q2', 'region': region, 'operator': operator,
        'environment': environment, 'kpi_code': metric['code'],
        'category': metric['category'], 'kpi': metric['kpi'],
        'kpi_type': metric['kpi_type'], 'value': value,
        'score': score, 'weighted_points': maximum * score,
        'max_points': maximum, 'sample_count': 4, **extra,
    }


def full_result(operators=('Vodafone UK', 'O2 UK', 'Three UK', 'EE (UK)'), environments=('DriveCity',)):
    rows = []
    for environment in environments:
        for operator in operators:
            for index, metric in enumerate(METRICS):
                score = 1.0
                if operator == 'O2 UK' and index == 0:
                    score = 0.5
                elif operator == 'EE' and index == 0:
                    score = 0.8
                elif operator == 'Three UK' and index == 1:
                    score = 1.0
                rows.append(metric_row(metric, operator, environment, score=score, value=index + 1))
    return {'scoring': rows, 'totals': []}


def test_reference_matrix_contains_all_32_kpis_and_four_preserved_operator_columns():
    views = build_scoring_views(
        {'levels': ['Operator', 'Region'], 'baseline_operator': 'EE'},
        full_result(),
        operator_mapping_groups=OPERATOR_MAPPING_GROUPS,
    )

    assert len(views['score_tables']) == 1
    table = views['score_tables'][0]
    assert len(table['rows']) == 32
    assert [row['kpi_code'] for row in table['rows']] == [metric['code'] for metric in METRICS]
    assert table['operators'] == ['Vodafone UK', 'O2 UK', 'Three UK', 'EE (UK)']
    assert table['baseline_operator'] == 'EE (UK)'
    assert table['context']['region'] == 'North'
    assert table['context']['environment'] == 'DriveCity'
    assert 'dataset_type' not in table['context']
    assert all(set(row['values']) == set(table['operators']) for row in table['rows'])
    assert all({'kpi_code', 'category', 'kpi', 'kpi_type', 'weight_percent', 'max_points', 'values', 'gaps'} <= row.keys()
               for row in table['rows'])
    assert table['total']['max_points'] == pytest.approx(650)
    assert table['total']['weight_percent'] == pytest.approx(65)
    assert table['rows'][0]['values']['EE (UK)']['threshold_band'] == 'High'
    assert table['rows'][0]['values']['EE (UK)']['color'] == THRESHOLD_COLORS['High']
    assert len(views['threshold_legend']) == 5


def test_dataset_type_context_filters_to_its_kpis_and_contexts_do_not_merge():
    rows = []
    voice_metric = next(metric for metric in METRICS if metric['source_kind'] == 'voice')
    data_metric = next(metric for metric in METRICS if metric['source_kind'] == 'data')
    rows.extend([
        metric_row(voice_metric, 'EE', region='North', dataset_type='Voice'),
        metric_row(data_metric, 'EE', region='South', dataset_type='Data'),
    ])
    views = build_scoring_views({'levels': ['Operator', 'Region', 'Dataset Type']}, {'scoring': rows})

    assert len(views['score_tables']) == 2
    voice_table = next(table for table in views['score_tables'] if table['context']['dataset_type'] == 'Voice')
    data_table = next(table for table in views['score_tables'] if table['context']['dataset_type'] == 'Data')
    assert {row['kpi_code'] for row in voice_table['rows']} == {m['code'] for m in METRICS if m['source_kind'] == 'voice'}
    assert {row['kpi_code'] for row in data_table['rows']} == {m['code'] for m in METRICS if m['source_kind'] == 'data'}
    assert voice_table['context']['region'] == 'North'
    assert data_table['context']['region'] == 'South'


def test_combined_tables_require_both_real_environments_and_keep_partial_points():
    c5 = METRICS[0]
    rows = [
        metric_row(c5, 'EE', 'DriveCity', score=0.8),
        metric_row(c5, 'O2', 'DriveCity', score=0.5),
        metric_row(c5, 'EE', 'DriveConnectionroad', score=0.6),
    ]
    result = {'scoring': rows, 'totals': [
        {'campaign': '2026Q2', 'region': 'North', 'environment': 'DriveCity', 'operator': 'EE', 'category': 'Overall'},
        {'campaign': '2026Q2', 'region': 'North', 'environment': 'Combined', 'operator': 'EE', 'category': 'Overall'},
    ]}
    views = build_scoring_views({'levels': ['Operator', 'Region']}, result)

    assert [table['context']['environment'] for table in views['score_tables']] == [
        'DriveCity', 'DriveConnectionroad', 'Combined',
    ]
    combined = views['score_tables'][-1]
    c5_row = next(row for row in combined['rows'] if row['kpi_code'] == METRICS[0]['code'])
    assert c5_row['max_points'] == pytest.approx(
        c5['contexts']['DriveCity']['max_points'] + c5['contexts']['DriveConnectionroad']['max_points']
    )
    assert c5_row['values']['O2']['points'] == pytest.approx(c5_row['max_points'] * 0.5 * (
        c5['contexts']['DriveCity']['max_points'] / c5_row['max_points']
    ))
    assert c5_row['values']['O2']['complete'] is False
    assert c5_row['values']['O2']['value'] is None
    assert c5_row['values']['O2']['threshold_band'] == 'Unavailable'
    assert c5_row['values']['O2']['color'] == THRESHOLD_COLORS['Unavailable']
    assert c5_row['values']['EE']['complete'] is True
    assert combined['total']['max_points'] == pytest.approx(1000)
    road = next(table for table in views['score_tables'] if table['context']['environment'] == 'DriveConnectionroad')
    road_c5 = next(row for row in road['rows'] if row['kpi_code'] == METRICS[0]['code'])
    assert road_c5['values']['O2']['points'] is None
    assert road_c5['values']['O2']['complete'] is False

    city_only = build_scoring_views({'levels': ['Operator']}, {'scoring': [rows[0]], 'totals': result['totals']})
    assert [table['context']['environment'] for table in city_only['score_tables']] == ['DriveCity']
    assert 'Combined is not shown' in city_only['score_tables'][0]['coverage_note']


def test_combined_tables_follow_positive_environment_weights_and_require_walk_coverage():
    zero_walk = validate_scoring_configuration(scoring_configuration())
    assert zero_walk['scope']['environments']['Walk']['total_points'] == 0
    c5_zero_walk = zero_walk['metrics'][0]
    zero_walk_rows = [
        metric_row(c5_zero_walk, operator, environment, score=score)
        for environment in ('DriveCity', 'DriveConnectionroad')
        for operator, score in (('EE', 1.0), ('O2', 0.5))
    ]
    zero_views = _build_scoring_views(
        {'levels': ['Operator']}, {'scoring': zero_walk_rows, 'configuration': zero_walk},
    )
    zero_combined = next(table for table in zero_views['score_tables'] if table['context']['environment'] == 'Combined')
    zero_c5 = next(row for row in zero_combined['rows'] if row['kpi_code'] == c5_zero_walk['code'])
    assert zero_combined['combined_required_environments'] == ['DriveCity', 'DriveConnectionroad']
    assert zero_c5['max_points'] == pytest.approx(
        c5_zero_walk['contexts']['DriveCity']['max_points']
        + c5_zero_walk['contexts']['DriveConnectionroad']['max_points']
    )
    assert zero_c5['values']['O2']['complete'] is True

    walk_configuration = scoring_configuration()
    for metric in walk_configuration['metrics']:
        walk_context = copy.deepcopy(metric['contexts']['DriveCity'])
        walk_context['max_points'] = metric['contexts']['DriveCity']['max_points']
        metric['contexts']['Walk'] = walk_context
    walk_configuration = validate_scoring_configuration(walk_configuration)
    assert walk_configuration['scope']['environments']['Walk']['total_points'] > 0
    c5_walk = walk_configuration['metrics'][0]
    walk_rows = [
        metric_row(c5_walk, operator, environment, score=score)
        for environment in ('DriveCity', 'DriveConnectionroad', 'Walk')
        for operator, score in (('EE', 1.0), ('O2', 0.5))
    ]
    walk_views = _build_scoring_views(
        {'levels': ['Operator']}, {'scoring': walk_rows, 'configuration': walk_configuration},
    )
    assert [table['context']['environment'] for table in walk_views['score_tables']] == [
        'DriveCity', 'DriveConnectionroad', 'Walk', 'Combined',
    ]
    walk_combined = next(table for table in walk_views['score_tables'] if table['context']['environment'] == 'Combined')
    walk_c5 = next(row for row in walk_combined['rows'] if row['kpi_code'] == c5_walk['code'])
    assert walk_combined['combined_required_environments'] == ['DriveCity', 'DriveConnectionroad', 'Walk']
    assert walk_c5['max_points'] == pytest.approx(sum(
        c5_walk['contexts'][environment]['max_points']
        for environment in ('DriveCity', 'DriveConnectionroad', 'Walk')
    ))
    assert walk_c5['values']['O2']['points'] == pytest.approx(walk_c5['max_points'] * 0.5)
    assert walk_c5['values']['O2']['complete'] is True

    no_walk_views = _build_scoring_views(
        {'levels': ['Operator']},
        {'scoring': [row for row in walk_rows if row['environment'] != 'Walk'], 'configuration': walk_configuration},
    )
    assert all(table['context']['environment'] != 'Combined' for table in no_walk_views['score_tables'])
    assert any('Walk' in table['coverage_note'] and 'Combined is not shown' in table['coverage_note']
               for table in no_walk_views['score_tables'])


def test_custom_environment_names_are_preserved_and_included_in_combined_views():
    configuration = scoring_configuration()
    environments = configuration['scope']['environments']
    for name, g_level_1 in (('City', 'City'), ('Indoor', 'Indoor')):
        environments[name] = {'sheet': name, 'g_level_1': g_level_1}
        configuration['scope']['environment_mapping'][g_level_1] = name
        for metric in configuration['metrics']:
            context = copy.deepcopy(metric['contexts']['DriveCity'])
            context['max_points'] *= 0.1
            metric['contexts'][name] = context
    configuration = validate_scoring_configuration(configuration)

    metric = configuration['metrics'][0]
    environment_scores = {
        'DriveCity': 0.4,
        'DriveConnectionroad': 0.5,
        'City': 0.6,
        'Indoor': 0.8,
    }
    rows = [
        metric_row(metric, 'EE', environment, score=score)
        for environment, score in environment_scores.items()
    ]
    views = _build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'},
        {'scoring': rows, 'configuration': configuration},
    )

    tables = views['score_tables']
    assert [table['context']['environment'] for table in tables] == [
        'DriveCity', 'DriveConnectionroad', 'City', 'Indoor', 'Combined',
    ]
    city_table = next(table for table in tables if table['context']['environment'] == 'City')
    city_row = next(row for row in city_table['rows'] if row['kpi_code'] == metric['code'])
    assert city_row['max_points'] == pytest.approx(metric['contexts']['City']['max_points'])
    assert city_row['values']['EE']['points'] == pytest.approx(
        metric['contexts']['City']['max_points'] * environment_scores['City'],
    )

    combined = tables[-1]
    assert combined['combined_required_environments'] == [
        'DriveCity', 'DriveConnectionroad', 'City', 'Indoor',
    ]
    combined_row = next(row for row in combined['rows'] if row['kpi_code'] == metric['code'])
    expected_points = sum(
        metric['contexts'][environment]['max_points'] * score
        for environment, score in environment_scores.items()
    )
    expected_maximum = sum(
        metric['contexts'][environment]['max_points'] for environment in environment_scores
    )
    assert combined_row['max_points'] == pytest.approx(expected_maximum)
    assert combined_row['values']['EE']['points'] == pytest.approx(expected_points)
    assert combined_row['values']['EE']['score'] == pytest.approx(expected_points / expected_maximum)


def test_custom_environment_requires_coverage_before_combined_is_shown():
    configuration = scoring_configuration()
    environments = configuration['scope']['environments']
    environments['Indoor'] = {'sheet': 'Indoor', 'g_level_1': 'Indoor'}
    configuration['scope']['environment_mapping']['Indoor'] = 'Indoor'
    for metric in configuration['metrics']:
        context = copy.deepcopy(metric['contexts']['DriveCity'])
        context['max_points'] *= 0.1
        metric['contexts']['Indoor'] = context
    configuration = validate_scoring_configuration(configuration)
    metric = configuration['metrics'][0]
    rows = [metric_row(metric, 'EE', environment) for environment in ('DriveCity', 'DriveConnectionroad')]

    views = _build_scoring_views(
        {'levels': ['Operator']}, {'scoring': rows, 'configuration': configuration},
    )

    assert all(table['context']['environment'] != 'Combined' for table in views['score_tables'])
    assert any(
        'Indoor' in table['coverage_note'] and 'Combined is not shown' in table['coverage_note']
        for table in views['score_tables']
    )


def test_legacy_environment_alias_resolves_only_to_a_configured_canonical_environment():
    row = metric_row(METRICS[0], 'EE')
    row['environment'] = 'City'

    legacy_views = build_scoring_views({'levels': ['Operator']}, {'scoring': [row]})

    assert [table['context']['environment'] for table in legacy_views['score_tables']] == ['DriveCity']


def test_signed_gaps_use_operator_minus_reference_and_gap_tables_keep_all_comparable_rows():
    result = full_result(operators=('EE', 'O2 UK', 'Three UK'))
    table = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)['score_tables'][0]
    c5 = next(row for row in table['rows'] if row['kpi_code'] == METRICS[0]['code'])
    c6 = next(row for row in table['rows'] if row['kpi_code'] == METRICS[1]['code'])

    assert c5['gaps']['O2 UK'] < 0
    assert c5['gaps']['Three UK'] > 0
    assert c6['gaps']['Three UK'] == 0
    o2_gap = next(gap for gap in build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)['gap_tables']
                  if gap['operator'] == 'O2 UK')
    assert o2_gap['rows'][0]['kpi_code'] == METRICS[0]['code']
    assert len(o2_gap['rows']) == 32
    assert any(row['gap_points'] < 0 for row in o2_gap['rows'])
    assert any(row['gap_points'] == 0 for row in o2_gap['rows'])
    assert o2_gap['total_gap_points'] < 0
    three_gap = next(gap for gap in build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)['gap_tables']
                     if gap['operator'] == 'Three UK')
    assert len(three_gap['rows']) == 32
    assert any(row['gap_points'] > 0 for row in three_gap['rows'])
    assert any(row['gap_points'] == 0 for row in three_gap['rows'])
    assert three_gap['total_gap_points'] > 0


def test_all_vs_reference_summary_preserves_operator_order_priority_signed_gaps_and_missing_values():
    result = full_result(operators=('EE', 'O2 UK', 'Three UK', 'Vodafone UK'))
    result['scoring'] = [row for row in result['scoring']
                         if not (row['operator'] == 'O2 UK' and row['kpi_code'] == METRICS[0]['code'])]
    views = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'}, result,
        operator_mapping_groups=OPERATOR_MAPPING_GROUPS,
    )
    summary = views['gap_summary_tables'][0]
    table = views['score_tables'][0]

    assert summary['operators'] == ['Vodafone UK', 'O2 UK', 'Three UK']
    assert [row['kpi_code'] for row in summary['rows']] == [metric['code'] for metric in METRICS]
    c5_summary = next(row for row in summary['rows'] if row['kpi_code'] == METRICS[0]['code'])
    c5_matrix = next(row for row in table['rows'] if row['kpi_code'] == METRICS[0]['code'])
    assert c5_summary['gaps']['Vodafone UK'] > 0
    assert c5_summary['gaps']['Three UK'] > 0
    assert c5_summary['gaps']['O2 UK'] is None
    assert c5_summary['gap_colors']['Vodafone UK'] == c5_matrix['gap_colors']['Vodafone UK']
    assert c5_summary['gap_colors']['Three UK'] == c5_matrix['gap_colors']['Three UK']
    assert c5_summary['gap_colors']['O2 UK'] == THRESHOLD_COLORS['Unavailable']
    assert summary['total']['gaps']['O2 UK'] is None
    assert summary['total']['gaps']['Vodafone UK'] == pytest.approx(sum(
        row['gaps']['Vodafone UK'] for row in table['rows'] if row['gaps']['Vodafone UK'] is not None
    ))
    assert 'Missing comparisons are N/A.' in summary['note']


def test_operator_order_alias_matching_and_names_are_not_collapsed():
    c5 = METRICS[0]
    rows = [metric_row(c5, name) for name in ('Three UK', 'EE (UK)', 'EE', 'Other', 'O2 UK', 'Vodafone UK')]
    views = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'},
        {'scoring': rows},
        operator_mapping_groups=OPERATOR_MAPPING_GROUPS,
    )
    table = views['score_tables'][0]

    assert table['operators'] == ['Vodafone UK', 'O2 UK', 'Three UK', 'EE', 'EE (UK)', 'Other']
    assert table['baseline_operator'] == 'EE'
    assert table['rows'][0]['values']['EE']['points'] == table['rows'][0]['values']['EE (UK)']['points']
    assert {gap['operator'] for gap in views['gap_tables']} == {
        'Vodafone UK', 'O2 UK', 'Three UK', 'Other',
    }


def test_baseline_alias_snapshot_matches_raw_operator_name():
    c5 = METRICS[0]
    rows = [metric_row(c5, 'VF_UK', score=1.0), metric_row(c5, 'O2', score=0.5)]
    views = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'Vodafone UK', 'baseline_aliases': ['Vodafone UK', 'VF_UK']},
        {'scoring': rows},
        operator_mapping_groups=[
            {'canonical': 'Vodafone UK', 'aliases': ['VF_UK'], 'position': 0, 'color': '#FF0000'},
        ],
    )
    table = views['score_tables'][0]

    assert table['baseline_operator'] == 'VF_UK'
    assert table['rows'][0]['gaps']['O2'] < 0
    assert [gap['operator'] for gap in views['gap_tables']] == ['O2']


def test_unmapped_operator_names_fall_back_to_alphabetical_order():
    c5 = METRICS[0]
    rows = [metric_row(c5, name) for name in ('Zulu Mobile', 'EE', 'Alpha Mobile')]
    table = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'},
        {'scoring': rows},
    )['score_tables'][0]

    assert table['operators'] == ['Alpha Mobile', 'EE', 'Zulu Mobile']
    assert {style['position'] for style in table['operator_styles'].values()} == {0}


def test_unknown_kpi_without_environment_is_kept_as_generic_view():
    source = {'scoring': [{'campaign': 'Legacy', 'operator': 'Example', 'kpi': 'Legacy KPI',
                           'category': 'Legacy category', 'weighted_points': 2.5, 'score': 0.5,
                           'value': 7, 'max_points': 5, 'sample_count': 3}]}
    before = copy.deepcopy(source)
    views = build_scoring_views({'levels': ['Operator']}, source)

    assert len(views['score_tables']) == 1
    table = views['score_tables'][0]
    assert table['context']['environment'] == 'Unspecified'
    legacy = next(row for row in table['rows'] if row['kpi'] == 'Legacy KPI')
    assert legacy['kpi_code'] == 'LEGACY-KPI:LEGACY-KPI'
    assert legacy['values']['Example']['points'] == pytest.approx(2.5)
    assert legacy['values']['Example']['complete'] is True
    assert legacy['values']['Example']['threshold_band'] == 'Unavailable'
    assert legacy['values']['Example']['color'] == THRESHOLD_COLORS['Unavailable']
    assert source == before


def test_threshold_bands_follow_non_ultra_and_ultra_anchors():
    c5, c9 = METRICS[0], METRICS[4]
    operators = ('EE', 'Low', 'Medium', 'NearHigh', 'High', 'Ultra')
    c5_scores = {'EE': 1.0, 'Low': 0.799, 'Medium': 0.8, 'NearHigh': 0.999, 'High': 1.0, 'Ultra': 1.1}
    c9_scores = {'EE': 1.0, 'Low': 0.799, 'Medium': 0.8, 'NearHigh': 0.949, 'High': 0.95, 'Ultra': 1.0}
    rows = [metric_row(c5, operator, score=c5_scores[operator]) for operator in operators]
    rows.extend(metric_row(c9, operator, score=c9_scores[operator]) for operator in operators)
    table = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, {'scoring': rows})['score_tables'][0]

    c5_cells = next(row for row in table['rows'] if row['kpi_code'] == c5['code'])['values']
    assert [c5_cells[operator]['threshold_band'] for operator in ('Low', 'Medium', 'NearHigh', 'High', 'Ultra')] == [
        'Low', 'Medium', 'Medium', 'High', 'High',
    ]
    c9_cells = next(row for row in table['rows'] if row['kpi_code'] == c9['code'])['values']
    assert [c9_cells[operator]['threshold_band'] for operator in ('Low', 'Medium', 'NearHigh', 'High', 'Ultra')] == [
        'Low', 'Medium', 'Medium', 'High', 'UltraHigh',
    ]


def test_gap_gradient_uses_shared_context_scale_for_matrix_and_gap_rows():
    result = full_result(operators=('EE', 'O2 UK', 'Three UK'))
    views = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)
    table = views['score_tables'][0]
    c5 = next(row for row in table['rows'] if row['kpi_code'] == METRICS[0]['code'])
    o2_gap = next(gap for gap in views['gap_tables'] if gap['operator'] == 'O2 UK')
    c5_gap = next(row for row in o2_gap['rows'] if row['kpi_code'] == METRICS[0]['code'])

    assert table['gap_scale_max'] == pytest.approx(max(abs(value) for row in table['rows']
                                                       for value in row['gaps'].values() if value is not None))
    assert c5['gap_colors']['O2 UK'] == c5_gap['gap_color']
    assert c5['gap_colors']['O2 UK'] == gap_color(c5['gaps']['O2 UK'], table['gap_scale_max'])
    assert c5['gap_colors']['Three UK'] != c5['gap_colors']['O2 UK']
    assert gap_color(None, table['gap_scale_max']) == THRESHOLD_COLORS['Unavailable']
    assert gap_color(0, table['gap_scale_max']) == '#FFFFFF'
    assert gap_color(1, 2) == '#9AC57D'
    assert gap_color(2, 2) == '#70AD47'
    assert gap_color(-2, 2) == '#E57373'


def test_gap_priority_precedes_gap_magnitude_and_can_be_configured():
    configuration = scoring_configuration()
    codes = configuration['gap_priority']
    first_code, second_code = METRICS[0]['code'], METRICS[1]['code']
    configuration['gap_priority'] = [second_code, first_code, *[
        code for code in codes if code not in {first_code, second_code}
    ]]
    result = full_result(operators=('EE', 'O2 UK'))
    result['configuration'] = configuration

    views = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)
    o2_gap = next(gap for gap in views['gap_tables'] if gap['operator'] == 'O2 UK')
    summary = views['gap_summary_tables'][0]

    assert o2_gap['rows'][0]['kpi_code'] == second_code
    assert o2_gap['rows'][1]['kpi_code'] == first_code
    assert [row['kpi_code'] for row in summary['rows'][:2]] == [second_code, first_code]


def test_configured_threshold_anchors_control_score_bands_and_weights():
    configuration = scoring_configuration()
    c5 = configuration['metrics'][0]
    c5['contexts']['DriveCity']['max_points'] = 100
    c5['contexts']['DriveCity']['score_mapping'].update({
        'low_score': 0.1, 'medium_score': 0.6, 'high_score': 0.9, 'ultra_score': 1.0,
    })
    configuration = validate_scoring_configuration(configuration)
    c5 = configuration['metrics'][0]
    result = {'scoring': [metric_row(c5, 'EE', score=1.0), metric_row(c5, 'O2', score=0.9)],
              'configuration': configuration}
    table = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)['score_tables'][0]
    c5_row = next(row for row in table['rows'] if row['kpi_code'] == c5['code'])

    assert c5_row['values']['O2']['threshold_band'] == 'High'
    assert c5_row['weight_percent'] == pytest.approx(100 * 100 / configuration['scope']['total_max_points'])


def test_legacy_gap_normalization_flips_only_gap_values_and_preserves_input():
    legacy = {
        'gap': [{'gap_points': 4.5, 'baseline_points': 10, 'operator_points': 5.5}],
        'gap_totals': [{'gap_points': -2, 'baseline_points': 8, 'operator_points': 6}],
    }
    original = copy.deepcopy(legacy)

    normalized = normalize_result_gaps(legacy)

    assert normalized['gap_direction'] == 'operator_minus_reference'
    assert normalized['gap'][0]['gap_points'] == -4.5
    assert normalized['gap_totals'][0]['gap_points'] == 2
    assert normalized['gap'][0]['baseline_points'] == 10
    assert normalized['gap'][0]['operator_points'] == 5.5
    assert legacy == original


def test_scoring_views_require_a_saved_or_explicit_workspace_configuration():
    with pytest.raises(ValueError, match='no configuration snapshot'):
        _build_scoring_views({}, {'scoring': []})


def _hierarchy_contract_result():
    contexts = [
        ('North', '2026Q1', ('EE', 'O2 UK')),
        ('North', '2026Q2', ('EE', 'O2 UK')),
        ('South', '2026Q1', ('EE', 'O2 UK')),
        ('South', '2026Q2', ('O2 UK',)),
    ]
    rows = []
    for region, campaign, operators in contexts:
        for operator in operators:
            for metric_index, metric in enumerate(METRICS):
                score = .8 if operator == 'EE' else .5 + .05 * metric_index
                if region == 'South' and campaign == '2026Q1' and operator == 'O2 UK':
                    score = .6 + .03 * metric_index
                rows.append(metric_row(
                    metric, operator, region=region, campaign=campaign,
                    score=score, value=score * 100,
                ))
    return {
        'aggregation_contract_version': 2,
        'aggregation_levels': ['Operator', 'Region', 'Campaign'],
        'scoring': rows,
        'totals': [],
        'configuration': CONFIG,
    }


def _hierarchy_job(levels=None):
    return {
        'aggregation_contract_version': 2,
        'aggregation_levels': levels or ['Operator', 'Region', 'Campaign'],
        'baseline_operator': 'EE',
        'configuration': CONFIG,
    }


def test_hierarchy_views_keep_context_leaves_and_only_compare_matching_baselines():
    result = _hierarchy_contract_result()
    views = build_scoring_views(
        _hierarchy_job(), result, operator_mapping_groups=OPERATOR_MAPPING_GROUPS,
    )

    assert len(views['score_tables']) == 4
    assert len(views['hierarchy_score_tables']) == 1
    matrix = views['hierarchy_score_tables'][0]
    assert matrix['context'] == {'environment': 'DriveCity'}
    assert matrix['hierarchy_levels'] == ['Operator', 'Region', 'Campaign']
    assert len(matrix['hierarchy_columns']) == 7
    assert matrix['operators'] == [column['id'] for column in matrix['hierarchy_columns']]
    assert all(style['fullpath'] == style['label'] for style in matrix['operator_styles'].values())
    assert all(style['color'] in {'#DA291C', '#1174E6', '#000000', '#17A09F'}
               for style in matrix['operator_styles'].values())

    row = next(row for row in matrix['rows'] if row['kpi_code'] == METRICS[0]['code'])
    by_context = {
        (
            next(item['value'] for item in column['path'] if item['level'] == 'Region'),
            next(item['value'] for item in column['path'] if item['level'] == 'Campaign'),
            column['operator'],
        ): column['id']
        for column in matrix['hierarchy_columns']
    }
    north_q1_o2 = by_context[('North', '2026Q1', 'O2 UK')]
    north_q1_ee = by_context[('North', '2026Q1', 'EE')]
    assert row['gaps'][north_q1_o2] == pytest.approx(
        row['values'][north_q1_o2]['points'] - row['values'][north_q1_ee]['points']
    )
    south_q2_o2 = by_context[('South', '2026Q2', 'O2 UK')]
    assert row['gaps'][south_q2_o2] is None
    assert row['values'][south_q2_o2]['points'] is not None
    assert len(views['hierarchy_gap_tables']) == 1


def test_hierarchy_level_permutation_is_preserved_and_legacy_results_stay_separate():
    result = _hierarchy_contract_result()
    levels = ['Region', 'Campaign', 'Operator']
    views = build_scoring_views(
        _hierarchy_job(levels), result, operator_mapping_groups=OPERATOR_MAPPING_GROUPS,
    )
    matrix = views['hierarchy_score_tables'][0]
    assert matrix['hierarchy_levels'] == levels
    assert all([item['level'] for item in column['path']] == levels for column in matrix['hierarchy_columns'])
    assert matrix['hierarchy_columns'][0]['path'][0] == {'level': 'Region', 'value': 'North'}
    assert matrix['hierarchy_columns'][0]['path'][1] == {'level': 'Campaign', 'value': '2026Q1'}
    assert [column['operator'] for column in matrix['hierarchy_columns'][:2]] == ['O2 UK', 'EE']

    legacy_result = {key: value for key, value in result.items() if key != 'aggregation_contract_version'}
    legacy_result.pop('aggregation_levels')
    legacy_job = {key: value for key, value in _hierarchy_job(levels).items() if key != 'aggregation_contract_version'}
    legacy = build_scoring_views(legacy_job, legacy_result, operator_mapping_groups=OPERATOR_MAPPING_GROUPS)
    assert legacy['hierarchy_score_tables'] == []
    assert legacy['hierarchy_gap_tables'] == []
    assert len(legacy['score_tables']) == 4


def test_expanded_and_summary_rows_preserve_metric_order_and_add_category_subtotals_and_average_gaps():
    configuration = scoring_configuration()
    first_code, second_code = METRICS[0]['code'], METRICS[1]['code']
    configuration['gap_priority'] = [second_code, first_code, *[
        code for code in configuration['gap_priority'] if code not in {first_code, second_code}
    ]]
    result = full_result(operators=('EE', 'O2 UK'))
    result['configuration'] = configuration
    views = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'}, result,
    )
    table = views['score_tables'][0]
    expanded_kpis = [row for row in table['expanded_rows'] if row['row_type'] == 'kpi']
    subtotals = [row for row in table['expanded_rows'] if row['row_type'] == 'category']

    assert [row['kpi_code'] for row in expanded_kpis] == [metric['code'] for metric in configuration['metrics']]
    assert [row['category'] for row in subtotals] == [
        row['category'] for row in table['category_rows']
    ]
    assert expanded_kpis[0]['kpi_code'] == first_code
    classic_total = next(row for row in subtotals if row['category'] == 'CLASSIC CALLS')
    classic_kpis = [row for row in expanded_kpis if row['category'] == 'CLASSIC CALLS']
    assert classic_total['kpi'] == 'CLASSIC CALLS total'
    assert classic_total['kpi_code'] == ''
    assert classic_total['kpi_type'] == ''
    assert classic_total['max_points'] == pytest.approx(sum(row['max_points'] for row in classic_kpis))
    assert classic_total['weight_percent'] == pytest.approx(sum(row['weight_percent'] for row in classic_kpis))
    assert classic_total['values']['O2 UK']['points'] == pytest.approx(
        sum(row['values']['O2 UK']['points'] for row in classic_kpis)
    )
    assert classic_total['values']['O2 UK']['value'] is None
    assert classic_total['values']['O2 UK']['kpi_value'] is None
    assert classic_total['source_kind'] is None

    assert table['rows'][0]['source_kind'] == 'voice'
    kpi_gaps = [row['gaps']['O2 UK'] for row in table['rows'] if row['gaps']['O2 UK'] is not None]
    expected_mean = sum(kpi_gaps) / len(kpi_gaps)
    assert table['expanded_total']['gap_label'] == 'Average KPI GAP'
    assert table['expanded_total']['gaps']['O2 UK'] == pytest.approx(expected_mean)
    assert table['category_total']['gaps']['O2 UK'] == pytest.approx(expected_mean)
    assert table['total']['gaps']['O2 UK'] == pytest.approx(sum(kpi_gaps))
    assert table['expanded_total']['values'] == table['total']['values']

    gap_summary = views['gap_summary_tables'][0]
    classic_gap_total = next(row for row in gap_summary['category_rows'] if row['category'] == 'CLASSIC CALLS')
    classic_gaps = [row['gaps']['O2 UK'] for row in gap_summary['rows']
                    if row['category'] == 'CLASSIC CALLS' and row['gaps']['O2 UK'] is not None]
    assert classic_gap_total['gaps']['O2 UK'] == pytest.approx(sum(classic_gaps) / len(classic_gaps))
    assert gap_summary['category_total']['gaps']['O2 UK'] == pytest.approx(expected_mean)
    assert [row['row_type'] for row in gap_summary['category_rows']] == ['category'] * len(subtotals)


def test_scoring_rows_follow_configuration_order_while_gap_rows_follow_gap_priority():
    configuration = scoring_configuration()
    configured_codes = [metric['code'] for metric in configuration['metrics']]
    configuration['metrics'] = list(reversed(configuration['metrics']))
    result = full_result(operators=('EE', 'O2 UK'))
    result['configuration'] = configuration

    views = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)
    score_table = views['score_tables'][0]
    gap_table = next(table for table in views['gap_tables'] if table['operator'] == 'O2 UK')
    summary_table = views['gap_summary_tables'][0]

    assert [row['kpi_code'] for row in score_table['rows']] == list(reversed(configured_codes))
    assert [row['kpi_code'] for row in score_table['expanded_rows'] if row['row_type'] == 'kpi'] == list(reversed(configured_codes))
    assert [row['category'] for row in score_table['category_rows']] == list(dict.fromkeys(
        metric['category'] for metric in configuration['metrics']
    ))
    assert [row['kpi_code'] for row in gap_table['rows']] == configuration['gap_priority']
    assert [row['kpi_code'] for row in summary_table['rows']] == configuration['gap_priority']


def test_category_gap_is_unavailable_when_all_kpi_comparisons_are_missing():
    result = full_result(operators=('EE', 'O2 UK'))
    result['scoring'] = [
        row for row in result['scoring']
        if not (row['operator'] == 'O2 UK' and row['category'] == 'CLASSIC CALLS')
    ]
    views = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'}, result,
    )
    score_table = views['score_tables'][0]
    classic_total = next(row for row in score_table['category_rows'] if row['category'] == 'CLASSIC CALLS')
    assert classic_total['gaps']['O2 UK'] is None
    assert classic_total['gap_colors']['O2 UK'] == THRESHOLD_COLORS['Unavailable']
    assert classic_total['values']['O2 UK']['points'] is None
    assert classic_total['values']['O2 UK']['complete'] is False
    individual_gap = next(table for table in views['gap_tables'] if table['operator'] == 'O2 UK')
    classic_rows = [row for row in individual_gap['expanded_rows'] if row['category'] == 'CLASSIC CALLS']
    classic_kpi_rows = [row for row in classic_rows if row['row_type'] == 'kpi']
    classic_gap_total = next(row for row in classic_rows if row['row_type'] == 'category')
    assert classic_kpi_rows and all(row['gap_points'] is None for row in classic_kpi_rows)
    assert classic_gap_total['gap_points'] is None
    assert classic_gap_total['gap_color'] == THRESHOLD_COLORS['Unavailable']


def test_hierarchy_matrices_expose_the_same_expanded_and_summary_contract():
    views = build_scoring_views(
        _hierarchy_job(), _hierarchy_contract_result(), operator_mapping_groups=OPERATOR_MAPPING_GROUPS,
    )
    score_matrix = views['hierarchy_score_tables'][0]
    gap_matrix = views['hierarchy_gap_tables'][0]

    assert len(score_matrix['category_rows']) < len(score_matrix['rows'])
    assert all(row['row_type'] == 'category' for row in score_matrix['category_rows'])
    assert all(row['row_type'] == 'category' for row in gap_matrix['category_rows'])
    assert score_matrix['expanded_total']['gap_label'] == 'Average KPI GAP'
    assert gap_matrix['expanded_total']['gap_label'] == 'Average KPI GAP'
