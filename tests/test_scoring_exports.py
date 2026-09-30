from collections import Counter
from io import BytesIO
import json
from pathlib import Path
import re

import pytest
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.util import Inches

from src.modules.scoring_exports import export_scoring_powerpoint
from src.modules.scoring_views import THRESHOLD_COLORS, build_scoring_views
from tests.scoring_fixtures import scoring_configuration


ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / 'assets/ppt-templates/Template_CDR_analysis.pptx'
METRICS = scoring_configuration()['metrics']
OPERATORS = ('Vodafone UK', 'O2 UK', 'Three UK', 'EE')
MAPPED_OPERATOR_ORDER = ('EE', 'Three UK', 'O2 UK', 'Vodafone UK')
MAPPED_OPERATOR_COLORS = {
    'EE': '#12AB34',
    'Three UK': '#3456AB',
    'O2 UK': '#AB3456',
    'Vodafone UK': '#56AB12',
}
VOICE_CATEGORIES = {'CLASSIC CALLS', 'WHATSAPP CALLS', 'MULTI RAB'}
WARNINGS = ['Speech CDR missing from this comparison.', 'Incomplete campaign coverage.']


def _score_for(operator, index, code):
    if code == 'C9':
        return {'Vodafone UK': 0.50, 'O2 UK': 0.85, 'Three UK': 0.97, 'EE': 1.00}.get(operator, 0.90)
    if operator == 'EE':
        return 0.80
    if operator == 'Three UK':
        return 0.90
    if operator == 'Vodafone UK':
        return 0.40 if index % 2 == 0 else 0.90
    if operator == 'O2 UK':
        return 0.50 if index % 2 == 0 else 0.95
    return 0.90


def _result(operators=OPERATORS, *, missing=(), peer_score=None, warnings=None):
    rows = []
    for index, metric in enumerate(METRICS):
        maximum = metric['contexts']['DriveCity']['max_points']
        for operator in operators:
            if (operator, metric['code']) in missing:
                continue
            score = peer_score(operator, index, metric) if peer_score else _score_for(
                operator, index, metric['code'],
            )
            rows.append({
                'campaign': 'UK_Q2_2026',
                'region': 'North',
                'operator': operator,
                'environment': 'DriveCity',
                'dataset_type': metric['source_kind'].title(),
                'kpi_code': metric['code'],
                'category': metric['category'],
                'kpi': metric['kpi'],
                'kpi_type': metric['kpi_type'],
                'value': score * 100,
                'score': score,
                'weighted_points': maximum * score,
                'max_points': maximum,
                'sample_count': 100,
                'complete': True,
            })
    totals = []
    for operator in operators:
        points = sum(row['weighted_points'] for row in rows if row['operator'] == operator)
        totals.append({
            'campaign': 'UK_Q2_2026', 'region': 'North', 'operator': operator,
            'environment': 'DriveCity', 'category': 'Overall',
            'weighted_points': points, 'max_points': 650,
        })
    return {
        'scoring': rows,
        'totals': totals,
        'warnings': list(WARNINGS if warnings is None else warnings),
        'configuration': scoring_configuration(),
    }


def _mapping_groups(order=MAPPED_OPERATOR_ORDER, colors=MAPPED_OPERATOR_COLORS):
    return [
        {'canonical': operator, 'aliases': [], 'position': position, 'color': colors[operator]}
        for position, operator in enumerate(order)
    ]


def _export(result, *, levels=('Operator',), baseline='EE', operator_mapping_groups=None, job_fields=None):
    job = {
        'aggregation_levels': list(levels),
        'nr_mode': 'NSA',
        'baseline_operator': baseline,
        'campaigns': ['UK_Q2_2026'],
        'configuration': scoring_configuration(),
    }
    job.update(job_fields or {})
    output = export_scoring_powerpoint(
        job, result, TEMPLATE, operator_mapping_groups=operator_mapping_groups,
    )
    return Presentation(BytesIO(output))


def _table_shapes(presentation):
    return [shape.table for slide in presentation.slides for shape in slide.shapes if shape.has_table]


def _comparison_matrices(presentation):
    return [
        table for table in _table_shapes(presentation)
        if len(table.rows) >= 3 and table.cell(0, 0).text.strip() == 'NETCHECK KPIs'
    ]


def _normalized_headers(table):
    return [re.sub(r'\s+', ' ', table.cell(0, column).text).strip() for column in range(len(table.columns))]


def _operator_columns(table):
    headers = _normalized_headers(table)
    gap_start = next((index for index, label in enumerate(headers) if label.startswith('GAP ')), len(headers))
    return {headers[index]: index for index in range(4, gap_start)}


