from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
from pptx.oxml.ns import qn
import pytest

from src.modules.scoring_pptx_allocation import (
    add_maximum_allocation_donut,
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
    assert 'DriveCity\n32.00 pts' in text and 'Voice  17.00 pts' in text and 'Data  29.00 pts' in text
    assert 'DriveRoad\n14.00 pts' in text


def test_single_environment_allocation_uses_one_ring_and_environment_maximum_center():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])

    chart = add_maximum_allocation_donut(
        slide, {'context': {'environment': 'DriveRoad'}},
        maximum_allocations_from_configuration(_configuration()),
        left=1, top=1, width=4, height=3,
    )

    assert len(chart.series) == 1
    assert [category.label for category in chart.plots[0].categories] == ['Voice', 'Data']
    assert list(chart.series[0].values) == [5.0, 9.0]
    assert [str(point.format.fill.fore_color.rgb) for point in chart.series[0].points] == [
        '4472C4', '7030A0',
    ]
    assert len([shape for shape in slide.shapes if shape.has_chart]) == 1
    drive_road_swatch = next(
        shape for shape in slide.shapes if shape.name == 'Maximum Allocation Swatch DriveRoad'
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
