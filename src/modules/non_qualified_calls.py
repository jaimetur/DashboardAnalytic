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

Follow-up is keyed by a stable ``call_key`` derived from the call itself: its
NetCheck ``JOIN_ID`` when the CDR has one, otherwise its service, Operator,
Campaign and test/session identifier. Statuses, comments and analysis fields
therefore survive reprocessing, uploading the same CDR again, and the move from
the Daily CDRs of a campaign to its Final CDR. A call can be in several CDRs:
the list shows it once, with the data of the most recent CDR (a Final CDR before
the Daily ones, then the newest data) and tells when a newer CDR changed it.
Speech calls are listed once per call; each of their samples keeps its own
follow-up (``sample_key``).

Every call of every CDR, qualified or not, is counted in ``nq_call_population``
so the share of Non-Qualified Calls of each campaign and operator can be shown.

Its Executive Summary and Progress Status report is a Reporting artifact
(PowerPoint, Word or Excel) registered with ``register_report_artifact_provider``.
"""

import hashlib
import json
import math
import re
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from io import BytesIO
from threading import Lock
from typing import Any, Callable

from src.modules.cdr_stage import CDR_STAGE_LABELS, dataset_cdr_stage
from src.modules.column_names import campaign_sort_key, column_identity
from src.modules.value_maps import ValueMapper, field_kind
from src.modules.mapping_order import dimension_order_key, mapping_group
from src.modules import nq_catalog
from src.modules.nq_catalog import (
    ATTENDED_FIELD, FIELD_TYPES, MAX_LONG_TEXT, YES_NO, evaluate_status, keyword_found, keywords as _keywords,
    normalized_text as _normalized_text,
)
from src.modules import nq_rca

NQ_CALLS_TABLE = 'nq_calls'
NQ_CALL_SOURCES_TABLE = 'nq_call_sources'
NQ_CALL_TRACKING_TABLE = 'nq_call_tracking'
NQ_CALL_COMMENTS_TABLE = 'nq_call_comments'
NQ_CALL_HISTORY_TABLE = 'nq_call_history'
NQ_CALL_OPTIONS_TABLE = 'nq_call_options'
NQ_TEAM_MEMBERS_TABLE = 'nq_team_members'
NQ_ROOT_CATALOG_TABLE = 'nq_root_catalog'
NQ_RCA_RESULTS_TABLE = 'nq_rca_results'
NQ_CALL_POPULATION_TABLE = 'nq_call_population'
NQ_CALL_VERSIONS_TABLE = 'nq_call_versions'
NQ_CALL_LATEST_TABLE = 'nq_call_latest'
NQ_FIELDS_TABLE = 'nq_analysis_fields'
NQ_FIELD_VALUES_TABLE = 'nq_analysis_field_values'
# Database Management titles of the module tables.
NQ_TABLE_TITLES = {
    NQ_CALLS_TABLE: 'NQ Calls',
    NQ_CALL_SOURCES_TABLE: 'NQ Call Sources',
    NQ_CALL_TRACKING_TABLE: 'NQ Call Tracking',
    NQ_CALL_COMMENTS_TABLE: 'NQ Call Comments',
    NQ_CALL_HISTORY_TABLE: 'NQ Call History',
    NQ_CALL_OPTIONS_TABLE: 'NQ Call Options',
    NQ_TEAM_MEMBERS_TABLE: 'NQ Team Members',
    NQ_ROOT_CATALOG_TABLE: 'NQ Root Catalog',
    NQ_RCA_RESULTS_TABLE: 'NQ RCA Results',
    NQ_CALL_POPULATION_TABLE: 'NQ Call Population',
    NQ_CALL_VERSIONS_TABLE: 'NQ Call Versions',
    NQ_CALL_LATEST_TABLE: 'NQ Call Latest',
    NQ_FIELDS_TABLE: 'NQ Analysis Fields',
    NQ_FIELD_VALUES_TABLE: 'NQ Analysis Field Values',
}
SERVICES = ('voice', 'speech', 'data')
SERVICE_LABELS = {'voice': 'Voice', 'speech': 'Speech', 'data': 'Data'}
QUALIFIED_RESULT = 'completed'
# Bump when the indexed fields or the call key change so every CDR is indexed again.
INDEX_VERSION = 4
# The call key of version 3: the JOIN_ID first, and Speech calls (not samples).
KEY_SCHEME = '3'
KEY_SCHEME_STATE_KEY = 'nq_calls_key_scheme'
TRACKING_FORMAT = 'nq-call-tracking'
TRACKING_FORMAT_VERSION = 3
CONFIGURATION_FORMAT = 'nq-calls-configuration'
CONFIGURATION_FORMAT_VERSION = 1
UNASSIGNED = '__unassigned__'
MAX_COMMENT_LENGTH = 5000
PAGE_SIZES = (25, 50, 100, 200)
OPTION_KINDS = ('status', 'team')
COLOR_PATTERN = re.compile(r'#[0-9a-fA-F]{6}')
DEFAULT_STATUSES = nq_catalog.DEFAULT_STATUSES
DEFAULT_TEAMS = nq_catalog.DEFAULT_TEAMS
# The statuses and teams of the first version: replaced by the Analysis Center ones while unchanged.
_FIRST_STATUSES = ('Open', 'Under Investigation', 'Pending Information', 'Resolved', 'Not Applicable')
_FIRST_STATUS_MOVES = {'under investigation': 'Under Analysis', 'pending information': 'Open', 'resolved': 'Closed',
                       'not applicable': 'Closed'}
_FIRST_TEAMS = ('RAN Optimisation', 'Core Network', 'IMS / VoLTE', 'Transport', 'Device & Test Setup')
ROOT_CAUSE_SETTINGS_STATE_KEY = 'nq_calls_root_cause_settings'
ROOT_CAUSE_RULE_STATE_KEY = 'nq_calls_root_cause_rule'
SECTIONS_STATE_KEY = 'nq_calls_sections'
STATUS_RULES_STATE_KEY = 'nq_calls_status_rules'
# Set once the Analysis Center catalog, statuses, teams and rules have been added to the workspace.
ANALYSIS_CENTER_STATE_KEY = 'nq_analysis_center_v1'
# The second layout of the Analysis Center (section colours and the order of the Analysis fields), applied once.
ANALYSIS_CENTER_V2_STATE_KEY = 'nq_analysis_center_v2'
# Set once the tables and columns of this version exist, so the requests check the schema without writing.
SCHEMA_STATE_KEY = 'nq_calls_schema'
SCHEMA_VERSION = '2026-10-10.2'
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
    'session_type': ('Session_Type',),
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
# The values a catalog field can read from the call: the indexed fields and the last cell of the Cell ID chain.
CATALOG_CALL_FIELDS = (*CALL_FIELDS, 'last_cell_id')


def last_cell_sql(column: str) -> str:
    """The last element of a Cell ID chain ("[a]->[b]->[c]" gives "c"): the cell where the call ended."""
    return f"trim(substr({column}, length(rtrim({column}, replace({column}, '>', ''))) + 1), '[] ')"
NUMERIC_FIELDS = frozenset({'latitude', 'longitude'})
# NetCheck's identifier of each voice call and data test, the same in the Daily and Final CDRs.
JOIN_SOURCES = ('JOIN_ID',)
# Without a JOIN_ID: the test of a Data CDR, the session (the call) of a Voice or Speech CDR.
IDENTIFIER_SOURCES = {
    'data': ('Test_ID', 'Session_id'),
    'voice': ('Session_ID_A', 'Session_id', 'Test_ID'),
    'speech': ('Session_ID_A', 'Session_id'),
}
# A Speech sample inside its call.
SAMPLE_SOURCES = ('Test_ID', 'Sample_ID', 'Sequence_ID_per_File_ID')
SUBSCRIBER_SOURCES = ('Subscriber',)
# Filters on indexed fields; the tracking filters are handled separately.
FIELD_FILTERS = (
    'service', 'campaign', 'operator', 'operator_vendor', 'vendor_operator', 'vendor', 'region', 'cluster', 'city',
    'technology', 'test_name', 'result', 'failure_classification', 'failure_category',
)
TRACKING_FILTERS = ('status', 'team', 'assignee', 'root_domain', 'root_category', 'root_cause', 'status_mode')
# Filters typed as a list of values rather than chosen among them (a JOIN_ID has too many values to list).
TYPED_FILTERS = ('join_id',)
TRACKING_FIELDS = ('status', 'team', 'assignee', 'root_domain', 'root_category', 'root_cause', 'status_mode')
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
    # RCA Identification: a root category or cause is selected.
    'identified': "(root_category <> '' OR root_cause <> '')", 'not_identified': "(root_category = '' AND root_cause = '')",
}
SORT_COLUMNS = {
    'service': 'service', 'start_time': 'start_time', 'operator': 'operator', 'operator_vendor': 'operator_vendor', 'vendor': 'vendor',
    'campaign': 'campaign', 'city': 'city', 'technology': 'technology', 'test_name': 'test_name',
    'result': 'result', 'failure': 'failure_classification', 'status': 'status', 'team': 'team',
    'assignee': 'assignee', 'root_cause': 'root_domain', 'root_category': 'root_category', 'cause': 'root_cause',
    'comments': 'comment_count',
    'updated_at': 'updated_at', 'join_id': 'join_id', 'region': 'region', 'cluster': 'cluster', 'nr_mode': 'nr_mode',
    'cell_id': 'cell_id', 'direction': 'direction', 'session_type': 'session_type', 'end_time': 'end_time', 'cdr': 'dataset_id',
    'version': 'version_state',
}
# The breakdowns of the Summary, in the order of the page and of the one-slide Executive Summary.
BREAKDOWNS = (
    ('service', 'By Service'), ('result', 'By Result'), ('status', 'By Status'), ('team', 'By Team'),
    ('root_domain', 'By Root Domain'), ('root_category', 'By Root Category'), ('root_cause', 'By Root Cause'),
    ('failure_classification', 'By Failure Classification'),
    ('campaign', 'By Campaign'), ('operator', 'By Operator'), ('vendor', 'By Vendor'), ('region', 'By Region'),
    ('cluster', 'By Cluster'), ('city', 'By City'),
)
SEARCH_FIELDS = (
    'operator', 'operator_vendor', 'vendor', 'campaign', 'region', 'cluster', 'city', 'technology', 'test_name', 'result',
    'failure_classification', 'failure_category', 'failure_subcategory', 'failure_comment', 'cell_id', 'join_id', 'session_type',
    'extra_json',
)
# How the CDRs see a call (see ``_base_sql``); "current" is the latest version with nothing to tell.
VERSION_STATES = ('current', 'changed', 'newer', 'not_in_final', 'qualified')
VERSION_LABELS = {
    'current': 'Latest version', 'changed': 'Changed between CDRs', 'newer': 'Newer version in another CDR',
    'not_in_final': 'Not in the Final CDR', 'qualified': 'Completed in a newer CDR',
}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {NQ_CALLS_TABLE} (
    dataset_id INTEGER NOT NULL,
    source_row_id INTEGER NOT NULL,
    call_key TEXT NOT NULL,
    service TEXT NOT NULL,
    nr_mode TEXT NOT NULL DEFAULT '',
    {', '.join(f"{field} REAL" if field in NUMERIC_FIELDS else f"{field} TEXT NOT NULL DEFAULT ''" for field in CALL_FIELDS)},
    join_id TEXT NOT NULL DEFAULT '',
    sample_key TEXT NOT NULL DEFAULT '',
    sample_id TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{{}}',
    PRIMARY KEY (dataset_id, source_row_id)
);
CREATE INDEX IF NOT EXISTS idx_{NQ_CALLS_TABLE}_call_key ON {NQ_CALLS_TABLE}(call_key);
CREATE TABLE IF NOT EXISTS {NQ_CALL_SOURCES_TABLE} (
    dataset_id INTEGER PRIMARY KEY,
    revision TEXT NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL,
    stage_rank INTEGER NOT NULL DEFAULT 1,
    data_date TEXT NOT NULL DEFAULT '',
    population_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS {NQ_CALL_POPULATION_TABLE} (
    dataset_id INTEGER NOT NULL,
    call_key TEXT NOT NULL,
    service TEXT NOT NULL,
    campaign TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    nr_mode TEXT NOT NULL DEFAULT '',
    is_nq INTEGER NOT NULL DEFAULT 0,
    is_latest INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dataset_id, call_key)
);
CREATE INDEX IF NOT EXISTS idx_{NQ_CALL_POPULATION_TABLE}_key ON {NQ_CALL_POPULATION_TABLE}(call_key);
CREATE INDEX IF NOT EXISTS idx_{NQ_CALL_POPULATION_TABLE}_latest ON {NQ_CALL_POPULATION_TABLE}(is_latest, service);
-- Covers the NQ rate of the latest version of every call, read from the index alone.
CREATE INDEX IF NOT EXISTS idx_{NQ_CALL_POPULATION_TABLE}_rates
    ON {NQ_CALL_POPULATION_TABLE}(is_latest, service, campaign, operator, nr_mode, is_nq);
CREATE TABLE IF NOT EXISTS {NQ_CALL_VERSIONS_TABLE} (
    call_key TEXT PRIMARY KEY,
    latest_dataset_id INTEGER NOT NULL,
    latest_is_nq INTEGER NOT NULL DEFAULT 1,
    in_final INTEGER NOT NULL DEFAULT 0,
    final_covered INTEGER NOT NULL DEFAULT 0,
    changed INTEGER NOT NULL DEFAULT 0,
    cdr_count INTEGER NOT NULL DEFAULT 1
);
-- The latest version of every call (the Final CDR first, then the newest data) with its Operator and Vendor
-- mapped: the part of the calls query that only changes when the CDRs are indexed or the maps change.
CREATE TABLE IF NOT EXISTS {NQ_CALL_LATEST_TABLE} (
    dataset_id INTEGER NOT NULL,
    source_row_id INTEGER NOT NULL,
    call_key TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    nr_mode TEXT NOT NULL DEFAULT '',
    {', '.join(f"{field} REAL" if field in NUMERIC_FIELDS else f"{field} TEXT NOT NULL DEFAULT ''" for field in CALL_FIELDS)},
    vendor_operator TEXT NOT NULL DEFAULT '',
    last_cell_id TEXT NOT NULL DEFAULT '',
    join_id TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{{}}',
    nq_samples INTEGER NOT NULL DEFAULT 1,
    latest_dataset_id INTEGER NOT NULL DEFAULT 0,
    cdr_count INTEGER NOT NULL DEFAULT 1,
    version_state TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS {NQ_FIELDS_TABLE} (
    field_key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '[]',
    position INTEGER NOT NULL DEFAULT 0,
    in_table INTEGER NOT NULL DEFAULT 0,
    in_summary INTEGER NOT NULL DEFAULT 0,
    required_to_close INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT 'analysis',
    source TEXT NOT NULL DEFAULT 'user',
    source_ref TEXT NOT NULL DEFAULT '',
    in_export INTEGER NOT NULL DEFAULT 1,
    suggest_from TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS {NQ_FIELD_VALUES_TABLE} (
    call_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (call_key, field_key)
);
CREATE INDEX IF NOT EXISTS idx_{NQ_FIELD_VALUES_TABLE}_field ON {NQ_FIELD_VALUES_TABLE}(field_key, value);
CREATE TABLE IF NOT EXISTS {NQ_CALL_TRACKING_TABLE} (
    call_key TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT '',
    team TEXT NOT NULL DEFAULT '',
    assignee TEXT NOT NULL DEFAULT '',
    root_domain TEXT NOT NULL DEFAULT '',
    root_cause TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 0,
    root_category TEXT NOT NULL DEFAULT '',
    status_mode TEXT NOT NULL DEFAULT 'auto',
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
CREATE TABLE IF NOT EXISTS {NQ_ROOT_CATALOG_TABLE} (
    kind TEXT NOT NULL CHECK(kind IN ('domain', 'category', 'cause')),
    name TEXT NOT NULL COLLATE NOCASE,
    domain TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '[]',
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, name)
);
CREATE TABLE IF NOT EXISTS {NQ_RCA_RESULTS_TABLE} (
    join_id TEXT PRIMARY KEY,
    original_join_id TEXT NOT NULL,
    values_json TEXT NOT NULL DEFAULT '{{}}',
    source_file TEXT NOT NULL DEFAULT '',
    imported_by TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT ''
);
"""

_sync_locks: dict[str, Lock] = {}
_sync_locks_guard = Lock()
# The NQ rate counts of each workspace and CDR scope, kept until the indexed CDRs change.
_rate_counts_cache: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
_rate_counts_guard = Lock()
RATE_COUNTS_CACHE_SIZE = 32


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


_LEGACY_ROOT_CAUSES_TABLE = 'nq_root_causes'


def _columns_of(connection: Any, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info({table})').fetchall()}


def _schema_ready(task_repository: Any) -> bool:
    """Whether every table of this version exists and the upgrades ran: read without taking the write lock."""
    with task_repository.connection() as connection:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not set(NQ_TABLE_TITLES) <= tables or 'workspace_state' not in tables:
            return False
        keys = (SCHEMA_STATE_KEY, ANALYSIS_CENTER_STATE_KEY, ANALYSIS_CENTER_V2_STATE_KEY)
        states = {str(row[0]): str(row[1]) for row in connection.execute(
            f"SELECT key, value FROM workspace_state WHERE key IN ({', '.join('?' for _ in keys)})", keys)}
    return states.get(SCHEMA_STATE_KEY) == SCHEMA_VERSION and bool(states.get(ANALYSIS_CENTER_STATE_KEY)) \
        and bool(states.get(ANALYSIS_CENTER_V2_STATE_KEY))


def ensure_nq_tables(task_repository: Any) -> None:
    """Create the module tables, add the columns of later versions and seed the defaults once.

    Every request calls it: once the schema of this version is in place it only reads, so the pages never wait
    for the workspace writer (the indexing or a CDR being processed).
    """
    if _schema_ready(task_repository):
        return
    with task_repository.connection() as connection:
        existed = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (NQ_CALL_OPTIONS_TABLE,),
        ).fetchone()
        catalog_existed = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (NQ_ROOT_CATALOG_TABLE,),
        ).fetchone()
        tracking = _columns_of(connection, NQ_CALL_TRACKING_TABLE)
        for column, definition in (('root_domain', "TEXT NOT NULL DEFAULT ''"), ('root_cause', "TEXT NOT NULL DEFAULT ''"),
                                   ('root_category', "TEXT NOT NULL DEFAULT ''"), ('status_mode', "TEXT NOT NULL DEFAULT 'auto'")):
            if tracking and column not in tracking:
                connection.execute(f'ALTER TABLE {NQ_CALL_TRACKING_TABLE} ADD COLUMN {column} {definition}')
        definitions = _columns_of(connection, NQ_FIELDS_TABLE)
        for column, definition in (('section', "TEXT NOT NULL DEFAULT 'analysis'"), ('source', "TEXT NOT NULL DEFAULT 'user'"),
                                   ('source_ref', "TEXT NOT NULL DEFAULT ''"), ('in_export', 'INTEGER NOT NULL DEFAULT 1'),
                                   ('suggest_from', "TEXT NOT NULL DEFAULT ''")):
            if definitions and column not in definitions:
                connection.execute(f'ALTER TABLE {NQ_FIELDS_TABLE} ADD COLUMN {column} {definition}')
        indexed = _columns_of(connection, NQ_CALLS_TABLE)
        if indexed and not set(CALL_FIELDS) <= indexed:
            # The index is rebuilt from the CDRs whenever its fields change.
            connection.execute(f'DROP TABLE {NQ_CALLS_TABLE}')
            connection.execute(f'DROP TABLE IF EXISTS {NQ_CALL_SOURCES_TABLE}')
            indexed = set()
        # Columns added later keep the indexed rows, so the follow-up can move to the new call keys.
        for column, definition in (('join_id', "TEXT NOT NULL DEFAULT ''"), ('sample_key', "TEXT NOT NULL DEFAULT ''"),
                                   ('sample_id', "TEXT NOT NULL DEFAULT ''"), ('extra_json', "TEXT NOT NULL DEFAULT '{}'")):
            if indexed and column not in indexed:
                connection.execute(f'ALTER TABLE {NQ_CALLS_TABLE} ADD COLUMN {column} {definition}')
        sources = _columns_of(connection, NQ_CALL_SOURCES_TABLE)
        for column, definition in (('stage_rank', 'INTEGER NOT NULL DEFAULT 1'), ('data_date', "TEXT NOT NULL DEFAULT ''"),
                                   ('population_count', 'INTEGER NOT NULL DEFAULT 0')):
            if sources and column not in sources:
                connection.execute(f'ALTER TABLE {NQ_CALL_SOURCES_TABLE} ADD COLUMN {column} {definition}')
        latest = _columns_of(connection, NQ_CALL_LATEST_TABLE)
        if latest and set(LATEST_COLUMNS) - latest:
            connection.execute(f'DROP TABLE {NQ_CALL_LATEST_TABLE}')
            connection.execute('DELETE FROM workspace_state WHERE key = ?', (LATEST_STATE_KEY,))
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
        if not catalog_existed:
            _write_root_catalog(connection, _initial_root_catalog(connection))
    if not task_repository.get_workspace_state(ANALYSIS_CENTER_STATE_KEY):
        _install_analysis_center(task_repository, fresh=not existed)
    if not task_repository.get_workspace_state(ANALYSIS_CENTER_V2_STATE_KEY):
        _upgrade_analysis_center_v2(task_repository)
    task_repository.set_workspace_state(SCHEMA_STATE_KEY, SCHEMA_VERSION)


def _initial_root_catalog(connection: Any) -> dict[str, list[dict[str, Any]]]:
    """The default root cause catalog, merged with the domains and causes of the first version's taxonomy."""
    catalog = nq_catalog.default_root_catalog()
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                              (_LEGACY_ROOT_CAUSES_TABLE,)).fetchone():
        return catalog
    rows = connection.execute(
        f'SELECT domain, cause, color, keywords FROM {_LEGACY_ROOT_CAUSES_TABLE} ORDER BY position, cause COLLATE NOCASE').fetchall()
    domains = {item['name'].casefold(): item for item in catalog['domains']}
    causes = {item['name'].casefold(): item for item in catalog['causes']}
    for row in rows:
        name, cause = str(row['domain']), str(row['cause'] or '')
        words = _keywords(json.loads(row['keywords'] or '[]'))
        if not cause:
            # The workspace's own domains keep their colour and keywords.
            target = domains.get(name.casefold())
            if target is None:
                target = {'name': name, 'color': str(row['color'] or '#7b8790'), 'keywords': words}
                catalog['domains'].append(target)
                domains[name.casefold()] = target
            else:
                target.update(color=str(row['color'] or target['color']), keywords=words)
        elif cause.casefold() in causes:
            causes[cause.casefold()].update(domain=name, keywords=words)
        else:
            item = {'name': cause, 'domain': name, 'keywords': words}
            catalog['causes'].append(item)
            causes[cause.casefold()] = item
    connection.execute(f'DROP TABLE {_LEGACY_ROOT_CAUSES_TABLE}')
    return catalog


