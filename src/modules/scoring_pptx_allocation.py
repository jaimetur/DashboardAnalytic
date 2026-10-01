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


_GLOBAL_COLORS = ('176E77', 'E6A81D', 'C55A11', '5B9BD5', 'A64D79')
_VOICE_COLOR = '4472C4'
_DATA_COLOR = '7030A0'
_CATEGORY_COLORS = ('4472C4', '7030A0', 'C55A11', '5B9BD5', 'A64D79', '548235', 'D65F8D', '8064A2')


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


def _add_percentage_labels(slide, values, colors, chart_left, chart_top, chart_size: float, hole: int) -> None:
    """Add editable native text labels over doughnut slices that have room."""
    total = sum(_number(value) for value in values)
    if total <= 0:
        return
    outer_radius = chart_size * .45
    middle_radius = outer_radius * (1 + hole / 100) / 2
    radial_width = outer_radius * (1 - hole / 100)
    center_x = chart_left + chart_size / 2
    center_y = chart_top + chart_size / 2
    angle = 0.0
    for value, color in zip(values, colors):
        share = _number(value) / total
        label_text = f'{share * 100:.1f}%'
        arc_length = 2 * math.pi * middle_radius * 72 * share
        label_width = len(label_text) * 7.5 * .62 + 4
        if radial_width * 72 < 9.5 or arc_length < label_width:
            angle += share * 360
            continue
        midpoint = math.radians(angle + share * 180)
        label_width_inches = max(.3, label_width / 72)
        x = center_x + middle_radius * math.sin(midpoint) - label_width_inches / 2
        y = center_y - middle_radius * math.cos(midpoint) - .09
        rgb = tuple(int(color[offset:offset + 2], 16) for offset in (0, 2, 4))
        luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
        text_color = '333333' if luminance > 155 else 'FFFFFF'
        label = slide.shapes.add_textbox(
            Inches(x), Inches(y), Inches(label_width_inches), Inches(.18),
        )
        label.name = 'Maximum Allocation Percentage Label'
        text_frame = label.text_frame
        text_frame.clear()
        text_frame.margin_left = 0
        text_frame.margin_right = 0
        text_frame.margin_top = 0
        text_frame.margin_bottom = 0
        text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        paragraph = text_frame.paragraphs[0]
        paragraph.alignment = PP_ALIGN.CENTER
        run = paragraph.add_run()
        run.text = label_text
        run.font.name = 'Ericsson Hilda'
        run.font.size = Pt(7.5)
        run.font.bold = True
        run.font.color.rgb = RGBColor.from_string(text_color)
        angle += share * 360


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


def category_maximum_allocations(matrix: dict[str, Any]) -> dict[str, float]:
    """Return configured maximum points once per KPI category in a score matrix."""
    allocations: dict[str, float] = {}
    for row in matrix.get('rows', []):
        if not isinstance(row, dict) or row.get('row_type') == 'category':
            continue
        category = str(row.get('category') or '').strip()
        if category:
            allocations[category] = allocations.get(category, 0.0) + _number(row.get('max_points'))
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


def _environment_display_label(environment: str) -> str:
    key = ''.join(character for character in environment.casefold() if character.isalnum())
    if key == 'drivecity':
        return 'Drive - City'
    if key in {'driveconnectionroad', 'driveconnectingroads', 'driveroad'}:
        return 'Drive - Connecting Roads'
    return environment


def _category_icon_kind(category: str) -> str:
    key = ''.join(character for character in category.casefold() if character.isalnum())
    if key == 'classiccalls':
        return 'voice'
    if key == 'whatsappcalls':
        return 'whatsapp'
    if 'multirab' in key:
        return 'multirab'
    if 'transfer' in key:
        return 'transfer'
    if 'brows' in key or 'httphttps' in key:
        return 'browsing'
    if 'video' in key or 'stream' in key:
        return 'video'
    if 'interactiv' in key:
        return 'interactivity'
    return 'category'


