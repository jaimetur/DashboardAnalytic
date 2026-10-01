"""Editable maximum-allocation doughnuts used in Scoring PowerPoint exports."""
from __future__ import annotations

import math
from typing import Any

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt


_GLOBAL_COLORS = ('4472C4', '7030A0', 'C55A11', '5B9BD5', 'A64D79')
_VOICE_COLOR = '176E77'
_DATA_COLOR = 'E6A81D'


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


def _environment_kind(environment: str) -> str:
    name = environment.casefold()
    return 'city' if 'city' in name else 'road' if 'road' in name else 'location'


def _allocation_chart(slide, categories, values, colors, left, top, size, hole):
    data = CategoryChartData()
    data.categories = categories
    data.add_series('Allocation', values)
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.DOUGHNUT, Inches(left), Inches(top), Inches(size), Inches(size), data,
    ).chart
    chart.has_title = False
    chart.has_legend = False
    # Use the same proportional plot frame for each overlay, avoiding automatic
    # pie margins that otherwise make the ring radii differ between charts.
    layout = chart._chartSpace.plotArea.find(qn('c:layout'))
    if layout is None:
        layout = OxmlElement('c:layout')
        chart._chartSpace.plotArea.insert(0, layout)
    manual = OxmlElement('c:manualLayout')
    for tag, value in (('layoutTarget', 'inner'), ('xMode', 'edge'), ('yMode', 'edge'),
                       ('wMode', 'factor'), ('hMode', 'factor'),
                       ('x', '.05'), ('y', '.05'), ('w', '.9'), ('h', '.9')):
        element = OxmlElement(f'c:{tag}')
        element.set('val', value)
        manual.append(element)
    layout.append(manual)
    plot = chart.plots[0]
    plot.vary_by_categories = True
    hole_size = plot._element.find(qn('c:holeSize'))
    if hole_size is None:
        hole_size = OxmlElement('c:holeSize')
        plot._element.append(hole_size)
    hole_size.set('val', str(hole))
    for point, color in zip(chart.series[0].points, colors):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = RGBColor.from_string(color)
    # No-fill chart and plot areas allow the inner native charts to remain
    # visible over the outer Global chart in Office and PDF renderers.
    chart_properties = OxmlElement('c:spPr')
    chart_properties.append(OxmlElement('a:noFill'))
    chart._chartSpace.insert_element_before(
        chart_properties, 'c:txPr', 'c:externalData', 'c:printSettings', 'c:userShapes', 'c:extLst',
    )
    plot_properties = OxmlElement('c:spPr')
    plot_properties.append(OxmlElement('a:noFill'))
    chart._chartSpace.plotArea.insert_element_before(plot_properties, 'c:extLst')
    return chart


def _legend_icon(slide, kind: str, x: float, y: float, size: float, color: str) -> None:
    """Draw a compact editable icon using native PowerPoint vector shapes."""
    rgb = RGBColor.from_string(color)
    if kind == 'city':
        for offset, height in ((.06, .48), (.32, .68), (.61, .42)):
            shape = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(x + size * offset),
                Inches(y + size * (1 - height)), Inches(size * .25), Inches(size * height),
            )
            shape.fill.background()
            shape.line.color.rgb = rgb
            shape.line.width = Pt(.7)
    elif kind == 'road':
        for xoff in (.32, .68):
            line = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + size * xoff), Inches(y + size * .08),
                Inches(x + size * (.5 + (xoff - .5) * .65)), Inches(y + size * .92),
            )
            line.line.color.rgb = rgb
            line.line.width = Pt(.8)
        for offset in (.27, .52, .77):
            line = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + size * .5), Inches(y + size * offset),
                Inches(x + size * .5), Inches(y + size * (offset + .08)),
            )
            line.line.color.rgb = rgb
            line.line.width = Pt(.7)
    elif kind == 'location':
        pin = slide.shapes.add_shape(
            MSO_SHAPE.TEAR, Inches(x + size * .16), Inches(y + size * .08),
            Inches(size * .68), Inches(size * .82),
        )
        pin.rotation = 180
        pin.fill.background()
        pin.line.color.rgb = rgb
        pin.line.width = Pt(.8)
        dot = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x + size * .42), Inches(y + size * .31),
            Inches(size * .16), Inches(size * .16),
        )
        dot.fill.solid()
        dot.fill.fore_color.rgb = rgb
        dot.line.fill.background()
    elif kind == 'voice':
        phone = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x + size * .27), Inches(y + size * .06),
            Inches(size * .46), Inches(size * .88),
        )
        phone.fill.background()
        phone.line.color.rgb = rgb
        phone.line.width = Pt(.8)
        for offset in (.2, .78):
            line = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + size * .42), Inches(y + size * offset),
                Inches(x + size * .58), Inches(y + size * offset),
            )
            line.line.color.rgb = rgb
            line.line.width = Pt(.7)
    else:  # Data device with exchange arrows.
        device = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x + size * .08), Inches(y + size * .17),
            Inches(size * .84), Inches(size * .66),
        )
        device.fill.background()
        device.line.color.rgb = rgb
        device.line.width = Pt(.8)
        for yoff, reverse in ((.42, False), (.61, True)):
            x1, x2 = ((.25, .72) if not reverse else (.75, .28))
            line = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + size * x1), Inches(y + size * yoff),
                Inches(x + size * x2), Inches(y + size * yoff),
            )
            line.line.color.rgb = rgb
            line.line.width = Pt(.7)


