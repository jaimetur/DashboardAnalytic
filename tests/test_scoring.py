"""Golden workbook mapping and raw CDR scoring regression fixtures."""

import pandas as pd
import pytest

from src.modules.scoring import calculate_scoring as _calculate_scoring, interpolate_score, required_input_columns
from tests.scoring_fixtures import load_initial_scoring_configuration, scoring_configuration

CONFIG = load_initial_scoring_configuration()


def calculate_scoring(datasets, *args, configuration=None, **kwargs):
    """Keep test calculations independent from workspace runtime state."""
    if configuration is None:
        configuration = load_initial_scoring_configuration()
    return _calculate_scoring(datasets, *args, configuration=configuration, **kwargs)


def frame(rows, operator='EE', environment='City', campaign='2026Q2'):
    return pd.DataFrame([{'Operator': operator, 'Campaign': campaign, 'G_Level_1': 'Drive',
                          'G_Level_2': environment, **row} for row in rows])


def metric(result, code, operator='EE', environment='DriveCity', campaign='2026Q2'):
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


@pytest.mark.parametrize(
    'sample',
    CONFIG['validation_examples']['mapping_workbook_samples'],
    ids=lambda sample: f"{sample['kpi_code']}-{sample['environment']}",
)
def test_mapping_workbook_samples_match_interpolated_scores(sample):
    metric_config = next(metric for metric in CONFIG['metrics'] if metric['code'] == sample['kpi_code'])
    context = metric_config['contexts'][sample['environment']]

    assert sample['thresholds'] == context['thresholds']
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


@pytest.mark.parametrize('kpi_code', ['C25', 'C30'])
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
    context = next(item for item in CONFIG['metrics'] if item['code'] == 'C31')['contexts']['DriveCity']
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
    assert metric(result, 'C5')['value'] == 50
    assert metric(result, 'C6')['value'] == 7
    assert metric(result, 'C7')['value'] == pytest.approx(100 / 3)
    assert metric(result, 'C10')['value'] == 25
    assert metric(result, 'C15')['value'] == 100
    assert metric(result, 'C8')['value'] == pytest.approx(100 / 3)
    assert metric(result, 'C9')['value'] == 3
    assert metric(result, 'C13')['score'] == 1


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
    expected = {'C17': 50, 'C18': 2, 'C19': 100, 'C20': 3, 'C21': 50, 'C24': 50,
                'C25': 180.2, 'C26': 100, 'C29': 0, 'C30': 20, 'C31': 1500, 'C32': 50,
                'C33': 50, 'C34': 50, 'C35': 50, 'C36': 2.5, 'C37': 30}
    for code, value in expected.items():
        assert metric(result, code)['value'] == pytest.approx(value), code


def test_campaign_environment_aliases_and_missing_coverage():
    first = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}])
    second = frame([{'Session_Type': 'CALL', 'Call_Status': 'Failed'}], campaign='2026Q3')
    invalid = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}], environment='Unknown')
    data = pd.concat([first, second, invalid], ignore_index=True).rename(columns={'Operator': 'operator', 'G_Level_1': 'g level 1', 'G_Level_2': 'g-level-2'})
    data['Region'] = 'City'
    result = calculate_scoring({'voice': data}, ['Operator'])
    assert metric(result, 'C5')['value'] == 100
    assert metric(result, 'C5', campaign='2026Q3')['value'] == 0
    assert len([r for r in result['scoring'] if r['kpi_code'] == 'C5']) == 2
    assert all(not row['complete_coverage'] and row['score'] is None for row in result['totals'])
    assert next(row for row in result['totals'] if row['environment'] == 'Combined' and row['category'] == 'Overall')['max_points'] == pytest.approx(1000)
    assert any('excluded' in warning for warning in result['warnings'])
    missing = calculate_scoring({'voice': first.drop(columns='G_Level_2')}, ['Operator'])
    assert missing['scoring'] == []
    assert any('G_Level_2' in warning for warning in missing['warnings'])