def _rgb(cell):
    return str(cell.fill.fore_color.rgb)


def _slide_text(slide):
    pieces = []
    for shape in slide.shapes:
        if shape.has_text_frame:
            pieces.append(shape.text)
        elif shape.has_table:
            pieces.extend(cell.text for row in shape.table.rows for cell in row.cells)
    return '\n'.join(pieces)


def _slide_with_table(presentation, headers):
    expected = [label.casefold() for label in headers]
    for slide in presentation.slides:
        for shape in slide.shapes:
            if shape.has_table and [cell.text.strip().casefold() for cell in shape.table.rows[0].cells] == expected:
                return slide, shape.table
    raise AssertionError(f'No slide has the expected table header: {headers!r}')


def test_powerpoint_exports_one_reference_style_scoring_matrix_with_signed_gaps_and_notes():
    result = _result(missing={('O2 UK', 'C5')})
    groups = _mapping_groups()
    views = build_scoring_views(
        {'levels': ['Operator'], 'baseline_operator': 'EE'},
        result,
        operator_mapping_groups=groups,
    )
    assert len(views['score_tables'][0]['rows']) == 32  # Totals without KPI codes are not a 33rd metric.
    presentation = _export(result, operator_mapping_groups=groups)
    source = Presentation(TEMPLATE)
    matrices = _comparison_matrices(presentation)

    assert presentation.slide_width == source.slide_width
    assert presentation.slide_height == source.slide_height
    assert len(matrices) == 1
    table = matrices[0]
    headers = _normalized_headers(table)
    assert headers[:4] == ['NETCHECK KPIs', 'KPI', 'Score weight (%)', 'Max score']
    operator_columns = _operator_columns(table)
    assert list(operator_columns) == list(MAPPED_OPERATOR_ORDER)
    gap_columns = [index for index, header in enumerate(headers) if header.startswith('GAP ')]
    assert len(gap_columns) == 3
    assert len(table.rows) == 34  # header + all 32 KPIs + total
    assert len(table.columns) == 11
    assert [table.cell(row, 1).text for row in range(1, 33)] == [metric['kpi'] for metric in METRICS]
    assert all(table.cell(row, 0).text not in OPERATORS for row in range(1, 33))

    total_row = len(table.rows) - 1
    assert table.cell(total_row, 0).text == 'TOTAL'
    assert table.cell(total_row, 2).text == '65.00%'
    assert table.cell(total_row, 3).text == '650.00'
    assert table.cell(total_row, 2).text != '100.00%'

    # Scoring bands keep the reference colors; operator headers follow workspace mappings.
    reference_header_colors = {
        'Score weight (%)': _rgb(table.cell(0, 2)),
        'Max score': _rgb(table.cell(0, 3)),
    }
    assert reference_header_colors == {
        'Score weight (%)': '4EA72E',
        'Max score': 'FF0000',
    }
    assert {operator: _rgb(table.cell(0, column)) for operator, column in operator_columns.items()} == {
        operator: color.lstrip('#').upper() for operator, color in MAPPED_OPERATOR_COLORS.items()
    }
    assert all(_rgb(table.cell(0, column)) == 'FFFF00' for column in gap_columns)

    signed_gaps = [
        float(table.cell(row, column).text)
        for row in range(1, 33) for column in gap_columns
        if table.cell(row, column).text != 'N/A'
    ]
    assert any(value > 0 for value in signed_gaps)
    assert any(value < 0 for value in signed_gaps)

    c5_index = next(index for index, metric in enumerate(METRICS, 1) if metric['code'] == 'C5')
    missing_cell = table.cell(c5_index, operator_columns['O2 UK'])
    assert missing_cell.text == 'N/A'
    assert _rgb(missing_cell) == 'ECEFF1'

    c9_index = next(index for index, metric in enumerate(METRICS, 1) if metric['code'] == 'C9')
    expected_bands = {'Vodafone UK': 'Low', 'O2 UK': 'Medium', 'Three UK': 'High', 'EE': 'UltraHigh'}
    for operator, band in expected_bands.items():
        assert _rgb(table.cell(c9_index, operator_columns[operator])) == THRESHOLD_COLORS[band].lstrip('#')

    gap_slide, gap_table = _slide_with_table(
        presentation, ['Category', 'NETCHECK KPIs', 'GAP operator −\nEE', 'Type of KPI'],
    )
    expected_gap_table = views['gap_tables'][0]
    assert [gap_table.cell(row, 1).text for row in range(1, len(gap_table.rows))] == [row['kpi'] for row in expected_gap_table['rows']]
    assert [float(gap_table.cell(row, 2).text) for row in range(1, len(gap_table.rows))] == pytest.approx([row['gap_points'] for row in expected_gap_table['rows']], abs=.0051)
    assert _rgb(gap_table.cell(0, 2)) == 'FFFF00'
    reliable_rows = [row for row in range(1, len(gap_table.rows)) if gap_table.cell(row, 3).text == 'Reliable']
    if reliable_rows:
        assert _rgb(gap_table.cell(reliable_rows[0], 3)) == THRESHOLD_COLORS['High'].lstrip('#')

    titles = [slide.shapes.title.text.split('\n')[0] for slide in presentation.slides]
    assert titles[:2] == ['Scoring & GAP Analysis', 'Scoring & GAP Analysis']
    assert titles[2:6] == [
        'Scoring & GAP Analysis — Best Network', 'Scoring Chart', 'Scoring Tables',
        'GAP Analysis — All vs EE',
    ]
    assert all(title == 'GAP Analysis' for title in titles[6:])
    assert len(titles[6:]) == 3
    intro_slides = [presentation.slides[index] for index in range(2)]
    assert [slide.slide_layout.name for slide in intro_slides] == ['Title Page', 'Title Only']
    cover_text = _slide_text(presentation.slides[0])
    transition_text = _slide_text(presentation.slides[1])
    expected_filter_text = 'NR Mode: NSA · Aggregation: Operator · Baseline: EE'
    assert expected_filter_text in cover_text
    assert expected_filter_text in transition_text
    assert 'Campaigns: UK_Q2_2026' in cover_text
    assert 'Campaigns: UK_Q2_2026' in transition_text
    assert next(shape for shape in presentation.slides[0].shapes if shape.name == 'Scoring Campaigns').top > Inches(5.66)
    assert next(shape for shape in presentation.slides[1].shapes if shape.name == 'Scoring Campaigns').top > Inches(1.7)

    summary_view = views['gap_summary_tables'][0]
    summary_slide, summary_table = _slide_with_table(
        presentation,
        ['Category', 'NETCHECK KPIs', 'Type of KPI',
         *[f'{operator} − EE' for operator in summary_view['operators']]],
    )
    assert summary_slide is presentation.slides[5]
    assert len(summary_table.rows) == len(summary_view['rows']) + 2
    assert len(summary_table.columns) == len(summary_view['operators']) + 3
    assert [summary_table.cell(row, 1).text for row in range(1, 33)] == [
        row['kpi'] for row in summary_view['rows']
    ]
    for row_index, row in enumerate(summary_view['rows'], 1):
        for operator_index, operator in enumerate(summary_view['operators'], 3):
            expected = row['gaps'][operator]
            cell = summary_table.cell(row_index, operator_index)
            if expected is None:
                assert cell.text == 'N/A'
                assert _rgb(cell) == THRESHOLD_COLORS['Unavailable'].lstrip('#')
            else:
                assert float(cell.text) == pytest.approx(expected, abs=.0051)
                assert _rgb(cell) == row['gap_colors'][operator].lstrip('#')
    summary_total_row = len(summary_table.rows) - 1
    assert summary_table.cell(summary_total_row, 0).text == 'Total'
    for operator_index, operator in enumerate(summary_view['operators'], 3):
        expected = summary_view['total']['gaps'][operator]
        cell = summary_table.cell(summary_total_row, operator_index)
        if expected is None:
            assert cell.text == 'N/A'
        else:
            assert float(cell.text) == pytest.approx(expected, abs=.0051)

    chart_shapes = [shape.chart for slide in presentation.slides for shape in slide.shapes if shape.has_chart]
    assert len(chart_shapes) == 3
    assert chart_shapes[0].chart_type == XL_CHART_TYPE.COLUMN_STACKED
    total_series = next(series for series in chart_shapes[0].series if series.name == 'Total')
    assert list(total_series.values) == pytest.approx([
        sum(row['weighted_points'] for row in result['scoring'] if row['operator'] == operator)
        for operator in MAPPED_OPERATOR_ORDER
    ])
    line_plot = chart_shapes[0]._chartSpace.chart.plotArea.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}lineChart')
    assert line_plot.find('.//{http://schemas.openxmlformats.org/drawingml/2006/chart}dLblPos').get('val') == 't'
    assert line_plot.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}noFill') is not None
    assert chart_shapes[1].chart_type == XL_CHART_TYPE.DOUGHNUT
    chart = chart_shapes[2]
    assert chart.chart_type == XL_CHART_TYPE.COLUMN_CLUSTERED
    categories = [category.label for category in chart.plots[0].categories]
    assert categories == list(dict.fromkeys(metric['category'] for metric in METRICS))
    assert [series.name for series in chart.series] == list(MAPPED_OPERATOR_ORDER)
    for series in chart.series:
        expected = [sum(row['weighted_points'] for row in result['scoring']
                        if row['operator'] == series.name and row['category'] == category) for category in categories]
        assert list(series.values) == pytest.approx(expected)
        assert str(series.format.fill.fore_color.rgb) == MAPPED_OPERATOR_COLORS[series.name].lstrip('#')
    assert chart.plots[0].has_data_labels
    assert chart.legend.position == XL_LEGEND_POSITION.TOP
    assert chart.legend.include_in_layout
    assert chart.value_axis.maximum_scale > max(value for series in chart.series for value in series.values if value is not None)
    reference_top = table.cell(0, operator_columns['EE'])._tc.get_or_add_tcPr().find('{http://schemas.openxmlformats.org/drawingml/2006/main}lnT')
    assert int(reference_top.get('w')) > 4500

    assert 'UK_Q2_2026' in '\n'.join(_slide_text(slide) for slide in presentation.slides)
    visible = '\n'.join(_slide_text(slide) for slide in presentation.slides)
    assert all(warning not in visible for warning in WARNINGS)
    assert all(all(warning in slide.notes_slide.notes_text_frame.text for warning in WARNINGS)
               for slide in presentation.slides)


