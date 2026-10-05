"""Non-Qualified Calls: follow-up of every CDR call and test that did not complete.

A Non-Qualified (NQ) call is a Voice or Speech call, or a Data test, whose result
is anything other than ``Completed`` (for example Failed, Dropped or Cutoff).
The module indexes those rows of every ready CDR of the active workspace in
``nq_calls`` and lets the teams follow each one up: a status, a responsible team,
an assignee and a shared comment thread. Every change is recorded in
``nq_call_history`` with its author and time.

Follow-up is keyed by a stable ``call_key`` derived from the call itself (its
service, Operator, Campaign and test/session identifier), so statuses and
comments survive reprocessing or uploading the same CDR again.

When the module produces reports, it registers a Reporting artifact provider with
``core.register_report_artifact_provider`` so Reporting Jobs can include them.
"""

import hashlib
import json
import math
import re
import uuid
from datetime import datetime
from io import BytesIO
from threading import Lock
from typing import Any

from src.modules.column_names import column_identity

NQ_CALLS_TABLE = 'nq_calls'
NQ_CALL_SOURCES_TABLE = 'nq_call_sources'
NQ_CALL_TRACKING_TABLE = 'nq_call_tracking'
NQ_CALL_COMMENTS_TABLE = 'nq_call_comments'
NQ_CALL_HISTORY_TABLE = 'nq_call_history'
NQ_CALL_OPTIONS_TABLE = 'nq_call_options'
# Database Management titles of the module tables.
NQ_TABLE_TITLES = {
    NQ_CALLS_TABLE: 'NQ Calls',
    NQ_CALL_SOURCES_TABLE: 'NQ Call Sources',
    NQ_CALL_TRACKING_TABLE: 'NQ Call Tracking',
    NQ_CALL_COMMENTS_TABLE: 'NQ Call Comments',
    NQ_CALL_HISTORY_TABLE: 'NQ Call History',
    NQ_CALL_OPTIONS_TABLE: 'NQ Call Options',
}
SERVICES = ('voice', 'speech', 'data')
SERVICE_LABELS = {'voice': 'Voice', 'speech': 'Speech', 'data': 'Data'}
QUALIFIED_RESULT = 'completed'
# Bump when the indexed fields or the call key change so every CDR is indexed again.
INDEX_VERSION = 1
TRACKING_FORMAT = 'nq-call-tracking'
TRACKING_FORMAT_VERSION = 1
UNASSIGNED = '__unassigned__'
MAX_COMMENT_LENGTH = 5000
PAGE_SIZES = (25, 50, 100, 200)
OPTION_KINDS = ('status', 'team')
COLOR_PATTERN = re.compile(r'#[0-9a-fA-F]{6}')
DEFAULT_STATUSES = (
    ('Open', '#d14a68', False),
    ('Under Investigation', '#e08a1e', False),
    ('Pending Information', '#6a63c9', False),
    ('Resolved', '#2e8b57', True),
    ('Not Applicable', '#7b8790', True),
)
DEFAULT_TEAMS = (
    ('RAN Optimisation', '#0f6f7d'),
    ('Core Network', '#6941a4'),
    ('IMS / VoLTE', '#b85b20'),
    ('Transport', '#245a96'),
    ('Device & Test Setup', '#5b6b2e'),
)

