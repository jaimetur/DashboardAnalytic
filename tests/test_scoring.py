"""Golden workbook mapping and raw CDR scoring regression fixtures."""

from copy import deepcopy

import pandas as pd
import pytest

from src.modules.scoring import calculate_scoring as _calculate_scoring, interpolate_score, required_input_columns
from tests.scoring_fixtures import load_initial_scoring_configuration, scoring_configuration

CONFIG = load_initial_scoring_configuration()
_GOLDEN_KPI_CODES = (
    'K1', 'K2', 'K3', 'K4', 'K5', 'K6', 'K7', 'K8', 'K9', 'K10', 'K11',
    'K12', 'K13', 'K14', 'K15', 'K16', 'K17', 'K18', 'K19', 'K20', 'K21',
    'K22', 'K23', 'K24', 'K25', 'K26', 'K27', 'K28', 'K29', 'K30', 'K31', 'K32',
)
_GOLDEN_WEIGHTS = {
    'DriveCity': (
        73.4825, 8.645000000000001, 4.322500000000001, 22.75, 7.585500000000001,
        15.164499999999999, 56.875, 14.7875, 4.9270000000000005, 9.8605, 9.1,
        30.419999999999998, 20.28, 15.209999999999999, 10.14, 20.28, 25.35,
        25.35, 15.209999999999999, 15.209999999999999, 10.14, 12.675, 12.675,
        7.6049999999999995, 7.6049999999999995, 33.800000000000004, 50.7,
        54.080000000000005, 3.3800000000000003, 27.040000000000003, 5.07, 20.28,
    ),
    'DriveConnectionroad': (
        39.567499999999995, 4.655, 2.3275, 12.25, 4.084499999999999, 8.1655,
        30.624999999999996, 7.9624999999999995, 2.653, 5.3095, 4.8999999999999995,
        16.38, 10.92, 8.19, 5.46, 10.92, 13.649999999999999, 13.649999999999999,
        8.19, 8.19, 5.46, 6.824999999999999, 6.824999999999999, 4.095, 4.095,
        18.2, 27.299999999999997, 29.119999999999997, 1.8199999999999998,
        14.559999999999999, 2.73, 10.92,
    ),
}


def calculate_scoring(datasets, *args, configuration=None, **kwargs):
    """Keep test calculations independent from workspace runtime state."""
    if configuration is None:
        configuration = load_initial_scoring_configuration()
    return _calculate_scoring(datasets, *args, configuration=configuration, **kwargs)


def frame(rows, operator='EE', environment='City', campaign='2026Q2'):
    return pd.DataFrame([{'Operator': operator, 'Campaign': campaign, 'G_Level_1': 'Drive',
                          'G_Level_2': environment, **row} for row in rows])


def metric(result, code, operator='EE', environment='DriveCity', campaign=None):
    return next(row for row in result['scoring'] if row['kpi_code'] == code and row['operator'] == operator
                and row['environment'] == environment and row['campaign'] == campaign)


def test_workbook_cached_golden_score():
    sample = CONFIG['validation_examples']['mapping_workbook_sample']
    mapping = CONFIG['metrics'][0]['contexts'][sample['environment']]
    score = interpolate_score(sample['measured_value'], mapping['thresholds'])
    assert score == pytest.approx(sample['expected_score'])
    assert score * mapping['max_points'] == pytest.approx(sample['expected_weighted_points'])
    assert sum(m['contexts']['DriveCity']['max_points'] for m in CONFIG['metrics']) == pytest.approx(650)
    assert sum(m['contexts']['DriveConnectionroad']['max_points'] for m in CONFIG['metrics']) == pytest.approx(350)