def _legend_row(slide, x, y, width, height, icon, color, label, bold=False, wrap=False):
    _legend_icon(slide, icon, x, y + max(.02, (height - .18) / 2), .18, color)
    swatch = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x + .20), Inches(y + (height - .09) / 2), Inches(.09), Inches(.09),
    )
    swatch.name = f'Maximum Allocation Swatch {label.splitlines()[0]}'
    swatch.fill.solid()
    swatch.fill.fore_color.rgb = RGBColor.from_string(color)
    swatch.line.fill.background()
    textbox = slide.shapes.add_textbox(
        Inches(x + .32), Inches(y), Inches(max(.2, width - .32)), Inches(height),
    )
    textbox.text_frame.clear()
    textbox.text_frame.word_wrap = wrap
    textbox.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = textbox.text_frame.paragraphs[0]
    paragraph.text = label
    paragraph.font.name = 'Ericsson Hilda'
    paragraph.font.bold = bold
    paragraph.font.size = Pt(6.5 if bold else 6)


def _global_color(environment: str, environment_allocations: dict[str, Any]) -> str:
    original_order = list(environment_allocations)
    index = next((i for i, name in enumerate(original_order)
                  if str(name).casefold() == environment.casefold()), 0)
    return _GLOBAL_COLORS[index % len(_GLOBAL_COLORS)]


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
    """Add an editable Global doughnut with nested Voice/Data environment rings.

    Geometry is in inches and describes the whole widget: the chart sits on the
    left, with compact per-environment maxima alongside it. Combined matrices
    show environment totals on the outer Global ring and a Voice/Data ring per
    environment inside it; a specific environment shows only its ring. The
    returned value is the outer native chart.
    """
    allocations = _selected_allocations(matrix, environment_allocations)
    if not allocations:
        return None

    chart_size = min(height, width * .64)
    chart_left = left
    chart_top = top + (height - chart_size) / 2
    if len(allocations) == 1:
        environment, voice, data_points = allocations[0]
        chart = _allocation_chart(
            slide, ['Voice', 'Data'], [voice, data_points],
            [_VOICE_COLOR, _DATA_COLOR], chart_left, chart_top, chart_size, 58,
        )
    else:
        totals = [voice + data_points for _, voice, data_points in allocations]
        global_colors = [_GLOBAL_COLORS[i % len(_GLOBAL_COLORS)] for i in range(len(allocations))]
        chart = _allocation_chart(
            slide, [environment for environment, _, _ in allocations], totals,
            global_colors, chart_left, chart_top, chart_size, 63,
        )
        ring_step = chart_size * .55 / (len(allocations) + 1)
        for index, (environment, voice, data_points) in enumerate(allocations):
            ring_size = chart_size - ring_step * (index + 1)
            hole_size = min(90, max(10, round(100 * (ring_size - ring_step) / ring_size)))
            ring_left = left + (chart_size - ring_size) / 2
            ring_top = top + (height - ring_size) / 2
            _allocation_chart(
                slide, ['Voice', 'Data'], [voice, data_points],
                [_VOICE_COLOR, _DATA_COLOR], ring_left, ring_top, ring_size, hole_size,
            )

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

    label_left = left + chart_size + .10
    label_width = max(.35, left + width - label_left)
    block_height = height / len(allocations)
    legend_top = top
    for index, (environment, voice, data_points) in enumerate(allocations):
        block_top = legend_top + index * block_height
        global_color = _global_color(environment, environment_allocations)
        heading_height = block_height * .48
        family_height = (block_height - heading_height) / 2
        _legend_row(slide, label_left, block_top, label_width, heading_height,
                    _environment_kind(environment), global_color,
                    f'{environment}\n{voice + data_points:.2f} pts', True, wrap=True)
        _legend_row(slide, label_left, block_top + heading_height, label_width, family_height,
                    'voice', _VOICE_COLOR, f'Voice  {voice:.2f} pts')
        _legend_row(slide, label_left, block_top + heading_height + family_height,
                    label_width, family_height, 'data', _DATA_COLOR, f'Data  {data_points:.2f} pts')
    return chart
