"""Editable maximum-allocation doughnuts used in Scoring PowerPoint exports."""
from __future__ import annotations

import math
from typing import Any

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt


_VOICE_SHADES = ('E6A81D', 'D39C22', 'F0C75E', 'B98115', 'F4D477')
_DATA_SHADES = ('176E77', '29958F', '61B4A6', '0F5B62', '83CFC1')


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def _metric_source_kind(metric: dict[str, Any]) -> str:
    source_kind = metric.get('source_kind')
    if source_kind in (None, '') and isinstance(metric.get('calculation'), dict):
        source_kind = metric['calculation'].get('source_kind')
    return str(source_kind or '').strip().casefold()


def maximum_allocations_from_configuration(
    configuration: dict[str, Any] | None,
) -> dict[str, dict[str, float]]:
    """Return per-environment Voice/Data maximum points from configured KPI maxima.

    Each metric is counted once per environment. Leaf columns and result rows are
    deliberately ignored so the allocation cannot multiply with the hierarchy.
    """
    if not isinstance(configuration, dict):
        return {}
    scope = configuration.get('scope')
    environments = scope.get('environments') if isinstance(scope, dict) else None
    metrics = configuration.get('metrics')
    if not isinstance(environments, dict) or not isinstance(metrics, list):
        return {}

    allocations: dict[str, dict[str, float]] = {}
    for environment, details in environments.items():
        if not isinstance(details, dict) or _number(details.get('total_points')) <= 0:
            continue
        name = str(environment).strip()
        if name:
            allocations[name] = {'voice': 0.0, 'data': 0.0, 'max': 0.0}

    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        kind = _metric_source_kind(metric)
        family = 'voice' if kind in {'voice', 'speech'} else 'data' if kind == 'data' else None
        if family is None:
            continue
        contexts = metric.get('contexts')
        if not isinstance(contexts, dict):
            continue
        for environment, allocation in allocations.items():
            context = contexts.get(environment)
            if isinstance(context, dict):
                allocation[family] += _number(context.get('max_points'))
    for allocation in allocations.values():
        allocation['max'] = allocation['voice'] + allocation['data']
    return allocations


def _selected_allocations(
    matrix: dict[str, Any], environment_allocations: dict[str, dict[str, Any]],
) -> list[tuple[str, float, float]]:
    context = matrix.get('context')
    environment = str(context.get('environment') or '').strip() if isinstance(context, dict) else ''
    if environment.casefold() in {'combined', 'all', 'all environments', 'allenvironments'}:
        selected = list(environment_allocations.items())
    else:
        match = next((name for name in environment_allocations
                      if name.casefold() == environment.casefold()), None)
        selected = [(match, environment_allocations[match])] if match is not None else []
    return [
        (str(name), _number(values.get('voice')), _number(values.get('data')))
        for name, values in selected if isinstance(values, dict)
    ]


def add_maximum_allocation_donut(
    slide,
    matrix: dict[str, Any],
    environment_allocations: dict[str, dict[str, Any]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
):
    """Add an editable doughnut with one Voice/Data ring per selected environment.

    Geometry is in inches and describes the whole widget: the chart sits on the
    left, with compact per-environment maxima alongside it. Combined matrices
    show all configured environments as concentric rings; a specific environment
    shows only its ring. The returned value is the native python-pptx chart.
    """
    allocations = _selected_allocations(matrix, environment_allocations)
    if not allocations:
        return None

    chart_size = min(height, width * .68)
    chart_left = Inches(left)
    chart_top = Inches(top + (height - chart_size) / 2)
    chart_width = Inches(chart_size)
    chart_height = Inches(chart_size)

    data = CategoryChartData()
    data.categories = ['Voice', 'Data']
    for environment, voice, data_points in allocations:
        data.add_series(environment, [voice, data_points])
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.DOUGHNUT, chart_left, chart_top, chart_width, chart_height, data,
    ).chart
    chart.has_title = False
    chart.has_legend = False
    plot = chart.plots[0]
    plot.hole_size = 58
    plot.vary_by_categories = True

    for series_index, series in enumerate(chart.series):
        voice_color = _VOICE_SHADES[series_index % len(_VOICE_SHADES)]
        data_color = _DATA_SHADES[series_index % len(_DATA_SHADES)]
        for point, color in zip(series.points, (voice_color, data_color)):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = RGBColor.from_string(color)

    center_total = sum(voice + data_points for _, voice, data_points in allocations)
    center = slide.shapes.add_textbox(
        Inches(left + (chart_size - .9) / 2), Inches(top + (height - .48) / 2),
        Inches(.9), Inches(.48),
    )
    center.name = 'Maximum Score Allocation Total'
    center.text_frame.clear()
    center.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    center.text_frame.word_wrap = True
    paragraph = center.text_frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    paragraph.text = f'{center_total:.2f}\nmax points'
    paragraph.font.name = 'Ericsson Hilda'
    paragraph.font.size = Pt(10 if len(allocations) > 1 else 12)

    label_left = left + chart_size + .04
    label_width = max(.35, left + width - label_left)
    label_height = min(.74, height / max(1, len(allocations)))
    labels_top = top + (height - label_height * len(allocations)) / 2
    for index, (environment, voice, data_points) in enumerate(allocations):
        label = slide.shapes.add_textbox(
            Inches(label_left), Inches(labels_top + index * label_height),
            Inches(label_width), Inches(label_height),
        )
        label.name = f'Maximum Allocation {environment}'
        frame = label.text_frame
        frame.clear()
        frame.word_wrap = True
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        heading = frame.paragraphs[0]
        heading.text = f'{environment} · {voice + data_points:.2f} pts'
        heading.font.name = 'Ericsson Hilda'
        heading.font.bold = True
        heading.font.size = Pt(8)
        families = frame.add_paragraph()
        families.text = f'Voice {voice:.2f} · Data {data_points:.2f}'
        families.font.name = 'Ericsson Hilda'
        families.font.size = Pt(7)
    return chart