def test_netcheck_2026_kpi_weights_match_independent_original_workbook_goldens():
    assert tuple(metric['code'] for metric in CONFIG['metrics']) == _GOLDEN_KPI_CODES
    for environment, expected in _GOLDEN_WEIGHTS.items():
        actual = tuple(metric['contexts'][environment]['max_points'] for metric in CONFIG['metrics'])
        assert actual == pytest.approx(expected, rel=0, abs=1e-12)
        assert sum(actual) == pytest.approx(650 if environment == 'DriveCity' else 350, abs=1e-12)
    assert CONFIG['scope']['environments']['Walk']['total_points'] == 0
    assert all(metric['contexts']['Walk']['max_points'] == 0 for metric in CONFIG['metrics'])


@pytest.mark.parametrize(
    'sample',
    CONFIG['validation_examples']['mapping_workbook_samples'],
    ids=lambda sample: f"{sample['kpi_code']}-{sample['environment']}",
)
def test_mapping_workbook_samples_match_interpolated_scores(sample):
    metric_config = next(metric for metric in CONFIG['metrics'] if metric['code'] == sample['kpi_code'])
    context = metric_config['contexts'][sample['environment']]

    expected_thresholds = deepcopy(sample['thresholds'])
    if isinstance(expected_thresholds.get('ultra'), dict):
        expected_thresholds['ultra'].pop('source_formula', None)
    assert expected_thresholds == context['thresholds']
    assert sample['max_points'] == pytest.approx(context['max_points'])
    score = interpolate_score(
        sample['measured_value'], context['thresholds'], sample['dynamic_ultra_threshold'],
        context.get('score_mapping'),
    )

    assert score == pytest.approx(sample['expected_score_fraction'])
    assert score * sample['max_points'] == pytest.approx(sample['expected_weighted_points'])


def test_interpolation_anchors_clamping_and_dynamic_ultra():
    higher = {'low': 0, 'medium': 10, 'high': 20, 'ultra': {'rule': 'best_max'}}
    assert [interpolate_score(x, higher, 40) for x in [-1, 0, 10, 20, 30, 40, 50]] == pytest.approx([0, 0, .8, .95, .975, 1, 1])
    lower = {'low': 10, 'medium': 3, 'high': 1.5, 'ultra': None}
    assert [interpolate_score(x, lower) for x in [20, 10, 3, 1.5, 0]] == pytest.approx([0, 0, .8, 1, 1])
    assert interpolate_score(15, higher, 15) == pytest.approx(.875)


@pytest.mark.parametrize('kpi_code', ['K20', 'K25'])
@pytest.mark.parametrize('environment', ['DriveCity', 'DriveConnectionroad'])
def test_workbook_c25_c30_high_and_midpoint_ultra_anchors(kpi_code, environment):
    context = next(item for item in CONFIG['metrics'] if item['code'] == kpi_code)['contexts'][environment]
    thresholds = context['thresholds']
    anchors = context['score_mapping']
    high = thresholds['high']
    ultra = high + 200

    assert anchors == {'low_score': 0.0, 'medium_score': 0.8, 'high_score': 0.9, 'ultra_score': 1.0}
    assert interpolate_score(high, thresholds, ultra, anchors) == pytest.approx(0.9)
    assert interpolate_score((high + ultra) / 2, thresholds, ultra, anchors) == pytest.approx(0.95)


def test_c31_keeps_workbook_95_percent_high_anchor():
    context = next(item for item in CONFIG['metrics'] if item['code'] == 'K26')['contexts']['DriveCity']
    thresholds = context['thresholds']

    assert context['score_mapping']['high_score'] == 0.95
    assert interpolate_score(thresholds['high'], thresholds, 1000, context['score_mapping']) == pytest.approx(0.95)
    assert interpolate_score((thresholds['high'] + 1000) / 2, thresholds, 1000,
                             context['score_mapping']) == pytest.approx(0.975)


