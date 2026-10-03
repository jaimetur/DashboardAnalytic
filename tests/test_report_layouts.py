import csv
import io

import pytest

from src.modules.report_layouts import (
    DYNAMIC_LAYOUTS,
    canonical_layout_name,
    grid_layout_name,
    normalize_catalog_layouts,
    selectable_layout_name,
)


@pytest.mark.parametrize(
    'rows,columns,comments,expected',
    [
        (1, 1, '', 'Title + 1 rows + 1 columns'),
        (2, 3, 'down', 'Title + 2 rows + 3 columns + comments down'),
        (4, 2, 'right', 'Title + 4 rows + 2 columns + comments right'),
    ],
)
def test_grid_layout_names_are_canonical(rows, columns, comments, expected):
    assert grid_layout_name(rows, columns, comments) == expected
    assert canonical_layout_name(expected) == expected
    assert selectable_layout_name(expected)


def test_dynamic_layout_names_are_the_six_canonical_variants():
    assert DYNAMIC_LAYOUTS == (
        'Title + 2 rows + dynamic columns',
        'Title + dynamic rows + 2 columns',
        'Title + 2 rows + dynamic columns + comments right',
        'Title + 2 rows + dynamic columns + comments down',
        'Title + dynamic rows + 2 columns + comments right',
        'Title + dynamic rows + 2 columns + comments down',
    )
    assert all(selectable_layout_name(name) for name in DYNAMIC_LAYOUTS)


@pytest.mark.parametrize(
    'legacy,expected',
    [
        ('Title and 2 columns and 2 rows + Comments right', 'Title + 2 rows + 2 columns + comments right'),
        ('Title and 2 rows + Comments right', 'Title + 2 rows + 1 columns + comments right'),
        ('Title and 3 columns + Comments', 'Title + 1 rows + 3 columns + comments down'),
        ('2 rows + dynamic columns, comments down', DYNAMIC_LAYOUTS[3]),
    ],
)
def test_legacy_layout_aliases_normalize_to_canonical_names(legacy, expected):
    assert canonical_layout_name(legacy) == expected


def test_editor_filter_accepts_grid_variants_without_comments_only():
    assert selectable_layout_name('Title + 1 rows + 3 columns')
    assert not selectable_layout_name('Title + 1 rows + 3 columns + comments left')
    assert not selectable_layout_name('Title and Content')


def test_template_editor_layout_suggestions_include_supported_names_only():
    from src.DashboardAnalytic import catalogue_layout_names

    choices = catalogue_layout_names('nsa')

    assert set(DYNAMIC_LAYOUTS) <= set(choices)
    assert len(choices) == 50
    assert {'Title Page', 'Title Only'} <= set(choices)
    assert 'Title + 1 rows + 1 columns' in choices
    assert 'Title + 1 rows + 1 columns + comments left' not in choices
    assert 'Title and Content' not in choices


def test_layout_normalization_changes_only_layout_cells_and_keeps_csv_schema():
    source = (
        'Slide,Layout,Chart Type\n'
        '1,Title and 2 columns and 2 rows + Comments right,Average Vertical Bars\n'
        '2,"2 rows + dynamic columns, comments down",Histogram Bars\n'
    ).encode('utf-8')
    normalized = normalize_catalog_layouts(source).decode('utf-8')
    rows = list(csv.DictReader(io.StringIO(normalized)))

    assert list(rows[0]) == ['Slide', 'Layout', 'Chart Type']
    assert rows == [
        {'Slide': '1', 'Layout': 'Title + 2 rows + 2 columns + comments right', 'Chart Type': 'Average Vertical Bars'},
        {'Slide': '2', 'Layout': DYNAMIC_LAYOUTS[3], 'Chart Type': 'Histogram Bars'},
    ]