def test_powerpoint_splits_many_operators_into_comparable_five_column_pages():
    peers = [f'Network {index:02}' for index in range(36)]
    operators = peers + ['EE']
    mapped_order = list(reversed(peers)) + ['EE']
    colors = {name: f'#{index + 1:06X}' for index, name in enumerate(mapped_order)}
    groups = _mapping_groups(mapped_order, colors)
    result = _result(
        operators,
        peer_score=lambda operator, _index, _metric: 0.80 if operator == 'EE' else 0.90,
        warnings=[],
    )
    presentation = _export(result, operator_mapping_groups=groups)
    matrices = _comparison_matrices(presentation)

    assert len(matrices) == 9
    counts = Counter()
    for table in matrices:
        operator_columns = _operator_columns(table)
        assert len(operator_columns) == 5
        assert 'EE' in operator_columns
        assert len(table.rows) == 34
        assert {operator: _rgb(table.cell(0, column)) for operator, column in operator_columns.items()} == {
            operator: colors[operator].lstrip('#').upper() for operator in operator_columns
        }
        counts.update(operator_columns.keys())
    assert counts['EE'] == len(matrices)
    assert {name for name in counts if name != 'EE'} == set(peers)
    assert all(counts[name] == 1 for name in peers)
    assert [name for name in mapped_order if name != 'EE'] == [
        name for table in matrices for name in _operator_columns(table) if name != 'EE'
    ]
    charts = [shape.chart for slide in presentation.slides for shape in slide.shapes if shape.has_chart]
    scoring_charts = [chart for chart in charts if chart.chart_type == XL_CHART_TYPE.COLUMN_CLUSTERED]
    assert len(scoring_charts) == 1
    assert [series.name for series in scoring_charts[0].series] == mapped_order
    assert {series.name: str(series.format.fill.fore_color.rgb) for series in scoring_charts[0].series} == {
        operator: colors[operator].lstrip('#').upper() for operator in mapped_order}


