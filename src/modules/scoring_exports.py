"""Reference-style editable scoring matrices using the existing CDR master."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from src.modules.cdr_reporting import (
    _named_slide_layout, _remove_all_slides, _set_slide_header,
    _set_structural_slide_text,
)
from src.modules.scoring_views import build_scoring_views

_FONT = 'Ericsson Hilda'
_WHITE = '#FFFFFF'
_NEUTRAL = '#ECEFF1'
_SCOPE_FILTER_FIELDS = ('Region', 'City', 'Operator', 'Vendor', 'Campaign')


def _number(value: Any) -> str:
    if value is None:
        return 'N/A'
    formatted = f'{float(value):.2f}'
    return '0.00' if formatted == '-0.00' else formatted


def _scope(context: dict[str, Any]) -> str:
    return ' · '.join(f'{key.replace("_", " ").title()}: {value}' for key, value in context.items()
                      if value is not None and str(value).strip())


def _slide(presentation, title: str, subtitle: str):
    layout = _named_slide_layout(presentation, 'Title Only')
    if layout is None:
        raise ValueError("The PowerPoint template needs a 'Title Only' layout.")
    slide = presentation.slides.add_slide(layout)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(255, 255, 255)
    _set_slide_header(slide, title, subtitle)
    if slide.shapes.title is not None:
        for paragraph in slide.shapes.title.text_frame.paragraphs:
            paragraph.font.color.rgb = RGBColor.from_string('17232D')
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor.from_string('17232D')
        for paragraph in slide.shapes.title.text_frame.paragraphs[1:]:
            paragraph.font.size = Pt(12)
            for run in paragraph.runs:
                run.font.size = Pt(12)
    return slide


def _text(slide, text: str, top: float, *, left: float = .55, width: float = 12.2,
          height: float = .4, size: float = 10, color: str = '#263746', align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    box.text_frame.word_wrap = True
    box.text_frame.margin_top = box.text_frame.margin_bottom = 0
    box.text_frame.margin_left = box.text_frame.margin_right = 0
    box.text = text
    for paragraph in box.text_frame.paragraphs:
        paragraph.font.name = _FONT
        paragraph.font.size = Pt(size)
        paragraph.font.color.rgb = RGBColor.from_string(color.lstrip('#'))
        paragraph.alignment = align
    return box


def _cell(cell, text: str, *, color: str = _WHITE, foreground: str = '#17232D',
          size: float = 9, bold: bool = False, left: bool = False) -> None:
    cell.text = text
    cell.margin_left = cell.margin_right = Inches(.025)
    cell.margin_top = cell.margin_bottom = 0
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    cell.fill.solid()
    cell.fill.fore_color.rgb = RGBColor.from_string(color.lstrip('#'))
    for paragraph in cell.text_frame.paragraphs:
        paragraph.font.name = _FONT
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = RGBColor.from_string(foreground.lstrip('#'))
        paragraph.alignment = PP_ALIGN.LEFT if left else PP_ALIGN.CENTER
        paragraph.line_spacing = 1.0
        paragraph.space_before = paragraph.space_after = 0
    properties = cell._tc.get_or_add_tcPr()
    for edge in ('lnL', 'lnR', 'lnT', 'lnB'):
        line = OxmlElement(f'a:{edge}')
        line.set('w', '4500')
        fill = OxmlElement('a:solidFill')
        rgb = OxmlElement('a:srgbClr')
        rgb.set('val', '65717A')
        fill.append(rgb)
        line.append(fill)
        properties.append(line)


def _operator_color(matrix: dict, operator: str) -> str:
    return matrix.get('operator_styles', {}).get(operator, {}).get('color', '#365F91')


def _operator_label(matrix: dict, operator: str) -> str:
    return matrix.get('operator_styles', {}).get(operator, {}).get('label', operator)


def _campaigns_for_export(job: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Prefer campaign values in scored contexts over the selected-source union."""
    campaigns: list[str] = []

    def collect(value: Any) -> None:
        if value is None:
            return
        label = str(value).strip()
        if label and label.casefold() not in {item.casefold() for item in campaigns}:
            campaigns.append(label)

    for key in ('scoring', 'score_rows', 'totals', 'charts'):
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            campaign = next((value for field, value in row.items()
                             if str(field).casefold() in {'campaign', 'period', 'quarter'} and value is not None), None)
            collect(campaign)
    if campaigns:
        return sorted(campaigns, key=str.casefold)

    source_metadata = job.get('source_metadata', [])
    if isinstance(source_metadata, dict):
        source_metadata = source_metadata.get('sources', [])
    if isinstance(source_metadata, list):
        for source in source_metadata:
            if not isinstance(source, dict):
                continue
            source_campaigns = source.get('campaigns', [])
            for campaign in source_campaigns if isinstance(source_campaigns, list) else [source_campaigns]:
                collect(campaign)
    if not campaigns:
        fallback = job.get('campaigns', [])
        for campaign in fallback if isinstance(fallback, list) else [fallback]:
            collect(campaign)
    return sorted(campaigns, key=str.casefold)


