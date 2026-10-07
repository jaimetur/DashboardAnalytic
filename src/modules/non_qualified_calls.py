"""Non-Qualified Calls: follow-up of every CDR call and test that did not complete.

A Non-Qualified (NQ) call is a Voice or Speech call, or a Data test, whose result
is anything other than ``Completed`` (for example Failed, Dropped or Cutoff).
The module indexes those rows of every ready CDR of the active workspace in
``nq_calls`` and lets the teams follow each one up: a status, a responsible team,
an assignee and a shared comment thread. Every change is recorded in
``nq_call_history`` with its author and time.

Each call can also be labelled with a root cause from a configurable two-level
taxonomy (``nq_root_causes``): a domain (RF, RAN, Core, IMS/E2E…) and a cause
inside it. The keywords of every domain and cause suggest a root cause from the
CDR failure classification, and the Root Cause Analysis summarises the labelled
calls per domain and cause, call type, NR mode, technology and eNB/gNB.

Follow-up is keyed by a stable ``call_key`` derived from the call itself (its
service, Operator, Campaign and test/session identifier), so statuses and
comments survive reprocessing or uploading the same CDR again.

Its Executive Summary and Progress Status report is a Reporting artifact
(PowerPoint, Word or Excel) registered with ``register_report_artifact_provider``.
"""

import hashlib
import json
import math
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from io import BytesIO
from threading import Lock
from typing import Any

from src.modules.column_names import campaign_sort_key, column_identity
from src.modules.value_maps import ValueMapper, field_kind
from src.modules.mapping_order import dimension_order_key

NQ_CALLS_TABLE = 'nq_calls'
NQ_CALL_SOURCES_TABLE = 'nq_call_sources'
NQ_CALL_TRACKING_TABLE = 'nq_call_tracking'
NQ_CALL_COMMENTS_TABLE = 'nq_call_comments'
NQ_CALL_HISTORY_TABLE = 'nq_call_history'
NQ_CALL_OPTIONS_TABLE = 'nq_call_options'
NQ_TEAM_MEMBERS_TABLE = 'nq_team_members'
NQ_ROOT_CAUSES_TABLE = 'nq_root_causes'
# Database Management titles of the module tables.
NQ_TABLE_TITLES = {
    NQ_CALLS_TABLE: 'NQ Calls',
    NQ_CALL_SOURCES_TABLE: 'NQ Call Sources',
    NQ_CALL_TRACKING_TABLE: 'NQ Call Tracking',
    NQ_CALL_COMMENTS_TABLE: 'NQ Call Comments',
    NQ_CALL_HISTORY_TABLE: 'NQ Call History',
    NQ_CALL_OPTIONS_TABLE: 'NQ Call Options',
    NQ_TEAM_MEMBERS_TABLE: 'NQ Team Members',
    NQ_ROOT_CAUSES_TABLE: 'NQ Root Causes',
}
SERVICES = ('voice', 'speech', 'data')
SERVICE_LABELS = {'voice': 'Voice', 'speech': 'Speech', 'data': 'Data'}
QUALIFIED_RESULT = 'completed'
# Bump when the indexed fields or the call key change so every CDR is indexed again.
INDEX_VERSION = 2
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
# Root cause taxonomy: (domain, colour, keywords, causes); each cause is (name, keywords).
# Domain keywords are looked for in the CDR Failure_Classification and cause keywords in
# its Failure_Category, Failure_Subcategory and Failure_Comment.
DEFAULT_ROOT_CAUSES = (
    # Interference is DL or UL only when the CDR says so (for example the subcategory
    # "DL interference problems"); otherwise the call keeps the RF domain alone.
    ('RF', '#c8102e', ('rf',), (
        ('DL interference', ('dl interference', 'downlink interference')),
        ('UL interference', ('ul interference', 'uplink interference')),
        ('Coverage', ('coverage',)), ('BLER', ('bler',)),
    )),
    ('RAN', '#e08a1e', ('ran', 'paging'), (
        ('Handover failure', ('handover',)), ('RRC layer', ('rrc',)), ('Inter-RAT transition', ('inter-rat',)),
        ('Low throughput', ('low throughput',)), ('Paging', ('paging',)),
    )),
    ('Core 2G/4G/5G', '#6941a4', ('core', 'gsm'), (
        ('EPS bearer deactivation', ('bearer deactivation', 'eps mobility management')), ('TAU reject', ('tracking area update', 'tau ')),
        ('NAS mobility management', ('nnas', 'nas ')), ('WhatsApp session in GSM', ('session in gsm',)),
    )),
    ('Core EPSFB', '#245a96', ('epsfb', 'eps fallback'), (
        ('EPS fallback failure', ('epsfb', 'eps fallback')),
    )),
    ('IMS/E2E', '#b85b20', ('volte', 'ims'), (
        ('No QCI1 established', ('qci1', 'qci 1')), ('VoLTE core', ('volte core',)), ('E2E trace required', ('e2e',)),
    )),
    ('AAA', '#2e8b57', ('aaa',), (
        ('Authentication/Authorization', ('authentication', 'authorization')),
    )),
    ('Protocol', '#0f6f7d', ('protocol',), (
        ('Packet loss', ('packet loss',)), ('TCP connection errors', ('tcp',)), ('DNS', ('dns',)), ('HTTP', ('http',)),
        ('Data transfer timeout', ('timeout',)), ('No DL packets', ('no dl packets',)), ('Latency', ('latency',)),
    )),
    ('Device', '#7b8790', ('device',), (
        ('Device or test setup', ('device', 'modem')),
    )),
)
ROOT_CAUSE_SETTINGS_STATE_KEY = 'nq_calls_root_cause_settings'
ROOT_CAUSE_DEFAULTS_STATE_KEY = 'nq_calls_root_cause_defaults_version'
ROOT_CAUSE_RULE_STATE_KEY = 'nq_calls_root_cause_rule'
# Indexed call fields that the suggestion rule can read, with their labels.
RULE_FIELDS = {
    'failure_classification': 'Failure Classification', 'failure_category': 'Failure Category',
    'failure_subcategory': 'Failure Subcategory', 'failure_comment': 'Failure Comment',
    'failure_phase': 'Failure Phase', 'failure_technology': 'Failure Technology', 'result': 'Result',
    'test_name': 'Test Name', 'technology': 'Technology', 'direction': 'Direction',
}
RULE_MATCHES = ('words', 'text')
DEFAULT_ROOT_CAUSE_RULE = {
    'domain_fields': ['failure_classification'],
    'cause_fields': ['failure_category', 'failure_subcategory', 'failure_comment'],
    'causes_in_domain': True, 'comments': True, 'comment_domain': True, 'match': 'words',
}
ROOT_CAUSE_DEFAULTS_VERSION = 2
# Rows of the first defaults that version 2 corrects, only while they are unchanged:
# interference is DL or UL only when the CDR says so, and "E2E Trace Required" is no domain.
_ROOT_CAUSE_DEFAULT_UPGRADES = (
    ('RF', 'DL interference', ['interference'], ['dl interference', 'downlink interference']),
    ('IMS/E2E', '', ['volte', 'ims', 'e2e'], ['volte', 'ims']),
)
NOT_CLASSIFIED = 'Not classified'

# Indexed field -> CDR columns, in order of preference.
FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    'campaign': ('Campaign',),
    'operator': ('Operator', 'Operator_A', 'Home_Operator_A', 'Home_Operator'),
    'operator_vendor': ('Operator_Vendor',),
    'vendor': ('Vendor',),
    'region': ('region', 'Region'),
    'cluster': ('Cluster',),
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
    'service', 'campaign', 'operator', 'operator_vendor', 'vendor_operator', 'vendor', 'region', 'cluster', 'city',
    'technology', 'test_name', 'result', 'failure_classification', 'failure_category',
)
TRACKING_FILTERS = ('status', 'team', 'assignee', 'root_domain', 'root_cause')
TRACKING_FIELDS = ('status', 'team', 'assignee', 'root_domain', 'root_cause')
# Filters set by clicking the Progress View and Root Cause Analysis: NR mode, call type
# (Classic, WhatsApp, Data), a timeline period ("month:2026-07"), the age of open calls,
# a labelled root cause ("RF||Coverage"), the root domain or cause counting the suggested
# ones, and the eNB/gNB of the last cell ("EE||eNB 525176").
# The indicator cards filter by follow-up state (closed, attended, with team...) and the
# Suggested card by the calls without a root cause that have a suggestion.
EXTRA_FILTERS = ('nr_mode', 'call_type', 'period', 'age', 'root_pair', 'effective_domain', 'effective_cause', 'node',
                 'state', 'rca_state')