def test_voice_and_speech_denominators_filters_and_boundary():
    voice = frame([
        {'Session_Type': 'CALL', 'Call_Status': 'Completed', 'Call_Setup_Time': 2, 'Disturbed_and_Impaired_Call': 'Yes'},
        {'Session_Type': 'CALL', 'Call_Status': 'Dropped', 'Call_Setup_Time': 12},
        {'Session_Type': 'CALL', 'Call_Status': 'Failed', 'Call_Setup_Time': 100},
        {'Session_Type': 'MultiRAB CALL', 'Call_Status': 'Completed', 'Test_Status': 'Successful'},
        {'Session_Type': 'WhatsApp CALL', 'Call_Status': 'Completed', 'Call_Setup_Time': 30},
    ])
    speech = frame([{'Session_Type': 'CALL', 'LQ': 1.6}, {'Session_Type': 'CALL', 'LQ': 4.4},
                    {'Session_Type': 'CALL', 'LQ': None}, {'Session_Type': 'WhatsApp CALL', 'LQ': 4.7}])
    result = calculate_scoring({'voice': voice, 'speech': speech}, ['Operator'])
    assert metric(result, 'K1')['value'] == 50
    assert metric(result, 'K2')['value'] == 7
    assert metric(result, 'K3')['value'] == pytest.approx(100 / 3)
    assert metric(result, 'K6')['value'] == 25
    assert metric(result, 'K11')['value'] == 100
    assert metric(result, 'K4')['value'] == pytest.approx(100 / 3)
    assert metric(result, 'K5')['value'] == 3
    assert metric(result, 'K9')['score'] == 1


def test_data_raw_kpis_and_units():
    data = frame([
        {'Test_Name': 'FDFS DL', 'Test_Result': 'Completed', 'Transfer_Duration': 2},
        {'Test_Name': 'FDFS DL', 'Test_Result': 'Failed', 'Transfer_Duration': 20},
        {'Test_Name': 'FDFS UL', 'Test_Result': 'Completed', 'Transfer_Duration': 3},
        {'Test_Name': 'FDTT DL', 'Test_Result': 'Completed', 'Mean_Data_Rate': 2},
        {'Test_Name': 'FDTT DL', 'Test_Result': 'Completed', 'Mean_Data_Rate': 200},
        {'Test_Name': 'FDTT DL', 'Test_Result': 'Failed', 'Mean_Data_Rate': 9000},
        {'Test_Name': 'UDP UL', 'Test_Result': 'Completed', 'Mean_Data_Rate': 20},
        {'Type_of_Test': 'httpBrowser', 'Test_Result': 'Completed', 'http_Browser_Transferred_Bytes': 1000000, 'http_Browser_1MB_Reached_Duration': 1500},
        {'Type_of_Test': 'httpBrowser', 'Test_Result': 'Failed', 'http_Browser_Transferred_Bytes': 10, 'http_Browser_1MB_Reached_Duration': 9000},
        {'Type_of_Test': 'VideoStreaming', 'Test_Result': 'Completed', 'VideoStream_Time_to_First_Picture': 10, 'Irritating_Video_Playout': 'No'},
        {'Type_of_Test': 'VideoStreaming', 'Test_Result': 'Failed', 'VideoStream_Time_to_First_Picture': 9},
        {'Type_of_Test': 'Interactivity', 'Packets_Lost': 1, 'Packets_Discarded': 2, 'Packets_Corrupted': 1.9,
         'Packets_Not_Sent': 1, 'Packets_Sent': 100, 'Interactivity_RTT_Median': 20},
        {'Type_of_Test': 'Interactivity', 'Packets_Sent': 100, 'Interactivity_RTT_Median': 40},
    ])
    result = calculate_scoring({'data': data}, ['Operator'])
    expected = {'K12': 50, 'K13': 2, 'K14': 100, 'K15': 3, 'K16': 50, 'K19': 50,
                'K20': 180.2, 'K21': 100, 'K24': 0, 'K25': 20, 'K26': 1500, 'K27': 50,
                'K28': 50, 'K29': 50, 'K30': 50, 'K31': 2.5, 'K32': 30}
    for code, value in expected.items():
        assert metric(result, code)['value'] == pytest.approx(value), code