def _filter_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ', '.join(str(item).strip() for item in value if item is not None and str(item).strip())
    return str(value).strip() if value is not None else ''


def _canonical_scope_filter_labels(payload: Any) -> list[str] | None:
    if not isinstance(payload, dict) or any(not isinstance(value, list) for value in payload.values()):
        return None
    normalized = {str(key).strip().casefold(): value for key, value in payload.items()}
    if payload and not any(field.casefold() in normalized for field in _SCOPE_FILTER_FIELDS):
        return None
    return [
        f'{field}: {_filter_value(normalized.get(field.casefold(), [])) or "All"}'
        for field in _SCOPE_FILTER_FIELDS
    ]


def _context_filter_labels(job: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    reserved = {'period', 'quarter', 'nr mode', 'aggregation', 'aggregation level', 'baseline'}

    def append(label: Any, value: Any, operator: Any = None) -> None:
        name = str(label or '').strip().replace('_', ' ')
        rendered_value = _filter_value(value)
        if not name or not rendered_value or name.casefold() in reserved:
            return
        formatted_name = ' '.join(
            part.upper() if part.casefold() == 'ran' else part.capitalize() for part in name.split()
        )
        description = f'{formatted_name} {operator} {rendered_value}' if operator else f'{formatted_name}: {rendered_value}'
        identity = description.casefold()
        if identity not in seen:
            seen.add(identity)
            labels.append(description)

    for payload_name in ('context_filters', 'filters'):
        payload = job.get(payload_name)
        if isinstance(payload, dict):
            canonical_labels = _canonical_scope_filter_labels(payload) if payload_name == 'context_filters' else None
            if canonical_labels is not None:
                for label in canonical_labels:
                    append(*label.split(': ', 1))
                continue
            if any(key in payload for key in ('column', 'field', 'name', 'key')):
                field = payload.get('column') or payload.get('field') or payload.get('name') or payload.get('key')
                append(field, payload.get('value', payload.get('values')), payload.get('operator'))
            else:
                for name, value in payload.items():
                    if isinstance(value, dict):
                        append(name, value.get('value', value.get('values')), value.get('operator'))
                    else:
                        append(name, value)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    field = item.get('column') or item.get('field') or item.get('name') or item.get('key')
                    append(field, item.get('value', item.get('values')), item.get('operator'))
                elif isinstance(item, str) and item.strip() and item.casefold() not in seen:
                    seen.add(item.casefold())
                    labels.append(item.strip())
        elif isinstance(payload, str) and payload.strip() and payload.casefold() not in seen:
            seen.add(payload.casefold())
            labels.append(payload.strip())
    return labels


def _scoring_filter_subtitle(job: dict[str, Any]) -> str:
    parts: list[str] = []
    nr_mode = str(job.get('nr_mode') or '').strip()
    if nr_mode:
        parts.append(f'NR Mode: {nr_mode}')
    levels = job.get('aggregation_levels') or job.get('levels') or []
    if isinstance(levels, str):
        levels = [levels]
    level_labels = [str(level).strip() for level in levels if str(level).strip()] if isinstance(levels, list) else []
    if level_labels:
        parts.append(f'Aggregation: {", ".join(level_labels)}')
    baseline = str(job.get('baseline_operator') or job.get('baseline') or '').strip()
    if baseline:
        parts.append(f'Baseline: {baseline}')
    filter_labels = _context_filter_labels(job)
    canonical_labels = _canonical_scope_filter_labels(job.get('context_filters'))
    if canonical_labels is not None:
        canonical_set = {label.casefold() for label in canonical_labels}
        other_labels = [label for label in filter_labels if label.casefold() not in canonical_set]
        filter_groups = [canonical_labels[index:index + 2] for index in range(0, len(canonical_labels), 2)]
        subtitle_lines = [' · '.join(parts)] if parts else []
        subtitle_lines.extend(' · '.join(group) for group in filter_groups)
        if other_labels:
            subtitle_lines.append(' · '.join(other_labels))
        return '\n'.join(subtitle_lines)
    parts.extend(filter_labels)
    return ' · '.join(parts)


def _fit_scoring_intro_subtitle(slide, layout_name: str) -> None:
    title_shape = next(
        (shape for shape in slide.placeholders if shape.placeholder_format.type in {1, 3}),
        None,
    )
    if title_shape is None:
        return
    subtitle_shape = next(
        (shape for shape in slide.placeholders if shape.placeholder_format.type == 4),
        None,
    )
    if layout_name == 'Title Page' and subtitle_shape is not None:
        _set_shape_geometry(subtitle_shape, Inches(1.08))
        subtitle_shape.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        paragraphs = subtitle_shape.text_frame.paragraphs
    else:
        _set_shape_geometry(title_shape, Inches(1.38))
        paragraphs = title_shape.text_frame.paragraphs[1:]
        title_paragraphs = title_shape.text_frame.paragraphs[:1]
        for paragraph in title_paragraphs:
            paragraph.font.size = Pt(30)
            for run in paragraph.runs:
                run.font.size = Pt(30)
    for paragraph in paragraphs:
        paragraph.font.size = Pt(12)
        paragraph.line_spacing = 1.0
        paragraph.space_before = Pt(2)
        paragraph.space_after = Pt(0)
        for run in paragraph.runs:
            run.font.size = Pt(12)


def _set_shape_geometry(shape, height: int) -> None:
    """Materialize inherited placeholder geometry before resizing its height."""
    left, top, width = shape.left, shape.top, shape.width
    shape.left = left
    shape.top = top
    shape.width = width
    shape.height = height


def _add_scoring_intro_slides(presentation, job: dict[str, Any], result: dict[str, Any]) -> None:
    title = 'Scoring & GAP Analysis'
    subtitle = _scoring_filter_subtitle(job)
    campaigns = _campaigns_for_export(job, result)
    campaign_text = f'Campaigns: {", ".join(campaigns) if campaigns else "Not available"}'
    for layout_name, top in (('Title Page', 5.92), ('Title Only', 1.98)):
        layout = _named_slide_layout(presentation, layout_name)
        if layout is None:
            raise ValueError(f"The PowerPoint template needs a '{layout_name}' layout for scoring exports.")
        slide = presentation.slides.add_slide(layout)
        _set_structural_slide_text(slide, title, subtitle)
        if '\n' in subtitle:
            _fit_scoring_intro_subtitle(slide, layout_name)
        campaign_shape = _text(slide, campaign_text, top, left=.52, width=10.68, height=.7,
                               size=14, color=_WHITE)
        campaign_shape.name = 'Scoring Campaigns'


def _header_foreground(color: str) -> str:
    red, green, blue = (int(color.lstrip('#')[index:index + 2], 16) for index in (0, 2, 4))
    return '#17232D' if .299 * red + .587 * green + .114 * blue > 155 else _WHITE


def _operator_pages(table: dict) -> list[list[str]]:
    operators = table['operators']
    baseline = table['baseline_operator']
    if len(operators) <= 5:
        return [operators]
    if baseline in operators:
        compared = [operator for operator in operators if operator != baseline]
        return [[operator for operator in operators if operator in compared[start:start + 4] or operator == baseline]
                for start in range(0, len(compared), 4)]
    return [operators[start:start + 5] for start in range(0, len(operators), 5)]


def _score_tables(presentation, matrices: list[dict], legend: list[dict]) -> None:
    for matrix in matrices:
        metric_pages = [matrix['rows'][start:start + 32] for start in range(0, len(matrix['rows']), 32)]
        for operators in _operator_pages(matrix):
            baseline = matrix['baseline_operator']
            comparisons = [name for name in operators if name != baseline] if baseline in matrix['operators'] else []
            for page_index, metrics in enumerate(metric_pages):
                page_label = f' · KPIs {page_index + 1}/{len(metric_pages)}' if len(metric_pages) > 1 else ''
                slide = _slide(presentation, 'Scoring Tables', _scope(matrix['context']) + page_label)
                include_total = page_index == len(metric_pages) - 1
                headers = ['NETCHECK KPIs', 'KPI', 'Score weight\n(%)', 'Max score',
                           *[_operator_label(matrix, name) for name in operators],
                           *[f'GAP {_operator_label(matrix, name)}\n− {_operator_label(matrix, baseline)}' for name in comparisons]]
                count = len(metrics) + 1 + int(include_total)
                table = slide.shapes.add_table(count, len(headers), Inches(.55), Inches(1.55),
                                               presentation.slide_width - Inches(1.1), Inches(5.2)).table
                widths = [1.22, 3.02, .68, .79]
                remaining = (presentation.slide_width / 914400 - 1.1 - sum(widths)) / max(1, len(headers) - 4)
                for index, column in enumerate(table.columns):
                    column.width = Inches(widths[index] if index < 4 else remaining)
                table.rows[0].height = Inches(.46)
                for row in list(table.rows)[1:]:
                    row.height = Inches((5.2 - .46) / max(1, count - 1))
                colors = [_WHITE, _WHITE, '#4EA72E', '#FF0000',
                          *[_operator_color(matrix, name) for name in operators], *['#FFFF00'] * len(comparisons)]
                for index, header in enumerate(headers):
                    _cell(table.cell(0, index), header, color=colors[index],
                          foreground=_header_foreground(colors[index]), size=8.5, bold=True)
                if baseline in operators:
                    reference_cell = table.cell(0, 4 + operators.index(baseline))
                    reference_line = reference_cell._tc.get_or_add_tcPr().find('{http://schemas.openxmlformats.org/drawingml/2006/main}lnT')
                    reference_line.set('w', '38100')
                    reference_line.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr').set('val', 'FFFF00')
                for row_index, metric in enumerate(metrics, 1):
                    _cell(table.cell(row_index, 0), metric['category'], size=8, left=True)
                    _cell(table.cell(row_index, 1), metric['kpi'], color='#E7E8E9', bold=True, left=True, size=8.5)
                    _cell(table.cell(row_index, 2), _number(metric['weight_percent']) + '%')
                    _cell(table.cell(row_index, 3), _number(metric['max_points']))
                    for offset, operator in enumerate(operators, 4):
                        value = metric['values'][operator]
                        partial = value['points'] is not None and not value['complete']
                        _cell(table.cell(row_index, offset), _number(value['points']) + ('*' if partial else ''),
                              color=value.get('color', _WHITE if value['complete'] else _NEUTRAL))
                    for offset, operator in enumerate(comparisons, 4 + len(operators)):
                        _cell(table.cell(row_index, offset), _number(metric['gaps'].get(operator)),
                              color=metric.get('gap_colors', {}).get(operator, '#FFF0D8'), bold=True)
                first = 0
                while first < len(metrics):
                    last = first
                    while last + 1 < len(metrics) and metrics[last + 1]['category'] == metrics[first]['category']:
                        last += 1
                    if last > first:
                        cell = table.cell(first + 1, 0)
                        cell.merge(table.cell(last + 1, 0))
                        _cell(cell, metrics[first]['category'], size=8.5, left=True)
                    first = last + 1
                if include_total:
                    total = matrix['total']
                    index = count - 1
                    _cell(table.cell(index, 0), 'TOTAL', color='#D8DFE4', bold=True, left=True)
                    _cell(table.cell(index, 1), 'Available points; * incomplete coverage', color='#D8DFE4', size=8, left=True)
                    for column, value in ((2, _number(total['weight_percent']) + '%'), (3, _number(total['max_points']))):
                        _cell(table.cell(index, column), value, color='#D8DFE4', bold=True)
                    for column, operator in enumerate(operators, 4):
                        value = total['values'][operator]
                        _cell(table.cell(index, column), _number(value['points']) + ('*' if value['points'] is not None and not value['complete'] else ''),
                              color='#D8DFE4', bold=True)
                    for column, operator in enumerate(comparisons, 4 + len(operators)):
                        _cell(table.cell(index, column), _number(total['gaps'].get(operator)), color='#D8DFE4', bold=True)
                # A native legend keeps the same threshold colors as the web view.
                for index, item in enumerate(legend):
                    legend_table = slide.shapes.add_table(1, 1, Inches(.55 + index * 1.15), Inches(7.02), Inches(1.1), Inches(.18)).table
                    _cell(legend_table.cell(0, 0), item.get('band', ''), color=item['color'], size=8)
                _text(slide, f'GAP = operator − reference; ±{matrix.get("gap_scale_max", 0):.2f} points; green + / red −',
                      7.03, left=6.5, width=6.2, size=8.5, height=.18)
                _text(slide, matrix['coverage_note'], 7.27, size=8, height=.18)


def _format_chart(chart, *, maximum: float, labels=XL_DATA_LABEL_POSITION.OUTSIDE_END) -> None:
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = True
    chart.legend.font.name = _FONT
    chart.legend.font.size = Pt(11)
    for axis in (chart.category_axis, chart.value_axis):
        axis.tick_labels.font.name = _FONT
        axis.tick_labels.font.size = Pt(10)
    chart.value_axis.minimum_scale = 0
    chart.value_axis.maximum_scale = max(1, maximum) * 1.12
    chart.plots[0].has_data_labels = True
    data_labels = chart.plots[0].data_labels
    data_labels.position = labels
    data_labels.number_format = '0.0'
    data_labels.font.name = _FONT
    data_labels.font.size = Pt(9)


def _charts(presentation, matrices: list[dict]) -> None:
    for matrix in matrices:
        slide = _slide(presentation, 'Scoring Chart', _scope(matrix['context']))
        categories = list(dict.fromkeys(row['category'] for row in matrix['rows']))
        data = CategoryChartData()
        data.categories = categories
        maximum = 0.0
        for operator in matrix['operators']:
            values = []
            for category in categories:
                cells = [row['values'][operator] for row in matrix['rows'] if row['category'] == category]
                available = [cell['points'] for cell in cells if cell['points'] is not None]
                value = sum(available) if available else None
                values.append(value)
                maximum = max(maximum, value or 0)
            data.add_series(_operator_label(matrix, operator), values)
        chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(.7), Inches(1.65),
                                        presentation.slide_width - Inches(1.4), Inches(4.95), data).chart
        _format_chart(chart, maximum=maximum)
        for series, operator in zip(chart.series, matrix['operators']):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = RGBColor.from_string(_operator_color(matrix, operator).lstrip('#'))
        _text(slide, matrix['coverage_note'], 6.95, size=9)


