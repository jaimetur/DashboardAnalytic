from collections import Counter
from io import BytesIO
import json
from pathlib import Path
import re

import pytest
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches

from src.modules.scoring_exports import _hierarchy_chart_color, export_scoring_powerpoint
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
CATEGORY_SUBTOTAL_FILL = 'E3E6E7'


def _score_for(operator, index, code):
    if code == 'K5':
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


def _export(result, *, levels=('Operator',), baseline='EE', operator_mapping_groups=None,
            job_fields=None, environment='DriveCity'):
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
        environment=environment,
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
    for shape in _nested_shapes(slide.shapes):
        if shape.has_text_frame:
            pieces.append(shape.text)
        elif shape.has_table:
            pieces.extend(cell.text for row in shape.table.rows for cell in row.cells)
    return '\n'.join(pieces)


def _nested_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _nested_shapes(shape.shapes)


def _charts_on_slide(slide):
    return [shape.chart for shape in _nested_shapes(slide.shapes) if shape.has_chart]


def _series_color(series):
    return str(series.format.fill.fore_color.rgb).upper()


def _voice_tint(color: str) -> str:
    channels = [int(color.lstrip('#')[index:index + 2], 16) for index in (0, 2, 4)]
    return '{:02X}{:02X}{:02X}'.format(
        *(round(channel + (255 - channel) * .45) for channel in channels)
    )


def _assert_sparse_series_values(series, expected_values):
    actual_values = list(series.values)
    assert len(actual_values) == len(expected_values)
    for actual, expected in zip(actual_values, expected_values):
        if expected is None:
            assert actual is None
        else:
            assert actual == pytest.approx(expected)


def _assert_gray_category_row(table, row_index):
    assert all(
        str(table.cell(row_index, column).fill.fore_color.rgb).upper() == CATEGORY_SUBTOTAL_FILL
        for column in range(len(table.columns))
    )


def _assert_category_shade_bar(chart_group, chart_shape, categories):
    keys = [shape for shape in chart_group.shapes
            if shape.name == 'Scoring Chart Category Shade Key' and shape.has_table]
    assert len(keys) == 1
    key = keys[0]
    cells = list(key.table.rows[0].cells)
    assert [cell.text for cell in cells] == categories
    assert [str(cell.fill.fore_color.rgb).upper() for cell in cells] == [
        _hierarchy_chart_color('#606060', index, len(categories)).lstrip('#').upper()
        for index in range(len(categories))
    ]
    assert key.top >= chart_shape.top + chart_shape.height
    assert chart_group.top + chart_group.height >= key.top + key.height


def _legend_visible_series_names(chart):
    deleted = {
        int(entry.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}idx').get('val'))
        for entry in chart._chartSpace.xpath('.//c:legend/c:legendEntry')
        if entry.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}delete').get('val') == '1'
    }
    return [series.name for index, series in enumerate(chart.series) if index not in deleted]


def _slide_with_table(presentation, headers):
    expected = [label.casefold() for label in headers]
    for slide in presentation.slides:
        for shape in slide.shapes:
            if shape.has_table and [cell.text.strip().casefold() for cell in shape.table.rows[0].cells] == expected:
                return slide, shape.table
    raise AssertionError(f'No slide has the expected table header: {headers!r}')