def _install_analysis_center(task_repository: Any, fresh: bool) -> None:
    """Add the Analysis Center to a workspace once: its fields, statuses, teams and status rules.

    Fields with the name of a default field keep their key and values and take its section and
    place. The statuses and teams of the first version are replaced (and their calls moved to the
    new statuses) while nobody changed them; otherwise the missing defaults are added.
    """
    current = list_fields(task_repository)
    by_label = {field['label'].casefold(): field for field in current}
    by_key = {field['key']: field for field in current}
    merged: list[dict[str, Any]] = []
    used: set[str] = set()
    for default in nq_catalog.default_fields():
        existing = by_key.get(default['key']) or by_label.get(default['label'].casefold())
        if existing is not None and existing['source'] == 'user' and default['source'] == 'user' and existing['type'] == default['type']:
            merged.append({**default, 'key': existing['key'], 'options': existing['options'] or default['options'],
                           'in_table': existing['in_table'] or default['in_table'],
                           'in_summary': existing['in_summary'] or default['in_summary'],
                           'required_to_close': existing['required_to_close']})
            used.add(existing['key'])
        elif default['key'] in by_key:
            merged.append(by_key[default['key']])
            used.add(default['key'])
        else:
            merged.append(default)
    merged += [field for field in current if field['key'] not in used]
    _store_fields(task_repository, nq_catalog.normalize_fields(merged, by_key, CATALOG_CALL_FIELDS))
    options = list_options(task_repository)
    names = [item['name'] for item in options['statuses']]
    with task_repository.connection() as connection:
        if fresh or [name.casefold() for name in names] == [name.casefold() for name in _FIRST_STATUSES]:
            for old, new in _FIRST_STATUS_MOVES.items():
                connection.execute(f'UPDATE {NQ_CALL_TRACKING_TABLE} SET status = ? WHERE status = ? COLLATE NOCASE', (new, old))
            connection.execute(f"DELETE FROM {NQ_CALL_OPTIONS_TABLE} WHERE kind = 'status'")
            connection.executemany(
                f"INSERT INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES ('status', ?, ?, ?, ?)",
                [(name, color, index, int(closed)) for index, (name, color, closed) in enumerate(DEFAULT_STATUSES)])
        else:
            known = {name.casefold() for name in names}
            missing = [entry for entry in DEFAULT_STATUSES if entry[0].casefold() not in known]
            if missing and missing[0][0] == DEFAULT_STATUSES[0][0]:
                connection.execute(f"UPDATE {NQ_CALL_OPTIONS_TABLE} SET position = position + 1 WHERE kind = 'status'")
                connection.execute(f"INSERT INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES ('status', ?, ?, 0, ?)",
                                   (missing[0][0], missing[0][1], int(missing[0][2])))
                missing = missing[1:]
            position = len(names) + 1
            for name, color, closed in missing:
                connection.execute(f"INSERT INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES ('status', ?, ?, ?, ?)",
                                   (name, color, position, int(closed)))
                position += 1
        teams = [item['name'] for item in options['teams']]
        teams_used = connection.execute(f"SELECT COUNT(*) FROM {NQ_CALL_TRACKING_TABLE} WHERE team <> ''").fetchone()[0]
        if fresh or ([name.casefold() for name in teams] == [name.casefold() for name in _FIRST_TEAMS] and not teams_used):
            connection.execute(f"DELETE FROM {NQ_CALL_OPTIONS_TABLE} WHERE kind = 'team'")
            connection.execute(f'DELETE FROM {NQ_TEAM_MEMBERS_TABLE}')
            connection.executemany(
                f"INSERT INTO {NQ_CALL_OPTIONS_TABLE} (kind, name, color, position, is_closed) VALUES ('team', ?, ?, ?, 0)",
                [(name, color, index) for index, (name, color) in enumerate(DEFAULT_TEAMS)])
        # The follow-up of the first version was chosen by hand: it stays as it is, except the first status.
        connection.execute(f"UPDATE {NQ_CALL_TRACKING_TABLE} SET status_mode = CASE WHEN status IN ('', ?, 'Open') "
                           "THEN 'auto' ELSE 'manual' END", (DEFAULT_STATUSES[0][0],))
    statuses = [item['name'] for item in list_options(task_repository)['statuses']]
    fields = list_fields(task_repository)
    rules = []
    known = nq_catalog.condition_fields(fields)
    for rule in nq_catalog.default_status_rules():
        conditions = [condition for condition in rule['conditions'] if condition['field'] in known]
        if rule['status'] in statuses and conditions:
            rules.append({**rule, 'conditions': conditions})
    task_repository.set_workspace_state(STATUS_RULES_STATE_KEY, json.dumps(rules, ensure_ascii=False))
    task_repository.set_workspace_state(ANALYSIS_CENTER_STATE_KEY, '1')
    recompute_statuses(task_repository, 'system')


def _upgrade_analysis_center_v2(task_repository: Any) -> None:
    """The second layout once, for what the workspace kept of the first one: Failure Details (formerly Failure Event)
    in red and Implementation and Planning in green, the Last Cell ID and Failure Comment of the CDR in Failure
    Details (Serving Cell when Failure proposing the last cell), and the Analysis fields in the order of the call panel."""
    try:
        sections = json.loads(task_repository.get_workspace_state(SECTIONS_STATE_KEY) or '[]')
    except (TypeError, ValueError):
        sections = []
    defaults = {section['key']: section for section in nq_catalog.default_sections()}
    changed = False
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict) or section.get('key') not in defaults:
            continue
        key = section['key']
        first_color = nq_catalog.FIRST_SECTION_COLORS.get(key)
        if first_color and str(section.get('color') or '').casefold() == first_color.casefold():
            section['color'] = defaults[key]['color']
            changed = True
        if nq_catalog.FIRST_SECTION_LABELS.get(key) == str(section.get('label') or ''):
            section['label'] = defaults[key]['label']
            changed = True
    if changed:
        task_repository.set_workspace_state(SECTIONS_STATE_KEY, json.dumps(nq_catalog.normalize_sections(sections)))
    fields = list_fields(task_repository)
    keys = [field['key'] for field in fields]
    first = list(nq_catalog.FIRST_ANALYSIS_ORDER)
    if [key for key in keys if key in first] == first:
        order = [field['key'] for field in nq_catalog.default_fields() if field['key'] in first]
        by_key = {field['key']: field for field in fields}
        for position, key in zip(sorted(keys.index(key) for key in first), order):
            fields[position] = by_key[key]
    # The new fields of the CDR, each after the field it follows by default (or at the end of its section).
    default_fields = nq_catalog.default_fields()
    labels = {field['label'].casefold() for field in fields}
    for index, default in enumerate(default_fields):
        if default['key'] not in {'last_cell_id', 'failure_comment'} or default['key'] in {field['key'] for field in fields} \
                or default['label'].casefold() in labels:
            continue
        previous = [field['key'] for field in default_fields[:index]]
        place = max((position for position, field in enumerate(fields) if field['key'] in previous
                     and field['section'] == default['section']), default=None)
        if place is None:
            place = max((position for position, field in enumerate(fields) if field['section'] == default['section']), default=len(fields) - 1)
        fields.insert(place + 1, default)
    for field in fields:
        if field['key'] == 'serving_cell_when_failure' and field.get('suggest_from') == 'cell_id':
            field['suggest_from'] = 'last_cell_id'
    _store_fields(task_repository, nq_catalog.normalize_fields(fields, {field['key']: field for field in list_fields(task_repository)},
                                                               CATALOG_CALL_FIELDS))
    task_repository.set_workspace_state(ANALYSIS_CENTER_V2_STATE_KEY, '1')


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


def call_key_for(service: str, values: dict[str, Any], identifier: str = '', subscriber: str = '', join_id: str = '') -> str:
    """A stable identity for a call: the same call keeps it across uploads, reprocessing and CDRs.

    The NetCheck JOIN_ID identifies each voice call and data test in the Daily and the Final
    CDRs alike; without it, the call is its service, Operator, Campaign and test or session
    identifier (or its subscriber, test name and start and end times).
    """
    if join_id:
        parts: tuple[str, ...] = (service, 'join', join_id.casefold())
    else:
        base = (service, _text(values.get('operator')).casefold(), _text(values.get('campaign')).casefold())
        if identifier:
            parts = (*base, 'id', identifier)
        else:
            parts = (*base, subscriber.casefold(), _text(values.get('test_name')).casefold(),
                     _text(values.get('start_time')), _text(values.get('end_time')))
    return hashlib.sha1('\x1f'.join(parts).encode('utf-8')).hexdigest()[:24]


def sample_key_for(call_key: str, sample: str) -> str:
    """The identity of one Speech sample inside its call."""
    return hashlib.sha1('\x1f'.join((call_key, 'sample', sample)).encode('utf-8')).hexdigest()[:24]


TABLE_COLUMNS_STATE_KEY = 'nq_calls_table_columns'
# Optional columns of the Calls table, with their labels.
OPTIONAL_COLUMNS = {
    'join_id': 'JOIN_ID', 'nr_mode': 'NR Mode', 'cell_id': 'Cell ID',
    'direction': 'Direction', 'session_type': 'Session Type (CDR)', 'end_time': 'End Time', 'cdr': 'CDR',
}
MAX_CDR_COLUMNS = 12
# CDR columns exported to Excel besides those of the table.
MAX_EXPORT_CDR_COLUMNS = 100
# The optional columns filtered by their own values; CDR uses the CDRs filter.
COLUMN_FILTER_SQL = {
    'join_id': 'join_id', 'nr_mode': 'nr_mode', 'cell_id': 'cell_id', 'direction': 'direction', 'session_type': 'session_type',
    'end_time': 'end_time',
}
MAX_COLUMN_FILTER_VALUES = 5000


def column_filter_sql(key: str) -> str | None:
    """The SQL value of a filterable table column: an optional column, or a CDR column (``cdr:<name>``)."""
    if key in COLUMN_FILTER_SQL:
        return f"COALESCE(CAST({COLUMN_FILTER_SQL[key]} AS TEXT), '')"
    if key.startswith('cdr:') and key[4:].strip():
        name = key[4:].replace('"', '').replace("'", '')
        return f"COALESCE(CAST(json_extract(extra_json, '$.\"{name}\"') AS TEXT), '')"
    return None


def table_columns(repository: Any) -> dict[str, list[str]]:
    """The Additional Columns of the workspace: built-in and CDR columns of the table, and CDR columns only exported to Excel."""
    try:
        stored = json.loads(repository.get_workspace_state(TABLE_COLUMNS_STATE_KEY) or '{}')
    except (TypeError, ValueError):
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    builtin = [column for column in _strings(stored.get('builtin')) if column in OPTIONAL_COLUMNS]
    cdr = [column for column in _strings(stored.get('cdr')) if column.strip()][:MAX_CDR_COLUMNS]
    export_cdr = [column for column in _strings(stored.get('export_cdr')) if column.strip() and column not in cdr][:MAX_EXPORT_CDR_COLUMNS]
    return {'builtin': builtin, 'cdr': cdr, 'export_cdr': export_cdr}


def indexed_cdr_columns(repository: Any) -> list[str]:
    """The CDR columns kept with every call: those of the table, those only exported to Excel and those of the catalog."""
    columns = table_columns(repository)
    try:
        catalog = [field['source_ref'][7:] for field in list_fields(repository)
                   if field['source'] == 'cdr' and field['source_ref'].startswith('column:')]
    except Exception:  # noqa: BLE001 - the catalog table may not exist yet while the module tables are created.
        catalog = []
    return list(dict.fromkeys([*columns['cdr'], *columns['export_cdr'], *catalog]))


def save_table_columns(repository: Any, builtin: Any, cdr: Any, username: str, export_cdr: Any = ()) -> dict[str, list[str]]:
    unknown = [column for column in _strings(builtin) if column not in OPTIONAL_COLUMNS]
    if unknown:
        raise ValueError(f'Unknown columns: {", ".join(unknown)}.')
    cdr_columns = list(dict.fromkeys(column.strip()[:120] for column in _strings(cdr) if column.strip()))
    if len(cdr_columns) > MAX_CDR_COLUMNS:
        raise ValueError(f'Choose at most {MAX_CDR_COLUMNS} CDR columns for the table.')
    # The table's CDR columns are always exported; these are exported to Excel only.
    export_columns = [column for column in dict.fromkeys(column.strip()[:120] for column in _strings(export_cdr) if column.strip())
                      if column not in cdr_columns]
    if len(export_columns) > MAX_EXPORT_CDR_COLUMNS:
        raise ValueError(f'Choose at most {MAX_EXPORT_CDR_COLUMNS} CDR columns for Excel only.')
    repository.set_workspace_state(TABLE_COLUMNS_STATE_KEY, json.dumps(
        {'builtin': _strings(builtin), 'cdr': cdr_columns, 'export_cdr': export_columns}))
    if hasattr(repository, 'try_add_log'):
        repository.try_add_log(username, 'nq_table_columns', 'Non-Qualified Calls table columns updated.')
    return table_columns(repository)


def available_cdr_columns(task_repository: Any) -> list[str]:
    """Every column of the indexed CDRs, for the CDR columns of the Calls table."""
    ids = [int(row['id']) for row in _cdr_datasets(task_repository)]
    if not ids:
        return []
    names: dict[str, str] = {}
    with task_repository.connection() as connection:
        rows = connection.execute(
            f"SELECT dataset_id, column_name FROM dataset_source_columns WHERE dataset_id IN ({', '.join('?' for _ in ids)})", ids,
        ).fetchall()
        described = {int(row['dataset_id']) for row in rows}
        columns = [str(row['column_name']) for row in rows]
        # CDRs without their source headings list the columns of their table.
        for dataset_id in ids:
            if dataset_id not in described:
                columns.extend(str(row[1]) for row in connection.execute(f'PRAGMA table_info({_quote(f"dataset_rows_{dataset_id}")})'))
    for column in columns:
        names.setdefault(column_identity(column), column)
    return sorted(names.values(), key=str.casefold)


def _dataset_revision(row: Any, signature: str = '') -> str:
    stage = dataset_cdr_stage(row['dataset_kind'], row['cdr_stage'] if 'cdr_stage' in row.keys() else None, row['file_name'])
    return ('|'.join(str(row[key] or '') for key in ('updated_at', 'processed_at', 'row_count', 'normalization_version'))
            + f'|{stage}|v{INDEX_VERSION}|{signature}')


def _columns_signature(cdr_columns: list[str]) -> str:
    return hashlib.sha1(json.dumps(sorted(column_identity(column) for column in cdr_columns)).encode('utf-8')).hexdigest()[:12] \
        if cdr_columns else ''


def _cdr_datasets(task_repository: Any) -> list[Any]:
    return [
        row for row in task_repository.list_datasets()
        if str(row['dataset_kind'] or '') in SERVICES and str(row['status'] or '') == 'ready'
    ]


_CALL_COLUMNS = ('dataset_id', 'source_row_id', 'call_key', 'service', 'nr_mode', *CALL_FIELDS,
                 'join_id', 'sample_key', 'sample_id', 'extra_json')
# The identity of a call needs only these fields.
_KEY_FIELDS = ('operator', 'campaign', 'test_name', 'start_time', 'end_time')


def _time_text(value: Any) -> str:
    return _text(value).replace('T', ' ')[:19]


def _dataset_calls(connection: Any, dataset: Any, cdr_columns: tuple[str, ...] = ()) -> dict[str, Any]:
    """The NQ rows of one CDR, ready to insert into ``nq_calls``, and every call of it for ``nq_call_population``.

    Speech CDRs list one row per sample: their samples share the call key of their call (the
    JOIN_ID or the A-side session) and each one has its own ``sample_key``.
    """
    dataset_id = int(dataset['id'])
    service = str(dataset['dataset_kind'])
    table = f'dataset_rows_{dataset_id}'
    empty = {'calls': [], 'population': [], 'data_date': ''}
    columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info({_quote(table)})').fetchall()]
    if not columns:
        return empty
    resolved = {field: _resolve_columns(columns, candidates) for field, candidates in FIELD_SOURCES.items()}
    if not resolved['result']:
        return empty
    result_column = resolved['result'][0]
    join_column = _resolve_column(columns, JOIN_SOURCES)
    identifier_column = _resolve_column(columns, IDENTIFIER_SOURCES.get(service, IDENTIFIER_SOURCES['data']))
    subscriber_column = _resolve_column(columns, SUBSCRIBER_SOURCES)
    sample_column = _resolve_column(columns, SAMPLE_SOURCES) if service == 'speech' else None
    extra = {name: column for name in cdr_columns if (column := _resolve_column(columns, (name,)))}
    nr_mode = _text(dataset['nr_mode'])

    def identity(row: Any, aliases: dict[str, str], values: dict[str, Any]) -> tuple[str, str]:
        join_id = _text(row[aliases[join_column]]) if join_column else ''
        identifier = _text(row[aliases[identifier_column]]) if identifier_column else ''
        subscriber = _text(row[aliases[subscriber_column]]) if subscriber_column else ''
        return call_key_for(service, values, identifier, subscriber, join_id), join_id

    # Every call of the CDR, with whether it is Non-Qualified: the population of the NQ rates.
    key_selected = list(dict.fromkeys(column for column in (
        result_column, join_column, identifier_column, subscriber_column,
        *(column for field in _KEY_FIELDS for column in resolved[field])) if column))
    key_aliases = {column: f'c{index}' for index, column in enumerate(key_selected)}
    population: dict[str, list[Any]] = {}
    data_date = ''
    for row in connection.execute(
        f"SELECT {', '.join(f'{_quote(column)} AS {key_aliases[column]}' for column in key_selected)} FROM {_quote(table)}"
    ):
        result = _text(row[key_aliases[result_column]]).casefold()
        if not result:
            continue
        values = {field: next((text for column in resolved[field] if (text := _text(row[key_aliases[column]]))), '')
                  for field in _KEY_FIELDS}
        key, _join_id = identity(row, key_aliases, values)
        is_nq = int(result != QUALIFIED_RESULT)
        entry = population.get(key)
        if entry is None:
            population[key] = [dataset_id, key, service, values['campaign'], values['operator'], nr_mode, is_nq]
        elif is_nq:
            entry[6] = 1
        moment = _time_text(values['start_time'])
        if moment > data_date:
            data_date = moment

    selected = list(dict.fromkeys(
        column for column in (*(item for items in resolved.values() for item in items), join_column, identifier_column,
                              subscriber_column, sample_column, *extra.values())
        if column
    ))
    aliases = {column: f'c{index}' for index, column in enumerate(selected)}
    normalized = f'LOWER(TRIM(CAST({_quote(result_column)} AS TEXT)))'
    # Range conditions use the CDR's normalized status index when it exists.
    query = (
        f"SELECT rowid AS source_row_id, {', '.join(f'{_quote(column)} AS {aliases[column]}' for column in selected)} "
        f"FROM {_quote(table)} WHERE {normalized} > ? OR ({normalized} < ? AND {normalized} > '')"
    )
    calls = []
    for row in connection.execute(query, (QUALIFIED_RESULT, QUALIFIED_RESULT)).fetchall():
        values: dict[str, Any] = {}
        for field, candidates in resolved.items():
            # The first candidate column with a value wins.
            if field in NUMERIC_FIELDS:
                values[field] = next((number for column in candidates if (number := _number(row[aliases[column]])) is not None), None)
            else:
                values[field] = next((text for column in candidates if (text := _text(row[aliases[column]]))), '')
        key, join_id = identity(row, aliases, values)
        sample_id = sample_key = ''
        if service == 'speech':
            sample_id = (_text(row[aliases[sample_column]]) if sample_column else '') or values['start_time'] or str(row['source_row_id'])
            sample_key = sample_key_for(key, sample_id)
        extras = {name: _text(row[aliases[column]]) for name, column in extra.items()}
        calls.append((dataset_id, int(row['source_row_id']), key, service, nr_mode, *(values[field] for field in CALL_FIELDS),
                      join_id, sample_key, sample_id, json.dumps(extras, ensure_ascii=False)))
    return {'calls': calls, 'population': list(population.values()), 'data_date': data_date}


def _move_follow_up(connection: Any, old_rows: list[Any], calls: list[tuple[Any, ...]]) -> int:
    """Move the follow-up of the previous call keys to the new ones (once, when the call key changes).

    Each previous key goes to the call (or Speech sample) of the row it was shown with. When two
    previous keys reach the same call, the newest follow-up wins and comments, history and analysis
    fields are kept from both.
    """
    position = {name: index for index, name in enumerate(_CALL_COLUMNS)}
    target = {(int(call[position['dataset_id']]), int(call[position['source_row_id']])):
              str(call[position['sample_key']] or call[position['call_key']]) for call in calls}
    shown: dict[str, tuple[int, tuple[int, int]]] = {}
    for row in old_rows:
        old_key, rowid = str(row['call_key']), int(row['rowid'])
        if old_key not in shown or rowid > shown[old_key][0]:
            shown[old_key] = (rowid, (int(row['dataset_id']), int(row['source_row_id'])))
    mapping = {old: target[place] for old, (_rowid, place) in shown.items() if place in target and target[place] != old}
    mapping = {old: new for old, new in mapping.items() if new not in mapping}
    for old, new in mapping.items():
        previous = connection.execute(f'SELECT * FROM {NQ_CALL_TRACKING_TABLE} WHERE call_key = ?', (old,)).fetchone()
        if previous is not None:
            current = connection.execute(f'SELECT updated_at FROM {NQ_CALL_TRACKING_TABLE} WHERE call_key = ?', (new,)).fetchone()
            if current is None:
                connection.execute(f'UPDATE {NQ_CALL_TRACKING_TABLE} SET call_key = ? WHERE call_key = ?', (new, old))
            elif str(previous['updated_at']) > str(current['updated_at']):
                connection.execute(f'DELETE FROM {NQ_CALL_TRACKING_TABLE} WHERE call_key = ?', (new,))
                connection.execute(f'UPDATE {NQ_CALL_TRACKING_TABLE} SET call_key = ? WHERE call_key = ?', (new, old))
            else:
                connection.execute(f'DELETE FROM {NQ_CALL_TRACKING_TABLE} WHERE call_key = ?', (old,))
        for table in (NQ_CALL_COMMENTS_TABLE, NQ_CALL_HISTORY_TABLE):
            connection.execute(f'UPDATE {table} SET call_key = ? WHERE call_key = ?', (new, old))
        connection.execute(
            f'INSERT OR IGNORE INTO {NQ_FIELD_VALUES_TABLE} (call_key, field_key, value, updated_by, updated_at) '
            f'SELECT ?, field_key, value, updated_by, updated_at FROM {NQ_FIELD_VALUES_TABLE} WHERE call_key = ?', (new, old))
        connection.execute(f'DELETE FROM {NQ_FIELD_VALUES_TABLE} WHERE call_key = ?', (old,))
    return len(mapping)