def _category_display_label(category: str) -> str:
    return category.strip().title()


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
    elif kind == 'whatsapp':
        bubble = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x + size * .12), Inches(y + size * .08),
            Inches(size * .76), Inches(size * .72),
        )
        bubble.fill.background()
        bubble.line.color.rgb = rgb
        bubble.line.width = Pt(.8)
        for offset in (.31, .47, .63):
            dot = slide.shapes.add_shape(
                MSO_SHAPE.OVAL, Inches(x + size * offset), Inches(y + size * .39),
                Inches(size * .07), Inches(size * .07),
            )
            dot.fill.solid()
            dot.fill.fore_color.rgb = rgb
            dot.line.fill.background()
    elif kind == 'multirab':
        mast = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Inches(x + size * .5), Inches(y + size * .18),
            Inches(x + size * .5), Inches(y + size * .91),
        )
        mast.line.color.rgb = rgb
        mast.line.width = Pt(.9)
        for yoff, half_width in ((.34, .32), (.52, .24), (.7, .16)):
            beam = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + size * (.5 - half_width)), Inches(y + size * yoff),
                Inches(x + size * (.5 + half_width)), Inches(y + size * yoff),
            )
            beam.line.color.rgb = rgb
            beam.line.width = Pt(.8)
    elif kind == 'transfer':
        for xoff, down in ((.32, False), (.68, True)):
            shaft = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + size * xoff), Inches(y + size * (.28 if down else .68)),
                Inches(x + size * xoff), Inches(y + size * (.7 if down else .26)),
            )
            shaft.line.color.rgb = rgb
            shaft.line.width = Pt(.9)
            arrow = slide.shapes.add_shape(
                MSO_SHAPE.ISOSCELES_TRIANGLE, Inches(x + size * (xoff - .13)),
                Inches(y + size * (.58 if down else .1)), Inches(size * .26), Inches(size * .24),
            )
            arrow.rotation = 180 if down else 0
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = rgb
            arrow.line.fill.background()
    elif kind == 'browsing':
        window = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x + size * .08), Inches(y + size * .18),
            Inches(size * .84), Inches(size * .65),
        )
        window.fill.background()
        window.line.color.rgb = rgb
        window.line.width = Pt(.8)
        header = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Inches(x + size * .08), Inches(y + size * .38),
            Inches(x + size * .92), Inches(y + size * .38),
        )
        header.line.color.rgb = rgb
        header.line.width = Pt(.7)
        for xoff in (.22, .34, .46):
            dot = slide.shapes.add_shape(
                MSO_SHAPE.OVAL, Inches(x + size * xoff), Inches(y + size * .25),
                Inches(size * .045), Inches(size * .045),
            )
            dot.fill.solid()
            dot.fill.fore_color.rgb = rgb
            dot.line.fill.background()
    elif kind == 'video':
        screen = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x + size * .08), Inches(y + size * .18),
            Inches(size * .84), Inches(size * .64),
        )
        screen.fill.background()
        screen.line.color.rgb = rgb
        screen.line.width = Pt(.8)
        play = slide.shapes.add_shape(
            MSO_SHAPE.ISOSCELES_TRIANGLE, Inches(x + size * .39), Inches(y + size * .32),
            Inches(size * .34), Inches(size * .35),
        )
        play.rotation = 90
        play.fill.solid()
        play.fill.fore_color.rgb = rgb
        play.line.fill.background()
    elif kind == 'interactivity':
        points = ((.08, .55), (.3, .55), (.4, .28), (.57, .76), (.69, .45), (.92, .45))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            segment = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + size * x1), Inches(y + size * y1),
                Inches(x + size * x2), Inches(y + size * y2),
            )
            segment.line.color.rgb = rgb
            segment.line.width = Pt(1)
    elif kind == 'category':
        for offset, height in ((.18, .35), (.4, .62), (.62, .82)):
            bar = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(x + size * offset), Inches(y + size * (1 - height)),
                Inches(size * .13), Inches(size * height),
            )
            bar.fill.solid()
            bar.fill.fore_color.rgb = rgb
            bar.line.fill.background()
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


def _environment_segment_icons(slide, allocations, environment_allocations,
                               chart_left: float, chart_top: float, chart_size: float) -> None:
    total = sum(voice + data_points for _, voice, data_points in allocations)
    if total <= 0:
        return
    size = .30
    radius = chart_size * .45 + .18
    angle = 0.0
    for environment, voice, data_points in allocations:
        share = (voice + data_points) / total
        midpoint = math.radians(angle + share * 180)
        x = chart_left + chart_size / 2 + radius * math.sin(midpoint) - size / 2
        y = chart_top + chart_size / 2 - radius * math.cos(midpoint) - size / 2
        first_shape = len(slide.shapes)
        _legend_icon(slide, _environment_kind(environment), x, y, size,
                     _global_color(environment, environment_allocations))
        parts = list(slide.shapes)[first_shape:]
        for part in parts:
            part.line.width = Pt(1.3)
        icon = parts[0] if len(parts) == 1 else slide.shapes.add_group_shape(parts)
        icon.name = f'Maximum Allocation Environment Segment Icon {environment}'
        angle += share * 360


def _legend_row(slide, x, y, width, height, icon, color, label, detail, bold=False, wrap=False):
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
    paragraph.font.name = 'Ericsson Hilda'
    paragraph.font.bold = bold
    font_size = min(8.5, max(8.0, 8.5 * 42 / max(42, len(label) + len(detail) + 2)))
    paragraph.font.size = Pt(font_size)
    name_run = paragraph.add_run()
    name_run.text = f'{label}  '
    name_run.font.name = 'Ericsson Hilda'
    name_run.font.size = Pt(font_size)
    name_run.font.bold = bold
    detail_run = paragraph.add_run()
    detail_run.text = detail
    detail_run.font.name = 'Ericsson Hilda'
    detail_run.font.size = Pt(font_size)
    detail_run.font.bold = bold
    detail_run.font.color.rgb = RGBColor.from_string('8A3D0A')


def _global_color(environment: str, environment_allocations: dict[str, Any]) -> str:
    original_order = list(environment_allocations)
    index = next((i for i, name in enumerate(original_order)
                  if str(name).casefold() == environment.casefold()), 0)
    return _GLOBAL_COLORS[index % len(_GLOBAL_COLORS)]


