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
    c5 = next(metric for metric in METRICS if metric['code'] == 'C5')
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
    c5_row = next(row for row in combined['rows'] if row['kpi_code'] == 'C5')
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
    road_c5 = next(row for row in road['rows'] if row['kpi_code'] == 'C5')
    assert road_c5['values']['O2']['points'] is None
    assert road_c5['values']['O2']['complete'] is False

    city_only = build_scoring_views({'levels': ['Operator']}, {'scoring': [rows[0]], 'totals': result['totals']})
    assert [table['context']['environment'] for table in city_only['score_tables']] == ['DriveCity']
    assert 'Combined is not shown' in city_only['score_tables'][0]['coverage_note']


def test_signed_gaps_use_operator_minus_reference_and_gap_tables_keep_all_comparable_rows():
    result = full_result(operators=('EE', 'O2 UK', 'Three UK'))
    table = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)['score_tables'][0]
    c5 = next(row for row in table['rows'] if row['kpi_code'] == 'C5')
    c6 = next(row for row in table['rows'] if row['kpi_code'] == 'C6')

    assert c5['gaps']['O2 UK'] < 0
    assert c5['gaps']['Three UK'] > 0
    assert c6['gaps']['Three UK'] == 0
    o2_gap = next(gap for gap in build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)['gap_tables']
                  if gap['operator'] == 'O2 UK')
    assert o2_gap['rows'][0]['kpi_code'] == 'C5'
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
                         if not (row['operator'] == 'O2 UK' and row['kpi_code'] == 'C5')]
    views = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'}, result,
        operator_mapping_groups=OPERATOR_MAPPING_GROUPS,
    )
    summary = views['gap_summary_tables'][0]
    table = views['score_tables'][0]

    assert summary['operators'] == ['Vodafone UK', 'O2 UK', 'Three UK']
    assert [row['kpi_code'] for row in summary['rows']] == [metric['code'] for metric in METRICS]
    c5_summary = next(row for row in summary['rows'] if row['kpi_code'] == 'C5')
    c5_matrix = next(row for row in table['rows'] if row['kpi_code'] == 'C5')
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
    c5 = next(metric for metric in METRICS if metric['code'] == 'C5')
    c9 = next(metric for metric in METRICS if metric['code'] == 'C9')
    operators = ('EE', 'Low', 'Medium', 'NearHigh', 'High', 'Ultra')
    c5_scores = {'EE': 1.0, 'Low': 0.799, 'Medium': 0.8, 'NearHigh': 0.999, 'High': 1.0, 'Ultra': 1.1}
    c9_scores = {'EE': 1.0, 'Low': 0.799, 'Medium': 0.8, 'NearHigh': 0.949, 'High': 0.95, 'Ultra': 1.0}
    rows = [metric_row(c5, operator, score=c5_scores[operator]) for operator in operators]
    rows.extend(metric_row(c9, operator, score=c9_scores[operator]) for operator in operators)
    table = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, {'scoring': rows})['score_tables'][0]

    c5_cells = next(row for row in table['rows'] if row['kpi_code'] == 'C5')['values']
    assert [c5_cells[operator]['threshold_band'] for operator in ('Low', 'Medium', 'NearHigh', 'High', 'Ultra')] == [
        'Low', 'Medium', 'Medium', 'High', 'High',
    ]
    c9_cells = next(row for row in table['rows'] if row['kpi_code'] == 'C9')['values']
    assert [c9_cells[operator]['threshold_band'] for operator in ('Low', 'Medium', 'NearHigh', 'High', 'Ultra')] == [
        'Low', 'Medium', 'Medium', 'High', 'UltraHigh',
    ]


def test_gap_gradient_uses_shared_context_scale_for_matrix_and_gap_rows():
    result = full_result(operators=('EE', 'O2 UK', 'Three UK'))
    views = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)
    table = views['score_tables'][0]
    c5 = next(row for row in table['rows'] if row['kpi_code'] == 'C5')
    o2_gap = next(gap for gap in views['gap_tables'] if gap['operator'] == 'O2 UK')
    c5_gap = next(row for row in o2_gap['rows'] if row['kpi_code'] == 'C5')

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
    configuration['gap_priority'] = ['C6', 'C5', *[code for code in codes if code not in {'C5', 'C6'}]]
    result = full_result(operators=('EE', 'O2 UK'))
    result['configuration'] = configuration

    views = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)
    o2_gap = next(gap for gap in views['gap_tables'] if gap['operator'] == 'O2 UK')
    summary = views['gap_summary_tables'][0]

    assert o2_gap['rows'][0]['kpi_code'] == 'C6'
    assert o2_gap['rows'][1]['kpi_code'] == 'C5'
    assert [row['kpi_code'] for row in summary['rows'][:2]] == ['C6', 'C5']


def test_configured_threshold_anchors_control_score_bands_and_weights():
    configuration = scoring_configuration()
    c5 = next(metric for metric in configuration['metrics'] if metric['code'] == 'C5')
    c5['contexts']['DriveCity']['max_points'] = 100
    c5['contexts']['DriveCity']['score_mapping'].update({
        'low_score': 0.1, 'medium_score': 0.6, 'high_score': 0.9, 'ultra_score': 1.0,
    })
    configuration = validate_scoring_configuration(configuration)
    c5 = next(metric for metric in configuration['metrics'] if metric['code'] == 'C5')
    result = {'scoring': [metric_row(c5, 'EE', score=1.0), metric_row(c5, 'O2', score=0.9)],
              'configuration': configuration}
    table = build_scoring_views({'levels': ['Operator'], 'baseline_operator': 'EE'}, result)['score_tables'][0]
    c5_row = next(row for row in table['rows'] if row['kpi_code'] == 'C5')

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

    row = next(row for row in matrix['rows'] if row['kpi_code'] == 'C5')
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