def _rebuild_versions(connection: Any, affected: set[str]) -> None:
    """Which CDR holds the latest version of each call and how the versions differ.

    The latest version is the one of a Final CDR before the Daily ones, then of the CDR with the
    newest data. Only the calls of the changed CDRs are recalculated, except whether a Final CDR
    covers the campaign of the calls that are only in Weekly or Daily CDRs.
    """
    connection.execute('CREATE TEMP TABLE IF NOT EXISTS nq_affected_keys (call_key TEXT PRIMARY KEY)')
    connection.execute('DELETE FROM nq_affected_keys')
    keys = list(affected)
    for start in range(0, len(keys), 5000):
        connection.executemany('INSERT OR IGNORE INTO nq_affected_keys (call_key) VALUES (?)',
                               [(key,) for key in keys[start:start + 5000]])
    connection.execute(
        f'UPDATE {NQ_CALL_POPULATION_TABLE} SET is_latest = 0 '
        f'WHERE is_latest = 1 AND call_key IN (SELECT call_key FROM nq_affected_keys)')
    connection.execute(f"""
        UPDATE {NQ_CALL_POPULATION_TABLE} SET is_latest = 1 WHERE rowid IN (
            SELECT rid FROM (
                SELECT p.rowid AS rid, ROW_NUMBER() OVER (
                    PARTITION BY p.call_key ORDER BY s.stage_rank DESC, s.data_date DESC, p.dataset_id DESC) AS rn
                FROM {NQ_CALL_POPULATION_TABLE} p
                JOIN {NQ_CALL_SOURCES_TABLE} s ON s.dataset_id = p.dataset_id
                WHERE p.call_key IN (SELECT call_key FROM nq_affected_keys)
            ) WHERE rn = 1)
    """)
    connection.execute(f'DELETE FROM {NQ_CALL_VERSIONS_TABLE} WHERE call_key IN (SELECT call_key FROM nq_affected_keys)')
    connection.execute(f"""
        INSERT INTO {NQ_CALL_VERSIONS_TABLE} (call_key, latest_dataset_id, latest_is_nq, in_final, changed, cdr_count)
        SELECT k.call_key, l.dataset_id, l.is_nq,
               EXISTS (SELECT 1 FROM {NQ_CALL_POPULATION_TABLE} f JOIN {NQ_CALL_SOURCES_TABLE} s ON s.dataset_id = f.dataset_id
                       WHERE f.call_key = k.call_key AND s.stage_rank = 1),
               (SELECT COUNT(DISTINCT c.result || '|' || c.failure_classification || '|' || c.failure_category)
                FROM {NQ_CALLS_TABLE} c WHERE c.call_key = k.call_key) > 1,
               (SELECT COUNT(*) FROM {NQ_CALL_POPULATION_TABLE} n WHERE n.call_key = k.call_key)
        FROM (SELECT DISTINCT call_key FROM {NQ_CALLS_TABLE} WHERE call_key IN (SELECT call_key FROM nq_affected_keys)) k
        JOIN {NQ_CALL_POPULATION_TABLE} l ON l.call_key = k.call_key AND l.is_latest = 1
    """)
    # A Final CDR covers the campaigns (of its service and NR Mode) it contains.
    connection.execute('CREATE TEMP TABLE IF NOT EXISTS nq_final_campaigns (service TEXT, nr_mode TEXT, campaign TEXT)')
    connection.execute('DELETE FROM nq_final_campaigns')
    connection.execute(f"""
        INSERT INTO nq_final_campaigns (service, nr_mode, campaign)
        SELECT DISTINCT p.service, p.nr_mode, lower(p.campaign) FROM {NQ_CALL_POPULATION_TABLE} p
        JOIN {NQ_CALL_SOURCES_TABLE} s ON s.dataset_id = p.dataset_id WHERE s.stage_rank = 1
    """)
    connection.execute(f"""
        UPDATE {NQ_CALL_VERSIONS_TABLE} SET final_covered = CASE WHEN in_final = 0 AND EXISTS (
            SELECT 1 FROM {NQ_CALL_POPULATION_TABLE} p JOIN nq_final_campaigns f
              ON f.service = p.service AND f.nr_mode = p.nr_mode AND f.campaign = lower(p.campaign)
            WHERE p.call_key = {NQ_CALL_VERSIONS_TABLE}.call_key AND p.is_latest = 1) THEN 1 ELSE 0 END
    """)


def _index_changes(task_repository: Any, force: bool = False) -> tuple[list[str], str, dict[int, Any], list[int], list[Any]]:
    """The indexed CDR columns and their signature, the CDRs, the indexed CDRs now removed and the CDRs to index."""
    cdr_columns = indexed_cdr_columns(task_repository)
    signature = _columns_signature(cdr_columns)
    datasets = {int(row['id']): row for row in _cdr_datasets(task_repository)}
    with task_repository.connection() as connection:
        indexed = {
            int(row['dataset_id']): str(row['revision'])
            for row in connection.execute(f'SELECT dataset_id, revision FROM {NQ_CALL_SOURCES_TABLE}').fetchall()
        }
    removed = [dataset_id for dataset_id in indexed if dataset_id not in datasets]
    changed = [row for dataset_id, row in datasets.items()
               if force or indexed.get(dataset_id) != _dataset_revision(row, signature)]
    return cdr_columns, signature, datasets, removed, changed


def sync_nq_calls(task_repository: Any, *, force: bool = False) -> dict[str, Any]:
    """Index the NQ calls and the population of new or changed CDRs and forget removed ones; ``force`` indexes
    every CDR again (Reindex)."""
    ensure_nq_tables(task_repository)
    path = str(task_repository.db_path)
    with _sync_locks_guard:
        lock = _sync_locks.setdefault(path, Lock())
    with lock:
        cdr_columns, signature, datasets, removed, changed = _index_changes(task_repository, force)
        migrating = str(task_repository.get_workspace_state(KEY_SCHEME_STATE_KEY) or '') != KEY_SCHEME
        moved = 0
        if removed or changed:
            # Read every changed CDR before taking the write transaction.
            with task_repository.connection() as connection:
                fresh = {int(row['id']): _dataset_calls(connection, row, tuple(cdr_columns)) for row in changed}
                touched = [*removed, *fresh]
                marks = ', '.join('?' for _ in touched)
                affected = {str(row[0]) for row in connection.execute(
                    f'SELECT DISTINCT call_key FROM {NQ_CALL_POPULATION_TABLE} WHERE dataset_id IN ({marks})', touched)}
                old_rows = connection.execute(
                    f'SELECT rowid, dataset_id, source_row_id, call_key FROM {NQ_CALLS_TABLE} WHERE dataset_id IN ({marks})',
                    touched).fetchall() if migrating else []
            columns = ', '.join(_CALL_COLUMNS)
            placeholders = ', '.join('?' for _ in _CALL_COLUMNS)
            with task_repository.connection() as connection:
                for dataset_id in touched:
                    connection.execute(f'DELETE FROM {NQ_CALLS_TABLE} WHERE dataset_id = ?', (dataset_id,))
                    connection.execute(f'DELETE FROM {NQ_CALL_SOURCES_TABLE} WHERE dataset_id = ?', (dataset_id,))
                    connection.execute(f'DELETE FROM {NQ_CALL_POPULATION_TABLE} WHERE dataset_id = ?', (dataset_id,))
                for dataset_id, content in fresh.items():
                    row = datasets[dataset_id]
                    connection.executemany(f'INSERT OR REPLACE INTO {NQ_CALLS_TABLE} ({columns}) VALUES ({placeholders})',
                                           content['calls'])
                    connection.executemany(
                        f'INSERT OR REPLACE INTO {NQ_CALL_POPULATION_TABLE} '
                        '(dataset_id, call_key, service, campaign, operator, nr_mode, is_nq) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        content['population'])
                    stage = dataset_cdr_stage(row['dataset_kind'], row['cdr_stage'] if 'cdr_stage' in row.keys() else None,
                                              row['file_name'])
                    connection.execute(
                        f'INSERT INTO {NQ_CALL_SOURCES_TABLE} (dataset_id, revision, call_count, synced_at, stage_rank, '
                        'data_date, population_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (dataset_id, _dataset_revision(row, signature), len({call[2] for call in content['calls']}), now_iso(),
                         int(stage == 'final'), content['data_date'], len(content['population'])),
                    )
                    affected.update(entry[1] for entry in content['population'])
                if old_rows:
                    moved = _move_follow_up(connection, old_rows, [call for content in fresh.values() for call in content['calls']])
                _rebuild_versions(connection, affected)
        if migrating:
            task_repository.set_workspace_state(KEY_SCHEME_STATE_KEY, KEY_SCHEME)
            if moved and hasattr(task_repository, 'try_add_log'):
                task_repository.try_add_log('system', 'nq_call_keys_upgraded',
                                            f'Non-Qualified Calls follow-up of {moved} calls moved to their JOIN_ID call keys.')
        # The latest versions of the calls are rebuilt here, in the background, rather than by the next page.
        refresh_latest_calls(task_repository)
        with task_repository.connection() as connection:
            total = connection.execute(f'SELECT COUNT(DISTINCT call_key) FROM {NQ_CALLS_TABLE}').fetchone()[0]
            synced_at = connection.execute(f'SELECT MAX(synced_at) FROM {NQ_CALL_SOURCES_TABLE}').fetchone()[0]
    return {'datasets': len(datasets), 'reindexed': len(changed), 'removed': len(removed),
            'calls': int(total or 0), 'synced_at': synced_at or ''}


# ---------------------------------------------------------------------------
# Indexing in the background: new, changed or removed CDRs are indexed once the server has been idle for a while
# (or at once the first time, and on Reindex), never while a page waits for its calls.
NQ_INDEX_IDLE_SECONDS = 2 * 60
_index_jobs: dict[str, dict[str, Any]] = {}
_index_jobs_guard = Lock()


def _workspace_key(path: Any) -> str:
    return str(Path(str(path)).resolve())


def nq_index_job(database_path: Any) -> dict[str, Any] | None:
    with _index_jobs_guard:
        job = _index_jobs.get(_workspace_key(database_path))
        return dict(job) if job else None


def start_nq_index(task_repository: Any, submit: Callable[..., Any], *, force: bool = False) -> dict[str, Any]:
    """Queue the indexing of the workspace (every CDR again with ``force``), unless it is already queued or running."""
    key = _workspace_key(task_repository.db_path)
    with _index_jobs_guard:
        current = _index_jobs.get(key)
        if current and current['status'] in {'queued', 'processing'}:
            return dict(current)
        job = {'status': 'queued', 'force': force, 'queued_at': time.time(), 'started_at': None, 'finished_at': None,
               'error': '', 'result': None}
        _index_jobs[key] = job

    def run() -> None:
        with _index_jobs_guard:
            job.update(status='processing', started_at=time.time())
        try:
            result = sync_nq_calls(task_repository, force=force)
        except Exception as exc:  # The next idle period or a Reindex tries again.
            with _index_jobs_guard:
                job.update(status='failed', error=str(exc), finished_at=time.time())
            return
        with _index_jobs_guard:
            job.update(status='ready', result=result, finished_at=time.time())

    submit(run)
    with _index_jobs_guard:
        return dict(job)


def nq_index_status(task_repository: Any) -> dict[str, Any]:
    """The indexed calls and CDRs, when they were last indexed, the CDRs waiting to be indexed and the running job."""
    _columns, _signature, datasets, removed, changed = _index_changes(task_repository)
    with task_repository.connection() as connection:
        total = connection.execute(f'SELECT COUNT(DISTINCT call_key) FROM {NQ_CALLS_TABLE}').fetchone()[0]
        synced_at = connection.execute(f'SELECT MAX(synced_at) FROM {NQ_CALL_SOURCES_TABLE}').fetchone()[0]
    job = nq_index_job(task_repository.db_path)
    running = bool(job and job['status'] in {'queued', 'processing'})
    return {'datasets': len(datasets), 'calls': int(total or 0), 'synced_at': synced_at or '',
            'pending': len(removed) + len(changed), 'indexing': running, 'reindexing': running and bool(job['force']),
            'error': job['error'] if job and job['status'] == 'failed' else ''}


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
    existing_statuses = {item['name'].casefold() for item in current['statuses']}
    renamed_statuses = {item['previous'].casefold(): item['name'] for item in lists['status']
                        if item['previous'] and item['previous'].casefold() in existing_statuses}
    try:
        stored_rules = json.loads(task_repository.get_workspace_state(STATUS_RULES_STATE_KEY) or '[]')
    except (TypeError, ValueError):
        stored_rules = []
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
    # The status rules follow renamed statuses and forget removed ones.
    if isinstance(stored_rules, list):
        rules = nq_catalog.rules_after_status_changes(
            [rule for rule in stored_rules if isinstance(rule, dict) and rule.get('status')], renamed_statuses,
            [item['name'] for item in lists['status']])
        task_repository.set_workspace_state(STATUS_RULES_STATE_KEY, json.dumps(rules, ensure_ascii=False))
    recompute_statuses(task_repository, username)
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_call_options', 'Non-Qualified Calls statuses and teams updated.')
    return list_options(task_repository)


# ---------------------------------------------------------------------------
# The field catalog: every field of the Analysis Center, in its section
# ---------------------------------------------------------------------------
MAX_FIELDS = nq_catalog.MAX_FIELDS


def list_fields(task_repository: Any) -> list[dict[str, Any]]:
    """The fields of the workspace catalog, in order, with their section, source and options."""
    with task_repository.connection() as connection:
        rows = connection.execute(f'SELECT * FROM {NQ_FIELDS_TABLE} ORDER BY position, label COLLATE NOCASE').fetchall()
    fields = []
    for row in rows:
        try:
            options = json.loads(row['options_json'] or '[]')
        except (TypeError, ValueError):
            options = []
        keys = row.keys()
        fields.append({
            'key': str(row['field_key']), 'label': str(row['label']), 'type': str(row['field_type']),
            'options': [{'name': str(item.get('name') or ''), 'color': str(item.get('color') or ''),
                         'keywords': _keywords(item.get('keywords'))}
                        for item in options if isinstance(item, dict) and item.get('name')],
            'in_table': bool(row['in_table']), 'in_summary': bool(row['in_summary']),
            'required_to_close': bool(row['required_to_close']), 'description': str(row['description'] or ''),
            'section': str(row['section'] if 'section' in keys else 'analysis') or 'analysis',
            'source': str(row['source'] if 'source' in keys else 'user') or 'user',
            'source_ref': str(row['source_ref'] if 'source_ref' in keys else '') or '',
            'in_export': bool(row['in_export'] if 'in_export' in keys else 1),
            'suggest_from': str(row['suggest_from'] if 'suggest_from' in keys else '') or '',
        })
    return fields


def _store_fields(task_repository: Any, fields: list[dict[str, Any]]) -> None:
    with task_repository.connection() as connection:
        connection.execute(f'DELETE FROM {NQ_FIELDS_TABLE}')
        connection.executemany(
            f'INSERT INTO {NQ_FIELDS_TABLE} (field_key, label, field_type, options_json, position, in_table, in_summary, '
            'required_to_close, description, section, source, source_ref, in_export, suggest_from) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [(field['key'], field['label'], field['type'],
              json.dumps([{'name': option['name'], 'color': option.get('color', ''),
                           **({'keywords': option['keywords']} if option.get('keywords') else {})}
                          for option in field['options']], ensure_ascii=False),
              index, int(field['in_table']), int(field['in_summary']), int(field['required_to_close']), field['description'],
              field['section'], field['source'], field['source_ref'], int(field.get('in_export', True)), field.get('suggest_from', ''))
             for index, field in enumerate(fields)],
        )


def save_fields(task_repository: Any, items: Any, username: str) -> list[dict[str, Any]]:
    """Replace the field catalog; renamed list values follow on every call and in the status rules, values in use
    cannot be removed, and the follow-up fields (status, team, assignee…) stay."""
    existing = {field['key']: field for field in list_fields(task_repository)}
    if not isinstance(items, list):
        raise ValueError('The field list is invalid.')
    # The follow-up fields (status, team, assignee…) cannot be removed: those left out keep their place at the end.
    given = {str(item.get('source_ref')) for item in items if isinstance(item, dict) and item.get('source') == 'tracking'}
    given |= {str(existing[str(item.get('key'))]['source_ref']) for item in items
              if isinstance(item, dict) and str(item.get('key')) in existing and existing[str(item.get('key'))]['source'] == 'tracking'}
    items = [*items, *(field for field in existing.values() if field['source'] == 'tracking' and field['source_ref'] not in given)]
    normalized = nq_catalog.normalize_fields(items, existing, CATALOG_CALL_FIELDS)
    kept = {field['key'] for field in normalized}
    with task_repository.connection() as connection:
        def used(key: str, value: str | None = None) -> int:
            sql = f"SELECT COUNT(*) FROM {NQ_FIELD_VALUES_TABLE} WHERE field_key = ? AND value <> ''"
            params: list[Any] = [key]
            if value is not None:
                sql += ' AND value = ? COLLATE NOCASE'
                params.append(value)
            return int(connection.execute(sql, params).fetchone()[0])

        for key, field in existing.items():
            if key not in kept and field['source'] == 'user' and used(key):
                raise ValueError(f'The field "{field["label"]}" has values; clear them before removing it.')
        for field in normalized:
            previous = existing.get(field['key'])
            if previous is None or previous['source'] != 'user':
                continue
            if (previous['type'] != field['type'] or field['source'] != 'user') and used(field['key']):
                raise ValueError(f'"{field["label"]}" has values: its type and source cannot change.')
            if field['type'] != 'list' or previous['type'] != 'list':
                continue
            old = {option['name'].casefold(): option['name'] for option in previous['options']}
            renamed = {option['previous'].casefold(): option['name'] for option in field['options']
                       if option.get('previous') and option['previous'].casefold() in old}
            names = {option['name'].casefold() for option in field['options']} | set(renamed)
            for key, name in old.items():
                if key not in names and used(field['key'], name):
                    raise ValueError(f'The value "{name}" of "{field["label"]}" is in use; rename it or change those calls first.')
            for key, name in renamed.items():
                if old[key] != name:
                    connection.execute(
                        f'UPDATE {NQ_FIELD_VALUES_TABLE} SET value = ? WHERE field_key = ? AND value = ? COLLATE NOCASE',
                        (name, field['key'], old[key]))
    rules = nq_catalog.rules_after_field_changes(status_rules(task_repository), list(existing.values()), normalized)
    _store_fields(task_repository, normalized)
    task_repository.set_workspace_state(STATUS_RULES_STATE_KEY, json.dumps(rules, ensure_ascii=False))
    recompute_statuses(task_repository, username)
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_analysis_fields', 'Non-Qualified Calls field catalog updated.')
    return list_fields(task_repository)


def list_sections(task_repository: Any) -> list[dict[str, str]]:
    """The six sections with the names and colours of the workspace."""
    try:
        stored = json.loads(task_repository.get_workspace_state(SECTIONS_STATE_KEY) or '[]')
    except (TypeError, ValueError):
        stored = []
    return nq_catalog.normalize_sections(stored if isinstance(stored, list) else [])


def save_sections(task_repository: Any, items: Any, username: str) -> list[dict[str, str]]:
    sections = nq_catalog.normalize_sections(items if isinstance(items, list) else [])
    task_repository.set_workspace_state(SECTIONS_STATE_KEY, json.dumps(sections, ensure_ascii=False))
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_sections', 'Non-Qualified Calls sections updated.')
    return sections