def test_powerpoint_empty_result_stays_readable_and_keeps_warnings_in_notes():
    empty_warning = 'No source data was available for this job.'
    presentation = _export({'scoring': [], 'totals': [], 'warnings': [empty_warning]})
    visible = '\n'.join(_slide_text(slide) for slide in presentation.slides)

    assert 'No scoring measurements are available' in visible
    assert empty_warning not in visible
    assert not _comparison_matrices(presentation)
    assert not any(shape.has_chart for slide in presentation.slides for shape in slide.shapes)
    assert all(empty_warning in slide.notes_slide.notes_text_frame.text for slide in presentation.slides)


def test_cover_campaigns_prefer_scored_contexts_and_include_context_filters():
    result = _result()
    job_fields = {
        'campaigns': ['Wrong_source_campaign'],
        'source_metadata': [{'campaigns': ['Wrong_source_campaign']}],
        'nr_mode': 'SA',
        'aggregation_levels': ['Operator', 'City'],
        'context_filters': [{'column': 'City', 'operator': '=', 'value': 'London'}],
    }
    presentation = _export(result, levels=('Operator',), job_fields=job_fields)
    for slide in (presentation.slides[index] for index in range(2)):
        text = _slide_text(slide)
        assert 'NR Mode: SA · Aggregation: Operator, City · Baseline: EE · City = London' in text
        assert 'Campaigns: UK_Q2_2026' in text
        assert 'Wrong_source_campaign' not in text