def test_campaign_environment_aliases_and_missing_coverage():
    first = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}])
    second = frame([{'Session_Type': 'CALL', 'Call_Status': 'Failed'}], campaign='2026Q3')
    invalid = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}], environment='Unknown')
    data = pd.concat([first, second, invalid], ignore_index=True).rename(columns={'Operator': 'operator', 'G_Level_1': 'g level 1', 'G_Level_2': 'g-level-2'})
    data['Region'] = 'City'
    result = calculate_scoring({'voice': data}, ['Operator', 'Campaign'])
    assert metric(result, 'K1', campaign='2026Q2')['value'] == 100
    assert metric(result, 'K1', campaign='2026Q3')['value'] == 0
    assert len([r for r in result['scoring'] if r['kpi_code'] == 'K1']) == 2
    assert all(not row['complete_coverage'] and row['score'] is None for row in result['totals'])
    assert next(row for row in result['totals'] if row['environment'] == 'Combined' and row['category'] == 'Overall')['max_points'] == pytest.approx(1000)
    assert any('excluded' in warning for warning in result['warnings'])
    missing = calculate_scoring({'voice': first.drop(columns='G_Level_2')}, ['Operator'])
    assert missing['scoring'] == []
    assert any('G_Level_2' in warning for warning in missing['warnings'])


def test_custom_environment_matches_explicit_g1_and_contributes_to_combined_totals():
    configuration = deepcopy(CONFIG)
    configuration['scope']['environments']['Indoor'] = {'source_filters': {'G_Level_1': 'Indoor'}}
    for item in configuration['metrics']:
        city = item['contexts']['DriveCity']
        indoor = deepcopy(city)
        indoor['max_points'] = city['weight_share'] * 100
        item['contexts']['Indoor'] = indoor
    source = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}])
    source['G_Level_1'] = 'Indoor'
    source['G_Level_2'] = 'Any subdivision'

    result = calculate_scoring({'voice': source}, ['Operator'], configuration=configuration)
    indoor_success = metric(result, 'K1', environment='Indoor')
    combined = next(
        row for row in result['totals']
        if row['environment'] == 'Combined' and row['category'] == 'Overall' and row['operator'] == 'EE'
    )

    assert indoor_success['value'] == 100
    assert indoor_success['max_points'] > 0
    assert combined['max_points'] == pytest.approx(1100)


def test_best_operator_ultra_and_gap_are_per_campaign_and_group():
    frames = []
    for operator, rate in [('EE', 1000), ('Other', 700)]:
        frames.append(frame([{'Test_Name': 'FDTT DL', 'Test_Result': 'Completed', 'Mean_Data_Rate': rate}], operator=operator))
    frames.append(frame([{'Test_Name': 'FDTT DL', 'Test_Result': 'Completed', 'Mean_Data_Rate': 2000}], operator='Other', campaign='Other campaign'))
    result = calculate_scoring({'data': pd.concat(frames)}, ['Operator', 'Campaign'])
    assert metric(result, 'K20', campaign='2026Q2')['score'] == 1
    c25_context = next(m for m in CONFIG['metrics'] if m['code'] == 'K20')['contexts']['DriveCity']
    expected = interpolate_score(700, c25_context['thresholds'], 1000, c25_context['score_mapping'])
    assert metric(result, 'K20', operator='Other', campaign='2026Q2')['score'] == pytest.approx(expected)
    gap = next(row for row in result['gap'] if row['kpi_code'] == 'K20')
    assert gap['gap_points'] == pytest.approx(gap['operator_points'] - gap['baseline_points'])
    assert gap['gap_points'] < 0
    assert any('Baseline EE' in warning for warning in result['warnings'])
    assert all(row['campaign'] == '2026Q2' for row in result['gap'])


