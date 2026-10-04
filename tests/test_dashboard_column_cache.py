import itertools
import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.modules.dashboard_column_cache import (
    CacheSource,
    ColumnCache,
    Segment,
    SelectionTerms,
    StaleSegment,
    read_frame,
)

COLUMNS = ('int_col', 'float_col', 'int_null', 'sparse', 'text', 'mixed', 'big', 'int_float', 'empty_text')


def _rows():
    rows = []
    for dataset_id in (3, 5, 9):
        for index in range(40):
            rows.append({
                'dataset_id': dataset_id,
                'int_col': index * dataset_id,
                'float_col': None if index % 7 == 0 else index / 3 + dataset_id,
                'int_null': None if index % 5 == 0 else index,
                # NULL in every row of dataset 3, numbers elsewhere.
                'sparse': None if dataset_id == 3 else index * 1.5,
                'text': None if index % 6 == 0 else f'City {index % 4} É',
                'mixed': index if index % 3 == 0 else (f'v{index}' if index % 3 == 1 else None),
                'big': 2 ** 62 + index if dataset_id == 9 else index,
                'int_float': index if dataset_id == 5 else index + 0.5,
                'empty_text': '' if index % 2 else None,
                'operator': ['EE', 'O2 (UK)', 'Vodafone UK', None][index % 4],
                'event_start_time': None if index == 13 else f'2026-0{1 + index % 3}-{10 + index % 9} 10:00:00',
                'source_sheet': ['CDR', 'Lists', None][index % 3],
            })
    # Interleave datasets in table order, as appended uploads can do.
    rows.sort(key=lambda row: (row['int_col'] % 11, row['dataset_id']))
    return rows


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / 'cdr.db'
    connection = sqlite3.connect(path)
    names = ['dataset_id', *COLUMNS, 'operator', 'event_start_time', 'source_sheet']
    connection.execute(f'CREATE TABLE reporting_rows_data ({", ".join(names)})')
    connection.execute(
        'CREATE INDEX idx_reporting_rows_data_dataset_event_time_date '
        'ON reporting_rows_data (dataset_id, date(CAST("event_start_time" AS TEXT)))'
    )
    connection.executemany(
        f'INSERT INTO reporting_rows_data VALUES ({", ".join("?" for _ in names)})',
        [tuple(row[name] for name in names) for row in _rows()],
    )
    connection.commit()
    connection.close()
    return path


def _cache(tmp_path, memory_bytes=64 * 1024 ** 2):
    return ColumnCache(tmp_path / 'cache', memory_bytes=memory_bytes, disk_bytes=1024 ** 3)


def _assert_identical(actual: pd.DataFrame, expected: pd.DataFrame):
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    for column in expected.columns:
        assert actual[column].dtype == expected[column].dtype, column
        if expected[column].dtype == object:
            assert [type(value) for value in actual[column]] == [type(value) for value in expected[column]], column


OPERATOR = 'LOWER(TRIM(CAST("operator" AS TEXT)))'
DATE = 'date(CAST("event_start_time" AS TEXT))'
SHEET = 'LOWER(TRIM(CAST("source_sheet" AS TEXT)))'


@pytest.mark.parametrize('datasets', [(3,), (5, 9), (3, 5, 9), (9, 3)])
@pytest.mark.parametrize('operators', [None, ('ee',), ('o2 (uk)', 'vodafone uk')])
@pytest.mark.parametrize('dates', [None, ('2026-01-01', '2026-02-28'), ('2026-03-01', None)])
def test_cached_frames_match_sqlite_reads(tmp_path, database, datasets, operators, dates):
    connect = lambda: sqlite3.connect(database)
    source = CacheSource('data', 'reporting_rows_data')
    cache = _cache(tmp_path)
    terms = SelectionTerms(
        values=((OPERATOR, frozenset(operators)),) if operators else (),
        date=(DATE, *dates) if dates else None,
        excluded_sheets=(SHEET, frozenset({'lists'})),
    )
    clauses = [f'dataset_id IN ({", ".join(str(item) for item in datasets)})']
    if operators:
        clauses.append(f'{OPERATOR} IN ({", ".join(repr(item) for item in operators)})')
    if dates:
        if dates[0]:
            clauses.append(f"{DATE} >= date('{dates[0]}')")
        if dates[1]:
            clauses.append(f"{DATE} <= date('{dates[1]}')")
    clauses.append(f'("source_sheet" IS NULL OR {SHEET} NOT IN (\'lists\'))')
    where = ' AND '.join(f'({clause})' for clause in clauses)
    segments = [Segment(source, dataset_id, 'r1') for dataset_id in sorted(datasets)]
    columns = [(name, f'"{name}"') for name in COLUMNS]
    for order, order_by in (
        ('dataset_rowid', 'dataset_id, rowid'),
        ('dataset_date_rowid', f'dataset_id, {DATE}, rowid'),
        ('rowid', 'rowid'),
    ):
        expected = pd.read_sql_query(
            f'SELECT {", ".join(name for name in COLUMNS)} FROM reporting_rows_data WHERE {where} ORDER BY {order_by}',
            sqlite3.connect(database),
        )
        _assert_identical(read_frame(cache, connect, segments, columns, terms, order), expected)


def test_every_column_subset_keeps_read_sql_query_types(tmp_path, database):
    connect = lambda: sqlite3.connect(database)
    source = CacheSource('data', 'reporting_rows_data')
    cache = _cache(tmp_path, memory_bytes=1)
    for size in (1, 2):
        for subset in itertools.combinations(COLUMNS, size):
            for datasets in ((3,), (5,), (9,), (3, 5), (5, 9), (3, 9)):
                columns = [(name, f'"{name}"') for name in subset]
                segments = [Segment(source, dataset_id, 'r1') for dataset_id in datasets]
                expected = pd.read_sql_query(
                    f'SELECT {", ".join(subset)} FROM reporting_rows_data '
                    f'WHERE dataset_id IN ({", ".join(map(str, datasets))}) ORDER BY dataset_id, rowid',
                    sqlite3.connect(database),
                )
                _assert_identical(read_frame(cache, connect, segments, columns, SelectionTerms(), 'dataset_rowid'), expected)


