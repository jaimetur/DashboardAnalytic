"""Displayed table modes preserve KPI evidence, aggregates and chart inputs."""
import csv
from copy import deepcopy
from io import BytesIO, StringIO

import pytest
from pptx import Presentation

from src.modules.scoring_exports import export_scoring_csv, export_scoring_powerpoint, _hierarchy_chart_color
from src.modules.scoring_views import build_scoring_views
from tests.scoring_fixtures import scoring_configuration
from tests.test_scoring_exports import TEMPLATE, _result, _comparison_matrices


def _job():
    return {'aggregation_levels': ['Operator'], 'baseline_operator': 'EE',
            'configuration': scoring_configuration(), 'campaigns': ['UK_Q2_2026'], 'nr_mode': 'NSA'}


@pytest.mark.parametrize('mode', ['expanded', 'summary'])
def test_display_csv_has_category_points_and_mean_gap_without_double_counting(mode):
    job = _job()
    result = _result(missing={('O2 UK', 'K1')})
    rows = list(csv.DictReader(StringIO(export_scoring_csv(job, result, 'scoring', mode))))
    matrix = build_scoring_views(job, result)['score_tables'][0]
    operator_rows = [row for row in rows if row['operator'] == 'O2 UK']
    category_rows = [row for row in operator_rows if row['row_type'] == 'category']
    assert len(category_rows) == 7
    assert all(row['kpi_value'] == '' for row in category_rows)
    assert {row['row_type'] for row in operator_rows} == ({'kpi', 'category', 'total'} if mode == 'expanded' else {'category', 'total'})
    total = next(row for row in operator_rows if row['row_type'] == 'total')
    valid_gaps = [row['gaps']['O2 UK'] for row in matrix['rows'] if row['gaps']['O2 UK'] is not None]
    assert float(total['gap_points']) == pytest.approx(sum(valid_gaps) / len(valid_gaps))
    assert float(total['score_points']) == pytest.approx(matrix['total']['values']['O2 UK']['points'])
    assert sum(float(row['score_points']) for row in category_rows) == pytest.approx(float(total['score_points']))


def test_summary_csv_gap_excludes_reference_and_keeps_missing_comparisons():
    result = _result(missing={('EE', 'K1')})
    rows = list(csv.DictReader(StringIO(export_scoring_csv(_job(), result, 'gap', 'summary'))))
    assert all(row['operator'] != 'EE' for row in rows)
    assert {row['row_type'] for row in rows} == {'category', 'total'}
    assert all(row['reference_operator'] == 'EE' for row in rows)


def test_ppt_table_modes_include_bold_category_totals_and_keep_identical_charts():
    result = _result(missing={('O2 UK', 'K1')})
    presentations = [Presentation(BytesIO(export_scoring_powerpoint(_job(), result, TEMPLATE, table_mode=mode)))
                     for mode in ('expanded', 'summary')]
    expanded, summary = [_comparison_matrices(presentation)[0] for presentation in presentations]
    assert len(expanded.rows) == 32 + 7 + 2
    assert len(summary.rows) == 7 + 2
    assert all(summary.cell(index, 4).text_frame.paragraphs[0].font.bold for index in range(1, 8))
    assert all(summary.cell(index, 1).text.endswith(' total') for index in range(1, 8))
    assert expanded.cell(len(expanded.rows) - 1, 4).text == summary.cell(len(summary.rows) - 1, 4).text
    chart_values = [[list(series.values) for slide in presentation.slides for shape in slide.shapes
                     if shape.has_chart for series in shape.chart.series] for presentation in presentations]
    assert chart_values[0] == chart_values[1]
    all_gap_slides = [slide for slide in presentations[1].slides
                      if slide.shapes.title.text.split('\n')[0] == 'GAP Analysis — All vs EE']
    table = next(shape.table for shape in all_gap_slides[0].shapes if shape.has_table)
    assert len(table.rows) == 9
    assert table.cell(8, 1).text == 'Average KPI GAP'
    assert table.cell(8, 3).text != 'N/A'