def test_powerpoint_exports_one_reference_style_scoring_matrix_with_signed_gaps_and_notes():
    result = _result(missing={('O2 UK', 'K1')})
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
    display_rows = views['score_tables'][0]['expanded_rows']
    assert len(table.rows) == len(display_rows) + 2
    assert len(table.columns) == 11
    assert [table.cell(row, 1).text for row in range(1, len(table.rows) - 1)] == [row['kpi'] for row in display_rows]
    assert all(table.cell(row, 0).text not in OPERATORS for row in range(1, 33))
    for row_index, row in enumerate(display_rows, 1):
        if row.get('row_type') == 'category':
            _assert_gray_category_row(table, row_index)

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

    c5_index = next(index for index, metric in enumerate(display_rows, 1) if metric['kpi_code'] == 'K1')
    missing_cell = table.cell(c5_index, operator_columns['O2 UK'])
    assert missing_cell.text == 'N/A'
    assert _rgb(missing_cell) == 'ECEFF1'

    c9_index = next(index for index, metric in enumerate(display_rows, 1) if metric['kpi_code'] == 'K5')
    expected_bands = {'Vodafone UK': 'Low', 'O2 UK': 'Medium', 'Three UK': 'High', 'EE': 'UltraHigh'}
    for operator, band in expected_bands.items():
        assert _rgb(table.cell(c9_index, operator_columns[operator])) == THRESHOLD_COLORS[band].lstrip('#')

    gap_slide, gap_table = _slide_with_table(
        presentation, ['Category', 'NETCHECK KPIs', 'GAP operator −\nEE', 'Type of KPI'],
    )
    expected_gap_table = views['gap_tables'][0]
    assert [gap_table.cell(row, 1).text for row in range(1, len(gap_table.rows) - 1)] == [row['kpi'] for row in expected_gap_table['expanded_rows']]
    assert [float(gap_table.cell(row, 2).text) for row in range(1, len(gap_table.rows) - 1)] == pytest.approx([row['gap_points'] for row in expected_gap_table['expanded_rows']], abs=.0051)
    assert _rgb(gap_table.cell(0, 2)) == 'FFFF00'
    reliable_rows = [row for row in range(1, len(gap_table.rows)) if gap_table.cell(row, 3).text == 'Reliable']
    if reliable_rows:
        assert _rgb(gap_table.cell(reliable_rows[0], 3)) == THRESHOLD_COLORS['High'].lstrip('#')

    titles = [slide.shapes.title.text.split('\n')[0] for slide in presentation.slides]
    assert titles[:2] == ['Scoring & GAP Analysis', 'Scoring & GAP Analysis']
    assert titles[2:6] == [
        'Scoring & GAP Analysis — Best Network', 'Scoring Chart', 'Scoring Table',
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
    assert len(summary_table.rows) == len(summary_view['expanded_rows']) + 2
    assert len(summary_table.columns) == len(summary_view['operators']) + 3
    assert [summary_table.cell(row, 1).text for row in range(1, len(summary_table.rows) - 1)] == [
        row['kpi'] for row in summary_view['expanded_rows']
    ]
    for row_index, row in enumerate(summary_view['expanded_rows'], 1):
        if row.get('row_type') == 'category':
            _assert_gray_category_row(summary_table, row_index)
        for operator_index, operator in enumerate(summary_view['operators'], 3):
            expected = row['gaps'][operator]
            cell = summary_table.cell(row_index, operator_index)
            if expected is None:
                assert cell.text == 'N/A'
                if row.get('row_type') != 'category':
                    assert _rgb(cell) == THRESHOLD_COLORS['Unavailable'].lstrip('#')
            else:
                assert float(cell.text) == pytest.approx(expected, abs=.0051)
                if row.get('row_type') != 'category':
                    assert _rgb(cell) == row['gap_colors'][operator].lstrip('#')
    summary_total_row = len(summary_table.rows) - 1
    assert summary_table.cell(summary_total_row, 0).text == 'Total'
    for operator_index, operator in enumerate(summary_view['operators'], 3):
        expected = summary_view['expanded_total']['gaps'][operator]
        cell = summary_table.cell(summary_total_row, operator_index)
        if expected is None:
            assert cell.text == 'N/A'
        else:
            assert float(cell.text) == pytest.approx(expected, abs=.0051)

    chart_shapes = [chart for slide in presentation.slides for chart in _charts_on_slide(slide)]
    assert len(chart_shapes) == 3
    best_network_chart = chart_shapes[0]
    assert best_network_chart.chart_type == XL_CHART_TYPE.COLUMN_STACKED
    assert best_network_chart.has_legend
    assert best_network_chart.legend.position == XL_LEGEND_POSITION.TOP
    best_series = {series.name: series for series in best_network_chart.series}
    metric_by_code = {metric['code']: metric for metric in result['configuration']['metrics']}
    family_source_kinds = {'Voice': {'voice', 'speech'}, 'Data': {'data'}}
    for operator_index, operator in enumerate(MAPPED_OPERATOR_ORDER):
        voice_series = best_series[f'Voice · {operator}']
        data_series = best_series[operator]
        for family, series in (('Voice', voice_series), ('Data', data_series)):
            expected_points = sum(
                row['weighted_points'] for row in result['scoring']
                if row['operator'] == operator
                and metric_by_code[row['kpi_code']]['source_kind'] in family_source_kinds[family]
            )
            expected_values = [None] * len(MAPPED_OPERATOR_ORDER)
            expected_values[operator_index] = expected_points
            _assert_sparse_series_values(series, expected_values)
        assert _series_color(voice_series) == _voice_tint(MAPPED_OPERATOR_COLORS[operator])
        assert _series_color(data_series) == MAPPED_OPERATOR_COLORS[operator].lstrip('#').upper()
    total_series = best_series['Total']
    assert list(total_series.values) == pytest.approx([
        sum(row['weighted_points'] for row in result['scoring'] if row['operator'] == operator)
        for operator in MAPPED_OPERATOR_ORDER
    ])
    assert _legend_visible_series_names(best_network_chart) == list(MAPPED_OPERATOR_ORDER)
    line_plot = best_network_chart._chartSpace.chart.plotArea.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}lineChart')
    assert line_plot.find('.//{http://schemas.openxmlformats.org/drawingml/2006/chart}dLblPos').get('val') == 't'
    assert line_plot.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}noFill') is not None
    assert chart_shapes[1].chart_type == XL_CHART_TYPE.DOUGHNUT
    donut = chart_shapes[1]
    assert [category.label for category in donut.plots[0].categories] == ['Voice', 'Data']
    expected_family_maximums = [
        sum(metric['contexts']['DriveCity']['max_points']
            for metric in result['configuration']['metrics']
            if metric['source_kind'] in family_source_kinds[family])
        for family in ('Voice', 'Data')
    ]
    assert list(donut.series[0].values) == pytest.approx(expected_family_maximums)
    assert donut.plots[0].vary_by_categories
    assert donut.plots[0].has_data_labels
    assert donut._chartSpace.xpath('.//c:doughnutChart//c:showCatName[@val="1"]')
    assert donut._chartSpace.xpath('.//c:doughnutChart//c:showVal[@val="1"]')
    assert [str(point.format.fill.fore_color.rgb) for point in donut.series[0].points] == [
        'E6A81D', '176E77',
    ]
    best_network_slide = next(slide for slide in presentation.slides
                              if slide.shapes.title.text.split('\n')[0] == 'Scoring & GAP Analysis — Best Network')
    best_network_text = _slide_text(best_network_slide)
    assert '650.00' in best_network_text and 'pts' in best_network_text
    assert 'Configured maximum' not in best_network_text
    assert 'Available totals:' not in best_network_text
    assert 'Voice: lighter operator color' not in best_network_text
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
    assert chart.legend.include_in_layout is False
    assert chart.value_axis.maximum_scale > max(value for series in chart.series for value in series.values if value is not None)
    flat_chart_slide = next(slide for slide, title in zip(presentation.slides, titles) if title == 'Scoring Chart')
    flat_chart_group = next(shape for shape in flat_chart_slide.shapes
                            if shape.name == 'Scoring Chart With Category Key')
    flat_chart_shape = next(shape for shape in flat_chart_group.shapes if shape.has_chart)
    _assert_category_shade_bar(flat_chart_group, flat_chart_shape, categories)
    reference_bottom = table.cell(0, operator_columns['EE'])._tc.get_or_add_tcPr().find('{http://schemas.openxmlformats.org/drawingml/2006/main}lnB')
    assert int(reference_bottom.get('w')) > 4500
    assert reference_bottom.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr').get('val') == \
        MAPPED_OPERATOR_COLORS['EE'].lstrip('#').upper()

    assert 'UK_Q2_2026' in '\n'.join(_slide_text(slide) for slide in presentation.slides)
    visible = '\n'.join(_slide_text(slide) for slide in presentation.slides)
    assert all(warning not in visible for warning in WARNINGS)
    assert all(all(warning in slide.notes_slide.notes_text_frame.text for warning in WARNINGS)
               for slide in presentation.slides)


