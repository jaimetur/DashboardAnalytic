"""Read-only SQL workspace queries over explicitly selected CDR sources."""

from __future__ import annotations

import csv
import io
import math
import re
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Callable


MAX_PREVIEW_ROWS = 50
MAX_FILTER_VALUES = 500
MAX_FILTER_OPTIONS = 200
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def normalize_query(query: str) -> str:
    query = str(query or '').strip().rstrip(';').strip()
    if not query:
        raise ValueError('Enter a SQL query.')
    if ';' in query or not re.match(r'^(?:select|with)\b', query, flags=re.I):
        raise ValueError('Only one SELECT query (optionally starting with WITH) is allowed.')
    return query


def _selected_views(connection: sqlite3.Connection, datasets: Iterable[dict[str, Any]]) -> list[str]:
    """Create one temporary union view per selected CDR kind.

    A view contains every physical source column, with NULL for a heading not
    present in one selected file. This preserves ad-hoc access to CDR fields
    without widening the persistent combined reporting tables.
    """
    grouped: dict[str, list[dict[str, Any]]] = {'data': [], 'voice': [], 'speech': []}
    for dataset in datasets:
        kind = str(dataset['kind'])
        if kind in grouped:
            grouped[kind].append(dataset)
    created: list[str] = []
    for kind, rows in grouped.items():
        if not rows:
            continue
        schemas: dict[int, list[str]] = {}
        all_columns: list[str] = []
        for row in rows:
            table = f"dataset_rows_{int(row['id'])}"
            cols = [str(item[1]) for item in connection.execute(f'PRAGMA table_info({_quote(table)})')]
            schemas[int(row['id'])] = cols
            for column in cols:
                if column not in all_columns:
                    all_columns.append(column)
        selects: list[str] = []
        for row in rows:
            dataset_id = int(row['id'])
            table = f'dataset_rows_{dataset_id}'
            known = set(schemas[dataset_id])
            values = [
                f'{dataset_id} AS source_dataset_id',
                f'{repr(str(row["name"]))} AS source_dataset_name',
                f'rowid AS source_row_id',
            ]
            values.extend(_quote(column) if column in known else f'NULL AS {_quote(column)}' for column in all_columns)
            selects.append(f"SELECT {', '.join(values)} FROM {_quote(table)}")
        view = f'selected_{kind}'
        connection.execute(f'CREATE TEMP VIEW {_quote(view)} AS ' + ' UNION ALL '.join(selects))
        created.append(view)
    return created


def _read_only_authorizer(action: int, _arg1: str | None, _arg2: str | None, _database: str | None, _source: str | None) -> int:
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def _result_columns(connection: sqlite3.Connection, query: str) -> list[str]:
    cursor = connection.execute(f'SELECT * FROM ({query}) LIMIT 0')
    return [str(item[0]) for item in cursor.description or []]


def _normalize_column_filters(
    column_filters: Any,
    columns: list[str],
    *,
    exclude_index: int | None = None,
) -> list[tuple[int, list[Any]]]:
    if column_filters is None:
        return []
    if not isinstance(column_filters, list):
        raise ValueError('Column filters must be a list.')
    normalized: list[tuple[int, list[Any]]] = []
    seen: set[int] = set()
    for item in column_filters:
        if not isinstance(item, dict):
            raise ValueError('Each column filter must include an index and values.')
        index = item.get('index')
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(columns):
            raise ValueError('A column filter refers to an invalid result column.')
        if index in seen:
            raise ValueError('A result column can only have one filter.')
        seen.add(index)
        values = item.get('values')
        if not isinstance(values, list):
            raise ValueError('Column filter values must be a list.')
        if len(values) > MAX_FILTER_VALUES:
            raise ValueError(f'A column filter can contain at most {MAX_FILTER_VALUES} values.')
        if index == exclude_index:
            continue
        for value in values:
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError('Column filter values must be JSON scalar values.')
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError('Column filter values must be finite numbers.')
        normalized.append((index, values))
    return normalized


def _filter_predicates(
    filters: list[tuple[int, list[Any]]], columns: list[str],
) -> tuple[str, list[Any]]:
    predicates: list[str] = []
    parameters: list[Any] = []
    for index, values in filters:
        column = _quote(columns[index])
        if not values:
            predicates.append('0')
            continue
        alternatives: list[str] = []
        for value in values:
            if value is None:
                alternatives.append(f'{column} IS NULL')
            else:
                # The type check keeps a selected text value such as "1" distinct
                # from a numeric 1 while retaining SQLite's normal scalar equality.
                sqlite_type = 'text' if isinstance(value, str) else 'real' if isinstance(value, float) else 'integer'
                alternatives.append(f"(typeof({column}) = '{sqlite_type}' AND {column} IS ?)")
                parameters.append(value)
        predicates.append('(' + ' OR '.join(alternatives) + ')')
    if not predicates:
        return '', parameters
    return ' WHERE ' + ' AND '.join(predicates), parameters