def test_best_operator_ultra_and_gap_are_per_campaign_and_group():
    frames = []
    for operator, rate in [('EE', 1000), ('Other', 700)]:
        frames.append(frame([{'Test_Name': 'FDTT DL', 'Test_Result': 'Completed', 'Mean_Data_Rate': rate}], operator=operator))
    frames.append(frame([{'Test_Name': 'FDTT DL', 'Test_Result': 'Completed', 'Mean_Data_Rate': 2000}], operator='Other', campaign='Other campaign'))
    result = calculate_scoring({'data': pd.concat(frames)}, ['Operator'])
    assert metric(result, 'C25')['score'] == 1
    c25_context = next(m for m in CONFIG['metrics'] if m['code'] == 'C25')['contexts']['DriveCity']
    expected = interpolate_score(700, c25_context['thresholds'], 1000, c25_context['score_mapping'])
    assert metric(result, 'C25', operator='Other')['score'] == pytest.approx(expected)
    gap = next(row for row in result['gap'] if row['kpi_code'] == 'C25')
    assert gap['gap_points'] == pytest.approx(gap['operator_points'] - gap['baseline_points'])
    assert gap['gap_points'] < 0
    assert any('Baseline EE' in warning for warning in result['warnings'])
    assert all(row['campaign'] == '2026Q2' for row in result['gap'])


def test_dimension_grouping_and_required_projection():
    source = frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed', 'Region': 'North', 'City': 'A', 'Vendor': 'V'},
                    {'Session_Type': 'CALL', 'Call_Status': 'Failed', 'Region': 'South', 'City': 'B', 'Vendor': 'W'}])
    result = calculate_scoring({'voice': source}, ['Region', 'City', 'Vendor', 'Dataset Type'])
    rows = [row for row in result['scoring'] if row['kpi_code'] == 'C5']
    assert len(rows) == 2
    assert {row['value'] for row in rows} == {0, 100}
    assert all(row['operator'] == 'EE' and row['dataset_type'] == 'Voice' for row in rows)
    columns = required_input_columns('voice', ['Dataset Type', 'Region'])
    assert {'Operator', 'Campaign', 'G_Level_1', 'G_Level_2', 'Dataset_Kind', 'Region'} <= set(columns)


def test_empty_denominators_do_not_fabricate_scores():
    result = calculate_scoring({'data': frame([{'Type_of_Test': 'Interactivity', 'Packets_Sent': 0,
                                              'Packets_Lost': 1, 'Packets_Discarded': None,
                                              'Packets_Corrupted': None, 'Packets_Not_Sent': None}])})
    assert metric(result, 'C36')['score'] is None
    assert metric(result, 'C36')['weighted_points'] is None


def test_baseline_alias_category_totals_and_incomplete_gap_totals():
    source = pd.concat([frame([{'Session_Type': 'CALL', 'Call_Status': 'Completed'}], operator='EE (UK)'),
                        frame([{'Session_Type': 'CALL', 'Call_Status': 'Failed'}], operator='Other')])
    result = calculate_scoring({'voice': source})
    gap = next(row for row in result['gap'] if row['kpi_code'] == 'C5')
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
    c5_gap = next(row for row in result['gap'] if row['kpi_code'] == 'C5')

    assert c5_gap['baseline_actual_operator'] == 'VF_UK'
    assert c5_gap['gap_points'] == pytest.approx(c5_gap['operator_points'] - c5_gap['baseline_points'])
    assert c5_gap['gap_points'] < 0
    assert result['gap_direction'] == 'operator_minus_reference'


def test_zero_weight_metrics_remain_visible_but_do_not_block_total_coverage():
    configuration = scoring_configuration()
    for metric_configuration in configuration['metrics']:
        for context in metric_configuration['contexts'].values():
            context['max_points'] = 0
    c17 = next(item for item in configuration['metrics'] if item['code'] == 'C17')
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
