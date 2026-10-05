"""Reporting: scheduled report jobs that collect artifacts and email them.

A Reporting Job (``report_tasks``) selects artifacts — CDR Analysis,
Network Insights, Dashboard PPTs and Scoring PPTs — plus optional email
recipients and a schedule. Each execution (``report_task_runs``) writes its
artifacts to its own folder and, when email is enabled, sends them as attachments
with a body that describes every artifact and its filters.

Jobs belong to a workspace and only run while it is the active workspace: the
artifact generators read the active workspace. A run that falls due while
another workspace is active runs as soon as its workspace becomes active again.
"""

import calendar
import html
import json
import math
import re
import shutil
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
from typing import Any

from src.modules.column_names import sort_vendor_values

REPORT_TASKS_TABLE = 'report_tasks'
REPORT_TASK_RUNS_TABLE = 'report_task_runs'
REPORT_FORMATS = ('powerpoint', 'word')
SCHEDULE_MODES = ('manual', 'once', 'daily', 'weekly', 'monthly')
WEEKDAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
SCORING_LEVELS = ('Operator', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign')
SCORING_FILTER_FIELDS = ('Operator', 'Operator_Vendor', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign')
NETWORK_FILTER_FIELDS = ('operators', 'operator_vendors', 'vendors', 'campaigns', 'regions', 'clusters', 'cities')
# CDR Analysis artifacts: the global aggregation of the charts and the CDF comparison, one choice each.
CDR_ANALYSIS_AGGREGATIONS = {
    'all': 'Auto', 'operator': 'Operator', 'operator_vendor': 'Operator_Vendor', 'vendor': 'Vendor',
    'market': 'Market', 'region': 'Region', 'cluster': 'Cluster', 'city': 'City',
}
CDR_ANALYSIS_CDF_GROUPINGS = {'all': 'Single CDF', **{key: label for key, label in CDR_ANALYSIS_AGGREGATIONS.items() if key != 'all'}}
# Network Insights filter names and the CDR Analysis dimension each one filters.
CDR_ANALYSIS_FILTER_DIMENSIONS = {
    'operators': 'operator', 'operator_vendors': 'operator_vendor', 'vendors': 'vendor', 'regions': 'region',
    'clusters': 'cluster', 'cities': 'city', 'campaigns': 'campaign',
}
RUN_FINAL_STATUSES = ('sent', 'completed', 'partial', 'failed')
DASHBOARD_JOB_TIMEOUT_SECONDS = 3 * 60 * 60
SCHEDULER_INTERVAL_SECONDS = 30
INTERRUPTED_RUN_MESSAGE = 'The run was interrupted by an application restart.'
MODULE_LABELS = {
    'dataset_analysis': 'CDR Analysis', 'network_insights': 'Network Insights',
    'dashboards': 'Dashboards', 'scoring': 'Scoring',
}
# The feature a user needs to include each kind of artifact in a Reporting Job.
MODULE_FEATURES = {
    'dataset_analysis': 'datasets-analysis', 'network_insights': 'network-insights',
    'dashboards': 'e2e-dashboards', 'scoring': 'scoring',
}
# Artifacts of other modules (for example Non-Qualified Calls) register here:
# key -> {'label', 'feature', 'formats', 'generate', 'filters', 'settings', 'values'}.
# ``generate(config, folder, stamp, user)`` returns artifact dictionaries; the
# config's ``options`` holds the chosen ``filters`` and ``settings``.
ARTIFACT_PROVIDERS: dict[str, dict[str, Any]] = {}


def register_report_artifact_provider(
    key: str, label: str, feature: str, generate, formats: tuple[str, ...] = ('powerpoint',), *,
    filters: tuple[tuple[str, str], ...] = (), settings: tuple[dict[str, Any], ...] = (), values=None,
) -> None:
    """Let a module add its own reports to Reporting Jobs.

    ``filters`` are (key, label) multi-value filters whose choices ``values(user)``
    returns; ``settings`` are single choices: {'key', 'label', 'choices', 'default'}.
    """
    ARTIFACT_PROVIDERS[key] = {'label': label, 'feature': feature, 'formats': tuple(formats), 'generate': generate,
                               'filters': tuple(filters), 'settings': tuple(settings), 'values': values}
FORMAT_LABELS = {'powerpoint': 'PPT', 'word': 'Word', 'excel': 'Excel'}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {REPORT_TASKS_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    definition_json TEXT NOT NULL DEFAULT '{{}}',
    send_email INTEGER NOT NULL DEFAULT 1,
    recipients_json TEXT NOT NULL DEFAULT '[]',
    schedule_json TEXT NOT NULL DEFAULT '{{}}',
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT,
    last_run_id INTEGER,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS {REPORT_TASK_RUNS_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    task_name TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    requested_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    send_email INTEGER NOT NULL DEFAULT 0,
    recipients_json TEXT NOT NULL DEFAULT '[]',
    email_status TEXT NOT NULL DEFAULT '',
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    output_dir TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_report_task_runs_task ON {REPORT_TASK_RUNS_TABLE}(task_id, id);
"""


def now_local() -> datetime:
    return datetime.now().astimezone()


def ensure_report_task_tables(task_repository: Any) -> None:
    with task_repository.connection() as connection:
        connection.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Definitions and schedules
# ---------------------------------------------------------------------------
def _ids(values: Any) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values or [] if str(value).strip().lstrip('-').isdigit()))


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    return list(dict.fromkeys(str(value).strip() for value in values or [] if str(value).strip()))


def _formats(values: Any) -> list[str]:
    selected = [value for value in _strings(values) if value in REPORT_FORMATS]
    return selected or ['powerpoint']


def _network_entries(value: Any) -> list[dict[str, Any]]:
    """Network Insights entries; jobs saved with a single selection keep it as one entry."""
    if isinstance(value, dict):
        return [value] if value.get('enabled') else []
    return [entry for entry in value or [] if isinstance(entry, dict)]


def _network_entry(entry: dict[str, Any]) -> dict[str, Any]:
    selection = entry.get('selection') if isinstance(entry.get('selection'), dict) else {}
    return {
        'label': str(entry.get('label') or '').strip()[:120],
        'formats': _formats(entry.get('formats')),
        'selection': {
            'nr_mode': 'SA' if str(selection.get('nr_mode') or '').upper() == 'SA' else 'NSA',
            'datasets': _datasets_by_kind(selection.get('datasets')),
            'technology': selection.get('technology') if selection.get('technology') in {'lte', 'nr', 'lte_nr'} else 'lte',
            'group': _network_groups(selection.get('group')),
            **{field: _strings(selection.get(field)) for field in NETWORK_FILTER_FIELDS},
            **_network_thresholds(selection),
            'grid_metres': float(selection.get('grid_metres', 250) or 250),
        },
    }


def network_entry_name(entry: dict[str, Any]) -> str:
    """Name of a Network Insights entry: its label, or NR Mode and technology."""
    selection = entry.get('selection') or {}
    technology = {'lte': 'LTE', 'nr': 'NR', 'lte_nr': 'LTE+NR'}.get(selection.get('technology'), 'LTE')
    return entry.get('label') or f"{selection.get('nr_mode') or 'NSA'} {technology}"


def _network_thresholds(selection: dict[str, Any]) -> dict[str, float]:
    """LTE and NR thresholds of a Network Insights selection.

    Jobs saved before NR had its own thresholds keep their single pair for
    NR-only analyses.
    """
    def number(key: str, default: float) -> float:
        try:
            value = float(selection.get(key))
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default

    legacy_nr = selection.get('technology') == 'nr' and 'nr_coverage_threshold' not in selection
    return {
        'coverage_threshold': number('coverage_threshold', -110.0),
        'interference_threshold': number('interference_threshold', 0.0),
        'nr_coverage_threshold': number('coverage_threshold' if legacy_nr else 'nr_coverage_threshold', -115.0),
        'nr_interference_threshold': number('interference_threshold' if legacy_nr else 'nr_interference_threshold', -3.0),
    }


def _datasets_by_kind(value: Any) -> dict[str, list[int]]:
    if not isinstance(value, dict):
        return {}
    return {str(kind): _ids(ids) for kind, ids in value.items() if _ids(ids)}


def _filters(value: Any, fields: tuple[str, ...]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {field: _strings(value.get(field)) for field in fields if _strings(value.get(field))}


def _date_text(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f'Invalid date: {text}.') from exc


CDR_ANALYSIS_KINDS = {'data': 'CDR Data', 'voice': 'CDR Voice', 'speech': 'CDR Speech'}


def _cdr_analysis_metrics(value: Any) -> dict[str, list[str]]:
    value = value if isinstance(value, dict) else {}
    return {kind: metrics for kind in CDR_ANALYSIS_KINDS if (metrics := _strings(value.get(kind)))}


def _network_groups(value: Any) -> list[str]:
    """Network Insights grouping: Operator is always included unless Vendor groups the samples."""
    groups = _strings(value) or ['operator', 'campaign']
    return groups if 'operator' in groups or 'vendor' in groups else ['operator', *groups]


def _choice(value: Any, choices: dict[str, str], default: str) -> str:
    text = str(value or '').strip()
    return text if text in choices else default


def normalize_definition(raw: Any) -> dict[str, Any]:
    """Validate a Reporting Job artifact selection; raises ValueError when nothing is selected."""
    raw = raw if isinstance(raw, dict) else {}
    dataset_analysis = raw.get('dataset_analysis') if isinstance(raw.get('dataset_analysis'), dict) else {}
    definition: dict[str, Any] = {
        'dataset_analysis': {
            'enabled': bool(dataset_analysis.get('enabled')),
            'formats': _formats(dataset_analysis.get('formats')),
            # An empty list selects every ready CDR dataset at run time.
            'dataset_ids': _ids(dataset_analysis.get('dataset_ids')),
            # The same filters as Network Insights; empty filters include every value.
            'filters': {field: values for field in NETWORK_FILTER_FIELDS
                        if (values := _strings((dataset_analysis.get('filters') or {}).get(field)))},
            # The metrics of each CDR type; an empty or missing list includes every metric.
            'metrics': _cdr_analysis_metrics(dataset_analysis.get('metrics')),
            'aggregation': _choice(dataset_analysis.get('aggregation'), CDR_ANALYSIS_AGGREGATIONS, 'all'),
            'cdf_grouping': _choice(dataset_analysis.get('cdf_grouping'), CDR_ANALYSIS_CDF_GROUPINGS, 'operator'),
        },
        # One Network Insights per entry, each with its own selection.
        'network_insights': [_network_entry(entry) for entry in _network_entries(raw.get('network_insights'))],
        'dashboards': [],
        'scoring': [],
        # Artifacts of modules registered in ARTIFACT_PROVIDERS.
        'modules': {},
    }
    for key, config in (raw.get('modules') or {}).items() if isinstance(raw.get('modules'), dict) else ():
        provider = ARTIFACT_PROVIDERS.get(key)
        if provider and isinstance(config, dict) and config.get('enabled'):
            formats = [value for value in _strings(config.get('formats')) if value in provider['formats']] or [provider['formats'][0]]
            definition['modules'][key] = {'enabled': True, 'formats': formats,
                                          'options': config.get('options') if isinstance(config.get('options'), dict) else {}}
    # Dashboards and Scoring entries carry every option of their own module;
    # each run generates a new PPT with them.
    for entry in raw.get('dashboards') or []:
        if not isinstance(entry, dict) or not str(entry.get('dashboard_id') or '').strip():
            continue
        definition['dashboards'].append({
            'dashboard_id': str(entry['dashboard_id']).strip(), 'label': str(entry.get('label') or '').strip()[:120],
            'scope': entry.get('scope') if entry.get('scope') in {'single', 'multivendor'} else 'single',
            'vendor_comparison': entry.get('vendor_comparison') if entry.get('vendor_comparison') in {'operator_vendor', 'vendor_only'} else 'operator_vendor',
            'datasets': _datasets_by_kind(entry.get('datasets')),
            # Every ready Data, Voice and Speech CDR of the Dashboard's NR Mode at each run.
            'all_datasets': bool(entry.get('all_datasets')),
            'date_from': _date_text(entry.get('date_from')), 'date_to': _date_text(entry.get('date_to')),
            'filters': {str(field): _strings(values) for field, values in (entry.get('filters') or {}).items()
                        if str(field).strip() and _strings(values)} if isinstance(entry.get('filters'), dict) else {},
        })
    for entry in raw.get('scoring') or []:
        if not isinstance(entry, dict):
            continue
        nr_mode = str(entry.get('nr_mode') or 'NSA').upper()
        levels = [level for level in _strings(entry.get('aggregation_levels')) if level in SCORING_LEVELS]
        definition['scoring'].append({
            'label': str(entry.get('label') or '').strip()[:120],
            'nr_mode': nr_mode if nr_mode in {'NSA', 'SA'} else 'NSA',
            # An empty list uses the newest complete set of CDRs at run time.
            'dataset_ids': _ids(entry.get('dataset_ids')),
            'aggregation_levels': ['Operator', *[level for level in levels if level != 'Operator']],
            'context_filters': _filters(entry.get('context_filters'), SCORING_FILTER_FIELDS),
            # The workspace Main Cities at run time, like the Scoring module's Main Cities option.
            'main_cities': bool(entry.get('main_cities')),
            'scoring_profile_id': str(entry.get('scoring_profile_id') or '').strip(),
            'baseline_operator': str(entry.get('baseline_operator') or 'EE').strip() or 'EE',
        })
    if not (definition['dataset_analysis']['enabled'] or definition['network_insights']
            or definition['dashboards'] or definition['scoring'] or definition['modules']):
        raise ValueError('Select at least one artifact for the Reporting Job.')
    return definition


def normalize_schedule(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get('mode') if raw.get('mode') in SCHEDULE_MODES else 'manual'
    time_text = str(raw.get('time') or '08:00').strip()
    if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', time_text):
        raise ValueError('Enter the time as HH:MM.')
    schedule: dict[str, Any] = {'mode': mode, 'time': time_text}
    if mode == 'once':
        schedule['date'] = _date_text(raw.get('date'))
        if not schedule['date']:
            raise ValueError('Choose the date of the single execution.')
    if mode == 'weekly':
        schedule['weekdays'] = sorted({int(day) for day in raw.get('weekdays') or [] if str(day).isdigit() and 0 <= int(day) <= 6})
        if not schedule['weekdays']:
            raise ValueError('Choose at least one weekday.')
    if mode == 'monthly':
        day = int(raw.get('day_of_month') or 1)
        if not 1 <= day <= 31:
            raise ValueError('The day of the month must be between 1 and 31.')
        schedule['day_of_month'] = day
    return schedule


def next_run_after(schedule: dict[str, Any], after: datetime) -> datetime | None:
    """Next execution strictly after ``after`` (an aware local datetime), or None."""
    mode = schedule.get('mode')
    hour, minute = (int(part) for part in str(schedule.get('time') or '08:00').split(':'))
    tz = after.tzinfo

    def at(day: date) -> datetime:
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)

    if mode == 'once':
        candidate = at(date.fromisoformat(schedule['date']))
        return candidate if candidate > after else None
    if mode == 'daily':
        candidate = at(after.date())
        return candidate if candidate > after else at(after.date() + timedelta(days=1))
    if mode == 'weekly':
        for offset in range(0, 8):
            day = after.date() + timedelta(days=offset)
            if day.weekday() in schedule.get('weekdays', []) and at(day) > after:
                return at(day)
        return None
    if mode == 'monthly':
        year, month = after.year, after.month
        for _ in range(0, 13):
            day = min(int(schedule.get('day_of_month') or 1), calendar.monthrange(year, month)[1])
            candidate = at(date(year, month, day))
            if candidate > after:
                return candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def used_modules(definition: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(module, label, required feature) for every kind of artifact a definition includes."""
    used = []
    if (definition.get('dataset_analysis') or {}).get('enabled'):
        used.append(('dataset_analysis', MODULE_LABELS['dataset_analysis'], MODULE_FEATURES['dataset_analysis']))
    for module in ('network_insights', 'dashboards', 'scoring'):
        if definition.get(module):
            used.append((module, MODULE_LABELS[module], MODULE_FEATURES[module]))
    for key in definition.get('modules') or {}:
        provider = ARTIFACT_PROVIDERS.get(key)
        used.append((key, provider['label'] if provider else key, provider['feature'] if provider else key))
    return used


def recurrence_label(schedule: dict[str, Any]) -> str:
    mode, at_time = schedule.get('mode'), schedule.get('time') or '08:00'
    if mode == 'once':
        return f"Once · {schedule.get('date')} {at_time}"
    if mode == 'daily':
        return f'Daily · {at_time}'
    if mode == 'weekly':
        days = ', '.join(WEEKDAY_NAMES[day][:3] for day in schedule.get('weekdays', []))
        return f'Weekly · {days} · {at_time}'
    if mode == 'monthly':
        return f"Monthly · day {schedule.get('day_of_month')} · {at_time}"
    return 'Manual only'


def artifact_labels(definition: dict[str, Any], dashboard_names: dict[str, str] | None = None) -> list[str]:
    labels = []
    section = definition.get('dataset_analysis') or {}
    if section.get('enabled'):
        labels.append(f"{MODULE_LABELS['dataset_analysis']} ({'/'.join(FORMAT_LABELS[value] for value in section.get('formats') or [])})")
    for entry in definition.get('network_insights') or []:
        labels.append(f"{MODULE_LABELS['network_insights']} · {network_entry_name(entry)} ({'/'.join(FORMAT_LABELS[value] for value in entry.get('formats') or [])})")
    dashboards = definition.get('dashboards') or []
    if dashboards:
        names = ', '.join(entry.get('label') or (dashboard_names or {}).get(entry.get('dashboard_id', ''), entry.get('dashboard_id', '')) for entry in dashboards)
        labels.append(f'Dashboards: {len(dashboards)} PPT ({names})')
    scoring = definition.get('scoring') or []
    if scoring:
        names = ', '.join(entry.get('label') or f"{entry.get('nr_mode', 'NSA')} {' → '.join(entry.get('aggregation_levels') or ['Operator'])}" for entry in scoring)
        labels.append(f'Scoring: {len(scoring)} PPT ({names})')
    for key, config in (definition.get('modules') or {}).items():
        provider = ARTIFACT_PROVIDERS.get(key)
        labels.append(f"{provider['label'] if provider else key} ({'/'.join(FORMAT_LABELS.get(value, value) for value in config.get('formats') or [])})")
    return labels


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _loads(value: Any, default: Any) -> Any:
    try:
        decoded = json.loads(str(value or ''))
    except (TypeError, ValueError):
        return default
    return decoded if isinstance(decoded, type(default)) else default


def task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    definition = _loads(row['definition_json'], {})
    try:
        # Stored definitions are read through the current model.
        definition = normalize_definition(definition)
    except (ValueError, TypeError):
        pass
    schedule = _loads(row['schedule_json'], {'mode': 'manual', 'time': '08:00'})
    return {
        'id': int(row['id']), 'name': str(row['name']), 'definition': definition,
        'send_email': bool(row['send_email']), 'recipients': _loads(row['recipients_json'], []),
        'schedule': schedule, 'recurrence': recurrence_label(schedule), 'enabled': bool(row['enabled']),
        'next_run_at': row['next_run_at'], 'last_run_id': row['last_run_id'],
        'artifacts': artifact_labels(definition),
        'created_by': str(row['created_by']), 'created_at': str(row['created_at']), 'updated_at': str(row['updated_at']),
    }


def run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'id': int(row['id']), 'task_id': int(row['task_id']), 'task_name': str(row['task_name']),
        'trigger': str(row['trigger']), 'status': str(row['status']), 'progress': int(row['progress'] or 0),
        'message': str(row['message'] or ''), 'requested_by': str(row['requested_by']),
        'created_at': str(row['created_at']), 'started_at': row['started_at'], 'finished_at': row['finished_at'],
        'send_email': bool(row['send_email']), 'recipients': _loads(row['recipients_json'], []),
        'email_status': str(row['email_status'] or ''), 'artifacts': _loads(row['artifacts_json'], []),
        'output_dir': str(row['output_dir'] or ''), 'error': str(row['last_error'] or ''),
    }


def list_tasks(task_repository: Any) -> list[dict[str, Any]]:
    ensure_report_task_tables(task_repository)
    with task_repository.connection() as connection:
        rows = connection.execute(f'SELECT * FROM {REPORT_TASKS_TABLE} ORDER BY name COLLATE NOCASE, id').fetchall()
    return [task_from_row(row) for row in rows]


def get_task(task_repository: Any, task_id: int) -> dict[str, Any] | None:
    ensure_report_task_tables(task_repository)
    with task_repository.connection() as connection:
        row = connection.execute(f'SELECT * FROM {REPORT_TASKS_TABLE} WHERE id = ?', (task_id,)).fetchone()
    return task_from_row(row) if row else None


def save_task(task_repository: Any, task_id: int | None, payload: dict[str, Any], username: str,
              *, parse_recipients, invalid_recipients) -> dict[str, Any]:
    """Create or update a Reporting Job after validating every field."""
    name = str(payload.get('name') or '').strip()
    if not name:
        raise ValueError('Enter a name for the Reporting Job.')
    definition = normalize_definition(payload.get('definition'))
    schedule = normalize_schedule(payload.get('schedule'))
    send_email = bool(payload.get('send_email'))
    recipients = parse_recipients(payload.get('recipients'))
    if send_email:
        if not recipients:
            raise ValueError('Add at least one email recipient or disable email delivery.')
        if invalid := invalid_recipients(recipients):
            raise ValueError(f"Invalid email recipients: {', '.join(invalid)}.")
    enabled = bool(payload.get('enabled', True))
    next_run = next_run_after(schedule, now_local()) if enabled else None
    if schedule['mode'] == 'once' and next_run is None:
        raise ValueError('The single execution must be in the future.')
    now = now_local().isoformat()
    values = (name[:160], json.dumps(definition, ensure_ascii=False), int(send_email), json.dumps(recipients),
              json.dumps(schedule), int(enabled), next_run.isoformat() if next_run else None)
    ensure_report_task_tables(task_repository)
    with task_repository.connection() as connection:
        if task_id is None:
            task_id = int(connection.execute(
                f'INSERT INTO {REPORT_TASKS_TABLE} (name, definition_json, send_email, recipients_json, schedule_json, enabled, next_run_at, '
                'created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (*values, username, now, now),
            ).lastrowid)
        elif connection.execute(
            f'UPDATE {REPORT_TASKS_TABLE} SET name = ?, definition_json = ?, send_email = ?, recipients_json = ?, schedule_json = ?, '
            'enabled = ?, next_run_at = ?, updated_at = ? WHERE id = ?', (*values, now, task_id),
        ).rowcount == 0:
            raise ValueError('Reporting Job not found.')
    return get_task(task_repository, task_id)


def delete_task(task_repository: Any, task_id: int) -> list[str]:
    """Delete a Reporting Job and its runs; returns the run folders to remove."""
    ensure_report_task_tables(task_repository)
    with task_repository.connection() as connection:
        folders = [str(row['output_dir']) for row in connection.execute(
            f'SELECT output_dir FROM {REPORT_TASK_RUNS_TABLE} WHERE task_id = ?', (task_id,)).fetchall() if row['output_dir']]
        if connection.execute(f'DELETE FROM {REPORT_TASKS_TABLE} WHERE id = ?', (task_id,)).rowcount == 0:
            raise ValueError('Reporting Job not found.')
        connection.execute(f'DELETE FROM {REPORT_TASK_RUNS_TABLE} WHERE task_id = ?', (task_id,))
    return folders


def list_runs(task_repository: Any, task_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    ensure_report_task_tables(task_repository)
    query = f'SELECT * FROM {REPORT_TASK_RUNS_TABLE}' + (' WHERE task_id = ?' if task_id is not None else '') + ' ORDER BY id DESC LIMIT ?'
    with task_repository.connection() as connection:
        rows = connection.execute(query, ((task_id, limit) if task_id is not None else (limit,))).fetchall()
    return [run_from_row(row) for row in rows]


def get_run(task_repository: Any, run_id: int) -> dict[str, Any] | None:
    ensure_report_task_tables(task_repository)
    with task_repository.connection() as connection:
        row = connection.execute(f'SELECT * FROM {REPORT_TASK_RUNS_TABLE} WHERE id = ?', (run_id,)).fetchone()
    return run_from_row(row) if row else None


def update_run(task_repository: Any, run_id: int, **changes: Any) -> None:
    if not changes:
        return
    columns = {'artifacts': 'artifacts_json', 'recipients': 'recipients_json', 'error': 'last_error'}
    assignments, values = [], []
    for key, value in changes.items():
        column = columns.get(key, key)
        if column in {'artifacts_json', 'recipients_json'} and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        assignments.append(f'{column} = ?')
        values.append(value)
    with task_repository.connection() as connection:
        connection.execute(f'UPDATE {REPORT_TASK_RUNS_TABLE} SET {", ".join(assignments)} WHERE id = ?', (*values, run_id))


def create_run(task_repository: Any, task: dict[str, Any], trigger: str, username: str) -> int:
    with task_repository.connection() as connection:
        run_id = int(connection.execute(
            f'INSERT INTO {REPORT_TASK_RUNS_TABLE} (task_id, task_name, trigger, status, message, requested_by, created_at, send_email, recipients_json) '
            "VALUES (?, ?, ?, 'queued', 'Waiting to start', ?, ?, ?, ?)",
            (task['id'], task['name'], trigger, username, now_local().isoformat(), int(task['send_email']), json.dumps(task['recipients'])),
        ).lastrowid)
        connection.execute(f'UPDATE {REPORT_TASKS_TABLE} SET last_run_id = ? WHERE id = ?', (run_id, task['id']))
    return run_id


def claim_due_tasks(task_repository: Any, now: datetime) -> list[dict[str, Any]]:
    """Advance every due job to its next execution and return the jobs to run once each."""
    ensure_report_task_tables(task_repository)
    due = []
    with task_repository.connection() as connection:
        rows = connection.execute(
            f'SELECT * FROM {REPORT_TASKS_TABLE} WHERE enabled = 1 AND next_run_at IS NOT NULL').fetchall()
        for row in rows:
            try:
                scheduled = datetime.fromisoformat(str(row['next_run_at']))
            except ValueError:
                continue
            if scheduled > now:
                continue
            task = task_from_row(row)
            # Missed executions collapse into this single run.
            following = next_run_after(task['schedule'], now)
            claimed = connection.execute(
                f'UPDATE {REPORT_TASKS_TABLE} SET next_run_at = ? WHERE id = ? AND next_run_at = ?',
                (following.isoformat() if following else None, task['id'], row['next_run_at']),
            ).rowcount
            if claimed:
                due.append(task)
    return due


def fail_interrupted_runs(task_repository: Any, active_run_ids: set[int]) -> None:
    ensure_report_task_tables(task_repository)
    now = now_local().isoformat()
    with task_repository.connection() as connection:
        for row in connection.execute(
            f"SELECT id FROM {REPORT_TASK_RUNS_TABLE} WHERE status IN ('queued', 'running')").fetchall():
            if int(row['id']) not in active_run_ids:
                connection.execute(
                    f"UPDATE {REPORT_TASK_RUNS_TABLE} SET status = 'failed', message = ?, last_error = ?, finished_at = ? WHERE id = ?",
                    (INTERRUPTED_RUN_MESSAGE, INTERRUPTED_RUN_MESSAGE, now, int(row['id'])),
                )


# ---------------------------------------------------------------------------
# Transfer (export/import, workspace transfers, backup/restore)
# ---------------------------------------------------------------------------
def _definition_dataset_ids(definition: dict[str, Any]) -> set[int]:
    ids = set(definition.get('dataset_analysis', {}).get('dataset_ids') or [])
    for entry in definition.get('network_insights') or []:
        ids.update(value for values in ((entry.get('selection') or {}).get('datasets') or {}).values() for value in values)
    for entry in definition.get('scoring') or []:
        ids.update(entry.get('dataset_ids') or [])
    return {int(value) for value in ids}


def _remap_dataset_ids(definition: dict[str, Any], mapping: dict[int, int]) -> dict[str, Any]:
    """Point dataset references at the destination workspace; unknown datasets are dropped."""
    remap = lambda values: [mapping[int(value)] for value in values or [] if int(value) in mapping]
    definition = json.loads(json.dumps(definition))
    if definition.get('dataset_analysis', {}).get('dataset_ids'):
        definition['dataset_analysis']['dataset_ids'] = remap(definition['dataset_analysis']['dataset_ids'])
    definition['network_insights'] = _network_entries(definition.get('network_insights'))
    for entry in definition['network_insights']:
        selection = entry.get('selection') or {}
        if selection.get('datasets'):
            selection['datasets'] = {kind: remap(values) for kind, values in selection['datasets'].items() if remap(values)}
    for entry in definition.get('scoring') or []:
        if entry.get('dataset_ids'):
            entry['dataset_ids'] = remap(entry['dataset_ids'])
    return definition


def export_tasks_document(task_repository: Any) -> bytes:
    """Portable Reporting Jobs; dataset references also carry their file names."""
    tasks = list_tasks(task_repository)
    names = {int(row['id']): str(row['file_name']) for row in task_repository.list_datasets()}
    used = set().union(*(_definition_dataset_ids(task['definition']) for task in tasks)) if tasks else set()
    document = {
        'format': 'dashboard-analytic-reporting-jobs', 'version': 1,
        'dataset_names': {str(dataset_id): names[dataset_id] for dataset_id in sorted(used) if dataset_id in names},
        'reporting_jobs': [{key: task[key] for key in ('name', 'definition', 'send_email', 'recipients', 'schedule', 'enabled')} for task in tasks],
    }
    return json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')


def import_tasks_document(task_repository: Any, content: bytes | str, username: str, *, parse_recipients, invalid_recipients) -> int:
    """Add or replace (by name) the Reporting Jobs of an exported document."""
    document = json.loads(content)
    if not isinstance(document, dict) or document.get('format') != 'dashboard-analytic-reporting-jobs':
        raise ValueError('The file is not a Dashboard Analytic Reporting Jobs export.')
    # Datasets are matched by file name, since IDs differ between workspaces.
    source_names = {int(key): str(value) for key, value in (document.get('dataset_names') or {}).items() if str(key).isdigit()}
    destination = {}
    for row in task_repository.list_datasets():
        destination.setdefault(str(row['file_name']).casefold(), int(row['id']))
    mapping = {source_id: destination[name.casefold()] for source_id, name in source_names.items() if name.casefold() in destination}
    existing = {task['name'].casefold(): task['id'] for task in list_tasks(task_repository)}
    imported = 0
    for item in document.get('reporting_jobs') or []:
        if not isinstance(item, dict):
            continue
        schedule = dict(item.get('schedule') or {})
        if schedule.get('mode') == 'once' and next_run_after(normalize_schedule(schedule), now_local()) is None:
            schedule['mode'] = 'manual'  # A past single execution cannot be scheduled again.
        definition = _remap_dataset_ids(item.get('definition') or {}, mapping)
        save_task(task_repository, existing.get(str(item.get('name') or '').strip().casefold()),
                  {**item, 'definition': definition, 'schedule': schedule}, username,
                  parse_recipients=parse_recipients, invalid_recipients=invalid_recipients)
        imported += 1
    return imported


# ---------------------------------------------------------------------------
# Email body
# ---------------------------------------------------------------------------
def email_subject(task_name: str, started: datetime) -> str:
    return f'{task_name} · {started.strftime("%Y-%m-%d %H:%M")}'


def email_bodies(task_name: str, started: datetime, artifacts: list[dict[str, Any]], app_name: str) -> tuple[str, str]:
    """Plain-text and HTML bodies listing each artifact, its content and its filters."""
    attached = [item for item in artifacts if item.get('status') == 'ready']
    failed = [item for item in artifacts if item.get('status') != 'ready']
    text = [f'{task_name}', f'Generated by {app_name} on {started.strftime("%Y-%m-%d %H:%M %Z").strip()}.', '',
            f'Attached artifacts ({len(attached)}):']
    parts = [f'<p><strong>{html.escape(task_name)}</strong><br>Generated by {html.escape(app_name)} on '
             f'{html.escape(started.strftime("%Y-%m-%d %H:%M %Z").strip())}.</p>',
             f'<p><strong>Attached artifacts ({len(attached)})</strong></p><ol>']
    for item in attached:
        text.append(f"- {item['file_name']} — {item['title']}")
        text.extend(f'    {line}' for line in item.get('details') or [])
        details = ''.join(f'<li>{html.escape(line)}</li>' for line in item.get('details') or [])
        parts.append(f"<li><strong>{html.escape(item['title'])}</strong> · <code>{html.escape(item['file_name'])}</code>"
                     f"{f'<ul>{details}</ul>' if details else ''}</li>")
    parts.append('</ol>')
    if failed:
        text += ['', f'Not generated ({len(failed)}):'] + [f"- {item['title']}: {item.get('error') or 'failed'}" for item in failed]
        parts.append(f'<p><strong>Not generated ({len(failed)})</strong></p><ul>' + ''.join(
            f"<li>{html.escape(item['title'])}: {html.escape(item.get('error') or 'failed')}</li>" for item in failed) + '</ul>')
    return '\n'.join(text) + '\n', '<html><body style="font-family:Arial,sans-serif;font-size:14px">' + ''.join(parts) + '</body></html>'


def safe_file_name(value: str) -> str:
    """A portable file name of at most 150 characters that keeps its extension."""
    cleaned = re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', value)).strip()
    suffix = Path(cleaned).suffix if re.fullmatch(r'\.[A-Za-z0-9]{1,5}', Path(cleaned).suffix or '') else ''
    stem = cleaned[:len(cleaned) - len(suffix)] if suffix else cleaned
    return (stem[:150 - len(suffix)].rstrip(' .-') or 'artifact') + suffix


_LEADING_STAMP = re.compile(r'^\s*\d{8}_\d{6}\s*-\s*')


def artifact_path(folder: Path, stamp: str, module: str, name: str, suffix: str) -> Path:
    """``<yyyymmdd_hhmmss> - <Module> - <Report name><suffix>``, unique in ``folder``.

    The report name drops its own leading timestamps and module name, so a
    Dashboard or Scoring PPT does not repeat them.
    """
    report = str(name or '').strip()
    while _LEADING_STAMP.match(report):
        report = _LEADING_STAMP.sub('', report, count=1)
    report = re.sub(rf'^\s*{re.escape(module)}\s*(?:-\s*|$)', '', report, flags=re.IGNORECASE).strip(' -')
    base = f'{stamp} - {module}' + (f' - {report}' if report else '')
    candidate, copy = folder / safe_file_name(f'{base}{suffix}'), 2
    while candidate.exists():
        candidate, copy = folder / safe_file_name(f'{base} ({copy}){suffix}'), copy + 1
    return candidate


def run_stamp(run: dict[str, Any]) -> str:
    """The yyyymmdd_hhmmss timestamp of a run, as in its artifact names."""
    match = re.match(r'(\d{8}_\d{6})', Path(str(run.get('output_dir') or '')).name)
    if match:
        return match.group(1)
    for key in ('started_at', 'created_at'):
        try:
            return datetime.fromisoformat(str(run.get(key))).strftime('%Y%m%d_%H%M%S')
        except (TypeError, ValueError):
            continue
    return now_local().strftime('%Y%m%d_%H%M%S')


def zip_artifacts(run: dict[str, Any]) -> BytesIO:
    buffer = BytesIO()
    folder = Path(run['output_dir'])
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in run['artifacts']:
            path = folder / str(item.get('file_name') or '')
            if item.get('status') == 'ready' and path.is_file():
                archive.write(path, path.name)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Execution and routes
# ---------------------------------------------------------------------------
def install_report_task_routes(core: Any) -> None:
    from fastapi import Depends, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field

    app = core.app
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='reporting-jobs')
    # Runs of workspaces other than the active one each use their own worker process.
    worker_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='reporting-workers')
    # (workspace database, run ID): run IDs are only unique within a workspace.
    active_runs: set[tuple[str, int]] = set()
    active_lock = Lock()
    recovered_databases: set[str] = set()

    class ReportTaskPayload(BaseModel):
        name: str = ''
        definition: dict[str, Any] = Field(default_factory=dict)
        send_email: bool = False
        recipients: list[str] | str = Field(default_factory=list)
        schedule: dict[str, Any] = Field(default_factory=dict)
        enabled: bool = True

    def reporting_repository(user):
        if not core.active_workspace:
            raise HTTPException(409, 'Open a workspace before using Reporting.')
        core.require_workspace_access(user, core.active_workspace.id)
        return core.Repository(core.active_workspace.database_path, global_db_path=core.repository.global_db_path,
                               workspace_registry_db_path=core.workspace_registry.registry_path)

    def reporting_user(user=Depends(core.current_user)):
        return user

    def editor_user(user=Depends(core.current_user)):
        if user.role not in {'user-editor', 'admin', 'super-admin'}:
            raise HTTPException(403, 'Editor access is required to change Reporting Jobs.')
        return user

    def run_user(username: str):
        record = core.repository.get_user(username)
        return core.SessionUser(username=username, role=record.role if record else 'user-editor')

    def output_root() -> Path:
        return Path(core.settings.output_dir) / 'reporting'

    # -- artifact generators ------------------------------------------------
    def dataset_names(task_repository) -> dict[int, str]:
        return {int(row['id']): str(row['file_name']) for row in task_repository.list_datasets()}

    def generate_dataset_analysis(section, folder, stamp, username, names) -> list[dict[str, Any]]:
        artifacts = []
        for export_kind in section['formats']:
            suffix = 'docx' if export_kind == 'word' else 'pptx'
            title = f"CDR Analysis ({FORMAT_LABELS[export_kind]})"
            destination = artifact_path(folder, stamp, 'CDR Analysis', '', f'.{suffix}')
            try:
                filters = {CDR_ANALYSIS_FILTER_DIMENSIONS[field]: values for field, values in (section.get('filters') or {}).items()
                           if field in CDR_ANALYSIS_FILTER_DIMENSIONS}
                _path, reports, errors = core.write_dataset_summary(
                    section['dataset_ids'], export_kind, destination, username, filters=filters,
                    metrics=section.get('metrics') or None, aggregation=section.get('aggregation') or 'all',
                    cdf_grouping=section.get('cdf_grouping') or 'operator',
                )
                filter_text = '; '.join(f"{CDR_ANALYSIS_AGGREGATIONS.get(dimension, dimension.title())}: {', '.join(values)}"
                                        for dimension, values in filters.items()) or 'none'
                details = [f"Datasets ({len(reports)}): {', '.join(report['dataset_name'] for report in reports)}",
                           *[f"Metrics ({label}): {', '.join(section['metrics'][kind]) if (section.get('metrics') or {}).get(kind) else 'every metric'}"
                             for kind, label in CDR_ANALYSIS_KINDS.items()],
                           f"Filters: {filter_text}",
                           f"Aggregation: {CDR_ANALYSIS_AGGREGATIONS[section.get('aggregation') or 'all']} · "
                           f"CDF comparison: {CDR_ANALYSIS_CDF_GROUPINGS[section.get('cdf_grouping') or 'operator']}",
                           *[f'Skipped: {error}' for error in errors]]
                artifacts.append(ready_artifact('dataset_analysis', title, destination, details))
            except Exception as exc:
                artifacts.append(failed_artifact('dataset_analysis', title, exc))
        return artifacts

    def generate_network_insights(section, folder, stamp, index=1) -> list[dict[str, Any]]:
        from src.modules.network_insights_export import summary_selection_lines

        artifacts = []
        name = network_entry_name(section)
        for export_kind in section['formats']:
            suffix = 'docx' if export_kind == 'word' else 'pptx'
            title = f"Network Insights · {name} ({FORMAT_LABELS[export_kind]})"
            destination = artifact_path(folder, stamp, 'Network Insights', name, f'.{suffix}')
            try:
                description = core.write_network_insights_summary(section['selection'], export_kind, destination)
                artifacts.append(ready_artifact('network_insights', title, destination, summary_selection_lines(description)))
            except Exception as exc:
                artifacts.append(failed_artifact('network_insights', title, getattr(exc, 'detail', exc)))
        return artifacts

    def wait_for_dashboard_job(task_repository, job_id, run_id) -> Any:
        tools = core.dashboard_reporting
        deadline = time.monotonic() + DASHBOARD_JOB_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            row = tools.job(task_repository, job_id)
            if row is None:
                raise RuntimeError('The Dashboard PPT job was deleted.')
            if str(row['status']) == 'ready':
                return row
            if str(row['status']) in {'failed', 'stopped'}:
                raise RuntimeError(str(row['last_error'] or f"The Dashboard PPT job {row['status']}."))
            update_run(task_repository, run_id, message=f"Waiting for Dashboard PPT job {job_id} ({int(row['progress'] or 0)}%)")
            time.sleep(3)
        raise RuntimeError('The Dashboard PPT job did not finish within three hours.')

    def dashboard_details(serialized: dict[str, Any]) -> list[str]:
        cover = serialized.get('cover') or {}
        lines = [f"Template: {serialized.get('template') or '—'} · {serialized.get('nr_mode')} · {serialized.get('scope')}"]
        for label, key in (('Campaigns', 'campaigns'), ('Regions', 'regions'), ('Cities', 'cities')):
            if cover.get(key):
                value = cover[key]
                lines.append(f"{label}: {', '.join(value) if isinstance(value, list) else value}")
        lines.extend(str(item) for item in serialized.get('filters') or [])
        return lines

    def dashboard_definition(stored: dict[str, Any], entry: dict[str, Any], task_repository=None) -> dict[str, Any]:
        """The saved Dashboard with the artifact's Scope, CDRs, dates and filters."""
        definition = dict(stored)
        if entry.get('all_datasets') and task_repository is not None:
            nr_mode = 'SA' if str(stored.get('technology') or 'nsa').upper() == 'SA' else 'NSA'
            entry = {**entry, 'datasets': {
                kind: ids for kind in ('data', 'voice', 'speech')
                if (ids := sorted((int(row['id']) for row in task_repository.list_datasets()
                                   if row['status'] == 'ready' and str(row['dataset_kind']) == kind
                                   and core.dataset_nr_mode(row['dataset_kind'], row['nr_mode'], row['file_name']) == nr_mode), reverse=True))
            }}
            if not entry['datasets']:
                raise RuntimeError(f'There are no ready {nr_mode} CDRs.')
        definition.update({
            'scope': entry['scope'], 'vendor_comparison': entry['vendor_comparison'],
            'date_from': entry.get('date_from') or 'Oldest', 'date_to': entry.get('date_to') or 'Newest',
            'filters': dict(entry.get('filters') or {}),
        })
        if entry.get('datasets'):
            definition['datasets'] = entry['datasets']
        return definition

    def generate_dashboard(entry, task_repository, folder, stamp, user, run_id) -> dict[str, Any]:
        tools = core.dashboard_reporting
        stored = tools.list_dashboards(task_repository).get(entry['dashboard_id'])
        title = f"Dashboard · {entry.get('label') or (stored or {}).get('name') or entry['dashboard_id']}"
        try:
            if not isinstance(stored, dict):
                raise RuntimeError('The Dashboard no longer exists.')
            update_run(task_repository, run_id, message=f'Generating {title}')
            job_id = tools.queue_export(entry['dashboard_id'], user, dashboard_definition(stored, entry, task_repository))
            row = wait_for_dashboard_job(task_repository, job_id, run_id)
            source = Path(str(row['output_path']))
            # Dashboard PPT names start with their own generation time, which is dropped.
            destination = artifact_path(folder, stamp, 'E2E Dashboards', entry.get('label') or source.stem, source.suffix)
            shutil.copy2(source, destination)
            return ready_artifact('dashboards', title, destination, dashboard_details(tools.serialize_job(row)))
        except Exception as exc:
            return failed_artifact('dashboards', title, getattr(exc, 'detail', exc))

    def scoring_details(job: dict[str, Any], entry: dict[str, Any], names: dict[int, str]) -> list[str]:
        filters = job.get('context_filters') or {}
        lines = [f"NR Mode: {job.get('nr_mode') or '—'} · Aggregation: {' → '.join(job.get('levels') or ['Operator'])}",
                 f"CDRs: {', '.join(names.get(int(value), str(value)) for value in job.get('dataset_ids') or []) or '—'}"]
        lines.extend(f'{field}: {", ".join(values)}' for field, values in filters.items() if values)
        if entry.get('main_cities'):
            lines.append('City: Main Cities')
        lines.append(f"GAP reference: {job.get('baseline_operator') or entry.get('baseline_operator') or 'EE'}")
        return lines

    def generate_scoring(entry, task_repository, folder, stamp, username, names, run_id) -> dict[str, Any]:
        title = f"Scoring · {entry.get('label') or entry['nr_mode'] + ' ' + ' → '.join(entry['aggregation_levels'])}"
        try:
            dataset_ids = entry.get('dataset_ids') or []
            if not dataset_ids:
                candidates = [row for row in task_repository.list_datasets()
                              if row['status'] == 'ready' and str(row['dataset_kind']) in {'data', 'voice', 'speech'}
                              and core.dataset_nr_mode(row['dataset_kind'], row['nr_mode'], row['file_name']) == entry['nr_mode']]
                if not candidates:
                    raise RuntimeError(f"There are no ready {entry['nr_mode']} CDRs.")
                newest = max(candidates, key=lambda row: int(row['id']))
                dataset_ids = core.select_latest_companion_cdrs(task_repository, int(newest['id']))
            context_filters = dict(entry.get('context_filters') or {})
            if entry.get('main_cities'):
                context_filters['City'] = list(task_repository.list_main_cities())
            selected = core.validate_complete_scoring_cdr_selection(
                task_repository, dataset_ids, entry['nr_mode'], context_filters=context_filters)
            update_run(task_repository, run_id, message=f'Calculating {title}')
            job, cached = core.create_scoring_job(
                task_repository, selected, entry['aggregation_levels'], entry['nr_mode'], username=username,
                baseline_operator=entry.get('baseline_operator') or 'EE', context_filters=context_filters,
                scoring_profile_id=entry.get('scoring_profile_id') or None,
            )
            if not cached:
                core.run_scoring_job(task_repository, int(job['id']))
            content, filename, export_job = core.build_scoring_job_powerpoint(task_repository, int(job['id']))
            destination = artifact_path(folder, stamp, 'Scoring & GAP Analysis', entry.get('label') or Path(filename).stem, '.pptx')
            destination.write_bytes(content)
            return ready_artifact('scoring', title, destination, scoring_details(export_job, entry, names))
        except Exception as exc:
            return failed_artifact('scoring', title, exc)

    def generate_provider(key, provider, config, folder, stamp, user) -> list[dict[str, Any]]:
        try:
            return list(provider['generate'](config, folder, stamp, user))
        except Exception as exc:
            return [failed_artifact(key, provider['label'], exc)]

    def ready_artifact(module, title, path: Path, details: list[str]) -> dict[str, Any]:
        return {'module': module, 'title': title, 'file_name': path.name, 'size': path.stat().st_size,
                'status': 'ready', 'details': [line for line in details if line]}

    def failed_artifact(module, title, error) -> dict[str, Any]:
        return {'module': module, 'title': title, 'file_name': '', 'size': 0, 'status': 'failed', 'error': str(error)}

    def execute_run(database_path: str, run_id: int) -> None:
        task_repository = core.Repository(Path(database_path), global_db_path=core.repository.global_db_path,
                                          workspace_registry_db_path=core.workspace_registry.registry_path)
        run = get_run(task_repository, run_id)
        task = get_task(task_repository, run['task_id']) if run else None
        try:
            if run is None or task is None:
                return
            started = now_local()
            stamp = started.strftime('%Y%m%d_%H%M%S')
            folder = output_root() / f"{stamp} - {safe_file_name(task['name'])} - run {run_id}"
            folder.mkdir(parents=True, exist_ok=True)
            update_run(task_repository, run_id, status='running', started_at=started.isoformat(), output_dir=str(folder),
                       message='Generating artifacts', progress=1)
            if not core.active_workspace or Path(core.active_workspace.database_path).resolve() != Path(database_path).resolve():
                raise RuntimeError('The Reporting Job workspace is no longer the active workspace.')
            definition, user = task['definition'], run_user(task['created_by'])
            names = dataset_names(task_repository)
            steps: list[tuple[str, Any]] = []
            # Artifacts of modules the job owner can no longer use are reported, not generated.
            allowed = {module: core.user_has_feature(user, feature) for module, _label, feature in used_modules(definition)}
            for module, label, feature in used_modules(definition):
                if not allowed[module]:
                    steps.append((label, lambda module=module, label=label: [failed_artifact(module, label, f'{task["created_by"]} no longer has access to {label}.')]))
            definition = {**definition,
                          **{module: ({'enabled': False} if module == 'dataset_analysis' else [])
                             for module, permitted in allowed.items() if not permitted and module in MODULE_FEATURES},
                          'modules': {key: value for key, value in (definition.get('modules') or {}).items() if allowed.get(key)}}
            if definition.get('dataset_analysis', {}).get('enabled'):
                steps.append(('CDR Analysis', lambda: generate_dataset_analysis(definition['dataset_analysis'], folder, stamp, user.username, names)))
            for index, entry in enumerate(definition.get('network_insights') or [], start=1):
                steps.append(('Network Insights', lambda entry=entry, index=index: generate_network_insights(entry, folder, stamp, index)))
            for entry in definition.get('dashboards') or []:
                steps.append(('Dashboard', lambda entry=entry: [generate_dashboard(entry, task_repository, folder, stamp, user, run_id)]))
            for entry in definition.get('scoring') or []:
                steps.append(('Scoring', lambda entry=entry: [generate_scoring(entry, task_repository, folder, stamp, user.username, names, run_id)]))
            for key, config in (definition.get('modules') or {}).items():
                provider = ARTIFACT_PROVIDERS.get(key)
                if provider is None:
                    steps.append((key, lambda key=key: [failed_artifact(key, key, 'This module no longer provides Reporting artifacts.')]))
                else:
                    steps.append((provider['label'], lambda provider=provider, config=config, key=key: generate_provider(key, provider, config, folder, stamp, user)))
            artifacts: list[dict[str, Any]] = []
            for index, (label, step) in enumerate(steps):
                update_run(task_repository, run_id, message=f'Generating {label} ({index + 1}/{len(steps)})',
                           progress=max(1, round(index * 90 / max(len(steps), 1))))
                artifacts.extend(step())
                update_run(task_repository, run_id, artifacts=artifacts)
            ready = [item for item in artifacts if item['status'] == 'ready']
            email_status, error = '', ''
            if task['send_email'] and ready:
                update_run(task_repository, run_id, message='Sending the email', progress=95)
                try:
                    settings = core.email_delivery_settings(core.repository, include_password=True)
                    text, body = email_bodies(task['name'], started, artifacts, core.__app_name__)
                    core.send_email(settings, task['recipients'], email_subject(task['name'], started), text, body,
                                    [(item['file_name'], folder / item['file_name']) for item in ready])
                    email_status = f"Sent to {', '.join(task['recipients'])}"
                except Exception as exc:
                    email_status, error = 'Not sent', f'Email delivery failed: {exc}'
            elif task['send_email']:
                email_status = 'Not sent: no artifact was generated'
            failed = [item for item in artifacts if item['status'] != 'ready']
            if not ready:
                status = 'failed'
                error = error or '; '.join(f"{item['title']}: {item.get('error')}" for item in failed) or 'No artifact was generated.'
            elif error:
                status = 'failed'
            elif failed:
                status = 'partial'
            else:
                status = 'sent' if task['send_email'] else 'completed'
            message = {'sent': 'Artifacts generated and emailed', 'completed': 'Artifacts generated',
                       'partial': f'{len(failed)} of {len(artifacts)} artifacts failed', 'failed': 'The run failed'}[status]
            update_run(task_repository, run_id, status=status, message=message, progress=100, email_status=email_status,
                       error=error, finished_at=now_local().isoformat(), artifacts=artifacts)
            task_repository.try_add_log(task['created_by'], 'reporting_job_run', json.dumps({
                'task_id': task['id'], 'run_id': run_id, 'status': status, 'artifacts': len(ready), 'email': email_status,
            }))
        except Exception as exc:
            update_run(task_repository, run_id, status='failed', message='The run failed', progress=100,
                       error=str(exc), finished_at=now_local().isoformat())
        finally:
            with active_lock:
                active_runs.discard((str(Path(database_path).resolve()), run_id))

    def run_in_worker(workspace_id: str, database: str, run_id: int) -> None:
        """Run a job of a workspace that is not open in this process, without opening it for users."""
        import os
        import subprocess
        import sys

        try:
            command = [sys.executable, '-m', 'src.report_worker', '--workspace-id', workspace_id, '--run-id', str(run_id),
                       '--parent-pid', str(os.getpid()), '--global-db', str(core.repository.global_db_path),
                       '--workspace-registry-db', str(core.workspace_registry.registry_path)]
            exit_code = subprocess.run(command, cwd=core.PROJECT_ROOT, check=False).returncode
            task_repository = core.Repository(Path(database), global_db_path=core.repository.global_db_path,
                                              workspace_registry_db_path=core.workspace_registry.registry_path)
            run = get_run(task_repository, run_id)
            if run and run['status'] in {'queued', 'running'}:
                update_run(task_repository, run_id, status='failed', message='The run failed', progress=100,
                           error=f'The Reporting worker stopped unexpectedly (exit code {exit_code}).',
                           finished_at=now_local().isoformat())
        finally:
            with active_lock:
                active_runs.discard((database, run_id))

    def start_run(task_repository, task: dict[str, Any], trigger: str, username: str, workspace_id: str | None = None) -> int:
        run_id = create_run(task_repository, task, trigger, username)
        database = str(Path(task_repository.db_path).resolve())
        with active_lock:
            active_runs.add((database, run_id))
        active = core.active_workspace
        if workspace_id and not (active and str(Path(active.database_path).resolve()) == database):
            worker_executor.submit(run_in_worker, workspace_id, database, run_id)
        else:
            executor.submit(execute_run, database, run_id)
        return run_id

    def run_due_tasks(now: datetime | None = None) -> list[int]:
        """Start every due job of every workspace, open or not; returns the new run IDs."""
        started = []
        workspaces = list(core.workspace_registry.list())
        if core.active_workspace and all(item.id != core.active_workspace.id for item in workspaces):
            workspaces.append(core.active_workspace)
        for workspace in workspaces:
            if getattr(workspace, 'status', 'ready') not in {'ready', '', None} or not Path(workspace.database_path).is_file():
                continue
            task_repository = core.Repository(workspace.database_path, global_db_path=core.repository.global_db_path,
                                              workspace_registry_db_path=core.workspace_registry.registry_path)
            database = str(Path(task_repository.db_path).resolve())
            if database not in recovered_databases:
                with active_lock:
                    running = {run_id for run_database, run_id in active_runs if run_database == database}
                fail_interrupted_runs(task_repository, running)
                recovered_databases.add(database)
            started += [start_run(task_repository, task, 'schedule', task['created_by'], workspace.id)
                        for task in claim_due_tasks(task_repository, now or now_local())]
        return started

    def scheduler_loop(stop_event: Event) -> None:
        while not stop_event.wait(SCHEDULER_INTERVAL_SECONDS):
            try:
                run_due_tasks()
            except Exception as exc:  # The scheduler keeps running after a failed check.
                core.repository.try_add_log('system', 'reporting_scheduler_error', json.dumps({'error': str(exc)}))

    core.register_report_artifact_provider = register_report_artifact_provider
    core.report_task_scheduler_loop = scheduler_loop
    core.run_due_report_tasks = run_due_tasks
    core.execute_report_run = execute_run

    # -- options ------------------------------------------------------------
    def reporting_options(task_repository, user) -> dict[str, Any]:
        from src.modules.e2e_dashboards import ADAPTATIVE_FILTER_FIELDS

        datasets = [
            {'id': int(row['id']), 'file_name': str(row['file_name']), 'kind': str(row['dataset_kind']),
             'nr_mode': core.dataset_nr_mode(row['dataset_kind'], row['nr_mode'], row['file_name'])}
            for row in task_repository.list_datasets()
            if row['status'] == 'ready' and str(row['dataset_kind']) in {'data', 'voice', 'speech'}
        ]
        datasets.sort(key=lambda item: item['id'], reverse=True)
        tools = getattr(core, 'dashboard_reporting', None)
        dashboards = []
        if tools is not None:
            for dashboard_id, stored in tools.list_dashboards(task_repository).items():
                if not isinstance(stored, dict):
                    continue
                dashboards.append({
                    'id': dashboard_id, 'name': str(stored.get('name') or dashboard_id),
                    'template': str(stored.get('template') or ''), 'scope': str(stored.get('scope') or 'single'),
                    'vendor_comparison': str(stored.get('vendor_comparison') or 'operator_vendor'),
                    'technology': str(stored.get('technology') or 'nsa'), 'datasets': stored.get('datasets') or {},
                    'filters': stored.get('filters') or {}, 'custom_fields': stored.get('custom_fields') or [],
                    'date_from': str(stored.get('date_from') or ''), 'date_to': str(stored.get('date_to') or ''),
                })
        dashboards.sort(key=lambda item: item['name'].casefold())
        try:
            profiles = task_repository.get_scoring_profiles()
            methodologies = [{'id': profile['id'], 'name': profile.get('name') or profile['id']} for profile in profiles['profiles']]
            active_methodology = profiles['active_profile_id']
        except ValueError:
            methodologies, active_methodology = [], ''
        catalogue = task_repository.cdr_catalogue_values()
        return {
            'allowed_modules': {module: core.user_has_feature(user, feature) for module, feature in MODULE_FEATURES.items()},
            'providers': [provider_options(key, provider, user)
                          for key, provider in ARTIFACT_PROVIDERS.items() if core.user_has_feature(user, provider['feature'])],
            'datasets': datasets, 'dashboards': dashboards,
            'dashboard_filter_fields': list(ADAPTATIVE_FILTER_FIELDS),
            'main_cities': list(task_repository.list_main_cities()),
            'methodologies': methodologies, 'active_methodology': active_methodology,
            'values': {'Operator': catalogue.get('operators', []), 'Operator_Vendor': sort_vendor_values(catalogue.get('vendors', [])),
                       'Vendor': sort_vendor_values(catalogue.get('vendors_only', [])), 'Region': catalogue.get('regions', []),
                       'Cluster': catalogue.get('clusters', []), 'City': catalogue.get('cities', []),
                       'Campaign': catalogue.get('campaigns', [])},
            'scoring_levels': list(SCORING_LEVELS), 'formats': list(REPORT_FORMATS),
            # CDR Analysis: the metrics of the ready CDRs, and its aggregation and CDF comparison choices.
            'cdr_metrics': {kind: list(dict.fromkeys(
                metric for dataset in datasets if dataset['kind'] == kind
                for metric in core.analysis_metric_columns(task_repository.list_dataset_row_columns(dataset['id']), kind)
            )) for kind in CDR_ANALYSIS_KINDS},
            'cdr_kinds': CDR_ANALYSIS_KINDS,
            'cdr_aggregations': CDR_ANALYSIS_AGGREGATIONS, 'cdr_cdf_groupings': CDR_ANALYSIS_CDF_GROUPINGS,
            'network_groupings': {'operator': 'Operator', 'vendor': 'Vendor', 'region': 'Region', 'cluster': 'Cluster', 'city': 'City',
                                  'kind': 'CDR type', 'campaign': 'Campaign'},
            'technologies': {'lte': 'LTE', 'nr': 'NR', 'lte_nr': 'LTE+NR'},
            'email_configured': bool(core.email_delivery_settings(core.repository).get('configured')),
            'timezone': now_local().strftime('%Z (UTC%z)'),
        }

    def provider_options(key, provider, user) -> dict[str, Any]:
        values = {}
        if callable(provider.get('values')):
            try:
                values = provider['values'](user) or {}
            except Exception:  # noqa: BLE001 - a provider without values still offers its formats.
                values = {}
        return {'key': key, 'label': provider['label'], 'formats': list(provider['formats']),
                'filters': [{'key': name, 'label': text} for name, text in provider.get('filters') or ()],
                'settings': list(provider.get('settings') or ()), 'values': values}

    def serialize_task(task, runs_by_id, dashboard_names) -> dict[str, Any]:
        last = runs_by_id.get(task['last_run_id']) if task['last_run_id'] else None
        return {**task, 'artifacts': artifact_labels(task['definition'], dashboard_names), 'last_run': last}

    # -- routes -------------------------------------------------------------
    @app.get('/reporting', response_class=HTMLResponse)
    def reporting_jobs_page(request: Request, user=Depends(reporting_user)):
        reporting_repository(user)
        return core.render_template(request, 'report_jobs.html', {'user': user})

    @app.get('/api/reporting/state')
    def reporting_jobs_state(user=Depends(reporting_user)):
        task_repository = reporting_repository(user)
        runs = list_runs(task_repository, limit=200)
        runs_by_id = {run['id']: run for run in runs}
        missing = [task['last_run_id'] for task in list_tasks(task_repository) if task['last_run_id'] and task['last_run_id'] not in runs_by_id]
        for run_id in missing:
            if (run := get_run(task_repository, run_id)) is not None:
                runs_by_id[run_id] = run
        tools = getattr(core, 'dashboard_reporting', None)
        dashboard_names = {str(key): str(value.get('name') or key) for key, value in tools.list_dashboards(task_repository).items()
                           if isinstance(value, dict)} if tools is not None else {}
        return {
            'tasks': [serialize_task(task, runs_by_id, dashboard_names) for task in list_tasks(task_repository)],
            'runs': runs, 'can_edit': user.role in {'user-editor', 'admin', 'super-admin'},
        }

    @app.get('/api/reporting/options')
    def reporting_jobs_options(user=Depends(reporting_user)):
        return reporting_options(reporting_repository(user), user)

    def save_route(task_id, payload, user):
        task_repository = reporting_repository(user)
        try:
            definition = normalize_definition(payload.definition)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # A Reporting Job only includes artifacts of the modules its author can use.
        forbidden = [label for _module, label, feature in used_modules(definition) if not core.user_has_feature(user, feature)]
        if forbidden:
            raise HTTPException(403, f"Your account cannot include artifacts of: {', '.join(forbidden)}.")
        try:
            task = save_task(task_repository, task_id, payload.model_dump(), user.username,
                             parse_recipients=core.parse_recipients, invalid_recipients=core.invalid_recipients)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        task_repository.try_add_log(user.username, 'save_reporting_job', json.dumps({'task_id': task['id'], 'name': task['name']}))
        return {'task': task}

    @app.post('/api/reporting/tasks')
    def reporting_jobs_create(payload: ReportTaskPayload, user=Depends(editor_user)):
        return save_route(None, payload, user)

    @app.put('/api/reporting/tasks/{task_id}')
    def reporting_jobs_update(task_id: int, payload: ReportTaskPayload, user=Depends(editor_user)):
        return save_route(task_id, payload, user)

    @app.post('/api/reporting/tasks/{task_id}/duplicate')
    def reporting_jobs_duplicate(task_id: int, user=Depends(editor_user)):
        task_repository = reporting_repository(user)
        task = get_task(task_repository, task_id)
        if task is None:
            raise HTTPException(404, 'Reporting Job not found.')
        names = {item['name'].casefold() for item in list_tasks(task_repository)}
        name, copy = f"{task['name']} (copy)", 2
        while name.casefold() in names:
            name, copy = f"{task['name']} (copy {copy})", copy + 1
        schedule = task['schedule'] if task['schedule'].get('mode') != 'once' or next_run_after(task['schedule'], now_local()) else {**task['schedule'], 'mode': 'manual'}
        payload = ReportTaskPayload(name=name, definition=task['definition'], send_email=task['send_email'],
                                    recipients=task['recipients'], schedule=schedule, enabled=False)
        return save_route(None, payload, user)

    @app.delete('/api/reporting/tasks/{task_id}')
    def reporting_jobs_delete(task_id: int, user=Depends(editor_user)):
        task_repository = reporting_repository(user)
        try:
            folders = delete_task(task_repository, task_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        root = output_root().resolve()
        for folder in folders:
            path = Path(folder).resolve()
            if root in path.parents:
                shutil.rmtree(path, ignore_errors=True)
        task_repository.try_add_log(user.username, 'delete_reporting_job', json.dumps({'task_id': task_id}))
        return {'deleted': task_id}

    @app.post('/api/reporting/tasks/{task_id}/run')
    def reporting_jobs_run_now(task_id: int, user=Depends(editor_user)):
        task_repository = reporting_repository(user)
        task = get_task(task_repository, task_id)
        if task is None:
            raise HTTPException(404, 'Reporting Job not found.')
        run_id = start_run(task_repository, task, 'manual', user.username)
        task_repository.try_add_log(user.username, 'run_reporting_job', json.dumps({'task_id': task_id, 'run_id': run_id}))
        return {'run_id': run_id}

    @app.post('/api/reporting/tasks/{task_id}/enabled')
    async def reporting_jobs_enable(task_id: int, request: Request, user=Depends(editor_user)):
        body = await request.json()
        task_repository = reporting_repository(user)
        task = get_task(task_repository, task_id)
        if task is None:
            raise HTTPException(404, 'Reporting Job not found.')
        payload = ReportTaskPayload(name=task['name'], definition=task['definition'], send_email=task['send_email'],
                                    recipients=task['recipients'], schedule=task['schedule'], enabled=bool(body.get('enabled')))
        return save_route(task_id, payload, user)

    def run_or_404(task_repository, run_id):
        run = get_run(task_repository, run_id)
        if run is None:
            raise HTTPException(404, 'Reporting run not found.')
        return run

    @app.get('/api/reporting/runs/{run_id}/download')
    def reporting_jobs_download_run(run_id: int, user=Depends(reporting_user)):
        run = run_or_404(reporting_repository(user), run_id)
        ready = [item for item in run['artifacts'] if item.get('status') == 'ready' and (Path(run['output_dir']) / item['file_name']).is_file()]
        if not ready:
            raise HTTPException(404, 'This run has no artifacts to download.')
        name = safe_file_name(f"{run_stamp(run)} - Reporting - {run['task_name']}")
        return StreamingResponse(zip_artifacts(run), media_type='application/zip',
                                 headers={'Content-Disposition': f'attachment; filename="{name}.zip"'})

    @app.get('/api/reporting/runs/{run_id}/artifacts/{index}')
    def reporting_jobs_download_artifact(run_id: int, index: int, user=Depends(reporting_user)):
        run = run_or_404(reporting_repository(user), run_id)
        if not 0 <= index < len(run['artifacts']) or run['artifacts'][index].get('status') != 'ready':
            raise HTTPException(404, 'Artifact not found.')
        path = Path(run['output_dir']) / run['artifacts'][index]['file_name']
        if not path.is_file():
            raise HTTPException(404, 'The artifact file is no longer available.')
        return FileResponse(path, filename=path.name)

    @app.delete('/api/reporting/runs/{run_id}')
    def reporting_jobs_delete_run(run_id: int, user=Depends(editor_user)):
        task_repository = reporting_repository(user)
        run = run_or_404(task_repository, run_id)
        if run['status'] in {'queued', 'running'}:
            raise HTTPException(409, 'Wait for the run to finish before deleting it.')
        with task_repository.connection() as connection:
            connection.execute(f'DELETE FROM {REPORT_TASK_RUNS_TABLE} WHERE id = ?', (run_id,))
        path = Path(run['output_dir']).resolve() if run['output_dir'] else None
        if path and output_root().resolve() in path.parents:
            shutil.rmtree(path, ignore_errors=True)
        return JSONResponse({'deleted': run_id})