def _best_network(presentation, matrices: list[dict]) -> None:
    voice_categories = {'CLASSIC CALLS', 'WHATSAPP CALLS', 'MULTI RAB'}
    for matrix in matrices:
        slide = _slide(presentation, 'Scoring & GAP Analysis — Best Network', _scope(matrix['context']))
        operators = matrix['operators']
        data = CategoryChartData()
        data.categories = [_operator_label(matrix, operator) for operator in operators]
        maximums = []
        for family in ('Voice', 'Data'):
            metrics = [row for row in matrix['rows'] if (row['category'] in voice_categories) == (family == 'Voice')]
            maximums.append(sum(row['max_points'] or 0 for row in metrics))
            values = []
            for operator in operators:
                available = [row['values'][operator]['points'] for row in metrics if row['values'][operator]['points'] is not None]
                values.append(sum(available) if available else None)
            data.add_series(family, values)
        totals = [sum(value for series in data if (value := series.values[index]) is not None)
                  if any(series.values[index] is not None for series in data) else None
                  for index in range(len(operators))]
        data.add_series('Total', totals)
        chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, Inches(.65), Inches(1.75),
                                        Inches(8.65), Inches(4.75), data).chart
        _format_chart(chart, maximum=matrix['total']['max_points'], labels=XL_DATA_LABEL_POSITION.CENTER)
        for series_index, series in enumerate(list(chart.series)[:2]):
            for operator_index, operator in enumerate(operators):
                color = _operator_color(matrix, operator).lstrip('#')
                channels = [int(color[index:index + 2], 16) for index in (0, 2, 4)]
                if series_index == 0:
                    channels = [round(channel + (255 - channel) * .45) for channel in channels]
                point = series.points[operator_index]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = RGBColor(*channels)
        _add_total_labels(chart)
        chart.has_legend = False
        _text(slide, 'Voice: lighter operator color · Data: solid operator color', 6.5, left=.8, width=8.3, size=10)
        _text(slide, 'Available totals: ' + ' · '.join(
            f'{_operator_label(matrix, operator)} {_number(matrix["total"]["values"][operator]["points"])}'
            + ('*' if not matrix['total']['values'][operator]['complete'] else '') for operator in operators),
            1.4, left=.8, width=8.4, height=.3, size=10)
        donut_data = CategoryChartData()
        donut_data.categories = ['Voice', 'Data']
        donut_data.add_series('Maximum ranking points', maximums)
        donut = slide.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, Inches(9.5), Inches(3), Inches(3.2), Inches(3.2), donut_data).chart
        donut.has_title = False
        donut.plots[0].hole_size = 65
        donut.has_legend = True
        donut.legend.position = XL_LEGEND_POSITION.BOTTOM
        donut.legend.font.size = Pt(11)
        for point, color in zip(donut.series[0].points, ('E6A81D', '176E77')):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = RGBColor.from_string(color)
        _text(slide, f'{matrix["total"]["max_points"]:.2f}\npts', 4.1, left=10.3, width=1.6, height=.7, size=15, align=PP_ALIGN.CENTER)
        _text(slide, f'Configured maximum\nVoice: {maximums[0]:.2f} pts\nData: {maximums[1]:.2f} pts',
              1.85, left=9.7, width=3, height=1.1, size=13)
        _text(slide, matrix['coverage_note'], 7.03, size=9, height=.35)