def test_campaign_is_optional_and_defaults_to_pooled_raw_rows():
    source = pd.concat([
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}], campaign='2026Q2'),
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Failed'}], campaign='2026Q3'),
    ], ignore_index=True)

    pooled = calculate_scoring({'voice': source}, ['Operator'])
    separated = calculate_scoring({'voice': source}, ['Operator', 'Campaign'])

    pooled_rows = [row for row in pooled['scoring'] if row['kpi_code'] == 'K1']
    separated_rows = [row for row in separated['scoring'] if row['kpi_code'] == 'K1']
    assert len(pooled_rows) == 1
    assert pooled_rows[0]['campaign'] is None
    assert pooled_rows[0]['value'] == 50
    assert pooled['aggregation_levels'] == ['Operator']
    assert pooled['aggregation_contract_version'] == 2
    assert pooled['campaigns'] == ['2026Q2', '2026Q3']
    assert {row['campaign']: row['value'] for row in separated_rows} == {'2026Q2': 100, '2026Q3': 0}
    assert separated['aggregation_levels'] == ['Operator', 'Campaign']
    assert 'Campaigns are scored separately; the supplied Tableau Prep flow pools campaigns.' not in separated['warnings']
    global_pooled = next(row for row in pooled['global_kpis'] if row['kpi_code'] == 'K1')
    global_separated = {row['campaign']: row['value'] for row in separated['global_kpis'] if row['kpi_code'] == 'K1'}
    assert global_pooled['environment'] == 'All Environments'
    assert global_pooled['campaign'] is None
    assert global_pooled['value'] == 50
    assert global_separated == {'2026Q2': 100, '2026Q3': 0}


def test_global_kpis_recalculate_ratios_and_medians_over_pooled_source_rows():
    configuration = scoring_configuration()
    k2 = next(metric for metric in configuration['metrics'] if metric['code'] == 'K2')
    k2['calculation']['formula'] = 'MEDIAN(Call_Setup_Time)'
    source = pd.concat([
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed', 'Call_Setup_Time': 2}]),
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Dropped', 'Call_Setup_Time': 100}], environment='Connectionroad'),
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Dropped', 'Call_Setup_Time': 10}], environment='Connectionroad'),
    ], ignore_index=True)

    result = calculate_scoring({'voice': source}, configuration=configuration)
    global_rows = {row['kpi_code']: row for row in result['global_kpis']}

    assert global_rows['K1']['value'] == pytest.approx(100 / 3)
    assert global_rows['K2']['value'] == pytest.approx(10)
    assert global_rows['K1']['sample_count'] == 3
    assert all(row['environment'] != 'All Environments' for row in result['scoring'] + result['totals'])
    overall = {row['environment']: row for row in result['totals'] if row['category'] == 'Overall'}
    assert overall['Combined']['weighted_points'] == pytest.approx(
        overall['DriveCity']['weighted_points'] + overall['DriveConnectionroad']['weighted_points']
    )


def test_k31_ifnull_packet_component_can_be_absent_but_sent_denominator_is_required():
    source = frame([{
        'Type_of_Test': 'Interactivity',
        'Packets_Lost': 1,
        'Packets_Discarded': 2,
        'Packets_Not_Sent': 3,
        'Packets_Sent': 100,
    }])

    result = calculate_scoring({'data': source})
    row = metric(result, 'K31')

    assert row['value'] == pytest.approx(6)
    assert row['sample_count'] == 1
    assert row['score'] is not None
    assert not any('K31 requires missing column Packets_Corrupted' in warning for warning in result['warnings'])

    missing_denominator = source.drop(columns='Packets_Sent')
    unavailable = calculate_scoring({'data': missing_denominator})
    assert metric(unavailable, 'K31')['value'] is None
    assert 'Data: K31 requires missing column Packets_Sent.' in unavailable['warnings']


def test_operator_mapping_aliases_are_canonicalized_before_kpi_aggregation():
    source = pd.concat([
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}], operator='VF_UK'),
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Failed'}], operator='Vodafone UK'),
    ], ignore_index=True)

    result = calculate_scoring(
        {'voice': source}, ['Operator'],
        operator_mappings={'vf_uk': 'Vodafone UK', 'vodafone uk': 'Vodafone UK'},
    )
    rows = [row for row in result['scoring'] if row['kpi_code'] == 'K1']

    assert len(rows) == 1
    assert rows[0]['operator'] == 'Vodafone UK'
    assert rows[0]['value'] == 50