def test_powerpoint_keeps_many_operators_in_one_comparison_table():
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

    assert len(matrices) == 1
    counts = Counter()
    for table in matrices:
        operator_columns = _operator_columns(table)
        assert len(operator_columns) == len(operators)
        assert 'EE' in operator_columns
        assert len(table.rows) == len(METRICS) + len({metric['category'] for metric in METRICS}) + 2
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
    charts = [shape.chart for slide in presentation.slides for shape in _nested_shapes(slide.shapes) if shape.has_chart]
    scoring_charts = [chart for chart in charts if chart.chart_type == XL_CHART_TYPE.COLUMN_CLUSTERED]
    assert len(scoring_charts) == 1
    assert [series.name for series in scoring_charts[0].series] == mapped_order
    assert {series.name: str(series.format.fill.fore_color.rgb) for series in scoring_charts[0].series} == {
        operator: colors[operator].lstrip('#').upper() for operator in mapped_order}


def test_powerpoint_empty_result_stays_readable_and_keeps_warnings_in_notes():
    empty_warning = 'No source data was available for this job.'
    presentation = _export(
        {'scoring': [], 'totals': [], 'warnings': [empty_warning]}, environment='all',
    )
    visible = '\n'.join(_slide_text(slide) for slide in presentation.slides)

    assert 'No scoring measurements are available' in visible
    assert empty_warning not in visible
    assert not _comparison_matrices(presentation)
    assert not any(shape.has_chart for slide in presentation.slides for shape in _nested_shapes(slide.shapes))
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


