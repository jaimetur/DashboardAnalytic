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


def test_template_contains_every_fixed_grid_size_and_comment_variant():
    from pptx import Presentation
    from src.modules.cdr_reporting import _layout_chart_frames

    deck = Presentation('assets/powerpoint-templates/Template_01.pptx')
    layouts = {canonical_layout_name(layout.name): layout for layout in deck.slide_layouts}

    for rows in range(1, 7):
        for columns in range(1, 7):
            for comments in ('', 'down', 'right'):
                name = grid_layout_name(rows, columns, comments)
                assert name in layouts
                assert len(_layout_chart_frames(layouts[name])) == rows * columns


def test_template_contains_all_dynamic_axes_and_comment_variants():
    from pptx import Presentation

    deck = Presentation('assets/powerpoint-templates/Template_01.pptx')
    layouts = {canonical_layout_name(layout.name): layout for layout in deck.slide_layouts}

    for name in DYNAMIC_LAYOUTS:
        assert name not in layouts


def test_dynamic_layout_names_cover_three_axes_and_comment_variants():
    expected = tuple(
        f'Title + {axes}' + (f' + comments {comments}' if comments else '')
        for axes in ('2 rows + dynamic columns', 'dynamic rows + 2 columns', 'dynamic rows + dynamic columns')
        for comments in ('', 'down', 'right')
    )
    assert DYNAMIC_LAYOUTS == expected
    assert all(selectable_layout_name(name) for name in DYNAMIC_LAYOUTS)


@pytest.mark.parametrize(
    'legacy,expected',
    [
        ('Title and 2 columns and 2 rows + Comments right', 'Title + 2 rows + 2 columns + comments right'),
        ('Title and 2 rows + Comments right', 'Title + 2 rows + 1 columns + comments right'),
        ('Title and 3 columns + Comments', 'Title + 1 rows + 3 columns + comments down'),
        ('2 rows + dynamic columns, comments down', DYNAMIC_LAYOUTS[1]),
    ],
)
def test_legacy_layout_aliases_normalize_to_canonical_names(legacy, expected):
    assert canonical_layout_name(legacy) == expected


def test_editor_filter_accepts_grid_variants_without_comments_only():
    assert selectable_layout_name('Title + 1 rows + 3 columns')
    assert not selectable_layout_name('Title + 1 rows + 3 columns + comments left')
    assert not selectable_layout_name('Title and Content')


def test_template_editor_layout_suggestions_include_supported_names_only():
    from src.DriveTestAnalyzer import catalogue_layout_names

    choices = catalogue_layout_names('nsa')

    assert set(DYNAMIC_LAYOUTS) <= set(choices)
    assert len(choices) == 121
    assert {'Title Page', 'Title Only', 'Transition', 'Black logo end slide'} <= set(choices)
    assert 'Title + 1 rows + 1 columns' in choices
    assert 'Title + 1 rows + 1 columns + comments left' not in choices
    assert 'Title and Content' not in choices
    fixed_names = {
        grid_layout_name(rows, columns, comments)
        for rows in range(1, 7)
        for columns in range(1, 7)
        for comments in ('', 'down', 'right')
    }
    assert choices[:4] == ['Title Page', 'Title Only', 'Transition', 'Black logo end slide']
    assert choices[4:13] == list(DYNAMIC_LAYOUTS)
    assert choices[13:] == sorted(fixed_names, key=str.casefold)


def test_visible_physical_layout_block_is_unique_and_sorted_after_black_title_page():
    from pptx import Presentation

    deck = Presentation('assets/powerpoint-templates/Template_01.pptx')
    physical = [canonical_layout_name(layout.name) for layout in deck.slide_layouts]
    physical_visible = [name for name in physical if selectable_layout_name(name)]
    fixed_names = {
        grid_layout_name(rows, columns, comments)
        for rows in range(1, 7)
        for columns in range(1, 7)
        for comments in ('', 'down', 'right')
    }
    structures = ['Title Page', 'Title Only', 'Transition', 'Black logo end slide']
    expected_block = structures + sorted(fixed_names, key=str.casefold)
    block_start = physical.index('Black Title Page') + 1

    assert physical[block_start:block_start + len(expected_block)] == expected_block
    assert physical_visible == expected_block
    assert len(physical_visible) == len(set(physical_visible)) == 112


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
        {'Slide': '2', 'Layout': DYNAMIC_LAYOUTS[1], 'Chart Type': 'Histogram Bars'},
    ]