KEY_FILTERS = ('effective_domain', 'effective_cause', 'node', 'rca_state')
_ATTENDED_SQL = "(updated_at <> '' OR comment_count > 0)"
STATE_SQL = {
    'attended': _ATTENDED_SQL, 'not_attended': f'NOT {_ATTENDED_SQL}', 'with_team': "team <> ''",
    'assigned': "assignee <> ''", 'commented': 'comment_count > 0', 'labelled': "root_domain <> ''",
}
SORT_COLUMNS = {
    'service': 'service', 'start_time': 'start_time', 'operator': 'operator', 'operator_vendor': 'operator_vendor', 'vendor': 'vendor',
    'campaign': 'campaign', 'city': 'city', 'technology': 'technology', 'test_name': 'test_name',
    'result': 'result', 'failure': 'failure_classification', 'status': 'status', 'team': 'team',
    'assignee': 'assignee', 'root_cause': 'root_domain', 'cause': 'root_cause', 'comments': 'comment_count',
    'updated_at': 'updated_at',
}
# The breakdowns of the Summary, in the order of the page and of the one-slide Executive Summary.
BREAKDOWNS = (
    ('service', 'By Service'), ('result', 'By Result'), ('status', 'By Status'), ('team', 'By Team'),
    ('root_domain', 'By Root Domain'), ('failure_classification', 'By Failure Classification'),
    ('campaign', 'By Campaign'), ('operator', 'By Operator'), ('vendor', 'By Vendor'), ('region', 'By Region'),
    ('cluster', 'By Cluster'), ('city', 'By City'),
)
SEARCH_FIELDS = (
    'operator', 'operator_vendor', 'vendor', 'campaign', 'region', 'cluster', 'city', 'technology', 'test_name', 'result',
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
    root_domain TEXT NOT NULL DEFAULT '',
    root_cause TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS {NQ_TEAM_MEMBERS_TABLE} (
    team TEXT NOT NULL COLLATE NOCASE,
    username TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (team, username)
);
CREATE TABLE IF NOT EXISTS {NQ_ROOT_CAUSES_TABLE} (
    domain TEXT NOT NULL COLLATE NOCASE,
    cause TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
    color TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '[]',
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (domain, cause)
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
        root_causes_existed = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (NQ_ROOT_CAUSES_TABLE,),
        ).fetchone()
        tracking = {str(row[1]) for row in connection.execute(f'PRAGMA table_info({NQ_CALL_TRACKING_TABLE})').fetchall()}
        for column in ('root_domain', 'root_cause'):
            if tracking and column not in tracking:
                connection.execute(f"ALTER TABLE {NQ_CALL_TRACKING_TABLE} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        indexed = {str(row[1]) for row in connection.execute(f'PRAGMA table_info({NQ_CALLS_TABLE})').fetchall()}
        if indexed and not set(CALL_FIELDS) <= indexed:
            # The index is rebuilt from the CDRs whenever its fields change.
            connection.execute(f'DROP TABLE {NQ_CALLS_TABLE}')
            connection.execute(f'DROP TABLE IF EXISTS {NQ_CALL_SOURCES_TABLE}')
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
        if not root_causes_existed:
            _write_root_causes(connection, default_root_causes())
    if not root_causes_existed:
        task_repository.set_workspace_state(ROOT_CAUSE_DEFAULTS_STATE_KEY, str(ROOT_CAUSE_DEFAULTS_VERSION))
    elif str(task_repository.get_workspace_state(ROOT_CAUSE_DEFAULTS_STATE_KEY) or '1') != str(ROOT_CAUSE_DEFAULTS_VERSION):
        _upgrade_default_root_causes(task_repository)


def default_root_causes() -> list[dict[str, Any]]:
    return [{'name': domain, 'color': color, 'keywords': list(keywords),
             'causes': [{'name': cause, 'keywords': list(cause_keywords)} for cause, cause_keywords in causes]}
            for domain, color, keywords, causes in DEFAULT_ROOT_CAUSES]


def _upgrade_default_root_causes(task_repository: Any) -> None:
    """Correct, once, the rows of the first default root causes that nobody edited, and add UL interference."""
    with task_repository.connection() as connection:
        for domain, cause, old, new in _ROOT_CAUSE_DEFAULT_UPGRADES:
            row = connection.execute(
                f'SELECT keywords FROM {NQ_ROOT_CAUSES_TABLE} WHERE domain = ? AND cause = ?', (domain, cause),
            ).fetchone()
            if row is not None and _keywords(json.loads(row['keywords'] or '[]')) == old:
                connection.execute(f'UPDATE {NQ_ROOT_CAUSES_TABLE} SET keywords = ? WHERE domain = ? AND cause = ?',
                                   (json.dumps(new), domain, cause))
        dl = connection.execute(
            f"SELECT position FROM {NQ_ROOT_CAUSES_TABLE} WHERE domain = 'RF' AND cause = 'DL interference'").fetchone()
        ul = connection.execute(
            f"SELECT 1 FROM {NQ_ROOT_CAUSES_TABLE} WHERE domain = 'RF' AND cause = 'UL interference'").fetchone()
        if dl is not None and ul is None:
            # UL interference goes right after DL interference.
            connection.execute(f"UPDATE {NQ_ROOT_CAUSES_TABLE} SET position = position + 1 "
                               f"WHERE domain = 'RF' AND cause <> '' AND position > ?", (dl['position'],))
            connection.execute(
                f'INSERT OR IGNORE INTO {NQ_ROOT_CAUSES_TABLE} (domain, cause, color, keywords, position) VALUES (?, ?, ?, ?, ?)',
                ('RF', 'UL interference', '', json.dumps(['ul interference', 'uplink interference']), dl['position'] + 1),
            )
    task_repository.set_workspace_state(ROOT_CAUSE_DEFAULTS_STATE_KEY, str(ROOT_CAUSE_DEFAULTS_VERSION))


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
    """The statuses and the teams, each team with its members."""
    with task_repository.connection() as connection:
        rows = connection.execute(
            f'SELECT kind, name, color, is_closed FROM {NQ_CALL_OPTIONS_TABLE} ORDER BY kind, position, name COLLATE NOCASE'
        ).fetchall()
        members: dict[str, list[str]] = {}
        for row in connection.execute(f'SELECT team, username FROM {NQ_TEAM_MEMBERS_TABLE} ORDER BY username COLLATE NOCASE'):
            members.setdefault(str(row['team']).casefold(), []).append(str(row['username']))
    options: dict[str, list[dict[str, Any]]] = {'statuses': [], 'teams': []}
    for row in rows:
        item = {'name': str(row['name']), 'color': str(row['color'])}
        if row['kind'] == 'status':
            options['statuses'].append({**item, 'closed': bool(row['is_closed'])})
        else:
            options['teams'].append({**item, 'members': members.get(item['name'].casefold(), [])})
    return options


def team_members(options: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    """Casefolded members of every team that has members."""
    return {team['name'].casefold(): {member.casefold() for member in team.get('members') or []}
            for team in options['teams'] if team.get('members')}


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
        option = {
            'name': name,
            'previous': re.sub(r'\s+', ' ', str(item.get('previous') or '')).strip(),
            'color': color if COLOR_PATTERN.fullmatch(color) else '#7b8790',
            'closed': bool(item.get('closed')) if kind == 'status' else False,
        }
        # Teams edited without their members keep the members they have.
        if kind == 'team' and isinstance(item.get('members'), list):
            option['members'] = list(dict.fromkeys(
                str(member).strip() for member in item['members'] if str(member).strip()
            ))
        normalized.append(option)
    return normalized


def save_options(
    task_repository: Any, statuses: Any, teams: Any, username: str, users: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Replace the statuses and teams; renamed values follow on every call, removed ones must be unused.

    Team members must be users of the workspace when ``users`` is given.
    """
    current = list_options(task_repository)
    lists = {'status': _normalize_option_list(statuses, 'status'), 'team': _normalize_option_list(teams, 'team')}
    if users is not None:
        known = {name.casefold(): name for name in users}
        for team in lists['team']:
            if 'members' not in team:
                continue
            unknown = [member for member in team['members'] if member.casefold() not in known]
            if unknown:
                raise ValueError(f'{", ".join(unknown)} cannot join "{team["name"]}": choose users with access to this workspace.')
            team['members'] = [known[member.casefold()] for member in team['members']]
    if not lists['status']:
        raise ValueError('Keep at least one status.')
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
            if kind == 'team':
                previous_members = {item['name'].casefold(): item.get('members') or [] for item in current['teams']}
                connection.execute(f'DELETE FROM {NQ_TEAM_MEMBERS_TABLE}')
                rows = []
                for item in lists['team']:
                    members = item['members'] if 'members' in item else previous_members.get(
                        (item['previous'] or item['name']).casefold(), previous_members.get(item['name'].casefold(), []))
                    rows.extend((item['name'], member) for member in members)
                connection.executemany(
                    f'INSERT OR IGNORE INTO {NQ_TEAM_MEMBERS_TABLE} (team, username) VALUES (?, ?)', rows,
                )
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_call_options', 'Non-Qualified Calls statuses and teams updated.')
    return list_options(task_repository)


# ---------------------------------------------------------------------------
# Root causes: a domain and a cause inside it
# ---------------------------------------------------------------------------
def _keywords(values: Any) -> list[str]:
    if isinstance(values, str):
        values = re.split(r'[,;\n]', values)
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(text for value in values if (text := _normalized_text(value))))[:30]


def _normalized_text(value: Any) -> str:
    """Lower-case text with underscores and non-breaking spaces as spaces, for keyword matching."""
    return re.sub(r'\s+', ' ', str(value or '').replace('_', ' ').replace('\xa0', ' ')).strip().casefold()


def _write_root_causes(connection: Any, domains: list[dict[str, Any]]) -> None:
    connection.execute(f'DELETE FROM {NQ_ROOT_CAUSES_TABLE}')
    rows = []
    for position, domain in enumerate(domains):
        rows.append((domain['name'], '', domain.get('color') or '#7b8790', json.dumps(_keywords(domain.get('keywords'))), position))
        rows.extend((domain['name'], cause['name'], '', json.dumps(_keywords(cause.get('keywords'))), index)
                    for index, cause in enumerate(domain.get('causes') or []))
    connection.executemany(
        f'INSERT INTO {NQ_ROOT_CAUSES_TABLE} (domain, cause, color, keywords, position) VALUES (?, ?, ?, ?, ?)', rows,
    )


def root_cause_settings(repository: Any) -> dict[str, Any]:
    try:
        stored = json.loads(repository.get_workspace_state(ROOT_CAUSE_SETTINGS_STATE_KEY) or '{}')
    except (TypeError, ValueError):
        stored = {}
    return {'require_to_close': bool(isinstance(stored, dict) and stored.get('require_to_close')),
            'rule': root_cause_rule(repository)}


def normalize_root_cause_rule(rule: Any) -> dict[str, Any]:
    """A valid suggestion rule: known fields in their order, flags and the keyword matching."""
    if not isinstance(rule, dict):
        raise ValueError('The root cause rule is invalid.')

    def fields(key: str) -> list[str]:
        values = rule.get(key)
        if not isinstance(values, list):
            raise ValueError('The root cause rule is invalid.')
        unknown = [str(value) for value in values if str(value) not in RULE_FIELDS]
        if unknown:
            raise ValueError(f'Unknown root cause rule fields: {", ".join(unknown)}.')
        return list(dict.fromkeys(str(value) for value in values))

    normalized = {'domain_fields': fields('domain_fields'), 'cause_fields': fields('cause_fields')}
    if not normalized['domain_fields'] and not normalized['cause_fields'] and not rule.get('comments'):
        raise ValueError('The rule must read at least one field or the comments.')
    normalized.update({key: bool(rule.get(key)) for key in ('causes_in_domain', 'comments', 'comment_domain')})
    normalized['match'] = str(rule.get('match') or 'words')
    if normalized['match'] not in RULE_MATCHES:
        raise ValueError('Choose whole-word or partial keyword matching.')
    return normalized


def root_cause_rule(repository: Any) -> dict[str, Any]:
    """The workspace suggestion rule, or the default one."""
    try:
        stored = json.loads(repository.get_workspace_state(ROOT_CAUSE_RULE_STATE_KEY) or 'null')
        return normalize_root_cause_rule(stored) if stored else dict(DEFAULT_ROOT_CAUSE_RULE)
    except (TypeError, ValueError):
        return dict(DEFAULT_ROOT_CAUSE_RULE)


def save_root_cause_rule(repository: Any, rule: Any, username: str) -> dict[str, Any]:
    """Save the suggestion rule; None restores the default one."""
    if rule is None:
        repository.set_workspace_state(ROOT_CAUSE_RULE_STATE_KEY, '')
    else:
        repository.set_workspace_state(ROOT_CAUSE_RULE_STATE_KEY, json.dumps(normalize_root_cause_rule(rule)))
    if hasattr(repository, 'try_add_log'):
        repository.try_add_log(username, 'nq_root_cause_rule', 'Non-Qualified Calls root cause suggestion rule updated.')
    return root_cause_rule(repository)


def _current_root_causes(connection: Any) -> list[dict[str, Any]]:
    """The taxonomy read inside an open transaction (for the tracking import)."""
    rows = connection.execute(
        f'SELECT domain, cause, color, keywords, position FROM {NQ_ROOT_CAUSES_TABLE} ORDER BY position, cause COLLATE NOCASE'
    ).fetchall()
    domains = {str(row['domain']).casefold(): {'name': str(row['domain']), 'color': str(row['color']), 'causes': [],
                                               'keywords': _keywords(json.loads(row['keywords'] or '[]'))}
               for row in rows if not row['cause']}
    for row in rows:
        if row['cause'] and str(row['domain']).casefold() in domains:
            domains[str(row['domain']).casefold()]['causes'].append(
                {'name': str(row['cause']), 'keywords': _keywords(json.loads(row['keywords'] or '[]'))})
    return list(domains.values())


def list_root_causes(task_repository: Any) -> dict[str, Any]:
    """The root cause domains in order, each with its colour, keywords and causes, and the settings."""
    with task_repository.connection() as connection:
        rows = connection.execute(
            f'SELECT domain, cause, color, keywords, position FROM {NQ_ROOT_CAUSES_TABLE} ORDER BY position, cause COLLATE NOCASE'
        ).fetchall()
    domains: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row['cause']:
            domains[str(row['domain']).casefold()] = {
                'name': str(row['domain']), 'color': str(row['color'] or '#7b8790'), 'position': int(row['position']),
                'keywords': _keywords(json.loads(row['keywords'] or '[]')), 'causes': [],
            }
    for row in rows:
        domain = domains.get(str(row['domain']).casefold())
        if row['cause'] and domain is not None:
            domain['causes'].append({'name': str(row['cause']), 'keywords': _keywords(json.loads(row['keywords'] or '[]'))})
    ordered = sorted(domains.values(), key=lambda item: item['position'])
    for domain in ordered:
        domain.pop('position')
    return {'domains': ordered, **root_cause_settings(task_repository)}


def _normalize_root_causes(domains: Any) -> list[dict[str, Any]]:
    if not isinstance(domains, list):
        raise ValueError('The root cause list is invalid.')
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in domains:
        if not isinstance(item, dict):
            raise ValueError('The root cause list is invalid.')
        name = re.sub(r'\s+', ' ', str(item.get('name') or '')).strip()[:60]
        if not name:
            raise ValueError('Every root cause domain needs a name.')
        if name.casefold() in seen:
            raise ValueError(f'The domain "{name}" is repeated.')
        seen.add(name.casefold())
        color = str(item.get('color') or '').strip()
        causes: list[dict[str, Any]] = []
        cause_names: set[str] = set()
        for cause in item.get('causes') or []:
            if not isinstance(cause, dict):
                raise ValueError('The root cause list is invalid.')
            cause_name = re.sub(r'\s+', ' ', str(cause.get('name') or '')).strip()[:80]
            if not cause_name:
                raise ValueError(f'Every cause of "{name}" needs a name.')
            if cause_name.casefold() in cause_names:
                raise ValueError(f'The cause "{cause_name}" is repeated in "{name}".')
            cause_names.add(cause_name.casefold())
            causes.append({'name': cause_name, 'keywords': _keywords(cause.get('keywords')),
                           'previous': re.sub(r'\s+', ' ', str(cause.get('previous') or '')).strip()})
        normalized.append({
            'name': name, 'color': color if COLOR_PATTERN.fullmatch(color) else '#7b8790',
            'keywords': _keywords(item.get('keywords')), 'causes': causes,
            'previous': re.sub(r'\s+', ' ', str(item.get('previous') or '')).strip(),
        })
    return normalized


def save_root_causes(task_repository: Any, domains: Any, require_to_close: bool, username: str) -> dict[str, Any]:
    """Replace the root cause taxonomy; renamed values follow on every call, removed ones must be unused."""
    current = list_root_causes(task_repository)
    normalized = _normalize_root_causes(domains)
    existing = {domain['name'].casefold(): domain for domain in current['domains']}
    with task_repository.connection() as connection:
        def used(domain: str, cause: str | None = None) -> int:
            sql = f'SELECT COUNT(*) FROM {NQ_CALL_TRACKING_TABLE} WHERE root_domain = ? COLLATE NOCASE'
            params = [domain]
            if cause is not None:
                sql += ' AND root_cause = ? COLLATE NOCASE'
                params.append(cause)
            return int(connection.execute(sql, params).fetchone()[0])

        kept_domains: dict[str, dict[str, Any]] = {}
        for domain in normalized:
            previous = existing.get((domain['previous'] or domain['name']).casefold())
            if previous is not None:
                kept_domains[previous['name'].casefold()] = domain
        for key, domain in existing.items():
            if key not in kept_domains and used(domain['name']):
                raise ValueError(f'The domain "{domain["name"]}" is in use; rename it or change the root cause of its calls first.')
        for old_key, domain in kept_domains.items():
            old = existing[old_key]
            old_causes = {cause['name'].casefold(): cause['name'] for cause in old['causes']}
            renamed = {cause['previous'].casefold(): cause['name'] for cause in domain['causes']
                       if cause['previous'] and cause['previous'].casefold() in old_causes}
            kept = {cause['name'].casefold() for cause in domain['causes']} | set(renamed)
            for cause_key, cause_name in old_causes.items():
                if cause_key not in kept and used(old['name'], cause_name):
                    raise ValueError(f'The cause "{cause_name}" of "{old["name"]}" is in use; rename it or change the root cause of its calls first.')
            for cause_key, new_name in renamed.items():
                connection.execute(
                    f'UPDATE {NQ_CALL_TRACKING_TABLE} SET root_cause = ? WHERE root_domain = ? COLLATE NOCASE '
                    'AND root_cause = ? COLLATE NOCASE', (new_name, old['name'], old_causes[cause_key]),
                )
            if old['name'] != domain['name']:
                connection.execute(
                    f'UPDATE {NQ_CALL_TRACKING_TABLE} SET root_domain = ? WHERE root_domain = ? COLLATE NOCASE',
                    (domain['name'], old['name']),
                )
        _write_root_causes(connection, normalized)
    task_repository.set_workspace_state(ROOT_CAUSE_SETTINGS_STATE_KEY, json.dumps({'require_to_close': bool(require_to_close)}))
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_root_causes', 'Non-Qualified Calls root causes updated.')
    return list_root_causes(task_repository)


def _keyword_found(keywords: list[str], text: str, match: str = 'words') -> bool:
    """Whether a keyword appears in the text: as whole words ("rf" in "RF Problems", not in "performance"),
    or anywhere with the partial matching of the rule."""
    if not text:
        return False
    if match == 'text':
        return any(keyword in text for keyword in keywords)
    return any(re.search(rf'(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])', text) for keyword in keywords)


def _matching_cause(domains: list[dict[str, Any]], text: str, match: str = 'words') -> dict[str, str] | None:
    for domain in domains:
        for cause in domain['causes']:
            if _keyword_found(cause['keywords'], text, match):
                return {'domain': domain['name'], 'cause': cause['name']}
    return None


def suggest_root_cause(call: Any, taxonomy: dict[str, Any], comments: str = '') -> dict[str, str] | None:
    """The root cause suggested by the call, following the workspace suggestion rule.

    With the default rule:
    1. A domain keyword in the CDR Failure Classification chooses the domain.
    2. A cause keyword in the Failure Category, Subcategory or Comment chooses the cause:
       among the causes of that domain, or of every domain when no domain matched.
    3. When the CDR leaves the cause unresolved, the comments of the engineers are read the
       same way: a cause of the CDR domain (or of any domain), else a domain keyword.
    Admins and super-admins choose the fields of steps 1 and 2, whether causes stay in the domain, the
    use of the comments and the keyword matching. Domains and causes are tried in their
    configured order. ``source`` tells where the cause came from.
    """
    rule = taxonomy.get('rule') or DEFAULT_ROOT_CAUSE_RULE
    match = rule['match']

    def text(fields: list[str]) -> str:
        values = []
        for field in fields:
            try:
                values.append(_normalized_text(call[field]))
            except (KeyError, IndexError):
                continue
        return ' | '.join(value for value in values if value)

    domains = taxonomy['domains']
    classification = text(rule['domain_fields'])
    details = text(rule['cause_fields'])
    matched_domain = next((domain for domain in domains if _keyword_found(domain['keywords'], classification, match)), None)
    candidates = [matched_domain] if matched_domain and rule['causes_in_domain'] else domains
    found = _matching_cause(candidates, details, match)
    if found:
        return {**found, 'source': 'cdr'}
    notes = _normalized_text(comments) if rule['comments'] else ''
    found = _matching_cause(candidates, notes, match)
    if found:
        return {**found, 'source': 'comments'}
    if matched_domain is not None:
        return {'domain': matched_domain['name'], 'cause': '', 'source': 'cdr'}
    if rule['comment_domain']:
        commented_domain = next((domain for domain in domains if _keyword_found(domain['keywords'], notes, match)), None)
        if commented_domain is not None:
            return {'domain': commented_domain['name'], 'cause': '', 'source': 'comments'}
    return None


def _comment_texts(connection: Any, keys: list[str]) -> dict[str, str]:
    """The text of the comments of each call (deleted comments left out), for the root cause fallback."""
    texts: dict[str, list[str]] = {}
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        for row in connection.execute(
            f"SELECT call_key, body FROM {NQ_CALL_COMMENTS_TABLE} WHERE deleted_at = '' "
            f"AND call_key IN ({', '.join('?' for _ in chunk)}) ORDER BY id", chunk,
        ):
            texts.setdefault(str(row['call_key']), []).append(str(row['body']))
    return {key: '\n'.join(bodies) for key, bodies in texts.items()}


# ---------------------------------------------------------------------------
# Querying calls
# ---------------------------------------------------------------------------
# Operators and Vendors are indexed as the CDRs spell them and shown with their Operator
# and Vendor Maps labels, so filters, breakdowns, the table and exports use the mapped values.
MAPPED_FIELDS = ('operator', 'operator_vendor', 'vendor')


def _value_maps(task_repository: Any) -> dict[str, str]:
    """For each mapped field, a JSON object from the indexed source values to their mapped labels.

    ``vendor_operator`` maps each source Operator_Vendor to its mapped Vendor_Operator.
    """
    mapper = ValueMapper.from_repository(task_repository)
    maps = {}
    with task_repository.connection() as connection:
        for field in MAPPED_FIELDS:
            rows = connection.execute(f"SELECT DISTINCT {field} AS value FROM {NQ_CALLS_TABLE} WHERE {field} <> ''").fetchall()
            mapped = {str(row['value']): str(mapper.map(field_kind(field), row['value'])) for row in rows}
            maps[field] = json.dumps({source: label for source, label in mapped.items() if source != label})
            if field == 'operator_vendor':
                maps['vendor_operator'] = json.dumps({source: mapper.vendor_operators([label])[0]
                                                      for source, label in mapped.items()})
    return maps


def _base_sql(default: str, task_repository: Any) -> tuple[str, list[Any]]:
    """One row per call (the newest CDR wins when a call is uploaded twice) with its follow-up."""
    maps = _value_maps(task_repository)
    columns = ', '.join(
        f'COALESCE((SELECT m.value FROM json_each(?) m WHERE m.key = c.{column}), c.{column}) AS {column}'
        if column in MAPPED_FIELDS else f'c.{column}'
        for column in ('dataset_id', 'source_row_id', 'call_key', 'service', 'nr_mode', *CALL_FIELDS)
    )
    map_params = [maps[column] for column in ('dataset_id', 'source_row_id', 'call_key', 'service', 'nr_mode', *CALL_FIELDS)
                  if column in MAPPED_FIELDS]
    # Vendor_Operator: the mapped Operator_Vendor the other way round.
    columns += ", COALESCE((SELECT m.value FROM json_each(?) m WHERE m.key = c.operator_vendor), '') AS vendor_operator"
    map_params.append(maps['vendor_operator'])
    sql = f"""
        SELECT {columns},
               COALESCE(NULLIF(t.status, ''), ?) AS status,
               COALESCE(t.team, '') AS team,
               COALESCE(t.assignee, '') AS assignee,
               COALESCE(t.root_domain, '') AS root_domain,
               COALESCE(t.root_cause, '') AS root_cause,
               COALESCE(t.version, 0) AS version,
               COALESCE(t.updated_by, '') AS updated_by,
               COALESCE(t.updated_at, '') AS updated_at,
               (SELECT COUNT(*) FROM {NQ_CALL_COMMENTS_TABLE} m WHERE m.call_key = c.call_key AND m.deleted_at = '') AS comment_count
        FROM {NQ_CALLS_TABLE} c
        LEFT JOIN {NQ_CALL_TRACKING_TABLE} t ON t.call_key = c.call_key
        WHERE c.rowid IN (SELECT MAX(rowid) FROM {NQ_CALLS_TABLE} GROUP BY call_key)
    """
    return sql, [*map_params, default]


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value) for value in values if value is not None))


# The Filters panel is shared: every user of the workspace finds the last selection, in any session.
SAVED_FILTERS_STATE_KEY = 'nq_calls_filters'
FLAG_FILTERS = ('open_only', 'mine', 'without_comments')


def normalize_saved_filters(filters: Any) -> dict[str, Any]:
    """The known filters of a selection: value lists, flags and the search text."""
    filters = filters if isinstance(filters, dict) else {}
    saved: dict[str, Any] = {}
    for field in (*FIELD_FILTERS, *TRACKING_FILTERS, *EXTRA_FILTERS, 'datasets'):
        values = _strings(filters.get(field))[:5000]
        if values:
            saved[field] = values
    saved.update({flag: True for flag in FLAG_FILTERS if filters.get(flag) is True})
    search = str(filters.get('search') or '').strip()[:200]
    if search:
        saved['search'] = search
    return saved


def saved_filters(repository: Any) -> dict[str, Any]:
    try:
        return normalize_saved_filters(json.loads(repository.get_workspace_state(SAVED_FILTERS_STATE_KEY) or '{}'))
    except (TypeError, ValueError):
        return {}


def save_filters(repository: Any, filters: Any) -> dict[str, Any]:
    saved = normalize_saved_filters(filters)
    repository.set_workspace_state(SAVED_FILTERS_STATE_KEY, json.dumps(saved, ensure_ascii=False, sort_keys=True))
    return saved


CALL_TYPE_SQL = ("CASE WHEN service = 'data' THEN 'Data' WHEN instr(lower(test_name), 'whatsapp') > 0 "
                 "THEN 'WhatsApp' ELSE 'Classic' END")
START_SQL = "replace(substr(start_time, 1, 19), 'T', ' ')"
_AGE_DAYS = f"(julianday('now', 'localtime') - julianday({START_SQL}))"
AGE_SQL = {
    'Under 7 days': f'{_AGE_DAYS} < 7', '7–30 days': f'({_AGE_DAYS} >= 7 AND {_AGE_DAYS} < 30)',
    '30–90 days': f'({_AGE_DAYS} >= 30 AND {_AGE_DAYS} < 90)', 'Over 90 days': f'{_AGE_DAYS} >= 90',
    'Unknown date': f'julianday({START_SQL}) IS NULL',
}


def period_bounds(value: str) -> tuple[str, str] | None:
    """Start and end (excluded) of a timeline period such as "month:2026-07" or "week:2026-W28"."""
    from datetime import timedelta

    granularity, _, label = str(value).partition(':')
    try:
        if granularity == 'week':
            year, week = label.split('-W')
            start = datetime.fromisocalendar(int(year), int(week), 1)
            end = start + timedelta(days=7)
        elif granularity == 'month':
            year, month = (int(part) for part in label.split('-'))
            start = datetime(year, month, 1)
            end = datetime(year + (month == 12), month % 12 + 1, 1)
        elif granularity == 'quarter':
            year, quarter = label.split('-Q')
            month = (int(quarter) - 1) * 3 + 1
            start = datetime(int(year), month, 1)
            end = datetime(int(year) + (month == 10), (month + 2) % 12 + 1, 1)
        elif granularity == 'year':
            start, end = datetime(int(label), 1, 1), datetime(int(label) + 1, 1, 1)
        else:
            return None
    except (TypeError, ValueError):
        return None
    return start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S')


def _resolve_key_filters(task_repository: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Turn the filters computed per call (root cause counting suggestions, eNB/gNB) into call keys.

    Operator and Vendor selections are compared with the mapped values, so a source
    spelling saved before (for example Vodafone UK) selects its mapped label (VF).
    """
    if any(_strings(filters.get(field)) for field in (*MAPPED_FIELDS, 'vendor_operator')):
        mapper = ValueMapper.from_repository(task_repository)
        filters = {**filters, **{field: [str(mapper.map(field_kind(field), value)) for value in _strings(filters.get(field))]
                                 for field in (*MAPPED_FIELDS, 'vendor_operator') if _strings(filters.get(field))}}
    wanted = {field: set(_strings(filters.get(field))) for field in KEY_FILTERS}
    if not any(wanted.values()):
        return filters
    suggestions_needed = bool(wanted['effective_domain'] or wanted['effective_cause'] or wanted['rca_state'])
    options = list_options(task_repository)
    taxonomy = list_root_causes(task_repository)
    base, base_params = _base_sql(default_status(options), task_repository)
    with task_repository.connection() as connection:
        calls = connection.execute(f'WITH calls AS ({base}) SELECT * FROM calls', base_params).fetchall()
        notes = _comment_texts(connection, [str(call['call_key']) for call in calls if not call['root_domain']]) \
            if suggestions_needed else {}
    keys = []
    for call in calls:
        key = str(call['call_key'])
        if suggestions_needed:
            domain, cause = str(call['root_domain'] or ''), str(call['root_cause'] or '')
            suggestion = None if domain else suggest_root_cause(call, taxonomy, notes.get(key, ''))
            if suggestion:
                domain, cause = suggestion['domain'], suggestion['cause']
            if wanted['rca_state'] and not ('suggested' in wanted['rca_state'] and suggestion):
                continue
            if wanted['effective_domain'] and (domain or UNASSIGNED) not in wanted['effective_domain']:
                continue
            if wanted['effective_cause'] and f'{domain}||{cause}' not in wanted['effective_cause']:
                continue
        if wanted['node']:
            node = serving_node(call['cell_id'])
            if node is None or f"{call['operator'] or ''}||{node[0]} {node[1]}" not in wanted['node']:
                continue
        keys.append(key)
    return {**filters, '_call_keys': keys}


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
    states = _strings(filters.get('state'))
    for state in states:
        if state == 'closed':
            marks = ', '.join('?' for _ in closed_statuses) or "''"
            clauses.append(f'status IN ({marks})')
            params.extend(closed_statuses)
        elif state in STATE_SQL:
            clauses.append(STATE_SQL[state])
    if filters.get('open_only') and closed_statuses:
        clauses.append(f"status NOT IN ({', '.join('?' for _ in closed_statuses)})")
        params.extend(closed_statuses)
    if filters.get('mine'):
        clauses.append('assignee = ? COLLATE NOCASE')
        params.append(username)
    if filters.get('without_comments'):
        clauses.append('comment_count = 0')
    nr_modes = ['' if value in {UNASSIGNED, 'Unknown'} else value for value in _strings(filters.get('nr_mode'))]
    if nr_modes:
        clauses.append(f"nr_mode IN ({', '.join('?' for _ in nr_modes)})")
        params.extend(nr_modes)
    call_types = _strings(filters.get('call_type'))
    if call_types:
        clauses.append(f"({CALL_TYPE_SQL}) IN ({', '.join('?' for _ in call_types)})")
        params.extend(call_types)
    ranges = [bounds for value in _strings(filters.get('period')) if (bounds := period_bounds(value))]
    if ranges:
        clauses.append('(' + ' OR '.join(f'({START_SQL} >= ? AND {START_SQL} < ?)' for _ in ranges) + ')')
        params.extend(bound for pair in ranges for bound in pair)
    ages = [condition for value in _strings(filters.get('age')) if (condition := AGE_SQL.get(value))]
    if ages:
        clauses.append('(' + ' OR '.join(ages) + ')')
    pairs = _strings(filters.get('root_pair'))
    if pairs:
        clauses.append(f"(root_domain || '||' || root_cause) IN ({', '.join('?' for _ in pairs)})")
        params.extend('||' if value == UNASSIGNED else value for value in pairs)
    if '_call_keys' in filters:
        clauses.append('call_key IN (SELECT value FROM json_each(?))')
        params.append(json.dumps(list(filters['_call_keys'])))
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
    filters = _resolve_key_filters(task_repository, filters)
    closed = [item['name'] for item in options['statuses'] if item['closed']]
    base, base_params = _base_sql(default_status(options), task_repository)
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
        notes = _comment_texts(connection, [call['call_key'] for call in calls])
        taxonomy = list_root_causes(task_repository)
        for call in calls:
            call['last_comment'] = last_comments.get(call['call_key'])
            call['suggested_root_cause'] = suggest_root_cause(call, taxonomy, notes.get(call['call_key'], ''))
        breakdowns = []
        mapping_settings = task_repository.chart_mapping_settings()
        for field, label in BREAKDOWNS:
            values = connection.execute(
                f'SELECT {field} AS value, COUNT(*) AS count FROM ({filtered}) GROUP BY {field} ORDER BY count DESC, value LIMIT 12',
                all_params,
            ).fetchall()
            items = [{'value': str(row['value'] or ''), 'count': int(row['count'])} for row in values]
            # The largest Operators and Vendors are listed in Operator Map and Vendor Map order,
            # and Campaigns chronologically (the plain, NSA and SA campaigns of a quarter in that order).
            if field in {'operator', 'vendor', 'operator_vendor'}:
                items.sort(key=lambda item, field=field: dimension_order_key(
                    field, item['value'], mapping_settings['operator_mapping_groups'], mapping_settings['vendor_mapping_groups'],
                ))
            elif field == 'campaign':
                items.sort(key=lambda item: campaign_sort_key(item['value']))
            breakdowns.append({'field': field, 'label': label, 'items': items})
        closed_marks = ', '.join('?' for _ in closed) or "''"
        summary = connection.execute(
            f"SELECT COUNT(*) AS total, "
            f"SUM(CASE WHEN status IN ({closed_marks}) THEN 1 ELSE 0 END) AS closed, "
            f"SUM(CASE WHEN comment_count > 0 THEN 1 ELSE 0 END) AS commented, "
            # Attended: followed up (a status, team, assignee or root cause change) or commented.
            f"SUM(CASE WHEN updated_at <> '' OR comment_count > 0 THEN 1 ELSE 0 END) AS attended, "
            f"SUM(CASE WHEN team <> '' THEN 1 ELSE 0 END) AS with_team, "
            f"SUM(CASE WHEN assignee <> '' THEN 1 ELSE 0 END) AS assigned "
            f"FROM ({filtered})",
            [*closed, *all_params],
        ).fetchone()
    summary_payload = {key: int(summary[key] or 0) for key in ('total', 'closed', 'attended', 'commented', 'with_team', 'assigned')}
    summary_payload['open'] = summary_payload['total'] - summary_payload['closed']
    return {
        'calls': calls, 'total': total, 'page': page, 'pages': pages, 'page_size': page_size,
        'sort': next((key for key, column in SORT_COLUMNS.items() if column == sort), 'start_time'),
        'direction': direction.lower(), 'summary': summary_payload, 'breakdowns': breakdowns,
    }


def filter_options(task_repository: Any) -> dict[str, list[str]]:
    """Distinct values of every indexed filter; Operators and Vendors with their mapped labels."""
    values: dict[str, list[str]] = {}
    mapper = ValueMapper.from_repository(task_repository)
    with task_repository.connection() as connection:
        for field in FIELD_FILTERS:
            if field == 'vendor_operator':
                # Derived from the mapped Operator_Vendor values (listed before it).
                values[field] = mapper.values('vendor_operator', mapper.vendor_operators(values.get('operator_vendor') or []))
                continue
            rows = connection.execute(
                f"SELECT DISTINCT {field} AS value FROM {NQ_CALLS_TABLE} WHERE {field} <> '' ORDER BY value COLLATE NOCASE"
            ).fetchall()
            values[field] = [str(row['value']) for row in rows]
            if field in MAPPED_FIELDS:
                values[field] = [str(value) for value in mapper.values(field_kind(field), values[field])]
            elif field == 'campaign':
                values[field] = sorted(values[field], key=campaign_sort_key)
        assignees = connection.execute(
            f"SELECT DISTINCT assignee FROM {NQ_CALL_TRACKING_TABLE} WHERE assignee <> '' ORDER BY assignee COLLATE NOCASE"
        ).fetchall()
    values['assignee'] = [str(row['assignee']) for row in assignees]
    return values


PROGRESS_GRANULARITIES = ('week', 'month', 'quarter', 'year')
AGE_BUCKETS = ((7, 'Under 7 days'), (30, '7–30 days'), (90, '30–90 days'), (None, 'Over 90 days'))


def _parse_time(value: Any) -> datetime | None:
    text = _text(value).replace('T', ' ')
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone().replace(tzinfo=None)


def period_label(moment: datetime, granularity: str) -> str:
    """The week (ISO), month, quarter or year a moment belongs to."""
    if granularity == 'week':
        year, week, _day = moment.isocalendar()
        return f'{year}-W{week:02d}'
    if granularity == 'quarter':
        return f'{moment.year}-Q{(moment.month - 1) // 3 + 1}'
    if granularity == 'year':
        return str(moment.year)
    return f'{moment.year}-{moment.month:02d}'


def progress_stats(task_repository: Any, filters: dict[str, Any], username: str, granularity: str = 'month') -> dict[str, Any]:
    """Follow-up progress of the calls matching the filters.

    Distributions by status, team, assignee, service and result; how many calls
    were detected, attended (first change or comment), commented, moved to each
    status, closed and reopened per week, month, quarter or year; the open
    backlog, the age of open calls, the workload of teams and assignees and the
    activity of every user.
    """
    granularity = granularity if granularity in PROGRESS_GRANULARITIES else 'month'
    options = list_options(task_repository)
    closed_names = {item['name'].casefold() for item in options['statuses'] if item['closed']}
    base, base_params = _base_sql(default_status(options), task_repository)
    where, params = _filter_sql(_resolve_key_filters(task_repository, filters), username,
                                [item['name'] for item in options['statuses'] if item['closed']])
    with task_repository.connection() as connection:
        calls = connection.execute(
            f'WITH calls AS ({base}) SELECT call_key, start_time, status, team, assignee, service, result FROM calls{where}',
            [*base_params, *params],
        ).fetchall()
        keys = [str(row['call_key']) for row in calls]
        history: list[Any] = []
        comments: list[Any] = []
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ', '.join('?' for _ in chunk)
            history.extend(connection.execute(
                f'SELECT call_key, field, old_value, new_value, changed_by, changed_at FROM {NQ_CALL_HISTORY_TABLE} '
                f'WHERE call_key IN ({marks}) ORDER BY changed_at, id', chunk).fetchall())
            comments.extend(connection.execute(
                f'SELECT call_key, created_by, created_at, deleted_at FROM {NQ_CALL_COMMENTS_TABLE} '
                f'WHERE call_key IN ({marks}) ORDER BY created_at, id', chunk).fetchall())

    def distribution(field: str, empty: str, order: list[str] | None = None) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for row in calls:
            value = str(row[field] or '') or empty
            counts[value] = counts.get(value, 0) + 1
        ordered = [name for name in (order or []) if name in counts]
        ordered += sorted((name for name in counts if name not in ordered), key=lambda name: (-counts[name], name.casefold()))
        return [{'value': name, 'count': counts[name]} for name in ordered]

    first_followup: dict[str, datetime] = {}
    closed_at: dict[str, datetime] = {}
    timeline: dict[str, dict[str, Any]] = {}

    def bucket(moment: datetime | None) -> dict[str, Any] | None:
        if moment is None:
            return None
        label = period_label(moment, granularity)
        return timeline.setdefault(label, {
            'period': label, 'detected': 0, 'attended': 0, 'comments': 0, 'changes': 0,
            'closed': 0, 'reopened': 0, 'statuses': {}, 'close_days': [],
        })

    def follow_up(key: str, moment: datetime | None) -> None:
        if moment is not None and (key not in first_followup or moment < first_followup[key]):
            first_followup[key] = moment

    activity: dict[str, dict[str, int]] = {}
    for row in history:
        moment = _parse_time(row['changed_at'])
        key = str(row['call_key'])
        follow_up(key, moment)
        user = activity.setdefault(str(row['changed_by'] or '—'), {'changes': 0, 'comments': 0, 'closed': 0})
        user['changes'] += 1
        target = bucket(moment)
        if target is not None:
            target['changes'] += 1
        if row['field'] != 'status' or target is None:
            continue
        new_value, old_value = str(row['new_value']), str(row['old_value'])
        target['statuses'][new_value] = target['statuses'].get(new_value, 0) + 1
        if new_value.casefold() in closed_names and old_value.casefold() not in closed_names:
            target['closed'] += 1
            user['closed'] += 1
            closed_at[key] = moment
        elif old_value.casefold() in closed_names and new_value.casefold() not in closed_names:
            target['reopened'] += 1
            closed_at.pop(key, None)
    for row in comments:
        moment = _parse_time(row['created_at'])
        follow_up(str(row['call_key']), moment)
        activity.setdefault(str(row['created_by'] or '—'), {'changes': 0, 'comments': 0, 'closed': 0})['comments'] += 1
        target = bucket(moment)
        if target is not None:
            target['comments'] += 1
    for row in calls:
        target = bucket(_parse_time(row['start_time']))
        if target is not None:
            target['detected'] += 1
    for key, moment in first_followup.items():
        bucket(moment)['attended'] += 1
    for key, moment in closed_at.items():
        if key in first_followup:
            bucket(moment)['close_days'].append((moment - first_followup[key]).total_seconds() / 86400)

    periods = []
    backlog = 0
    for label in sorted(timeline):
        item = timeline[label]
        backlog += item['detected'] - item['closed'] + item['reopened']
        days = item.pop('close_days')
        periods.append({**item, 'open_backlog': max(backlog, 0),
                        'avg_days_to_close': round(sum(days) / len(days), 1) if days else None})

    open_calls = [row for row in calls if str(row['status']).casefold() not in closed_names]
    now = datetime.now()
    ages: dict[str, int] = {label: 0 for _limit, label in AGE_BUCKETS}
    ages['Unknown date'] = 0
    for row in open_calls:
        moment = _parse_time(row['start_time'])
        if moment is None:
            ages['Unknown date'] += 1
            continue
        days = (now - moment).total_seconds() / 86400
        ages[next(label for limit, label in AGE_BUCKETS if limit is None or days < limit)] += 1

    def workload(field: str) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for row in calls:
            name = str(row[field] or '') or 'Unassigned'
            entry = rows.setdefault(name, {'name': name, 'open': 0, 'closed': 0, 'total': 0})
            entry['total'] += 1
            entry['closed' if str(row['status']).casefold() in closed_names else 'open'] += 1
        return sorted(rows.values(), key=lambda entry: (-entry['open'], -entry['total'], entry['name'].casefold()))

    attended = [key for key in keys if key in first_followup]
    response_days = []
    starts = {str(row['call_key']): _parse_time(row['start_time']) for row in calls}
    for key in attended:
        if starts.get(key) is not None and first_followup[key] >= starts[key]:
            response_days.append((first_followup[key] - starts[key]).total_seconds() / 86400)
    close_days = [(closed_at[key] - first_followup[key]).total_seconds() / 86400
                  for key in closed_at if key in first_followup]
    total = len(calls)
    closed_total = total - len(open_calls)
    return {
        'granularity': granularity,
        'summary': {
            'total': total, 'attended': len(attended), 'not_attended': total - len(attended),
            'open': len(open_calls), 'closed': closed_total,
            'closure_rate': round(closed_total * 100 / total, 1) if total else 0.0,
            'comments': sum(1 for row in comments if not row['deleted_at']),
            'changes': len(history), 'contributors': len(activity),
            'avg_days_to_first_follow_up': round(sum(response_days) / len(response_days), 1) if response_days else None,
            'avg_days_to_close': round(sum(close_days) / len(close_days), 1) if close_days else None,
        },
        'distributions': [
            {'field': 'status', 'label': 'By Status', 'items': distribution('status', '—', [item['name'] for item in options['statuses']])},
            {'field': 'team', 'label': 'By Team', 'items': distribution('team', 'Unassigned', [item['name'] for item in options['teams']])},
            {'field': 'assignee', 'label': 'By Assignee', 'items': distribution('assignee', 'Unassigned')},
            {'field': 'service', 'label': 'By Service', 'items': [
                {**item, 'value': SERVICE_LABELS.get(item['value'], item['value']), 'filter': item['value']}
                for item in distribution('service', '—')]},
            {'field': 'result', 'label': 'By Result', 'items': distribution('result', '—')},
        ],
        'aging': [{'value': label, 'count': count} for label, count in ages.items() if count or label != 'Unknown date'],
        'periods': periods,
        'statuses': [item['name'] for item in options['statuses']],
        'teams': workload('team'),
        'assignees': workload('assignee')[:20],
        'activity': sorted(({'name': name, **values} for name, values in activity.items()),
                           key=lambda entry: (-(entry['changes'] + entry['comments']), entry['name'].casefold()))[:20],
    }


# ---------------------------------------------------------------------------
# Root Cause Analysis
# ---------------------------------------------------------------------------
MAX_ECI = 268_435_455  # 28-bit E-UTRAN Cell Identity; larger identities are NR cells (36-bit NCI).
MAX_NODES = 25
MAX_RATS = 12
_CELL_NUMBERS = re.compile(r'\d+')
NODE_MAPPING_COLUMNS = {
    'eci': ('CId___ECI', 'ECI', 'ECGI'),
    'enb': ('eNBId', 'eNodeB ID', 'eNodeB_ID', 'ENodeBFunctionId'),
    'gnb': ('gNodeB ID', 'gNodeB_ID', 'gNBId', 'GNBDUFunctionId'),
    'site': ('Site_Name', 'Site Name', 'eNodeB', 'gNodeB', 'Site_ID', 'Site ID'),
    'host': ('Host OSS', 'OSS Name', 'OssName', 'Host Network'),
    'vendor': ('Vendor_Only', 'OP_Vendor', 'OP/ Vendor', 'Vendor'),
}
# Cell mapping datasets and the operators they describe.
MAPPING_OPERATORS = {'mapping_vodafone': re.compile(r'^(vf|vodafone)(?![a-z0-9])', re.I),
                     'mapping_three': re.compile(r'^(3|three|h3g)(?![a-z0-9])', re.I)}
_node_mapping_cache: dict[tuple[str, int, str], dict[tuple[str, int], dict[str, str]]] = {}


def call_type(service: str, test_name: str) -> str:
    """Classic or WhatsApp for Voice and Speech calls; Data for the Data tests."""
    if service == 'data':
        return 'Data'
    return 'WhatsApp' if 'whatsapp' in str(test_name or '').casefold() else 'Classic'


def serving_node(cell_id: Any) -> tuple[str, int] | None:
    """The eNB or gNB of the last cell of the call (where it failed), or the cell itself for 2G/3G cells."""
    numbers = _CELL_NUMBERS.findall(str(cell_id or ''))
    if not numbers:
        return None
    value = int(numbers[-1])
    if value > MAX_ECI:
        return 'gNB', value >> 12
    if value > 65535:
        return 'eNB', value >> 8
    return 'Cell', value


def _node_mappings(connection: Any, dataset: Any) -> dict[tuple[str, int], dict[str, str]]:
    """eNB and gNB of a cell mapping dataset with their site, host and vendor (cached per revision)."""
    key = (str(dataset['stored_path'] or ''), int(dataset['id']), str(dataset['updated_at'] or dataset['processed_at'] or ''))
    if key in _node_mapping_cache:
        return _node_mapping_cache[key]
    table = f"dataset_rows_{int(dataset['id'])}"
    columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info({_quote(table)})').fetchall()]
    resolved = {field: _resolve_columns(columns, candidates) for field, candidates in NODE_MAPPING_COLUMNS.items()}
    selected = list(dict.fromkeys(column for items in resolved.values() for column in items))
    nodes: dict[tuple[str, int], dict[str, str]] = {}
    if selected and (resolved['eci'] or resolved['enb'] or resolved['gnb']):
        for row in connection.execute(f"SELECT {', '.join(_quote(column) for column in selected)} FROM {_quote(table)}"):
            values = dict(zip(selected, row))

            def first(field: str) -> str:
                return next((text for column in resolved[field] if (text := _text(values.get(column)))), '')

            details = {'site': first('site'), 'host': first('host'), 'vendor': first('vendor')}
            for kind, field in (('eNB', 'enb'), ('gNB', 'gnb')):
                number = _number(first(field))
                if number is not None and number >= 0:
                    nodes.setdefault((kind, int(number)), details)
            eci = _number(first('eci'))
            if eci is not None and 65535 < eci <= MAX_ECI:
                nodes.setdefault(('eNB', int(eci) >> 8), details)
    if len(_node_mapping_cache) > 16:
        _node_mapping_cache.clear()
    _node_mapping_cache[key] = nodes
    return nodes


def root_cause_stats(task_repository: Any, filters: dict[str, Any], username: str,
                     include_suggestions: bool = True) -> dict[str, Any]:
    """Root Cause Analysis of the calls matching the filters.

    Calls are counted per root domain and cause, Classic/WhatsApp/Data call type, NR
    mode (NSA or SA), technology and the eNB/gNB of their last cell, with its site,
    host and vendor from the workspace cell mappings. Calls without a root cause
    count with their suggested one when ``include_suggestions`` is set.
    """
    options = list_options(task_repository)
    taxonomy = list_root_causes(task_repository)
    base, base_params = _base_sql(default_status(options), task_repository)
    where, params = _filter_sql(_resolve_key_filters(task_repository, filters), username,
                                [item['name'] for item in options['statuses'] if item['closed']])
    with task_repository.connection() as connection:
        calls = connection.execute(f'WITH calls AS ({base}) SELECT * FROM calls{where}', [*base_params, *params]).fetchall()
        notes = _comment_texts(connection, [str(call['call_key']) for call in calls if not call['root_domain']]) \
            if include_suggestions else {}
        mappings = {}
        for dataset in task_repository.list_datasets():
            kind = str(dataset['dataset_kind'] or '')
            if kind in MAPPING_OPERATORS and str(dataset['status'] or '') == 'ready':
                try:
                    mappings.setdefault(kind, {}).update(_node_mappings(connection, dataset))
                except Exception:  # noqa: BLE001 - an unreadable mapping only leaves its nodes without details.
                    continue
    colors = {domain['name']: domain['color'] for domain in taxonomy['domains']}
    order = [domain['name'] for domain in taxonomy['domains']]
    counts = {'labelled': 0, 'suggested': 0, 'unclassified': 0}
    domains: dict[str, int] = {}
    causes: dict[tuple[str, str], int] = {}
    matrices: dict[str, dict[str, dict[str, int]]] = {'call_type': {}, 'nr_mode': {}, 'technology': {}}
    nodes: dict[tuple[str, str, int], dict[str, Any]] = {}
    for call in calls:
        domain, cause = str(call['root_domain'] or ''), str(call['root_cause'] or '')
        if domain:
            counts['labelled'] += 1
        elif include_suggestions and (suggestion := suggest_root_cause(call, taxonomy, notes.get(str(call['call_key']), ''))):
            domain, cause = suggestion['domain'], suggestion['cause']
            counts['suggested'] += 1
        else:
            counts['unclassified'] += 1
        domain = domain or NOT_CLASSIFIED
        domains[domain] = domains.get(domain, 0) + 1
        causes[(domain, cause)] = causes.get((domain, cause), 0) + 1
        groups = {'call_type': call_type(str(call['service']), str(call['test_name'] or '')),
                  'nr_mode': str(call['nr_mode'] or '') or 'Unknown', 'technology': str(call['technology'] or '') or 'Unknown'}
        for name, group in groups.items():
            row = matrices[name].setdefault(group, {})
            row[domain] = row.get(domain, 0) + 1
        node = serving_node(call['cell_id'])
        if node is None:
            continue
        operator = str(call['operator'] or '')
        entry = nodes.setdefault((operator, *node), {
            'operator': operator, 'type': node[0], 'id': node[1], 'calls': 0, 'domains': {},
            'vendor': str(call['vendor'] or ''), 'site': '', 'host': '',
        })
        entry['calls'] += 1
        entry['domains'][domain] = entry['domains'].get(domain, 0) + 1
    for entry in nodes.values():
        kind = next((name for name, pattern in MAPPING_OPERATORS.items() if pattern.match(entry['operator'].strip())), None)
        details = mappings.get(kind, {}).get((entry['type'], entry['id'])) if kind else None
        if details:
            entry.update({key: value for key, value in details.items() if value})

    def domain_key(name: str) -> tuple[int, int, str]:
        return (order.index(name) if name in order else len(order), -domains.get(name, 0), name.casefold())

    columns = sorted(domains, key=domain_key)

    def matrix(name: str, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [{'name': group, 'counts': values, 'total': sum(values.values())} for group, values in matrices[name].items()]
        rows.sort(key=lambda row: (-row['total'], row['name'].casefold()))
        return rows[:limit] if limit else rows

    top_nodes = sorted(nodes.values(), key=lambda entry: (-entry['calls'], entry['operator'].casefold(), entry['id']))[:MAX_NODES]
    for entry in top_nodes:
        entry['top_domain'] = max(entry['domains'], key=lambda name: (entry['domains'][name], name)) if entry['domains'] else ''
        entry['node'] = f"{entry['type']} {entry['id']}"
    return {
        'include_suggestions': include_suggestions,
        'summary': {'total': len(calls), **counts},
        'domains': [{'value': name, 'count': domains[name], 'color': colors.get(name, '#b8c0c6')} for name in columns],
        'causes': [{'domain': domain, 'cause': cause or 'No cause', 'value': cause, 'count': count,
                    'color': colors.get(domain, '#b8c0c6')}
                   for (domain, cause), count in sorted(causes.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
                   if domain != NOT_CLASSIFIED],
        'columns': columns,
        'call_types': matrix('call_type'),
        'nr_modes': matrix('nr_mode'),
        'technologies': matrix('technology', MAX_RATS),
        'nodes': top_nodes,
    }


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
def _call_row(connection: Any, call_key: str, default: str, task_repository: Any) -> Any:
    base, params = _base_sql(default, task_repository)
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
        row = _call_row(connection, call_key, default_status(options), task_repository)
        if row is None:
            return None
        call = _call_payload(row)
        comments = [_comment_payload(item) for item in connection.execute(
            f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE call_key = ? ORDER BY id', (call_key,),
        ).fetchall()]
        history = [
            {'id': int(item['id']), 'field': str(item['field']), 'old_value': str(item['old_value']),
             'new_value': str(item['new_value']), 'changed_by': str(item['changed_by']), 'changed_at': str(item['changed_at'])}
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
    notes = '\n'.join(comment['body'] for comment in comments if not comment['deleted_at'])
    call['suggested_root_cause'] = suggest_root_cause(call, list_root_causes(task_repository), notes)
    return {'call': call, 'comments': comments, 'history': history, 'fields': fields}


def _record_history(connection: Any, call_key: str, field: str, old: str, new: str, username: str, when: str) -> None:
    connection.execute(
        f'INSERT INTO {NQ_CALL_HISTORY_TABLE} (uid, call_key, field, old_value, new_value, changed_by, changed_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (uuid.uuid4().hex, call_key, field, old, new, username, when),
    )


def _validate_changes(changes: dict[str, Any], options: dict[str, list[dict[str, Any]]], users: set[str],
                      taxonomy: dict[str, Any]) -> dict[str, str]:
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
    if 'root_domain' in changes or 'root_cause' in changes:
        domains = {item['name'].casefold(): item for item in taxonomy['domains']}
        value = str(changes.get('root_domain') or '').strip()
        domain = domains.get(value.casefold())
        if value and domain is None:
            raise ValueError('Choose one of the configured root cause domains.')
        cause = str(changes.get('root_cause') or '').strip()
        causes = {item['name'].casefold(): item['name'] for item in (domain or {}).get('causes', [])}
        if cause and cause.casefold() not in causes:
            raise ValueError('Choose one of the causes of the selected domain.')
        validated['root_domain'] = domain['name'] if domain else ''
        validated['root_cause'] = causes.get(cause.casefold(), '')
    if changes.get('apply_suggestion'):
        validated['apply_suggestion'] = '1'
    if not validated:
        raise ValueError('There is nothing to change.')
    return validated


class TrackingConflict(Exception):
    """Another user changed the call after it was loaded."""


def update_tracking(
    task_repository: Any, call_keys: list[str], changes: dict[str, Any], username: str, users: set[str],
    expected_version: int | None = None,
) -> list[str]:
    """Apply status, team, assignee or root cause changes; returns the calls that changed.

    A team with members only accepts them as assignees: assigning anybody else
    is refused, and moving a call to such a team clears an assignee who is not
    a member. ``apply_suggestion`` labels the calls without a root cause with the
    suggested one. When the root cause is required to close, a call cannot move
    to a closed status without one.
    """
    options = list_options(task_repository)
    taxonomy = list_root_causes(task_repository)
    validated = _validate_changes(changes, options, users, taxonomy)
    apply_suggestion = bool(validated.pop('apply_suggestion', None))
    closed = {item['name'].casefold() for item in options['statuses'] if item['closed']}
    members = team_members(options)
    default = default_status(options)
    when = now_iso()
    changed: list[str] = []
    with task_repository.connection() as connection:
        for call_key in dict.fromkeys(call_keys):
            row = _call_row(connection, call_key, default, task_repository)
            if row is None:
                raise LookupError('The call is no longer available. Refresh the list.')
            if expected_version is not None and int(row['version']) != int(expected_version):
                raise TrackingConflict(
                    f"{row['updated_by'] or 'Another user'} changed this call at {row['updated_at']}. Review it and try again."
                )
            current = {field: str(row[field]) for field in TRACKING_FIELDS}
            current.update(validated)
            if apply_suggestion and not current['root_domain']:
                suggestion = suggest_root_cause(row, taxonomy, _comment_texts(connection, [call_key]).get(call_key, ''))
                if suggestion:
                    current['root_domain'], current['root_cause'] = suggestion['domain'], suggestion['cause']
            allowed = members.get(current['team'].casefold())
            if allowed and current['assignee'] and current['assignee'].casefold() not in allowed:
                if 'assignee' in validated:
                    raise ValueError(f'{current["assignee"]} is not a member of the {current["team"]} team.')
                current['assignee'] = ''
            differences = {field: value for field, value in current.items() if str(row[field]) != value}
            if not differences:
                continue
            if (taxonomy['require_to_close'] and current['status'].casefold() in closed and not current['root_domain']
                    and ('status' in differences or 'root_domain' in differences)):
                raise ValueError(f'Set a root cause before closing a call as {current["status"]}.')
            connection.execute(
                f'INSERT INTO {NQ_CALL_TRACKING_TABLE} (call_key, status, team, assignee, root_domain, root_cause, version, '
                'updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?) ON CONFLICT(call_key) DO UPDATE SET '
                'status = excluded.status, team = excluded.team, assignee = excluded.assignee, '
                'root_domain = excluded.root_domain, root_cause = excluded.root_cause, version = version + 1, '
                'updated_by = excluded.updated_by, updated_at = excluded.updated_at',
                (call_key, current['status'], current['team'], current['assignee'], current['root_domain'],
                 current['root_cause'], username, when),
            )
            for field, value in differences.items():
                _record_history(connection, call_key, field, str(row[field]), value, username, when)
            changed.append(call_key)
    return changed


def delete_history(task_repository: Any, username: str, *, call_keys: list[str] | None = None,
                   entry_ids: list[int] | None = None) -> int:
    """Delete history entries: some entries by id, or every entry of some calls; returns how many were deleted.

    The follow-up values and the comments of the calls stay as they are.
    """
    keys = list(dict.fromkeys(str(key) for key in call_keys or [] if str(key)))
    ids = list(dict.fromkeys(int(entry) for entry in entry_ids or []))
    if not keys and not ids:
        raise ValueError('Choose the history to delete.')
    deleted = 0
    with task_repository.connection() as connection:
        for column, values in (('call_key', keys), ('id', ids)):
            for start in range(0, len(values), 500):
                chunk = values[start:start + 500]
                deleted += connection.execute(
                    f"DELETE FROM {NQ_CALL_HISTORY_TABLE} WHERE {column} IN ({', '.join('?' for _ in chunk)})", chunk,
                ).rowcount
    if deleted and hasattr(task_repository, 'try_add_log'):
        scope = f'{len(keys)} calls' if keys else f'{len(ids)} entries'
        task_repository.try_add_log(username, 'nq_call_history_delete', f'Non-Qualified Calls history deleted ({scope}, {deleted} entries).')
    return deleted


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
        if _call_row(connection, call_key, default_status(options), task_repository) is None:
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
    ('Assignee', 'assignee'), ('Root Domain', 'root_domain'), ('Root Cause', 'root_cause'),
    ('Suggested Root Domain', 'suggested_domain'), ('Suggested Root Cause', 'suggested_cause'), ('Comments', 'comment_count'), ('Last Comment', 'last_comment_text'),
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
    base, base_params = _base_sql(default_status(options), task_repository)
    where, params = _filter_sql(_resolve_key_filters(task_repository, filters), username, closed)
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
    taxonomy = list_root_causes(task_repository)
    notes: dict[str, list[str]] = {}
    for row in comments:
        if not row['deleted_at']:
            notes.setdefault(str(row['call_key']), []).append(str(row['body']))
    for call in calls:
        suggestion = None if call.get('root_domain') else suggest_root_cause(
            call, taxonomy, '\n'.join(notes.get(call['call_key'], [])))
        call['suggested_domain'] = suggestion['domain'] if suggestion else ''
        call['suggested_cause'] = suggestion['cause'] if suggestion else ''
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
    'status': 'Status', 'team': 'Team', 'assignee': 'Assignee', 'root_domain': 'Root Domain', 'root_cause': 'Root Cause',
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
            f'SELECT call_key, status, team, assignee, root_domain, root_cause, version, updated_by, updated_at '
            f'FROM {NQ_CALL_TRACKING_TABLE} ORDER BY call_key')]
        comments = [dict(row) for row in connection.execute(
            f'SELECT uid, call_key, body, created_by, created_at, edited_by, edited_at, deleted_by, deleted_at '
            f'FROM {NQ_CALL_COMMENTS_TABLE} ORDER BY id')]
        history = [dict(row) for row in connection.execute(
            f'SELECT uid, call_key, field, old_value, new_value, changed_by, changed_at FROM {NQ_CALL_HISTORY_TABLE} ORDER BY id')]
    document = {
        'format': TRACKING_FORMAT, 'version': TRACKING_FORMAT_VERSION, 'options': list_options(task_repository),
        'root_causes': list_root_causes(task_repository),
        'tracking': tracking, 'comments': comments, 'history': history,
    }
    return json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')


def import_tracking_document(task_repository: Any, payload: bytes | str) -> int:
    """Merge a tracking document; returns the number of calls whose follow-up was added or updated.

    Missing statuses, teams and root cause domains and causes are added, newer follow-up replaces older follow-up,
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
                connection.executemany(
                    f'INSERT OR IGNORE INTO {NQ_TEAM_MEMBERS_TABLE} (team, username) VALUES (?, ?)',
                    [(item['name'], member) for member in item.get('members') or []],
                )
        root_causes = document.get('root_causes') if isinstance(document.get('root_causes'), dict) else {}
        incoming_domains = [item for item in root_causes.get('domains') or [] if isinstance(item, dict) and item.get('name')]
        if incoming_domains:
            current = {domain['name'].casefold(): domain for domain in _current_root_causes(connection)}
            merged = list(current.values())
            for domain in _normalize_root_causes(incoming_domains):
                target = current.get(domain['name'].casefold())
                if target is None:
                    merged.append(domain)
                    continue
                names = {cause['name'].casefold() for cause in target['causes']}
                target['causes'].extend(cause for cause in domain['causes'] if cause['name'].casefold() not in names)
            _write_root_causes(connection, merged)
    if isinstance(root_causes.get('rule'), dict) and not task_repository.get_workspace_state(ROOT_CAUSE_RULE_STATE_KEY):
        try:
            task_repository.set_workspace_state(ROOT_CAUSE_RULE_STATE_KEY, json.dumps(normalize_root_cause_rule(root_causes['rule'])))
        except ValueError:
            pass
    if root_causes.get('require_to_close') and not task_repository.get_workspace_state(ROOT_CAUSE_SETTINGS_STATE_KEY):
        task_repository.set_workspace_state(ROOT_CAUSE_SETTINGS_STATE_KEY, json.dumps({'require_to_close': True}))
    with task_repository.connection() as connection:
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
                f'INSERT OR REPLACE INTO {NQ_CALL_TRACKING_TABLE} (call_key, status, team, assignee, root_domain, root_cause, '
                'version, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (call_key, _text(item.get('status')), _text(item.get('team')), _text(item.get('assignee')),
                 _text(item.get('root_domain')), _text(item.get('root_cause')),
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

    class HistoryPayload(BaseModel):
        call_keys: list[str] = Field(default_factory=list)

    class OptionsPayload(BaseModel):
        statuses: list[dict[str, Any]] = Field(default_factory=list)
        teams: list[dict[str, Any]] = Field(default_factory=list)

    class RootCausesPayload(BaseModel):
        domains: list[dict[str, Any]] = Field(default_factory=list)
        require_to_close: bool = False

    class RootCauseRulePayload(BaseModel):
        rule: dict[str, Any] | None = None

    class RootCauseStatsPayload(BaseModel):
        filters: dict[str, Any] = Field(default_factory=dict)
        include_suggestions: bool = True

    class ProgressPayload(BaseModel):
        filters: dict[str, Any] = Field(default_factory=dict)
        granularity: str = 'month'
        include_suggestions: bool = True

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

    def can_configure_rule(user) -> bool:
        """Everybody sees the suggestion rule; admins and super-admins change it."""
        return user.role in {'admin', 'super-admin'}

    def rule_user(user=Depends(core.current_user)):
        if not can_configure_rule(user):
            raise HTTPException(403, 'Only admins and super-admins can change the root cause suggestion rule.')
        return user

    def moderator_user(user=Depends(core.current_user)):
        if not can_moderate(user):
            raise HTTPException(403, 'Only admins and super-admins can delete the history of Non-Qualified Calls.')
        return user

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

    # -- Reporting Jobs artifact ---------------------------------------------
    report_filters = (
        ('datasets', 'CDRs'), ('service', 'Service'), ('campaign', 'Campaign'), ('operator', 'Operator'),
        ('operator_vendor', 'Operator_Vendor'), ('vendor_operator', 'Vendor_Operator'), ('vendor', 'Vendor'),
        ('region', 'Region'), ('cluster', 'Cluster'), ('city', 'City'), ('result', 'Result'), ('failure_classification', 'Failure Classification'),
        ('status', 'Status'), ('team', 'Team'), ('assignee', 'Assignee'), ('root_domain', 'Root Domain'),
        ('root_cause', 'Root Cause'),
    )
    report_settings = (
        {'key': 'granularity', 'label': 'Progress periods', 'default': 'month',
         'choices': [['week', 'Week'], ['month', 'Month'], ['quarter', 'Quarter'], ['year', 'Year']]},
        {'key': 'open_only', 'label': 'Calls', 'default': '',
         'choices': [['', 'Every call'], ['1', 'Open calls only']]},
        {'key': 'include_suggestions', 'label': 'Root Cause Analysis', 'default': '1',
         'choices': [['1', 'Count suggested root causes'], ['', 'Labelled root causes only']]},
    )

    def report_values(user) -> dict[str, list[Any]]:
        repository = workspace_repository(user)
        values = filter_options(repository)
        options = list_options(repository)
        values['datasets'] = [[str(item['id']), item['name']] for item in indexed_datasets(repository)]
        values['status'] = [item['name'] for item in options['statuses']]
        values['team'] = [[UNASSIGNED, 'Unassigned'], *[item['name'] for item in options['teams']]]
        values['assignee'] = [[UNASSIGNED, 'Unassigned'], *workspace_users()]
        taxonomy = list_root_causes(repository)
        values['root_domain'] = [[UNASSIGNED, NOT_CLASSIFIED], *[domain['name'] for domain in taxonomy['domains']]]
        values['root_cause'] = list(dict.fromkeys(cause['name'] for domain in taxonomy['domains'] for cause in domain['causes']))
        return values

    def summary_parts(repository, filters: dict[str, Any], username: str, granularity: str, include_suggestions: bool = True):
        """The executive summary, progress status, options and selection lines of one NQ selection.

        The options carry the Root Cause Analysis of the selection under ``root_causes``.
        """
        from src.modules.non_qualified_calls_export import selection_lines

        executive = query_calls(repository, {'filters': filters, 'page_size': 25}, username)
        progress = progress_stats(repository, filters, username, granularity)
        options = {**list_options(repository),
                   'root_causes': root_cause_stats(repository, filters, username, include_suggestions)}
        names = {str(item['id']): item['name'] for item in indexed_datasets(repository)}
        return executive, progress, options, selection_lines(filters, names, granularity)

    def write_summary_document(export_format: str, destination: Path, executive, progress, options, lines) -> None:
        from src.modules.non_qualified_calls_export import export_powerpoint, export_word

        if export_format == 'powerpoint':
            export_powerpoint(destination, lines, executive['summary'], executive['breakdowns'], progress, options)
        else:
            export_word(destination, lines, executive['summary'], executive['breakdowns'], progress, options)

    def generate_report(config, folder, stamp, user) -> list[dict[str, Any]]:
        from src.modules.report_tasks import artifact_path

        repository = workspace_repository(user)
        sync_nq_calls(repository)
        settings = config.get('options') if isinstance(config.get('options'), dict) else {}
        filters = {key: [str(value) for value in values] for key, values in (settings.get('filters') or {}).items()
                   if isinstance(values, list) and values}
        if str(settings.get('open_only') or '') == '1':
            filters['open_only'] = True
        granularity = str(settings.get('granularity') or 'month')
        include_suggestions = str(settings.get('include_suggestions', '1') or '') == '1'
        executive, progress, options, lines = summary_parts(repository, filters, user.username, granularity,
                                                            include_suggestions)
        summary = executive['summary']
        details = [*lines[:-1], f"{summary['total']:,} Non-Qualified Calls · {summary['open']:,} open · {summary['closed']:,} closed · "
                   f"{progress['summary']['attended']:,} attended"]
        artifacts = []
        for export_format in config.get('formats') or ['powerpoint']:
            suffix = {'powerpoint': '.pptx', 'word': '.docx', 'excel': '.xlsx'}[export_format]
            label = {'powerpoint': 'PPT', 'word': 'Word', 'excel': 'Excel'}[export_format]
            destination = artifact_path(folder, stamp, 'Non-Qualified Calls', 'Executive Summary and Progress Status', suffix)
            if export_format in {'powerpoint', 'word'}:
                write_summary_document(export_format, destination, executive, progress, options, lines)
            else:
                destination.write_bytes(export_workbook(repository, filters, user.username))
            artifacts.append({'module': 'non_qualified_calls', 'title': f'Non-Qualified Calls ({label})',
                              'file_name': destination.name, 'size': destination.stat().st_size,
                              'status': 'ready', 'details': details})
        return artifacts

    from src.modules.report_tasks import register_report_artifact_provider

    register_report_artifact_provider(
        'non_qualified_calls', 'Non-Qualified Calls', 'non-qualified-calls', generate_report,
        formats=('powerpoint', 'word', 'excel'), filters=report_filters, settings=report_settings, values=report_values,
    )

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
            'user': {'username': user.username, 'can_edit': can_edit(user), 'can_moderate': can_moderate(user),
                     'can_configure_rule': can_configure_rule(user)},
            'unassigned': UNASSIGNED, 'page_sizes': list(PAGE_SIZES),
            'main_cities': list(repository.list_main_cities()),
            'saved_filters': saved_filters(repository),
            'root_causes': list_root_causes(repository), 'root_cause_defaults': default_root_causes(),
            'root_cause_rule_fields': RULE_FIELDS, 'default_root_cause_rule': DEFAULT_ROOT_CAUSE_RULE,
        })

    @core.app.put('/api/non-qualified-calls/filters')
    def nq_save_filters(payload: QueryPayload, user=Depends(core.current_user)) -> JSONResponse:
        return JSONResponse({'filters': save_filters(workspace_repository(user), payload.filters)})

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

    @core.app.delete('/api/non-qualified-calls/history/{entry_id}')
    def nq_delete_history_entry(entry_id: int, user=Depends(moderator_user)) -> JSONResponse:
        deleted = translate(lambda: delete_history(workspace_repository(user), user.username, entry_ids=[entry_id]))
        if not deleted:
            raise HTTPException(404, 'The history entry no longer exists.')
        return JSONResponse({'deleted': deleted})

    @core.app.post('/api/non-qualified-calls/history/clear')
    def nq_clear_history(payload: HistoryPayload, user=Depends(moderator_user)) -> JSONResponse:
        if len(payload.call_keys) > 5000:
            raise HTTPException(400, 'Clear the history of at most 5000 calls at once.')
        deleted = translate(lambda: delete_history(workspace_repository(user), user.username, call_keys=payload.call_keys))
        return JSONResponse({'deleted': deleted})

    @core.app.put('/api/non-qualified-calls/options')
    def nq_save_options(payload: OptionsPayload, user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        options = translate(lambda: save_options(repository, payload.statuses, payload.teams, user.username, set(workspace_users())))
        return JSONResponse({'options': options})

    @core.app.get('/api/non-qualified-calls/root-causes')
    def nq_root_causes(user=Depends(core.current_user)) -> JSONResponse:
        return JSONResponse(list_root_causes(workspace_repository(user)))

    @core.app.put('/api/non-qualified-calls/root-causes')
    def nq_save_root_causes(payload: RootCausesPayload, user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        return JSONResponse(translate(lambda: save_root_causes(repository, payload.domains, payload.require_to_close,
                                                                user.username)))

    @core.app.put('/api/non-qualified-calls/root-causes/rule')
    def nq_save_root_cause_rule(payload: RootCauseRulePayload, user=Depends(rule_user)) -> JSONResponse:
        """The suggestion rule of the workspace (admins and super-admins); no rule restores the default one."""
        repository = workspace_repository(user)
        return JSONResponse({'rule': translate(lambda: save_root_cause_rule(repository, payload.rule, user.username))})

    @core.app.post('/api/non-qualified-calls/root-causes/stats')
    def nq_root_cause_stats(payload: RootCauseStatsPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        sync_nq_calls(repository)
        return JSONResponse(root_cause_stats(repository, payload.filters, user.username, payload.include_suggestions))

    @core.app.post('/api/non-qualified-calls/progress')
    def nq_progress(payload: ProgressPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        sync_nq_calls(repository)
        return JSONResponse(progress_stats(repository, payload.filters, user.username, payload.granularity))

    @core.app.post('/api/non-qualified-calls/export/{export_format}')
    def nq_export_document(export_format: str, payload: ProgressPayload, user=Depends(core.current_user)) -> Response:
        """The Executive Summary, Progress Status and Root Cause Analysis of the filtered calls, in PowerPoint or Word."""
        if export_format not in {'powerpoint', 'word'}:
            raise HTTPException(404, 'Unsupported export type.')
        repository = workspace_repository(user)
        sync_nq_calls(repository)
        executive, progress, options, lines = summary_parts(repository, payload.filters, user.username, payload.granularity,
                                                            payload.include_suggestions)
        suffix = '.pptx' if export_format == 'powerpoint' else '.docx'
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name = re.sub(r'[^A-Za-z0-9._ -]+', '_', f'{stamp} - Non-Qualified Calls - {core.active_workspace.name}{suffix}')
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / f'summary{suffix}'
            write_summary_document(export_format, destination, executive, progress, options, lines)
            content = destination.read_bytes()
        media_type = ('application/vnd.openxmlformats-officedocument.presentationml.presentation' if export_format == 'powerpoint'
                      else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        return Response(content, media_type=media_type, headers={'Content-Disposition': f'attachment; filename="{name}"'})

    @core.app.post('/api/non-qualified-calls/export')
    def nq_export(payload: ExportPayload, user=Depends(core.current_user)) -> Response:
        repository = workspace_repository(user)
        sync_nq_calls(repository)
        content = export_workbook(repository, payload.filters, user.username)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', f'{core.active_workspace.name}_non-qualified-calls_{stamp}.xlsx')
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})