def _add_total_labels(chart) -> None:
    """Overlay an invisible native line series with labels at each stacked total."""
    plot_area = chart._chartSpace.chart.plotArea
    bar_plot = plot_area.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}barChart')
    series = bar_plot.findall('{http://schemas.openxmlformats.org/drawingml/2006/chart}ser')[-1]
    bar_plot.remove(series)
    for element in list(series):
        if element.tag.endswith('}invertIfNegative'):
            series.remove(element)
    shape_properties = OxmlElement('c:spPr')
    line = OxmlElement('a:ln')
    line.append(OxmlElement('a:noFill'))
    shape_properties.append(line)
    series.insert(3, shape_properties)
    marker = OxmlElement('c:marker')
    symbol = OxmlElement('c:symbol')
    symbol.set('val', 'none')
    marker.append(symbol)
    series.insert(4, marker)
    line_plot = OxmlElement('c:lineChart')
    grouping = OxmlElement('c:grouping')
    grouping.set('val', 'standard')
    line_plot.extend([grouping, series])
    labels = deepcopy(bar_plot.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}dLbls'))
    labels.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}dLblPos').set('val', 't')
    line_plot.append(labels)
    for axis_id in bar_plot.findall('{http://schemas.openxmlformats.org/drawingml/2006/chart}axId'):
        line_plot.append(deepcopy(axis_id))
    plot_area.insert(plot_area.index(bar_plot) + 1, line_plot)