@pytest.mark.parametrize('column_count', [13, 19])
def test_recognized_legacy_catalog_schemas_upgrade_to_22_columns_without_losing_values(column_count):
    from src.modules.cdr_reporting import CATALOG_HEADERS, PRE_LEGEND_FORMAT_CATALOG_HEADERS, RANGELESS_CATALOG_HEADERS

    legacy_headers = RANGELESS_CATALOG_HEADERS if column_count == 13 else PRE_LEGEND_FORMAT_CATALOG_HEADERS
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=legacy_headers, lineterminator='\n')
    writer.writeheader()
    writer.writerow({
        'Slide': '4', 'Slide Tittle': 'Legacy quality', 'Layout': 'Title and 2 columns + Comments right',
        'Chart Tittle': 'Completed calls', 'Source Dataset': 'CDR-Voice', 'KPI': 'Call_Status',
        'Chart type': '100% Stacked Vertical Bars',
        **({'Label Format': 'bold'} if 'Label Format' in legacy_headers else {}),
    })

    migrated = normalize_catalog_layouts(output.getvalue().encode('utf-8')).decode('utf-8')
    reader = csv.DictReader(io.StringIO(migrated))
    rows = list(reader)

    assert tuple(reader.fieldnames) == CATALOG_HEADERS
    assert rows[0]['Slide'] == '4'
    assert rows[0]['Slide Tittle'] == 'Legacy quality'
    assert rows[0]['Layout'] == 'Title + 1 rows + 2 columns + comments right'
    assert rows[0]['Chart Tittle'] == 'Completed calls'
    assert rows[0]['Dynamic Rows Field'] == rows[0]['Dynamic Columns Field'] == ''
    if column_count == 19:
        assert rows[0]['Label Format'] == 'bold'


def test_legacy_dynamic_field_migration_maps_to_the_declared_axis():
    from src.modules.cdr_reporting import CATALOG_HEADERS, catalogue_csv, parse_catalog_csv

    from src.modules.cdr_reporting import SINGLE_DYNAMIC_CATALOG_HEADERS

    old_headers = SINGLE_DYNAMIC_CATALOG_HEADERS
    old_rows = []
    for slide, layout, field in (
        (1, 'Title + dynamic rows + 2 columns + comments down', 'Vendor'),
        (2, 'Title + 2 rows + dynamic columns + comments right', 'Operator'),
    ):
        for chart in ('LTE', 'NR'):
            old_rows.append({
                'Slide': str(slide), 'Slide Tittle': f'{chart} quality', 'Layout': layout,
                'Chart Tittle': chart, 'Source Dataset': 'CDR-Data', 'KPI': 'LTE_RSRP',
                'Chart type': 'Histogram Bars', 'Rows Aggregation': 'Operator',
                'Dynamic Field': field,
            })
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=old_headers, lineterminator='\n')
    writer.writeheader()
    writer.writerows(old_rows)

    old_csv = output.getvalue()
    migrated_csv = normalize_catalog_layouts(old_csv.encode('utf-8')).decode('utf-8')
    migrated_reader = csv.DictReader(io.StringIO(migrated_csv))
    migrated_rows = list(migrated_reader)
    restored = parse_catalog_csv(old_csv, 'nsa')
    normalized = list(csv.DictReader(io.StringIO(catalogue_csv(restored).decode('utf-8'))))

    assert CATALOG_HEADERS[4:6] == ('Dynamic Rows Field', 'Dynamic Columns Field')
    assert len(CATALOG_HEADERS) == 22
    assert migrated_reader.fieldnames[4:6] == ['Dynamic Rows Field', 'Dynamic Columns Field']
    assert migrated_rows[0]['Dynamic Rows Field'] == 'Vendor'
    assert migrated_rows[2]['Dynamic Columns Field'] == 'Operator'
    assert normalized[0]['Dynamic Rows Field'] == 'Vendor'
    assert normalized[0]['Dynamic Columns Field'] == ''
    assert normalized[2]['Dynamic Rows Field'] == ''
    assert normalized[2]['Dynamic Columns Field'] == 'Operator'


