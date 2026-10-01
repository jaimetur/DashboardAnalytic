from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE

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


def test_combined_allocation_is_editable_concentric_doughnut_with_total_center():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    allocations = maximum_allocations_from_configuration(_configuration())

    chart = add_maximum_allocation_donut(
        slide, {'context': {'environment': 'Combined'}}, allocations,
        left=1, top=1, width=4, height=3,
    )

    assert chart.chart_type == XL_CHART_TYPE.DOUGHNUT
    assert len(chart.series) == 2
    assert [[category.label for category in plot.categories] for plot in chart.plots] == [
        ['Voice', 'Data'],
    ]
    assert [series.name for series in chart.series] == ['DriveCity', 'DriveRoad']
    assert list(chart.series[0].values) == [12.0, 20.0]
    assert list(chart.series[1].values) == [5.0, 9.0]
    assert [str(point.format.fill.fore_color.rgb) for point in chart.series[0].points] == [
        'E6A81D', '176E77',
    ]
    assert [str(point.format.fill.fore_color.rgb) for point in chart.series[1].points] == [
        'D39C22', '29958F',
    ]
    text = '\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame).replace('\x0b', '\n')
    assert '46.00\nmax points' in text
    assert 'DriveCity · 32.00 pts' in text and 'Voice 12.00 · Data 20.00' in text
    assert 'DriveRoad · 14.00 pts' in text and 'Voice 5.00 · Data 9.00' in text


def test_single_environment_allocation_uses_one_ring_and_environment_maximum_center():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])

    chart = add_maximum_allocation_donut(
        slide, {'context': {'environment': 'DriveRoad'}},
        maximum_allocations_from_configuration(_configuration()),
        left=1, top=1, width=4, height=3,
    )

    assert len(chart.series) == 1
    assert chart.series[0].name == 'DriveRoad'
    assert list(chart.series[0].values) == [5.0, 9.0]
    assert '14.00\nmax points' in '\n'.join(
        shape.text for shape in slide.shapes if shape.has_text_frame
    ).replace('\x0b', '\n')