def _gap_summary_tables(presentation, matrices: list[dict]) -> None:
    """Export the combined comparison before individual operator GAP slides."""
    for matrix in matrices:
        operators = matrix['operators']
        pages = [matrix['rows'][offset:offset + 32] for offset in range(0, len(matrix['rows']), 32)] or [[]]
        for page_index, rows in enumerate(pages):
            page_label = f' · Page {page_index + 1}/{len(pages)}' if len(pages) > 1 else ''
            reference = _operator_label(matrix, matrix['baseline_operator'])
            slide = _slide(presentation, 'GAP Analysis — All vs ' + reference, _scope(matrix['context']) + page_label)
            table = slide.shapes.add_table(len(rows) + 2, len(operators) + 3, Inches(.65), Inches(1.65),
                                           Inches(12.03), Inches(.43 + .148 * (len(rows) + 1))).table
            widths = [1.45, 4.05, 1.1] + [5.43 / max(1, len(operators))] * len(operators)
            for column, width in zip(table.columns, widths):
                column.width = Inches(width)
            headers = ['Category', 'NETCHECK KPIs', 'Type of KPI'] + [
                f'{_operator_label(matrix, operator)} − {reference}' for operator in operators]
            table.rows[0].height = Inches(.43)
            for index, header in enumerate(headers):
                _cell(table.cell(0, index), header, color='#FFFF00' if index >= 3 else '#0084FF',
                      foreground='#17232D' if index >= 3 else _WHITE, size=10, bold=True)
            for index, row in enumerate(rows, 1):
                table.rows[index].height = Inches(.148)
                _cell(table.cell(index, 0), row['category'], color='#0084FF', foreground=_WHITE, size=8, bold=True)
                _cell(table.cell(index, 1), row['kpi'], color='#E6ECFA', size=8.5, left=True)
                _cell(table.cell(index, 2), row['kpi_type'], color='#D8EFCA' if row['kpi_type'] == 'Reliable' else '#E6ECFA', size=8)
                for column, operator in enumerate(operators, 3):
                    _cell(table.cell(index, column), _number(row['gaps'][operator]),
                          color=row['gap_colors'][operator], size=9, bold=True)
            total_index = len(rows) + 1
            table.rows[total_index].height = Inches(.148)
            for index, text in enumerate(['Total', 'Weighted score GAP', ''] + [
                    _number(matrix['total']['gaps'][operator]) for operator in operators]):
                _cell(table.cell(total_index, index), text, color='#E4E9EC', size=9, bold=True, left=index == 1)
            _text(slide, matrix['note'], 7.12, height=.25, size=9)