def _filtered_query(
    query: str,
    columns: list[str],
    filters: list[tuple[int, list[Any]]],
) -> tuple[str, list[Any]]:
    where_clause, parameters = _filter_predicates(filters, columns)
    return f'SELECT * FROM ({query}) AS _query_builder_rows{where_clause}', parameters


def execute_query(
    database_path: Path, datasets: list[dict[str, Any]], query: str, row_limit: int = MAX_PREVIEW_ROWS,
    cancel_requested: Callable[[], bool] | None = None,
    offset: int = 0,
    include_total: bool = False,
    column_filters: Any = None,
) -> tuple[list[str], list[tuple[Any, ...]], bool, list[str]] | tuple[list[str], list[tuple[Any, ...]], bool, list[str], int]:
    query = normalize_query(query)
    if not datasets:
        raise ValueError('Select at least one ready CDR source.')
    if offset < 0:
        raise ValueError('Query offset must be non-negative.')
    # The workspace database is normally in WAL mode. Immutable read access
    # avoids creating lock sidecars while an interactive query is running.
    connection = sqlite3.connect(f'file:{database_path.resolve()}?mode=ro&immutable=1', uri=True, timeout=30.0)
    try:
        if cancel_requested:
            connection.set_progress_handler(lambda: 1 if cancel_requested() else 0, 1_000)
        views = _selected_views(connection, datasets)
        connection.set_authorizer(_read_only_authorizer)
        columns = _result_columns(connection, query) if column_filters is not None else []
        filters = _normalize_column_filters(column_filters, columns) if column_filters is not None else []
        result_query, filter_parameters = _filtered_query(query, columns, filters) if filters else (query, [])
        cursor = connection.execute(
            f'SELECT * FROM ({result_query}) LIMIT ? OFFSET ?' if filters else f'SELECT * FROM ({query}) LIMIT ? OFFSET ?',
            (*filter_parameters, max(1, int(row_limit)) + 1, offset),
        )
        rows = cursor.fetchmany(max(1, int(row_limit)) + 1)
        columns = [str(item[0]) for item in cursor.description or []]
        truncated = len(rows) > row_limit
        page = (columns, [tuple(row) for row in rows[:row_limit]], truncated, views)
        if include_total:
            count_query = f'SELECT COUNT(*) FROM ({result_query})' if filters else f'SELECT COUNT(*) FROM ({query})'
            total_rows = int(connection.execute(count_query, filter_parameters).fetchone()[0])
            return (*page, total_rows)
        return page
    finally:
        connection.close()


def iter_query_csv(
    database_path: Path, datasets: list[dict[str, Any]], query: str,
    on_complete: Callable[[int], None] | None = None,
    column_filters: Any = None,
) -> Iterator[str]:
    query = normalize_query(query)
    if not datasets:
        raise ValueError('Select at least one ready CDR source.')
    connection = sqlite3.connect(
        f'file:{database_path.resolve()}?mode=ro&immutable=1', uri=True,
        timeout=30.0, check_same_thread=False,
    )
    try:
        _selected_views(connection, datasets)
        connection.set_authorizer(_read_only_authorizer)
        columns = _result_columns(connection, query) if column_filters is not None else []
        filters = _normalize_column_filters(column_filters, columns) if column_filters is not None else []
        if filters:
            result_query, parameters = _filtered_query(query, columns, filters)
            cursor = connection.execute(result_query, parameters)
        else:
            cursor = connection.execute(query)
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow([str(item[0]) for item in cursor.description or []])
        yield output.getvalue()
        row_count = 0
        while rows := cursor.fetchmany(1_000):
            output.seek(0)
            output.truncate(0)
            writer.writerows(rows)
            row_count += len(rows)
            yield output.getvalue()
        if on_complete:
            on_complete(row_count)
    finally:
        connection.close()


