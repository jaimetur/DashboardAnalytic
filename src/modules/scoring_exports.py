"""Reference-style editable scoring matrices using the existing CDR master."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from math import ceil
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
from src.modules.scoring_views import THRESHOLD_COLORS, build_scoring_views

_FONT = 'Ericsson Hilda'
_WHITE = '#FFFFFF'
_NEUTRAL = '#ECEFF1'
_SCOPE_FILTER_FIELDS = ('Operator', 'Vendor', 'Region', 'City', 'Campaign')


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


def _scope_filter_fields(job: dict[str, Any]) -> tuple[str, ...]:
    configured = job.get('aggregation_hierarchy')
    if not isinstance(configured, list):
        configuration = job.get('configuration')
        configured = configuration.get('aggregation_hierarchy') if isinstance(configuration, dict) else None
    if not isinstance(configured, list):
        return _SCOPE_FILTER_FIELDS
    canonical = {field.casefold(): field for field in _SCOPE_FILTER_FIELDS}
    fields = []
    for value in configured:
        field = canonical.get(str(value).strip().casefold())
        if field and field not in fields:
            fields.append(field)
    fields.extend(field for field in _SCOPE_FILTER_FIELDS if field not in fields)
    return tuple(fields)


def _canonical_scope_filter_labels(payload: Any, fields: tuple[str, ...] = _SCOPE_FILTER_FIELDS) -> list[str] | None:
    if not isinstance(payload, dict) or any(not isinstance(value, list) for value in payload.values()):
        return None
    normalized = {str(key).strip().casefold(): value for key, value in payload.items()}
    if payload and not any(field.casefold() in normalized for field in fields):
        return None
    return [
        f'{field}: {_filter_value(normalized.get(field.casefold(), [])) or "All"}'
        for field in fields
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
            canonical_labels = (
                _canonical_scope_filter_labels(payload, _scope_filter_fields(job))
                if payload_name == 'context_filters' else None
            )
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
    canonical_labels = _canonical_scope_filter_labels(
        job.get('context_filters'), _scope_filter_fields(job),
    )
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
        hierarchy_columns = matrix.get('hierarchy_columns', [])
        if hierarchy_columns:
            _add_hierarchy_chart_categories(data, hierarchy_columns)
            hierarchy_labels = {column['id']: _hierarchy_display_path(column) for column in hierarchy_columns}
        else:
            data.categories = [_operator_label(matrix, operator) for operator in operators]
            hierarchy_labels = {}
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
        if hierarchy_columns:
            chart.category_axis.tick_labels.font.size = Pt(
                min(7, max(5, 38 / max(1, len(operators)) ** .5))
            )
        for series_index, series in enumerate(list(chart.series)[:2]):
            for operator_index, operator in enumerate(operators):
                color = _operator_color(matrix, operator).lstrip('#')
                channels = [int(color[index:index + 2], 16) for index in (0, 2, 4)]
                if series_index == 0:
                    channels = [round(channel + (255 - channel) * .45) for channel in channels]
                point = series.points[operator_index]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = RGBColor(*channels)
                if matrix.get('operator_styles', {}).get(operator, {}).get('is_reference'):
                    point.format.line.color.rgb = RGBColor.from_string('FFFF00')
                    point.format.line.width = Pt(2)
        _add_total_labels(chart)
        chart.has_legend = False
        _text(slide, 'Voice: lighter operator color · Data: solid operator color', 6.5, left=.8, width=8.3, size=10)
        _text(slide, 'Available totals: ' + ' · '.join(
            f'{hierarchy_labels.get(operator, _operator_label(matrix, operator))} '
            f'{_number(matrix["total"]["values"][operator]["points"])}'
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


def _hierarchy_chart(presentation, matrix: dict) -> None:
    columns = matrix.get('hierarchy_columns', [])
    slide = _slide(presentation, 'Scoring Chart', _scope(matrix['context']))
    data = CategoryChartData()
    _add_hierarchy_chart_categories(data, columns)
    categories = list(dict.fromkeys(row['category'] for row in matrix['rows']))
    stacked_values: list[list[float | None]] = []
    for category in categories:
        values = []
        for column in columns:
            cells = [row['values'][column['id']] for row in matrix['rows'] if row['category'] == category]
            available = [cell['points'] for cell in cells if cell['points'] is not None]
            value = sum(available) if available else None
            values.append(value)
        stacked_values.append(values)
        data.add_series(str(category), values)

    maximum = max(
        (sum(value or 0 for value in column_values) for column_values in zip(*stacked_values)),
        default=0.0,
    )
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_STACKED, Inches(.55), Inches(1.92),
        presentation.slide_width - Inches(1.1), Inches(4.48), data,
    ).chart
    _format_chart(chart, maximum=maximum, labels=XL_DATA_LABEL_POSITION.CENTER)
    chart.has_legend = False
    chart.category_axis.tick_labels.font.size = Pt(min(7, max(5, 38 / max(1, len(columns)) ** .5)))
    for category_index, series in enumerate(chart.series):
        for column_index, column in enumerate(columns):
            point = series.points[column_index]
            color = _hierarchy_chart_color(column['color'], category_index)
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = RGBColor.from_string(color.lstrip('#'))
            if column['is_reference']:
                point.format.line.color.rgb = RGBColor.from_string('FFFF00')
                point.format.line.width = Pt(1.5)
    operator_entries = {}
    for column in columns:
        operator_entries.setdefault(column['operator'], column)
    legend_shape = slide.shapes.add_table(1, max(1, len(operator_entries)), Inches(.55), Inches(1.62),
                                          presentation.slide_width - Inches(1.1), Inches(.22))
    legend_shape.name = 'Hierarchy Operator Legend'
    legend = legend_shape.table
    for index, (operator, column) in enumerate(operator_entries.items()):
        label = f'{operator} (Reference)' if column['is_reference'] else operator
        _cell(legend.cell(0, index), label, color=column['color'],
              foreground=_header_foreground(column['color']), size=8, bold=True)
    category_note = 'Stacked KPI categories: ' + ' · '.join(str(category) for category in categories)
    _text(slide, category_note, 6.48, size=8, height=.18)
    _text(slide, matrix['coverage_note'], 6.69, size=8, height=.2)


def _hierarchy_chart_color(color: str, category_index: int) -> str:
    """Use lighter shades of each operator color to distinguish stacked KPI groups."""
    channels = [int(color.lstrip('#')[index:index + 2], 16) for index in (0, 2, 4)]
    tint = min(.42, category_index * .1)
    return '#{:02X}{:02X}{:02X}'.format(*(round(channel + (255 - channel) * tint) for channel in channels))


def _wrapped_line_count(text: Any, width_inches: float, font_size: float) -> int:
    capacity = max(1, int((width_inches * 72 - 3.6) / max(.1, font_size * .65)))
    lines = 1
    used = 0
    for word in str(text or '').split():
        word_length = len(word)
        if used and used + 1 + word_length > capacity:
            lines += 1
            used = 0
        if word_length > capacity:
            extra_lines = ceil(word_length / capacity) - 1
            lines += extra_lines
            used = word_length % capacity
        else:
            used += (1 if used else 0) + word_length
    return lines


def _hierarchy_metric_layout(metrics: list[dict], total_label: str, *, available_height: float,
                             kpi_width: float) -> tuple[float, list[float]]:
    texts = [str(row.get('kpi', '')) for row in metrics] + [total_label]
    font_size = min(7.5, max(5.0, available_height * 72 / max(1, len(texts)) * .82))
    line_counts = [_wrapped_line_count(text, kpi_width, font_size) for text in texts]
    for _ in range(3):
        base_height = available_height / max(1, sum(line_counts))
        font_size = min(7.5, max(5.0, base_height * 72 * .82))
        updated = [_wrapped_line_count(text, kpi_width, font_size) for text in texts]
        if updated == line_counts:
            break
        line_counts = updated
    base_height = available_height / max(1, sum(line_counts))
    return font_size, [base_height * lines for lines in line_counts]


def _hierarchy_content_font(texts: list[str], width_inches: float, *, maximum: float = 7.5) -> float:
    glyph_units = {
        '.': .28, '-': .4, '+': .48, '*': .36,
    }
    widest = max(
        (sum(glyph_units.get(char, .56 if char.isdigit() else .52) for char in str(text)) for text in texts),
        default=1.0,
    )
    usable_width = max(1.0, width_inches * 72 - 3.6)
    return min(maximum, max(2.5, usable_width / max(1.0, widest)))


def _add_hierarchy_chart_categories(data: CategoryChartData, columns: list[dict]) -> None:
    """Build native multi-level chart categories from hierarchy values."""
    nodes = {}
    for column in columns:
        parent = None
        prefix = ()
        for item in column.get('path', []):
            value = 'Not specified' if item.get('value') is None else str(item['value'])
            prefix += (value,)
            if prefix in nodes:
                parent = nodes[prefix]
                continue
            node = data.add_category(value) if parent is None else parent.add_sub_category(value)
            nodes[prefix] = node
            parent = node


def _hierarchy_display_path(column: dict) -> str:
    return ' · '.join(
        'Not specified' if item.get('value') is None else str(item['value'])
        for item in column.get('path', [])
    )


def _hierarchy_header_groups(table, columns: list[dict], levels: list[str], *, start_col: int,
                             leaf_width: int, header_rows: int, physical_column_width: float,
                             leaf_label: str = 'Score') -> None:
    for level_index, level in enumerate(levels):
        start = 0
        while start < len(columns):
            representative = columns[start]
            prefix = tuple((entry['level'], entry.get('value')) for entry in representative['path'][:level_index + 1])
            end = start
            while end + 1 < len(columns):
                next_prefix = tuple(
                    (entry['level'], entry.get('value')) for entry in columns[end + 1]['path'][:level_index + 1]
                )
                if next_prefix != prefix:
                    break
                end += 1
            left_column = start_col + start * leaf_width
            right_column = start_col + (end + 1) * leaf_width - 1
            cell = table.cell(level_index, left_column)
            if right_column > left_column:
                cell.merge(table.cell(level_index, right_column))
            value = representative['path'][level_index].get('value')
            label = value if value is not None else 'Not specified'
            color = representative['color'] if level == 'Operator' else '#E6ECFA'
            header_size = min(7.5, max(5.0, physical_column_width * leaf_width
                                      * (end - start + 1) * 12))
            _cell(cell, str(label), color=color, foreground=_header_foreground(color), size=header_size, bold=True)
            if level == 'Operator' and all(item['is_reference'] for item in columns[start:end + 1]):
                _yellow_top_border(cell)
            start = end + 1
    subheader_row = len(levels)
    for column_index, column in enumerate(columns):
        color = column['color']
        leaf_font_size = min(7.5, max(5.0, physical_column_width * 12))
        _cell(table.cell(subheader_row, start_col + column_index * leaf_width), leaf_label,
              color=color, foreground=_header_foreground(color), size=leaf_font_size, bold=True)
        if leaf_width == 2:
            _cell(table.cell(subheader_row, start_col + column_index * leaf_width + 1), 'GAP',
                  color='#FFFF00', foreground='#17232D', size=leaf_font_size, bold=True)
        if column['is_reference']:
            _yellow_top_border(table.cell(subheader_row, start_col + column_index * leaf_width))


def _yellow_top_border(cell) -> None:
    properties = cell._tc.get_or_add_tcPr()
    line = properties.find('{http://schemas.openxmlformats.org/drawingml/2006/main}lnT')
    if line is None:
        line = OxmlElement('a:lnT')
        properties.append(line)
    line.set('w', '38100')
    fill = line.find('{http://schemas.openxmlformats.org/drawingml/2006/main}solidFill')
    if fill is None:
        fill = OxmlElement('a:solidFill')
        line.append(fill)
    rgb = fill.find('{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr')
    if rgb is None:
        rgb = OxmlElement('a:srgbClr')
        fill.append(rgb)
    rgb.set('val', 'FFFF00')


def _hierarchy_score_tables(presentation, matrices: list[dict], legend: list[dict]) -> None:
    for matrix in matrices:
        columns = matrix['hierarchy_columns']
        levels = matrix['hierarchy_levels']
        metrics = matrix['rows']
        slide = _slide(presentation, 'Scoring Tables', _scope(matrix['context']))
        header_rows = len(levels) + 1
        row_count = header_rows + len(metrics) + 1
        table_height = 5.0
        table_width = presentation.slide_width / 914400 - 1.1
        fixed_widths = [0.9, 2.35, 0.47, 0.52]
        table = slide.shapes.add_table(row_count, 4 + 2 * len(columns), Inches(.55), Inches(1.5),
                                       Inches(table_width), Inches(table_height)).table
        leaf_width = (table_width - sum(fixed_widths)) / max(1, 2 * len(columns))
        for index, column in enumerate(table.columns):
            column.width = Inches(fixed_widths[index] if index < 4 else leaf_width)
        header_level_height = min(.25, 1.05 / max(1, len(levels)))
        subheader_height = .25
        for row_index in range(len(levels)):
            table.rows[row_index].height = Inches(header_level_height)
        table.rows[len(levels)].height = Inches(subheader_height)
        available_body_height = table_height - header_level_height * len(levels) - subheader_height
        metric_font, body_heights = _hierarchy_metric_layout(
            metrics, 'Available points; * incomplete coverage',
            available_height=available_body_height, kpi_width=fixed_widths[1],
        )
        for row_index, row_height in enumerate(body_heights, header_rows):
            table.rows[row_index].height = Inches(row_height)
        _hierarchy_header_groups(table, columns, levels, start_col=4, leaf_width=2,
                                 header_rows=header_rows, physical_column_width=leaf_width)
        static_headers = [('Category', '#0084FF'), ('KPI', '#0084FF'), ('Score weight\n(%)', '#4EA72E'), ('Max score', '#FF0000')]
        for index, (label, color) in enumerate(static_headers):
            cell = table.cell(0, index)
            if header_rows > 1:
                cell.merge(table.cell(header_rows - 1, index))
            _cell(cell, label, color=color, foreground=_header_foreground(color), size=7, bold=True)
        data_font = min(7, metric_font)
        total = matrix['total']
        score_texts = []
        gap_texts = []
        for metric in metrics:
            for column in columns:
                leaf_id = column['id']
                value = metric['values'][leaf_id]
                score_texts.append(_number(value['points']) + ('*' if value['points'] is not None and not value['complete'] else ''))
                gap_texts.append(_number(metric['gaps'].get(leaf_id)))
        for column in columns:
            leaf_id = column['id']
            value = total['values'][leaf_id]
            score_texts.append(_number(value['points']) + ('*' if value['points'] is not None and not value['complete'] else ''))
            gap_texts.append(_number(total['gaps'].get(leaf_id)))
        score_font = _hierarchy_content_font(score_texts, leaf_width)
        gap_font = _hierarchy_content_font(gap_texts, leaf_width)
        for row_offset, metric in enumerate(metrics, header_rows):
            _cell(table.cell(row_offset, 0), metric['category'], size=data_font, left=True)
            _cell(table.cell(row_offset, 1), metric['kpi'], color='#E7E8E9', bold=True, left=True, size=metric_font)
            _cell(table.cell(row_offset, 2), _number(metric['weight_percent']) + '%', size=data_font)
            _cell(table.cell(row_offset, 3), _number(metric['max_points']), size=data_font)
            for column_index, column in enumerate(columns):
                leaf_id = column['id']
                value = metric['values'][leaf_id]
                partial = value['points'] is not None and not value['complete']
                _cell(table.cell(row_offset, 4 + 2 * column_index),
                      _number(value['points']) + ('*' if partial else ''),
                      color=value.get('color', _NEUTRAL), size=score_font)
                _cell(table.cell(row_offset, 5 + 2 * column_index), _number(metric['gaps'].get(leaf_id)),
                      color=metric.get('gap_colors', {}).get(leaf_id, '#FFF0D8'), size=gap_font, bold=True)
        total_index = row_count - 1
        _cell(table.cell(total_index, 0), 'TOTAL', color='#D8DFE4', bold=True, left=True, size=data_font)
        _cell(table.cell(total_index, 1), 'Available points; * incomplete coverage',
              color='#D8DFE4', size=metric_font, left=True)
        _cell(table.cell(total_index, 2), _number(total['weight_percent']) + '%', color='#D8DFE4', size=data_font, bold=True)
        _cell(table.cell(total_index, 3), _number(total['max_points']), color='#D8DFE4', size=data_font, bold=True)
        for column_index, column in enumerate(columns):
            leaf_id = column['id']
            value = total['values'][leaf_id]
            _cell(table.cell(total_index, 4 + 2 * column_index),
                  _number(value['points']) + ('*' if value['points'] is not None and not value['complete'] else ''),
                  color='#D8DFE4', size=score_font, bold=True)
            _cell(table.cell(total_index, 5 + 2 * column_index), _number(total['gaps'].get(leaf_id)),
                  color='#D8DFE4', size=gap_font, bold=True)
        _merge_category_cells(table, metrics, header_rows)
        for index, item in enumerate(legend):
            legend_table = slide.shapes.add_table(
                1, 1, Inches(6.8 + index * 1.15), Inches(1.25), Inches(1.1), Inches(.18),
            ).table
            _cell(legend_table.cell(0, 0), item.get('band', ''), color=item['color'], size=8)
        _text(slide, matrix['coverage_note'], 7.27, size=8, height=.18)


def _merge_category_cells(table, metrics: list[dict], start_row: int) -> None:
    first = 0
    while first < len(metrics):
        last = first
        while last + 1 < len(metrics) and metrics[last + 1]['category'] == metrics[first]['category']:
            last += 1
        if last > first:
            cell = table.cell(start_row + first, 0)
            cell.merge(table.cell(start_row + last, 0))
            _cell(cell, metrics[first]['category'], size=8.5, left=True)
        first = last + 1


def _hierarchy_gap_projection(matrix: dict, columns: list[dict]) -> dict:
    """Keep a selected set of leaves in a hierarchy GAP view."""
    projected = deepcopy(matrix)
    leaf_ids = [column['id'] for column in columns]
    projected['hierarchy_columns'] = deepcopy(columns)
    projected['operators'] = leaf_ids
    projected['operator_styles'] = {
        leaf_id: projected['operator_styles'][leaf_id]
        for leaf_id in leaf_ids if leaf_id in projected.get('operator_styles', {})
    }
    projected['rows'] = [
        row | {
            'gaps': {leaf_id: row.get('gaps', {}).get(leaf_id) for leaf_id in leaf_ids},
            'gap_colors': {leaf_id: row.get('gap_colors', {}).get(leaf_id, THRESHOLD_COLORS['Unavailable'])
                           for leaf_id in leaf_ids},
        }
        for row in projected.get('rows', [])
    ]
    projected['total'] = {
        'gaps': {leaf_id: matrix.get('total', {}).get('gaps', {}).get(leaf_id) for leaf_id in leaf_ids},
    }
    return projected


def _hierarchy_gap_tables(presentation, matrices: list[dict], *, title: str = 'GAP Analysis — All vs reference') -> None:
    for matrix in matrices:
        columns = matrix['hierarchy_columns']
        levels = matrix['hierarchy_levels']
        metrics = matrix['rows']
        slide = _slide(presentation, title, _scope(matrix['context']))
        header_rows = len(levels) + 1
        row_count = header_rows + len(metrics) + 1
        table_height = 5.0
        table_width = 12.03
        fixed_widths = [1.0, 2.55, .7]
        table = slide.shapes.add_table(row_count, 3 + len(columns), Inches(.65), Inches(1.55),
                                       Inches(table_width), Inches(table_height)).table
        leaf_width = (table_width - sum(fixed_widths)) / max(1, len(columns))
        for index, column in enumerate(table.columns):
            column.width = Inches(fixed_widths[index] if index < 3 else leaf_width)
        header_level_height = min(.25, 1.05 / max(1, len(levels)))
        subheader_height = .25
        for row_index in range(len(levels)):
            table.rows[row_index].height = Inches(header_level_height)
        table.rows[len(levels)].height = Inches(subheader_height)
        available_body_height = table_height - header_level_height * len(levels) - subheader_height
        metric_font, body_heights = _hierarchy_metric_layout(
            metrics, 'Weighted score GAP', available_height=available_body_height,
            kpi_width=fixed_widths[1],
        )
        for row_index, row_height in enumerate(body_heights, header_rows):
            table.rows[row_index].height = Inches(row_height)
        _hierarchy_header_groups(table, columns, levels, start_col=3, leaf_width=1,
                                 header_rows=header_rows, physical_column_width=leaf_width,
                                 leaf_label='GAP')
        data_font = min(7, metric_font)
        for index, (label, color) in enumerate((('Category', '#0084FF'), ('KPI', '#0084FF'), ('Type of KPI', '#0084FF'))):
            cell = table.cell(0, index)
            if header_rows > 1:
                cell.merge(table.cell(header_rows - 1, index))
            _cell(cell, label, color=color, foreground=_WHITE, size=7, bold=True)
        gap_texts = [
            _number(row['gaps'].get(column['id']))
            for row in metrics for column in columns
        ] + [_number(matrix['total']['gaps'].get(column['id'])) for column in columns]
        leaf_font = _hierarchy_content_font(gap_texts, leaf_width)
        for row_offset, row in enumerate(metrics, header_rows):
            _cell(table.cell(row_offset, 0), row['category'], color='#0084FF', foreground=_WHITE, size=data_font, bold=True)
            _cell(table.cell(row_offset, 1), row['kpi'], color='#E6ECFA', size=metric_font, left=True)
            _cell(table.cell(row_offset, 2), row['kpi_type'], color='#D8EFCA' if row['kpi_type'] == 'Reliable' else '#E6ECFA', size=data_font)
            for column_index, column in enumerate(columns, 3):
                leaf_id = column['id']
                _cell(table.cell(row_offset, column_index), _number(row['gaps'].get(leaf_id)),
                      color=row['gap_colors'].get(leaf_id, THRESHOLD_COLORS['Unavailable']), size=leaf_font, bold=True)
        total_index = row_count - 1
        total_gaps = matrix['total']['gaps']
        for index, label in enumerate(('Total', 'Weighted score GAP', '')):
            _cell(table.cell(total_index, index), label, color='#E4E9EC', size=data_font, bold=True, left=index == 1)
        for column_index, column in enumerate(columns, 3):
            _cell(table.cell(total_index, column_index), _number(total_gaps.get(column['id'])),
                  color='#E4E9EC', size=leaf_font, bold=True)
        _merge_category_cells(table, metrics, header_rows)
        _text(slide, matrix['note'], 7.05, height=.25, size=9)


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
    hierarchy_matrices = views.get('hierarchy_score_tables', [])
    use_hierarchy = bool(hierarchy_matrices) and len(hierarchy_matrices[0].get('hierarchy_levels', [])) > 1
    if use_hierarchy:
        gap_by_environment = {
            matrix['context'].get('environment'): matrix
            for matrix in views.get('hierarchy_gap_tables', [])
        }
        export_gap_matrices = []
        for matrix in hierarchy_matrices:
            _best_network(presentation, [matrix])
            _hierarchy_chart(presentation, matrix)
            _hierarchy_score_tables(presentation, [matrix], views.get('threshold_legend', []))
            gap_matrix = gap_by_environment.get(matrix['context'].get('environment'))
            if gap_matrix is not None:
                export_gap_matrices.append(gap_matrix)
        # Export every combined comparison before the operator-specific views.
        for gap_matrix in export_gap_matrices:
            reference = _operator_label(gap_matrix, gap_matrix['baseline_operator'])
            compared_columns = [column for column in gap_matrix['hierarchy_columns']
                                if not column.get('is_reference')]
            if compared_columns:
                all_matrix = _hierarchy_gap_projection(gap_matrix, compared_columns)
                _hierarchy_gap_tables(
                    presentation, [all_matrix], title=f'GAP Analysis — All vs {reference}',
                )
        for gap_matrix in export_gap_matrices:
            reference = _operator_label(gap_matrix, gap_matrix['baseline_operator'])
            compared_operators = dict.fromkeys(
                column['operator'] for column in gap_matrix['hierarchy_columns']
                if not column.get('is_reference')
            )
            for operator in compared_operators:
                operator_columns = [column for column in gap_matrix['hierarchy_columns']
                                    if column['operator'] == operator]
                operator_matrix = _hierarchy_gap_projection(gap_matrix, operator_columns)
                _hierarchy_gap_tables(
                    presentation, [operator_matrix],
                    title=f'GAP Analysis — {operator} vs {reference}',
                )
    elif matrices:
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