def _gap_tables(presentation, matrices: list[dict]) -> None:
    for matrix in matrices:
        pages = [matrix['rows'][offset:offset + 32] for offset in range(0, len(matrix['rows']), 32)] or [[]]
        for page_index, rows in enumerate(pages):
            page_label = f' · Page {page_index + 1}/{len(pages)}' if len(pages) > 1 else ''
            subtitle = f'{_operator_label(matrix, matrix["operator"])} vs {_operator_label(matrix, matrix["baseline_operator"])} · {_scope(matrix["context"])}{page_label}'
            slide = _slide(presentation, 'GAP Analysis', subtitle)
            if not rows:
                _text(slide, 'No comparable KPI gaps are available. See the scoring matrix for missing values.', 1.8, height=1, size=16)
                continue
            table = slide.shapes.add_table(len(rows) + 1, 4, Inches(.65), Inches(1.65), Inches(9.3),
                                           Inches(.43 + .158 * len(rows))).table
            for column, width in zip(table.columns, (1.65, 4.45, 1.5, 1.7)):
                column.width = Inches(width)
            table.rows[0].height = Inches(.43)
            headers = ['Category', 'NETCHECK KPIs', f'GAP operator −\n{_operator_label(matrix, matrix["baseline_operator"])}', 'Type of KPI']
            for index, header in enumerate(headers):
                _cell(table.cell(0, index), header, color='#FFFF00' if index == 2 else '#0084FF',
                      foreground='#17232D' if index == 2 else _WHITE, size=11, bold=True)
            for index, row in enumerate(rows, 1):
                table.rows[index].height = Inches(.158)
                _cell(table.cell(index, 0), row['category'], color='#0084FF', foreground=_WHITE, size=8, bold=True)
                _cell(table.cell(index, 1), row['kpi'], color='#E6ECFA', size=8.5, left=True)
                _cell(table.cell(index, 2), _number(row['gap_points']), color=row.get('gap_color', '#FFFF80'), size=8.5, bold=True)
                _cell(table.cell(index, 3), row['kpi_type'], color='#D8EFCA' if row['kpi_type'] == 'Reliable' else '#E6ECFA', size=8.5)
            signed_total = sum(row['gap_points'] for row in matrix['rows'])
            _text(slide, f'KPI prioritization\n\nAvailable GAP: {signed_total:.2f} points\n\nOperator − reference\nGreen: positive\nRed: negative\n\n{matrix["note"]}',
                  1.8, left=10.2, width=2.5, height=3.9, size=13)
            _text(slide, 'KPI types and priority follow this job’s saved workspace configuration.', 6.85, size=10)