def _allocation_legend_heading(slide, x, y, width, height, label):
    textbox = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height))
    textbox.text_frame.clear()
    textbox.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    textbox.text_frame.word_wrap = False
    paragraph = textbox.text_frame.paragraphs[0]
    paragraph.text = label
    paragraph.font.name = 'Ericsson Hilda'
    paragraph.font.bold = True
    paragraph.font.size = Pt(9)


def add_maximum_allocation_donut(
    slide,
    matrix: dict[str, Any],
    environment_allocations: dict[str, dict[str, Any]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    category_allocations: dict[str, float] | None = None,
):
    """Add an editable environment doughnut with an inner allocation ring.

    Geometry is in inches and describes the whole widget: the chart sits above
    its legend, with per-environment maxima listed first. Combined matrices
    show environment totals on the outer ring and allocation totals inside it;
    a specific environment shows only its allocation ring. The
    returned value is the outer native chart.
    """
    allocations = _selected_allocations(matrix, environment_allocations)
    if not allocations:
        return None

    category_allocations = {
        str(category): _number(value) for category, value in (category_allocations or {}).items()
        if str(category).strip() and _number(value) > 0
    }
    category_mode = bool(category_allocations)
    inner_labels = [_category_display_label(category) for category in category_allocations] if category_mode else ['Voice', 'Data']
    inner_colors = ([_CATEGORY_COLORS[index % len(_CATEGORY_COLORS)]
                     for index in range(len(inner_labels))]
                    if category_mode else [_VOICE_COLOR, _DATA_COLOR])
    if category_mode:
        inner_totals = list(category_allocations.values())
    elif len(allocations) > 1:
        inner_totals = [sum(voice for _, voice, _ in allocations),
                        sum(data_points for _, _, data_points in allocations)]
    else:
        inner_totals = [allocations[0][1], allocations[0][2]]

    center_total = sum(voice + data_points for _, voice, data_points in allocations)
    legend_items = [('heading', 'Points per Environment:')]
    for environment, voice, data_points in allocations:
        value = voice + data_points
        percent = value * 100 / center_total if center_total else 0
        legend_items.append((_environment_kind(environment), _global_color(environment, environment_allocations),
                             _environment_display_label(environment),
                             f'{value:.2f} pts ({percent:.1f}%)'))
    legend_items.append(('heading', 'Points per KPI Category:' if category_mode else 'Points per Service:'))
    if category_mode:
        for index, category in enumerate(inner_labels):
            value = inner_totals[index]
            percent = value * 100 / center_total if center_total else 0
            legend_items.append((_category_icon_kind(category), inner_colors[index], _category_display_label(category),
                                 f'{value:.2f} pts ({percent:.1f}%)'))
    else:
        for index, (label, color, kind) in enumerate((
            ('Voice', _VOICE_COLOR, 'voice'), ('Data', _DATA_COLOR, 'data'),
        )):
            value = inner_totals[index]
            percent = value * 100 / center_total if center_total else 0
            legend_items.append((kind, color, label, f'{value:.2f} pts ({percent:.1f}%)'))

    legend_heights = [.22 for _ in legend_items]
    chart_size = min(width * .90, height - .35 - sum(legend_heights))
    chart_left = left + (width - chart_size) / 2
    chart_top = top
    totals = [voice + data_points for _, voice, data_points in allocations]
    chart = _allocation_chart(
        slide, [environment for environment, _, _ in allocations], totals,
        [_global_color(environment, environment_allocations) for environment, _, _ in allocations],
        chart_left, chart_top, chart_size, 72,
    )
    _environment_segment_icons(slide, allocations, environment_allocations,
                               chart_left, chart_top, chart_size)
    ring_size = chart_size * .72
    _allocation_chart(
        slide, inner_labels, inner_totals, inner_colors,
        chart_left + (chart_size - ring_size) / 2, chart_top + (chart_size - ring_size) / 2,
        ring_size, 63,
    )
    _add_percentage_labels(slide, totals,
                           [_global_color(environment, environment_allocations)
                            for environment, _, _ in allocations],
                           chart_left, chart_top, chart_size, 72)
    _add_percentage_labels(slide, inner_totals, inner_colors,
                           chart_left + (chart_size - ring_size) / 2,
                           chart_top + (chart_size - ring_size) / 2, ring_size, 63)

    center = slide.shapes.add_textbox(
        Inches(chart_left + (chart_size - .9) / 2), Inches(chart_top + (chart_size - .48) / 2),
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

    label_top = top + chart_size + .25
    label_width = width
    label_y = label_top
    for item, label_height in zip(legend_items, legend_heights):
        x = left
        y = label_y
        if item[0] == 'heading':
            _allocation_legend_heading(slide, x + .12, y, label_width - .12, label_height, item[1])
        else:
            kind, color, label, detail = item
            _legend_row(slide, x + .15, y, label_width - .15, label_height,
                        kind, color, label, detail, bold=False, wrap=False)
        label_y += label_height
    return chart