def test_dimension_grouping_and_required_projection():
    source = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed', 'Region': 'North', 'City': 'A', 'Vendor': 'V'},
                    {'Session_Type': 'CALL', 'Call_Status': 'Failed', 'Region': 'South', 'City': 'B', 'Vendor': 'W'}])
    result = calculate_scoring({'voice': source}, ['Region', 'City', 'Vendor', 'Dataset Type'])
    rows = [row for row in result['scoring'] if row['kpi_code'] == 'K1']
    assert len(rows) == 2
    assert {row['value'] for row in rows} == {0, 100}
    assert all(row['operator'] == 'EE' and row['dataset_type'] == 'Voice' for row in rows)
    columns = required_input_columns('voice', ['Dataset Type', 'Region'])
    assert {'Operator', 'Campaign', 'G_Level_1', 'G_Level_2', 'Dataset_Kind', 'Region'} <= set(columns)


def test_empty_denominators_do_not_fabricate_scores():
    result = calculate_scoring({'data': frame([{'Type_of_Test': 'Interactivity', 'Packets_Sent': 0,
                                              'Packets_Lost': 1, 'Packets_Discarded': None,
                                              'Packets_Corrupted': None, 'Packets_Not_Sent': None}])})
    assert metric(result, 'K31')['score'] is None
    assert metric(result, 'K31')['weighted_points'] is None


def test_baseline_alias_category_totals_and_incomplete_gap_totals():
    source = pd.concat([frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}], operator='EE (UK)'),
                        frame([{'Session_Type': 'CALL', 'Call_Status': 'Failed'}], operator='Other')])
    result = calculate_scoring({'voice': source})
    gap = next(row for row in result['gap'] if row['kpi_code'] == 'K1')
    assert gap['baseline_actual_operator'] == 'EE (UK)'
    assert gap['gap_points'] < 0
    assert {'Overall', 'CLASSIC CALLS', 'TRANSFER'} <= {row['category'] for row in result['totals']}
    assert all(row['gap_points'] is None and not row['complete_coverage'] for row in result['gap_totals'])
    overall = next(row for row in result['totals'] if row['category'] == 'Overall' and row['environment'] == 'DriveCity' and row['operator'] == 'EE (UK)')
    categories = [row for row in result['totals'] if row['category'] != 'Overall' and row['environment'] == 'DriveCity' and row['operator'] == 'EE (UK)']
    assert overall['weighted_points'] == pytest.approx(sum(row['weighted_points'] for row in categories))


def test_baseline_mapping_aliases_are_resolved_and_gap_sign_is_operator_minus_reference():
    source = pd.concat([
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}], operator='VF_UK'),
        frame([{'Session_Type': 'CALL', 'Call_Status': 'Failed'}], operator='Other'),
    ])

    result = calculate_scoring(
        {'voice': source}, baseline_operator='Vodafone UK', baseline_aliases=['VF_UK', 'VF UK'],
    )
    c5_gap = next(row for row in result['gap'] if row['kpi_code'] == 'K1')

    assert c5_gap['baseline_actual_operator'] == 'VF_UK'
    assert c5_gap['gap_points'] == pytest.approx(c5_gap['operator_points'] - c5_gap['baseline_points'])
    assert c5_gap['gap_points'] < 0
    assert result['gap_direction'] == 'operator_minus_reference'


