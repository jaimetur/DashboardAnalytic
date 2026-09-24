from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path


def _database_with_query_rows(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Value, Category TEXT)')
        connection.executemany(
            'INSERT INTO dataset_rows_1 VALUES (?, ?)',
            [(1, 'Alpha'), (2, 'Alpha'), ('2', 'Alpha'), (3, 'Beta'), (None, 'Beta')],
        )


def test_query_builder_reads_committed_wal_rows(tmp_path: Path) -> None:
    from src.modules.query_builder import execute_query, iter_query_csv, query_column_values

    database_path = tmp_path / 'query-builder-wal.sqlite'
    writer = sqlite3.connect(database_path)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE dataset_rows_7 (Value TEXT)')
        writer.execute("INSERT INTO dataset_rows_7 VALUES ('visible')")
        writer.commit()
        datasets = [{'id': 7, 'name': 'source.csv', 'kind': 'data'}]
        query_sql = 'SELECT Value FROM selected_data'

        assert execute_query(database_path, datasets, query_sql, include_total=True) == (
            ['Value'], [('visible',)], False, ['selected_data'], 1,
        )
        assert ''.join(iter_query_csv(database_path, datasets, query_sql)) == 'Value\r\nvisible\r\n'
        assert query_column_values(database_path, datasets, query_sql, 0) == (['visible'], False)
    finally:
        writer.close()


def test_query_builder_column_filters_apply_before_pagination_and_csv(tmp_path: Path) -> None:
    from src.modules.query_builder import execute_query, iter_query_csv

    database_path = tmp_path / 'query-builder-filters.sqlite'
    _database_with_query_rows(database_path)
    datasets = [{'id': 1, 'name': 'data.csv', 'kind': 'data'}]
    query_sql = '''
        SELECT Value AS result_value, Category AS category, Category AS category
        FROM selected_data
        ORDER BY source_row_id
    '''
    filters = [
        {'index': 0, 'values': [2, None]},
        {'index': 1, 'values': ['Alpha', 'Beta']},
    ]

    first_page = execute_query(
        database_path, datasets, query_sql, row_limit=1, offset=0,
        include_total=True, column_filters=filters,
    )
    second_page = execute_query(
        database_path, datasets, query_sql, row_limit=1, offset=1,
        include_total=True, column_filters=filters,
    )

    assert first_page == (['result_value', 'category', 'category:1'], [(2, 'Alpha', 'Alpha')], True, ['selected_data'], 2)
    assert second_page == (['result_value', 'category', 'category:1'], [(None, 'Beta', 'Beta')], False, ['selected_data'], 2)
    assert ''.join(iter_query_csv(database_path, datasets, query_sql, column_filters=filters)) == (
        'result_value,category,category:1\r\n2,Alpha,Alpha\r\n,Beta,Beta\r\n'
    )


def test_query_builder_filter_values_ignores_own_filter_and_supports_search(client, monkeypatch, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 1, 'file_name': 'filters.csv', 'dataset_kind': 'data', 'status': 'ready'},
    ])
    monkeypatch.setattr(app_module, 'MAX_PREVIEW_ROWS', 1)
    database_path = tmp_path / 'query-builder-filter-values.sqlite'
    monkeypatch.setattr(app_module, 'active_workspace', replace(app_module.active_workspace, database_path=database_path))
    _database_with_query_rows(database_path)

    response = client.post('/api/query-builder/filter-values', json={
        'dataset_ids': [1],
        'query_sql': 'SELECT Value, Category FROM selected_data ORDER BY source_row_id',
        'column_index': 1,
        'column_filters': [
            {'index': 0, 'values': [2]},
            {'index': 1, 'values': ['not selected']},
        ],
        'search': 'ALP',
    })

    assert response.status_code == 200, response.text
    assert response.json() == {'values': ['Alpha'], 'truncated': False}

    query_sql = 'SELECT Value, Category FROM selected_data ORDER BY source_row_id'
    run_payload = {
        'dataset_ids': [1],
        'query_sql': query_sql,
        'column_filters': [
            {'index': 0, 'values': [2, None]},
            {'index': 1, 'values': ['Alpha', 'Beta']},
        ],
    }
    first_page = client.post('/api/query-builder/run', json={
        **run_payload, 'execution_id': 'filter-page-1', 'offset': 0,
    })
    second_page = client.post('/api/query-builder/run', json={
        **run_payload, 'execution_id': 'filter-page-2', 'offset': 1,
    })
    assert first_page.status_code == second_page.status_code == 200
    assert first_page.json()['rows'] == [[2, 'Alpha']]
    assert first_page.json()['total_rows'] == 2
    assert first_page.json()['next_offset'] == 1
    assert second_page.json()['rows'] == [[None, 'Beta']]
    assert second_page.json()['next_offset'] is None

    duplicate_header_query = 'SELECT Value AS x, Category AS x FROM selected_data ORDER BY source_row_id'
    duplicate_header_run = client.post('/api/query-builder/run', json={
        'dataset_ids': [1],
        'query_sql': duplicate_header_query,
        'column_filters': [{'index': 1, 'values': ['Alpha']}],
        'execution_id': 'duplicate-header-run',
        'offset': 0,
    })
    assert duplicate_header_run.status_code == 200, duplicate_header_run.text
    assert duplicate_header_run.json()['columns'] == ['x', 'x:1']
    assert duplicate_header_run.json()['rows'] == [[1, 'Alpha']]
    assert duplicate_header_run.json()['total_rows'] == 3

    duplicate_header_values = client.post('/api/query-builder/filter-values', json={
        'dataset_ids': [1],
        'query_sql': duplicate_header_query,
        'column_index': 1,
        'column_filters': [
            {'index': 0, 'values': [2]},
            {'index': 1, 'values': ['not selected']},
        ],
    })
    assert duplicate_header_values.status_code == 200, duplicate_header_values.text
    assert duplicate_header_values.json() == {'values': ['Alpha'], 'truncated': False}

    export_response = client.post('/api/query-builder/export', json=run_payload)
    assert export_response.status_code == 200
    assert export_response.text == 'Value,Category\r\n2,Alpha\r\n,Beta\r\n'

    empty_filter = client.post('/api/query-builder/filter-values', json={
        'dataset_ids': [1],
        'query_sql': 'SELECT Value, Category FROM selected_data ORDER BY source_row_id',
        'column_index': 0,
        'column_filters': [{'index': 1, 'values': []}],
    })
    assert empty_filter.status_code == 200
    assert empty_filter.json() == {'values': [], 'truncated': False}
