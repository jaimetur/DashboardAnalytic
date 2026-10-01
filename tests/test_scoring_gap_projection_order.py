from src.modules.scoring_exports import _hierarchy_gap_projection


def _column(column_id, operator, *, is_reference=False):
    return {
        'id': column_id,
        'operator': operator,
        'is_reference': is_reference,
        'context': {},
    }


def _kpi(code, category, peer_gap):
    return {
        'row_type': 'kpi',
        'kpi_code': code,
        'category': category,
        'gaps': {'EE': None, 'O2 UK': peer_gap, 'Three UK': peer_gap},
        'gap_colors': {},
    }


def _subtotal(category, peer_gap):
    return {
        'row_type': 'category',
        'kpi_code': '',
        'category': category,
        'gaps': {'EE': None, 'O2 UK': peer_gap, 'Three UK': peer_gap},
        'gap_colors': {},
    }


def _matrix(rows, *, table_mode='expanded'):
    return {
        'operators': ['EE', 'O2 UK', 'Three UK'],
        'operator_styles': {'EE': {}, 'O2 UK': {}, 'Three UK': {}},
        'rows': rows,
        'total': {'gaps': {'EE': None, 'O2 UK': 2.0}},
        'table_mode': table_mode,
    }


def test_combined_hierarchy_projection_preserves_definition_order():
    source_rows = [
        _kpi('KPI-A', 'Category A', 1.0),
        _kpi('KPI-B', 'Category B', 5.0),
        _kpi('KPI-C', 'Category A', 4.0),
    ]
    projected = _hierarchy_gap_projection(
        _matrix(source_rows),
        [
            _column('EE', 'EE', is_reference=True),
            _column('O2 UK', 'O2 UK'),
            _column('Three UK', 'Three UK'),
        ],
    )

    assert [row['kpi_code'] for row in projected['rows']] == ['KPI-A', 'KPI-B', 'KPI-C']


def test_individual_expanded_projection_reranks_kpis_and_places_subtotal_after_last_kpi():
    source_rows = [
        _kpi('KPI-A1', 'Category A', 1.0),
        _kpi('KPI-B1', 'Category B', 5.0),
        _kpi('KPI-A2', 'Category A', 4.0),
        _subtotal('Category A', 2.5),
        _subtotal('Category B', 5.0),
    ]
    projected = _hierarchy_gap_projection(
        _matrix(source_rows),
        [_column('EE', 'EE', is_reference=True), _column('O2 UK', 'O2 UK')],
    )

    assert [(row['row_type'], row['kpi_code'] or row['category']) for row in projected['rows']] == [
        ('kpi', 'KPI-B1'),
        ('category', 'Category B'),
        ('kpi', 'KPI-A2'),
        ('kpi', 'KPI-A1'),
        ('category', 'Category A'),
    ]


def test_individual_summary_projection_sorts_by_numeric_signed_gap_descending():
    source_rows = [
        _kpi('KPI-NEGATIVE', 'Category A', -2.0),
        _kpi('KPI-TEN', 'Category B', 10.0),
        _kpi('KPI-ONE', 'Category C', 1.0),
    ]
    projected = _hierarchy_gap_projection(
        _matrix(source_rows, table_mode='summary'),
        [_column('EE', 'EE', is_reference=True), _column('O2 UK', 'O2 UK')],
    )

    assert [row['kpi_code'] for row in projected['rows']] == [
        'KPI-TEN', 'KPI-ONE', 'KPI-NEGATIVE',
    ]