def test_intro_slides_show_all_canonical_scope_filters_without_overlapping_campaigns():
    job_fields = {
        'context_filters': {
            'Region': ['North', 'South'],
            'City': [],
            'Operator': ['O2 UK'],
            'Vendor': [],
            'Campaign': ['UK_Q2_2026', 'UK_Q3_2026'],
        },
    }
    presentation = _export(_result(), job_fields=job_fields)
    for index in (0, 1):
        slide = presentation.slides[index]
        text = _slide_text(slide)
        assert 'Region: North, South' in text
        assert 'City: All' in text
        assert 'Operator: O2 UK' in text
        assert 'Vendor: All' in text
        assert 'Campaign: UK_Q2_2026, UK_Q3_2026' in text
        assert 'Campaigns: UK_Q2_2026' in text
        ordered_labels = [
            'Operator: O2 UK', 'Vendor: All', 'Region: North, South', 'City: All',
            'Campaign: UK_Q2_2026, UK_Q3_2026',
        ]
        assert [text.index(label) for label in ordered_labels] == sorted(
            text.index(label) for label in ordered_labels
        )
        campaign_shape = next(shape for shape in slide.shapes if shape.name == 'Scoring Campaigns')
        if index == 0:
            subtitle_shape = next(
                shape for shape in slide.placeholders if shape.placeholder_format.type == 4
            )
        else:
            subtitle_shape = next(
                shape for shape in slide.placeholders if shape.placeholder_format.type in {1, 3}
            )
        assert subtitle_shape.left > 0
        assert subtitle_shape.top > 0
        assert subtitle_shape.width > Inches(9)
        assert subtitle_shape.top + subtitle_shape.height <= campaign_shape.top


def test_intro_scope_filters_follow_saved_aggregation_hierarchy_order():
    fields = ['Campaign', 'City', 'Vendor', 'Operator', 'Region']
    job_fields = {
        'aggregation_hierarchy': fields,
        'context_filters': {
            'Operator': ['O2 UK'], 'Vendor': ['Telefonica'], 'Region': ['North'],
            'City': ['London'], 'Campaign': ['UK_Q2_2026'],
        },
    }
    presentation = _export(_result(), job_fields=job_fields)
    expected = [
        'Campaign: UK_Q2_2026', 'City: London', 'Vendor: Telefonica',
        'Operator: O2 UK', 'Region: North',
    ]
    for index in (0, 1):
        text = _slide_text(presentation.slides[index])
        assert [text.index(label) for label in expected] == sorted(
            text.index(label) for label in expected
        )