def test_seven_category_tints_are_distinct_and_invalid_export_mode_is_rejected():
    colors = [_hierarchy_chart_color('#F7931E', index, 7) for index in range(7)]
    assert len(set(colors)) == 7
    assert colors[0] == '#F7931E'
    with pytest.raises(ValueError, match='Table mode'):
        export_scoring_powerpoint(_job(), _result(), TEMPLATE, table_mode='unsupported')


@pytest.mark.parametrize('layout', ['end', 'adjacent'])
def test_gap_placement_excludes_reference_and_preserves_score_and_gap_values(layout):
    job = _job()
    presentation = Presentation(BytesIO(export_scoring_powerpoint(job, _result(), TEMPLATE, gap_layout=layout)))
    slide = next(slide for slide in presentation.slides if slide.shapes.title.text.split('\n')[0] == 'Scoring Tables')
    table = next(shape.table for shape in slide.shapes if shape.has_table)
    if layout == 'end':
        headers = [cell.text for cell in table.rows[0].cells][4:]
        assert headers[:4] == ['EE', 'O2 UK', 'Three UK', 'Vodafone UK']
        assert len(headers) == 7
        assert all('GAP' in text and 'GAP EE' not in text for text in headers[4:])
    else:
        headers = [cell.text for cell in table.rows[2].cells][4:]
        assert headers == ['Score', 'Score', 'GAP', 'Score', 'GAP', 'Score', 'GAP']
        values = [cell.text for cell in table.rows[3].cells][4:]
        assert values[0] == '58.79'
        assert values[2] != '0.00'
    with pytest.raises(ValueError, match='GAP layout'):
        export_scoring_powerpoint(job, _result(), TEMPLATE, gap_layout='invalid')


def _multi_environment_result():
    result = _result(operators=('EE', 'O2 UK'), warnings=[])
    configuration = result['configuration']
    metrics = {metric['code']: metric for metric in configuration['metrics']}
    road_rows = deepcopy(result['scoring'])
    for row in road_rows:
        row['environment'] = 'DriveConnectionroad'
        row['max_points'] = metrics[row['kpi_code']]['contexts']['DriveConnectionroad']['max_points']
        row['weighted_points'] = row['score'] * row['max_points']
    result['scoring'].extend(road_rows)
    return result


@pytest.mark.parametrize('levels', [['Operator'], ['Operator', 'Region', 'Campaign']])
def test_all_environment_ppt_finishes_each_full_block_aggregate_first(levels):
    job = {**_job(), 'aggregation_levels': levels}
    result = _multi_environment_result()
    result.update({'aggregation_contract_version': 2, 'aggregation_levels': levels})
    presentation = Presentation(BytesIO(export_scoring_powerpoint(job, result, TEMPLATE, table_mode='summary')))
    titles = [slide.shapes.title.text.split('\n')[0] for slide in presentation.slides][2:]
    expected_block = ['Scoring & GAP Analysis — Best Network', 'Scoring Chart', 'Scoring Tables',
                      'GAP Analysis — All vs EE',
                      'GAP Analysis — O2 UK vs EE' if len(levels) > 1 else 'GAP Analysis']
    assert titles == expected_block * 3
    for index, environment in enumerate(('All Environments', 'DriveCity', 'DriveConnectionroad')):
        for slide in list(presentation.slides)[2 + index * 5:7 + index * 5]:
            text = '\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame)
            assert f'Environment: {environment}' in text
    selected = Presentation(BytesIO(export_scoring_powerpoint(job, result, TEMPLATE, environment='DriveCity')))
    assert len(selected.slides) == 7
    assert all('Environment: DriveCity' in slide.shapes.title.text for slide in list(selected.slides)[2:])


def test_csv_environment_selection_filters_rows_and_rejects_unavailable_environment():
    rows = list(csv.DictReader(StringIO(export_scoring_csv(
        _job(), _multi_environment_result(), 'scoring', 'summary', environment='DriveConnectionroad',
    ))))
    assert {row['environment'] for row in rows} == {'DriveConnectionroad'}
    with pytest.raises(ValueError, match='not available'):
        export_scoring_powerpoint(_job(), _result(), TEMPLATE, environment='Walk')
    with pytest.raises(ValueError, match='not available'):
        export_scoring_csv(_job(), _result(), 'gap', 'summary', environment='Unknown')
