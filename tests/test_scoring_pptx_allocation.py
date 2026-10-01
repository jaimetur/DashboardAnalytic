from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
from pptx.oxml.ns import qn
import pytest

from src.modules.scoring_pptx_allocation import (
    add_maximum_allocation_donut,
    category_maximum_allocations,
    maximum_allocations_from_configuration,
)


def _configuration():
    return {
        'scope': {'environments': {
            'DriveCity': {'total_points': 65},
            'DriveRoad': {'total_points': 35},
            'Unused': {'total_points': 0},
        }},
        'metrics': [
            {'source_kind': 'voice', 'contexts': {
                'DriveCity': {'max_points': 10}, 'DriveRoad': {'max_points': 4},
            }},
            {'calculation': {'source_kind': 'speech'}, 'contexts': {
                'DriveCity': {'max_points': 2}, 'DriveRoad': {'max_points': 1},
            }},
            {'source_kind': 'data', 'contexts': {
                'DriveCity': {'max_points': 20}, 'DriveRoad': {'max_points': 9},
            }},
        ],
    }


def test_configuration_allocations_sum_metrics_once_per_positive_environment():
    assert maximum_allocations_from_configuration(_configuration()) == {
        'DriveCity': {'voice': 12.0, 'data': 20.0, 'max': 32.0},
        'DriveRoad': {'voice': 5.0, 'data': 9.0, 'max': 14.0},
    }
    assert maximum_allocations_from_configuration(None) == {}


def test_combined_allocation_has_environment_outer_ring_and_one_family_ring():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    allocations = maximum_allocations_from_configuration(_configuration())

    chart = add_maximum_allocation_donut(
        slide, {'context': {'environment': 'Combined'}}, allocations,
        left=1, top=1, width=4, height=3,
    )

    assert chart.chart_type == XL_CHART_TYPE.DOUGHNUT
    assert len(chart.series) == 1
    assert [category.label for category in chart.plots[0].categories] == ['DriveCity', 'DriveRoad']
    assert list(chart.series[0].values) == [32.0, 14.0]
    assert [str(point.format.fill.fore_color.rgb) for point in chart.series[0].points] == [
        '176E77', 'E6A81D',
    ]
    charts = [shape.chart for shape in slide.shapes if shape.has_chart]
    assert len(charts) == 2
    assert [category.label for category in charts[1].plots[0].categories] == ['Voice', 'Data']
    assert list(charts[1].series[0].values) == [17.0, 29.0]
    assert [str(point.format.fill.fore_color.rgb) for point in charts[1].series[0].points] == [
        '4472C4', '7030A0',
    ]
    ring_shapes = [shape for shape in slide.shapes if shape.has_chart]
    assert ring_shapes[1].width < ring_shapes[0].width
    for environment_chart in charts:
        chart_space_children = list(environment_chart._chartSpace)
        chart_index = next(i for i, child in enumerate(chart_space_children) if child.tag == qn('c:chart'))
        shape_index = next(i for i, child in enumerate(chart_space_children) if child.tag == qn('c:spPr'))
        assert shape_index > chart_index
        text_properties = [i for i, child in enumerate(chart_space_children) if child.tag == qn('c:txPr')]
        assert not text_properties or shape_index < text_properties[0]
    text = '\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame).replace('\x0b', '\n')
    assert '46.00\nmax points' in text
    assert 'Drive - City  32.00 pts (69.6%)' in text
    assert 'Voice  17.00 pts (37.0%)' in text and 'Data  29.00 pts (63.0%)' in text
    assert 'Drive - Connecting Roads  14.00 pts (30.4%)' in text
    assert 'Points per Environment:' in text and 'Points per Service:' in text
    labels = [shape for shape in slide.shapes if shape.has_text_frame
              and shape.text.startswith(('Drive - City', 'Drive - Connecting Roads', 'Voice  ', 'Data  '))]
    assert [shape.text.splitlines()[0] for shape in labels] == [
        'Drive - City  32.00 pts (69.6%)', 'Drive - Connecting Roads  14.00 pts (30.4%)',
        'Voice  17.00 pts (37.0%)', 'Data  29.00 pts (63.0%)',
    ]
    assert all(first.top < second.top for first, second in zip(labels, labels[1:]))
    detail_run = labels[0].text_frame.paragraphs[0].runs[-1]
    assert detail_run.text == '32.00 pts (69.6%)'
    assert str(detail_run.font.color.rgb) == '8A3D0A'
    chart_shape = next(shape for shape in slide.shapes if shape.has_chart)
    assert labels[-1].top >= chart_shape.top + chart_shape.height