# Indexed field -> CDR columns, in order of preference.
FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    'campaign': ('Campaign',),
    'operator': ('Operator', 'Operator_A', 'Home_Operator_A', 'Home_Operator'),
    'vendor': ('Vendor',),
    'region': ('region', 'Region'),
    'city': ('city', 'City'),
    'technology': ('Technology', 'technology_primary', 'RAT_A', 'RAT'),
    'test_name': ('Test_Name', 'Type_Of_Test', 'Session_Type', 'Test_Type'),
    'direction': ('Direction', 'Call_Direction'),
    'result': ('status', 'Call_Status', 'Test_Result', 'Test_Status'),
    'start_time': ('event_start_time', 'Call_Start_Time', 'Test_Start_Time'),
    'end_time': ('event_end_time', 'Call_End_Time', 'Test_End_Time'),
    'failure_phase': ('Failure_Phase',),
    'failure_technology': ('Failure_Technology',),
    'failure_classification': ('Failure_Classification',),
    'failure_category': ('Failure_Category',),
    'failure_subcategory': ('Failure_Subcategory',),
    'failure_comment': ('Failure_Comment',),
    'latitude': ('Call_Start_Latitude_A', 'Test_Start_Latitude', 'Playing_Latitude', 'Recording_Latitude'),
    'longitude': ('Call_Start_Longitude_A', 'Test_Start_Longitude', 'Playing_Longitude', 'Recording_Longitude'),
    'cell_id': ('Cell_ID_A', 'Cell_ID', 'Cell_IDs_A', 'LAC_CID_xARFCN_A', 'LAC_CID_xARFCN'),
}
CALL_FIELDS = tuple(FIELD_SOURCES)
NUMERIC_FIELDS = frozenset({'latitude', 'longitude'})
IDENTIFIER_SOURCES = ('Test_ID', 'Session_ID_A', 'Session_id', 'JOIN_ID')
SUBSCRIBER_SOURCES = ('Subscriber',)
# Filters on indexed fields; the tracking filters are handled separately.
FIELD_FILTERS = (
    'service', 'campaign', 'operator', 'vendor', 'region', 'city', 'technology', 'test_name', 'result',
    'failure_classification', 'failure_category',
)
TRACKING_FILTERS = ('status', 'team', 'assignee')
SORT_COLUMNS = {
    'service': 'service', 'start_time': 'start_time', 'operator': 'operator', 'vendor': 'vendor',
    'campaign': 'campaign', 'city': 'city', 'technology': 'technology', 'test_name': 'test_name',
    'result': 'result', 'failure': 'failure_classification', 'status': 'status', 'team': 'team',
    'assignee': 'assignee', 'comments': 'comment_count', 'updated_at': 'updated_at',
}
BREAKDOWNS = (
    ('service', 'By Service'), ('result', 'By Result'), ('status', 'By Status'), ('team', 'By Team'),
    ('failure_classification', 'By Failure Classification'), ('operator', 'By Operator'),
)
SEARCH_FIELDS = (
    'operator', 'vendor', 'campaign', 'region', 'city', 'technology', 'test_name', 'result',
    'failure_classification', 'failure_category', 'failure_subcategory', 'failure_comment', 'cell_id',
)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {NQ_CALLS_TABLE} (
    dataset_id INTEGER NOT NULL,
    source_row_id INTEGER NOT NULL,
    call_key TEXT NOT NULL,
    service TEXT NOT NULL,
    nr_mode TEXT NOT NULL DEFAULT '',
    {', '.join(f"{field} REAL" if field in NUMERIC_FIELDS else f"{field} TEXT NOT NULL DEFAULT ''" for field in CALL_FIELDS)},
    PRIMARY KEY (dataset_id, source_row_id)
);
CREATE INDEX IF NOT EXISTS idx_{NQ_CALLS_TABLE}_call_key ON {NQ_CALLS_TABLE}(call_key);
CREATE TABLE IF NOT EXISTS {NQ_CALL_SOURCES_TABLE} (
    dataset_id INTEGER PRIMARY KEY,
    revision TEXT NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS {NQ_CALL_TRACKING_TABLE} (
    call_key TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT '',
    team TEXT NOT NULL DEFAULT '',
    assignee TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 0,
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS {NQ_CALL_COMMENTS_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    call_key TEXT NOT NULL,
    body TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    edited_by TEXT NOT NULL DEFAULT '',
    edited_at TEXT NOT NULL DEFAULT '',
    deleted_by TEXT NOT NULL DEFAULT '',
    deleted_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_{NQ_CALL_COMMENTS_TABLE}_call ON {NQ_CALL_COMMENTS_TABLE}(call_key, id);
CREATE TABLE IF NOT EXISTS {NQ_CALL_HISTORY_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    call_key TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_{NQ_CALL_HISTORY_TABLE}_call ON {NQ_CALL_HISTORY_TABLE}(call_key, id);
CREATE TABLE IF NOT EXISTS {NQ_CALL_OPTIONS_TABLE} (
    kind TEXT NOT NULL CHECK(kind IN ('status', 'team')),
    name TEXT NOT NULL COLLATE NOCASE,
    color TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    is_closed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, name)
);
"""

_sync_locks: dict[str, Lock] = {}
_sync_locks_guard = Lock()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, float):
        if math.isnan(value):
            return ''
        if value.is_integer():
            return str(int(value))
    text = str(value).strip()
    return '' if text.casefold() in {'nan', 'nat', 'none', '<na>'} else text


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def ensure_nq_tables(task_repository: Any) -> None:
    """Create the module tables and seed the default statuses and teams once."""
    with task_repository.connection() as connection:
        existed = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (NQ_CALL_OPTIONS_TABLE,),
        ).fetchone()
        connection.executescript(SCHEMA)
        if not existed:
            connection.executemany(
                f"INSERT OR IGNORE INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES ('status', ?, ?, ?, ?)",
                [(name, color, index, int(closed)) for index, (name, color, closed) in enumerate(DEFAULT_STATUSES)],
            )
            connection.executemany(
                f"INSERT OR IGNORE INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES ('team', ?, ?, ?, 0)",
                [(name, color, index) for index, (name, color) in enumerate(DEFAULT_TEAMS)],
            )


# ---------------------------------------------------------------------------
# Indexing the NQ calls of every CDR
# ---------------------------------------------------------------------------
def _resolve_columns(columns: list[str], candidates: tuple[str, ...]) -> list[str]:
    """Every CDR column matching the candidates, in order of preference."""
    exact = set(columns)
    identities: dict[str, str] = {}
    for column in columns:
        identities.setdefault(column_identity(column), column)
    resolved = [candidate if candidate in exact else identities.get(column_identity(candidate)) for candidate in candidates]
    return list(dict.fromkeys(column for column in resolved if column))


def _resolve_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    return next(iter(_resolve_columns(columns, candidates)), None)


def call_key_for(service: str, values: dict[str, Any], identifier: str = '', subscriber: str = '') -> str:
    """A stable identity for a call: the same call keeps it across uploads and reprocessing."""
    base = (service, _text(values.get('operator')).casefold(), _text(values.get('campaign')).casefold())
    if identifier:
        parts = (*base, 'id', identifier)
    else:
        parts = (*base, subscriber.casefold(), _text(values.get('test_name')).casefold(),
                 _text(values.get('start_time')), _text(values.get('end_time')))
    return hashlib.sha1('\x1f'.join(parts).encode('utf-8')).hexdigest()[:24]


def _dataset_revision(row: Any) -> str:
    return '|'.join(str(row[key] or '') for key in ('updated_at', 'processed_at', 'row_count', 'normalization_version')) + f'|v{INDEX_VERSION}'


def _cdr_datasets(task_repository: Any) -> list[Any]:
    return [
        row for row in task_repository.list_datasets()
        if str(row['dataset_kind'] or '') in SERVICES and str(row['status'] or '') == 'ready'
    ]


def _dataset_calls(connection: Any, dataset: Any) -> list[tuple[Any, ...]]:
    """The NQ rows of one CDR, ready to insert into ``nq_calls``."""
    dataset_id = int(dataset['id'])
    service = str(dataset['dataset_kind'])
    table = f'dataset_rows_{dataset_id}'
    columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info({_quote(table)})').fetchall()]
    if not columns:
        return []
    resolved = {field: _resolve_columns(columns, candidates) for field, candidates in FIELD_SOURCES.items()}
    if not resolved['result']:
        return []
    result_column = resolved['result'][0]
    identifier_column = _resolve_column(columns, IDENTIFIER_SOURCES)
    subscriber_column = _resolve_column(columns, SUBSCRIBER_SOURCES)
    selected = list(dict.fromkeys(
        column for column in (*(item for items in resolved.values() for item in items), identifier_column, subscriber_column)
        if column
    ))
    aliases = {column: f'c{index}' for index, column in enumerate(selected)}
    normalized = f'LOWER(TRIM(CAST({_quote(result_column)} AS TEXT)))'
    # Range conditions use the CDR's normalized status index when it exists.
    query = (
        f"SELECT rowid AS source_row_id, {', '.join(f'{_quote(column)} AS {aliases[column]}' for column in selected)} "
        f"FROM {_quote(table)} WHERE {normalized} > ? OR ({normalized} < ? AND {normalized} > '')"
    )
    nr_mode = _text(dataset['nr_mode'])
    calls = []
    for row in connection.execute(query, (QUALIFIED_RESULT, QUALIFIED_RESULT)).fetchall():
        values: dict[str, Any] = {}
        for field, candidates in resolved.items():
            # The first candidate column with a value wins.
            if field in NUMERIC_FIELDS:
                values[field] = next((number for column in candidates if (number := _number(row[aliases[column]])) is not None), None)
            else:
                values[field] = next((text for column in candidates if (text := _text(row[aliases[column]]))), '')
        identifier = _text(row[aliases[identifier_column]]) if identifier_column else ''
        subscriber = _text(row[aliases[subscriber_column]]) if subscriber_column else ''
        key = call_key_for(service, values, identifier, subscriber)
        calls.append((dataset_id, int(row['source_row_id']), key, service, nr_mode, *(values[field] for field in CALL_FIELDS)))
    return calls


def sync_nq_calls(task_repository: Any) -> dict[str, Any]:
    """Index the NQ calls of new or changed CDRs and forget removed ones."""
    ensure_nq_tables(task_repository)
    path = str(task_repository.db_path)
    with _sync_locks_guard:
        lock = _sync_locks.setdefault(path, Lock())
    with lock:
        datasets = {int(row['id']): row for row in _cdr_datasets(task_repository)}
        with task_repository.connection() as connection:
            indexed = {
                int(row['dataset_id']): str(row['revision'])
                for row in connection.execute(f'SELECT dataset_id, revision FROM {NQ_CALL_SOURCES_TABLE}').fetchall()
            }
        removed = [dataset_id for dataset_id in indexed if dataset_id not in datasets]
        changed = [row for dataset_id, row in datasets.items() if indexed.get(dataset_id) != _dataset_revision(row)]
        if removed or changed:
            # Read every changed CDR before taking the write transaction.
            with task_repository.connection() as connection:
                fresh = {int(row['id']): _dataset_calls(connection, row) for row in changed}
            placeholders = ', '.join('?' for _ in range(5 + len(CALL_FIELDS)))
            with task_repository.connection() as connection:
                for dataset_id in [*removed, *fresh]:
                    connection.execute(f'DELETE FROM {NQ_CALLS_TABLE} WHERE dataset_id = ?', (dataset_id,))
                    connection.execute(f'DELETE FROM {NQ_CALL_SOURCES_TABLE} WHERE dataset_id = ?', (dataset_id,))
                for dataset_id, calls in fresh.items():
                    connection.executemany(f'INSERT OR REPLACE INTO {NQ_CALLS_TABLE} VALUES ({placeholders})', calls)
                    connection.execute(
                        f'INSERT INTO {NQ_CALL_SOURCES_TABLE} (dataset_id, revision, call_count, synced_at) VALUES (?, ?, ?, ?)',
                        (dataset_id, _dataset_revision(datasets[dataset_id]), len(calls), now_iso()),
                    )
        with task_repository.connection() as connection:
            total = connection.execute(f'SELECT COUNT(DISTINCT call_key) FROM {NQ_CALLS_TABLE}').fetchone()[0]
            synced_at = connection.execute(f'SELECT MAX(synced_at) FROM {NQ_CALL_SOURCES_TABLE}').fetchone()[0]
    return {'datasets': len(datasets), 'reindexed': len(changed), 'removed': len(removed),
            'calls': int(total or 0), 'synced_at': synced_at or ''}


# ---------------------------------------------------------------------------
# Options: statuses and teams
# ---------------------------------------------------------------------------
def list_options(task_repository: Any) -> dict[str, list[dict[str, Any]]]:
    with task_repository.connection() as connection:
        rows = connection.execute(
            f'SELECT kind, name, color, is_closed FROM {NQ_CALL_OPTIONS_TABLE} ORDER BY kind, position, name COLLATE NOCASE'
        ).fetchall()
    options: dict[str, list[dict[str, Any]]] = {'statuses': [], 'teams': []}
    for row in rows:
        item = {'name': str(row['name']), 'color': str(row['color'])}
        if row['kind'] == 'status':
            options['statuses'].append({**item, 'closed': bool(row['is_closed'])})
        else:
            options['teams'].append(item)
    return options


def default_status(options: dict[str, list[dict[str, Any]]]) -> str:
    """Untracked calls show the first status."""
    return options['statuses'][0]['name'] if options['statuses'] else 'Open'


def _normalize_option_list(items: Any, kind: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(f'The {kind} list is invalid.')
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f'The {kind} list is invalid.')
        name = re.sub(r'\s+', ' ', str(item.get('name') or '')).strip()[:60]
        if not name:
            raise ValueError(f'Every {kind} needs a name.')
        if name.casefold() in seen:
            raise ValueError(f'The {kind} "{name}" is repeated.')
        seen.add(name.casefold())
        color = str(item.get('color') or '').strip()
        normalized.append({
            'name': name,
            'previous': re.sub(r'\s+', ' ', str(item.get('previous') or '')).strip(),
            'color': color if COLOR_PATTERN.fullmatch(color) else '#7b8790',
            'closed': bool(item.get('closed')) if kind == 'status' else False,
        })
    return normalized


def save_options(task_repository: Any, statuses: Any, teams: Any, username: str) -> dict[str, list[dict[str, Any]]]:
    """Replace the statuses and teams; renamed values follow on every call, removed ones must be unused."""
    lists = {'status': _normalize_option_list(statuses, 'status'), 'team': _normalize_option_list(teams, 'team')}
    if not lists['status']:
        raise ValueError('Keep at least one status.')
    current = list_options(task_repository)
    with task_repository.connection() as connection:
        for kind, column in (('status', 'status'), ('team', 'team')):
            existing = {item['name'].casefold(): item['name'] for item in current['statuses' if kind == 'status' else 'teams']}
            renamed = {item['previous'].casefold(): item['name'] for item in lists[kind]
                       if item['previous'] and item['previous'].casefold() in existing}
            kept = {item['name'].casefold() for item in lists[kind]} | set(renamed)
            for old_key, old_name in existing.items():
                if old_key in kept:
                    continue
                used = connection.execute(
                    f'SELECT COUNT(*) FROM {NQ_CALL_TRACKING_TABLE} WHERE {column} = ? COLLATE NOCASE', (old_name,),
                ).fetchone()[0]
                if used:
                    raise ValueError(f'The {kind} "{old_name}" is in use; rename it or move its calls first.')
            for old_key, new_name in renamed.items():
                old_name = existing[old_key]
                if old_name != new_name:
                    connection.execute(
                        f'UPDATE {NQ_CALL_TRACKING_TABLE} SET {column} = ? WHERE {column} = ? COLLATE NOCASE',
                        (new_name, old_name),
                    )
            connection.execute(f'DELETE FROM {NQ_CALL_OPTIONS_TABLE} WHERE kind = ?', (kind,))
            connection.executemany(
                f'INSERT INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES (?, ?, ?, ?, ?)',
                [(kind, item['name'], item['color'], index, int(item['closed'])) for index, item in enumerate(lists[kind])],
            )
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_call_options', 'Non-Qualified Calls statuses and teams updated.')
    return list_options(task_repository)


# ---------------------------------------------------------------------------
# Querying calls
# ---------------------------------------------------------------------------
def _base_sql(default: str) -> tuple[str, list[Any]]:
    """One row per call (the newest CDR wins when a call is uploaded twice) with its follow-up."""
    sql = f"""
        SELECT c.*,
               COALESCE(NULLIF(t.status, ''), ?) AS status,
               COALESCE(t.team, '') AS team,
               COALESCE(t.assignee, '') AS assignee,
               COALESCE(t.version, 0) AS version,
               COALESCE(t.updated_by, '') AS updated_by,
               COALESCE(t.updated_at, '') AS updated_at,
               (SELECT COUNT(*) FROM {NQ_CALL_COMMENTS_TABLE} m WHERE m.call_key = c.call_key AND m.deleted_at = '') AS comment_count
        FROM {NQ_CALLS_TABLE} c
        LEFT JOIN {NQ_CALL_TRACKING_TABLE} t ON t.call_key = c.call_key
        WHERE c.rowid IN (SELECT MAX(rowid) FROM {NQ_CALLS_TABLE} GROUP BY call_key)
    """
    return sql, [default]


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value) for value in values if value is not None))


def _filter_sql(filters: dict[str, Any], username: str, closed_statuses: list[str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for field in (*FIELD_FILTERS, *TRACKING_FILTERS):
        values = _strings(filters.get(field))
        if not values:
            continue
        values = ['' if value == UNASSIGNED else value for value in values]
        clauses.append(f"{field} IN ({', '.join('?' for _ in values)})")
        params.extend(values)
    dataset_ids = [int(value) for value in _strings(filters.get('datasets')) if value.lstrip('-').isdigit()]
    if dataset_ids:
        clauses.append(f"dataset_id IN ({', '.join('?' for _ in dataset_ids)})")
        params.extend(dataset_ids)
    if filters.get('open_only') and closed_statuses:
        clauses.append(f"status NOT IN ({', '.join('?' for _ in closed_statuses)})")
        params.extend(closed_statuses)
    if filters.get('mine'):
        clauses.append('assignee = ? COLLATE NOCASE')
        params.append(username)
    if filters.get('without_comments'):
        clauses.append('comment_count = 0')
    search = str(filters.get('search') or '').strip().casefold()
    if search:
        haystack = " || ' ' || ".join(f"COALESCE({field}, '')" for field in SEARCH_FIELDS)
        clauses.append(
            f"(instr(lower({haystack}), ?) > 0 OR EXISTS (SELECT 1 FROM {NQ_CALL_COMMENTS_TABLE} s "
            f"WHERE s.call_key = calls.call_key AND s.deleted_at = '' AND instr(lower(s.body), ?) > 0))"
        )
        params.extend([search, search])
    return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', params


def _call_payload(row: Any) -> dict[str, Any]:
    payload = {key: row[key] for key in row.keys()}
    payload['service_label'] = SERVICE_LABELS.get(str(payload.get('service')), str(payload.get('service') or ''))
    return payload


def _comments_by_call(connection: Any, keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    rows = connection.execute(
        f"SELECT call_key, body, created_by, created_at FROM {NQ_CALL_COMMENTS_TABLE} "
        f"WHERE deleted_at = '' AND call_key IN ({', '.join('?' for _ in keys)}) ORDER BY id",
        keys,
    ).fetchall()
    return {str(row['call_key']): {'body': str(row['body']), 'created_by': str(row['created_by']),
                                   'created_at': str(row['created_at'])} for row in rows}


def query_calls(task_repository: Any, request: dict[str, Any], username: str) -> dict[str, Any]:
    """A page of calls with the executive summary of every call that matches the filters."""
    options = list_options(task_repository)
    filters = request.get('filters') if isinstance(request.get('filters'), dict) else {}
    closed = [item['name'] for item in options['statuses'] if item['closed']]
    base, base_params = _base_sql(default_status(options))
    where, params = _filter_sql(filters, username, closed)
    filtered = f'WITH calls AS ({base}) SELECT * FROM calls{where}'
    all_params = [*base_params, *params]
    sort = SORT_COLUMNS.get(str(request.get('sort') or ''), 'start_time')
    direction = 'ASC' if str(request.get('direction') or '').lower() == 'asc' else 'DESC'
    page_size = int(request.get('page_size') or 50)
    page_size = page_size if page_size in PAGE_SIZES else 50
    with task_repository.connection() as connection:
        total = int(connection.execute(f'SELECT COUNT(*) FROM ({filtered})', all_params).fetchone()[0])
        pages = max(1, math.ceil(total / page_size))
        page = min(max(1, int(request.get('page') or 1)), pages)
        rows = connection.execute(
            f'SELECT * FROM ({filtered}) ORDER BY {sort} = \'\', {sort} {direction}, start_time DESC, call_key '
            f'LIMIT ? OFFSET ?',
            [*all_params, page_size, (page - 1) * page_size],
        ).fetchall()
        calls = [_call_payload(row) for row in rows]
        last_comments = _comments_by_call(connection, [call['call_key'] for call in calls])
        for call in calls:
            call['last_comment'] = last_comments.get(call['call_key'])
        breakdowns = []
        for field, label in BREAKDOWNS:
            values = connection.execute(
                f'SELECT {field} AS value, COUNT(*) AS count FROM ({filtered}) GROUP BY {field} ORDER BY count DESC, value LIMIT 12',
                all_params,
            ).fetchall()
            breakdowns.append({'field': field, 'label': label, 'items': [
                {'value': str(row['value'] or ''), 'count': int(row['count'])} for row in values
            ]})
        closed_marks = ', '.join('?' for _ in closed) or "''"
        summary = connection.execute(
            f"SELECT COUNT(*) AS total, "
            f"SUM(CASE WHEN status IN ({closed_marks}) THEN 1 ELSE 0 END) AS closed, "
            f"SUM(CASE WHEN comment_count > 0 THEN 1 ELSE 0 END) AS commented, "
            f"SUM(CASE WHEN team <> '' THEN 1 ELSE 0 END) AS with_team, "
            f"SUM(CASE WHEN assignee <> '' THEN 1 ELSE 0 END) AS assigned "
            f"FROM ({filtered})",
            [*closed, *all_params],
        ).fetchone()
    summary_payload = {key: int(summary[key] or 0) for key in ('total', 'closed', 'commented', 'with_team', 'assigned')}
    summary_payload['open'] = summary_payload['total'] - summary_payload['closed']
    return {
        'calls': calls, 'total': total, 'page': page, 'pages': pages, 'page_size': page_size,
        'sort': next((key for key, column in SORT_COLUMNS.items() if column == sort), 'start_time'),
        'direction': direction.lower(), 'summary': summary_payload, 'breakdowns': breakdowns,
    }


def filter_options(task_repository: Any) -> dict[str, list[str]]:
    """Distinct values of every indexed filter."""
    values: dict[str, list[str]] = {}
    with task_repository.connection() as connection:
        for field in FIELD_FILTERS:
            rows = connection.execute(
                f"SELECT DISTINCT {field} AS value FROM {NQ_CALLS_TABLE} WHERE {field} <> '' ORDER BY value COLLATE NOCASE"
            ).fetchall()
            values[field] = [str(row['value']) for row in rows]
        assignees = connection.execute(
            f"SELECT DISTINCT assignee FROM {NQ_CALL_TRACKING_TABLE} WHERE assignee <> '' ORDER BY assignee COLLATE NOCASE"
        ).fetchall()
    values['assignee'] = [str(row['assignee']) for row in assignees]
    return values


def indexed_datasets(task_repository: Any) -> list[dict[str, Any]]:
    with task_repository.connection() as connection:
        counts = {int(row['dataset_id']): int(row['call_count'])
                  for row in connection.execute(f'SELECT dataset_id, call_count FROM {NQ_CALL_SOURCES_TABLE}').fetchall()}
    return [
        {'id': int(row['id']), 'name': str(row['file_name']), 'service': str(row['dataset_kind']),
         'nr_mode': _text(row['nr_mode']), 'calls': counts.get(int(row['id']), 0)}
        for row in sorted(_cdr_datasets(task_repository), key=lambda item: str(item['file_name']).casefold())
    ]


# ---------------------------------------------------------------------------
# One call: details, follow-up and comments
# ---------------------------------------------------------------------------
def _call_row(connection: Any, call_key: str, default: str) -> Any:
    base, params = _base_sql(default)
    return connection.execute(f'WITH calls AS ({base}) SELECT * FROM calls WHERE call_key = ?', [*params, call_key]).fetchone()


def _comment_payload(row: Any) -> dict[str, Any]:
    deleted = bool(row['deleted_at'])
    return {
        'id': int(row['id']), 'body': '' if deleted else str(row['body']), 'created_by': str(row['created_by']),
        'created_at': str(row['created_at']), 'edited_by': str(row['edited_by']), 'edited_at': str(row['edited_at']),
        'deleted_by': str(row['deleted_by']), 'deleted_at': str(row['deleted_at']),
    }


def call_detail(task_repository: Any, call_key: str) -> dict[str, Any] | None:
    options = list_options(task_repository)
    with task_repository.connection() as connection:
        row = _call_row(connection, call_key, default_status(options))
        if row is None:
            return None
        call = _call_payload(row)
        comments = [_comment_payload(item) for item in connection.execute(
            f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE call_key = ? ORDER BY id', (call_key,),
        ).fetchall()]
        history = [
            {'field': str(item['field']), 'old_value': str(item['old_value']), 'new_value': str(item['new_value']),
             'changed_by': str(item['changed_by']), 'changed_at': str(item['changed_at'])}
            for item in connection.execute(
                f"SELECT * FROM {NQ_CALL_HISTORY_TABLE} WHERE call_key = ? ORDER BY id", (call_key,),
            ).fetchall()
        ]
        table = f"dataset_rows_{int(call['dataset_id'])}"
        try:
            source = connection.execute(f'SELECT * FROM {_quote(table)} WHERE rowid = ?', (int(call['source_row_id']),)).fetchone()
        except Exception:  # noqa: BLE001 - the CDR may have been removed since it was indexed.
            source = None
        dataset = connection.execute('SELECT file_name FROM datasets WHERE id = ?', (int(call['dataset_id']),)).fetchone()
    fields = []
    if source is not None:
        fields = [[key, _text(source[key])] for key in source.keys() if _text(source[key])]
    call['dataset_name'] = str(dataset['file_name']) if dataset else ''
    return {'call': call, 'comments': comments, 'history': history, 'fields': fields}


def _record_history(connection: Any, call_key: str, field: str, old: str, new: str, username: str, when: str) -> None:
    connection.execute(
        f'INSERT INTO {NQ_CALL_HISTORY_TABLE} (uid, call_key, field, old_value, new_value, changed_by, changed_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (uuid.uuid4().hex, call_key, field, old, new, username, when),
    )


def _validate_changes(changes: dict[str, Any], options: dict[str, list[dict[str, Any]]], users: set[str]) -> dict[str, str]:
    validated: dict[str, str] = {}
    if 'status' in changes:
        names = {item['name'].casefold(): item['name'] for item in options['statuses']}
        status = names.get(str(changes.get('status') or '').strip().casefold())
        if not status:
            raise ValueError('Choose one of the configured statuses.')
        validated['status'] = status
    if 'team' in changes:
        names = {item['name'].casefold(): item['name'] for item in options['teams']}
        value = str(changes.get('team') or '').strip()
        if value and value.casefold() not in names:
            raise ValueError('Choose one of the configured teams.')
        validated['team'] = names.get(value.casefold(), '')
    if 'assignee' in changes:
        value = str(changes.get('assignee') or '').strip()
        lookup = {name.casefold(): name for name in users}
        if value and value.casefold() not in lookup:
            raise ValueError('Choose a user with access to this workspace.')
        validated['assignee'] = lookup.get(value.casefold(), '')
    if not validated:
        raise ValueError('There is nothing to change.')
    return validated


class TrackingConflict(Exception):
    """Another user changed the call after it was loaded."""


def update_tracking(
    task_repository: Any, call_keys: list[str], changes: dict[str, Any], username: str, users: set[str],
    expected_version: int | None = None,
) -> list[str]:
    """Apply status, team or assignee changes; returns the calls that changed."""
    options = list_options(task_repository)
    validated = _validate_changes(changes, options, users)
    default = default_status(options)
    when = now_iso()
    changed: list[str] = []
    with task_repository.connection() as connection:
        for call_key in dict.fromkeys(call_keys):
            row = _call_row(connection, call_key, default)
            if row is None:
                raise LookupError('The call is no longer available. Refresh the list.')
            if expected_version is not None and int(row['version']) != int(expected_version):
                raise TrackingConflict(
                    f"{row['updated_by'] or 'Another user'} changed this call at {row['updated_at']}. Review it and try again."
                )
            differences = {field: value for field, value in validated.items() if str(row[field]) != value}
            if not differences:
                continue
            current = {field: str(row[field]) for field in ('status', 'team', 'assignee')}
            current.update(differences)
            connection.execute(
                f'INSERT INTO {NQ_CALL_TRACKING_TABLE} (call_key, status, team, assignee, version, updated_by, updated_at) '
                'VALUES (?, ?, ?, ?, 1, ?, ?) ON CONFLICT(call_key) DO UPDATE SET status = excluded.status, '
                'team = excluded.team, assignee = excluded.assignee, version = version + 1, '
                'updated_by = excluded.updated_by, updated_at = excluded.updated_at',
                (call_key, current['status'], current['team'], current['assignee'], username, when),
            )
            for field, value in differences.items():
                _record_history(connection, call_key, field, str(row[field]), value, username, when)
            changed.append(call_key)
    return changed


def _clean_comment(body: Any) -> str:
    text = str(body or '').replace('\r\n', '\n').strip()
    if not text:
        raise ValueError('Write a comment first.')
    if len(text) > MAX_COMMENT_LENGTH:
        raise ValueError(f'Comments are limited to {MAX_COMMENT_LENGTH} characters.')
    return text


def add_comment(task_repository: Any, call_key: str, body: Any, username: str) -> dict[str, Any]:
    text = _clean_comment(body)
    options = list_options(task_repository)
    with task_repository.connection() as connection:
        if _call_row(connection, call_key, default_status(options)) is None:
            raise LookupError('The call is no longer available. Refresh the list.')
        cursor = connection.execute(
            f'INSERT INTO {NQ_CALL_COMMENTS_TABLE} (uid, call_key, body, created_by, created_at) VALUES (?, ?, ?, ?, ?)',
            (uuid.uuid4().hex, call_key, text, username, now_iso()),
        )
        row = connection.execute(f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE id = ?', (cursor.lastrowid,)).fetchone()
    return _comment_payload(row)


def _comment_for_change(connection: Any, comment_id: int, username: str, moderator: bool) -> Any:
    row = connection.execute(f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE id = ?', (comment_id,)).fetchone()
    if row is None or row['deleted_at']:
        raise LookupError('The comment no longer exists.')
    if str(row['created_by']).casefold() != username.casefold() and not moderator:
        raise PermissionError('Only the author or an admin can change this comment.')
    return row


def edit_comment(task_repository: Any, comment_id: int, body: Any, username: str, moderator: bool) -> dict[str, Any]:
    text = _clean_comment(body)
    when = now_iso()
    with task_repository.connection() as connection:
        row = _comment_for_change(connection, comment_id, username, moderator)
        if str(row['body']) != text:
            connection.execute(
                f'UPDATE {NQ_CALL_COMMENTS_TABLE} SET body = ?, edited_by = ?, edited_at = ? WHERE id = ?',
                (text, username, when, comment_id),
            )
            _record_history(connection, str(row['call_key']), 'comment_edit', str(row['body']), text, username, when)
        updated = connection.execute(f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE id = ?', (comment_id,)).fetchone()
    return _comment_payload(updated)


def delete_comment(task_repository: Any, comment_id: int, username: str, moderator: bool) -> dict[str, Any]:
    """Comments are hidden, not erased: the history keeps their text."""
    when = now_iso()
    with task_repository.connection() as connection:
        row = _comment_for_change(connection, comment_id, username, moderator)
        connection.execute(
            f'UPDATE {NQ_CALL_COMMENTS_TABLE} SET deleted_by = ?, deleted_at = ? WHERE id = ?', (username, when, comment_id),
        )
        _record_history(connection, str(row['call_key']), 'comment_delete', str(row['body']), '', username, when)
        updated = connection.execute(f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE id = ?', (comment_id,)).fetchone()
    return _comment_payload(updated)


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
EXPORT_COLUMNS = (
    ('Service', 'service_label'), ('Start Time', 'start_time'), ('End Time', 'end_time'), ('Operator', 'operator'),
    ('Vendor', 'vendor'), ('Campaign', 'campaign'), ('NR Mode', 'nr_mode'), ('Region', 'region'), ('City', 'city'),
    ('Technology', 'technology'), ('Test Name', 'test_name'), ('Direction', 'direction'), ('Result', 'result'),
    ('Failure Phase', 'failure_phase'), ('Failure Technology', 'failure_technology'),
    ('Failure Classification', 'failure_classification'), ('Failure Category', 'failure_category'),
    ('Failure Subcategory', 'failure_subcategory'), ('Failure Comment', 'failure_comment'), ('Cell ID', 'cell_id'),
    ('Latitude', 'latitude'), ('Longitude', 'longitude'), ('Status', 'status'), ('Team', 'team'),
    ('Assignee', 'assignee'), ('Comments', 'comment_count'), ('Last Comment', 'last_comment_text'),
    ('Last Comment By', 'last_comment_by'), ('Last Comment At', 'last_comment_at'), ('Updated By', 'updated_by'),
    ('Updated At', 'updated_at'), ('CDR', 'dataset_name'), ('Call Key', 'call_key'),
)


def export_workbook(task_repository: Any, filters: dict[str, Any], username: str) -> bytes:
    """Every call that matches the filters, its comments and its change history."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    options = list_options(task_repository)
    closed = [item['name'] for item in options['statuses'] if item['closed']]
    base, base_params = _base_sql(default_status(options))
    where, params = _filter_sql(filters, username, closed)
    with task_repository.connection() as connection:
        rows = connection.execute(
            f'WITH calls AS ({base}) SELECT * FROM calls{where} ORDER BY start_time DESC, call_key', [*base_params, *params],
        ).fetchall()
        calls = [_call_payload(row) for row in rows]
        keys = [call['call_key'] for call in calls]
        names = {int(row['id']): str(row['file_name']) for row in connection.execute('SELECT id, file_name FROM datasets')}
        comments: list[Any] = []
        history: list[Any] = []
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ', '.join('?' for _ in chunk)
            comments.extend(connection.execute(
                f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE call_key IN ({marks}) ORDER BY id', chunk).fetchall())
            history.extend(connection.execute(
                f'SELECT * FROM {NQ_CALL_HISTORY_TABLE} WHERE call_key IN ({marks}) ORDER BY id', chunk).fetchall())
    latest = {str(row['call_key']): row for row in comments if not row['deleted_at']}
    by_key = {call['call_key']: call for call in calls}
    for call in calls:
        comment = latest.get(call['call_key'])
        call['last_comment_text'] = str(comment['body']) if comment else ''
        call['last_comment_by'] = str(comment['created_by']) if comment else ''
        call['last_comment_at'] = str(comment['created_at']) if comment else ''
        call['dataset_name'] = names.get(int(call['dataset_id']), '')

    workbook = Workbook()
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='9C1C47')

    def write_sheet(sheet, headers: list[str], data: list[list[Any]], widths: list[int]) -> None:
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font, cell.fill = header_font, header_fill
            cell.alignment = Alignment(vertical='center')
        for values in data:
            sheet.append(values)
        sheet.freeze_panes = 'A2'
        if data:
            sheet.auto_filter.ref = sheet.dimensions
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width

    calls_sheet = workbook.active
    calls_sheet.title = 'NQ Calls'
    write_sheet(
        calls_sheet, [label for label, _key in EXPORT_COLUMNS],
        [[call.get(key) if call.get(key) is not None else '' for _label, key in EXPORT_COLUMNS] for call in calls],
        [max(12, min(48, len(label) + 6)) for label, _key in EXPORT_COLUMNS],
    )

    def call_context(call_key: str) -> list[Any]:
        call = by_key.get(call_key, {})
        return [call.get('service_label', ''), call.get('operator', ''), call.get('campaign', ''), call.get('start_time', '')]

    write_sheet(
        workbook.create_sheet('Comments'),
        ['Service', 'Operator', 'Campaign', 'Start Time', 'Comment', 'Author', 'Created At', 'Edited By', 'Edited At',
         'Deleted By', 'Deleted At', 'Call Key'],
        [[*call_context(str(row['call_key'])), str(row['body']), row['created_by'], row['created_at'], row['edited_by'],
          row['edited_at'], row['deleted_by'], row['deleted_at'], row['call_key']] for row in comments],
        [10, 16, 16, 24, 70, 16, 26, 16, 26, 16, 26, 28],
    )
    write_sheet(
        workbook.create_sheet('History'),
        ['Service', 'Operator', 'Campaign', 'Start Time', 'Change', 'Previous Value', 'New Value', 'Changed By',
         'Changed At', 'Call Key'],
        [[*call_context(str(row['call_key'])), HISTORY_LABELS.get(str(row['field']), str(row['field'])),
          row['old_value'], row['new_value'], row['changed_by'], row['changed_at'], row['call_key']] for row in history],
        [10, 16, 16, 24, 18, 40, 40, 16, 26, 28],
    )
    for sheet in workbook.worksheets[1:]:
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


HISTORY_LABELS = {
    'status': 'Status', 'team': 'Team', 'assignee': 'Assignee',
    'comment_edit': 'Comment edited', 'comment_delete': 'Comment deleted',
}


# ---------------------------------------------------------------------------
# Portability: export, import, transfers and backups
# ---------------------------------------------------------------------------
def export_tracking_document(task_repository: Any) -> bytes:
    """The statuses, teams, follow-up, comments and history of a workspace."""
    ensure_nq_tables(task_repository)
    with task_repository.connection() as connection:
        tracking = [dict(row) for row in connection.execute(
            f'SELECT call_key, status, team, assignee, version, updated_by, updated_at FROM {NQ_CALL_TRACKING_TABLE} ORDER BY call_key')]
        comments = [dict(row) for row in connection.execute(
            f'SELECT uid, call_key, body, created_by, created_at, edited_by, edited_at, deleted_by, deleted_at '
            f'FROM {NQ_CALL_COMMENTS_TABLE} ORDER BY id')]
        history = [dict(row) for row in connection.execute(
            f'SELECT uid, call_key, field, old_value, new_value, changed_by, changed_at FROM {NQ_CALL_HISTORY_TABLE} ORDER BY id')]
    document = {
        'format': TRACKING_FORMAT, 'version': TRACKING_FORMAT_VERSION, 'options': list_options(task_repository),
        'tracking': tracking, 'comments': comments, 'history': history,
    }
    return json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')


def import_tracking_document(task_repository: Any, payload: bytes | str) -> int:
    """Merge a tracking document; returns the number of calls whose follow-up was added or updated.

    Missing statuses and teams are added, newer follow-up replaces older follow-up,
    and comments and history entries are added once (by their identifier), so
    importing the same document again changes nothing.
    """
    document = json.loads(payload.decode('utf-8') if isinstance(payload, bytes) else payload)
    if not isinstance(document, dict) or document.get('format') != TRACKING_FORMAT:
        raise ValueError('The file is not a Non-Qualified Calls tracking export.')
    if int(document.get('version') or 0) > TRACKING_FORMAT_VERSION:
        raise ValueError('The Non-Qualified Calls tracking export was created by a newer version.')
    ensure_nq_tables(task_repository)

    def records(name: str) -> list[dict[str, Any]]:
        items = document.get(name) or []
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError(f'The "{name}" section of the tracking export is invalid.')
        return items

    options = document.get('options') if isinstance(document.get('options'), dict) else {}
    tracking, comments, history = records('tracking'), records('comments'), records('history')
    touched: set[str] = set()
    with task_repository.connection() as connection:
        for kind, key in (('status', 'statuses'), ('team', 'teams')):
            items = options.get(key) if isinstance(options.get(key), list) else []
            position = connection.execute(
                f'SELECT COALESCE(MAX(position), -1) FROM {NQ_CALL_OPTIONS_TABLE} WHERE kind = ?', (kind,)).fetchone()[0]
            for item in _normalize_option_list([item for item in items if isinstance(item, dict) and item.get('name')], kind):
                position += 1
                connection.execute(
                    f'INSERT OR IGNORE INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES (?, ?, ?, ?, ?)',
                    (kind, item['name'], item['color'], position, int(item['closed'])),
                )
        for item in tracking:
            call_key = _text(item.get('call_key'))
            if not call_key:
                continue
            existing = connection.execute(
                f'SELECT updated_at FROM {NQ_CALL_TRACKING_TABLE} WHERE call_key = ?', (call_key,)).fetchone()
            incoming = _text(item.get('updated_at'))
            if existing is not None and str(existing['updated_at']) >= incoming:
                continue
            connection.execute(
                f'INSERT OR REPLACE INTO {NQ_CALL_TRACKING_TABLE} (call_key, status, team, assignee, version, updated_by, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (call_key, _text(item.get('status')), _text(item.get('team')), _text(item.get('assignee')),
                 int(item.get('version') or 1), _text(item.get('updated_by')), incoming),
            )
            touched.add(call_key)
        for item in comments:
            uid, call_key, body = _text(item.get('uid')), _text(item.get('call_key')), str(item.get('body') or '')
            if not uid or not call_key or not body:
                continue
            existing = connection.execute(
                f'SELECT edited_at, deleted_at FROM {NQ_CALL_COMMENTS_TABLE} WHERE uid = ?', (uid,)).fetchone()
            values = (body, _text(item.get('edited_by')), _text(item.get('edited_at')),
                      _text(item.get('deleted_by')), _text(item.get('deleted_at')))
            if existing is None:
                connection.execute(
                    f'INSERT INTO {NQ_CALL_COMMENTS_TABLE} (uid, call_key, created_by, created_at, body, edited_by, edited_at, '
                    'deleted_by, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (uid, call_key, _text(item.get('created_by')) or 'import', _text(item.get('created_at')), *values),
                )
                touched.add(call_key)
            elif (values[2], values[4]) > (str(existing['edited_at']), str(existing['deleted_at'])):
                connection.execute(
                    f'UPDATE {NQ_CALL_COMMENTS_TABLE} SET body = ?, edited_by = ?, edited_at = ?, deleted_by = ?, '
                    'deleted_at = ? WHERE uid = ?', (*values, uid),
                )
                touched.add(call_key)
        for item in history:
            uid, call_key = _text(item.get('uid')), _text(item.get('call_key'))
            if not uid or not call_key:
                continue
            connection.execute(
                f'INSERT OR IGNORE INTO {NQ_CALL_HISTORY_TABLE} (uid, call_key, field, old_value, new_value, changed_by, changed_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (uid, call_key, _text(item.get('field')), str(item.get('old_value') or ''), str(item.get('new_value') or ''),
                 _text(item.get('changed_by')) or 'import', _text(item.get('changed_at'))),
            )
    return len(touched)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def install_non_qualified_calls_routes(core: Any) -> None:
    from fastapi import Depends, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from pydantic import BaseModel, Field

    class QueryPayload(BaseModel):
        filters: dict[str, Any] = Field(default_factory=dict)
        sort: str = 'start_time'
        direction: str = 'desc'
        page: int = 1
        page_size: int = 50

    class TrackingPayload(BaseModel):
        changes: dict[str, Any] = Field(default_factory=dict)
        version: int | None = None

    class BulkTrackingPayload(BaseModel):
        call_keys: list[str] = Field(default_factory=list)
        changes: dict[str, Any] = Field(default_factory=dict)

    class CommentPayload(BaseModel):
        body: str = ''

    class OptionsPayload(BaseModel):
        statuses: list[dict[str, Any]] = Field(default_factory=list)
        teams: list[dict[str, Any]] = Field(default_factory=list)

    class ExportPayload(BaseModel):
        filters: dict[str, Any] = Field(default_factory=dict)

    def workspace_repository(user):
        if not core.active_workspace:
            raise HTTPException(409, 'Open a workspace before using Non-Qualified Calls.')
        core.require_workspace_access(user, core.active_workspace.id)
        repository = core.Repository(core.active_workspace.database_path, global_db_path=core.repository.global_db_path,
                                     workspace_registry_db_path=core.workspace_registry.registry_path)
        ensure_nq_tables(repository)
        return repository

    def can_edit(user) -> bool:
        return user.role in core.WORKSPACE_EDITOR_ROLES

    def can_moderate(user) -> bool:
        return user.role in {'admin', 'super-admin'}

    def editor_user(user=Depends(core.current_user)):
        if not can_edit(user):
            raise HTTPException(403, 'The user-viewer role can read Non-Qualified Calls but cannot change them.')
        return user

    def workspace_users() -> list[str]:
        """Active accounts that can open the active workspace: the assignable users."""
        names = []
        for row in core.repository.list_users():
            if not row['active']:
                continue
            username = str(row['username'])
            if row['role'] == 'super-admin' or core.repository.user_has_workspace_access(username, core.active_workspace.id):
                names.append(username)
        return sorted(names, key=str.casefold)

    def translate(action):
        try:
            return action()
        except TrackingConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404, str(exc).strip("'\"")) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @core.app.get('/non-qualified-calls', response_class=HTMLResponse)
    def non_qualified_calls_page(request: Request, user=Depends(core.current_user)):
        return core.render_template(request, 'non_qualified_calls.html', {
            'user': user, 'nq_can_edit': can_edit(user), 'nq_page_sizes': PAGE_SIZES,
        })

    @core.app.get('/api/non-qualified-calls/state')
    def nq_state(user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        sync = sync_nq_calls(repository)
        return JSONResponse({
            'sync': sync, 'options': list_options(repository), 'filter_options': filter_options(repository),
            'datasets': indexed_datasets(repository), 'users': workspace_users(),
            'user': {'username': user.username, 'can_edit': can_edit(user), 'can_moderate': can_moderate(user)},
            'unassigned': UNASSIGNED, 'page_sizes': list(PAGE_SIZES),
        })

    @core.app.post('/api/non-qualified-calls/calls')
    def nq_calls(payload: QueryPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        sync = sync_nq_calls(repository)
        result = query_calls(repository, payload.model_dump(), user.username)
        return JSONResponse({**result, 'sync': sync})

    @core.app.get('/api/non-qualified-calls/calls/{call_key}')
    def nq_call(call_key: str, user=Depends(core.current_user)) -> JSONResponse:
        detail = call_detail(workspace_repository(user), call_key)
        if detail is None:
            raise HTTPException(404, 'The call is no longer available. Refresh the list.')
        return JSONResponse(detail)

    @core.app.patch('/api/non-qualified-calls/calls/{call_key}')
    def nq_update_call(call_key: str, payload: TrackingPayload, user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        translate(lambda: update_tracking(repository, [call_key], payload.changes, user.username,
                                          set(workspace_users()), payload.version))
        return JSONResponse(call_detail(repository, call_key))

    @core.app.post('/api/non-qualified-calls/calls/bulk')
    def nq_bulk_update(payload: BulkTrackingPayload, user=Depends(editor_user)) -> JSONResponse:
        if not payload.call_keys:
            raise HTTPException(400, 'Select at least one call.')
        if len(payload.call_keys) > 5000:
            raise HTTPException(400, 'Change at most 5000 calls at once.')
        repository = workspace_repository(user)
        changed = translate(lambda: update_tracking(repository, payload.call_keys, payload.changes, user.username,
                                                    set(workspace_users())))
        return JSONResponse({'changed': len(changed)})

    @core.app.post('/api/non-qualified-calls/calls/{call_key}/comments')
    def nq_add_comment(call_key: str, payload: CommentPayload, user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        comment = translate(lambda: add_comment(repository, call_key, payload.body, user.username))
        return JSONResponse({'comment': comment})

    @core.app.patch('/api/non-qualified-calls/comments/{comment_id}')
    def nq_edit_comment(comment_id: int, payload: CommentPayload, user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        comment = translate(lambda: edit_comment(repository, comment_id, payload.body, user.username, can_moderate(user)))
        return JSONResponse({'comment': comment})

    @core.app.delete('/api/non-qualified-calls/comments/{comment_id}')
    def nq_delete_comment(comment_id: int, user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        comment = translate(lambda: delete_comment(repository, comment_id, user.username, can_moderate(user)))
        return JSONResponse({'comment': comment})

    @core.app.put('/api/non-qualified-calls/options')
    def nq_save_options(payload: OptionsPayload, user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        options = translate(lambda: save_options(repository, payload.statuses, payload.teams, user.username))
        return JSONResponse({'options': options})

    @core.app.post('/api/non-qualified-calls/export')
    def nq_export(payload: ExportPayload, user=Depends(core.current_user)) -> Response:
        repository = workspace_repository(user)
        sync_nq_calls(repository)
        content = export_workbook(repository, payload.filters, user.username)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', f'{core.active_workspace.name}_non-qualified-calls_{stamp}.xlsx')
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})