def test_zero_weight_metrics_remain_visible_but_do_not_block_total_coverage():
    configuration = scoring_configuration()
    for metric_configuration in configuration['metrics']:
        for context in metric_configuration['contexts'].values():
            context['max_points'] = 0
    c17 = next(item for item in configuration['metrics'] if item['code'] == 'K12')
    c17['contexts']['DriveCity']['max_points'] = 100
    c17['contexts']['DriveConnectionroad']['max_points'] = 100
    data = pd.concat([
        frame([{'Test_Name': 'FDFS DL', 'Test_Result': 'Completed'}], environment='City'),
        frame([{'Test_Name': 'FDFS DL', 'Test_Result': 'Completed'}], environment='Connectionroad'),
    ])

    result = calculate_scoring({'data': data}, configuration=configuration)
    overall = {row['environment']: row for row in result['totals'] if row['category'] == 'Overall'}

    assert overall['DriveCity']['complete_coverage'] is True
    assert overall['DriveCity']['max_points'] == 100
    assert overall['DriveConnectionroad']['complete_coverage'] is True
    assert overall['Combined']['complete_coverage'] is True
    assert overall['Combined']['max_points'] == 200


def test_global_raw_kpi_keeps_zero_weight_environment_coverage_separate():
    configuration = scoring_configuration()
    for metric_configuration in configuration['metrics']:
        metric_configuration['contexts']['DriveConnectionroad']['max_points'] = 0
    source = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}])

    result = calculate_scoring({'voice': source}, configuration=configuration)
    global_k1 = next(row for row in result['global_kpis'] if row['kpi_code'] == 'K1')

    assert global_k1['value'] == 100
    assert global_k1['sample_count'] == 1
    assert global_k1['complete_coverage'] is False
    assert global_k1['missing_environments'] == ['DriveConnectionroad', 'Walk']


def test_complete_city_road_coverage_combines_fixed_weights():
    frames = {}
    data_rows = [
        {'Test_Name': 'FDFS DL', 'Test_Result': 'Completed', 'Transfer_Duration': 1},
        {'Test_Name': 'FDFS UL', 'Test_Result': 'Completed', 'Transfer_Duration': 1},
        {'Test_Name': 'FDTT DL', 'Test_Result': 'Completed', 'Mean_Data_Rate': 1000},
        {'Test_Name': 'UDP UL', 'Test_Result': 'Completed', 'Mean_Data_Rate': 100},
        {'Type_of_Test': 'httpBrowser', 'Test_Result': 'Completed', 'http_Browser_Transferred_Bytes': 1000000, 'http_Browser_1MB_Reached_Duration': 100},
        {'Type_of_Test': 'VideoStreaming', 'Test_Result': 'Completed', 'VideoStream_Time_to_First_Picture': 1, 'Irritating_Video_Playout': None},
        {'Type_of_Test': 'Interactivity', 'Packets_Lost': 0, 'Packets_Discarded': 0, 'Packets_Corrupted': 0,
         'Packets_Not_Sent': 0, 'Packets_Sent': 100, 'Interactivity_RTT_Median': 1},
    ]
    voice_rows = [{'Session_Type': session, 'Call_Status': 'Completed', 'Call_Setup_Time': 1,
                   'Disturbed_and_Impaired_Call': 'No', 'Test_Status': 'Successful'}
                  for session in ['CALL', 'MultiRAB CALL', 'WhatsApp CALL']]
    speech_rows = [{'Session_Type': session, 'LQ': 4.7} for session in ['CALL', 'WhatsApp CALL']]
    for kind, rows in [('data', data_rows), ('voice', voice_rows), ('speech', speech_rows)]:
        frames[kind] = pd.concat([frame(rows), frame(rows, environment='Connectionroad')], ignore_index=True)
    result = calculate_scoring(frames)
    overall = {row['environment']: row for row in result['totals'] if row['category'] == 'Overall'}
    assert len(result['scoring']) == 64
    assert all(row['complete_coverage'] for row in overall.values())
    assert overall['DriveCity']['max_points'] == pytest.approx(650)
    assert overall['DriveConnectionroad']['max_points'] == pytest.approx(350)
    assert overall['Combined']['weighted_points'] == pytest.approx(overall['DriveCity']['weighted_points'] + overall['DriveConnectionroad']['weighted_points'])
    assert overall['Combined']['score'] == pytest.approx(overall['Combined']['weighted_points'] / 1000)