def test_single_environment_allocation_keeps_outer_environment_ring_and_inner_service_ring():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])

    chart = add_maximum_allocation_donut(
        slide, {'context': {'environment': 'DriveRoad'}},
        maximum_allocations_from_configuration(_configuration()),
        left=1, top=1, width=4, height=3,
    )

    assert chart.chart_type == XL_CHART_TYPE.DOUGHNUT
    assert [category.label for category in chart.plots[0].categories] == ['DriveRoad']
    assert list(chart.series[0].values) == [14.0]
    assert [str(point.format.fill.fore_color.rgb) for point in chart.series[0].points] == [
        'E6A81D',
    ]
    charts = [shape.chart for shape in slide.shapes if shape.has_chart]
    assert len(charts) == 2
    assert [category.label for category in charts[1].plots[0].categories] == ['Voice', 'Data']
    assert list(charts[1].series[0].values) == [5.0, 9.0]
    assert [str(point.format.fill.fore_color.rgb) for point in charts[1].series[0].points] == [
        '4472C4', '7030A0',
    ]
    drive_road_swatch = next(
        shape for shape in slide.shapes
        if shape.name.startswith('Maximum Allocation Swatch Drive - Connecting Roads')
    )
    assert str(drive_road_swatch.fill.fore_color.rgb) == 'E6A81D'
    assert '14.00\nmax points' in '\n'.join(
        shape.text for shape in slide.shapes if shape.has_text_frame
    ).replace('\x0b', '\n')


def test_many_environment_rings_keep_hole_size_within_powerpoint_limits():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    allocations = {
        f'Environment{index}': {'voice': 10 + index, 'data': 20 + index}
        for index in range(6)
    }

    add_maximum_allocation_donut(
        slide, {'context': {'environment': 'Combined'}}, allocations,
        left=1, top=1, width=4, height=3,
    )

    charts = [shape.chart for shape in slide.shapes if shape.has_chart]
    assert len(charts) == 2
    hole_sizes = [int(chart.plots[0]._element.find(qn('c:holeSize')).get('val')) for chart in charts]
    assert all(10 <= hole <= 90 for hole in hole_sizes)


def test_category_allocations_count_each_matrix_row_once_and_render_category_ring():
    matrix = {
        'context': {'environment': 'DriveRoad'},
        'rows': [
            {'category': 'Voice', 'max_points': 12, 'values': {'operator-a': {'points': 4}, 'operator-b': {'points': 6}}},
            {'category': 'Data', 'max_points': 20, 'values': {'operator-a': {'points': 10}, 'operator-b': {'points': 9}}},
            {'category': 'Voice', 'max_points': 3, 'values': {'operator-a': {'points': 1}, 'operator-b': {'points': 2}}},
        ],
    }
    categories = category_maximum_allocations(matrix)
    assert categories == {'Voice': 15.0, 'Data': 20.0}

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    chart = add_maximum_allocation_donut(
        slide, matrix, {'DriveRoad': {'voice': 15, 'data': 20, 'max': 35}},
        left=1, top=1, width=3, height=3.2, category_allocations=categories,
    )

    assert chart.chart_type == XL_CHART_TYPE.DOUGHNUT
    assert [category.label for category in chart.plots[0].categories] == ['DriveRoad']
    assert list(chart.series[0].values) == [35]
    assert [str(point.format.fill.fore_color.rgb) for point in chart.series[0].points] == [
        '176E77',
    ]
    charts = [shape for shape in slide.shapes if shape.has_chart]
    assert len(charts) == 2
    assert [category.label for category in charts[0].chart.plots[0].categories] == ['DriveRoad']
    assert list(charts[0].chart.series[0].values) == [35.0]
    assert [category.label for category in charts[1].chart.plots[0].categories] == ['Voice', 'Data']
    assert list(charts[1].chart.series[0].values) == [15.0, 20.0]
    assert [str(point.format.fill.fore_color.rgb) for point in charts[1].chart.series[0].points] == [
        '4472C4', '7030A0',
    ]
    assert all(chart.chart.series[0]._element.find(qn('c:dLbls')) is None for chart in charts)
    percentage_labels = [shape for shape in slide.shapes
                         if shape.name == 'Maximum Allocation Percentage Label']
    assert [shape.text_frame.text for shape in percentage_labels] == ['100.0%', '42.9%', '57.1%']
    assert all(shape.text_frame.paragraphs[0].runs[0].font.size.pt == pytest.approx(7.5)
               for shape in percentage_labels)
    chart_shape = charts[0]
    swatches = [shape for shape in slide.shapes if shape.name.startswith('Maximum Allocation Swatch')]
    assert len(swatches) == 3
    texts = [shape for shape in slide.shapes if shape.has_text_frame]
    legend_texts = [shape for shape in texts if ' pts' in shape.text]
    assert all(shape.top >= chart_shape.top + chart_shape.height
               for shape in legend_texts)


def test_percentage_labels_hide_category_slices_that_are_too_small():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_maximum_allocation_donut(
        slide, {'context': {'environment': 'DriveCity'}},
        {'DriveCity': {'voice': 1, 'data': 99, 'max': 100}},
        left=1, top=1, width=3, height=3.2,
        category_allocations={'Multi RAB': 3.9, 'Video Stream': 96.1},
    )

    charts = [shape.chart for shape in slide.shapes if shape.has_chart]
    assert all(chart.series[0]._element.find(qn('c:dLbls')) is None for chart in charts)
    percentage_labels = [shape.text_frame.text for shape in slide.shapes
                         if shape.name == 'Maximum Allocation Percentage Label']
    assert percentage_labels == ['100.0%', '96.1%']