def query_column_values(
    database_path: Path,
    datasets: list[dict[str, Any]],
    query: str,
    column_index: int,
    column_filters: Any = None,
    search: str = '',
) -> tuple[list[Any], bool]:
    """Return distinct result values, constrained by the other active filters."""
    query = normalize_query(query)
    if not datasets:
        raise ValueError('Select at least one ready CDR source.')
    if isinstance(column_index, bool) or not isinstance(column_index, int) or column_index < 0:
        raise ValueError('Select a valid result column.')
    if not isinstance(search, str):
        raise ValueError('Filter value search must be text.')
    if len(search) > 200:
        raise ValueError('Filter value search is too long.')
    connection = sqlite3.connect(f'file:{database_path.resolve()}?mode=ro&immutable=1', uri=True, timeout=30.0)
    try:
        _selected_views(connection, datasets)
        connection.create_function('casefold', 1, lambda value: str(value).casefold() if value is not None else None)
        connection.set_authorizer(_read_only_authorizer)
        columns = _result_columns(connection, query)
        if column_index >= len(columns):
            raise ValueError('Select a valid result column.')
        filters = _normalize_column_filters(column_filters, columns, exclude_index=column_index)
        result_query, parameters = _filtered_query(query, columns, filters) if filters else (query, [])
        selected_column = _quote(columns[column_index])
        search_clause = ''
        if search:
            search_clause = f' WHERE instr(casefold(CAST(_query_builder_filter_rows.{selected_column} AS TEXT)), casefold(?)) > 0'
            parameters = [*parameters, search]
        cursor = connection.execute(
            f'SELECT DISTINCT _query_builder_filter_rows.{selected_column} AS _query_builder_filter_value '
            f'FROM ({result_query}) AS _query_builder_filter_rows{search_clause} '
            'ORDER BY _query_builder_filter_value LIMIT ?',
            (*parameters, MAX_FILTER_OPTIONS + 1),
        )
        rows = cursor.fetchall()
        return [row[0] for row in rows[:MAX_FILTER_OPTIONS]], len(rows) > MAX_FILTER_OPTIONS
    finally:
        connection.close()


ANGELO_OVERLAP_QUERY = """WITH fdtt AS MATERIALIZED (
  SELECT
    CASE WHEN source_dataset_name LIKE '%Q1%' THEN 'Q1'
         WHEN source_dataset_name LIKE '%Q2%' THEN 'Q2' ELSE source_dataset_name END AS quarter,
    source_dataset_id, source_dataset_name, source_row_id,
    Operator, Test_Name, Test_Start_Time, Test_End_Time,
    Mean_Data_Rate, NR_DL_PCell_ARFCN, NR_DL_PCell_Band, Cell_ID
  FROM selected_data
  WHERE Test_Name IN ('FDTT http DL MT', 'FDTT UDP UL ST')
    AND Test_Result = 'Completed'
    AND (NR_DL_PCell_Band LIKE '%78%' OR CAST(NR_B78_Total_Time AS REAL) > 0)
    AND NR_DL_PCell_ARFCN IS NOT NULL
    AND (lower(Operator) LIKE 'vodafone%' OR lower(Operator) IN ('3', 'three uk', 'three'))
), overlapping_sessions AS MATERIALIZED (
  SELECT DISTINCT f.source_dataset_id, f.source_row_id
  FROM fdtt f
  JOIN fdtt o
    ON o.quarter = f.quarter
   AND o.NR_DL_PCell_ARFCN = f.NR_DL_PCell_ARFCN
   AND o.Test_Start_Time < f.Test_End_Time
   AND o.Test_End_Time > f.Test_Start_Time
   AND (
     (lower(f.Operator) LIKE 'vodafone%' AND lower(o.Operator) IN ('3', 'three uk', 'three'))
     OR (lower(f.Operator) IN ('3', 'three uk', 'three') AND lower(o.Operator) LIKE 'vodafone%')
   )
), classified AS (
  SELECT f.*,
    CASE WHEN overlapping_sessions.source_row_id IS NOT NULL THEN 'Overlapping VF-Three'
         ELSE 'No VF-Three overlap' END AS overlap_status
  FROM fdtt f
  LEFT JOIN overlapping_sessions
    ON overlapping_sessions.source_dataset_id = f.source_dataset_id
   AND overlapping_sessions.source_row_id = f.source_row_id
)
SELECT quarter, Operator AS operator, Test_Name AS test_name,
       SUM(CASE WHEN overlap_status = 'Overlapping VF-Three' THEN 1 ELSE 0 END) AS overlap_sessions,
       ROUND(AVG(CASE WHEN overlap_status = 'Overlapping VF-Three' THEN CAST(Mean_Data_Rate AS REAL) END), 2) AS overlap_avg_Mean_Data_Rate,
       SUM(CASE WHEN overlap_status = 'No VF-Three overlap' THEN 1 ELSE 0 END) AS non_overlap_sessions,
       ROUND(AVG(CASE WHEN overlap_status = 'No VF-Three overlap' THEN CAST(Mean_Data_Rate AS REAL) END), 2) AS non_overlap_avg_Mean_Data_Rate
FROM classified
GROUP BY quarter, Operator, Test_Name
ORDER BY quarter, Operator, Test_Name"""