def test_two_axis_dynamic_template_round_trips_both_fields():
    from src.modules.cdr_reporting import CATALOG_HEADERS, CatalogEntry, catalogue_csv, parse_catalog_csv

    entry = CatalogEntry(
        slide=1, slide_title='Quality', slide_subtitle='',
        layout='Title + dynamic rows + dynamic columns + comments down',
        chart_title='Signal', cdr_source='CDR-Data', kpi='LTE_RSRP',
        chart_type='Histogram Bars', legend='', filters='',
        grouping_rows='Vendor_Only', grouping_columns='Campaign',
        dynamic_rows_field='Vendor_Only', dynamic_columns_field='Campaign',
    )

    exported = catalogue_csv([entry])
    restored = parse_catalog_csv(exported, 'nsa')

    assert CATALOG_HEADERS[4:6] == ('Dynamic Rows Field', 'Dynamic Columns Field')
    assert len(CATALOG_HEADERS) == 22
    assert b'Dynamic Field' not in exported
    assert (restored[0].dynamic_rows_field, restored[0].dynamic_columns_field) == ('Vendor_Only', 'Campaign')


def test_catalogue_csv_accepts_reordered_headers_and_legacy_trailing_dynamic_headers():
    from src.modules.cdr_reporting import (
        CATALOG_HEADERS, TRAILING_DYNAMIC_CATALOG_HEADERS, CatalogEntry,
        catalogue_csv, parse_catalog_csv,
    )

    entry = CatalogEntry(
        slide=1, slide_title='Quality', slide_subtitle='',
        layout='Title + dynamic rows + dynamic columns + comments down',
        chart_title='Signal', cdr_source='CDR-Data', kpi='LTE_RSRP',
        chart_type='Histogram Bars', legend='', filters='',
        grouping_rows='Vendor_Only', grouping_columns='Campaign',
        dynamic_rows_field='Vendor_Only', dynamic_columns_field='Campaign',
    )
    canonical_rows = list(csv.DictReader(io.StringIO(catalogue_csv([entry]).decode('utf-8'))))
    canonical_row = canonical_rows[0]

    reordered_headers = (*CATALOG_HEADERS[6:], *CATALOG_HEADERS[:6])
    reordered = io.StringIO()
    writer = csv.DictWriter(reordered, fieldnames=reordered_headers, lineterminator='\n')
    writer.writeheader()
    writer.writerow(canonical_row)
    restored = parse_catalog_csv(reordered.getvalue(), 'nsa')
    assert (restored[0].dynamic_rows_field, restored[0].dynamic_columns_field) == ('Vendor_Only', 'Campaign')

    trailing_headers = TRAILING_DYNAMIC_CATALOG_HEADERS
    trailing = io.StringIO()
    writer = csv.DictWriter(trailing, fieldnames=trailing_headers, lineterminator='\n')
    writer.writeheader()
    writer.writerow(canonical_row)
    restored_trailing = parse_catalog_csv(trailing.getvalue(), 'nsa')
    assert (restored_trailing[0].dynamic_rows_field, restored_trailing[0].dynamic_columns_field) == ('Vendor_Only', 'Campaign')