def export_scoring_powerpoint(job: dict[str, Any], result: dict[str, Any], template_path: Path,
                             operator_mapping_groups: list[dict[str, Any]] | None = None) -> bytes:
    """Export saved points as comparison matrices, charts and prioritized gaps."""
    if not template_path.is_file():
        raise ValueError('The configured CDR PowerPoint template is missing.')
    presentation = Presentation(template_path)
    _remove_all_slides(presentation)
    views = build_scoring_views(job, result, operator_mapping_groups)
    _add_scoring_intro_slides(presentation, job, result)
    levels = job.get('aggregation_levels') or job.get('levels') or ['Operator']
    subtitle = ', '.join(levels)
    matrices = views['score_tables']
    if matrices:
        for matrix in matrices:
            _best_network(presentation, [matrix])
            _charts(presentation, [matrix])
            _score_tables(presentation, [matrix], views.get('threshold_legend', []))
            _gap_summary_tables(presentation, [table for table in views['gap_summary_tables'] if table['context'] == matrix['context']])
            _gap_tables(presentation, [table for table in views['gap_tables'] if table['context'] == matrix['context']])
    else:
        slide = _slide(presentation, 'Scoring Tables', subtitle)
        _text(slide, 'No scoring measurements are available for this saved job.', 1.8, height=1, size=16)
    for slide in presentation.slides:
        slide.notes_slide.notes_text_frame.text = '\n'.join(str(warning) for warning in result.get('warnings', []))
    output = BytesIO()
    presentation.save(output)
    return output.getvalue()