def _field_value(field: dict[str, Any], value: Any) -> str:
    """A valid value of a field entered by the analysts ('' clears it)."""
    text = str(value if value is not None else '').strip()
    if not text:
        return ''
    if field['source'] != 'user':
        raise ValueError(f'{field["label"]} is set automatically.')
    kind = field['type']
    if kind == 'list':
        names = {option['name'].casefold(): option['name'] for option in field['options']}
        if text.casefold() not in names:
            raise ValueError(f'Choose one of the values of {field["label"]}.')
        return names[text.casefold()]
    if kind == 'yes_no':
        names = {name.casefold(): name for name in YES_NO}
        if text.casefold() not in names:
            raise ValueError(f'{field["label"]} is Yes or No.')
        return names[text.casefold()]
    if kind == 'number':
        number = _number(text.replace(',', '.'))
        if number is None:
            raise ValueError(f'{field["label"]} is a number.')
        return str(int(number)) if number.is_integer() else repr(number)
    if kind == 'date':
        try:
            return datetime.strptime(text[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError as exc:
            raise ValueError(f'{field["label"]} is a date (YYYY-MM-DD).') from exc
    limit = MAX_LONG_TEXT if kind == 'long_text' else 300
    if len(text) > limit:
        raise ValueError(f'{field["label"]} accepts up to {limit} characters.')
    return text if kind == 'long_text' else re.sub(r'\s+', ' ', text)


def field_values(connection: Any, keys: list[str]) -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        for row in connection.execute(
            f"SELECT call_key, field_key, value FROM {NQ_FIELD_VALUES_TABLE} WHERE value <> '' "
            f"AND call_key IN ({', '.join('?' for _ in chunk)})", chunk,
        ):
            values.setdefault(str(row['call_key']), {})[str(row['field_key'])] = str(row['value'])
    return values


def derived_value(field: dict[str, Any], call: Any) -> str:
    """The value of a derived list: the first option whose keywords appear in the call values it reads."""
    text = ' '.join(_normalized_text(_call_value(call, name)) for name in field['source_ref'].split(','))
    return next((option['name'] for option in field['options'] if keyword_found(option.get('keywords') or [], text, 'text')), '')


def _call_value(call: Any, key: str) -> Any:
    key = key.strip()
    try:
        if key.startswith('column:'):
            extra = call['extra'] if isinstance(call, dict) and 'extra' in call else json.loads(call['extra_json'] or '{}')
            return (extra or {}).get(key[7:], '')
        return call[key]
    except (KeyError, IndexError, TypeError, ValueError):
        return ''


def catalog_value(field: dict[str, Any], call: Any, rca: dict[str, str] | None = None, stored: dict[str, str] | None = None) -> Any:
    """The value of a catalog field for a call: entered, followed up, from the CDR, the RCA script or derived."""
    source, ref = field['source'], field['source_ref']
    if source == 'user':
        return (stored or {}).get(field['key'], '')
    if source == 'tracking':
        return _call_value(call, 'comment_count' if ref == 'comments' else ref)
    if source == 'cdr':
        return _call_value(call, ref)
    if source == 'rca':
        return (rca or {}).get(ref, '')
    if source == 'derived':
        return derived_value(field, call)
    return ''


def field_sql(field: dict[str, Any]) -> str:
    """The SQL value of a catalog field in the calls query (``calls`` rows of ``_base_sql``)."""
    source, ref = field['source'], field['source_ref']
    if source == 'user':
        return f"COALESCE(json_extract(field_values_json, '$.\"{field['key']}\"'), '')"
    if source == 'tracking':
        return {'comments': 'comment_count', 'updated_at': "substr(updated_at, 1, 10)"}.get(ref, ref) \
            if ref in nq_catalog.TRACKING_REFS else "''"
    if source == 'cdr':
        if ref in CATALOG_CALL_FIELDS:
            return f"COALESCE(CAST({ref} AS TEXT), '')"
        name = ref[7:].replace('"', '').replace("'", '') if ref.startswith('column:') else ref
        return f"COALESCE(CAST(json_extract(extra_json, '$.\"{name}\"') AS TEXT), '')"
    if source == 'rca':
        name = ref.replace('"', '').replace("'", '')
        return f"COALESCE(json_extract(rca_json, '$.\"{name}\"'), '')"
    if source == 'derived':
        names = [name.strip() for name in ref.split(',') if name.strip() in CALL_FIELDS]
        if not names:
            return "''"
        text = "lower(' ' || " + " || ' ' || ".join(f"COALESCE({name}, '')" for name in names) + " || ' ')"
        text = f"replace({text}, '_', ' ')"
        cases = []
        for option in field['options']:
            tests = []
            for keyword in option.get('keywords') or []:
                parts = [part.replace("'", "''") for part in keyword.split('+')]
                tests.append('(' + ' AND '.join(f"instr({text}, '{part}') > 0" for part in parts) + ')')
            if tests:
                cases.append(f"WHEN {' OR '.join(tests)} THEN '{option['name'].replace(chr(39), chr(39) * 2)}'")
        return f"(CASE {' '.join(cases)} ELSE '' END)" if cases else "''"
    return "''"


def catalog_document(task_repository: Any) -> bytes:
    """The whole catalog of the workspace as an Excel workbook, to edit and import again."""
    options = list_options(task_repository)
    root = list_root_causes(task_repository)
    return nq_catalog.catalog_workbook(list_sections(task_repository), list_fields(task_repository), options['statuses'],
                                       options['teams'], root, status_rules(task_repository))


def _merged_catalog(task_repository: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """The catalog after an import: incoming entries first (matched by key or name), then the current ones it leaves out."""
    current_fields = list_fields(task_repository)
    by_key = {field['key']: field for field in current_fields}
    by_label = {field['label'].casefold(): field for field in current_fields}
    fields: list[dict[str, Any]] = []
    used: set[str] = set()
    for item in incoming.get('fields') or []:
        existing = by_key.get(str(item.get('key') or '')) or by_label.get(str(item.get('label') or '').casefold())
        if existing is not None:
            if existing['key'] in used:
                continue
            item = {**existing, **{key: value for key, value in item.items() if value not in (None, '')}, 'key': existing['key']}
            if existing['source'] != 'user':
                item.update(source=existing['source'], source_ref=existing['source_ref'], type=existing['type'])
            if not item.get('options'):
                item['options'] = existing['options']
            used.add(existing['key'])
        elif item.get('source') == 'tracking' and item.get('source_ref') in {field['source_ref'] for field in current_fields
                                                                             if field['source'] == 'tracking'}:
            continue
        fields.append(item)
    fields += [field for field in current_fields if field['key'] not in used]
    options = list_options(task_repository)
    statuses, teams = options['statuses'], options['teams']
    for plural, items in (('statuses', incoming.get('statuses')), ('teams', incoming.get('teams'))):
        if not items:
            continue
        current = statuses if plural == 'statuses' else teams
        names = {item['name'].casefold(): item for item in current}
        ordered = []
        for item in items:
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            base = names.get(name.casefold(), {})
            ordered.append({**base, **{key: value for key, value in item.items() if value not in (None, '')},
                            'previous': base.get('name', ''), **({'members': base.get('members', [])} if plural == 'teams' and not item.get('members') else {})})
        chosen = {item['name'].casefold() for item in ordered}
        ordered += [{**item, 'previous': item['name']} for item in current if item['name'].casefold() not in chosen]
        if plural == 'statuses':
            statuses = ordered
        else:
            teams = ordered
    root = list_root_causes(task_repository)
    catalog = {plural: [dict(item, previous=item['name']) for item in root[plural]] for plural in ('domains', 'categories', 'causes')}
    for plural, items in (incoming.get('root') or {}).items():
        names = {item['name'].casefold(): item for item in catalog.get(plural, [])}
        for item in items:
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            if name.casefold() in names:
                names[name.casefold()].update({key: value for key, value in item.items() if value not in (None, '', [])})
            else:
                catalog[plural].append(dict(item))
    return {'sections': incoming.get('sections'), 'fields': fields, 'statuses': statuses, 'teams': teams, 'root': catalog,
            'rules': incoming.get('rules'), 'require_to_close': root['require_to_close']}


def preview_catalog(task_repository: Any, content: bytes) -> dict[str, Any]:
    """What importing a catalog workbook would change, without changing anything."""
    incoming = nq_catalog.read_catalog_workbook(content)
    merged = _merged_catalog(task_repository, incoming)
    current_fields = {field['key']: field for field in list_fields(task_repository)}
    normalized = nq_catalog.normalize_fields(merged['fields'], current_fields, CATALOG_CALL_FIELDS)
    added = [field['label'] for field in normalized if field['key'] not in current_fields]
    changed = [field['label'] for field in normalized if field['key'] in current_fields and any(
        field[key] != current_fields[field['key']].get(key) for key in ('label', 'section', 'type', 'in_table', 'in_export'))
        or (field['key'] in current_fields and [option['name'] for option in field['options']]
            != [option['name'] for option in current_fields[field['key']]['options']])]
    root = list_root_causes(task_repository)
    root_added = {plural: [item['name'] for item in merged['root'][plural]
                           if item['name'].casefold() not in {entry['name'].casefold() for entry in root[plural]}]
                  for plural in ('domains', 'categories', 'causes')}
    options = list_options(task_repository)
    return {
        'format': incoming.get('format'), 'fields': len(normalized), 'added': added, 'changed': changed,
        'root_added': root_added, 'sections': bool(incoming.get('sections')),
        'statuses_added': [item['name'] for item in merged['statuses']
                           if item['name'].casefold() not in {entry['name'].casefold() for entry in options['statuses']}],
        'teams_added': [item['name'] for item in merged['teams']
                        if item['name'].casefold() not in {entry['name'].casefold() for entry in options['teams']}],
        'rules': len(incoming.get('rules') or []),
    }


def import_catalog(task_repository: Any, content: bytes, username: str, users: set[str] | None = None) -> dict[str, Any]:
    """Import a catalog workbook: the new fields, list values, catalog entries, statuses and teams are added, and the
    sections and status rules it has are taken. Nothing is removed."""
    incoming = nq_catalog.read_catalog_workbook(content)
    merged = _merged_catalog(task_repository, incoming)
    if merged['sections']:
        save_sections(task_repository, merged['sections'], username)
    save_options(task_repository, merged['statuses'], merged['teams'], username, users)
    save_root_causes(task_repository, merged['root'], merged['require_to_close'], username)
    save_fields(task_repository, merged['fields'], username)
    if merged['rules']:
        save_status_rules(task_repository, merged['rules'], username)
    return {'fields': list_fields(task_repository), 'sections': list_sections(task_repository),
            'root_causes': list_root_causes(task_repository), 'options': list_options(task_repository),
            'status_rules': status_rules(task_repository)}


# ---------------------------------------------------------------------------
# Root cause catalog: domains, root categories and root causes
# ---------------------------------------------------------------------------
def _write_root_catalog(connection: Any, catalog: dict[str, list[dict[str, Any]]]) -> None:
    connection.execute(f'DELETE FROM {NQ_ROOT_CATALOG_TABLE}')
    rows = [('domain', item['name'], '', item.get('color') or '#7b8790', json.dumps(_keywords(item.get('keywords'))), index)
            for index, item in enumerate(catalog['domains'])]
    for kind, plural in (('category', 'categories'), ('cause', 'causes')):
        rows += [(kind, item['name'], item.get('domain') or '', '', json.dumps(_keywords(item.get('keywords'))), index)
                 for index, item in enumerate(catalog[plural])]
    connection.executemany(
        f'INSERT INTO {NQ_ROOT_CATALOG_TABLE} (kind, name, domain, color, keywords, position) VALUES (?, ?, ?, ?, ?, ?)', rows)


def _read_root_catalog(connection: Any) -> dict[str, list[dict[str, Any]]]:
    rows = connection.execute(
        f'SELECT kind, name, domain, color, keywords FROM {NQ_ROOT_CATALOG_TABLE} ORDER BY position, name COLLATE NOCASE').fetchall()
    catalog: dict[str, list[dict[str, Any]]] = {'domains': [], 'categories': [], 'causes': []}
    plural = {'domain': 'domains', 'category': 'categories', 'cause': 'causes'}
    for row in rows:
        item = {'name': str(row['name']), 'keywords': _keywords(json.loads(row['keywords'] or '[]'))}
        if row['kind'] == 'domain':
            item['color'] = str(row['color'] or '#7b8790')
        else:
            item['domain'] = str(row['domain'] or '')
        catalog[plural[str(row['kind'])]].append(item)
    colors = {item['name']: item['color'] for item in catalog['domains']}
    for plural_name in ('categories', 'causes'):
        for item in catalog[plural_name]:
            item['color'] = colors.get(item['domain'], '')
    return catalog


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


def list_root_causes(task_repository: Any) -> dict[str, Any]:
    """The root cause catalog (domains, root categories and root causes, in order) and its settings."""
    with task_repository.connection() as connection:
        catalog = _read_root_catalog(connection)
    return {**catalog, **root_cause_settings(task_repository)}


def domain_of(catalog: dict[str, Any], category: str, cause: str) -> str:
    """The domain of a root category, else of a root cause."""
    for plural, name in (('categories', category), ('causes', cause)):
        item = next((entry for entry in catalog.get(plural) or [] if name and entry['name'].casefold() == name.casefold()), None)
        if item and item.get('domain'):
            return item['domain']
    return ''


def save_root_causes(task_repository: Any, catalog: Any, require_to_close: bool, username: str) -> dict[str, Any]:
    """Replace the root cause catalog; renamed values follow on every call, removed ones must be unused."""
    current = list_root_causes(task_repository)
    normalized = nq_catalog.normalize_root_catalog(catalog)
    columns = {'domains': 'root_domain', 'categories': 'root_category', 'causes': 'root_cause'}
    titles = {'domains': 'domain', 'categories': 'Root Category', 'causes': 'Root Cause'}
    with task_repository.connection() as connection:
        for plural, column in columns.items():
            existing = {item['name'].casefold(): item['name'] for item in current[plural]}
            renamed = {item['previous'].casefold(): item['name'] for item in normalized[plural]
                       if item['previous'] and item['previous'].casefold() in existing}
            kept = {item['name'].casefold() for item in normalized[plural]} | set(renamed)
            for key, name in existing.items():
                if key in kept:
                    continue
                if connection.execute(f'SELECT COUNT(*) FROM {NQ_CALL_TRACKING_TABLE} WHERE {column} = ? COLLATE NOCASE',
                                      (name,)).fetchone()[0]:
                    raise ValueError(f'The {titles[plural]} "{name}" is in use; rename it or change the root cause of its calls first.')
            for key, name in renamed.items():
                if existing[key] != name:
                    connection.execute(f'UPDATE {NQ_CALL_TRACKING_TABLE} SET {column} = ? WHERE {column} = ? COLLATE NOCASE',
                                       (name, existing[key]))
        _write_root_catalog(connection, normalized)
        _refresh_root_domains(connection, normalized)
    task_repository.set_workspace_state(ROOT_CAUSE_SETTINGS_STATE_KEY, json.dumps({'require_to_close': bool(require_to_close)}))
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_root_causes', 'Non-Qualified Calls root cause catalog updated.')
    return list_root_causes(task_repository)


def _refresh_root_domains(connection: Any, catalog: dict[str, Any]) -> None:
    """The stored domain of every call follows the domain of its root category (else of its root cause)."""
    rows = connection.execute(
        f"SELECT call_key, root_domain, root_category, root_cause FROM {NQ_CALL_TRACKING_TABLE} "
        "WHERE root_category <> '' OR root_cause <> ''").fetchall()
    for row in rows:
        domain = domain_of(catalog, str(row['root_category']), str(row['root_cause'])) or str(row['root_domain'] or '')
        if domain != str(row['root_domain'] or ''):
            connection.execute(f'UPDATE {NQ_CALL_TRACKING_TABLE} SET root_domain = ? WHERE call_key = ?', (domain, row['call_key']))


def suggest_root_cause(call: Any, taxonomy: dict[str, Any], comments: str = '') -> dict[str, str] | None:
    """The domain, root category and root cause the CDR (or the comments) suggest, following the workspace rule."""
    return nq_rca.suggest_from_text(call, taxonomy, taxonomy.get('rule') or DEFAULT_ROOT_CAUSE_RULE, comments)


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
# NQ Call Status: rules on the phase fields, or a status set by hand
# ---------------------------------------------------------------------------
def status_rules(task_repository: Any) -> list[dict[str, Any]]:
    """The status rules of the workspace; conditions on fields or statuses that no longer exist are left out."""
    try:
        stored = json.loads(task_repository.get_workspace_state(STATUS_RULES_STATE_KEY) or '[]')
    except (TypeError, ValueError):
        stored = []
    statuses = {item['name'].casefold(): item['name'] for item in list_options(task_repository)['statuses']}
    known = nq_catalog.condition_fields(list_fields(task_repository))
    rules = []
    for rule in stored if isinstance(stored, list) else []:
        if not isinstance(rule, dict) or str(rule.get('status') or '').casefold() not in statuses:
            continue
        conditions = [condition for condition in rule.get('conditions') or []
                      if isinstance(condition, dict) and condition.get('field') in known
                      and condition.get('op') in nq_catalog.RULE_OPERATORS]
        if conditions:
            rules.append({'status': statuses[str(rule['status']).casefold()], 'conditions': conditions})
    return rules


def save_status_rules(task_repository: Any, rules: Any, username: str) -> list[dict[str, Any]]:
    statuses = [item['name'] for item in list_options(task_repository)['statuses']]
    normalized = nq_catalog.normalize_status_rules(rules, statuses, list_fields(task_repository))
    task_repository.set_workspace_state(STATUS_RULES_STATE_KEY, json.dumps(normalized, ensure_ascii=False))
    changed = recompute_statuses(task_repository, username)
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_status_rules', f'Non-Qualified Calls status rules updated ({changed} calls changed).')
    return normalized


def _status_inputs(call: Any, stored: dict[str, str], fields: list[dict[str, Any]], tracking: dict[str, Any], attended: bool) -> dict[str, str]:
    """The values the status rules read for a call."""
    values = {field['key']: (stored.get(field['key'], '') if field['source'] == 'user' else derived_value(field, call) if call is not None else '')
              for field in fields if field['source'] in {'user', 'derived'}}
    values[ATTENDED_FIELD] = 'Yes' if attended else 'No'
    for ref in ('team', 'assignee', 'root_category', 'root_cause'):
        values[f'@{ref}'] = str(tracking.get(ref) or '')
    return values


def untracked_status(task_repository: Any, options: dict[str, list[dict[str, Any]]] | None = None) -> str:
    """The status of a call nobody has followed up: what the rules say without any value, else the first status."""
    options = options or list_options(task_repository)
    fallback = default_status(options)
    rules = status_rules(task_repository)
    return evaluate_status(rules, _status_inputs(None, {}, [], {}, False), fallback) if rules else fallback


def recompute_statuses(task_repository: Any, username: str, keys: list[str] | None = None) -> int:
    """Set again the automatic status of the followed-up or commented calls; returns how many changed."""
    options = list_options(task_repository)
    fallback = default_status(options)
    rules = status_rules(task_repository)
    fields = list_fields(task_repository)
    needs_call = any(field['source'] == 'derived' for field in fields)
    when = now_iso()
    changed = 0
    with task_repository.connection() as connection:
        tracked = {str(row['call_key']): dict(row) for row in connection.execute(f'SELECT * FROM {NQ_CALL_TRACKING_TABLE}')}
        commented = {str(row[0]) for row in connection.execute(
            f"SELECT DISTINCT call_key FROM {NQ_CALL_COMMENTS_TABLE} WHERE deleted_at = ''")}
        candidates = set(tracked) | commented | {str(row[0]) for row in connection.execute(
            f'SELECT DISTINCT call_key FROM {NQ_FIELD_VALUES_TABLE}')}
        if keys is not None:
            candidates &= set(keys)
        candidates = [key for key in candidates if tracked.get(key, {}).get('status_mode', 'auto') != 'manual']
        stored = field_values(connection, candidates)
        rows: dict[str, Any] = {}
        if needs_call:
            for start in range(0, len(candidates), 500):
                chunk = candidates[start:start + 500]
                marks = ', '.join('?' for _ in chunk)
                for row in connection.execute(
                        f'SELECT * FROM {NQ_CALLS_TABLE} WHERE call_key IN ({marks}) OR sample_key IN ({marks})', [*chunk, *chunk]):
                    rows.setdefault(str(row['sample_key'] or row['call_key']), row)
                    rows.setdefault(str(row['call_key']), row)
        for key in candidates:
            tracking = tracked.get(key, {})
            attended = bool(tracking.get('updated_at')) or key in commented
            status = evaluate_status(rules, _status_inputs(rows.get(key), stored.get(key, {}), fields, tracking, attended), fallback)
            current = str(tracking.get('status') or '') or fallback
            if status == current:
                continue
            connection.execute(
                f"INSERT INTO {NQ_CALL_TRACKING_TABLE} (call_key, status, status_mode, version, updated_by, updated_at) "
                "VALUES (?, ?, 'auto', 1, '', '') ON CONFLICT(call_key) DO UPDATE SET status = excluded.status, version = version + 1",
                (key, status))
            _record_history(connection, key, 'status_auto', current, status, username, when)
            changed += 1
    return changed


# ---------------------------------------------------------------------------
# Querying calls
# ---------------------------------------------------------------------------
# Operators and Vendors are indexed as the CDRs spell them and shown with their Operator
# and Vendor Maps labels, so filters, breakdowns, the table and exports use the mapped values.
MAPPED_FIELDS = ('operator', 'operator_vendor', 'vendor')


_value_maps_cache: dict[tuple[str, str], dict[str, str]] = {}
_value_maps_guard = Lock()


def _value_maps(task_repository: Any) -> dict[str, str]:
    """For each mapped field, a JSON object from the indexed source values to their mapped labels.

    ``vendor_operator`` maps each source Operator_Vendor to its mapped Vendor_Operator. The maps are kept until
    the indexed calls or the Operator and Vendor Maps change.
    """
    settings = task_repository.chart_mapping_settings()
    with task_repository.connection() as connection:
        stamp = tuple(connection.execute(f'SELECT COUNT(*), MAX(rowid) FROM {NQ_CALLS_TABLE}').fetchone())
    key = (_workspace_key(task_repository.db_path),
           hashlib.sha1(json.dumps([stamp, settings], sort_keys=True, default=str).encode()).hexdigest())
    with _value_maps_guard:
        if key in _value_maps_cache:
            return dict(_value_maps_cache[key])
    mapper = ValueMapper.from_settings(settings)
    maps = {}
    with task_repository.connection() as connection:
        for field in MAPPED_FIELDS:
            rows = connection.execute(f"SELECT DISTINCT {field} AS value FROM {NQ_CALLS_TABLE} WHERE {field} <> ''").fetchall()
            mapped = {str(row['value']): str(mapper.map(field_kind(field), row['value'])) for row in rows}
            maps[field] = json.dumps({source: label for source, label in mapped.items() if source != label})
            if field == 'operator_vendor':
                maps['vendor_operator'] = json.dumps({source: mapper.vendor_operators([label])[0]
                                                      for source, label in mapped.items()})
    with _value_maps_guard:
        if len(_value_maps_cache) > 16:
            _value_maps_cache.clear()
        _value_maps_cache[key] = dict(maps)
    return maps


def _materialized(connection: Any, base: str, params: list[Any], scoped: bool) -> tuple[str, list[Any]]:
    """The calls of a choice of CDRs read once into a temporary table of the connection, for the several queries of
    one request (without a choice the latest versions table is already fast)."""
    if not scoped:
        return base, params
    connection.execute('DROP TABLE IF EXISTS temp.nq_scoped_calls')
    connection.execute(f'CREATE TEMP TABLE nq_scoped_calls AS {base}', params)
    return 'SELECT * FROM temp.nq_scoped_calls', []


def _scope(filters: dict[str, Any] | None) -> list[int]:
    """The CDRs chosen in the CDRs filter (none means every CDR)."""
    return [int(value) for value in _strings((filters or {}).get('datasets')) if value.lstrip('-').isdigit()]


# The columns of the latest version of each call that only change when the CDRs are indexed or the maps change.
LATEST_COLUMNS = ('dataset_id', 'source_row_id', 'call_key', 'service', 'nr_mode', *CALL_FIELDS, 'vendor_operator', 'last_cell_id',
                  'join_id', 'extra_json', 'nq_samples', 'latest_dataset_id', 'cdr_count', 'version_state')
LATEST_STATE_KEY = 'nq_call_latest_fingerprint'
_latest_locks: dict[str, Lock] = {}
_latest_guard = Lock()


def _latest_sql(maps: dict[str, str], dataset_ids: list[int] | None = None) -> tuple[str, list[Any]]:
    """The latest version of every call among the chosen CDRs (every CDR when none is chosen).

    A Final CDR comes before the Daily ones, then the CDR with the newest data. ``version_state``
    tells how the other CDRs see the call: ``qualified`` (the latest CDR has it Completed),
    ``not_in_final`` (only in Weekly or Daily CDRs while a Final CDR covers its campaign), ``newer`` (a newer
    CDR outside the chosen ones has it) or ``changed`` (its result or failure differs between CDRs).
    Speech calls count their Non-Qualified samples in ``nq_samples``.
    """
    columns = ', '.join(
        f'COALESCE((SELECT m.value FROM json_each(?) m WHERE m.key = c.{column}), c.{column}) AS {column}'
        if column in MAPPED_FIELDS else f'c.{column}'
        for column in ('dataset_id', 'source_row_id', 'call_key', 'service', 'nr_mode', *CALL_FIELDS)
    )
    params: list[Any] = [maps[column] for column in ('dataset_id', 'source_row_id', 'call_key', 'service', 'nr_mode', *CALL_FIELDS)
                         if column in MAPPED_FIELDS]
    # Vendor_Operator: the mapped Operator_Vendor the other way round.
    params.append(maps['vendor_operator'])
    scope = list(dict.fromkeys(int(value) for value in dataset_ids or []))
    scope_sql = f"WHERE n.dataset_id IN ({', '.join('?' for _ in scope)})" if scope else ''
    sql = f"""
        SELECT {columns},
               COALESCE((SELECT m.value FROM json_each(?) m WHERE m.key = c.operator_vendor), '') AS vendor_operator,
               {last_cell_sql('c.cell_id')} AS last_cell_id,
               c.join_id, c.extra_json, c.nq_samples,
               COALESCE(v.latest_dataset_id, c.dataset_id) AS latest_dataset_id,
               COALESCE(v.cdr_count, 1) AS cdr_count,
               CASE WHEN v.latest_is_nq = 0 THEN 'qualified'
                    WHEN v.in_final = 0 AND v.final_covered = 1 THEN 'not_in_final'
                    WHEN v.latest_dataset_id IS NOT NULL AND v.latest_dataset_id <> c.dataset_id THEN 'newer'
                    WHEN v.changed = 1 THEN 'changed' ELSE '' END AS version_state
        FROM (
            SELECT n.*, COUNT(*) OVER (PARTITION BY n.call_key, n.dataset_id) AS nq_samples,
                   ROW_NUMBER() OVER (PARTITION BY n.call_key
                                      ORDER BY s.stage_rank DESC, s.data_date DESC, n.dataset_id DESC, n.start_time, n.rowid) AS rn
            FROM {NQ_CALLS_TABLE} n JOIN {NQ_CALL_SOURCES_TABLE} s ON s.dataset_id = n.dataset_id
            {scope_sql}
        ) c
        LEFT JOIN {NQ_CALL_VERSIONS_TABLE} v ON v.call_key = c.call_key
        WHERE c.rn = 1
    """
    return sql, [*params, *scope]


def _latest_fingerprint(connection: Any, maps: dict[str, str]) -> str:
    """What the latest versions depend on: the indexed CDRs, their calls and the Operator and Vendor maps."""
    sources = [tuple(row) for row in connection.execute(
        f'SELECT dataset_id, revision, stage_rank, data_date, synced_at FROM {NQ_CALL_SOURCES_TABLE} ORDER BY dataset_id')]
    calls = tuple(connection.execute(f'SELECT COUNT(*), MAX(rowid) FROM {NQ_CALLS_TABLE}').fetchone())
    payload = json.dumps([INDEX_VERSION, sources, calls, maps], sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()


def refresh_latest_calls(task_repository: Any, *, force: bool = False, maps: dict[str, str] | None = None) -> bool:
    """Rebuild the latest version of every call when the indexed CDRs or the maps changed; returns whether it did."""
    maps = maps or _value_maps(task_repository)
    key = _workspace_key(task_repository.db_path)
    with _latest_guard:
        lock = _latest_locks.setdefault(key, Lock())
    with lock:
        with task_repository.connection() as connection:
            fingerprint = _latest_fingerprint(connection, maps)
            stored = connection.execute('SELECT value FROM workspace_state WHERE key = ?', (LATEST_STATE_KEY,)).fetchone()
        if not force and stored and str(stored[0]) == fingerprint:
            return False
        sql, params = _latest_sql(maps)
        columns = ', '.join(LATEST_COLUMNS)
        with task_repository.connection() as connection:
            connection.execute(f'DELETE FROM {NQ_CALL_LATEST_TABLE}')
            connection.execute(f'INSERT INTO {NQ_CALL_LATEST_TABLE} ({columns}) SELECT {columns} FROM ({sql})', params)
            connection.execute('INSERT INTO workspace_state (key, value) VALUES (?, ?) '
                               'ON CONFLICT(key) DO UPDATE SET value = excluded.value', (LATEST_STATE_KEY, fingerprint))
    return True


def _latest_ready(task_repository: Any, maps: dict[str, str]) -> bool:
    """Whether the calls are read from the latest versions table: rebuilt first when needed, except while the
    CDRs are being indexed, when the previous versions stay until the indexing ends."""
    job = nq_index_job(task_repository.db_path)
    if job and job['status'] in {'queued', 'processing'}:
        with task_repository.connection() as connection:
            return connection.execute('SELECT 1 FROM workspace_state WHERE key = ?', (LATEST_STATE_KEY,)).fetchone() is not None
    refresh_latest_calls(task_repository, maps=maps)
    return True


def _base_sql(default: str, task_repository: Any, dataset_ids: list[int] | None = None) -> tuple[str, list[Any]]:
    """One row per call with its follow-up: the version of the most recent CDR among the chosen ones.

    Without a choice of CDRs the latest versions come from the ``nq_call_latest`` table; the follow-up (status,
    team, assignee, root cause, comments, fields and RCA results) is always read as it is now.
    """
    maps = _value_maps(task_repository)
    scope = list(dict.fromkeys(int(value) for value in dataset_ids or []))
    if not scope and _latest_ready(task_repository, maps):
        source, source_params = NQ_CALL_LATEST_TABLE, []
    else:
        latest, source_params = _latest_sql(maps, scope)
        source = f'({latest})'
    sql = f"""
        SELECT s.*,
               COALESCE(NULLIF(t.status, ''), ?) AS status,
               COALESCE(t.team, '') AS team,
               COALESCE(t.assignee, '') AS assignee,
               COALESCE(t.root_domain, '') AS root_domain,
               COALESCE(t.root_category, '') AS root_category,
               COALESCE(t.root_cause, '') AS root_cause,
               COALESCE(t.status_mode, 'auto') AS status_mode,
               COALESCE(t.version, 0) AS version,
               COALESCE(t.updated_by, '') AS updated_by,
               COALESCE(t.updated_at, '') AS updated_at,
               (SELECT COUNT(*) FROM {NQ_CALL_COMMENTS_TABLE} m WHERE m.call_key = s.call_key AND m.deleted_at = '') AS comment_count,
               (SELECT json_group_object(f.field_key, f.value) FROM {NQ_FIELD_VALUES_TABLE} f
                WHERE f.call_key = s.call_key AND f.value <> '') AS field_values_json,
               COALESCE((SELECT r.values_json FROM {NQ_RCA_RESULTS_TABLE} r
                         WHERE s.join_id <> '' AND r.join_id = lower(s.join_id)), '{{}}') AS rca_json
        FROM {source} s
        LEFT JOIN {NQ_CALL_TRACKING_TABLE} t ON t.call_key = s.call_key
    """
    # Placeholders in order: the default status (select list), then those of the latest versions (maps and CDRs).
    return sql, [default, *source_params]


def _sample_sql(default: str, task_repository: Any) -> tuple[str, list[Any]]:
    """The Speech samples with their own follow-up, as call rows keyed by their ``sample_key``."""
    maps = _value_maps(task_repository)
    columns = ', '.join(
        f'COALESCE((SELECT m.value FROM json_each(?) m WHERE m.key = c.{column}), c.{column}) AS {column}'
        if column in MAPPED_FIELDS else f'c.{column}'
        for column in ('dataset_id', 'source_row_id', 'service', 'nr_mode', *CALL_FIELDS)
    )
    params = [maps[column] for column in ('dataset_id', 'source_row_id', 'service', 'nr_mode', *CALL_FIELDS) if column in MAPPED_FIELDS]
    sql = f"""
        SELECT {columns}, c.sample_key AS call_key, c.call_key AS parent_key, c.sample_id, c.join_id, c.extra_json,
               1 AS nq_samples, '' AS vendor_operator, {last_cell_sql('c.cell_id')} AS last_cell_id,
               COALESCE(NULLIF(t.status, ''), ?) AS status, COALESCE(t.team, '') AS team,
               COALESCE(t.assignee, '') AS assignee, COALESCE(t.root_domain, '') AS root_domain,
               COALESCE(t.root_category, '') AS root_category, COALESCE(t.root_cause, '') AS root_cause,
               COALESCE(t.status_mode, 'auto') AS status_mode, COALESCE(t.version, 0) AS version,
               COALESCE(t.updated_by, '') AS updated_by, COALESCE(t.updated_at, '') AS updated_at,
               (SELECT COUNT(*) FROM {NQ_CALL_COMMENTS_TABLE} m WHERE m.call_key = c.sample_key AND m.deleted_at = '') AS comment_count,
               c.dataset_id AS latest_dataset_id, 1 AS cdr_count, '' AS version_state,
               (SELECT json_group_object(f.field_key, f.value) FROM {NQ_FIELD_VALUES_TABLE} f
                WHERE f.call_key = c.sample_key AND f.value <> '') AS field_values_json,
               COALESCE((SELECT r.values_json FROM {NQ_RCA_RESULTS_TABLE} r
                         WHERE c.join_id <> '' AND r.join_id = lower(c.join_id)), '{{}}') AS rca_json
        FROM {NQ_CALLS_TABLE} c
        JOIN {NQ_CALL_SOURCES_TABLE} s ON s.dataset_id = c.dataset_id
        LEFT JOIN {NQ_CALL_TRACKING_TABLE} t ON t.call_key = c.sample_key
        WHERE c.sample_key <> ''
    """
    return sql, [*params, default]


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
    for field in (*FIELD_FILTERS, *TRACKING_FILTERS, *TYPED_FILTERS, *EXTRA_FILTERS, 'datasets', 'version'):
        values = _strings(filters.get(field))[:5000]
        if values:
            saved[field] = values
    fields = filters.get('fields') if isinstance(filters.get('fields'), dict) else {}
    chosen = {str(key): _strings(values)[:5000] for key, values in fields.items() if _strings(values)}
    if chosen:
        saved['fields'] = chosen
    columns = filters.get('columns') if isinstance(filters.get('columns'), dict) else {}
    chosen_columns = {str(key): _strings(values)[:MAX_COLUMN_FILTER_VALUES] for key, values in columns.items()
                      if column_filter_sql(str(key)) and _strings(values)}
    if chosen_columns:
        saved['columns'] = chosen_columns
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


_key_filters_cache: dict[tuple[str, str], tuple[str, ...]] = {}
_key_filters_guard = Lock()


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
    base, base_params = _base_sql(untracked_status(task_repository, options), task_repository, _scope(filters))
    # The panels of one filter change ask for the same calls at once: they are found once while nothing changes.
    with task_repository.connection() as connection:
        stamp = [tuple(connection.execute(sql).fetchone()) for sql in (
            f'SELECT COUNT(*), SUM(version), MAX(updated_at) FROM {NQ_CALL_TRACKING_TABLE}',
            f'SELECT COUNT(*), MAX(id), MAX(edited_at), MAX(deleted_at) FROM {NQ_CALL_COMMENTS_TABLE}')]
    cache_key = (_workspace_key(task_repository.db_path), hashlib.sha1(json.dumps(
        [base, base_params, stamp, taxonomy, {field: sorted(values) for field, values in wanted.items()}],
        sort_keys=True, default=str).encode()).hexdigest())
    with _key_filters_guard:
        cached = _key_filters_cache.get(cache_key)
    if cached is not None:
        return {**filters, '_call_keys': list(cached)}
    columns = ', '.join(dict.fromkeys(('call_key', 'root_domain', 'root_cause', 'cell_id', 'operator', *RULE_FIELDS)))
    with task_repository.connection() as connection:
        calls = connection.execute(f'WITH calls AS ({base}) SELECT {columns} FROM calls', base_params).fetchall()
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
    with _key_filters_guard:
        if len(_key_filters_cache) >= 16:
            _key_filters_cache.pop(next(iter(_key_filters_cache)))
        _key_filters_cache[cache_key] = tuple(keys)
    return {**filters, '_call_keys': keys}


def _filter_sql(filters: dict[str, Any], username: str, closed_statuses: list[str],
                definitions: list[dict[str, Any]] | None = None) -> tuple[str, list[Any]]:
    known = {field['key']: field for field in definitions or []}
    clauses: list[str] = []
    params: list[Any] = []
    for field in (*FIELD_FILTERS, *TRACKING_FILTERS):
        values = _strings(filters.get(field))
        if not values:
            continue
        values = ['' if value == UNASSIGNED else value for value in values]
        clauses.append(f"{field} IN ({', '.join('?' for _ in values)})")
        params.extend(values)
    # The JOIN_IDs typed in their filter, whatever their case.
    join_ids = [value.casefold() for value in _strings(filters.get('join_id'))]
    if join_ids:
        clauses.append('lower(join_id) IN (SELECT value FROM json_each(?))')
        params.append(json.dumps(join_ids))
    # The CDRs filter chooses the versions in the base query. A call whose latest CDR has it
    # Completed is listed only on request, or while that CDR is not among the chosen ones.
    versions = ['' if value == 'current' else value for value in _strings(filters.get('version')) if value in VERSION_STATES]
    scope = _scope(filters)
    if versions:
        clauses.append(f"version_state IN ({', '.join('?' for _ in versions)})")
        params.extend(versions)
    elif scope:
        clauses.append(f"(version_state <> 'qualified' OR latest_dataset_id NOT IN ({', '.join('?' for _ in scope)}))")
        params.extend(scope)
    else:
        clauses.append("version_state <> 'qualified'")
    fields = filters.get('fields') if isinstance(filters.get('fields'), dict) else {}
    for key, values in fields.items():
        values = _strings(values)
        if not values:
            continue
        definition = known.get(str(key))
        if definition is not None and definition['source'] != 'user':
            # Fields from the follow-up, the CDR, the RCA script or derived: compared with their value.
            chosen = ['' if value == UNASSIGNED else value for value in values]
            clauses.append(f"{field_sql(definition)} IN ({', '.join('?' for _ in chosen)})")
            params.extend(chosen)
            continue
        chosen = [value for value in values if value != UNASSIGNED]
        parts = []
        if chosen:
            parts.append(f"EXISTS (SELECT 1 FROM {NQ_FIELD_VALUES_TABLE} f WHERE f.call_key = calls.call_key AND f.field_key = ? "
                         f"AND f.value IN ({', '.join('?' for _ in chosen)}))")
            params.extend([str(key), *chosen])
        if UNASSIGNED in values:
            parts.append(f"NOT EXISTS (SELECT 1 FROM {NQ_FIELD_VALUES_TABLE} f WHERE f.call_key = calls.call_key "
                         "AND f.field_key = ? AND f.value <> '')")
            params.append(str(key))
        clauses.append('(' + ' OR '.join(parts) + ')')
    # The optional and CDR columns of the table, filtered by their values ("Empty" for blank ones).
    columns = filters.get('columns') if isinstance(filters.get('columns'), dict) else {}
    for key, values in columns.items():
        expression = column_filter_sql(str(key))
        values = ['' if value == UNASSIGNED else value for value in _strings(values)]
        if expression and values:
            clauses.append(f"{expression} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
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
            f"WHERE s.call_key = calls.call_key AND s.deleted_at = '' AND instr(lower(s.body), ?) > 0) "
            f"OR EXISTS (SELECT 1 FROM {NQ_FIELD_VALUES_TABLE} f WHERE f.call_key = calls.call_key AND instr(lower(f.value), ?) > 0))"
        )
        params.extend([search, search, search])
    return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', params


def _call_payload(row: Any) -> dict[str, Any]:
    payload = {key: row[key] for key in row.keys()}
    payload['service_label'] = SERVICE_LABELS.get(str(payload.get('service')), str(payload.get('service') or ''))
    for source, target in (('field_values_json', 'fields'), ('extra_json', 'extra'), ('rca_json', 'rca')):
        try:
            value = json.loads(payload.pop(source, None) or '{}')
        except (TypeError, ValueError):
            value = {}
        payload[target] = value if isinstance(value, dict) else {}
    return payload


def _order_sql(sort: str, task_repository: Any) -> str:
    """The ORDER BY expression of a sort key: a column, an analysis field or a CDR column."""
    if sort.startswith('field:'):
        key = sort.split(':', 1)[1]
        definition = next((field for field in list_fields(task_repository) if field['key'] == key), None)
        if definition is not None:
            return field_sql(definition)
    if sort.startswith('cdr:'):
        name = sort.split(':', 1)[1]
        if name in table_columns(task_repository)['cdr']:
            return f"COALESCE(json_extract(extra_json, '$.\"{name.replace(chr(34), '')}\"'), '')"
    return SORT_COLUMNS.get(sort, 'start_time')


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
    definitions = list_fields(task_repository)
    filters = request.get('filters') if isinstance(request.get('filters'), dict) else {}
    filters = _resolve_key_filters(task_repository, filters)
    closed = [item['name'] for item in options['statuses'] if item['closed']]
    base, base_params = _base_sql(untracked_status(task_repository, options), task_repository, _scope(filters))
    where, params = _filter_sql(filters, username, closed, definitions)
    sort_key = str(request.get('sort') or '')
    sort = _order_sql(sort_key, task_repository)
    direction = 'ASC' if str(request.get('direction') or '').lower() == 'asc' else 'DESC'
    page_size = int(request.get('page_size') or 50)
    page_size = page_size if page_size in PAGE_SIZES else 50
    # The breakdowns of the Summary are left out while it is not shown.
    with_breakdowns = request.get('breakdowns', True) is not False
    with task_repository.connection() as connection:
        base, base_params = _materialized(connection, base, base_params, bool(_scope(filters)))
        filtered = f'WITH calls AS ({base}) SELECT * FROM calls{where}'
        all_params = [*base_params, *params]
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
        learned = learned_decisions(connection)
        names = {int(row['id']): str(row['file_name']) for row in connection.execute('SELECT id, file_name FROM datasets')}
        for call in calls:
            call['last_comment'] = last_comments.get(call['call_key'])
            note = notes.get(call['call_key'], '')
            call['suggested_root_cause'] = suggest_root_cause(call, taxonomy, note)
            call['rca_recommendation'] = recommendation_for(call, taxonomy, note, learned)
            call['values'] = {field['key']: catalog_value(field, call, call.get('rca'), call.get('fields')) for field in definitions}
            call['dataset_name'] = names.get(int(call['dataset_id']), '')
            call['latest_dataset_name'] = names.get(int(call['latest_dataset_id'] or call['dataset_id']), '')
        breakdowns = []
        mapping_settings = task_repository.chart_mapping_settings()
        for field, label in BREAKDOWNS if with_breakdowns else ():
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
        # The catalog fields shown in the Summary, as one more breakdown each.
        for definition in [field for field in definitions if with_breakdowns and field['in_summary']
                           and field['source'] in {'user', 'derived', 'cdr', 'rca'}]:
            values = connection.execute(
                f"SELECT {field_sql(definition)} AS value, COUNT(*) AS count "
                f"FROM ({filtered}) GROUP BY value ORDER BY count DESC, value LIMIT 12", all_params,
            ).fetchall()
            order = [option['name'] for option in definition['options']] or list(YES_NO)
            items = [{'value': str(row['value'] or ''), 'count': int(row['count'])} for row in values]
            items.sort(key=lambda item: (order.index(item['value']) if item['value'] in order else len(order), -item['count']))
            breakdowns.append({'field': f"field:{definition['key']}", 'label': f"By {definition['label']}", 'items': items,
                               'colors': {option['name']: option['color'] for option in definition['options'] if option['color']}})
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
        'sort': sort_key if sort_key.startswith(('field:', 'cdr:')) and sort != 'start_time'
        else next((key for key, column in SORT_COLUMNS.items() if column == sort), 'start_time'),
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
        # The values of every optional and CDR column of the table, for their header filters.
        chosen = table_columns(task_repository)
        for key in [*(column for column in chosen['builtin'] if column in COLUMN_FILTER_SQL), *(f'cdr:{name}' for name in chosen['cdr'])]:
            expression = column_filter_sql(key)
            rows = connection.execute(
                f"SELECT DISTINCT {expression} AS value FROM {NQ_CALLS_TABLE} WHERE {expression} <> '' "
                f"ORDER BY value COLLATE NOCASE LIMIT {MAX_COLUMN_FILTER_VALUES}"
            ).fetchall()
            values[f'column:{key}'] = [str(row['value']) for row in rows]
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


KEYED_READ_CHUNK = 500
# With more calls than this, the history or comments of the calls are read once and kept for the calls in Python.
KEYED_READ_SCAN = 4000


def _rows_of_calls(connection: Any, select: str, keys: list[str], where: str = '', order: str = '') -> list[Any]:
    """The rows of a follow-up table (history, comments) for some calls: by key for a few calls, or in one read."""
    condition = f' AND ({where})' if where else ''
    order_sql = f' ORDER BY {order}' if order else ''
    if len(keys) > KEYED_READ_SCAN:
        wanted = set(keys)
        return [row for row in connection.execute(f'{select} WHERE 1 = 1{condition}{order_sql}') if str(row['call_key']) in wanted]
    rows: list[Any] = []
    for start in range(0, len(keys), KEYED_READ_CHUNK):
        chunk = keys[start:start + KEYED_READ_CHUNK]
        rows.extend(connection.execute(
            f"{select} WHERE call_key IN ({', '.join('?' for _ in chunk)}){condition}{order_sql}", chunk).fetchall())
    if len(keys) > KEYED_READ_CHUNK and order:
        rows.sort(key=lambda row: tuple(row[name.split()[0]] for name in order.split(', ')))
    return rows


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
    base, base_params = _base_sql(untracked_status(task_repository, options), task_repository, _scope(filters))
    where, params = _filter_sql(_resolve_key_filters(task_repository, filters), username,
                                [item['name'] for item in options['statuses'] if item['closed']], list_fields(task_repository))
    with task_repository.connection() as connection:
        calls = connection.execute(
            f'WITH calls AS ({base}) SELECT call_key, start_time, status, team, assignee, service, result FROM calls{where}',
            [*base_params, *params],
        ).fetchall()
        keys = [str(row['call_key']) for row in calls]
        history = _rows_of_calls(connection, f'SELECT id, call_key, field, old_value, new_value, changed_by, changed_at '
                                             f'FROM {NQ_CALL_HISTORY_TABLE}', keys, order='changed_at, id')
        comments = _rows_of_calls(connection, f'SELECT id, call_key, created_by, created_at, deleted_at FROM {NQ_CALL_COMMENTS_TABLE}',
                                  keys, order='created_at, id')

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
    base, base_params = _base_sql(untracked_status(task_repository, options), task_repository, _scope(filters))
    where, params = _filter_sql(_resolve_key_filters(task_repository, filters), username,
                                [item['name'] for item in options['statuses'] if item['closed']], list_fields(task_repository))
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


# The filters that also apply to every call (qualified or not) of the NQ rates.
RATE_FILTERS = ('datasets', 'service', 'campaign', 'operator', 'nr_mode')


def nq_rates(task_repository: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Calls, Non-Qualified Calls and their share for each campaign and operator.

    Every call counts once, in the most recent of the chosen CDRs that has it (a Final CDR before
    the Daily ones), so a call that is Completed there is no longer Non-Qualified. Only the CDRs,
    Service, Campaign, Operator and NR Mode filters apply: the other filters describe Non-Qualified
    Calls only. Operators show their Operator Map label.
    """
    scope = _scope(filters)
    services = _strings(filters.get('service'))
    campaigns = set(_strings(filters.get('campaign')))
    nr_modes = {'' if value in {UNASSIGNED, 'Unknown'} else value for value in _strings(filters.get('nr_mode'))}
    mapper = ValueMapper.from_repository(task_repository)
    operators = {str(mapper.map(field_kind('operator'), value)) for value in _strings(filters.get('operator'))}
    where, params = [], []
    if services:
        where.append(f"p.service IN ({', '.join('?' for _ in services)})")
        params.extend(services)
    if scope:
        where.append(f"p.dataset_id IN ({', '.join('?' for _ in scope)})")
        params.extend(scope)
        source = f"""
            SELECT service, campaign, operator, nr_mode, COUNT(*) AS total, SUM(is_nq) AS nq FROM (
                SELECT p.service, p.campaign, p.operator, p.nr_mode, p.is_nq, ROW_NUMBER() OVER (
                    PARTITION BY p.call_key ORDER BY s.stage_rank DESC, s.data_date DESC, p.dataset_id DESC) AS rn
                FROM {NQ_CALL_POPULATION_TABLE} p JOIN {NQ_CALL_SOURCES_TABLE} s ON s.dataset_id = p.dataset_id
                WHERE {' AND '.join(where)}
            ) WHERE rn = 1 GROUP BY service, campaign, operator, nr_mode"""
    else:
        where.append('p.is_latest = 1')
        source = f"""
            SELECT p.service, p.campaign, p.operator, p.nr_mode, COUNT(*) AS total, SUM(p.is_nq) AS nq
            FROM {NQ_CALL_POPULATION_TABLE} p WHERE {' AND '.join(where)}
            GROUP BY p.service, p.campaign, p.operator, p.nr_mode"""
    with task_repository.connection() as connection:
        # The counts change only when the indexed CDRs do, so the same sources and scope reuse them.
        sources = tuple(tuple(row) for row in connection.execute(
            f'SELECT dataset_id, revision, synced_at FROM {NQ_CALL_SOURCES_TABLE} ORDER BY dataset_id').fetchall())
        key = (str(task_repository.db_path), sources, tuple(sorted(scope or ())), tuple(sorted(services)))
        with _rate_counts_guard:
            rows = _rate_counts_cache.get(key)
        if rows is None:
            rows = [(row['service'], row['campaign'], row['operator'], row['nr_mode'], row['total'], row['nq'])
                    for row in connection.execute(source, params).fetchall()]
            with _rate_counts_guard:
                if len(_rate_counts_cache) >= RATE_COUNTS_CACHE_SIZE:
                    _rate_counts_cache.pop(next(iter(_rate_counts_cache)))
                _rate_counts_cache[key] = rows
    groups: dict[str, dict[tuple[str, str], list[int]]] = {}
    for row_service, row_campaign, row_operator, row_nr_mode, row_total, row_nq in rows:
        campaign, operator = str(row_campaign or ''), str(mapper.map(field_kind('operator'), row_operator or '') or '')
        if campaigns and campaign not in campaigns:
            continue
        if operators and operator not in operators:
            continue
        if nr_modes and str(row_nr_mode or '') not in nr_modes:
            continue
        for service in (str(row_service), 'all'):
            cell = groups.setdefault(service, {}).setdefault((campaign, operator), [0, 0])
            cell[0] += int(row_total or 0)
            cell[1] += int(row_nq or 0)
    mapping_settings = task_repository.chart_mapping_settings()

    def matrix(service: str) -> dict[str, Any]:
        cells = groups.get(service, {})
        campaign_list = sorted({campaign for campaign, _operator in cells}, key=campaign_sort_key)
        operator_list = sorted({operator for _campaign, operator in cells}, key=lambda value: dimension_order_key(
            'operator', value, mapping_settings['operator_mapping_groups'], mapping_settings['vendor_mapping_groups']))

        def summary(total: int, nq: int) -> dict[str, Any]:
            return {'total': total, 'nq': nq, 'rate': round(nq * 100 / total, 2) if total else None}

        return {
            'service': service, 'label': 'All services' if service == 'all' else SERVICE_LABELS.get(service, service),
            'campaigns': campaign_list, 'operators': operator_list,
            # The colour of each operator in the Operator Maps, for its name.
            'operator_colors': {operator: str(group.get('color') or '') for operator in operator_list
                                if (group := mapping_group(operator, mapping_settings['operator_mapping_groups']))},
            'cells': {campaign: {operator: summary(*cells[(campaign, operator)]) for operator in operator_list
                                 if (campaign, operator) in cells} for campaign in campaign_list},
            'campaign_totals': {campaign: summary(*map(sum, zip(*(value for (row, _operator), value in cells.items()
                                                                   if row == campaign)))) for campaign in campaign_list},
            'operator_totals': {operator: summary(*map(sum, zip(*(value for (_row, column), value in cells.items()
                                                                   if column == operator)))) for operator in operator_list},
            'total': summary(*map(sum, zip(*cells.values()))) if cells else summary(0, 0),
        }

    ordered = [service for service in (*SERVICES, 'all') if service in groups]
    # "All services" adds calls and data tests: it is listed last, and only with several services.
    if len([service for service in ordered if service != 'all']) < 2:
        ordered = [service for service in ordered if service != 'all']
    return {'matrices': [matrix(service) for service in ordered], 'filters': list(RATE_FILTERS)}


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
    """A call (its latest version) or a Speech sample, with its follow-up."""
    base, params = _base_sql(default, task_repository)
    row = connection.execute(f'WITH calls AS ({base}) SELECT * FROM calls WHERE call_key = ?', [*params, call_key]).fetchone()
    if row is not None:
        return row
    sample, sample_params = _sample_sql(default, task_repository)
    return connection.execute(
        f'WITH samples AS ({sample}) SELECT * FROM samples WHERE call_key = ? ORDER BY dataset_id DESC LIMIT 1',
        [*sample_params, call_key]).fetchone()


def _call_versions(connection: Any, call_key: str) -> list[dict[str, Any]]:
    """Every CDR that contains the call: Final, Weekly or Daily, its newest data, and the call's result in it."""
    rows = connection.execute(f"""
        SELECT p.dataset_id, p.is_nq, p.is_latest, s.stage_rank, s.data_date, d.file_name, dp.dataset_kind, dp.cdr_stage,
               (SELECT c.result FROM {NQ_CALLS_TABLE} c WHERE c.call_key = p.call_key AND c.dataset_id = p.dataset_id
                ORDER BY c.start_time LIMIT 1) AS result,
               (SELECT c.failure_classification FROM {NQ_CALLS_TABLE} c WHERE c.call_key = p.call_key AND c.dataset_id = p.dataset_id
                ORDER BY c.start_time LIMIT 1) AS failure_classification
        FROM {NQ_CALL_POPULATION_TABLE} p
        JOIN {NQ_CALL_SOURCES_TABLE} s ON s.dataset_id = p.dataset_id
        LEFT JOIN datasets d ON d.id = p.dataset_id
        LEFT JOIN dataset_profiles dp ON dp.dataset_id = p.dataset_id
        WHERE p.call_key = ?
        ORDER BY s.stage_rank DESC, s.data_date DESC, p.dataset_id DESC
    """, (call_key,)).fetchall()
    return [{
        'dataset_id': int(row['dataset_id']), 'name': str(row['file_name'] or ''),
        'stage': 'Final' if int(row['stage_rank']) else CDR_STAGE_LABELS.get(
            dataset_cdr_stage(row['dataset_kind'], row['cdr_stage'], row['file_name']) or '', 'Daily'),
        'data_date': str(row['data_date'] or ''),
        'non_qualified': bool(row['is_nq']), 'latest': bool(row['is_latest']),
        'result': str(row['result'] or ('Completed' if not row['is_nq'] else '')),
        'failure_classification': str(row['failure_classification'] or ''),
    } for row in rows]


def _call_samples(connection: Any, call: dict[str, Any], default: str, task_repository: Any) -> list[dict[str, Any]]:
    """The Non-Qualified samples of a Speech call in the CDR of its shown version, with their follow-up."""
    if call.get('service') != 'speech' or call.get('parent_key'):
        return []
    sample, params = _sample_sql(default, task_repository)
    rows = connection.execute(
        f'WITH samples AS ({sample}) SELECT * FROM samples WHERE parent_key = ? AND dataset_id = ? ORDER BY start_time, source_row_id',
        [*params, call['call_key'], int(call['dataset_id'])]).fetchall()
    return [_call_payload(row) for row in rows]


def _comment_payload(row: Any) -> dict[str, Any]:
    deleted = bool(row['deleted_at'])
    return {
        'id': int(row['id']), 'body': '' if deleted else str(row['body']), 'created_by': str(row['created_by']),
        'created_at': str(row['created_at']), 'edited_by': str(row['edited_by']), 'edited_at': str(row['edited_at']),
        'deleted_by': str(row['deleted_by']), 'deleted_at': str(row['deleted_at']),
    }


def call_detail(task_repository: Any, call_key: str) -> dict[str, Any] | None:
    """A call or a Speech sample: its fields, follow-up, comments, history, CDR versions and samples."""
    options = list_options(task_repository)
    default = untracked_status(task_repository, options)
    definitions = list_fields(task_repository)
    with task_repository.connection() as connection:
        row = _call_row(connection, call_key, default, task_repository)
        if row is None:
            return None
        call = _call_payload(row)
        versions = _call_versions(connection, str(call.get('parent_key') or call_key))
        samples = _call_samples(connection, call, default, task_repository)
        learned = learned_decisions(connection)
        parent = None
        if call.get('parent_key'):
            parent_row = _call_row(connection, str(call['parent_key']), default, task_repository)
            parent = _call_payload(parent_row) if parent_row is not None else None
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
    taxonomy = list_root_causes(task_repository)
    call['suggested_root_cause'] = suggest_root_cause(call, taxonomy, notes)
    call['rca_recommendation'] = recommendation_for(call, taxonomy, notes, learned)
    # CDR columns of the catalog are read from the CDR row itself.
    source_values = {key: _text(source[key]) for key in source.keys()} if source is not None else {}
    call['extra'] = {**source_values, **(call.get('extra') or {})}
    call['values'] = {field['key']: catalog_value(field, call, call.get('rca'), call.get('fields')) for field in definitions}
    # Values of the CDR proposed for the empty fields that name one (for example the failure position).
    call['proposals'] = {field['key']: _text(_call_value(call, field['suggest_from'])) for field in definitions
                         if field['source'] == 'user' and field.get('suggest_from') and not (call.get('fields') or {}).get(field['key'])
                         and _text(_call_value(call, field['suggest_from']))}
    for sample in samples:
        sample['suggested_root_cause'] = suggest_root_cause(sample, taxonomy, '')
        sample['rca_recommendation'] = recommendation_for(sample, taxonomy, '', learned)
    return {'call': call, 'comments': comments, 'history': history, 'fields': fields, 'versions': versions,
            'samples': samples, 'parent': parent}


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
        validated['status_mode'] = 'manual'
    if changes.get('status_mode') == 'auto':
        validated.pop('status', None)
        validated['status_mode'] = 'auto'
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
    for key, plural, title in (('root_category', 'categories', 'Root Categories'), ('root_cause', 'causes', 'Root Causes')):
        if key in changes:
            names = {item['name'].casefold(): item['name'] for item in taxonomy[plural]}
            value = str(changes.get(key) or '').strip()
            if value and value.casefold() not in names:
                raise ValueError(f'Choose one of the {title} of the root cause catalog.')
            validated[key] = names.get(value.casefold(), '')
    if changes.get('apply_recommendation') or changes.get('apply_suggestion'):
        validated['apply_recommendation'] = '1'
    if not validated and not changes.get('fields'):
        raise ValueError('There is nothing to change.')
    return validated


def _validate_field_changes(changes: dict[str, Any], definitions: list[dict[str, Any]]) -> dict[str, str]:
    values = changes.get('fields')
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise ValueError('The analysis fields are invalid.')
    known = {field['key']: field for field in definitions}
    unknown = [str(key) for key in values if str(key) not in known]
    if unknown:
        raise ValueError(f'Unknown fields: {", ".join(unknown)}.')
    return {str(key): _field_value(known[str(key)], value) for key, value in values.items()}


class TrackingConflict(Exception):
    """Another user changed the call after it was loaded."""


def learned_decisions(connection: Any) -> dict[tuple[str, str, str], dict[tuple[str, str], set[str]]]:
    """For the RCA values of every call with a root category or cause, the categories and causes the analysts chose,
    with the calls that chose each one (so a call counts once and never for itself)."""
    learned: dict[tuple[str, str, str], dict[tuple[str, str], set[str]]] = {}
    rows = connection.execute(f"""
        SELECT t.call_key, t.root_category, t.root_cause, c.failure_category, c.failure_classification, c.failure_subcategory,
               COALESCE(r.values_json, '{{}}') AS rca_json
        FROM {NQ_CALL_TRACKING_TABLE} t
        JOIN {NQ_CALLS_TABLE} c ON c.call_key = t.call_key
        LEFT JOIN {NQ_RCA_RESULTS_TABLE} r ON c.join_id <> '' AND r.join_id = lower(c.join_id)
        WHERE t.root_category <> '' OR t.root_cause <> ''
        GROUP BY t.call_key
    """).fetchall()
    for row in rows:
        choice = (str(row['root_category'] or ''), str(row['root_cause'] or ''))
        try:
            rca = json.loads(row['rca_json'] or '{}')
        except (TypeError, ValueError):
            rca = {}
        pairs = [('netcheck', str(row['failure_category'] or row['failure_classification'] or ''), str(row['failure_subcategory'] or '')),
                 ('script', str(rca.get('rca_category') or rca.get('auto_rca_category_a') or ''),
                  str(rca.get('rca_cause') or rca.get('auto_rca_subcategory_a') or ''))]
        for source, category, cause in pairs:
            if category or cause:
                learned.setdefault(nq_rca.learned_key(source, category, cause), {}).setdefault(choice, set()).add(str(row['call_key']))
    return learned


def recommendation_for(call: dict[str, Any], taxonomy: dict[str, Any], comments: str,
                       learned: dict[tuple[str, str, str], dict[tuple[str, str], set[str]]]) -> dict[str, Any]:
    return nq_rca.recommend(call, call.get('rca') or {}, taxonomy, taxonomy.get('rule') or DEFAULT_ROOT_CAUSE_RULE,
                            comments, learned)


def update_tracking(
    task_repository: Any, call_keys: list[str], changes: dict[str, Any], username: str, users: set[str],
    expected_version: int | None = None,
) -> list[str]:
    """Apply follow-up and field changes; returns the calls that changed.

    A team with members only accepts them as assignees: assigning anybody else is refused, and
    moving a call to such a team clears an assignee who is not a member. ``apply_recommendation``
    gives the calls without a root category and cause the recommended ones. Choosing a status sets
    it by hand; otherwise (or after going back to automatic) the status rules set it from the
    fields. A call cannot be closed without the fields required to close it.
    """
    options = list_options(task_repository)
    taxonomy = list_root_causes(task_repository)
    definitions = list_fields(task_repository)
    validated = _validate_changes(changes, options, users, taxonomy)
    field_changes = _validate_field_changes(changes, definitions)
    required = [field for field in definitions if field['required_to_close']]
    apply_recommendation = bool(validated.pop('apply_recommendation', None))
    closed = {item['name'].casefold() for item in options['statuses'] if item['closed']}
    members = team_members(options)
    default = untracked_status(task_repository, options)
    fallback = default_status(options)
    rules = status_rules(task_repository)
    when = now_iso()
    changed: list[str] = []
    with task_repository.connection() as connection:
        learned = learned_decisions(connection) if apply_recommendation else {}
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
            if apply_recommendation:
                recommended = None
                if not current['root_category'] and not current['root_cause']:
                    call = _call_payload(row)
                    notes = _comment_texts(connection, [call_key]).get(call_key, '')
                    recommended = recommendation_for(call, taxonomy, notes, learned)['recommendation']
                if recommended:
                    current['root_category'], current['root_cause'] = recommended['category'], recommended['cause']
                elif not validated and not field_changes:
                    # Nothing to accept: the call stays as it is.
                    continue
            current['root_domain'] = domain_of(taxonomy, current['root_category'], current['root_cause'])
            # An assignee chosen alone brings the call to their team (the first one when they are in several),
            # unless the call already has a team they belong to.
            if validated.get('assignee') and 'team' not in validated:
                current_members = members.get(current['team'].casefold())
                if not current['team'] or (current_members and current['assignee'].casefold() not in current_members):
                    team = next((item['name'] for item in options['teams']
                                 if current['assignee'].casefold() in members.get(item['name'].casefold(), set())), '')
                    if team:
                        current['team'] = team
            allowed = members.get(current['team'].casefold())
            if allowed and current['assignee'] and current['assignee'].casefold() not in allowed:
                if 'assignee' in validated:
                    raise ValueError(f'{current["assignee"]} is not a member of the {current["team"]} team.')
                current['assignee'] = ''
            stored = field_values(connection, [call_key]).get(call_key, {})
            field_differences = {key: value for key, value in field_changes.items() if stored.get(key, '') != value}
            merged = {**stored, **field_changes}
            if current['status_mode'] != 'manual':
                current['status'] = evaluate_status(rules, _status_inputs(row, merged, definitions, current, True), fallback)
            differences = {field: value for field, value in current.items() if str(row[field]) != value}
            if not differences and not field_differences:
                continue
            closing = current['status'].casefold() in closed
            if (taxonomy['require_to_close'] and closing and not current['root_category']
                    and ('status' in differences or 'root_category' in differences)):
                raise ValueError(f'Choose a root category before closing a call as {current["status"]}.')
            if closing and required:
                missing = [field['label'] for field in required if not merged.get(field['key'])]
                if missing and ('status' in differences or field_differences):
                    raise ValueError(f'Fill {", ".join(missing)} before closing a call as {current["status"]}.')
            connection.execute(
                f'INSERT INTO {NQ_CALL_TRACKING_TABLE} (call_key, status, team, assignee, root_domain, root_category, root_cause, '
                'status_mode, version, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) ON CONFLICT(call_key) DO UPDATE SET '
                'status = excluded.status, team = excluded.team, assignee = excluded.assignee, '
                'root_domain = excluded.root_domain, root_category = excluded.root_category, root_cause = excluded.root_cause, '
                'status_mode = excluded.status_mode, version = version + 1, '
                'updated_by = excluded.updated_by, updated_at = excluded.updated_at',
                (call_key, current['status'], current['team'], current['assignee'], current['root_domain'],
                 current['root_category'], current['root_cause'], current['status_mode'], username, when),
            )
            automatic = current['status_mode'] != 'manual'
            for field, value in differences.items():
                # The domain follows the category and cause; a status chosen by hand tells its mode itself; a status
                # set by the rules is recorded after the changes that moved it.
                if field == 'root_domain' or (field == 'status_mode' and value == 'manual') or (field == 'status' and automatic):
                    continue
                _record_history(connection, call_key, field, str(row[field]), value, username, when)
            for key, value in field_differences.items():
                connection.execute(
                    f'INSERT INTO {NQ_FIELD_VALUES_TABLE} (call_key, field_key, value, updated_by, updated_at) VALUES (?, ?, ?, ?, ?) '
                    'ON CONFLICT(call_key, field_key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, '
                    'updated_at = excluded.updated_at', (call_key, key, value, username, when))
                _record_history(connection, call_key, f'field:{key}', stored.get(key, ''), value, username, when)
            if 'status' in differences and automatic:
                _record_history(connection, call_key, 'status_auto', str(row['status']), differences['status'], username, when)
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
        if _call_row(connection, call_key, untracked_status(task_repository, options), task_repository) is None:
            raise LookupError('The call is no longer available. Refresh the list.')
        cursor = connection.execute(
            f'INSERT INTO {NQ_CALL_COMMENTS_TABLE} (uid, call_key, body, created_by, created_at) VALUES (?, ?, ?, ?, ?)',
            (uuid.uuid4().hex, call_key, text, username, now_iso()),
        )
        row = connection.execute(f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE id = ?', (cursor.lastrowid,)).fetchone()
    # A comment attends the call: its automatic status follows.
    recompute_statuses(task_repository, username, [call_key])
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
# RCA script results: imported by JOIN_ID
# ---------------------------------------------------------------------------
def import_rca_results(task_repository: Any, content: bytes, file_name: str, username: str, *, replace: bool = False,
                       dry_run: bool = False) -> dict[str, Any]:
    """Read an RCA results file and (unless ``dry_run``) store its rows by JOIN_ID; ``replace`` forgets the previous ones."""
    parsed = nq_rca.read_rca_file(content, file_name)
    results = parsed['results']
    with task_repository.connection() as connection:
        known = {str(row[0]) for row in connection.execute(
            f"SELECT DISTINCT lower(join_id) FROM {NQ_CALLS_TABLE} WHERE join_id <> ''")}
        matched = sum(1 for item in results if item['join_id'].casefold() in known)
        existing = {str(row[0]) for row in connection.execute(f'SELECT join_id FROM {NQ_RCA_RESULTS_TABLE}')}
        summary = {
            'file_name': file_name, 'rows': len(results), 'matched': matched, 'unmatched': len(results) - matched,
            'columns': parsed['columns'], 'extra': parsed['extra'], 'skipped': parsed['skipped'], 'duplicates': parsed['duplicates'],
            'new': sum(1 for item in results if item['join_id'].casefold() not in existing),
            'replace': replace, 'preview': [{'join_id': item['join_id'], **item['values']} for item in results[:8]],
        }
        if dry_run:
            return summary
        when = now_iso()
        if replace:
            connection.execute(f'DELETE FROM {NQ_RCA_RESULTS_TABLE}')
        connection.executemany(
            f'INSERT OR REPLACE INTO {NQ_RCA_RESULTS_TABLE} (join_id, original_join_id, values_json, source_file, imported_by, imported_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            [(item['join_id'].casefold(), item['join_id'], json.dumps(item['values'], ensure_ascii=False), file_name, username, when)
             for item in results])
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_rca_import', json.dumps(
            {'file': file_name, 'rows': len(results), 'matched': matched, 'replace': replace}))
    return summary


def rca_results_summary(task_repository: Any) -> dict[str, Any]:
    """The imported RCA results: how many, how many match a call, and each imported file."""
    with task_repository.connection() as connection:
        total = connection.execute(f'SELECT COUNT(*) FROM {NQ_RCA_RESULTS_TABLE}').fetchone()[0]
        matched = connection.execute(
            f"SELECT COUNT(*) FROM {NQ_RCA_RESULTS_TABLE} r WHERE EXISTS "
            f"(SELECT 1 FROM {NQ_CALLS_TABLE} c WHERE c.join_id <> '' AND lower(c.join_id) = r.join_id)").fetchone()[0]
        files = [{'name': str(row['source_file']), 'rows': int(row['rows']), 'imported_at': str(row['imported_at']),
                  'imported_by': str(row['imported_by'])}
                 for row in connection.execute(
                     f'SELECT source_file, COUNT(*) AS rows, MAX(imported_at) AS imported_at, MAX(imported_by) AS imported_by '
                     f'FROM {NQ_RCA_RESULTS_TABLE} GROUP BY source_file ORDER BY imported_at DESC')]
    return {'total': int(total or 0), 'matched': int(matched or 0), 'files': files, 'format': nq_rca.RCA_FILE_FORMAT_HELP}


def clear_rca_results(task_repository: Any, username: str) -> int:
    with task_repository.connection() as connection:
        deleted = connection.execute(f'DELETE FROM {NQ_RCA_RESULTS_TABLE}').rowcount
    if hasattr(task_repository, 'try_add_log'):
        task_repository.try_add_log(username, 'nq_rca_clear', f'{deleted} RCA script results deleted.')
    return int(deleted or 0)


# ---------------------------------------------------------------------------
# Lifecycle and RCA insights
# ---------------------------------------------------------------------------
STALLED_DAYS = 14
PHASE_SECTIONS = ('analysis', 'implementation', 'planning')


def _filtered_calls(task_repository: Any, filters: dict[str, Any], username: str, columns: str = '*') -> tuple[list[Any], dict[str, Any]]:
    options = list_options(task_repository)
    definitions = list_fields(task_repository)
    base, base_params = _base_sql(untracked_status(task_repository, options), task_repository, _scope(filters))
    where, params = _filter_sql(_resolve_key_filters(task_repository, filters), username,
                                [item['name'] for item in options['statuses'] if item['closed']], definitions)
    with task_repository.connection() as connection:
        rows = connection.execute(f'WITH calls AS ({base}) SELECT {columns} FROM calls{where}', [*base_params, *params]).fetchall()
    return rows, {'options': options, 'definitions': definitions}


def lifecycle_stats(task_repository: Any, filters: dict[str, Any], username: str) -> dict[str, Any]:
    """Where the filtered calls are in their follow-up: the status pipeline, how the statuses were set, the
    phase fields, the time spent in each status, the most frequent moves and the calls without recent changes."""
    rows, context = _filtered_calls(task_repository, filters, username,
                                    'call_key, start_time, status, status_mode, updated_at, comment_count, field_values_json, '
                                    'service, test_name, session_type, operator, campaign, city, root_category, root_cause')
    options, definitions = context['options'], context['definitions']
    statuses = options['statuses']
    closed = {item['name'].casefold() for item in statuses if item['closed']}
    now = datetime.now()
    counts: Counter = Counter()
    ages: dict[str, list[float]] = {}
    modes: Counter = Counter()
    stalled = []
    keys = [str(row['call_key']) for row in rows]
    for row in rows:
        status = str(row['status'] or '')
        counts[status] += 1
        modes[str(row['status_mode'] or 'auto')] += 1
        started = _parse_time(row['start_time'])
        if started is not None:
            ages.setdefault(status, []).append((now - started).total_seconds() / 86400)
        if status.casefold() not in closed:
            last = _parse_time(row['updated_at']) or started
            if last is not None and (now - last).days >= STALLED_DAYS:
                stalled.append({'call_key': str(row['call_key']), 'status': status, 'operator': str(row['operator'] or ''),
                                'campaign': str(row['campaign'] or ''), 'city': str(row['city'] or ''),
                                'days': int((now - last).total_seconds() // 86400), 'followed_up': bool(row['updated_at'])})
    pipeline = [{'status': item['name'], 'color': item['color'], 'closed': item['closed'], 'count': counts.get(item['name'], 0),
                 'avg_age_days': round(sum(ages.get(item['name'], [])) / len(ages[item['name']]), 1) if ages.get(item['name']) else None}
                for item in statuses]
    pipeline += [{'status': name, 'color': '', 'closed': False, 'count': count, 'avg_age_days': None}
                 for name, count in counts.items() if name not in {item['name'] for item in statuses}]
    phases = []
    for field in definitions:
        if field['section'] not in PHASE_SECTIONS or field['type'] != 'list' or field['source'] not in {'user', 'derived'}:
            continue
        values: Counter = Counter()
        for row in rows:
            try:
                stored = json.loads(row['field_values_json'] or '{}') or {}
            except (TypeError, ValueError):
                stored = {}
            values[stored.get(field['key'], '') if field['source'] == 'user' else derived_value(field, row)] += 1
        phases.append({'key': field['key'], 'label': field['label'], 'section': field['section'], 'empty': values.pop('', 0),
                       'items': [{'value': option['name'], 'count': values.get(option['name'], 0), 'color': option['color']}
                                 for option in field['options']]})
    durations: dict[str, list[float]] = {}
    moves: Counter = Counter()
    with task_repository.connection() as connection:
        history: dict[str, list[Any]] = {}
        for entry in _rows_of_calls(connection, f'SELECT id, call_key, old_value, new_value, changed_at FROM {NQ_CALL_HISTORY_TABLE}',
                                    keys, where="field IN ('status', 'status_auto')", order='changed_at, id'):
            history.setdefault(str(entry['call_key']), []).append(entry)
    starts = {str(row['call_key']): _parse_time(row['start_time']) for row in rows}
    for key, entries in history.items():
        previous = starts.get(key)
        for entry in entries:
            moment = _parse_time(entry['changed_at'])
            moves[(str(entry['old_value'] or '—'), str(entry['new_value'] or '—'))] += 1
            if previous is not None and moment is not None and moment >= previous:
                durations.setdefault(str(entry['old_value'] or ''), []).append((moment - previous).total_seconds() / 86400)
            previous = moment or previous
    time_in_status = [{'status': name, 'avg_days': round(sum(values) / len(values), 1), 'moves': len(values)}
                      for name, values in durations.items() if name]
    order = [item['name'] for item in statuses]
    time_in_status.sort(key=lambda item: order.index(item['status']) if item['status'] in order else len(order))
    stalled.sort(key=lambda item: -item['days'])
    identified = sum(1 for row in rows if row['root_category'] or row['root_cause'])
    return {
        'total': len(rows), 'pipeline': pipeline, 'modes': {'auto': modes.get('auto', 0), 'manual': modes.get('manual', 0)},
        'rca': {'identified': identified, 'not_identified': len(rows) - identified},
        'phases': phases, 'time_in_status': time_in_status,
        'moves': [{'from': old, 'to': new, 'count': count} for (old, new), count in moves.most_common(12)],
        'stalled_days': STALLED_DAYS, 'stalled_total': len(stalled), 'stalled': stalled[:15],
        'rules': status_rules(task_repository),
    }


def rca_insights(task_repository: Any, filters: dict[str, Any], username: str) -> dict[str, Any]:
    """The three root cause sources of the filtered calls compared: how many calls each one covers, how often they
    agree, their category → cause hierarchies and how the analysts' choices relate to each RCA."""
    rows, _context = _filtered_calls(task_repository, filters, username,
                                     'call_key, rca_json, failure_classification, failure_category, failure_subcategory, '
                                     'failure_comment, technology, failure_technology, root_domain, root_category, root_cause')
    taxonomy = list_root_causes(task_repository)
    rule = taxonomy.get('rule') or DEFAULT_ROOT_CAUSE_RULE
    # NetCheck alone: the CDR fields, never the comments.
    cdr_rule = {**rule, 'comments': False, 'comment_domain': False}
    colors = {item['name']: item['color'] for item in taxonomy['domains']}
    coverage = Counter()
    agreement = {name: Counter() for name in ('selected_script', 'selected_netcheck', 'script_netcheck')}
    hierarchies: dict[str, dict[str, Counter]] = {'script': {}, 'netcheck': {}, 'selected': {}}
    confusion: dict[str, Counter] = {'script': Counter(), 'netcheck': Counter()}
    domains: Counter = Counter()
    mapped_counts: dict[str, Counter] = {'script': Counter(), 'netcheck': Counter(), 'selected': Counter()}
    for row in rows:
        try:
            rca = json.loads(row['rca_json'] or '{}') or {}
        except (TypeError, ValueError):
            rca = {}
        script_raw = (str(rca.get('rca_category') or rca.get('auto_rca_category_a') or ''),
                      str(rca.get('rca_cause') or rca.get('auto_rca_subcategory_a') or ''))
        netcheck_raw = (str(row['failure_category'] or row['failure_classification'] or ''), str(row['failure_subcategory'] or ''))
        selected = (str(row['root_category'] or ''), str(row['root_cause'] or ''))
        script = nq_rca.map_to_catalog(*script_raw, taxonomy, rule.get('match', 'words')) if any(script_raw) else None
        netcheck = nq_rca.suggest_from_text(row, taxonomy, cdr_rule) if any(netcheck_raw) else None
        coverage['total'] += 1
        if script is not None:
            coverage['script'] += 1
            hierarchies['script'].setdefault(script_raw[0] or '—', Counter())[script_raw[1] or '—'] += 1
            mapped_counts['script'][script['category'] or '—'] += 1
        if any(netcheck_raw):
            coverage['netcheck'] += 1
            hierarchies['netcheck'].setdefault(netcheck_raw[0] or '—', Counter())[netcheck_raw[1] or '—'] += 1
            mapped_counts['netcheck'][(netcheck or {}).get('category') or '—'] += 1
        if any(selected):
            coverage['selected'] += 1
            domain = str(row['root_domain'] or '') or domain_of(taxonomy, *selected) or NOT_CLASSIFIED
            domains[domain] += 1
            hierarchies['selected'].setdefault(selected[0] or '—', Counter())[selected[1] or '—'] += 1
            mapped_counts['selected'][selected[0] or '—'] += 1
            for source, mapped in (('script', script), ('netcheck', netcheck)):
                if mapped and (mapped.get('category') or mapped.get('cause')):
                    confusion[source][(mapped.get('category') or '—', selected[0] or '—')] += 1
                    target = agreement[f'selected_{source}']
                    target['compared'] += 1
                    same = (mapped.get('category') and mapped['category'] == selected[0]) or \
                        (not mapped.get('category') and mapped.get('cause') and mapped['cause'] == selected[1])
                    target['agree'] += int(bool(same))
        if script and netcheck and (script.get('category') or netcheck.get('category')):
            agreement['script_netcheck']['compared'] += 1
            agreement['script_netcheck']['agree'] += int(bool(script.get('category')) and script.get('category') == netcheck.get('category'))

    def hierarchy(name: str, limit: int = 12) -> list[dict[str, Any]]:
        groups = hierarchies[name]
        ordered = sorted(groups.items(), key=lambda item: -sum(item[1].values()))[:limit]
        return [{'category': category, 'count': sum(causes.values()),
                 'causes': [{'cause': cause, 'count': count} for cause, count in causes.most_common(8)]} for category, causes in ordered]

    def matrix(source: str) -> dict[str, Any]:
        cells = confusion[source]
        totals_rows = Counter()
        totals_columns = Counter()
        for (row_name, column_name), count in cells.items():
            totals_rows[row_name] += count
            totals_columns[column_name] += count
        rows_order = [name for name, _count in totals_rows.most_common(10)]
        columns_order = [name for name, _count in totals_columns.most_common(10)]
        return {'rows': rows_order, 'columns': columns_order,
                'cells': [[cells.get((row_name, column_name), 0) for column_name in columns_order] for row_name in rows_order]}

    def rate(name: str) -> dict[str, Any]:
        target = agreement[name]
        return {'agree': target['agree'], 'compared': target['compared'],
                'rate': round(target['agree'] * 100 / target['compared'], 1) if target['compared'] else None}

    return {
        'coverage': {key: coverage.get(key, 0) for key in ('total', 'script', 'netcheck', 'selected')},
        'agreement': {name: rate(name) for name in agreement},
        'hierarchies': {name: hierarchy(name) for name in hierarchies},
        'mapped': {name: [{'category': category, 'count': count} for category, count in counts.most_common(12)]
                   for name, counts in mapped_counts.items()},
        'domains': [{'domain': name, 'count': count, 'color': colors.get(name, '#b8c0c6')} for name, count in domains.most_common()],
        'confusion': {source: matrix(source) for source in confusion},
        'rca_results': rca_results_summary(task_repository),
    }


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
# The call itself, before the catalog fields: what identifies the call and what the CDR says about it.
# JOIN_ID, the call key and its CDR first, to find a call at once.
EXPORT_COLUMNS = (
    ('JOIN_ID', 'join_id'), ('Call Key', 'call_key'), ('CDR', 'dataset_name'), ('Service', 'service_label'), ('Start Time', 'start_time'), ('End Time', 'end_time'), ('Operator', 'operator'),
    ('Operator_Vendor', 'operator_vendor'), ('Vendor_Operator', 'vendor_operator'), ('Vendor', 'vendor'),
    ('Campaign', 'campaign'), ('NR Mode', 'nr_mode'), ('Region', 'region'), ('Cluster', 'cluster'), ('City', 'city'),
    ('Technology', 'technology'), ('Test Name', 'test_name'), ('Session Type (CDR)', 'session_type'), ('Direction', 'direction'),
    ('Result', 'result'), ('Failure Phase', 'failure_phase'), ('Failure Technology', 'failure_technology'),
    ('Cell ID', 'cell_id'), ('Latitude', 'latitude'), ('Longitude', 'longitude'),
    ('CDR Version', 'version_label'), ('Latest CDR', 'latest_dataset_name'),
    ('NQ Samples', 'nq_samples'),
)
CALL_SECTION = {'key': 'call', 'label': 'Call', 'color': '#5E6B75'}
# Columns of the export that follow a follow-up field: (field reference, label, value key).
EXPORT_COMPANIONS = {'status': [('Status Set', 'status_set')]}
# Columns that come before the selected root category (or cause): the root cause decision ends the RCA block.
EXPORT_ROOT_COMPANIONS = [('Root Domain', 'root_domain'), ('Recommended Root Category', 'recommended_category'),
                          ('Recommended Root Cause', 'recommended_cause'), ('Recommendation Sources', 'recommendation_sources')]
# Header shades: the status of each block darker than its section, the fields of the analysts and the follow-up light,
# the values from the CDR, the RCA script or derived lighter.
KEY_FIELD_TINT = -0.2
EDITABLE_FIELD_TINT = 0.35
COMPUTED_FIELD_TINT = 0.65


def _tint(color: str, amount: float) -> str:
    """A lighter shade of a colour (amount 0 keeps it, 1 is white; below 0 darker), as RRGGBB."""
    value = int(color.lstrip('#'), 16) if nq_catalog.COLOR_PATTERN.fullmatch(color or '') else 0x7B8790
    channels = [(value >> shift) & 255 for shift in (16, 8, 0)]
    if amount < 0:
        return ''.join(f'{round(channel * (1 + amount)):02X}' for channel in channels)
    return ''.join(f'{round(channel + (255 - channel) * amount):02X}' for channel in channels)


def key_fields(definitions: list[dict[str, Any]]) -> set[str]:
    """The status field of each block: the NQ Call Status and the first list of Analysis, Implementation and Planning."""
    keys = {field['key'] for field in definitions if field['source'] == 'tracking' and field['source_ref'] == 'status'}
    for section in PHASE_SECTIONS:
        first = next((field for field in definitions if field['section'] == section and field['type'] == 'list'
                      and field['source'] in {'user', 'derived'}), None)
        if first:
            keys.add(first['key'])
    return keys


def _comment_log(rows: list[Any]) -> str:
    """Every comment of a call, one per line: date and time, author and text."""
    lines = []
    for row in rows:
        if row['deleted_at']:
            continue
        moment = str(row['created_at'] or '').replace('T', ' ')[:16]
        lines.append(f"{moment} · {row['created_by']}: {str(row['body']).strip()}")
    return '\n'.join(lines)


def export_workbook(task_repository: Any, filters: dict[str, Any], username: str) -> bytes:
    """Every call that matches the filters with its catalog fields by section, its comments and its change history."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    options = list_options(task_repository)
    definitions = list_fields(task_repository)
    sections = {section['key']: section for section in list_sections(task_repository)}
    closed = [item['name'] for item in options['statuses'] if item['closed']]
    default = untracked_status(task_repository, options)
    base, base_params = _base_sql(default, task_repository, _scope(filters))
    where, params = _filter_sql(_resolve_key_filters(task_repository, filters), username, closed, definitions)
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
        sample_sql, sample_params = _sample_sql(default, task_repository)
        samples = [_call_payload(row) for row in connection.execute(
            f'WITH samples AS ({sample_sql}) SELECT * FROM samples WHERE parent_key IN (SELECT value FROM json_each(?)) '
            'ORDER BY parent_key, start_time',
            [*sample_params, json.dumps([call['call_key'] for call in calls if call['service'] == 'speech'])]).fetchall()]
        sample_keys = [sample['call_key'] for sample in samples]
        for start in range(0, len(sample_keys), 500):
            chunk = sample_keys[start:start + 500]
            marks = ', '.join('?' for _ in chunk)
            comments.extend(connection.execute(
                f'SELECT * FROM {NQ_CALL_COMMENTS_TABLE} WHERE call_key IN ({marks}) ORDER BY id', chunk).fetchall())
            history.extend(connection.execute(
                f'SELECT * FROM {NQ_CALL_HISTORY_TABLE} WHERE call_key IN ({marks}) ORDER BY id', chunk).fetchall())
        learned = learned_decisions(connection)
    by_key = {call['call_key']: call for call in calls}
    by_key.update({sample['call_key']: sample for sample in samples})
    taxonomy = list_root_causes(task_repository)
    per_call: dict[str, list[Any]] = {}
    for row in comments:
        per_call.setdefault(str(row['call_key']), []).append(row)
    for call in [*calls, *samples]:
        notes = '\n'.join(str(row['body']) for row in per_call.get(call['call_key'], []) if not row['deleted_at'])
        recommendation = recommendation_for(call, taxonomy, notes, learned)['recommendation'] or {}
        call['values'] = {field['key']: catalog_value(field, call, call.get('rca'), call.get('fields')) for field in definitions}
        call['comment_log'] = _comment_log(per_call.get(call['call_key'], []))
        call['status_set'] = 'By hand' if call.get('status_mode') == 'manual' else 'Automatic'
        call['recommended_category'] = recommendation.get('category', '')
        call['recommended_cause'] = recommendation.get('cause', '')
        call['recommendation_sources'] = ', '.join(nq_rca.SOURCE_LABELS.get(name, name) for name in recommendation.get('sources') or [])
        call['dataset_name'] = names.get(int(call['dataset_id']), '')
        call['latest_dataset_name'] = names.get(int(call.get('latest_dataset_id') or call['dataset_id']), '')
        call['version_label'] = VERSION_LABELS.get(call.get('version_state') or 'current', '')

    # (section, label, getter, tint): the call columns, the catalog in its order, the CDR columns and the keys.
    columns: list[tuple[dict[str, str], str, Callable[[dict[str, Any]], Any], float]] = [
        (CALL_SECTION, label, (lambda call, key=key: call.get(key)), 0.75) for label, key in EXPORT_COLUMNS]
    exported = [field for field in definitions if field.get('in_export', True)]
    highlighted = key_fields(definitions)
    # The recommendation goes right before the selected root category (or cause, without the category).
    selected = next((field['key'] for field in exported if field['source'] == 'tracking'
                     and field['source_ref'] in {'root_category', 'root_cause'}), None)
    for field in exported:
        section = sections.get(field['section'], CALL_SECTION)
        tint = KEY_FIELD_TINT if field['key'] in highlighted else \
            EDITABLE_FIELD_TINT if field['source'] in {'user', 'tracking'} else COMPUTED_FIELD_TINT
        if field['key'] == selected:
            columns += [(section, label, lambda call, key=key: call.get(key, ''), COMPUTED_FIELD_TINT)
                        for label, key in EXPORT_ROOT_COMPANIONS]
        if field['source'] == 'tracking' and field['source_ref'] == 'comments':
            columns.append((section, field['label'], lambda call: call.get('comment_log', ''), tint))
        elif field['source'] == 'tracking' and field['source_ref'] == 'updated_at':
            columns.append((section, field['label'], lambda call: str(call.get('updated_at') or '').replace('T', ' ')[:19], tint))
        else:
            columns.append((section, field['label'], lambda call, key=field['key']: call['values'].get(key, ''), tint))
        if field['source'] == 'tracking':
            for label, key in EXPORT_COMPANIONS.get(field['source_ref'], []):
                columns.append((section, label, lambda call, key=key: call.get(key, ''), COMPUTED_FIELD_TINT))
    extra_section = {'key': 'cdr', 'label': 'CDR Columns', 'color': '#5E6B75'}
    columns += [(extra_section, name, (lambda call, name=name: (call.get('extra') or {}).get(name, '')), 0.8)
                for name in indexed_cdr_columns(task_repository)
                if not any(field['source'] == 'cdr' and field['source_ref'] == f'column:{name}' for field in definitions)]
    columns += [(CALL_SECTION, 'Updated By', lambda call: call.get('updated_by', ''), 0.75),
                (CALL_SECTION, 'Updated At', lambda call: str(call.get('updated_at') or '').replace('T', ' ')[:19], 0.75)]

    workbook = Workbook()
    thin = Side(style='thin', color='FFFFFF')
    sheet = workbook.active
    sheet.title = 'NQ Calls'
    # Row 1: the sections, merged over their columns; row 2: the fields, in a lighter shade of their section.
    position = 1
    while position <= len(columns):
        section = columns[position - 1][0]
        end = position
        while end < len(columns) and columns[end][0] is section:
            end += 1
        cell = sheet.cell(1, position, section['label'].upper())
        cell.font = Font(bold=True, color=nq_catalog.contrast_color(section['color']))
        cell.fill = PatternFill('solid', fgColor=section['color'].lstrip('#'))
        cell.alignment = Alignment(horizontal='center', vertical='center')
        if end > position:
            sheet.merge_cells(start_row=1, start_column=position, end_row=1, end_column=end)
        position = end + 1
    for index, (section, label, _getter, tint) in enumerate(columns, start=1):
        cell = sheet.cell(2, index, label)
        shade = _tint(section['color'], tint)
        cell.fill = PatternFill('solid', fgColor=shade)
        cell.font = Font(bold=True, color=nq_catalog.contrast_color(f'#{shade}'))
        cell.alignment = Alignment(wrap_text=True, vertical='center')
        cell.border = Border(left=thin, right=thin)
        sheet.column_dimensions[get_column_letter(index)].width = max(12, min(48, len(label) + 6))
    for call in calls:
        sheet.append([_excel_value(getter(call)) for _section, _label, getter, _tint_value in columns])
    sheet.freeze_panes = 'A3'
    sheet.row_dimensions[2].height = 32
    if calls:
        sheet.auto_filter.ref = f'A2:{get_column_letter(len(columns))}{len(calls) + 2}'
    log_columns = [index for index, (_section, label, _getter, _tint_value) in enumerate(columns, start=1)
                   if any(field['source_ref'] == 'comments' and field['label'] == label for field in definitions)]
    for index in log_columns:
        sheet.column_dimensions[get_column_letter(index)].width = 70
        for cell in sheet.iter_rows(min_row=3, min_col=index, max_col=index):
            cell[0].alignment = Alignment(wrap_text=True, vertical='top')

    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='9C1C47')

    def write_sheet(target, headers: list[str], data: list[list[Any]], widths: list[int]) -> None:
        target.append(headers)
        for cell in target[1]:
            cell.font, cell.fill = header_font, header_fill
            cell.alignment = Alignment(vertical='center')
        for values in data:
            target.append([_excel_value(value) for value in values])
        target.freeze_panes = 'A2'
        if data:
            target.auto_filter.ref = target.dimensions
        for index, width in enumerate(widths, start=1):
            target.column_dimensions[get_column_letter(index)].width = width

    if samples:
        # Speech samples with their own follow-up, below the call they belong to.
        sample_columns = [('Call Start Time', lambda sample: by_key.get(str(sample['parent_key']), {}).get('start_time', '')),
                          ('Operator', lambda sample: sample.get('operator')), ('Campaign', lambda sample: sample.get('campaign')),
                          ('Sample', lambda sample: sample.get('sample_id')), ('Start Time', lambda sample: sample.get('start_time')),
                          ('Result', lambda sample: sample.get('result')),
                          *((field['label'], lambda sample, key=field['key']: sample['values'].get(key, ''))
                            for field in definitions if field.get('in_export', True) and field['source_ref'] != 'comments'),
                          ('Comments', lambda sample: sample.get('comment_log', '')),
                          ('Call Key', lambda sample: sample.get('parent_key')), ('Sample Key', lambda sample: sample.get('call_key'))]
        write_sheet(workbook.create_sheet('Speech Samples'), [label for label, _getter in sample_columns],
                    [[getter(sample) for _label, getter in sample_columns] for sample in samples],
                    [max(12, min(40, len(label) + 6)) for label, _getter in sample_columns])

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
        [[*call_context(str(row['call_key'])), history_label(str(row['field']), definitions),
          row['old_value'], row['new_value'], row['changed_by'], row['changed_at'], row['call_key']] for row in history],
        [10, 16, 16, 24, 18, 40, 40, 16, 26, 28],
    )
    for target in workbook.worksheets[1:]:
        for row in target.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _excel_value(value: Any) -> Any:
    if value is None:
        return ''
    if isinstance(value, str) and value.startswith('='):
        # Text that would be written as a formula.
        return "'" + value
    return value


HISTORY_LABELS = {
    'status': 'Status', 'status_auto': 'Status (automatic)', 'status_mode': 'Status set', 'team': 'Team', 'assignee': 'Assignee',
    'root_domain': 'Root Domain', 'root_category': 'Root Category', 'root_cause': 'Root Cause',
    'comment_edit': 'Comment edited', 'comment_delete': 'Comment deleted',
}


def history_label(field: str, definitions: list[dict[str, Any]]) -> str:
    if field.startswith('field:'):
        key = field[6:]
        return next((item['label'] for item in definitions if item['key'] == key), key)
    return HISTORY_LABELS.get(field, field)


# ---------------------------------------------------------------------------
# Portability: export, import, transfers and backups
# ---------------------------------------------------------------------------
def export_tracking_document(task_repository: Any) -> bytes:
    """The statuses, teams, follow-up, comments and history of a workspace."""
    ensure_nq_tables(task_repository)
    with task_repository.connection() as connection:
        tracking = [dict(row) for row in connection.execute(
            f'SELECT call_key, status, status_mode, team, assignee, root_domain, root_category, root_cause, version, updated_by, '
            f'updated_at FROM {NQ_CALL_TRACKING_TABLE} ORDER BY call_key')]
        rca_results = [dict(row) for row in connection.execute(
            f'SELECT original_join_id AS join_id, values_json, source_file, imported_by, imported_at '
            f'FROM {NQ_RCA_RESULTS_TABLE} ORDER BY join_id')]
        comments = [dict(row) for row in connection.execute(
            f'SELECT uid, call_key, body, created_by, created_at, edited_by, edited_at, deleted_by, deleted_at '
            f'FROM {NQ_CALL_COMMENTS_TABLE} ORDER BY id')]
        history = [dict(row) for row in connection.execute(
            f'SELECT uid, call_key, field, old_value, new_value, changed_by, changed_at FROM {NQ_CALL_HISTORY_TABLE} ORDER BY id')]
        values = [dict(row) for row in connection.execute(
            f"SELECT call_key, field_key, value, updated_by, updated_at FROM {NQ_FIELD_VALUES_TABLE} "
            "ORDER BY call_key, field_key")]
    document = {
        'format': TRACKING_FORMAT, 'version': TRACKING_FORMAT_VERSION, **_configuration(task_repository),
        'tracking': tracking, 'comments': comments, 'history': history, 'field_values': values, 'rca_results': rca_results,
    }
    return json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')


def _configuration(task_repository: Any) -> dict[str, Any]:
    return {
        'options': list_options(task_repository), 'root_causes': list_root_causes(task_repository),
        'fields': list_fields(task_repository), 'sections': list_sections(task_repository),
        'status_rules': status_rules(task_repository), 'table_columns': table_columns(task_repository),
    }


def export_configuration_document(task_repository: Any) -> bytes:
    """The Analysis Center configuration of a workspace, without the follow-up of its calls."""
    ensure_nq_tables(task_repository)
    document = {'format': CONFIGURATION_FORMAT, 'version': CONFIGURATION_FORMAT_VERSION, **_configuration(task_repository)}
    return json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')


def import_configuration_document(task_repository: Any, payload: bytes | str) -> None:
    """Merge an Analysis Center configuration like the configuration part of a tracking document."""
    document = json.loads(payload.decode('utf-8') if isinstance(payload, bytes) else payload)
    if not isinstance(document, dict) or document.get('format') != CONFIGURATION_FORMAT:
        raise ValueError('The file is not a Non-Qualified Calls configuration export.')
    if int(document.get('version') or 0) > CONFIGURATION_FORMAT_VERSION:
        raise ValueError('The Non-Qualified Calls configuration export was created by a newer version.')
    ensure_nq_tables(task_repository)
    _merge_configuration(task_repository, document)


def _incoming_root_catalog(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The root cause catalog of a tracking document; the first version listed causes inside their domains."""
    root = document.get('root_causes') if isinstance(document.get('root_causes'), dict) else {}
    catalog: dict[str, list[dict[str, Any]]] = {'domains': [], 'categories': [], 'causes': []}
    for domain in root.get('domains') or []:
        if not isinstance(domain, dict) or not domain.get('name'):
            continue
        catalog['domains'].append({'name': domain['name'], 'color': domain.get('color') or '', 'keywords': domain.get('keywords') or []})
        for cause in domain.get('causes') or []:
            if isinstance(cause, dict) and cause.get('name'):
                catalog['causes'].append({'name': cause['name'], 'domain': domain['name'], 'keywords': cause.get('keywords') or []})
    for plural in ('categories', 'causes'):
        catalog[plural] += [item for item in root.get(plural) or [] if isinstance(item, dict) and item.get('name')]
    return catalog


def _merge_configuration(task_repository: Any, document: dict[str, Any]) -> None:
    """Add the missing statuses, teams, fields, list values and root cause catalog entries of a document and take its
    sections and status rules (the table columns, suggestion rule and Require setting only where the workspace has none)."""
    options = document.get('options') if isinstance(document.get('options'), dict) else {}
    # Missing fields are added (in their section) and the values of the list fields are merged.
    incoming_fields = [item for item in document.get('fields') or [] if isinstance(item, dict) and item.get('key') and item.get('label')]
    if incoming_fields:
        current_fields = list_fields(task_repository)
        by_key = {field['key']: field for field in current_fields}
        labels = {field['label'].casefold() for field in current_fields}
        refs = {field['source_ref'] for field in current_fields if field['source'] == 'tracking'}
        merged = [dict(field) for field in current_fields]
        for item in incoming_fields:
            target = next((field for field in merged if field['key'] == item['key']), None)
            if target is None:
                if (str(item['label']).casefold() in labels or str(item.get('type')) not in FIELD_TYPES
                        or (item.get('source') == 'tracking' and item.get('source_ref') in refs)):
                    continue
                merged.append({**item, 'options': [option for option in item.get('options') or [] if isinstance(option, dict)]})
                continue
            if target['type'] == 'list' and str(item.get('type')) == 'list' and target['source'] in {'user', 'derived'}:
                names = {option['name'].casefold() for option in target['options']}
                target['options'] = [*target['options'], *(
                    option for option in item.get('options') or []
                    if isinstance(option, dict) and str(option.get('name') or '').casefold() not in names)]
        if merged != current_fields:
            _store_fields(task_repository, nq_catalog.normalize_fields(merged, by_key, CATALOG_CALL_FIELDS))
    if isinstance(document.get('sections'), list):
        task_repository.set_workspace_state(SECTIONS_STATE_KEY, json.dumps(nq_catalog.normalize_sections(document['sections'])))
    columns = document.get('table_columns')
    if isinstance(columns, dict) and not task_repository.get_workspace_state(TABLE_COLUMNS_STATE_KEY):
        try:
            save_table_columns(task_repository, columns.get('builtin') or [], columns.get('cdr') or [], 'import')
        except ValueError:
            pass
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
        incoming = _incoming_root_catalog(document)
        if any(incoming.values()):
            current = _read_root_catalog(connection)
            for plural in ('domains', 'categories', 'causes'):
                names = {item['name'].casefold() for item in current[plural]}
                current[plural] += [item for item in incoming[plural] if str(item['name']).casefold() not in names]
            _write_root_catalog(connection, nq_catalog.normalize_root_catalog(current))
    root_causes = document.get('root_causes') if isinstance(document.get('root_causes'), dict) else {}
    if isinstance(root_causes.get('rule'), dict) and not task_repository.get_workspace_state(ROOT_CAUSE_RULE_STATE_KEY):
        try:
            task_repository.set_workspace_state(ROOT_CAUSE_RULE_STATE_KEY, json.dumps(normalize_root_cause_rule(root_causes['rule'])))
        except ValueError:
            pass
    if root_causes.get('require_to_close') and not task_repository.get_workspace_state(ROOT_CAUSE_SETTINGS_STATE_KEY):
        task_repository.set_workspace_state(ROOT_CAUSE_SETTINGS_STATE_KEY, json.dumps({'require_to_close': True}))
    if isinstance(document.get('status_rules'), list):
        try:
            rules = nq_catalog.normalize_status_rules(document['status_rules'], [item['name'] for item in list_options(task_repository)['statuses']],
                                                      list_fields(task_repository))
            task_repository.set_workspace_state(STATUS_RULES_STATE_KEY, json.dumps(rules, ensure_ascii=False))
        except ValueError:
            pass


def import_tracking_document(task_repository: Any, payload: bytes | str) -> int:
    """Merge a tracking document; returns the number of calls whose follow-up was added or updated.

    Missing statuses, teams, fields, list values and root cause catalog entries are added, the
    sections and status rules of the document are taken, newer follow-up replaces older follow-up,
    and comments, history entries and RCA results are added once, so importing the same document
    again changes nothing.
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

    tracking, comments, history = records('tracking'), records('comments'), records('history')
    value_records, rca_records = records('field_values'), records('rca_results')
    touched: set[str] = set()
    _merge_configuration(task_repository, document)
    with task_repository.connection() as connection:
        for item in tracking:
            call_key = _text(item.get('call_key'))
            if not call_key:
                continue
            existing = connection.execute(
                f'SELECT updated_at FROM {NQ_CALL_TRACKING_TABLE} WHERE call_key = ?', (call_key,)).fetchone()
            incoming_at = _text(item.get('updated_at'))
            if existing is not None and str(existing['updated_at']) >= incoming_at:
                continue
            mode = 'manual' if _text(item.get('status_mode')) == 'manual' or (
                'status_mode' not in item and _text(item.get('status')) not in {'', 'Open'}) else 'auto'
            connection.execute(
                f'INSERT OR REPLACE INTO {NQ_CALL_TRACKING_TABLE} (call_key, status, status_mode, team, assignee, root_domain, '
                'root_category, root_cause, version, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (call_key, _text(item.get('status')), mode, _text(item.get('team')), _text(item.get('assignee')),
                 _text(item.get('root_domain')), _text(item.get('root_category')), _text(item.get('root_cause')),
                 int(item.get('version') or 1), _text(item.get('updated_by')), incoming_at),
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
        for item in value_records:
            call_key, field_key = _text(item.get('call_key')), _text(item.get('field_key'))
            if not call_key or not field_key:
                continue
            existing = connection.execute(
                f'SELECT updated_at FROM {NQ_FIELD_VALUES_TABLE} WHERE call_key = ? AND field_key = ?', (call_key, field_key),
            ).fetchone()
            incoming_at = _text(item.get('updated_at'))
            if existing is not None and str(existing['updated_at']) >= incoming_at:
                continue
            connection.execute(
                f'INSERT OR REPLACE INTO {NQ_FIELD_VALUES_TABLE} (call_key, field_key, value, updated_by, updated_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (call_key, field_key, str(item.get('value') or ''), _text(item.get('updated_by')) or 'import', incoming_at))
            touched.add(call_key)
        for item in rca_records:
            join_id = _text(item.get('join_id'))
            if not join_id:
                continue
            existing = connection.execute(
                f'SELECT imported_at FROM {NQ_RCA_RESULTS_TABLE} WHERE join_id = ?', (join_id.casefold(),)).fetchone()
            incoming_at = _text(item.get('imported_at'))
            if existing is not None and str(existing['imported_at']) >= incoming_at:
                continue
            values = item.get('values_json')
            connection.execute(
                f'INSERT OR REPLACE INTO {NQ_RCA_RESULTS_TABLE} (join_id, original_join_id, values_json, source_file, imported_by, '
                'imported_at) VALUES (?, ?, ?, ?, ?, ?)',
                (join_id.casefold(), join_id, values if isinstance(values, str) else json.dumps(values or {}, ensure_ascii=False),
                 _text(item.get('source_file')), _text(item.get('imported_by')) or 'import', incoming_at))
    if touched:
        recompute_statuses(task_repository, 'import', list(touched))
    return len(touched)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def install_non_qualified_calls_routes(core: Any) -> None:
    from fastapi import Depends, HTTPException, Request

    def index_when_idle() -> None:
        """Index the new, changed or removed CDRs of the active workspace once nobody has used the server for a while,
        if the module has been opened there."""
        workspace = core.active_workspace
        if not workspace:
            return
        repository = core.Repository(workspace.database_path, global_db_path=core.repository.global_db_path,
                                     workspace_registry_db_path=core.workspace_registry.registry_path)
        with repository.connection() as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                                      (NQ_CALL_SOURCES_TABLE,)).fetchone():
                return
        status = nq_index_status(repository)
        if status['pending'] and not status['indexing']:
            start_nq_index(repository, core.submit_background_task)

    def index_tasks(workspace: Any) -> list[dict[str, Any]]:
        job = nq_index_job(workspace.database_path)
        if not job or (job['status'] in {'ready', 'failed'} and time.time() - (job['finished_at'] or 0) > 5):
            return []
        detail = 'Indexing the calls of every CDR again' if job['force'] else 'Indexing the calls of new or changed CDRs'
        return [{
            'id': f'nq-index:{workspace.id}', 'label': 'Non-Qualified Calls indexing',
            'detail': job['error'] or detail, 'status': job['status'], 'progress': None,
            'queued_at': job['queued_at'], 'started_at': job['started_at'], 'completed_at': job['finished_at'],
        }]

    core.register_idle_task(index_when_idle, NQ_INDEX_IDLE_SECONDS)
    core.BACKGROUND_TASK_PROVIDERS.append(index_tasks)
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from pydantic import BaseModel, Field

    class QueryPayload(BaseModel):
        filters: dict[str, Any] = Field(default_factory=dict)
        sort: str = 'start_time'
        direction: str = 'desc'
        page: int = 1
        page_size: int = 50
        breakdowns: bool = True

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
        categories: list[dict[str, Any]] = Field(default_factory=list)
        causes: list[dict[str, Any]] = Field(default_factory=list)
        require_to_close: bool = False

    class SectionsPayload(BaseModel):
        sections: list[dict[str, Any]] = Field(default_factory=list)

    class StatusRulesPayload(BaseModel):
        rules: list[dict[str, Any]] = Field(default_factory=list)

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

    class FieldsPayload(BaseModel):
        fields: list[dict[str, Any]] = Field(default_factory=list)

    class TableColumnsPayload(BaseModel):
        builtin: list[str] = Field(default_factory=list)
        cdr: list[str] = Field(default_factory=list)
        export_cdr: list[str] = Field(default_factory=list)

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
        ('status', 'Status'), ('status_mode', 'Status Set'), ('team', 'Team'), ('assignee', 'Assignee'), ('root_domain', 'Root Domain'),
        ('root_category', 'Root Category'), ('root_cause', 'Root Cause'), ('version', 'CDR Version'),
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
        values['root_category'] = [[UNASSIGNED, NOT_CLASSIFIED], *[item['name'] for item in taxonomy['categories']]]
        values['root_cause'] = [[UNASSIGNED, 'No cause'], *[item['name'] for item in taxonomy['causes']]]
        values['status_mode'] = [['auto', 'Automatic'], ['manual', 'By hand']]
        values['version'] = [[key, label] for key, label in VERSION_LABELS.items()]
        return values

    def summary_parts(repository, filters: dict[str, Any], username: str, granularity: str, include_suggestions: bool = True):
        """The executive summary, progress status, options and selection lines of one NQ selection.

        The options carry the Root Cause Analysis of the selection under ``root_causes``.
        """
        from src.modules.non_qualified_calls_export import selection_lines

        executive = query_calls(repository, {'filters': filters, 'page_size': 25}, username)
        progress = progress_stats(repository, filters, username, granularity)
        options = {**list_options(repository),
                   'root_causes': root_cause_stats(repository, filters, username, include_suggestions),
                   'rates': nq_rates(repository, filters),
                   'lifecycle': lifecycle_stats(repository, filters, username),
                   'rca_insights': rca_insights(repository, filters, username),
                   'sections': list_sections(repository)}
        names = {str(item['id']): item['name'] for item in indexed_datasets(repository)}
        labels = {field['key']: field['label'] for field in list_fields(repository)}
        return executive, progress, options, selection_lines(filters, names, granularity, labels)

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
        sync = nq_index_status(repository)
        if sync['pending'] and not sync['synced_at'] and not sync['indexing']:
            # Nothing indexed yet (the first time the module opens): it is indexed at once, in the background.
            start_nq_index(repository, core.submit_background_task)
            sync = nq_index_status(repository)
        return JSONResponse({
            'sync': sync, 'options': list_options(repository), 'filter_options': filter_options(repository),
            'datasets': indexed_datasets(repository), 'users': workspace_users(),
            'user': {'username': user.username, 'can_edit': can_edit(user), 'can_moderate': can_moderate(user),
                     'can_configure_rule': can_configure_rule(user)},
            'unassigned': UNASSIGNED, 'page_sizes': list(PAGE_SIZES),
            'main_cities': list(repository.list_main_cities()),
            'saved_filters': saved_filters(repository),
            'root_causes': list_root_causes(repository), 'root_cause_defaults': nq_catalog.default_root_catalog(),
            'root_cause_rule_fields': RULE_FIELDS, 'default_root_cause_rule': DEFAULT_ROOT_CAUSE_RULE,
            'fields': list_fields(repository), 'field_types': FIELD_TYPES, 'field_sources': nq_catalog.FIELD_SOURCES,
            'tracking_refs': nq_catalog.TRACKING_REFS, 'rca_refs': nq_catalog.RCA_REFS, 'call_fields': list(CATALOG_CALL_FIELDS),
            'sections': list_sections(repository), 'default_sections': nq_catalog.default_sections(),
            'status_rules': status_rules(repository), 'default_status_rules': nq_catalog.default_status_rules(),
            'default_options': {'statuses': [{'name': name, 'color': color, 'closed': closed} for name, color, closed in DEFAULT_STATUSES],
                                'teams': [{'name': name, 'color': color, 'members': []} for name, color in DEFAULT_TEAMS]},
            'rule_operators': nq_catalog.RULE_OPERATORS, 'condition_fields': nq_catalog.condition_fields(list_fields(repository)),
            'rca_results': rca_results_summary(repository), 'rca_sources': nq_rca.SOURCE_LABELS,
            'table_columns': table_columns(repository), 'optional_columns': OPTIONAL_COLUMNS,
            'cdr_columns': available_cdr_columns(repository), 'max_cdr_columns': MAX_CDR_COLUMNS,
            'version_labels': VERSION_LABELS,
        })

    @core.app.post('/api/non-qualified-calls/reindex')
    def nq_reindex(user=Depends(core.current_user)) -> JSONResponse:
        """Index the calls of every CDR again in the background, keeping their follow-up."""
        repository = workspace_repository(user)
        start_nq_index(repository, core.submit_background_task, force=True)
        if hasattr(repository, 'try_add_log'):
            repository.try_add_log(user.username, 'nq_calls_reindex_queued', '{}')
        return JSONResponse({'sync': nq_index_status(repository)})

    @core.app.get('/api/non-qualified-calls/index-status')
    def nq_index_status_route(user=Depends(core.current_user)) -> JSONResponse:
        """Whether the indexing still runs, for the page to reload its calls once it ends."""
        return JSONResponse({'sync': nq_index_status(workspace_repository(user))})

    @core.app.put('/api/non-qualified-calls/fields')
    def nq_save_fields(payload: FieldsPayload, user=Depends(editor_user)) -> JSONResponse:
        """The analysis fields of the workspace (user-editor and above)."""
        repository = workspace_repository(user)
        return JSONResponse({'fields': translate(lambda: save_fields(repository, payload.fields, user.username))})

    async def uploaded_file(request: Request, name: str, limit_mb: int) -> tuple[bytes, str, dict[str, Any]]:
        form = await request.form()
        upload = form.get(name)
        if upload is None or not hasattr(upload, 'read'):
            raise HTTPException(400, 'Choose a file.')
        content = await upload.read()
        if len(content) > limit_mb * 1024 * 1024:
            raise HTTPException(400, f'The file is larger than {limit_mb} MB.')
        return content, str(getattr(upload, 'filename', '') or 'upload'), {key: form.get(key) for key in form.keys()}

    @core.app.put('/api/non-qualified-calls/sections')
    def nq_save_sections(payload: SectionsPayload, user=Depends(editor_user)) -> JSONResponse:
        """The names and colours of the six sections (user-editor and above)."""
        repository = workspace_repository(user)
        return JSONResponse({'sections': save_sections(repository, payload.sections, user.username)})

    @core.app.put('/api/non-qualified-calls/status-rules')
    def nq_save_status_rules(payload: StatusRulesPayload, user=Depends(editor_user)) -> JSONResponse:
        """The rules that set the automatic NQ Call Status; the calls follow them at once."""
        repository = workspace_repository(user)
        rules = translate(lambda: save_status_rules(repository, payload.rules, user.username))
        return JSONResponse({'status_rules': rules})

    @core.app.get('/api/non-qualified-calls/catalog/export')
    def nq_catalog_export(user=Depends(core.current_user)) -> Response:
        """The catalog (sections, fields, lists, root cause catalog, statuses, teams and status rules) as Excel."""
        repository = workspace_repository(user)
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', f'{core.active_workspace.name}_NQ_Analysis_Center_catalog.xlsx')
        return Response(catalog_document(repository),
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})

    @core.app.post('/api/non-qualified-calls/catalog/import')
    async def nq_catalog_import(request: Request, user=Depends(editor_user)) -> JSONResponse:
        """Preview (``preview=1``) or import a catalog workbook: its format, or the layout of the meeting workbook."""
        repository = workspace_repository(user)
        content, _name, form = await uploaded_file(request, 'workbook', 10)
        try:
            if str(form.get('preview') or '') == '1':
                return JSONResponse(preview_catalog(repository, content))
            return JSONResponse(import_catalog(repository, content, user.username, set(workspace_users())))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - an unreadable file is a user error.
            raise HTTPException(400, f'The workbook could not be read: {exc}') from exc

    @core.app.get('/api/non-qualified-calls/rca')
    def nq_rca_summary(user=Depends(core.current_user)) -> JSONResponse:
        return JSONResponse(rca_results_summary(workspace_repository(user)))

    @core.app.get('/api/non-qualified-calls/rca/template')
    def nq_rca_template(user=Depends(core.current_user)) -> Response:
        workspace_repository(user)
        return Response(nq_rca.rca_template(), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="NQ_RCA_results_template.csv"'})

    @core.app.post('/api/non-qualified-calls/rca/import')
    async def nq_rca_import(request: Request, user=Depends(editor_user)) -> JSONResponse:
        """Preview (``preview=1``) or import RCA script results by JOIN_ID; ``replace=1`` forgets the previous results."""
        repository = workspace_repository(user)
        content, name, form = await uploaded_file(request, 'file', 100)
        try:
            return JSONResponse(import_rca_results(repository, content, name, user.username,
                                                   replace=str(form.get('replace') or '') == '1',
                                                   dry_run=str(form.get('preview') or '') == '1'))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - an unreadable file is a user error.
            raise HTTPException(400, f'The RCA file could not be read: {exc}') from exc

    @core.app.delete('/api/non-qualified-calls/rca')
    def nq_rca_clear(user=Depends(editor_user)) -> JSONResponse:
        repository = workspace_repository(user)
        return JSONResponse({'deleted': clear_rca_results(repository, user.username), 'rca_results': rca_results_summary(repository)})

    @core.app.post('/api/non-qualified-calls/lifecycle')
    def nq_lifecycle(payload: ExportPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        return JSONResponse(lifecycle_stats(repository, payload.filters, user.username))

    @core.app.post('/api/non-qualified-calls/rca/insights')
    def nq_rca_insights(payload: ExportPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        return JSONResponse(rca_insights(repository, payload.filters, user.username))

    @core.app.put('/api/non-qualified-calls/table-columns')
    def nq_save_table_columns(payload: TableColumnsPayload, user=Depends(editor_user)) -> JSONResponse:
        """The optional columns of the Calls table: built-in ones and CDR columns (indexed again)."""
        repository = workspace_repository(user)
        columns = translate(lambda: save_table_columns(repository, payload.builtin, payload.cdr, user.username, payload.export_cdr))
        # New CDR columns are indexed in the background.
        start_nq_index(repository, core.submit_background_task)
        return JSONResponse({'table_columns': columns, 'sync': nq_index_status(repository)})

    @core.app.post('/api/non-qualified-calls/rates')
    def nq_rates_route(payload: ExportPayload, user=Depends(core.current_user)) -> JSONResponse:
        """Calls and Non-Qualified Calls of every campaign and operator."""
        repository = workspace_repository(user)
        return JSONResponse(nq_rates(repository, payload.filters))

    @core.app.put('/api/non-qualified-calls/filters')
    def nq_save_filters(payload: QueryPayload, user=Depends(core.current_user)) -> JSONResponse:
        return JSONResponse({'filters': save_filters(workspace_repository(user), payload.filters)})

    @core.app.post('/api/non-qualified-calls/calls')
    def nq_calls(payload: QueryPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        result = query_calls(repository, payload.model_dump(), user.username)
        return JSONResponse({**result, 'sync': nq_index_status(repository)})

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
        catalog = {'domains': payload.domains, 'categories': payload.categories, 'causes': payload.causes}
        return JSONResponse(translate(lambda: save_root_causes(repository, catalog, payload.require_to_close, user.username)))

    @core.app.put('/api/non-qualified-calls/root-causes/rule')
    def nq_save_root_cause_rule(payload: RootCauseRulePayload, user=Depends(rule_user)) -> JSONResponse:
        """The suggestion rule of the workspace (admins and super-admins); no rule restores the default one."""
        repository = workspace_repository(user)
        return JSONResponse({'rule': translate(lambda: save_root_cause_rule(repository, payload.rule, user.username))})

    @core.app.post('/api/non-qualified-calls/root-causes/stats')
    def nq_root_cause_stats(payload: RootCauseStatsPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        return JSONResponse(root_cause_stats(repository, payload.filters, user.username, payload.include_suggestions))

    @core.app.post('/api/non-qualified-calls/progress')
    def nq_progress(payload: ProgressPayload, user=Depends(core.current_user)) -> JSONResponse:
        repository = workspace_repository(user)
        return JSONResponse(progress_stats(repository, payload.filters, user.username, payload.granularity))

    @core.app.post('/api/non-qualified-calls/export/{export_format}')
    def nq_export_document(export_format: str, payload: ProgressPayload, user=Depends(core.current_user)) -> Response:
        """The Executive Summary, Progress Status and Root Cause Analysis of the filtered calls, in PowerPoint or Word."""
        if export_format not in {'powerpoint', 'word'}:
            raise HTTPException(404, 'Unsupported export type.')
        repository = workspace_repository(user)
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
        content = export_workbook(repository, payload.filters, user.username)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', f'{core.active_workspace.name}_non-qualified-calls_{stamp}.xlsx')
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})