def test_catalogue_csv_rejects_duplicate_canonical_header_aliases():
    from src.modules.cdr_reporting import CatalogEntry, catalogue_csv, parse_catalog_csv

    exported = catalogue_csv([CatalogEntry(
        slide=1, slide_title='Quality', slide_subtitle='', layout='Title + 1 rows + 1 columns',
        chart_title='Signal', cdr_source='CDR-Data', kpi='LTE_RSRP',
        chart_type='Histogram Bars', legend='', filters='',
        grouping_rows='Operator', grouping_columns='Campaign',
    )]).decode('utf-8')
    header, *rows = exported.splitlines()
    duplicate_header = header.replace('Source Dataset', 'Source Dataset,CDR source')
    duplicate_row = rows[0].replace('CDR-Data', 'CDR-Data,CDR-Data', 1)

    with pytest.raises(ValueError, match='duplicate column names or aliases'):
        parse_catalog_csv('\n'.join([duplicate_header, duplicate_row]), 'nsa')


@pytest.mark.parametrize(
    'layout,count,error',
    [
        ('Title + 2 rows + dynamic columns', 2, 'requires Dynamic Columns Field'),
        ('Title + dynamic rows + 2 columns', 2, 'requires Dynamic Rows Field'),
        ('Title + dynamic rows + dynamic columns', 1, 'requires Dynamic Rows Field and Dynamic Columns Field'),
    ],
)
def test_dynamic_layout_requires_fields_for_each_dynamic_axis(layout, count, error):
    from src.modules.cdr_reporting import CatalogEntry, catalogue_csv, parse_catalog_csv

    entries = [CatalogEntry(
        slide=1, slide_title='Quality', slide_subtitle='', layout=layout,
        chart_title=f'Signal {index}', cdr_source='CDR-Data', kpi='LTE_RSRP',
        chart_type='Histogram Bars', legend='', filters='',
        grouping_rows='Operator', grouping_columns='Campaign',
        dynamic_rows_field='', dynamic_columns_field='', dynamic_field='',
    ) for index in range(count)]

    with pytest.raises(ValueError, match=error):
        parse_catalog_csv(catalogue_csv(entries), 'nsa')


def test_catalogue_csv_renames_source_dataset_and_accepts_the_legacy_header():
    from src.modules.cdr_reporting import CatalogEntry, catalogue_csv, parse_catalog_csv

    entry = CatalogEntry(
        slide=1, slide_title='Quality', slide_subtitle='', layout='Title + 1 rows + 1 columns',
        chart_title='Signal', cdr_source='CDR-Voice', kpi='Call_Status',
        chart_type='Average Vertical Bars', legend='', filters='',
        grouping_rows='Operator', grouping_columns='Campaign',
    )
    current = catalogue_csv([entry])
    assert current.splitlines()[0].decode('utf-8').split(',')[7] == 'Source Dataset'

    legacy = current.replace(b'Source Dataset', b'CDR source', 1)
    restored = parse_catalog_csv(legacy, 'nsa')
    exported = catalogue_csv(restored)

    assert restored[0].cdr_source == 'CDR-Voice'
    assert exported.splitlines()[0].decode('utf-8').split(',')[7] == 'Source Dataset'


def test_compact_grids_and_dynamic_title_parts():
    from dataclasses import replace
    from src.modules.cdr_reporting import CatalogEntry, chart_title_parts
    from src.modules.report_layouts import compact_grid_layout

    assert compact_grid_layout('Title + 2 rows + 6 columns + comments down')
    assert compact_grid_layout('Title + 5 rows + 2 columns')
    assert not compact_grid_layout('Title + 1 rows + 3 columns + comments down')
    assert not compact_grid_layout('Title + 2 rows + 2 columns + comments right')
    assert not compact_grid_layout('Title Page')
    entry = CatalogEntry(
        4, 'RSRP', '', 'Title + 2 rows + 6 columns + comments down', 'LTE RSRP histogram – Data – EE',
        'CDR-Data', 'LTE_PCell_RSRP_Avg', 'Histogram Bars', '', 'Operator', 'Campaign', 'Campaign', 'Right',
    )
    assert chart_title_parts(replace(entry, dynamic_column_value='EE')) == ('EE', 'LTE RSRP histogram – Data')
    assert chart_title_parts(entry) == ('', 'LTE RSRP histogram – Data – EE')