def test_multilevel_hierarchy_export_uses_editable_nested_tables_and_one_chart_per_environment():
    base_result = _result()
    contexts = [
        ('North', 'UK_Q2_2026', False),
        ('North', 'UK_Q3_2026', False),
        ('South', 'UK_Q2_2026', False),
        ('South', 'UK_Q3_2026', True),
    ]
    scoring_rows = []
    for region, campaign, omit_baseline in contexts:
        for row in base_result['scoring']:
            if omit_baseline and row['operator'] == 'EE':
                continue
            scoring_rows.append({**row, 'region': region, 'campaign': campaign})
    result = {
        'aggregation_contract_version': 2,
        'aggregation_levels': ['Operator', 'Region', 'Campaign'],
        'scoring': scoring_rows,
        'totals': [],
        'configuration': scoring_configuration(),
        'warnings': [],
    }
    presentation = _export(
        result,
        operator_mapping_groups=_mapping_groups(),
        job_fields={
            'aggregation_contract_version': 2,
            'aggregation_levels': ['Operator', 'Region', 'Campaign'],
            'campaigns': ['UK_Q2_2026', 'UK_Q3_2026'],
        },
    )
    titles = [slide.shapes.title.text.split('\n')[0] for slide in presentation.slides]
    assert titles.count('Scoring Chart') == 1
    best_network_slide = next(slide for slide, title in zip(presentation.slides, titles)
                              if title == 'Scoring & GAP Analysis — Best Network')
    assert best_network_slide.shapes.title.text == \
        'Scoring & GAP Analysis — Best Network\nEnvironment: DriveCity'
    best_network_chart, donut = _charts_on_slide(best_network_slide)
    best_network_categories = best_network_chart.plots[0].categories
    assert best_network_categories.depth == 3
    best_paths = best_network_categories.flattened_labels
    assert ('EE', 'North', 'UK_Q2_2026') in best_paths
    assert not re.search(r'\b(?:Operator|Vendor|Region|City|Campaign):', _slide_text(best_network_slide))
    metric_by_code = {metric['code']: metric for metric in result['configuration']['metrics']}
    family_source_kinds = {'Voice': {'voice', 'speech'}, 'Data': {'data'}}
    best_series = {series.name: series for series in best_network_chart.series}
    for operator in MAPPED_OPERATOR_ORDER:
        for family in ('Voice', 'Data'):
            series = best_series[f'Voice · {operator}' if family == 'Voice' else operator]
            expected = []
            for path in best_paths:
                if path[0] != operator:
                    expected.append(None)
                    continue
                matching = [
                    row for row in scoring_rows
                    if row['operator'] == operator and row['region'] == path[1]
                    and row['campaign'] == path[2]
                    and metric_by_code[row['kpi_code']]['source_kind'] in family_source_kinds[family]
                ]
                expected.append(sum(row['weighted_points'] for row in matching) if matching else None)
            _assert_sparse_series_values(series, expected)
            expected_color = MAPPED_OPERATOR_COLORS[operator].lstrip('#').upper()
            if family == 'Voice':
                expected_color = _voice_tint(MAPPED_OPERATOR_COLORS[operator])
            assert _series_color(series) == expected_color
    expected_best_total = []
    for path in best_paths:
        matching = [row for row in scoring_rows if row['operator'] == path[0]
                    and row['region'] == path[1] and row['campaign'] == path[2]]
        expected_best_total.append(sum(row['weighted_points'] for row in matching) if matching else None)
    _assert_sparse_series_values(best_series['Total'], expected_best_total)
    assert _legend_visible_series_names(best_network_chart) == list(MAPPED_OPERATOR_ORDER)
    assert best_network_chart.legend.position == XL_LEGEND_POSITION.TOP
    assert best_network_chart._chartSpace.xpath('.//c:barChart/c:ser/c:dPt') == []

    expected_family_maximums = [
        sum(metric['contexts']['DriveCity']['max_points']
            for metric in result['configuration']['metrics']
            if metric['source_kind'] in family_source_kinds[family])
        for family in ('Voice', 'Data')
    ]
    assert [category.label for category in donut.plots[0].categories] == ['Voice', 'Data']
    assert list(donut.series[0].values) == pytest.approx(expected_family_maximums)
    assert donut.plots[0].vary_by_categories and donut.plots[0].has_data_labels
    assert donut._chartSpace.xpath('.//c:doughnutChart//c:showCatName[@val="1"]')
    assert donut._chartSpace.xpath('.//c:doughnutChart//c:showVal[@val="1"]')
    assert [str(point.format.fill.fore_color.rgb) for point in donut.series[0].points] == [
        'E6A81D', '176E77',
    ]
    best_network_text = _slide_text(best_network_slide)
    assert '650.00' in best_network_text and 'pts' in best_network_text
    assert 'Configured maximum' not in best_network_text
    assert 'Available totals:' not in best_network_text
    assert 'Voice: lighter operator color' not in best_network_text

    chart_slide = next(slide for slide, title in zip(presentation.slides, titles) if title == 'Scoring Chart')
    assert chart_slide.shapes.title.text == 'Scoring Chart\nEnvironment: DriveCity'
    chart_group = next(shape for shape in chart_slide.shapes
                       if shape.name == 'Scoring Chart With Category Key')
    chart_shape = next(shape for shape in chart_group.shapes if shape.has_chart)
    chart = chart_shape.chart
    assert chart.has_legend
    assert chart.legend.position == XL_LEGEND_POSITION.TOP
    assert chart.legend.include_in_layout is False
    chart_categories = chart.plots[0].categories
    assert chart_categories.depth == 3
    chart_paths = chart_categories.flattened_labels
    assert ('EE', 'North', 'UK_Q2_2026') in chart_paths
    assert all(not re.search(r'\b(?:Operator|Vendor|Region|City|Campaign):', label)
               for path in chart_paths for label in path)
    categories = list(dict.fromkeys(row['category'] for row in scoring_rows))
    chart_series = {series.name: series for series in chart.series}
    for operator in MAPPED_OPERATOR_ORDER:
        for category_index, category in enumerate(categories):
            name = operator if category_index == 0 else f'{operator} · {category}'
            series = chart_series[name]
            expected = []
            for path in chart_paths:
                if path[0] != operator:
                    expected.append(None)
                    continue
                matching = [
                    row for row in scoring_rows
                    if row['operator'] == operator and row['region'] == path[1]
                    and row['campaign'] == path[2] and row['category'] == category
                ]
                expected.append(sum(row['weighted_points'] for row in matching) if matching else None)
            _assert_sparse_series_values(series, expected)
            expected_color = _hierarchy_chart_color(
                MAPPED_OPERATOR_COLORS[operator], category_index, len(categories),
            ).lstrip('#').upper()
            assert _series_color(series) == expected_color
    assert _legend_visible_series_names(chart) == list(MAPPED_OPERATOR_ORDER)
    assert chart._chartSpace.xpath('.//c:barChart/c:ser/c:dPt') == []
    stacked_totals = [
        sum(series.values[index] or 0 for series in chart.series)
        for index in range(len(chart.series[0].values))
    ]
    assert chart.value_axis.maximum_scale >= max(stacked_totals)
    for index, path in enumerate(chart_paths):
        expected_total = sum(
            row['weighted_points'] for row in scoring_rows
            if row['operator'] == path[0] and row['region'] == path[1] and row['campaign'] == path[2]
        )
        assert stacked_totals[index] == pytest.approx(expected_total)
    assert not chart._chartSpace.xpath('.//a:ln//a:srgbClr[@val="FFFF00"]')
    assert not best_network_chart._chartSpace.xpath('.//a:ln//a:srgbClr[@val="FFFF00"]')
    assert not any(shape.name == 'Hierarchy Operator Legend' for shape in chart_slide.shapes)
    _assert_category_shade_bar(chart_group, chart_shape, categories)
    score_slides = [slide for slide, title in zip(presentation.slides, titles) if title == 'Scoring Table']
    gap_slides = [slide for slide, title in zip(presentation.slides, titles)
                  if title.startswith('GAP Analysis —')]
    assert score_slides and gap_slides
    assert len(score_slides) == 1
    score_table = next(shape.table for shape in score_slides[0].shapes if shape.has_table)
    assert len(score_table.rows) == 5 + len(METRICS) + len({metric['category'] for metric in METRICS}) + 1
    assert len(score_table.columns) == 4 + 15 + 12
    export_views = build_scoring_views(
        {
            'aggregation_contract_version': 2,
            'aggregation_levels': ['Operator', 'Region', 'Campaign'],
            'baseline_operator': 'EE',
            'campaigns': ['UK_Q2_2026', 'UK_Q3_2026'],
            'configuration': scoring_configuration(),
        },
        result,
        operator_mapping_groups=_mapping_groups(),
    )
    for row_index, row in enumerate(export_views['hierarchy_score_tables'][0]['expanded_rows'], 5):
        if row.get('row_type') == 'category':
            _assert_gray_category_row(score_table, row_index)
    for row in list(score_table.rows)[5:]:
        for cell in list(row.cells)[4:]:
            assert cell.text_frame.paragraphs[0].font.size.pt <= row.height.pt
    score_table_shape = next(shape for shape in score_slides[0].shapes if shape.has_table)
    hierarchy_legend = next(shape for shape in score_slides[0].shapes
                            if shape.has_table and shape.top == Inches(1.25))
    assert hierarchy_legend.top + hierarchy_legend.height < score_table_shape.top
    assert hierarchy_legend.left == Inches(6.8)
    all_gap_slides = [slide for slide, title in zip(presentation.slides, titles)
                      if title == 'GAP Analysis — All vs EE']
    individual_gap_slides = [
        slide for slide, title in zip(presentation.slides, titles)
        if title.startswith('GAP Analysis —') and title != 'GAP Analysis — All vs EE'
    ]
    assert max(presentation.slides.index(slide) for slide in all_gap_slides) < min(
        presentation.slides.index(slide) for slide in individual_gap_slides
    )
    assert len(all_gap_slides) == 1
    all_gap_tables = [next(shape.table for shape in slide.shapes if shape.has_table)
                      for slide in all_gap_slides]
    assert len(all_gap_tables[0].rows) == 4 + len(METRICS) + len({metric['category'] for metric in METRICS}) + 1
    assert len(all_gap_tables[0].columns) == 3 + 3 * len(contexts)
    for table in all_gap_tables:
        for row_index, row in enumerate(export_views['hierarchy_gap_tables'][0]['expanded_rows'], 4):
            if row.get('row_type') == 'category':
                _assert_gray_category_row(table, row_index)
    assert not any(cell.text == 'EE' for table in all_gap_tables
                   for row in table.rows for cell in row.cells)
    assert len(individual_gap_slides) == 3
    for slide in individual_gap_slides:
        operator_gap_table = next(shape.table for shape in slide.shapes if shape.has_table)
        assert len(operator_gap_table.rows) == 4 + len(METRICS) + len({metric['category'] for metric in METRICS}) + 1
        assert len(operator_gap_table.columns) == 3 + len(contexts)
        header_text = '\n'.join(cell.text for row in list(operator_gap_table.rows)[:4] for cell in row.cells)
        assert 'North' in header_text and 'South' in header_text
        assert 'UK_Q2_2026' in header_text and 'UK_Q3_2026' in header_text
        assert not re.search(r'\b(?:Operator|Vendor|Region|City|Campaign):', header_text)
        gap_header = operator_gap_table.rows[len(['Operator', 'Region', 'Campaign'])]
        assert all(cell.text == 'GAP' for cell in list(gap_header.cells)[3:])
    assert any(_charts_on_slide(slide) for slide, title in zip(presentation.slides, titles)
               if title == 'Scoring Chart')
    assert any(
        cell.is_merge_origin and cell.span_width > 1 and cell.text in MAPPED_OPERATOR_ORDER
        for slide in score_slides
        for shape in slide.shapes if shape.has_table
        for row in shape.table.rows
        for cell in row.cells
    )
    assert all(any(shape.has_table for shape in slide.shapes) for slide in score_slides + gap_slides)
    hierarchy_text = '\n'.join(_slide_text(slide) for slide in score_slides + gap_slides)
    assert 'UK_Q2_2026' in hierarchy_text
    assert 'South' in hierarchy_text
    assert not re.search(r'\b(?:Operator|Vendor|Region|City|Campaign):', hierarchy_text)