def test_empty_selection_matches_empty_sqlite_frame(tmp_path, database):
    connect = lambda: sqlite3.connect(database)
    source = CacheSource('data', 'reporting_rows_data')
    terms = SelectionTerms(values=((OPERATOR, frozenset({'unknown'})),))
    actual = read_frame(_cache(tmp_path), connect, [Segment(source, 3, 'r1')], [('text', '"text"')], terms, 'dataset_rowid')
    expected = pd.read_sql_query('SELECT text FROM reporting_rows_data WHERE 0', sqlite3.connect(database))
    pd.testing.assert_frame_equal(actual, expected)
    unavailable = SelectionTerms(values=((None, frozenset({'ee'})),))
    assert read_frame(_cache(tmp_path), connect, [Segment(source, 3, 'r1')], [('text', '"text"')], unavailable, 'dataset_rowid').empty


def test_union_branch_aliases_share_physical_columns(tmp_path, database):
    connect = lambda: sqlite3.connect(database)
    projection = (('Latitude', 'NULLIF(TRIM(CAST("float_col" AS TEXT)), \'\')'), ('CDR_Type', "'Data'"),
                  ('dataset_id', '"dataset_id"'), ('operator', '"operator"'))
    branch = CacheSource('data', 'reporting_rows_data', projection)
    cache = _cache(tmp_path)
    branch_sql = ('SELECT NULLIF(TRIM(CAST("float_col" AS TEXT)), \'\') AS "Latitude", \'Data\' AS "CDR_Type", '
                  '"dataset_id" AS "dataset_id", "operator" AS "operator", rowid AS "row" FROM reporting_rows_data')
    expected = pd.read_sql_query(
        f'SELECT "Latitude", "CDR_Type", {OPERATOR} AS "op" FROM ({branch_sql}) WHERE dataset_id IN (5, 9) '
        f'AND {OPERATOR} IN (\'ee\') ORDER BY dataset_id, "row"',
        sqlite3.connect(database),
    )
    terms = SelectionTerms(values=((OPERATOR, frozenset({'ee'})),))
    columns = [('Latitude', '"Latitude"'), ('CDR_Type', '"CDR_Type"'), ('op', OPERATOR)]
    segments = [Segment(branch, dataset_id, 'r1') for dataset_id in (5, 9)]
    _assert_identical(read_frame(cache, connect, segments, columns, terms, 'dataset_rowid'), expected)
    # The alias expression is cached by its physical SQL, shared with the table source.
    assert branch.physical('"Latitude"') == '(NULLIF(TRIM(CAST("float_col" AS TEXT)), \'\'))'
    assert branch.physical("'\"Latitude\"'") == "'\"Latitude\"'"


def test_cached_columns_persist_and_detect_changed_rows(tmp_path, database):
    source = CacheSource('data', 'reporting_rows_data')
    segment = Segment(source, 5, 'r1')
    calls = []

    def connect():
        calls.append(1)
        return sqlite3.connect(database)

    first = _cache(tmp_path)
    read_frame(first, connect, [segment], [('text', '"text"')], SelectionTerms(), 'dataset_rowid')
    assert len(calls) == 1
    # Another process instance reuses the persisted columns without SQLite.
    second = _cache(tmp_path)
    read_frame(second, connect, [segment], [('text', '"text"')], SelectionTerms(), 'dataset_rowid')
    assert len(calls) == 1
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM reporting_rows_data WHERE dataset_id = 5 AND int_col = 10")
    with pytest.raises(StaleSegment):
        read_frame(second, connect, [segment], [('int_col', '"int_col"')], SelectionTerms(), 'dataset_rowid')
    second.invalidate(segment)
    rebuilt = read_frame(second, connect, [segment], [('int_col', '"int_col"')], SelectionTerms(), 'dataset_rowid')
    assert 10 not in set(rebuilt['int_col'])


def test_new_revision_replaces_previous_segment_files(tmp_path, database):
    connect = lambda: sqlite3.connect(database)
    source = CacheSource('data', 'reporting_rows_data')
    cache = _cache(tmp_path)
    read_frame(cache, connect, [Segment(source, 5, 'r1')], [('text', '"text"')], SelectionTerms(), 'dataset_rowid')
    read_frame(cache, connect, [Segment(source, 5, 'r2')], [('text', '"text"')], SelectionTerms(), 'dataset_rowid')
    assert len([path for path in (cache.root / 'reporting_rows_data' / '5').iterdir() if path.is_dir()]) == 1


def test_float_assembly_matches_large_integer_conversion(tmp_path):
    path = tmp_path / 'big.db'
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE t (dataset_id, value)')
    connection.executemany('INSERT INTO t VALUES (?, ?)', [(1, 2 ** 53 + 1), (1, 9_007_199_254_740_993), (2, 0.5), (2, None)])
    connection.commit()
    connection.close()
    source = CacheSource('data', 't', has_event_time=False)
    actual = read_frame(_cache(tmp_path), lambda: sqlite3.connect(path),
                        [Segment(source, 1, 'r'), Segment(source, 2, 'r')], [('value', '"value"')], SelectionTerms(), 'dataset_rowid')
    expected = pd.read_sql_query('SELECT value FROM t ORDER BY dataset_id, rowid', sqlite3.connect(path))
    _assert_identical(actual, expected)
    assert np.isnan(actual['value'].iloc[-1])