def test_unselected_campaign_stays_metadata_without_becoming_a_hierarchy_header():
    result = _result()
    result['aggregation_contract_version'] = 2
    result['aggregation_levels'] = ['Operator', 'Region']
    result['campaigns'] = ['UK_Q2_2026']
    for row in result['scoring']:
        row['campaign'] = None
    job_fields = {
        'aggregation_contract_version': 2,
        'aggregation_levels': ['Operator', 'Region'],
        'campaigns': ['UK_Q2_2026'],
    }
    job = {
        'aggregation_contract_version': 2,
        'aggregation_levels': ['Operator', 'Region'],
        'baseline_operator': 'EE',
        'configuration': scoring_configuration(),
        **job_fields,
    }
    views = build_scoring_views(job, result, _mapping_groups())
    matrix = views['hierarchy_score_tables'][0]
    assert matrix['context'] == {'environment': 'DriveCity'}
    assert all('Campaign' not in {item['level'] for item in column['path']}
               for column in matrix['hierarchy_columns'])

    presentation = _export(result, operator_mapping_groups=_mapping_groups(), job_fields=job_fields)
    intro_text = '\n'.join(_slide_text(presentation.slides[index]) for index in (0, 1))
    assert 'Campaigns: UK_Q2_2026' in intro_text
