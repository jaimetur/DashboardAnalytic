from __future__ import annotations

import json
import io
import os
import errno
import gc
import sys
try:
    import resource
except ImportError:  # pragma: no cover - Windows does not expose resource.
    resource = None
import re
import secrets
import hashlib
import shutil
import sqlite3
import warnings
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Annotated
from typing import Any, Iterable
from typing import Callable
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import QueryParams
from starlette.requests import ClientDisconnect
from starlette.background import BackgroundTask

DEFAULT_TRANSFER_PORT = 7278

from src.config import PROJECT_ROOT, settings
from src.modules.analytics import build_analysis
from src.modules.auth import SessionUser, verify_password
from src.modules.cdr_reporting import CATALOG_HEADERS, CHART_TYPES, HOVER_TARGETS_VERSION, STRUCTURAL_SLIDE_TYPES, TEMPLATE_NAMES, CatalogEntry, _legend_dimensions, active_catalog_path, assign_cdr_vendors, calculated_dimensions_json, catalog_chart_hover_targets, catalogue_csv, classify_sessions, convert_catalog_csv, ensure_report_vendor_group, enrich_multivendor, is_empty_catalog_chart, load_catalog_csv, materialize_calculated_dimensions, parse_calculated_dimensions, parse_catalog_csv, parse_catalog_filters, parse_catalog_grouping, parse_legend_position, prepare_catalog_chart_preview_frame, preview_catalog_chart_data, render_catalog_chart_preview, render_cdr_report, render_unavailable_source_chart
from src.modules.exports import POWERPOINT_EXPORT_VERSION, export_powerpoint_report, export_word_report
from src.modules.ingestion import CDR_IGNORED_SHEET_KEYS, add_three_gcid_column, add_vfuk_gcid_column, get_excel_sheet_columns, infer_dataset_kind, load_dataset, summarise_dataset
from src.modules.repository import Repository, WORKSPACE_REGISTRY_TABLE
from src.modules.workspaces import Workspace, WorkspaceRegistry
from src.version import __app_name__, __release_date__, __version__
from src.utils.filesystem import ensure_directories, safe_join


SESSION_COOKIE = 'bench_automations_session'
SESSIONS: dict[str, SessionUser] = {}
ANALYSIS_CACHE: dict[str, dict[str, Any]] = {}
DATAFRAME_CACHE: dict[str, pd.DataFrame] = {}
CHART_PREVIEW_DATA_CACHE: dict[str, tuple[pd.DataFrame, dict[str, Any]]] = {}
CHART_PREVIEW_FRAME_CACHE: dict[str, pd.DataFrame] = {}
CHART_PREVIEW_FILTER_CACHE: dict[str, pd.DataFrame] = {}
CHART_PREVIEW_CACHE_LOCK = Lock()
STOP_REQUESTS: set[int] = set()
STOP_REQUESTS_LOCK = Lock()
DATASET_PROCESSING_LOCKS: dict[str, Lock] = {}
DATASET_PROCESSING_LOCKS_LOCK = Lock()
REPORT_CHART_JOB_LOCKS: dict[str, Lock] = {}
REPORT_CHART_JOB_LOCKS_LOCK = Lock()
TEMPLATE_SAVE_LOCK = Lock()
EXPORT_JOBS: dict[str, dict[str, Any]] = {}
EXPORT_JOBS_LOCK = Lock()
IMPORT_UPLOADS: dict[str, dict[str, Any]] = {}
IMPORT_JOBS: dict[str, dict[str, Any]] = {}
IMPORT_JOBS_LOCK = Lock()
AUTO_CALCULATED_FIELD_JOBS: dict[str, dict[str, Any]] = {}
AUTO_CALCULATED_FIELD_JOBS_LOCK = Lock()
AUTO_CALCULATED_FIELD_WORKSPACE_LOCKS: dict[str, Lock] = {}
AUTO_CALCULATED_FIELD_WORKSPACE_LOCKS_LOCK = Lock()
WORKSPACE_DIMENSION_MATERIALIZATION_THREADS: set[str] = set()
WORKSPACE_DIMENSION_MATERIALIZATION_THREADS_LOCK = Lock()
TRANSFER_JOBS: dict[str, dict[str, Any]] = {}
TRANSFER_OFFERS: dict[str, dict[str, Any]] = {}
TRANSFER_LOCK = Lock()
WORKSPACE_LIFECYCLE_JOBS: dict[str, dict[str, Any]] = {}
WORKSPACE_LIFECYCLE_JOBS_LOCK = Lock()
EXPORT_PACKAGE_TTL = timedelta(hours=24)
TRANSFER_OFFER_TTL = timedelta(minutes=15)
DEFAULT_SLIDES_TEMPLATES_DIR = settings.slides_templates_dir
application_config_dir = settings.database_path.parent


def _reporting_memory_mb() -> float:
    """Return the process high-water RSS in MB for render diagnostics."""
    if resource is None:
        return 0.0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1024 * 1024 if sys.platform == 'darwin' else 1024), 1)


def legacy_workspace_registry_path() -> Path:
    """Return the workspace registry location."""
    return application_config_dir / 'workspace-registry.db'


repository = Repository(settings.database_path)
workspace_registry = WorkspaceRegistry(
    settings.input_dir.parent / 'workspaces' / 'workspace-registry.db',
    settings.input_dir.parent,
    settings.slides_templates_dir,
    legacy_workspace_registry_path(),
)
repository.set_workspace_registry_database(workspace_registry.registry_path)
active_workspace: Workspace | None = None
_workspace_size_cache: dict[str, tuple[float, int]] = {}
_workspace_size_cache_lock = Lock()
_WORKSPACE_SIZE_CACHE_SECONDS = 15.0
FILTER_DIMENSIONS = ['market', 'period', 'operator', 'vendor', 'test_name', 'region', 'city', 'session_type', 'direction', 'technology_primary', 'source_sheet']
FILTER_DIMENSIONS_BY_KIND = {
    'voice': ['market', 'operator', 'vendor', 'region', 'city', 'session_type', 'technology_primary', 'source_sheet'],
    'speech': ['market', 'operator', 'vendor', 'region', 'city', 'session_type', 'technology_primary', 'source_sheet'],
    'data': ['market', 'operator', 'vendor', 'test_name', 'region', 'city', 'direction', 'technology_primary', 'source_sheet'],
    'generic': ['market', 'operator', 'vendor', 'region', 'city', 'source_sheet'],
}
COMMON_ANALYSIS_COLUMNS = [
    'dataset_kind', 'source_file', 'market', 'period', 'operator', 'vendor', 'test_name', 'region', 'city',
    'session_type', 'direction', 'technology_primary', 'source_sheet', 'event_start_time', 'status',
    'success', 'failure', 'dropped',
]
KIND_ANALYSIS_COLUMNS = {
    'voice': ['disturbed', 'impaired', 'setup_time_seconds', 'duration_seconds', 'quality_score', 'handovers'],
    'speech': ['disturbed', 'impaired', 'quality_score', 'latency_ms', 'jitter_ms', 'packet_loss_pct', 'handovers', 'LQ'],
    'data': ['setup_time_seconds', 'duration_seconds', 'throughput_mbps', 'latency_ms', 'handovers', 'DNS_Resolution_Success_Ratio', 'DNS_Resolution_Success', 'DNS_Resolution_Attempts'],
    'generic': ['quality_score'],
}
STATUS_LABELS = {
    'queued': 'Queued',
    'processing': 'Processing',
    'ready': 'Processed',
    'failed': 'Failed',
    'stopped': 'Stopped',
}
INPUT_KIND_LABELS = {
    'voice': 'CDR-Voice',
    'speech': 'CDR-Speech',
    'data': 'CDR-Data',
    'mapping_vodafone': 'Multivendor Mapping — Vodafone UK (VFUK)',
    'mapping_three': 'Multivendor Mapping — Three UK (3UK)',
    'smart_orchestrator_logs': 'Smart Orchestrator Logs',
    'generic': 'Other',
}
UPLOAD_DATASET_KINDS = frozenset({'data', 'voice', 'speech', 'mapping_vodafone', 'mapping_three', 'smart_orchestrator_logs', 'generic'})
CDR_DATASET_KINDS = frozenset({'data', 'voice', 'speech'})
CDR_PREVIEW_FILTER_DEFINITIONS = (
    ('cdr_operator', 'Operator', ('operator', 'Operator')),
    ('cdr_vendor', 'Vendor', ('vendor', 'Vendor')),
    ('cdr_rat', 'RAT', ('RAT_A', 'RAT', 'Sample_RAT_A')),
    ('cdr_session_type', 'Session Type', ('Session_Type', 'session_type', 'Type_of_Test')),
    ('cdr_call_status', 'Call Status', ('Call_Status', 'call_status', 'status')),
)
LEGACY_VENDOR_MAPPING_FAILURE_MARKERS = (
    'to assign vendors',
    'assign vendors',
    'duplicate column name: vendor_2',
)
DATASET_NORMALIZATION_VERSION = 6
MAPPING_PREVIEW_NORMALIZED_COLUMNS = frozenset({
    'dataset_kind', 'source_file', 'source_sheet', 'campaign', 'market', 'period', 'campaign_year', 'campaign_quarter',
    'operator', 'session_type', 'test_name', 'direction', 'region', 'city', 'vendor', 'status',
    'disturbed', 'impaired', 'dropped', 'unsustainable_call', 'success', 'failure',
    'event_start_time', 'event_end_time', 'hour_bucket', 'day_bucket', 'setup_time_seconds',
    'duration_seconds', 'quality_score', 'throughput_mbps', 'latency_ms', 'packet_loss_pct',
    'jitter_ms', 'handovers', 'technology_primary', 'technology_secondary',
})


def is_mapping_preview_normalized_column(column: object) -> bool:
    """Hide normalized fields, including SQLite's collision-safe ``__2`` names."""
    source_name = str(column).strip()
    # These are source mapping headers. The generated lower-case ``vendor``
    # becomes ``vendor__2`` when SQLite keeps both names case-insensitively.
    if source_name in {'Vendor', 'OP/ Vendor', 'OP_Vendor'}:
        return False
    normalized = source_name.casefold()
    if normalized.startswith('unnamed'):
        return True
    base, separator, suffix = normalized.rpartition('__')
    if separator and suffix.isdigit():
        normalized = base
    return normalized in MAPPING_PREVIEW_NORMALIZED_COLUMNS


def format_preview_gcid(value: object) -> object:
    """Render GCID as an identifier rather than a floating-point measurement."""
    if value is None or pd.isna(value):
        return ''
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(numeric_value)) if numeric_value.is_integer() else str(value)


def materialize_cdr_derived_columns(
    frame: pd.DataFrame,
    dataset_kind: str | None = None,
    dimensions: Iterable[Any] | None = None,
) -> pd.DataFrame:
    """Add the generic attempt metric and the active workspace dimensions."""
    result = frame.copy()
    # A CDR can legitimately contain only categorical attempt outcomes. Keep
    # it importable and analyzable by exposing its count when no measured KPI
    # is available, without adding this reporting-only field to generic data.
    result['attempt_count'] = pd.Series(1, index=result.index, dtype='Int64')
    if dataset_kind in CDR_DATASET_KINDS:
        result = materialize_calculated_dimensions(
            result,
            tuple(dimensions) if dimensions is not None else load_workspace_calculated_dimensions(),
            f'cdr-{dataset_kind}',
        )
    return result
HELP_HOME_DOCUMENT = '00-help.md'
HELP_NAVIGATION_DOCUMENTS = (
    HELP_HOME_DOCUMENT,
    '01-overview.md',
    '02-technical-considerations.md',
    '03-configuration.md',
    '04-web-interface.md',
    '05-workspace-management.md',
    '06-e2e-dashboard.md',
    '07-e2e-reporting.md',
    '08-chart-builder.md',
    '09-administration.md',
    '10-docker-deployment.md',
    '11-project-structure.md',
    '12-roadmap.md',
)
HELP_DOCUMENT_LABELS = {
    '01-overview.md': 'Product Overview',
    '02-technical-considerations.md': 'Technical Considerations',
    '06-e2e-dashboard.md': 'E2E Dashboard',
    '07-e2e-reporting.md': 'E2E Reporting',
    '08-chart-builder.md': 'Chart Builder',
    '05-workspace-management.md': 'Workspace Management',
}


def help_document_number(relative_path: str) -> str | None:
    match = re.match(r'^(\d+)[-_]', Path(relative_path).name)
    return match.group(1) if match else None


def help_document_label(relative_path: str) -> str:
    stem = re.sub(r'^\d+[-_\s]*', '', Path(relative_path).stem)
    return stem.replace('-', ' ').replace('_', ' ').title()


def default_report_slides_template_path(
    technology: str,
    template_name: str | None = None,
) -> Path:
    """Return the current default CSV, whose filename follows the promoted template."""
    default_name = str(template_name or f'{technology.upper()} Slide Template').strip()
    filename = template_filename(default_name)
    return settings.slides_templates_dir / 'default' / technology / filename


def catalogue_registry_key(name: str) -> str:
    """Use the visible template name as the persistent JSON key."""
    name = str(name or '').strip()
    template_filename(name)
    return name


def template_filename(name: str) -> str:
    """Return the human-facing CSV filename without normalising its display name."""
    template_name = str(name or '').strip()
    if not template_name or template_name in {'.', '..'} or Path(template_name).name != template_name:
        raise ValueError('Template names cannot contain a path or be empty.')
    return f'{template_name}.csv'


def template_download_filename(name: str) -> str:
    """Return the CSV filename shown to the user when exporting a template."""
    return template_filename(name).replace('"', '')


def atomic_write_template(path: Path, content: bytes) -> None:
    """Replace a template CSV atomically, never exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _normalise_catalogue_dimension_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value).casefold())


def default_calculated_dimensions() -> list[dict[str, object]]:
    """Load editable starter definitions from configuration rather than code."""
    path = PROJECT_ROOT / 'assets' / 'default-calculated-dimensions.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def load_workspace_calculated_dimensions(*, create: bool = True):
    """Load the active workspace definitions, migrating the former template sidecars once."""
    if not active_workspace:
        return ()
    if create and repository.get_workspace_state('calculated_dimensions_initialized') != '1':
        migrated: dict[str, dict[str, object]] = {}
        for path in settings.slides_templates_dir.rglob('*.dimensions.json'):
            try:
                for item in json.loads(path.read_text(encoding='utf-8')):
                    migrated.setdefault(_normalise_catalogue_dimension_name(item.get('name', '')), item)
            except (OSError, ValueError, TypeError):
                continue
        payload = list(migrated.values()) or default_calculated_dimensions()
        dimensions = parse_calculated_dimensions(payload)
        repository.replace_calculated_dimensions(calculated_dimensions_json(dimensions))
        repository.set_workspace_state('calculated_dimensions_need_materialization', '1')
    for path in settings.slides_templates_dir.rglob('*.dimensions.json'):
        path.unlink(missing_ok=True)
    return parse_calculated_dimensions(repository.list_calculated_dimensions())


def load_repository_calculated_dimensions(task_repository: Repository) -> tuple[Any, ...]:
    """Load definitions from a job-bound repository while preserving first-use defaults."""
    payload = task_repository.list_calculated_dimensions()
    if not payload and task_repository.get_workspace_state('calculated_dimensions_initialized') != '1':
        dimensions = parse_calculated_dimensions(default_calculated_dimensions())
        task_repository.replace_calculated_dimensions(calculated_dimensions_json(dimensions))
        return dimensions
    return parse_calculated_dimensions(payload)


def write_workspace_calculated_dimensions(payload: object) -> tuple:
    dimensions = parse_calculated_dimensions(payload)
    repository.replace_calculated_dimensions(calculated_dimensions_json(dimensions))
    return dimensions


def calculated_dimension_rename_map(
    payload: object, previous: Iterable[Any], dimensions: Iterable[Any],
) -> dict[str, str]:
    """Resolve explicitly supplied and unambiguous calculated-dimension renames."""
    previous_by_key = {_normalise_catalogue_dimension_name(item.name): item.name for item in previous}
    current_by_key = {_normalise_catalogue_dimension_name(item.name): item.name for item in dimensions}
    renames: dict[str, str] = {
        old_name: current_by_key[key]
        for key, old_name in previous_by_key.items()
        if key in current_by_key and old_name != current_by_key[key]
    }
    removed = [name for key, name in previous_by_key.items() if key not in current_by_key]
    added = [name for key, name in current_by_key.items() if key not in previous_by_key]
    if len(removed) == len(added) == 1:
        renames[removed[0]] = added[0]
    requested = payload.get('renames', []) if isinstance(payload, dict) else []
    if not isinstance(requested, list):
        raise ValueError('Auto-calculated field renames must be a list.')
    for item in requested:
        if not isinstance(item, dict):
            raise ValueError('Each auto-calculated field rename must be an object.')
        old_name = str(item.get('from') or '').strip()
        new_name = str(item.get('to') or '').strip()
        old_key = _normalise_catalogue_dimension_name(old_name)
        new_key = _normalise_catalogue_dimension_name(new_name)
        if not old_key or not new_key or old_key not in previous_by_key or new_key not in current_by_key:
            raise ValueError('An auto-calculated field rename does not match the saved definitions.')
        renames[previous_by_key[old_key]] = current_by_key[new_key]
    return {old_name: new_name for old_name, new_name in renames.items() if old_name != new_name}


def rename_calculated_dimension_template_references(renames: dict[str, str]) -> int:
    """Rename calculated fields in every stored Slides Template of the workspace."""
    if not renames:
        return 0

    def renamed_value(value: str, old_name: str, new_name: str) -> str:
        return new_name if _normalise_catalogue_dimension_name(value) == _normalise_catalogue_dimension_name(old_name) else value

    def renamed_grouping(value: str, old_name: str, new_name: str) -> str:
        parts = [part.strip() for part in re.split(r'\s*(?:×|x)\s*', value) if part.strip()]
        return ' × '.join(renamed_value(part, old_name, new_name) for part in parts) if parts else value

    condition_pattern = re.compile(r'^(?P<column>.+?)\s+(?P<operator>NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(?P<value>.+)$', re.I)

    def renamed_filters(value: str, old_name: str, new_name: str) -> str:
        clauses: list[str] = []
        for clause in str(value).split(';'):
            match = condition_pattern.match(clause.strip())
            if not match:
                clauses.append(clause.strip())
                continue
            column = renamed_value(match.group('column').strip(), old_name, new_name)
            clauses.append(f"{column} {match.group('operator')} {match.group('value')}")
        return '; '.join(clause for clause in clauses if clause)

    def renamed_entry(entry: CatalogEntry) -> CatalogEntry:
        updated = entry
        for old_name, new_name in renames.items():
            updated = replace(
                updated,
                kpi=renamed_value(updated.kpi, old_name, new_name),
                filters=renamed_filters(updated.filters, old_name, new_name),
                grouping_rows=renamed_grouping(updated.grouping_rows, old_name, new_name),
                grouping_columns=renamed_grouping(updated.grouping_columns, old_name, new_name),
                legend=renamed_grouping(updated.legend, old_name, new_name),
            )
        return updated

    pending_writes: dict[Path, bytes] = {}
    changed_templates = 0
    for technology in TEMPLATE_NAMES:
        for template in report_catalogue_options(technology):
            entries = load_catalog_csv(template['path'], technology, validate_filters=False)
            updated_entries = [renamed_entry(entry) for entry in entries]
            if updated_entries == entries:
                continue
            content = catalogue_csv(updated_entries)
            pending_writes[Path(template['path'])] = content
            if template['active']:
                pending_writes[named_catalogue_path(technology, template['identifier'], template['identifier'])] = content
            changed_templates += 1
    with TEMPLATE_SAVE_LOCK:
        for path, content in pending_writes.items():
            atomic_write_template(path, content)
    return changed_templates


def load_template_catalogue(catalogue_path: Path, technology: str, *, validate_filters: bool = True, task_repository: Repository | None = None):
    dimensions = load_repository_calculated_dimensions(task_repository) if task_repository else load_workspace_calculated_dimensions()
    return [
        replace(entry, calculated_dimensions=dimensions)
        for entry in load_catalog_csv(catalogue_path, technology, validate_filters=validate_filters)
    ]


def materialize_workspace_calculated_dimensions(
    previous_names: Iterable[str] = (), task_repository: Repository | None = None,
    affected_sources: Iterable[str] = (),
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> int:
    """Rebuild auto-calculated columns for the affected CDR types."""
    task_repository = task_repository or repository
    dimensions = parse_calculated_dimensions(task_repository.list_calculated_dimensions())
    removable = {_normalise_catalogue_dimension_name(name) for name in previous_names}
    selected_sources = {
        str(source).casefold().removeprefix('cdr-') for source in affected_sources if str(source).strip()
    }
    all_datasets = [
        row for row in task_repository.list_datasets()
        if row['status'] == 'ready' and str(row['dataset_kind'] or '').casefold() in CDR_DATASET_KINDS
    ]
    datasets = [
        row for row in all_datasets
        if not selected_sources or str(row['dataset_kind'] or '').casefold() in selected_sources
    ]
    total_steps = max(len(datasets) * 2, 1)
    completed_steps = 0
    for dataset in datasets:
        dataset_id = int(dataset['id'])
        kind = str(dataset['dataset_kind']).casefold()
        columns = task_repository.list_dataset_row_columns(dataset_id)
        frame = task_repository.load_dataset_rows(dataset_id, columns, {})
        generated_columns = [
            column for column in frame.columns
            if _normalise_catalogue_dimension_name(column) in removable
        ]
        if generated_columns:
            frame = frame.drop(columns=generated_columns)
        frame = materialize_calculated_dimensions(frame, dimensions, f'cdr-{kind}')
        task_repository.replace_dataset_rows(dataset_id, frame)
        completed_steps += 1
        if progress_callback:
            progress_callback(completed_steps, total_steps, f'Updating {dataset["file_name"]}')
    affected_kinds = selected_sources or set(CDR_DATASET_KINDS)
    for kind in affected_kinds:
        task_repository.drop_reporting_table(kind)
    calculated_names = [dimension.name for dimension in dimensions]
    reporting_datasets = [
        row for row in all_datasets if str(row['dataset_kind'] or '').casefold() in affected_kinds
    ]
    for dataset in reporting_datasets:
        task_repository.copy_dataset_rows_to_reporting(
            int(dataset['id']), str(dataset['dataset_kind']).casefold(), calculated_names,
        )
        completed_steps += 1
        if progress_callback:
            progress_callback(min(completed_steps, total_steps), total_steps, f'Rebuilding {dataset["dataset_kind"]} reporting table')
    DATAFRAME_CACHE.clear()
    ANALYSIS_CACHE.clear()
    CHART_PREVIEW_DATA_CACHE.clear()
    task_repository.set_workspace_state('calculated_dimensions_need_materialization', '0')
    return len(datasets)


def _auto_field_sql_expression(
    definition: Any, columns: Iterable[str], quote: Callable[[str], str],
) -> tuple[str, list[Any]]:
    """Compile one field to a parameterized SQLite CASE expression."""
    column_lookup = {_normalise_catalogue_dimension_name(column): str(column) for column in columns}

    def resolve(value: str | Iterable[str]) -> str | None:
        candidates = value.split('|') if isinstance(value, str) else value
        return next((column_lookup.get(_normalise_catalogue_dimension_name(item)) for item in candidates if column_lookup.get(_normalise_catalogue_dimension_name(item))), None)

    def numeric_value(value: str) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if pd.notna(parsed) else None

    def condition_sql(condition: Any) -> tuple[str, list[Any]] | None:
        column = resolve(condition.column)
        if not column:
            return None
        selected = quote(column)
        operator = str(condition.operator)
        if operator in {'>', '>=', '<', '<=', '=', '!='}:
            target = str(condition.values[0])
            number = numeric_value(target)
            if number is not None:
                comparison = f'da_try_number({selected}) {operator} ?'
                if operator == '!=':
                    comparison = f'(da_try_number({selected}) IS NULL OR {comparison})'
                return comparison, [number]
            if operator not in {'=', '!='}:
                return None
            return f'da_casefold({selected}) {operator} ?', [target.casefold()]
        if operator in {'CONTAINS', 'NOT CONTAINS'}:
            checks = [f'instr(da_casefold({selected}), ?) > 0' for _value in condition.values]
            expression = f"({' OR '.join(checks)})"
            if operator == 'NOT CONTAINS':
                expression = f'NOT COALESCE({expression}, 0)'
            return expression, [str(value).casefold() for value in condition.values]
        if operator in {'IN', 'NOT IN'}:
            placeholders = ', '.join('?' for _value in condition.values)
            expression = f'da_casefold({selected}) IN ({placeholders})'
            if operator == 'NOT IN':
                expression = f'NOT COALESCE({expression}, 0)'
            return expression, [str(value).casefold() for value in condition.values]
        return None

    clauses: list[str] = []
    parameters: list[Any] = []
    for rule in definition.rules:
        compiled = [condition_sql(condition) for condition in rule.conditions]
        if any(item is None for item in compiled):
            continue
        conditions = [item for item in compiled if item is not None]
        clauses.append(f"WHEN {' AND '.join(item[0] for item in conditions)} THEN ?")
        for _sql, values in conditions:
            parameters.extend(values)
        parameters.append(rule.value)
    default_column = resolve(definition.default_from)
    fallback = f'CAST({quote(default_column)} AS TEXT)' if default_column else 'NULL'
    if definition.default != '':
        fallback = f'COALESCE({fallback}, ?)'
        parameters.append(definition.default)
    expression = f"CASE {' '.join(clauses)} ELSE {fallback} END" if clauses else fallback
    return expression, parameters


def _incremental_auto_field_table_update(
    task_repository: Repository,
    table_name: str,
    cdr_source: str,
    previous: Iterable[Any],
    current: Iterable[Any],
    renames: dict[str, str],
) -> bool:
    """Apply changed fields in one SQL scan without replacing the source table."""
    quote = task_repository._quote_identifier
    previous_items = tuple(previous)
    current_items = tuple(current)
    previous_by_key = {_normalise_catalogue_dimension_name(item.name): item for item in previous_items}
    rename_sources = {
        _normalise_catalogue_dimension_name(new_name): previous_by_key.get(_normalise_catalogue_dimension_name(old_name))
        for old_name, new_name in renames.items()
    }
    with task_repository.connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,),
        ).fetchone()
        if not exists:
            return False
        connection.create_function(
            'da_casefold', 1,
            lambda value: str(value).casefold() if value is not None else None,
            deterministic=True,
        )

        def try_number(value: Any) -> float | None:
            if value is None:
                return None
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return None
            return parsed if pd.notna(parsed) else None

        connection.create_function('da_try_number', 1, try_number, deterministic=True)
        columns = task_repository._table_columns(connection, table_name)
        column_lookup = {_normalise_catalogue_dimension_name(column): column for column in columns}
        source = cdr_source.casefold()
        applicable_current = {
            _normalise_catalogue_dimension_name(item.name): item
            for item in current_items if source in item.sources
        }
        applicable_previous = {
            _normalise_catalogue_dimension_name(item.name): item
            for item in previous_items if source in item.sources
        }

        # Rename in place whenever possible, including case-only display-name
        # changes via a temporary name because SQLite identifiers ignore case.
        for old_name, new_name in renames.items():
            old_key = _normalise_catalogue_dimension_name(old_name)
            new_key = _normalise_catalogue_dimension_name(new_name)
            physical_old = column_lookup.get(old_key)
            if not physical_old or new_key not in applicable_current:
                continue
            physical_new = column_lookup.get(new_key)
            if physical_new and physical_new != physical_old:
                connection.execute(f'ALTER TABLE {quote(table_name)} DROP COLUMN {quote(physical_old)}')
                columns.remove(physical_old)
            elif physical_old != new_name:
                temporary = f'__auto_field_rename_{uuid4().hex}'
                connection.execute(f'ALTER TABLE {quote(table_name)} RENAME COLUMN {quote(physical_old)} TO {quote(temporary)}')
                connection.execute(f'ALTER TABLE {quote(table_name)} RENAME COLUMN {quote(temporary)} TO {quote(new_name)}')
                columns[columns.index(physical_old)] = new_name
            column_lookup.pop(old_key, None)
            column_lookup[new_key] = new_name

        removable_keys = set(applicable_previous) - set(applicable_current)
        # Also clean known stale columns whose current definition does not
        # apply to this CDR type.
        removable_keys.update(
            key for key, item in {
                _normalise_catalogue_dimension_name(item.name): item for item in current_items
            }.items() if source not in item.sources and key in column_lookup
        )
        for key in removable_keys:
            physical = column_lookup.get(key)
            if not physical:
                continue
            connection.execute(f'ALTER TABLE {quote(table_name)} DROP COLUMN {quote(physical)}')
            columns.remove(physical)
            column_lookup.pop(key, None)

        updates: list[tuple[str, list[Any], Any]] = []
        for key, definition in applicable_current.items():
            old_definition = previous_by_key.get(key) or rename_sources.get(key)
            physical = column_lookup.get(key)
            changed = old_definition != definition or physical is None or physical != definition.name
            if not changed:
                continue
            if physical is None:
                connection.execute(f'ALTER TABLE {quote(table_name)} ADD COLUMN {quote(definition.name)} TEXT')
                columns.append(definition.name)
                column_lookup[key] = definition.name
                physical = definition.name
            elif physical != definition.name:
                temporary = f'__auto_field_case_{uuid4().hex}'
                connection.execute(f'ALTER TABLE {quote(table_name)} RENAME COLUMN {quote(physical)} TO {quote(temporary)}')
                connection.execute(f'ALTER TABLE {quote(table_name)} RENAME COLUMN {quote(temporary)} TO {quote(definition.name)}')
                columns[columns.index(physical)] = definition.name
                physical = definition.name
            # Match the DataFrame implementation: a field cannot use its own
            # previously materialized value as input. Earlier fields in the
            # ordered definition list remain available for dependencies.
            expression_columns = [
                column for column in columns
                if _normalise_catalogue_dimension_name(column) != key
            ]
            expression, values = _auto_field_sql_expression(definition, expression_columns, quote)
            updates.append((f'{quote(physical)} = {expression}', values, definition))
        if updates:
            changed_keys = {
                _normalise_catalogue_dimension_name(definition.name)
                for _assignment, _values, definition in updates
            }
            has_dependencies = any(
                changed_keys.intersection({
                    _normalise_catalogue_dimension_name(alias)
                    for rule in definition.rules
                    for condition in rule.conditions
                    for alias in condition.column.split('|')
                } | {
                    _normalise_catalogue_dimension_name(alias) for alias in definition.default_from
                })
                for _assignment, _values, definition in updates
            )
            if has_dependencies:
                # SQLite evaluates all SET expressions against the old row.
                # Preserve ordered field dependencies with one scan per field
                # only when a changed field references another changed field.
                for assignment, values, _definition in updates:
                    connection.execute(f'UPDATE {quote(table_name)} SET {assignment}', values)
            else:
                connection.execute(
                    f'UPDATE {quote(table_name)} SET {", ".join(item[0] for item in updates)}',
                    [value for _assignment, values, _definition in updates for value in values],
                )
        return bool(updates or removable_keys or renames)


def combined_reporting_required_columns(dimensions: Iterable[Any], kind: str) -> list[str]:
    """Return source, preview-filter and calculated columns required by a combined CDR table."""
    source = f'cdr-{kind}'
    requested = [*Repository.REPORTING_CORE_COLUMNS, 'attempt_count']
    requested.extend(
        candidate
        for _parameter, _label, candidates in CDR_PREVIEW_FILTER_DEFINITIONS
        for candidate in candidates
    )
    for definition in dimensions:
        if source not in definition.sources:
            continue
        requested.append(definition.name)
        requested.extend(definition.default_from)
        requested.extend(
            alias.strip()
            for rule in definition.rules
            for condition in rule.conditions
            for alias in condition.column.split('|')
            if alias.strip()
        )
    return list(dict.fromkeys(column for column in requested if str(column).strip()))


def materialize_workspace_auto_fields_incrementally(
    previous: Iterable[Any],
    current: Iterable[Any],
    renames: dict[str, str],
    task_repository: Repository,
    affected_sources: Iterable[str],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, int]:
    """Update only changed columns, scanning each affected SQLite table once."""
    selected_sources = {
        str(source).casefold().removeprefix('cdr-') for source in affected_sources if str(source).strip()
    }
    datasets = [
        row for row in task_repository.list_datasets()
        if row['status'] == 'ready'
        and str(row['dataset_kind'] or '').casefold() in selected_sources
    ]
    reporting_kinds = sorted({str(row['dataset_kind']).casefold() for row in datasets})
    total = max(len(datasets) + len(reporting_kinds), 1)
    completed = 0
    for dataset in datasets:
        kind = str(dataset['dataset_kind']).casefold()
        _incremental_auto_field_table_update(
            task_repository, task_repository.dataset_rows_table_name(int(dataset['id'])),
            f'cdr-{kind}', previous, current, renames,
        )
        completed += 1
        if progress_callback:
            progress_callback(completed, total, f'Updating {dataset["file_name"]}')
    for kind in reporting_kinds:
        required_columns = combined_reporting_required_columns(current, kind)
        # Reconcile membership before updating calculated columns. A combined
        # table may predate a newly processed CDR of the same type, so an
        # incremental column update alone would leave that dataset out.
        for dataset in datasets:
            if str(dataset['dataset_kind']).casefold() == kind:
                task_repository.copy_dataset_rows_to_reporting(
                    int(dataset['id']), kind, required_columns,
                )
        if task_repository.list_reporting_row_columns(kind):
            _incremental_auto_field_table_update(
                task_repository, task_repository.reporting_rows_table_name(kind),
                f'cdr-{kind}', previous, current, renames,
            )
        completed += 1
        task_repository.set_workspace_state(
            f'combined_reporting_updated_{kind}', now_iso(),
        )
        if progress_callback:
            progress_callback(completed, total, f'Updating combined CDR-{kind.upper()} table')
    DATAFRAME_CACHE.clear()
    ANALYSIS_CACHE.clear()
    CHART_PREVIEW_DATA_CACHE.clear()
    task_repository.set_workspace_state('calculated_dimensions_need_materialization', '0')
    return {
        'datasets': len(datasets),
        'combined_tables': len(reporting_kinds),
        'tables': completed,
    }


def affected_calculated_dimension_sources(previous: Iterable[Any], current: Iterable[Any]) -> set[str]:
    """Return only the CDR types touched by an auto-calculated field change."""
    previous_by_name = {_normalise_catalogue_dimension_name(item.name): item for item in previous}
    current_by_name = {_normalise_catalogue_dimension_name(item.name): item for item in current}
    affected: set[str] = set()
    for key in previous_by_name.keys() | current_by_name.keys():
        old = previous_by_name.get(key)
        new = current_by_name.get(key)
        if old == new:
            continue
        for definition in (old, new):
            if definition:
                affected.update(str(source).casefold() for source in definition.sources)
    return affected


def _auto_calculated_field_workspace_lock(workspace_id: str) -> Lock:
    with AUTO_CALCULATED_FIELD_WORKSPACE_LOCKS_LOCK:
        return AUTO_CALCULATED_FIELD_WORKSPACE_LOCKS.setdefault(workspace_id, Lock())


def _run_auto_calculated_field_job(job_id: str, workspace: Workspace) -> None:
    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        job = AUTO_CALCULATED_FIELD_JOBS[job_id]
        job.update(status='processing', message='Preparing CDR tables')
        previous = parse_calculated_dimensions(job['previous_definitions'])
        affected_sources = tuple(job['affected_sources'])
        renames = dict(job['renames'])
    task_repository = Repository(
        workspace.database_path,
        global_db_path=repository.global_db_path,
        workspace_registry_db_path=workspace_registry.registry_path,
    )

    def update_progress(completed: int, total: int, message: str) -> None:
        with AUTO_CALCULATED_FIELD_JOBS_LOCK:
            job = AUTO_CALCULATED_FIELD_JOBS.get(job_id)
            if job:
                job.update(completed=completed, total=total, message=message)

    try:
        with _auto_calculated_field_workspace_lock(workspace.id):
            task_repository.set_workspace_state('calculated_dimensions_need_materialization', 'processing')
            current = parse_calculated_dimensions(task_repository.list_calculated_dimensions())
            current_sources = affected_calculated_dimension_sources(previous, current)
            stats = materialize_workspace_auto_fields_incrementally(
                previous, current, renames, task_repository,
                set(affected_sources) | current_sources, update_progress,
            )
        with AUTO_CALCULATED_FIELD_JOBS_LOCK:
            completed_tables = int(AUTO_CALCULATED_FIELD_JOBS[job_id].get('total') or stats['tables'])
            dataset_count = stats['datasets']
            combined_count = stats['combined_tables']
            updated_parts = [f'{dataset_count} CDR dataset' + ('' if dataset_count == 1 else 's')]
            if combined_count:
                updated_parts.append(f'{combined_count} combined CDR table' + ('' if combined_count == 1 else 's'))
            AUTO_CALCULATED_FIELD_JOBS[job_id].update(
                status='ready', completed=completed_tables, total=completed_tables,
                materialized_datasets=dataset_count, materialized_combined_tables=combined_count,
                message=f"Updated {' and '.join(updated_parts)}",
                finished_at=datetime.now(timezone.utc).timestamp(),
            )
    except Exception as exc:
        task_repository.set_workspace_state('calculated_dimensions_need_materialization', '1')
        with AUTO_CALCULATED_FIELD_JOBS_LOCK:
            AUTO_CALCULATED_FIELD_JOBS[job_id].update(
                status='failed', error=str(exc), message='Materialization failed',
                finished_at=datetime.now(timezone.utc).timestamp(),
            )


def start_auto_calculated_field_job(
    workspace: Workspace, previous: Iterable[Any], current: Iterable[Any],
    renames: dict[str, str], username: str, *, background: bool = True,
) -> dict[str, Any]:
    """Queue materialization so the web request and UI remain responsive."""
    job_id = uuid4().hex
    previous_items = tuple(previous)
    current_items = tuple(current)
    affected_sources = affected_calculated_dimension_sources(previous_items, current_items)
    job = {
        'id': job_id, 'workspace_id': workspace.id, 'workspace_name': workspace.name,
        'status': 'queued', 'completed': 0, 'total': 0,
        'message': 'Waiting to update CDR tables',
        'previous_definitions': calculated_dimensions_json(previous_items),
        'affected_sources': sorted(set(affected_sources)), 'username': username,
        'renames': dict(renames),
        'created_at': datetime.now(timezone.utc).timestamp(),
    }
    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        cutoff = datetime.now(timezone.utc).timestamp() - EXPORT_PACKAGE_TTL.total_seconds()
        for stale_id in [
            existing_id for existing_id, existing in AUTO_CALCULATED_FIELD_JOBS.items()
            if existing.get('status') in {'ready', 'failed'}
            and float(existing.get('finished_at') or 0) < cutoff
        ]:
            AUTO_CALCULATED_FIELD_JOBS.pop(stale_id, None)
        AUTO_CALCULATED_FIELD_JOBS[job_id] = job
    if not job['affected_sources']:
        job.update(
            status='ready', message='No CDR tables required changes',
            finished_at=datetime.now(timezone.utc).timestamp(),
        )
        return job
    # Keep a recoverable pending marker until the worker actually starts. If
    # the process exits first, opening this workspace queues the rebuild again.
    pending_repository = Repository(
        workspace.database_path,
        global_db_path=repository.global_db_path,
        workspace_registry_db_path=workspace_registry.registry_path,
    )
    pending_repository.set_workspace_state('calculated_dimensions_need_materialization', '1')
    if background:
        Thread(
            target=_run_auto_calculated_field_job,
            args=(job_id, workspace),
            name=f'auto-calculated-fields-{workspace.id}', daemon=True,
        ).start()
    else:
        _run_auto_calculated_field_job(job_id, workspace)
    return job


def _run_combined_cdr_recreation_job(job_id: str, workspace: Workspace, kind: str) -> None:
    task_repository = Repository(
        workspace.database_path,
        global_db_path=repository.global_db_path,
        workspace_registry_db_path=workspace_registry.registry_path,
    )

    def update_progress(completed: int, total: int, message: str) -> None:
        with AUTO_CALCULATED_FIELD_JOBS_LOCK:
            job = AUTO_CALCULATED_FIELD_JOBS.get(job_id)
            if job:
                job.update(completed=completed, total=total, message=message)

    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        AUTO_CALCULATED_FIELD_JOBS[job_id].update(
            status='processing', message=f'Preparing combined CDR-{kind.upper()} table',
        )
    try:
        with _auto_calculated_field_workspace_lock(workspace.id):
            task_repository.set_workspace_state('calculated_dimensions_need_materialization', 'processing')
            stats = recreate_combined_cdr_table(workspace, kind, update_progress)
            task_repository.set_workspace_state('calculated_dimensions_need_materialization', '0')
        with AUTO_CALCULATED_FIELD_JOBS_LOCK:
            total = int(AUTO_CALCULATED_FIELD_JOBS[job_id].get('total') or stats['tables'])
            AUTO_CALCULATED_FIELD_JOBS[job_id].update(
                status='ready', completed=total, total=total,
                materialized_datasets=stats['datasets'], materialized_combined_tables=1,
                message=f"Recreated combined CDR-{kind.upper()} table with {stats['rows']} rows",
                refresh_workspace=True,
                finished_at=datetime.now(timezone.utc).timestamp(),
            )
    except Exception as exc:
        task_repository.set_workspace_state('calculated_dimensions_need_materialization', '0')
        task_repository.set_workspace_state(f'combined_reporting_error_{kind}', str(exc))
        with AUTO_CALCULATED_FIELD_JOBS_LOCK:
            AUTO_CALCULATED_FIELD_JOBS[job_id].update(
                status='failed', error=str(exc), message=f'Combined CDR-{kind.upper()} recreation failed',
                finished_at=datetime.now(timezone.utc).timestamp(),
            )


def start_combined_cdr_recreation_job(
    workspace: Workspace, kind: str, username: str, *, background: bool = True,
) -> dict[str, Any]:
    """Queue one combined-table rebuild in the shared materialization progress UI."""
    job_id = uuid4().hex
    job = {
        'id': job_id, 'workspace_id': workspace.id, 'workspace_name': workspace.name,
        'operation': 'combined_recreation', 'combined_kind': kind,
        'status': 'queued', 'completed': 0, 'total': 0,
        'message': f'Waiting to recreate combined CDR-{kind.upper()} table',
        'previous_definitions': [], 'affected_sources': [], 'renames': {}, 'username': username,
        'created_at': datetime.now(timezone.utc).timestamp(),
    }
    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        AUTO_CALCULATED_FIELD_JOBS[job_id] = job
    task_repository = Repository(
        workspace.database_path,
        global_db_path=repository.global_db_path,
        workspace_registry_db_path=workspace_registry.registry_path,
    )
    task_repository.set_workspace_state('calculated_dimensions_need_materialization', '1')
    if background:
        Thread(
            target=_run_combined_cdr_recreation_job,
            args=(job_id, workspace, kind),
            name=f'recreate-combined-cdr-{workspace.id}-{kind}', daemon=True,
        ).start()
    else:
        _run_combined_cdr_recreation_job(job_id, workspace, kind)
    return job


def queue_workspace_dimension_materialization(workspace: Workspace) -> None:
    """Materialize a migrated workspace without blocking its management page."""
    if repository.get_workspace_state('calculated_dimensions_need_materialization') not in {'1', 'processing'}:
        return
    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        if any(
            job.get('workspace_id') == workspace.id and job.get('status') in {'queued', 'processing'}
            for job in AUTO_CALCULATED_FIELD_JOBS.values()
        ):
            return
    with WORKSPACE_DIMENSION_MATERIALIZATION_THREADS_LOCK:
        if workspace.id in WORKSPACE_DIMENSION_MATERIALIZATION_THREADS:
            return
        WORKSPACE_DIMENSION_MATERIALIZATION_THREADS.add(workspace.id)
    repository.set_workspace_state('calculated_dimensions_need_materialization', 'processing')

    def run() -> None:
        task_repository = Repository(
            workspace.database_path,
            global_db_path=repository.global_db_path,
            workspace_registry_db_path=workspace_registry.registry_path,
        )
        try:
            dimensions = parse_calculated_dimensions(task_repository.list_calculated_dimensions())
            materialize_workspace_auto_fields_incrementally(
                (), dimensions, {}, task_repository,
                {'cdr-data', 'cdr-voice', 'cdr-speech'},
            )
        except Exception:
            task_repository.set_workspace_state('calculated_dimensions_need_materialization', '1')
        finally:
            with WORKSPACE_DIMENSION_MATERIALIZATION_THREADS_LOCK:
                WORKSPACE_DIMENSION_MATERIALIZATION_THREADS.discard(workspace.id)

    Thread(target=run, name=f'calculated-dimensions-{workspace.id}', daemon=True).start()


def named_catalogue_path(technology: str, identifier: str, template_name: str | None = None) -> Path:
    """Return the canonical library location, named exactly after the template."""
    filename = template_filename(template_name) if template_name else f'{identifier}.csv'
    return settings.slides_templates_dir / 'library' / technology / filename


def synchronize_template_file_names(technology: str) -> None:
    """Reconcile registered templates without treating arbitrary CSVs as templates."""
    library_dir = settings.slides_templates_dir / 'library' / technology
    library_dir.mkdir(parents=True, exist_ok=True)
    default_dir = settings.slides_templates_dir / 'default' / technology
    default_dir.mkdir(parents=True, exist_ok=True)
    existing = {str(row['name']): bool(row['is_default']) for row in repository.list_report_templates(technology)}
    default_files = sorted(default_dir.glob('*.csv'))
    physical_names = {catalogue_registry_key(path.stem) for path in [*library_dir.glob('*.csv'), *default_files]}
    missing_names = set(existing) - physical_names
    unregistered_names = physical_names - set(existing)
    # Preserve the one unambiguous manual CSV rename supported by the library,
    # but never promote arbitrary CSVs into the registry on a later page
    # render. This prevents phantom templates from stale/incidental files.
    if len(missing_names) == len(unregistered_names) == 1:
        previous_name = next(iter(missing_names))
        replacement_name = next(iter(unregistered_names))
        repository.rename_report_template(technology, previous_name, replacement_name)
        existing[replacement_name] = existing.pop(previous_name)
        missing_names.clear()
    for name in missing_names:
        repository.delete_report_template(technology, name)
        existing.pop(name, None)
    # The application-managed default is the only safe bootstrap source when
    # an otherwise empty configuration database is restored.
    if len(default_files) == 1:
        default_name = catalogue_registry_key(default_files[0].stem)
        if default_name not in existing:
            repository.add_report_template(technology, default_name, is_default=False)
            existing[default_name] = False
    if len(default_files) == 1:
        default_name = catalogue_registry_key(default_files[0].stem)
        repository.set_default_report_template(technology, default_name)
        library_path = named_catalogue_path(technology, default_name, default_name)
        if not library_path.exists():
            shutil.copy2(default_files[0], library_path)


def promote_report_template_to_default(
    technology: str,
    identifier: str,
) -> None:
    """Make a library template the default while retaining every library CSV."""
    available = {str(row['name']): row for row in repository.list_report_templates(technology)}
    if identifier not in available:
        raise ValueError('Named template metadata was not found.')
    source_path = named_catalogue_path(technology, identifier, identifier)
    if not source_path.exists():
        raise ValueError('The named template CSV could not be found.')
    default_dir = settings.slides_templates_dir / 'default' / technology
    promoted_path = default_dir / source_path.name
    promoted_name = identifier
    promoted_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, promoted_path)
    for active_copy in promoted_path.parent.glob('*.csv'):
        if active_copy != promoted_path:
            active_copy.unlink()
    repository.set_default_report_template(technology, promoted_name)


def report_catalogue_options(technology: str) -> list[dict[str, Any]]:
    synchronize_template_file_names(technology)
    templates = repository.list_report_templates(technology)
    options: list[dict[str, Any]] = []
    for row in templates:
        identifier = str(row['name'])
        is_default = bool(row['is_default'])
        path = named_catalogue_path(technology, identifier, identifier)
        if is_default:
            path = active_catalog_path(settings.slides_templates_dir, default_report_slides_template_path(technology, identifier), technology)
        if not path.exists():
            continue
        options.append({
            'identifier': identifier,
            'name': identifier,
            'path': path,
            'source': 'Default source' if is_default else 'Named workspace template',
            'active': is_default,
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        })
    return options


def reporting_catalog_path(technology: str) -> Path:
    active = next((option for option in report_catalogue_options(technology) if option['active']), None)
    if not active:
        raise FileNotFoundError(f'No default {technology.upper()} Slides Template is configured.')
    return active['path']


def reporting_catalog_entries(technology: str):
    path = reporting_catalog_path(technology)
    return load_template_catalogue(path, technology)


def catalogue_editor_columns(datasets: Iterable[Any] | None = None, calculated_dimensions: Iterable[Any] = ()) -> dict[str, list[str]]:
    """Offer the processed CDR fields that can be used in the template editor."""
    common = {'Operator', 'Campaign', 'source_sheet', 'vendor', 'RAT_A', 'RAT'}
    columns: dict[str, set[str]] = {
        'cdr-data': set(common) | {'Test_Result', 'Test_Name', 'Type_of_Test', 'Direction', 'G Level 4'},
        'cdr-voice': set(common) | {'Call_Status', 'Session_Type', 'Call_Setup_Time', 'G Level 4'},
        'cdr-speech': set(common) | {'Call_Status', 'Session_Type', 'LQ', 'G Level 4'},
    }
    for dataset in datasets if datasets is not None else repository.list_datasets():
        kind = str(dataset['dataset_kind'] or '').casefold()
        source = f'cdr-{kind}'
        if source not in columns or dataset['status'] != 'ready':
            continue
        columns[source].update(str(column) for column in repository.list_dataset_row_columns(dataset['id']))
    result: dict[str, list[str]] = {}
    for source, values in columns.items():
        # A source can expose the same field with presentation and physical
        # spellings (for example ``G Level 4`` and ``G_Level_4``). Present it
        # only once, preferring the readable spelling, so a multi-select can
        # never build a duplicate Cartesian grouping dimension.
        unique: dict[str, str] = {}
        calculated = {
            dimension.name for dimension in calculated_dimensions
            if source in dimension.sources
        }
        for value in sorted(values | calculated, key=lambda item: ("_" in item, item.casefold())):
            unique.setdefault(re.sub(r'[^a-z0-9]+', '', value.casefold()), value)
        result[source] = sorted(unique.values(), key=str.casefold)
    return result


def catalogue_editor_filter_values(columns: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    """Expose a bounded set of real processed values for template filter assistance."""
    values: dict[str, dict[str, set[str]]] = {source: {} for source in columns}
    for dataset in repository.list_datasets():
        kind = str(dataset['dataset_kind'] or '').casefold()
        source = f'cdr-{kind}'
        if source not in values or dataset['status'] != 'ready' or not repository.dataset_rows_table_exists(dataset['id']):
            continue
        for column in repository.list_dataset_row_columns(dataset['id']):
            known = values[source].setdefault(str(column), set())
            known.update(repository.list_distinct_dataset_row_values(dataset['id'], str(column), limit=100))
    return {
        source: {
            column: sorted(column_values, key=str.casefold)[:100]
            for column, column_values in per_column.items()
            if column_values
        }
        for source, per_column in values.items()
    }


def catalogue_layout_names(technology: str) -> list[str]:
    template = settings.ppt_templates_dir / TEMPLATE_NAMES[technology]
    if not template.exists():
        return []
    try:
        from pptx import Presentation
        return sorted({layout.name for layout in Presentation(template).slide_layouts if layout.name.strip()}, key=str.casefold)
    except Exception:
        return []


def catalogue_editor_payload(technology: str | None, catalogue_id: str | None) -> dict[str, Any] | None:
    if technology not in TEMPLATE_NAMES or not catalogue_id:
        return None
    catalogue = next((item for item in report_catalogue_options(technology) if item['identifier'] == catalogue_id), None)
    if not catalogue:
        return None
    validation_error = None
    try:
        entries = load_template_catalogue(catalogue['path'], technology)
    except ValueError as exc:
        # A newly created template deliberately contains only the current CSV
        # headers.  It is valid to open that blank canvas in the editor, while
        # the report-generation parser continues to reject a template that
        # has not yet been configured with any slides.
        if str(exc) == 'The report template does not contain any rows.':
            entries = []
        elif 'Invalid filter' in str(exc):
            # An invalid persisted filter must remain editable. Report
            # generation and saving still use strict validation, but opening
            # Admin must not become impossible because of a damaged row.
            validation_error = str(exc)
            entries = load_template_catalogue(catalogue['path'], technology, validate_filters=False)
        else:
            raise
    # CSVs are allowed to have been edited out of order. The editor always
    # presents coherent slide blocks while preserving the chart order inside a
    # slide when it is saved again.
    entries = [entry for _index, entry in sorted(enumerate(entries), key=lambda item: (item[1].slide, item[0]))]
    rows = [
        {
            'Slide': entry.slide,
            'Slide Tittle': entry.slide_title,
            'Slide Subtittle': entry.slide_subtitle,
            'Layout': entry.layout,
            'Chart Tittle': entry.chart_title,
            'CDR source': entry.cdr_source,
            'KPI': entry.kpi,
            'Chart type': entry.chart_type,
            'Filters': entry.filters,
            'Rows Aggregation': entry.grouping_rows,
            'Column Aggregation': entry.grouping_columns,
            'Legend': entry.legend,
            'Legend Position': entry.legend_position.title(),
        }
        for entry in entries
    ]
    if not rows:
        rows = [{header: ('1' if header == 'Slide' else '') for header in CATALOG_HEADERS}]
    dimensions = load_workspace_calculated_dimensions()
    columns = catalogue_editor_columns(calculated_dimensions=dimensions)
    return {
        'technology': technology,
        'catalogue': catalogue,
        'rows': rows,
        'headers': CATALOG_HEADERS,
        'validation_error': validation_error,
        'calculated_dimensions': calculated_dimensions_json(dimensions),
        'suggestions': {
            'layouts': catalogue_layout_names(technology),
            'chart_types': sorted(CHART_TYPES | STRUCTURAL_SLIDE_TYPES, key=str.casefold),
            'legend_positions': ['Top', 'Bottom', 'Left', 'Right'],
            'columns': columns,
        },
    }


def synchronize_reporting_row_store() -> None:
    """Backfill shared CDR tables from existing per-dataset materialisations."""
    for dataset in repository.list_datasets():
        kind = str(dataset['dataset_kind'] or '').casefold()
        if dataset['status'] != 'ready' or kind not in CDR_DATASET_KINDS:
            continue
        dataset_id = int(dataset['id'])
        repository.copy_dataset_rows_to_reporting(dataset_id, kind)


def activate_workspace(workspace_id: str, *, initialize: bool = True) -> Workspace:
    """Make one isolated workspace the target for all dataset operations."""
    global active_workspace
    workspace = workspace_registry.mark_opened(workspace_id)
    # Authentication remains global; template files and metadata are workspace-owned.
    repository.set_global_database(application_config_dir / 'application.db')
    for path in (workspace.database_path.parent, workspace.input_dir, workspace.output_dir, workspace.export_dir):
        path.mkdir(parents=True, exist_ok=True)
    object.__setattr__(settings, 'database_path', workspace.database_path)
    object.__setattr__(settings, 'input_dir', workspace.input_dir)
    object.__setattr__(settings, 'output_dir', workspace.output_dir)
    object.__setattr__(settings, 'export_dir', workspace.export_dir)
    object.__setattr__(settings, 'slides_templates_dir', workspace.slides_templates_dir)
    repository.db_path = workspace.database_path
    ANALYSIS_CACHE.clear()
    DATAFRAME_CACHE.clear()
    _clear_chart_preview_caches()
    active_workspace = workspace
    if initialize:
        repository.initialize()
        migration_marker = workspace.slides_templates_dir / '.migrate-library'
        if migration_marker.exists():
            register_workspace_template_files(workspace)
            migration_marker.unlink()
        # The workspace database is self-contained.  In particular, a
        # duplicate already includes its reporting-row store, so rebuilding
        # every ready CDR here can take minutes and make opening the copied
        # workspace look like a server failure.  Reporting materialises the
        # exact columns it needs lazily in ``_combined_reporting_frame``.
        for technology in TEMPLATE_NAMES:
            synchronize_template_file_names(technology)
    return workspace


def close_active_workspace() -> None:
    global active_workspace
    if active_workspace:
        workspace_registry.close_active(active_workspace.id)
    ANALYSIS_CACHE.clear()
    DATAFRAME_CACHE.clear()
    _clear_chart_preview_caches()
    active_workspace = None


def workspace_disk_usage(workspace: Workspace) -> int:
    """Return the bytes used by a managed workspace, with a short-lived cache."""
    root = workspace.database_path.parent
    cache_key = str(root.resolve())
    now = monotonic()
    with _workspace_size_cache_lock:
        cached = _workspace_size_cache.get(cache_key)
        if cached and now - cached[0] < _WORKSPACE_SIZE_CACHE_SECONDS:
            return cached[1]

    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        # A concurrent upload, report job or cleanup can move
                        # a file while the display value is being calculated.
                        continue
        except OSError:
            continue

    with _workspace_size_cache_lock:
        _workspace_size_cache[cache_key] = (now, total)
    return total


def invalidate_workspace_size_cache(workspace_root: Path | None = None) -> None:
    """Discard a workspace-size snapshot after changing files on its disk."""
    root = workspace_root or (active_workspace.database_path.parent if active_workspace else None)
    if root is None:
        return
    try:
        cache_key = str(root.resolve())
    except OSError:
        cache_key = str(root)
    with _workspace_size_cache_lock:
        _workspace_size_cache.pop(cache_key, None)


def format_workspace_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        value = size_bytes / (1024 ** 3)
        unit = 'GB'
    else:
        value = size_bytes / (1024 ** 2)
        unit = 'MB'
    formatted = f'{value:.1f}'.rstrip('0').rstrip('.')
    return f'{formatted} {unit}'


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_directories([
        settings.database_path.parent,
        settings.template_dir,
        settings.slides_templates_dir,
        settings.ppt_templates_dir,
        settings.static_dir,
    ])
    # Capture the configured legacy paths once, then retain them as the
    # original workspace while every newly-created workspace gets its own DB
    # and data directories.
    global workspace_registry, application_config_dir
    application_config_dir = settings.database_path.parent
    workspace_registry = WorkspaceRegistry(
        settings.input_dir.parent / 'workspaces' / 'workspace-registry.db',
        settings.input_dir.parent, settings.slides_templates_dir,
        legacy_workspace_registry_path(),
    )
    workspace_registry.initialize()
    repository.set_global_database(settings.database_path.parent / 'application.db')
    repository.set_workspace_registry_database(workspace_registry.registry_path)
    migrate_workspace_template_registries()
    # Workspace schema cleanup and interrupted-job recovery happen when a
    # workspace becomes active.  Scanning every workspace here opens and
    # checkpoints every SQLite database, which can leave startup blocked for
    # minutes on installations with large reporting-row stores.
    export_package_dir().mkdir(parents=True, exist_ok=True)
    _recover_unimported_transfer_packages()
    _cleanup_expired_export_packages()
    if (workspace_id := workspace_registry.active_id()):
        activate_workspace(workspace_id)
        interrupted_datasets, interrupted_reports = repository.fail_interrupted_background_jobs()
        interrupted_chart_jobs = repository.fail_interrupted_report_chart_jobs()
        if interrupted_datasets or interrupted_reports or interrupted_chart_jobs:
            repository.add_log(
                'system',
                'recover_interrupted_background_jobs',
                json.dumps({
                    'datasets': interrupted_datasets,
                    'reports': interrupted_reports,
                    'chart_jobs': interrupted_chart_jobs,
                }),
            )
    yield


app = FastAPI(title=__app_name__, version=__version__, lifespan=lifespan)
app.mount('/static', StaticFiles(directory=settings.static_dir), name='static')
templates = Jinja2Templates(directory=str(settings.template_dir))


def asset_version(relative_path: str) -> str:
    asset_path = settings.static_dir / relative_path
    if not asset_path.exists():
        return __version__
    # Some synced development folders preserve a file's modification time when
    # it changes.  A content fingerprint prevents browsers from reusing an old
    # JavaScript or CSS response after an interface update.
    return hashlib.blake2b(asset_path.read_bytes(), digest_size=8).hexdigest()


def parse_extra_filters(raw_filters: str) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for chunk in raw_filters.split(';'):
        entry = chunk.strip()
        if not entry or '=' not in entry:
            continue
        key, value = entry.split('=', 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            values = [item.strip() for item in value.split(',') if item.strip()]
            filters[key] = values if len(values) > 1 else values[0]
    return filters


def format_extra_filters(filters: dict[str, Any] | None) -> str:
    if not filters:
        return ''
    fragments: list[str] = []
    for key, value in filters.items():
        if isinstance(value, (list, tuple, set)):
            joined = ','.join(str(item).strip() for item in value if str(item).strip())
            if joined:
                fragments.append(f'{key}={joined}')
            continue
        if value not in (None, ''):
            fragments.append(f'{key}={value}')
    return '; '.join(fragments)


def parse_aggregation_overrides(raw_overrides: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for chunk in (raw_overrides or '').split(';'):
        entry = chunk.strip()
        if not entry or '=' not in entry:
            continue
        metric, aggregation = entry.split('=', 1)
        metric = metric.strip()
        aggregation = aggregation.strip()
        if metric and aggregation:
            overrides[metric] = aggregation
    return overrides


def format_aggregation_overrides(overrides: dict[str, str] | None) -> str:
    if not overrides:
        return ''
    return '; '.join(f'{metric}={aggregation}' for metric, aggregation in overrides.items() if metric and aggregation)


def parse_cdf_overrides(raw_overrides: str) -> dict[str, str]:
    return parse_aggregation_overrides(raw_overrides)


def format_cdf_overrides(overrides: dict[str, str] | None) -> str:
    return format_aggregation_overrides(overrides)


def format_aggregation_label(value: str | None) -> str:
    normalized = str(value or 'all').strip()
    if not normalized or normalized == 'all':
        return 'Auto / raw view'
    if normalized.lower() == 'technology_primary':
        return 'Technology'
    return normalized.replace('_', ' ').title()


def _summarize_export_filters(filters: dict[str, Any] | None) -> str:
    if not filters:
        return 'No filters selected'
    fragments: list[str] = []
    for key in ['market', 'period']:
        values = filters.get(key) or []
        if values:
            fragments.append(f"{format_aggregation_label(key)}: {', '.join(str(item) for item in values)}")
    for key, value in (filters.get('extra_filters') or {}).items():
        if not value or value == ['__none__']:
            continue
        values = value if isinstance(value, list) else [value]
        fragments.append(f"{format_aggregation_label(key)}: {', '.join(str(item) for item in values)}")
    if filters.get('date_from'):
        fragments.append(f"Date From: {filters['date_from']}")
    if filters.get('date_to'):
        fragments.append(f"Date To: {filters['date_to']}")
    return ' | '.join(fragments) if fragments else 'No filters selected'


def parse_json_field(value: Any, fallback: Any) -> Any:
    if value in (None, ''):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def unique_values(series) -> list[str]:
    values = sorted({str(value).strip() for value in series.dropna().tolist() if str(value).strip()})
    return values[:50]


def restrict_frame_to_metric(df, metric: str):
    if metric not in df.columns:
        return df
    mask = pd.to_numeric(df[metric], errors='coerce').notna()
    filtered = df[mask].copy()
    return filtered if not filtered.empty else df


def derive_filter_options(df) -> dict[str, list[str]]:
    options: dict[str, list[str]] = {}
    for column in FILTER_DIMENSIONS:
        if column not in df.columns:
            continue
        values = unique_values(df[column])
        if values:
            options[column] = values
    return options


def is_metric_candidate(column: str) -> bool:
    normalized = str(column).strip()
    lowered = normalized.lower()
    excluded_exact = {
        'year', 'week', 'month', 'day', 'hour',
        'campaign_year', 'campaign_quarter', 'hour_bucket', 'day_bucket',
        'dataset_id', 'user_id', 'row_id', 'record_id', 'session_id', 'call_id', 'test_id', 'campaign_id',
    }
    excluded_fragments = (
        '_id', ' id', 'uuid', 'guid',
        'latitude', 'longitude', 'gps_lat', 'gps_lon', 'coordinate', 'location_accuracy',
        'cell_id', 'cellid', 'global_ci', 'globalci', 'gcid', 'cgi', 'eci', 'enodeb',
        'local_cell', 'physical_cell', 'pci', 'arfcn', 'channel', 'mcc', 'mnc', 'tac', 'lac',
    )
    excluded_normalized = {'lat', 'lon', 'latitude', 'longitude', 'altitude', 'bearing', 'accuracy', 'x_coordinate', 'y_coordinate'}
    if lowered in excluded_exact:
        return False
    if lowered in excluded_normalized:
        return False
    if any(fragment in lowered for fragment in excluded_fragments):
        return False
    return not normalized.startswith('_')


def derive_available_metrics(df) -> list[str]:
    preferred = [
        'POLQA_LQ_Avg', 'LQ', 'Mean_Data_Rate', 'quality_score', 'throughput_mbps', 'setup_time_seconds', 'duration_seconds',
        'jitter_ms', 'packet_loss_pct', 'latency_ms', 'Call_Setup_Time', 'Call_Duration', 'Receive_Delay', 'TCP_RTT_Service_Access_Delay',
    ]
    numeric_columns = [
        column for column in df.columns
        if not pd.api.types.is_bool_dtype(df[column])
        and pd.to_numeric(df[column], errors='coerce').notna().any()
    ]
    # Keep known metric columns visible even when the current dataset contains
    # only empty values. Runtime availability will mark them disabled instead
    # of hiding them from the selector altogether.
    numeric_columns.extend(
        column for column in preferred
        if column in df.columns and column not in numeric_columns and is_metric_candidate(column)
    )
    ordered = [column for column in preferred if column in numeric_columns and is_metric_candidate(column)]
    ordered.extend(column for column in numeric_columns if column not in ordered and is_metric_candidate(column))
    return ordered[:20]


def derive_available_aggregations(filter_options: dict[str, list[str]]) -> list[str]:
    return [column for column, values in filter_options.items() if len(values) > 1]


def serialize_dataset_row(row) -> dict[str, Any]:
    item = dict(row)
    for timestamp_key in ('uploaded_at', 'updated_at', 'processed_at', 'created_at'):
        if item.get(timestamp_key):
            item[f'{timestamp_key}_local'] = format_local_timestamp(item[timestamp_key])
    item['available_metrics'] = parse_json_field(item.get('available_metrics_json'), [])
    item['available_aggregations'] = parse_json_field(item.get('available_aggregations_json'), [])
    item['filter_options'] = parse_json_field(item.get('filter_options_json'), {})
    item['summary'] = parse_json_field(item.get('summary_json'), {})
    item['kpis_snapshot'] = parse_json_field(item.get('kpis_json'), {})
    item['status_label'] = STATUS_LABELS.get(item.get('status') or 'queued', 'Queued')
    item['input_kind_label'] = INPUT_KIND_LABELS.get(item.get('dataset_kind') or 'generic', 'Other')
    item['progress'] = int(item.get('progress') or 0)
    item['normalization_version'] = int(item.get('normalization_version') or 1)
    item['vendor_mapping_applied'] = bool(item.get('vendor_mapping_applied'))
    item['vendor_values_complete'] = bool(item.get('vendor_values_complete'))
    item['is_ready'] = item.get('status') == 'ready'
    dataset_path = Path(item.get('stored_path') or '')
    size_bytes = dataset_path.stat().st_size if dataset_path.exists() else 0
    item['size_bytes'] = int(size_bytes)
    item['size_mb'] = round(size_bytes / (1024 * 1024), 2) if size_bytes else 0.0
    item['size_mb_label'] = f"{item['size_mb']:.2f} MB"
    return item


def add_workspace_vendor_capabilities(datasets: list[dict[str, Any]]) -> None:
    """Materialise the Workspace-only Vendor actions for pages and live polling."""
    has_vendor_mappings = any(
        dataset.get('is_ready') and dataset.get('dataset_kind') in {'mapping_vodafone', 'mapping_three'}
        for dataset in datasets
    )
    for dataset in datasets:
        vendor_mapping_applied = bool(dataset.get('vendor_mapping_applied'))
        dataset['can_map_vendors'] = (
            has_vendor_mappings
            and dataset.get('is_ready')
            and dataset.get('dataset_kind') in CDR_DATASET_KINDS
            and not vendor_mapping_applied
            and not dataset.get('vendor_values_complete')
        )
        dataset['can_clear_vendors'] = (
            dataset.get('is_ready')
            and dataset.get('dataset_kind') in CDR_DATASET_KINDS
            and vendor_mapping_applied
        )


def derive_runtime_available_metrics(dataset: dict[str, Any]) -> list[str]:
    available_metrics = [metric for metric in (dataset.get('available_metrics') or []) if is_metric_candidate(metric)]
    if not available_metrics or not dataset.get('is_ready'):
        return available_metrics

    dataset_id = int(dataset['id'])
    if repository.dataset_rows_table_exists(dataset_id):
        return repository.list_metrics_with_non_null_data(dataset_id, available_metrics)

    dataset_path = Path(dataset['stored_path'])
    if not dataset_path.exists():
        return available_metrics

    df = load_cached_dataset(dataset_path)
    numeric_with_data = {
        column for column in df.columns
        if column in available_metrics and pd.to_numeric(df[column], errors='coerce').notna().any()
    }
    return [metric for metric in available_metrics if metric in numeric_with_data]


def derive_runtime_metric_availability(dataset: dict[str, Any]) -> dict[str, bool]:
    available_metrics = [metric for metric in (dataset.get('available_metrics') or []) if is_metric_candidate(metric)]
    selectable_metrics = set(derive_runtime_available_metrics(dataset))
    return {metric: metric in selectable_metrics for metric in available_metrics}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='microseconds')


def format_local_timestamp(value: Any) -> str:
    """Render an ISO timestamp in the server's local timezone."""
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return raw


class ProcessingStopped(Exception):
    pass


def request_stop(dataset_id: int) -> None:
    with STOP_REQUESTS_LOCK:
        STOP_REQUESTS.add(dataset_id)


def clear_stop_request(dataset_id: int) -> None:
    with STOP_REQUESTS_LOCK:
        STOP_REQUESTS.discard(dataset_id)


def stop_requested(dataset_id: int) -> bool:
    with STOP_REQUESTS_LOCK:
        return dataset_id in STOP_REQUESTS


def ensure_not_stopped(dataset_id: int) -> None:
    if stop_requested(dataset_id):
        raise ProcessingStopped('Processing stopped by user.')


def build_analysis_cache_key(dataset_path: Path, filters: dict[str, Any], metric: str) -> str:
    stat = dataset_path.stat()
    payload = {
        'path': str(dataset_path.resolve()),
        'mtime_ns': stat.st_mtime_ns,
        'size': stat.st_size,
        'metric': metric or '',
        'filters': filters,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def build_dataset_cache_key(dataset_path: Path) -> str:
    stat = dataset_path.stat()
    payload = {
        'path': str(dataset_path.resolve()),
        'mtime_ns': stat.st_mtime_ns,
        'size': stat.st_size,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def get_cached_analysis(dataset_path: Path, filters: dict[str, Any], metric: str) -> dict[str, Any] | None:
    return ANALYSIS_CACHE.get(build_analysis_cache_key(dataset_path, filters, metric))


def store_cached_analysis(dataset_path: Path, filters: dict[str, Any], metric: str, analysis: Any) -> Any:
    ANALYSIS_CACHE[build_analysis_cache_key(dataset_path, filters, metric)] = analysis
    if len(ANALYSIS_CACHE) > 64:
        oldest_key = next(iter(ANALYSIS_CACHE))
        ANALYSIS_CACHE.pop(oldest_key, None)
    return analysis


def get_cached_dataset_frame(dataset_path: Path) -> pd.DataFrame | None:
    if not dataset_path.exists():
        return None
    return DATAFRAME_CACHE.get(build_dataset_cache_key(dataset_path))


def store_cached_dataset_frame(dataset_path: Path, df: pd.DataFrame) -> pd.DataFrame:
    if not dataset_path.exists():
        return df
    DATAFRAME_CACHE[build_dataset_cache_key(dataset_path)] = df
    if len(DATAFRAME_CACHE) > 16:
        oldest_key = next(iter(DATAFRAME_CACHE))
        DATAFRAME_CACHE.pop(oldest_key, None)
    return df


def load_cached_dataset(dataset_path: Path) -> pd.DataFrame:
    if not dataset_path.exists():
        raise FileNotFoundError(f'Dataset source file is missing: {dataset_path}')
    cached = get_cached_dataset_frame(dataset_path)
    if cached is not None:
        return cached
    return store_cached_dataset_frame(dataset_path, load_dataset(dataset_path))


def build_analysis_query_columns(
    selected_dataset: dict[str, Any],
    selected_metrics: list[str],
    filters: dict[str, Any],
    aggregation_overrides: dict[str, str],
    cdf_overrides: dict[str, str],
) -> list[str]:
    dataset_kind = str(selected_dataset.get('dataset_kind') or 'generic')
    requested = set(COMMON_ANALYSIS_COLUMNS)
    requested.update(KIND_ANALYSIS_COLUMNS.get(dataset_kind, KIND_ANALYSIS_COLUMNS['generic']))
    requested.update(selected_metrics)
    requested.update({'market', 'period'})
    requested.update((filters.get('extra_filters') or {}).keys())
    requested_groupings = {
        str(filters.get('aggregation') or '').strip(),
        str(filters.get('cdf_grouping') or '').strip(),
        *(str(value).strip() for value in aggregation_overrides.values()),
        *(str(value).strip() for value in cdf_overrides.values()),
    }
    requested.update(grouping for grouping in requested_groupings if grouping and grouping != 'all')
    return sorted(column for column in requested if column)


def ensure_dataset_query_table(dataset: dict[str, Any], required_columns: list[str], filters: dict[str, Any] | None = None) -> None:
    dataset_id = int(dataset['id'])
    dataset_path = Path(dataset['stored_path'])
    filters = filters or {}
    structural_candidates = {
        'market',
        'period',
    }
    requested_aggregation = str(filters.get('aggregation') or '').strip()
    if requested_aggregation and requested_aggregation != 'all':
        structural_candidates.add(requested_aggregation)
    structural_candidates.update((filters.get('extra_filters') or {}).keys())
    structural_columns = [column for column in required_columns if column in structural_candidates]
    if not repository.dataset_rows_table_exists(dataset_id):
        if not dataset_path.exists():
            return
        df = load_cached_dataset(dataset_path)
        repository.replace_dataset_rows(dataset_id, df)
        return

    repository.ensure_dataset_row_indexes(dataset_id)
    missing_columns = [
        column for column in structural_columns
        if repository.resolve_dataset_row_column_name(dataset_id, column) is None
    ]
    if not missing_columns or not dataset_path.exists():
        return

    # Legacy materialized tables may be missing normalized dimensions such as
    # operator/region/vendor. Rebuild them from source so aggregations work.
    df = load_cached_dataset(dataset_path)
    repository.replace_dataset_rows(dataset_id, df)


def process_dataset(
    dataset_id: int,
    dataset_path: Path,
    username: str,
    vodafone_mapping_dataset_id: int | None = None,
    three_mapping_dataset_id: int | None = None,
    task_repository: Repository | None = None,
) -> None:
    task_repository = task_repository or repository
    # FastAPI background tasks can be submitted from separate requests at the
    # same time.  Serialize them per workspace DB: a task waits visibly as
    # Queued, then becomes Processing only after the preceding task finishes.
    workspace_key = str(task_repository.db_path.resolve())
    with DATASET_PROCESSING_LOCKS_LOCK:
        workspace_lock = DATASET_PROCESSING_LOCKS.setdefault(workspace_key, Lock())
    with workspace_lock:
        dataset = task_repository.get_dataset(dataset_id)
        if not dataset or not dataset_path.exists():
            if dataset:
                task_repository.update_dataset_profile(
                    dataset_id,
                    status='failed',
                    progress=100,
                    last_error='The source file is missing. Reupload the dataset before retrying.',
                    processed_at=now_iso(),
                )
            clear_stop_request(dataset_id)
            return
        clear_stop_request(dataset_id)
        task_repository.update_dataset_profile(dataset_id, status='processing', progress=10, last_error=None)
        try:
            def progress_update(value: int) -> None:
                ensure_not_stopped(dataset_id)
                task_repository.update_dataset_profile(dataset_id, progress=max(10, min(95, int(value))))

            selected_kind = str(dataset['dataset_kind'] or '').strip().lower()
            forced_dataset_kind = selected_kind if selected_kind in UPLOAD_DATASET_KINDS else None
            rebuild_result = rebuild_dataset_artifacts(
                dataset_id,
                dataset_path,
                progress_callback=progress_update,
                forced_dataset_kind=forced_dataset_kind,
                vodafone_mapping_dataset_id=vodafone_mapping_dataset_id,
                three_mapping_dataset_id=three_mapping_dataset_id,
                task_repository=task_repository,
            )
            task_repository.add_log(username, 'process_dataset', json.dumps({
                'dataset_id': dataset_id,
                'file': dataset_path.name,
                'status': 'ready',
                'vodafone_mapping_dataset_id': vodafone_mapping_dataset_id,
                'three_mapping_dataset_id': three_mapping_dataset_id,
            }))
            if rebuild_result.get('vendor_mapping_error'):
                task_repository.add_log(username, 'vendor_mapping_skipped', json.dumps({
                    'dataset_id': dataset_id,
                    'error': rebuild_result['vendor_mapping_error'],
                }))
        except ProcessingStopped as exc:
            progress = int((task_repository.get_dataset(dataset_id) or {}).get('progress') or 0)
            task_repository.update_dataset_profile(
                dataset_id,
                status='stopped',
                progress=max(0, min(99, progress)),
                last_error=str(exc),
                processed_at=now_iso(),
            )
            task_repository.add_log(username, 'stop_dataset', json.dumps({'dataset_id': dataset_id, 'file': dataset_path.name}))
        except Exception as exc:
            task_repository.update_dataset_profile(dataset_id, status='failed', progress=100, last_error=str(exc), processed_at=now_iso())
            task_repository.add_log(username, 'process_dataset_failed', json.dumps({'dataset_id': dataset_id, 'file': dataset_path.name, 'error': str(exc)}))
        finally:
            clear_stop_request(dataset_id)
            # Materialising dataset rows can substantially change the
            # workspace database even though the uploaded file itself was
            # already counted when it was saved.
            invalidate_workspace_size_cache(task_repository.db_path.parent)


def enqueue_dataset_processing(
    background_tasks: BackgroundTasks,
    dataset_id: int,
    dataset_path: Path,
    username: str,
    vodafone_mapping_dataset_id: int | None = None,
    three_mapping_dataset_id: int | None = None,
) -> None:
    clear_stop_request(dataset_id)
    stale_keys = [key for key in ANALYSIS_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_keys:
        ANALYSIS_CACHE.pop(key, None)
    stale_dataset_keys = [key for key in DATAFRAME_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_dataset_keys:
        DATAFRAME_CACHE.pop(key, None)
    repository.update_dataset_profile(dataset_id, status='queued', progress=0, last_error=None, processed_at=None)
    # BackgroundTasks runs after the response is sent. Capture the workspace
    # database now, rather than resolving the mutable active workspace later.
    task_repository = Repository(Path(repository.db_path))
    background_tasks.add_task(
        process_dataset,
        dataset_id,
        dataset_path,
        username,
        vodafone_mapping_dataset_id,
        three_mapping_dataset_id,
        task_repository,
    )


def rebuild_dataset_artifacts(
    dataset_id: int,
    dataset_path: Path,
    progress_callback: Callable[[int], None] | None = None,
    forced_dataset_kind: str | None = None,
    vodafone_mapping_dataset_id: int | None = None,
    three_mapping_dataset_id: int | None = None,
    task_repository: Repository | None = None,
) -> dict[str, Any]:
    task_repository = task_repository or repository
    workspace_dimensions = load_repository_calculated_dimensions(task_repository)
    df = load_dataset(dataset_path, progress_callback=progress_callback)
    if forced_dataset_kind in UPLOAD_DATASET_KINDS:
        df['dataset_kind'] = forced_dataset_kind
    if forced_dataset_kind == 'mapping_vodafone':
        df = add_vfuk_gcid_column(df)
    elif forced_dataset_kind == 'mapping_three':
        df = add_three_gcid_column(df)
    dataset_kind = df['dataset_kind'].iloc[0] if 'dataset_kind' in df.columns and not df.empty else (forced_dataset_kind or infer_dataset_kind(df, dataset_path.name))
    auto_vendor_mapping_applied = False
    auto_vendor_mapping_error: str | None = None
    if dataset_kind in CDR_DATASET_KINDS and (vodafone_mapping_dataset_id or three_mapping_dataset_id):
        if progress_callback:
            progress_callback(52)
        vodafone_mapping = (
            _reporting_dataset(vodafone_mapping_dataset_id, 'mapping_vodafone', task_repository)
            if vodafone_mapping_dataset_id else None
        )
        three_mapping = (
            _reporting_dataset(three_mapping_dataset_id, 'mapping_three', task_repository)
            if three_mapping_dataset_id else None
        )
        try:
            df = assign_cdr_vendors(
                df,
                _reporting_frame(vodafone_mapping['id'], task_repository) if vodafone_mapping else None,
                _reporting_frame(three_mapping['id'], task_repository) if three_mapping else None,
            )
            auto_vendor_mapping_applied = True
        except Exception as exc:
            # Mapping is optional during import. A mapping issue must not make
            # an otherwise valid CDR unusable in Workspace or Dashboard.
            auto_vendor_mapping_error = str(exc)
    if dataset_kind in CDR_DATASET_KINDS:
        df = materialize_cdr_derived_columns(df, dataset_kind, workspace_dimensions)
    store_cached_dataset_frame(dataset_path, df)
    task_repository.replace_dataset_rows(dataset_id, df)
    if dataset_kind in CDR_DATASET_KINDS:
        task_repository.replace_reporting_rows(dataset_id, dataset_kind, df)
        task_repository.copy_dataset_rows_to_reporting(
            dataset_id, dataset_kind,
            combined_reporting_required_columns(workspace_dimensions, dataset_kind),
        )
    if progress_callback:
        progress_callback(62)
    task_repository.update_dataset_profile(dataset_id, progress=62, dataset_kind=dataset_kind)
    summary = summarise_dataset(df)
    if progress_callback:
        progress_callback(72)
    task_repository.update_dataset_profile(dataset_id, progress=72)
    available_metrics = derive_available_metrics(df)
    analysis = build_analysis(df, {'aggregation': 'all', 'extra_filters': {}}, '')
    if progress_callback:
        progress_callback(84)
    task_repository.update_dataset_profile(dataset_id, progress=84)
    profile_df = restrict_frame_to_metric(df, analysis.selected_metric)
    filter_options = derive_filter_options(profile_df)
    available_aggregations = derive_available_aggregations(filter_options)
    default_aggregation = analysis.filters.get('aggregation')
    if default_aggregation == 'all' and available_aggregations:
        default_aggregation = available_aggregations[0]
    if progress_callback:
        progress_callback(94)
    vendor_values_complete = bool(
        'vendor' in df.columns
        and not df.empty
        and df['vendor'].fillna('').astype(str).str.strip().ne('').all()
    )
    task_repository.update_dataset_profile(
        dataset_id,
        status='ready',
        progress=100,
        normalization_version=DATASET_NORMALIZATION_VERSION,
        vendor_mapping_applied=auto_vendor_mapping_applied,
        vendor_values_complete=vendor_values_complete,
        dataset_kind=dataset_kind,
        row_count=summary.rows,
        column_count=len(summary.columns),
        default_metric=analysis.selected_metric,
        default_aggregation=default_aggregation or 'all',
        available_metrics_json=json.dumps(available_metrics),
        available_aggregations_json=json.dumps(available_aggregations),
        filter_options_json=json.dumps(filter_options),
        summary_json=json.dumps(asdict(summary)),
        kpis_json=json.dumps(analysis.kpis),
        processed_at=now_iso(),
        last_error=None,
    )
    return {
        'df': df,
        'summary': summary,
        'analysis': analysis,
        'filter_options': filter_options,
        'vendor_mapping_error': auto_vendor_mapping_error,
    }


def ensure_mapping_gcid(dataset: dict[str, Any]) -> dict[str, Any]:
    """Backfill GCID for mappings processed before the column was introduced."""
    dataset_kind = dataset.get('dataset_kind')
    if dataset_kind not in {'mapping_vodafone', 'mapping_three'} or not dataset.get('is_ready'):
        return dataset
    dataset_id = int(dataset['id'])
    if (
        repository.resolve_dataset_row_column_name(dataset_id, 'GCID')
        and int(dataset.get('normalization_version') or 1) >= DATASET_NORMALIZATION_VERSION
    ):
        return dataset

    dataset_path = Path(dataset.get('stored_path') or '')
    if not dataset_path.exists():
        return dataset
    rebuild_dataset_artifacts(dataset_id, dataset_path, forced_dataset_kind=dataset_kind)
    refreshed = repository.get_dataset(dataset_id)
    return serialize_dataset_row(refreshed) if refreshed else dataset


def persist_mapped_cdr_frame(dataset: dict[str, Any], frame: pd.DataFrame) -> None:
    """Replace a materialized CDR after vendor mapping and refresh its profile."""
    dataset_id = int(dataset['id'])
    if str(dataset.get('dataset_kind') or '').casefold() in CDR_DATASET_KINDS:
        frame = materialize_cdr_derived_columns(frame, str(dataset.get('dataset_kind') or '').casefold())
    repository.replace_dataset_rows(dataset_id, frame)
    dataset_kind = str(dataset.get('dataset_kind') or '').casefold()
    if dataset_kind in CDR_DATASET_KINDS:
        workspace_dimensions = load_workspace_calculated_dimensions()
        repository.replace_reporting_rows(dataset_id, dataset_kind, frame)
        repository.copy_dataset_rows_to_reporting(
            dataset_id, dataset_kind,
            combined_reporting_required_columns(workspace_dimensions, dataset_kind),
        )
    summary = summarise_dataset(frame)
    available_metrics = derive_available_metrics(frame)
    analysis = build_analysis(frame, {'aggregation': 'all', 'extra_filters': {}}, '')
    profile_df = restrict_frame_to_metric(frame, analysis.selected_metric)
    filter_options = derive_filter_options(profile_df)
    available_aggregations = derive_available_aggregations(filter_options)
    default_aggregation = analysis.filters.get('aggregation')
    if default_aggregation == 'all' and available_aggregations:
        default_aggregation = available_aggregations[0]
    repository.update_dataset_profile(
        dataset_id,
        normalization_version=DATASET_NORMALIZATION_VERSION,
        vendor_mapping_applied=True,
        vendor_values_complete=bool(
            'vendor' in frame.columns
            and not frame.empty
            and frame['vendor'].fillna('').astype(str).str.strip().ne('').all()
        ),
        row_count=summary.rows,
        column_count=len(summary.columns),
        default_metric=analysis.selected_metric,
        default_aggregation=default_aggregation or 'all',
        available_metrics_json=json.dumps(available_metrics),
        available_aggregations_json=json.dumps(available_aggregations),
        filter_options_json=json.dumps(filter_options),
        summary_json=json.dumps(asdict(summary)),
        kpis_json=json.dumps(analysis.kpis),
        processed_at=now_iso(),
        last_error=None,
    )


def ensure_canonical_mapped_vendor_column(dataset: dict[str, Any] | None) -> dict[str, Any] | None:
    """Migrate already-mapped CDRs from the old ``vendor__2`` storage name."""
    if not dataset or not dataset.get('is_ready') or not dataset.get('vendor_mapping_applied'):
        return dataset
    dataset_id = int(dataset['id'])
    columns = repository.list_dataset_row_columns(dataset_id)
    if 'vendor' in columns:
        return dataset
    legacy_vendor_column = next(
        (column for column in columns if re.fullmatch(r'vendor__\d+', str(column).casefold())),
        None,
    )
    if not legacy_vendor_column:
        return dataset
    frame = _reporting_frame(dataset_id)
    calculated_vendor = frame[legacy_vendor_column].copy()
    collisions = [
        column for column in frame.columns
        if str(column).casefold() == 'vendor' or re.fullmatch(r'vendor__\d+', str(column).casefold())
    ]
    frame = frame.drop(columns=collisions)
    frame['vendor'] = calculated_vendor
    leading_columns = [column for column in ('source_sheet', 'vendor') if column in frame.columns]
    remaining_columns = [column for column in frame.columns if column not in {*leading_columns, 'report_vendor'}]
    if 'report_vendor' in frame.columns:
        frame = frame.loc[:, [*leading_columns, *remaining_columns, 'report_vendor']]
    else:
        frame = frame.loc[:, [*leading_columns, *remaining_columns]]
    persist_mapped_cdr_frame(dataset, frame)
    clear_dataset_analysis_cache(Path(dataset['stored_path']))
    refreshed = repository.get_dataset(dataset_id)
    return serialize_dataset_row(refreshed) if refreshed else dataset


def process_vendor_mapping(
    dataset_id: int,
    username: str,
    vodafone_mapping_dataset_id: int | None,
    three_mapping_dataset_id: int | None,
) -> None:
    """Apply persisted mapping files as a queued Workspace operation."""
    dataset_row = repository.get_dataset(dataset_id)
    if not dataset_row:
        return
    dataset = serialize_dataset_row(dataset_row)
    dataset_path = Path(dataset['stored_path'])
    repository.update_dataset_profile(dataset_id, status='processing', progress=10, last_error=None)
    try:
        ensure_not_stopped(dataset_id)
        vodafone_mapping = (
            _reporting_dataset(vodafone_mapping_dataset_id, 'mapping_vodafone')
            if vodafone_mapping_dataset_id else None
        )
        three_mapping = (
            _reporting_dataset(three_mapping_dataset_id, 'mapping_three')
            if three_mapping_dataset_id else None
        )
        repository.update_dataset_profile(dataset_id, progress=35)
        ensure_not_stopped(dataset_id)
        mapped_frame = assign_cdr_vendors(
            _reporting_frame(dataset_id),
            _reporting_frame(vodafone_mapping['id']) if vodafone_mapping else None,
            _reporting_frame(three_mapping['id']) if three_mapping else None,
        )
        repository.update_dataset_profile(dataset_id, progress=75)
        ensure_not_stopped(dataset_id)
        persist_mapped_cdr_frame(dataset, mapped_frame)
        clear_dataset_analysis_cache(dataset_path)
        repository.update_dataset_profile(dataset_id, status='ready', progress=100, last_error=None, processed_at=now_iso())
        repository.add_log(username, 'map_dataset_vendors', json.dumps({
            'dataset_id': dataset_id,
            'vodafone_mapping_dataset_id': vodafone_mapping_dataset_id,
            'three_mapping_dataset_id': three_mapping_dataset_id,
            'status': 'ready',
        }))
    except ProcessingStopped as exc:
        repository.update_dataset_profile(dataset_id, status='stopped', progress=99, last_error=str(exc), processed_at=now_iso())
        repository.add_log(username, 'stop_vendor_mapping', json.dumps({'dataset_id': dataset_id}))
    except Exception as exc:
        # Mapping reads and enriches an already materialised CDR.  Until the
        # final persistence step succeeds, it does not alter that CDR.  A bad
        # mapping or an unrecognised Cell ID field must therefore leave the
        # source dataset ready for Preview, Dashboard and a later retry.
        repository.update_dataset_profile(dataset_id, status='ready', progress=100, last_error=None, processed_at=now_iso())
        repository.add_log(username, 'map_dataset_vendors_failed', json.dumps({'dataset_id': dataset_id, 'error': str(exc)}))
    finally:
        clear_stop_request(dataset_id)


def enqueue_vendor_mapping(
    background_tasks: BackgroundTasks,
    dataset_id: int,
    username: str,
    vodafone_mapping_dataset_id: int | None,
    three_mapping_dataset_id: int | None,
) -> None:
    """Queue one CDR mapping without blocking the Workspace request."""
    clear_stop_request(dataset_id)
    repository.update_dataset_profile(dataset_id, status='queued', progress=0, last_error=None, processed_at=None)
    background_tasks.add_task(
        process_vendor_mapping,
        dataset_id,
        username,
        vodafone_mapping_dataset_id,
        three_mapping_dataset_id,
    )


def queue_legacy_vendor_mapping_recovery(
    background_tasks: BackgroundTasks,
    datasets: list[dict[str, Any]],
    username: str,
) -> bool:
    """Recover CDRs failed by the former inline Vendor-mapping implementation."""
    queued_recovery = False
    for dataset in datasets:
        error_text = str(dataset.get('last_error') or '').casefold()
        if (
            dataset.get('status') != 'failed'
            or dataset.get('dataset_kind') not in CDR_DATASET_KINDS
            or not any(marker in error_text for marker in LEGACY_VENDOR_MAPPING_FAILURE_MARKERS)
        ):
            continue
        dataset_path = Path(dataset.get('stored_path') or '')
        if not dataset_path.exists():
            continue
        # Rebuild from the original workbook with no mappings selected. This
        # restores Preview/Dashboard availability without repeating the error.
        enqueue_dataset_processing(background_tasks, int(dataset['id']), dataset_path, username)
        repository.add_log(username, 'recover_vendor_mapping_dataset', json.dumps({'dataset_id': dataset['id']}))
        queued_recovery = True
    return queued_recovery


def process_vendor_clearing(dataset_id: int, username: str) -> None:
    """Rebuild one CDR without the persisted Vendor enrichment in the queue."""
    dataset_row = repository.get_dataset(dataset_id)
    if not dataset_row:
        return
    dataset = serialize_dataset_row(dataset_row)
    dataset_path = Path(dataset['stored_path'])
    repository.update_dataset_profile(dataset_id, status='processing', progress=10, last_error=None)
    try:
        ensure_not_stopped(dataset_id)
        rebuild_dataset_artifacts(
            dataset_id,
            dataset_path,
            forced_dataset_kind=dataset['dataset_kind'],
            progress_callback=lambda progress: repository.update_dataset_profile(
                dataset_id, progress=max(10, min(95, int(progress)))
            ),
        )
        clear_dataset_analysis_cache(dataset_path)
        repository.update_dataset_profile(dataset_id, status='ready', progress=100, last_error=None, processed_at=now_iso())
        repository.add_log(username, 'clear_dataset_vendors', json.dumps({'dataset_id': dataset_id, 'status': 'ready'}))
    except ProcessingStopped as exc:
        repository.update_dataset_profile(dataset_id, status='stopped', progress=99, last_error=str(exc), processed_at=now_iso())
        repository.add_log(username, 'stop_vendor_clearing', json.dumps({'dataset_id': dataset_id}))
    except Exception as exc:
        repository.update_dataset_profile(dataset_id, status='failed', progress=100, last_error=str(exc), processed_at=now_iso())
        repository.add_log(username, 'clear_dataset_vendors_failed', json.dumps({'dataset_id': dataset_id, 'error': str(exc)}))
    finally:
        clear_stop_request(dataset_id)


def enqueue_vendor_clearing(background_tasks: BackgroundTasks, dataset_id: int, username: str) -> None:
    """Queue Vendor clearing so the Workspace remains available to the user."""
    clear_stop_request(dataset_id)
    repository.update_dataset_profile(dataset_id, status='queued', progress=0, last_error=None, processed_at=None)
    background_tasks.add_task(process_vendor_clearing, dataset_id, username)


def clear_dataset_analysis_cache(dataset_path: Path) -> None:
    resolved_path = str(dataset_path.resolve())
    for key in [key for key in ANALYSIS_CACHE if resolved_path in key]:
        ANALYSIS_CACHE.pop(key, None)


def refresh_selected_dataset_if_stale(selected_dataset: dict[str, Any] | None) -> dict[str, Any] | None:
    if not selected_dataset or not selected_dataset.get('is_ready'):
        return selected_dataset
    if int(selected_dataset.get('normalization_version') or 1) >= DATASET_NORMALIZATION_VERSION:
        return selected_dataset

    dataset_id = int(selected_dataset['id'])
    if repository.dataset_rows_table_exists(dataset_id) and repository.refresh_dataset_row_normalized_dimensions(dataset_id):
        filter_options = {
            dimension: values
            for dimension in FILTER_DIMENSIONS
            if (values := repository.list_distinct_dataset_row_values(dataset_id, dimension))
        }
        available_aggregations = derive_available_aggregations(filter_options)

        repository.update_dataset_profile(
            dataset_id,
            normalization_version=DATASET_NORMALIZATION_VERSION,
            filter_options_json=json.dumps(filter_options),
            available_aggregations_json=json.dumps(available_aggregations),
        )

    refreshed = repository.get_dataset(int(selected_dataset['id']))
    return serialize_dataset_row(refreshed) if refreshed else selected_dataset


def create_session(response: Response, user: SessionUser) -> None:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite='lax')


def current_user(request: Request) -> SessionUser:
    token = request.cookies.get(SESSION_COOKIE)
    user = SESSIONS.get(token or '')
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={'Location': '/login'})
    return user


@app.post('/account/change-password')
def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirmation: str = Form(...),
    user: SessionUser = Depends(current_user),
) -> JSONResponse:
    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail='All password fields are required.')
    if new_password != new_password_confirmation:
        raise HTTPException(status_code=400, detail='The new passwords do not match.')
    record = repository.get_user(user.username)
    if not record or not record.active:
        raise HTTPException(status_code=403, detail='The current user is not active.')
    try:
        valid_current = verify_password(current_password, record.password_hash)
    except (TypeError, ValueError):
        valid_current = False
    if not valid_current:
        raise HTTPException(status_code=400, detail='The current password is incorrect.')
    repository.update_password(user.username, new_password)
    repository.add_log(user.username, 'change_password', 'Password changed from the account badge.')
    return JSONResponse({'changed': True})


def admin_user(user: SessionUser = Depends(current_user)) -> SessionUser:
    if user.role not in {'admin', 'super-admin'}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin access required')
    return user


def super_admin_user(user: SessionUser = Depends(current_user)) -> SessionUser:
    if user.role != 'super-admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Super-admin access required')
    return user


def render_template(request: Request, template_name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    template_user = context.get('user')
    embedded_template_editor = bool(context.get('embedded_template_editor'))
    header_workspaces = workspace_registry.list() if isinstance(template_user, SessionUser) and not embedded_template_editor else []
    header_workspace_access = workspace_access_map(template_user, header_workspaces) if isinstance(template_user, SessionUser) else {}
    payload = {
        'request': request,
        'app_name': __app_name__,
        'app_version': __version__,
        'app_release_date': __release_date__,
        'asset_version': asset_version,
        'static_path': lambda asset_path: str(request.app.url_path_for('static', path=asset_path)),
        'active_workspace': active_workspace,
        'active_workspace_size': format_workspace_size(workspace_disk_usage(active_workspace)) if active_workspace and not embedded_template_editor else None,
        'header_workspaces': header_workspaces,
        'header_workspace_access': header_workspace_access,
        'header_workspace_sizes': {item.id: format_workspace_size(workspace_disk_usage(item)) for item in header_workspaces},
        **context,
    }
    response = templates.TemplateResponse(request, template_name, payload, status_code=status_code)
    # These pages render mutable workspace/user state.  In particular, an
    # imported configuration must not leave a browser showing a previously
    # cached Admin page while Database Management already reads the new DB.
    response.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    return response


def resolve_doc_path(doc_name: str) -> Path:
    normalized = str(doc_name or '').strip().lower()
    allowed = {
        'readme': 'README.md',
        'changelog': 'CHANGELOG.md',
        'help': f'help/{HELP_HOME_DOCUMENT}',
    }
    relative_path = allowed.get(normalized)
    if not relative_path:
        raise HTTPException(status_code=404, detail='Document not found')
    target = (PROJECT_ROOT / relative_path).resolve()
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f'Document not found: {relative_path}')
    return target


def resolve_help_doc_path(doc_file: str) -> Path:
    requested = str(doc_file or '').strip().replace('\\', '/')
    if not requested.lower().endswith('.md'):
        raise HTTPException(status_code=400, detail='Only Markdown help documents are allowed.')
    help_root = (PROJECT_ROOT / 'help').resolve()
    target = (help_root / requested).resolve()
    try:
        target.relative_to(help_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Invalid help document path.') from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f'Help document not found: {requested}')
    return target


def choose_selected_dataset(
    datasets: list[dict[str, Any]], dataset_id: int | None, input_kind: str | None,
    allowed_kinds: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    ready_datasets = [
        dataset for dataset in datasets
        if dataset.get('is_ready') and (allowed_kinds is None or dataset.get('dataset_kind') in allowed_kinds)
    ]
    if dataset_id is not None:
        for dataset in ready_datasets:
            if dataset['id'] == dataset_id:
                return dataset
    filtered_datasets = [dataset for dataset in ready_datasets if not input_kind or dataset.get('dataset_kind') == input_kind]
    candidate_datasets = filtered_datasets or ready_datasets
    return candidate_datasets[0] if candidate_datasets else None


def enrich_selected_dataset_for_dashboard(selected_dataset: dict[str, Any] | None) -> dict[str, Any] | None:
    if not selected_dataset or not selected_dataset['is_ready']:
        return selected_dataset
    selected_dataset['metric_availability'] = derive_runtime_metric_availability(selected_dataset)
    selected_dataset['available_metrics'] = list(selected_dataset['metric_availability'].keys())
    selected_dataset['selectable_metrics'] = [
        metric for metric, enabled in selected_dataset['metric_availability'].items() if enabled
    ]
    if selected_dataset.get('default_metric') not in selected_dataset['selectable_metrics']:
        selected_dataset['default_metric'] = selected_dataset['selectable_metrics'][0] if selected_dataset['selectable_metrics'] else None
    filter_options = selected_dataset.get('filter_options') or {}
    selected_dataset['available_cdf_groupings'] = [
        item for item in ['vendor', 'market', 'operator', 'region', 'city']
        if len(filter_options.get(item, []) or []) > 1
    ]
    return selected_dataset


def build_dashboard_table_rows(df: pd.DataFrame, selected_metrics: list[str], aggregation: str | None) -> list[dict[str, Any]]:
    if df.empty:
        return []

    usable_metrics = [
        metric for metric in selected_metrics
        if metric in df.columns and pd.to_numeric(df[metric], errors='coerce').notna().any()
    ]
    if not usable_metrics:
        return []

    if aggregation and aggregation != 'all' and aggregation in df.columns:
        grouped_rows: list[dict[str, Any]] = []
        grouped = df.dropna(subset=[aggregation]).groupby(aggregation, dropna=False)
        for group_name, group in grouped:
            row: dict[str, Any] = {
                aggregation: group_name,
                'samples': int(len(group.index)),
            }
            if 'success' in group.columns:
                row['success_rate_pct'] = round(float(group['success'].fillna(False).astype(bool).mean() * 100), 2)
            for metric in usable_metrics:
                values = pd.to_numeric(group[metric], errors='coerce').dropna()
                row[metric] = round(float(values.mean()), 4) if not values.empty else None
            grouped_rows.append(row)
        return sorted(grouped_rows, key=lambda item: -int(item.get('samples') or 0))[:50]

    preferred_columns: list[str] = []
    for column in ['market', 'operator', 'vendor', 'region', 'city', 'session_type', 'test_name', 'direction', 'technology_primary', 'source_sheet', 'event_start_time', 'status']:
        if column in df.columns and column not in preferred_columns:
            preferred_columns.append(column)
    preferred_columns.extend(metric for metric in usable_metrics if metric not in preferred_columns)
    rows = df.copy()
    if 'event_start_time' in rows.columns:
        rows = rows.sort_values('event_start_time', ascending=False)
    elif usable_metrics:
        rows = rows.sort_values(usable_metrics[0], ascending=False)
    rows = rows.head(50)
    return rows[preferred_columns].to_dict(orient='records')


def build_dataset_view_state(
    dataset_id: int | None, input_kind: str | None, allowed_kinds: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any] | None]:
    datasets = [serialize_dataset_row(row) for row in repository.list_datasets()]
    ready_datasets = [
        dataset for dataset in datasets
        if dataset['is_ready'] and (allowed_kinds is None or dataset.get('dataset_kind') in allowed_kinds)
    ]
    input_kind_options = sorted({dataset.get('dataset_kind') or 'generic' for dataset in ready_datasets})
    valid_input_kind = input_kind if input_kind in input_kind_options else None
    selected_dataset = choose_selected_dataset(datasets, dataset_id, valid_input_kind, allowed_kinds)
    return datasets, ready_datasets, input_kind_options, selected_dataset


def workspace_combined_tables(task_repository: Repository | None = None) -> list[dict[str, Any]]:
    """Return existing combined CDR tables for the Workspace dataset panel."""
    task_repository = task_repository or repository
    combined: list[dict[str, Any]] = []
    with task_repository.connection() as connection:
        for kind in ('data', 'voice', 'speech'):
            table_name = task_repository.reporting_rows_table_name(kind)
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,),
            ).fetchone()
            if not exists:
                continue
            row_count = connection.execute(
                f'SELECT COUNT(*) AS count FROM {task_repository._quote_identifier(table_name)}',
            ).fetchone()['count']
            updated_at = task_repository.get_workspace_state(f'combined_reporting_updated_{kind}')
            if not updated_at:
                dataset_dates = [
                    str(dataset['updated_at'] or dataset['uploaded_at'] or '')
                    for dataset in task_repository.list_datasets()
                    if str(dataset['dataset_kind'] or '').casefold() == kind
                ]
                updated_at = max(dataset_dates, default='')
            source_datasets = [
                dataset for dataset in task_repository.list_datasets()
                if dataset['status'] == 'ready' and str(dataset['dataset_kind'] or '').casefold() == kind
            ]
            expected_row_count = sum(int(dataset['row_count'] or 0) for dataset in source_datasets)
            combined.append({
                'name': f'CDR-{kind.title()} (combined)',
                'kind': kind,
                'table_name': table_name,
                'row_count': int(row_count or 0),
                'expected_row_count': expected_row_count,
                'has_missing_rows': int(row_count or 0) != expected_row_count,
                'updated_at_label': format_local_timestamp(updated_at) if updated_at else '—',
            })
    return combined


def combined_cdr_integrity(kind: str, task_repository: Repository | None = None) -> dict[str, Any]:
    """Compare a combined CDR table with its ready individual source datasets."""
    task_repository = task_repository or repository
    normalized_kind = str(kind or '').casefold()
    if normalized_kind not in CDR_DATASET_KINDS:
        raise ValueError('Unknown combined CDR table.')
    source_datasets = [
        dataset for dataset in task_repository.list_datasets()
        if dataset['status'] == 'ready' and str(dataset['dataset_kind'] or '').casefold() == normalized_kind
    ]
    expected_row_count = sum(int(dataset['row_count'] or 0) for dataset in source_datasets)
    row_count = task_repository.reporting_row_count(normalized_kind)
    return {
        'kind': normalized_kind,
        'row_count': row_count,
        'expected_row_count': expected_row_count,
        'has_missing_rows': row_count != expected_row_count,
    }


def recreate_combined_cdr_table(
    workspace: Workspace,
    kind: str,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, int]:
    """Rebuild one combined CDR table and recover missing individual row stores."""
    task_repository = Repository(
        workspace.database_path,
        global_db_path=repository.global_db_path,
        workspace_registry_db_path=workspace_registry.registry_path,
    )
    dimensions = load_repository_calculated_dimensions(task_repository)
    required_columns = combined_reporting_required_columns(dimensions, kind)
    all_datasets = list(task_repository.list_datasets())
    datasets = [
        dataset for dataset in all_datasets
        if dataset['status'] == 'ready' and str(dataset['dataset_kind'] or '').casefold() == kind
    ]
    ready_mappings = {
        mapping_kind: next(
            (
                int(dataset['id']) for dataset in all_datasets
                if dataset['status'] == 'ready'
                and str(dataset['dataset_kind'] or '').casefold() == mapping_kind
            ),
            None,
        )
        for mapping_kind in ('mapping_vodafone', 'mapping_three')
    }
    total = max(len(datasets) * 100 + 1, 1)
    task_repository.drop_reporting_table(kind)
    for index, dataset in enumerate(datasets):
        dataset_id = int(dataset['id'])
        expected_rows = int(dataset['row_count'] or 0)
        materialized_rows = task_repository.dataset_row_count(dataset_id)
        if materialized_rows == 0 or (expected_rows and materialized_rows != expected_rows):
            dataset_path = Path(str(dataset['stored_path'] or ''))
            if not dataset_path.is_file():
                raise FileNotFoundError(
                    f"{dataset['file_name']} has {materialized_rows} materialized rows instead of "
                    f'{expected_rows}, and its source file is unavailable.'
                )
            if progress_callback:
                progress_callback(index * 100, total, f"Recovering rows for {dataset['file_name']}")

            def rebuild_progress(value: int, *, offset: int = index * 100, name: str = str(dataset['file_name'])) -> None:
                if progress_callback:
                    progress_callback(offset + min(max(int(value), 0), 95), total, f'Recovering rows for {name}')

            use_mappings = bool(dataset['vendor_mapping_applied'])
            rebuild_dataset_artifacts(
                dataset_id,
                dataset_path,
                progress_callback=rebuild_progress,
                forced_dataset_kind=kind,
                vodafone_mapping_dataset_id=ready_mappings['mapping_vodafone'] if use_mappings else None,
                three_mapping_dataset_id=ready_mappings['mapping_three'] if use_mappings else None,
                task_repository=task_repository,
            )
            materialized_rows = task_repository.dataset_row_count(dataset_id)
        task_repository.copy_dataset_rows_to_reporting(dataset_id, kind, required_columns)
        combined_rows = task_repository.reporting_row_count(kind, dataset_id)
        if combined_rows != materialized_rows:
            raise RuntimeError(
                f"{dataset['file_name']} contributed {combined_rows} of {materialized_rows} rows to the combined table."
            )
        if progress_callback:
            progress_callback((index + 1) * 100, total, f"Added {dataset['file_name']}")
    total_rows = task_repository.reporting_row_count(kind)
    expected_total = sum(task_repository.dataset_row_count(int(dataset['id'])) for dataset in datasets)
    if total_rows != expected_total:
        raise RuntimeError(f'The combined CDR-{kind.upper()} table contains {total_rows} of {expected_total} rows.')
    task_repository.set_workspace_state(f'combined_reporting_updated_{kind}', now_iso())
    task_repository.set_workspace_state(f'combined_reporting_error_{kind}', '')
    if progress_callback:
        progress_callback(total, total, f'Combined CDR-{kind.upper()} table is ready')
    return {'datasets': len(datasets), 'rows': total_rows, 'tables': len(datasets) + 1}


def choose_filter_values(query_values: list[str], options: dict[str, list[str]], key: str) -> list[str]:
    values = options.get(key, [])
    selected = [value for value in query_values if value in values]
    if selected:
        return selected
    if query_values:
        return [value for value in query_values if value]
    if len(values) == 1:
        return [values[0]]
    return []


def should_load_analysis(request: Request) -> bool:
    return request.query_params.get('load') == '1'


async def save_upload_file(upload_file: UploadFile, destination: Path) -> None:
    with destination.open('wb') as output:
        while True:
            chunk = await upload_file.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    await upload_file.close()


def build_default_access_accounts() -> list[dict[str, str]]:
    # Credentials are stored per workspace. Once it is closed the repository
    # still points at its former path, which may have been moved or removed.
    if not active_workspace:
        return []
    defaults = [
        {'username': 'super', 'password': 'super123'},
        {'username': 'admin', 'password': 'admin123'},
        {'username': 'demo', 'password': 'demo123'},
    ]
    available_accounts: list[dict[str, str]] = []
    for item in defaults:
        record = repository.get_user(item['username'])
        if record and record.active and verify_password(item['password'], record.password_hash):
            available_accounts.append({**item, 'role': record.role})
    return available_accounts


ARCHIVE_FORMAT = 'dashboard-analytic-export'
ARCHIVE_VERSION = 1
UNCOMPRESSED_ARCHIVE_SUFFIXES = frozenset({
    '.7z', '.avi', '.docx', '.gif', '.gz', '.jpeg', '.jpg', '.mp3', '.mp4', '.pdf', '.png', '.pptx', '.rar',
    '.tar', '.tgz', '.webp', '.xlsx', '.xlsm', '.zip',
})


def export_package_dir() -> Path:
    """Keep temporary transfer packages outside individual workspaces."""
    return workspace_registry.registry_path.parent.parent / 'transfer-packages'


def _archive_compression(path: Path) -> int:
    return zipfile.ZIP_STORED if path.suffix.casefold() in UNCOMPRESSED_ARCHIVE_SUFFIXES else zipfile.ZIP_DEFLATED


def _archive_file(archive: zipfile.ZipFile, source: Path, archive_name: str, progress_callback: Callable[[int], None] | None = None) -> None:
    archive.write(source, archive_name, compress_type=_archive_compression(source))
    if progress_callback:
        progress_callback(source.stat().st_size)


def _archive_database(
    archive: zipfile.ZipFile,
    database_path: Path,
    archive_name: str,
    scratch_dir: Path | None = None,
    progress_callback: Callable[[int], None] | None = None,
    exclude_tables: tuple[str, ...] = (),
) -> None:
    """Add a consistent SQLite snapshot, compacting databases with substantial free space."""
    if not database_path.exists():
        return
    with tempfile.TemporaryDirectory(prefix='dashboard-analytic-export-', dir=scratch_dir) as temporary_dir:
        snapshot = Path(temporary_dir) / 'snapshot.db'
        with sqlite3.connect(database_path) as source:
            page_count = int(source.execute('PRAGMA page_count').fetchone()[0])
            free_pages = int(source.execute('PRAGMA freelist_count').fetchone()[0])
            # VACUUM INTO creates a consistent, compact copy.  It is much faster
            # overall for workspace databases whose deleted rows otherwise add
            # several unused GB to both the snapshot and ZIP operation.
            if page_count and free_pages / page_count >= 0.10:
                source.execute('VACUUM INTO ?', (str(snapshot),))
            else:
                with sqlite3.connect(snapshot) as target:
                    source.backup(target)
        if exclude_tables:
            with sqlite3.connect(snapshot) as target:
                for table in exclude_tables:
                    target.execute(f'DELETE FROM "{table.replace(chr(34), chr(34) * 2)}"')
        _archive_file(archive, snapshot, archive_name, progress_callback)


def _archive_tree(archive: zipfile.ZipFile, source: Path, archive_prefix: str, *, exclude_slides_templates: bool = False, progress_callback: Callable[[int], None] | None = None) -> None:
    if not source.exists():
        return
    for path in source.rglob('*'):
        if not path.is_file() or path.name.endswith(('-wal', '-shm')):
            continue
        relative_path = path.relative_to(source)
        if exclude_slides_templates and relative_path.parts and relative_path.parts[0] == 'slides-templates':
            continue
        _archive_file(archive, path, f'{archive_prefix}/{relative_path.as_posix()}', progress_callback)


def _workspace_archive_metadata(workspace: Workspace) -> dict[str, Any]:
    # The source id is required to translate user access grants when a Full
    # Environment is restored onto a server where the same workspace name is
    # already registered under a different local id.
    access_usernames = [
        str(user['username']) for user in repository.list_users()
        if workspace.id in repository.list_user_workspace_ids(int(user['id']))
    ]
    return {
        'id': workspace.id,
        'name': workspace.name,
        'source_input_dir': str(workspace.input_dir),
        'source_output_dir': str(workspace.output_dir),
        'access_usernames': access_usernames,
    }


def _archive_workspace(
    archive: zipfile.ZipFile, workspace: Workspace, archive_prefix: str, scratch_dir: Path | None = None,
    progress_callback: Callable[[int], None] | None = None, include_generated_outputs: bool = True,
) -> None:
    _archive_database(
        archive, workspace.database_path, f'{archive_prefix}/database.sqlite', scratch_dir, progress_callback,
        exclude_tables=() if include_generated_outputs else ('generated_jobs',),
    )
    _archive_tree(archive, workspace.slides_templates_dir, f'{archive_prefix}/slides-templates', progress_callback=progress_callback)
    _archive_tree(archive, workspace.input_dir, f'{archive_prefix}/input', progress_callback=progress_callback)
    if include_generated_outputs:
        _archive_tree(archive, workspace.output_dir, f'{archive_prefix}/output', progress_callback=progress_callback)


def export_archive_filename(target: str) -> str:
    # The generated package is unique on the server, but a static download
    # filename makes it too easy to re-import an older browser download.
    # Include seconds so each visible download can be identified unambiguously.
    generated_at = datetime.now().strftime('%Y%m%d-%H%M%S')
    if target == 'config':
        return f'dashboard-analytic-config_{generated_at}.zip'
    if target == 'slides-templates':
        return f'dashboard-analytic-slides-templates_{generated_at}.zip'
    if target == 'auto-calculated-fields':
        workspace_name = active_workspace.name if active_workspace else 'workspace'
        return f'{workspace_name}_auto-calculated-fields_{generated_at}.zip'
    if target == 'config-with-templates':
        return f'dashboard-analytic-config-with-slides-templates_{generated_at}.zip'
    if target == 'full-environment':
        return f'dashboard-analytic-full-environment_{generated_at}.zip'
    if target.startswith('workspace:'):
        workspace = workspace_registry.get(target.removeprefix('workspace:'))
        if workspace:
            return f'{workspace.name}_{generated_at}.zip'
    raise ValueError('Select a valid export option.')


def _selected_export_workspaces(workspace_ids: Iterable[str] | None) -> list[Workspace]:
    available = {workspace.id: workspace for workspace in workspace_registry.list()}
    if workspace_ids is None:
        return list(available.values())
    selected_ids = list(dict.fromkeys(str(workspace_id) for workspace_id in workspace_ids))
    missing = [workspace_id for workspace_id in selected_ids if workspace_id not in available]
    if missing:
        raise ValueError('One or more selected workspaces no longer exist.')
    if not selected_ids:
        raise ValueError('Select at least one workspace for the Full Environment export.')
    return [available[workspace_id] for workspace_id in selected_ids]


def build_export_archive_file(
    target: str, destination: Path, workspace_ids: Iterable[str] | None = None,
    progress_callback: Callable[[int], None] | None = None, include_generated_outputs: bool = True,
) -> str:
    """Create a portable archive on disk, keeping large exports out of RAM."""
    filename = export_archive_filename(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # ``settings.database_path`` changes with the active workspace and the
    # registry lives with workspace data, so retain the configured app root.
    config_root = application_config_dir
    def archive_configuration(archive: zipfile.ZipFile, *, include_templates: bool) -> None:
        """Archive application configuration, with its database as a known payload.

        ``application.db`` owns users, roles and workspace access.
        Slides Template registries belong to the workspace snapshots.  Do not rely on the currently selected
        workspace when deciding which database to export.
        """
        application_database = application_config_dir / 'application.db'
        if not application_database.is_file():
            raise FileNotFoundError('The application configuration database was not found.')
        # Transfer handshakes are local runtime state and must never be copied
        # into the destination as part of a configuration/full export.
        _archive_database(
            archive, application_database, 'config/application.db', destination.parent,
            progress_callback, exclude_tables=('transfer_offers',),
        )
        for path in config_root.iterdir():
            if (
                path == application_database
                or path == workspace_registry.registry_path
                or path == settings.slides_templates_dir
                or not path.is_file()
                or path.name.endswith(('-wal', '-shm'))
            ):
                continue
            _archive_file(archive, path, f'config/{path.name}', progress_callback)
        if include_templates:
            _archive_tree(archive, settings.slides_templates_dir, 'config/slides-templates', progress_callback=progress_callback)

    # Level 1 retains most of SQLite's compression benefit while avoiding the
    # disproportionate CPU cost of the default level on multi-GB databases.
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        if target in {'config', 'config-with-templates'}:
            include_templates = target == 'config-with-templates'
            manifest = {
                'format': ARCHIVE_FORMAT,
                'version': ARCHIVE_VERSION,
                'kind': 'config',
                'includes_slides_templates': include_templates,
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            archive_configuration(archive, include_templates=include_templates)
        elif target == 'slides-templates':
            source_id = next(iter(workspace_ids or ()), active_workspace.id if active_workspace else '')
            source_workspace = workspace_registry.get(source_id) if source_id else None
            if not source_workspace:
                raise ValueError('Open a workspace before exporting Slides Templates.')
            manifest = {
                'format': ARCHIVE_FORMAT, 'version': ARCHIVE_VERSION,
                'kind': 'slides-templates', 'includes_slides_templates': True,
                'source_workspace': {'id': source_workspace.id, 'name': source_workspace.name},
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            _archive_tree(archive, source_workspace.slides_templates_dir, 'slides-templates', progress_callback=progress_callback)
        elif target == 'auto-calculated-fields':
            source_workspace_id = next(iter(workspace_ids or ()), active_workspace.id if active_workspace else '')
            source_workspace = workspace_registry.get(source_workspace_id) if source_workspace_id else None
            if not source_workspace:
                raise ValueError('Open a workspace before exporting auto-calculated fields.')
            source_repository = Repository(
                source_workspace.database_path,
                global_db_path=repository.global_db_path,
                workspace_registry_db_path=workspace_registry.registry_path,
            )
            definitions = calculated_dimensions_json(
                load_workspace_calculated_dimensions()
                if active_workspace and source_workspace.id == active_workspace.id
                else parse_calculated_dimensions(source_repository.list_calculated_dimensions())
            )
            payload = json.dumps(definitions, indent=2, ensure_ascii=False).encode('utf-8')
            manifest = {
                'format': ARCHIVE_FORMAT,
                'version': ARCHIVE_VERSION,
                'kind': 'auto-calculated-fields',
                'source_workspace': {'id': source_workspace.id, 'name': source_workspace.name},
                'field_count': len(definitions),
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            archive.writestr('auto-calculated-fields.json', payload)
            if progress_callback:
                progress_callback(len(payload))
        elif target.startswith('workspace:'):
            workspace = workspace_registry.get(target.removeprefix('workspace:'))
            if not workspace:
                raise ValueError('Workspace not found.')
            manifest = {
                'format': ARCHIVE_FORMAT,
                'version': ARCHIVE_VERSION,
                'kind': 'workspace',
                'workspace': _workspace_archive_metadata(workspace),
                'includes_generated_outputs': include_generated_outputs,
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            _archive_workspace(
                archive, workspace, 'workspace', destination.parent, progress_callback,
                include_generated_outputs=include_generated_outputs,
            )
        elif target == 'full-environment':
            workspaces = _selected_export_workspaces(workspace_ids)
            manifest = {
                'format': ARCHIVE_FORMAT,
                'version': ARCHIVE_VERSION,
                'kind': 'full-environment',
                'includes_slides_templates': True,
                'includes_generated_outputs': include_generated_outputs,
                'workspaces': [
                    {**_workspace_archive_metadata(workspace), 'archive_path': f'workspaces/{index}'}
                    for index, workspace in enumerate(workspaces, start=1)
                ],
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            archive_configuration(archive, include_templates=False)
            for entry, workspace in zip(manifest['workspaces'], workspaces, strict=True):
                _archive_workspace(
                    archive, workspace, str(entry['archive_path']), destination.parent, progress_callback,
                    include_generated_outputs=include_generated_outputs,
                )
        else:
            raise ValueError('Select a valid export option.')
    return filename


def build_export_archive(target: str) -> tuple[bytes, str]:
    """Compatibility helper for small programmatic exports and tests."""
    with tempfile.TemporaryDirectory(prefix='dashboard-analytic-export-') as temporary_dir:
        destination = Path(temporary_dir) / 'package.zip'
        filename = build_export_archive_file(target, destination)
        return destination.read_bytes(), filename


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _tree_size(source: Path, *, exclude_slides_templates: bool = False) -> int:
    if not source.exists():
        return 0
    total = 0
    for path in source.rglob('*'):
        if not path.is_file() or path.name.endswith(('-wal', '-shm')):
            continue
        relative_path = path.relative_to(source)
        if exclude_slides_templates and relative_path.parts and relative_path.parts[0] == 'slides-templates':
            continue
        total += _file_size(path)
    return total


def estimate_export_bytes(
    target: str, workspace_ids: Iterable[str] | None = None, include_generated_outputs: bool = True,
) -> int:
    """Estimate input bytes so the UI can show meaningful export progress."""
    total = _file_size(application_config_dir / 'application.db')
    if target in {'config', 'config-with-templates', 'full-environment'}:
        for path in application_config_dir.iterdir():
            if path.is_file() and path.name not in {'application.db', workspace_registry.registry_path.name} and not path.name.endswith(('-wal', '-shm')):
                total += _file_size(path)
        if target == 'config-with-templates':
            total += _tree_size(settings.slides_templates_dir)
    elif target == 'slides-templates':
        source_id = next(iter(workspace_ids or ()), active_workspace.id if active_workspace else '')
        source_workspace = workspace_registry.get(source_id) if source_id else None
        total = _tree_size(source_workspace.slides_templates_dir) if source_workspace else 0
    elif target == 'auto-calculated-fields':
        source_workspace_id = next(iter(workspace_ids or ()), active_workspace.id if active_workspace else '')
        source_workspace = workspace_registry.get(source_workspace_id) if source_workspace_id else None
        if source_workspace:
            source_repository = Repository(
                source_workspace.database_path,
                global_db_path=repository.global_db_path,
                workspace_registry_db_path=workspace_registry.registry_path,
            )
            definitions = parse_calculated_dimensions(source_repository.list_calculated_dimensions())
            total = len(json.dumps(calculated_dimensions_json(definitions)).encode('utf-8'))
    elif target.startswith('workspace:'):
        workspace = workspace_registry.get(target.removeprefix('workspace:'))
        if workspace:
            total = _file_size(workspace.database_path) + _tree_size(workspace.input_dir) + _tree_size(workspace.slides_templates_dir)
            if include_generated_outputs:
                total += _tree_size(workspace.output_dir)
    if target == 'full-environment':
        total += sum(
            _file_size(workspace.database_path) + _tree_size(workspace.input_dir) + _tree_size(workspace.slides_templates_dir)
            + (_tree_size(workspace.output_dir) if include_generated_outputs else 0)
            for workspace in _selected_export_workspaces(workspace_ids)
        )
    return max(total, 1)


def _cleanup_expired_export_packages() -> None:
    package_dir = export_package_dir()
    if not package_dir.exists():
        return
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - EXPORT_PACKAGE_TTL.total_seconds()
    offer_cutoff = now - TRANSFER_OFFER_TTL.total_seconds()
    active_paths: set[Path] = set()
    with EXPORT_JOBS_LOCK:
        for job in EXPORT_JOBS.values():
            if job.get('status') in {'queued', 'processing'}:
                active_paths.add(Path(str(job['path'])))
        stale_jobs = [job_id for job_id, job in EXPORT_JOBS.items() if job.get('status') in {'ready', 'failed'} and float(job.get('finished_at', 0)) < cutoff]
        for job_id in stale_jobs:
            EXPORT_JOBS.pop(job_id, None)
    with IMPORT_JOBS_LOCK:
        for job in IMPORT_JOBS.values():
            if job.get('status') in {'queued', 'processing'}:
                active_paths.add(Path(str(job['path'])))
        stale_upload_ids = [
            upload_id for upload_id, upload in IMPORT_UPLOADS.items()
            if float(upload.get('created_at', 0)) < cutoff and not upload.get('claimed')
        ]
        for upload_id in stale_upload_ids:
            IMPORT_UPLOADS.pop(upload_id, None)
        stale_import_jobs = [
            job_id for job_id, job in IMPORT_JOBS.items()
            if job.get('status') in {'ready', 'failed'} and float(job.get('finished_at', 0)) < cutoff
        ]
        for job_id in stale_import_jobs:
            IMPORT_JOBS.pop(job_id, None)
    with TRANSFER_LOCK:
        # Pending offers are persisted across container restarts. Restore them
        # before evaluating expiry so stale approvals cannot evade cleanup and
        # permanently exhaust the per-source admission limit.
        _refresh_persisted_transfer_offers()
        for job in TRANSFER_JOBS.values():
            if job.get('status') not in {'ready', 'failed', 'cancelled'}:
                active_paths.add(Path(str(job['path'])))
        for offer in TRANSFER_OFFERS.values():
            if offer.get('status') in {'receiving', 'received', 'importing', 'recovered'} and offer.get('path'):
                active_paths.add(Path(str(offer['path'])))
            if offer.get('status') == 'pending' and float(offer.get('created_at', 0)) < offer_cutoff:
                offer.update({'status': 'expired', 'phase': 'approval expired', 'error': 'The transfer offer expired before it was accepted.', 'finished_at': now})
                _save_transfer_offer(offer)
        for job_id in [
            job_id for job_id, job in TRANSFER_JOBS.items()
            if job.get('status') in {'ready', 'failed'} and float(job.get('finished_at', 0)) < cutoff
        ]:
            TRANSFER_JOBS.pop(job_id, None)
        for offer_id in [
            offer_id for offer_id, offer in TRANSFER_OFFERS.items()
            if offer.get('status') in {'ready', 'failed', 'rejected', 'expired', 'cancelled'} and float(offer.get('finished_at', 0)) < cutoff
        ]:
            TRANSFER_OFFERS.pop(offer_id, None)
            repository.delete_transfer_offer(offer_id)
            _transfer_offer_state_path(offer_id).unlink(missing_ok=True)
    for path in package_dir.iterdir():
        if path in active_paths or path.stat().st_mtime >= cutoff:
            continue
        if path.is_file():
            path.unlink(missing_ok=True)


def _recovered_transfer_details(manifest: dict[str, Any]) -> tuple[str, list[str]]:
    kind = str(manifest.get('kind') or '')
    if kind == 'config':
        return ('Config + Slides Templates' if manifest.get('includes_slides_templates') else 'Config', [])
    if kind == 'slides-templates':
        source = manifest.get('source_workspace') or {}
        return ('Slides Templates', [str(source['name'])] if isinstance(source, dict) and source.get('name') else [])
    if kind == 'auto-calculated-fields':
        source = manifest.get('source_workspace')
        name = str(source.get('name') or '') if isinstance(source, dict) else ''
        return ('Auto-calculated Fields', [name] if name else [])
    if kind == 'workspace':
        workspace = manifest.get('workspace')
        name = str(workspace.get('name') or '') if isinstance(workspace, dict) else ''
        return ('Workspace', [name] if name else [])
    if kind == 'full-environment':
        entries = manifest.get('workspaces')
        workspaces = [str(entry.get('name') or '') for entry in entries if isinstance(entry, dict) and entry.get('name')] if isinstance(entries, list) else []
        return ('Full Environment', workspaces)
    return (kind.title() or 'Transfer package', [])


def _recover_unimported_transfer_packages() -> None:
    """Restore valid incoming transfer archives left by an interrupted server.

    A partial streamed upload is not a valid ZIP and is safe to remove. A
    complete archive is retained in memory as a deliberate recovery choice for
    a super-admin instead of silently importing it after a restart.
    """
    package_dir = export_package_dir()
    if not package_dir.exists():
        return
    with TRANSFER_LOCK:
        known_paths = {Path(str(offer.get('path'))) for offer in TRANSFER_OFFERS.values() if offer.get('path')}
        active_outgoing_paths = {Path(str(job.get('path'))) for job in TRANSFER_JOBS.values() if job.get('path') and job.get('status') not in {'ready', 'failed'}}
    # Outgoing transfer archives are disposable intermediates. There is no
    # remote receipt state to resume after a restart, so remove every orphan.
    for package_path in package_dir.glob('transfer-*.zip'):
        if package_path not in active_outgoing_paths:
            package_path.unlink(missing_ok=True)
    for package_path in package_dir.glob('incoming-transfer-*.upload'):
        if package_path in known_paths:
            continue
        try:
            manifest = read_import_manifest(package_path)
            kind = str(manifest.get('kind') or '')
            if kind not in {'config', 'workspace', 'full-environment', 'slides-templates', 'auto-calculated-fields'}:
                raise ValueError('Unsupported transfer package.')
        except (OSError, ValueError, zipfile.BadZipFile):
            package_path.unlink(missing_ok=True)
            continue
        created_at = package_path.stat().st_mtime
        offer_id = uuid4().hex
        content, workspaces = _recovered_transfer_details(manifest)
        with TRANSFER_LOCK:
            TRANSFER_OFFERS[offer_id] = {
                'id': offer_id,
                'source': 'Recovered local transfer package',
                'kind': kind,
                'content': content,
                'workspaces': workspaces,
                'status': 'recovered',
                'phase': 'ready to import',
                'progress': 100.0,
                'size': package_path.stat().st_size,
                'path': str(package_path),
                'manifest': manifest,
                'created_at': created_at,
                'recovered': True,
            }
            _save_transfer_offer(TRANSFER_OFFERS[offer_id])


def recovered_transfer_packages() -> list[dict[str, Any]]:
    _recover_unimported_transfer_packages()
    def created_at(offer: dict[str, Any]) -> str:
        try:
            return datetime.fromtimestamp(float(offer.get('created_at') or 0), timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')
        except (TypeError, ValueError, OSError):
            return ''
    with TRANSFER_LOCK:
        return sorted([
            {
                key: offer.get(key)
                for key in ('id', 'source', 'content', 'kind', 'workspaces', 'size')
            } | {'created_at': created_at(offer)}
            for offer in TRANSFER_OFFERS.values()
            if offer.get('status') == 'recovered'
        ], key=lambda offer: offer['created_at'] or '', reverse=True)


def _run_export_job(job_id: str, target: str, workspace_ids: list[str] | None, include_generated_outputs: bool) -> None:
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        if not job:
            return
        job['status'] = 'processing'
    destination = Path(str(job['path']))
    partial_path = destination.with_suffix('.part')
    bytes_total = estimate_export_bytes(target, workspace_ids, include_generated_outputs)
    bytes_done = 0
    with EXPORT_JOBS_LOCK:
        job.update({'bytes_total': bytes_total, 'bytes_done': 0, 'progress': 0})

    def progress_callback(amount: int) -> None:
        nonlocal bytes_done
        bytes_done += max(0, amount)
        with EXPORT_JOBS_LOCK:
            job.update({'bytes_done': bytes_done, 'progress': min(99, round(bytes_done * 100 / bytes_total, 1))})

    try:
        filename = build_export_archive_file(
            target, partial_path, workspace_ids, progress_callback,
            include_generated_outputs=include_generated_outputs,
        )
        partial_path.replace(destination)
        with EXPORT_JOBS_LOCK:
            job.update({'status': 'ready', 'filename': filename, 'size': destination.stat().st_size, 'bytes_done': bytes_total, 'progress': 100, 'finished_at': datetime.now(timezone.utc).timestamp()})
    except Exception as exc:
        partial_path.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        with EXPORT_JOBS_LOCK:
            job.update({'status': 'failed', 'error': str(exc), 'finished_at': datetime.now(timezone.utc).timestamp()})


def start_export_job(
    target: str, workspace_ids: Iterable[str] | None = None, include_generated_outputs: bool = True,
    owner: str = '',
) -> dict[str, Any]:
    """Start a disk-backed ZIP build that continues independently of the page."""
    filename = export_archive_filename(target)
    _cleanup_expired_export_packages()
    package_dir = export_package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    destination = package_dir / f'{job_id}.zip'
    selected_workspace_ids = list(workspace_ids) if workspace_ids is not None else None
    if target in {'auto-calculated-fields', 'slides-templates'}:
        if not active_workspace:
            raise ValueError('Open a workspace before exporting workspace templates or fields.')
        if target == 'auto-calculated-fields':
            load_workspace_calculated_dimensions()
        selected_workspace_ids = [active_workspace.id]
    elif target.startswith('workspace:'):
        selected_workspace_ids = [target.removeprefix('workspace:')]
    if target == 'full-environment':
        _selected_export_workspaces(selected_workspace_ids)
    job = {
        'id': job_id,
        'owner': owner,
        'target': target,
        'status': 'queued',
        'filename': filename,
        'path': str(destination),
        'created_at': datetime.now(timezone.utc).timestamp(),
        'workspace_ids': selected_workspace_ids,
        'include_generated_outputs': include_generated_outputs,
    }
    with EXPORT_JOBS_LOCK:
        EXPORT_JOBS[job_id] = job
    Thread(
        target=_run_export_job, args=(job_id, target, selected_workspace_ids, include_generated_outputs),
        name=f'export-{job_id[:8]}', daemon=True,
    ).start()
    return job


def export_job_payload(job_id: str) -> dict[str, Any] | None:
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        if not job:
            return None
        payload = {key: value for key, value in job.items() if key not in {'path', 'owner'}}
    if payload['status'] == 'ready':
        payload['download_url'] = f'/admin/import-export/export/jobs/{job_id}/download'
    return payload


def _safe_extract_archive(archive: zipfile.ZipFile, destination: Path) -> None:
    for member in archive.infolist():
        candidate = PurePosixPath(member.filename)
        if member.is_dir():
            continue
        if candidate.is_absolute() or '..' in candidate.parts or not candidate.parts:
            raise ValueError('The import archive contains an invalid file path.')
        target = destination.joinpath(*candidate.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open('wb') as output:
            shutil.copyfileobj(source, output, length=16 * 1024 * 1024)


def _safe_extract_archive_prefix(
    archive: zipfile.ZipFile,
    destination: Path,
    prefix: str,
    progress_callback: Callable[[int], None] | None = None,
) -> None:
    normalized_prefix = f'{prefix.rstrip("/")}/'
    members = [member for member in archive.infolist() if member.filename.startswith(normalized_prefix)]
    if not members:
        raise ValueError(f'The import archive does not contain the expected {prefix} payload.')
    for member in members:
        candidate = PurePosixPath(member.filename)
        if member.is_dir():
            continue
        if candidate.is_absolute() or '..' in candidate.parts or not candidate.parts:
            raise ValueError('The import archive contains an invalid file path.')
        target = destination.joinpath(*candidate.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open('wb') as output:
            shutil.copyfileobj(source, output, length=16 * 1024 * 1024)
        if progress_callback:
            progress_callback(member.file_size)


def _unique_import_workspace_name(name: str) -> str:
    base_name = ' '.join(name.split()) or 'Imported Workspace'
    existing = {workspace.name.casefold() for workspace in workspace_registry.list()}
    candidate = base_name
    suffix = 2
    while candidate.casefold() in existing:
        candidate = f'{base_name} - Imported' if suffix == 2 else f'{base_name} - Imported {suffix}'
        suffix += 1
    return candidate


def _replace_workspace_from_staging(existing: Workspace, staging: Workspace) -> Workspace:
    """Commit a validated workspace import while retaining its local identity."""
    existing_root = existing.database_path.parent
    staging_root = staging.database_path.parent
    backup_root = existing_root.with_name(f'.{existing_root.name}-import-backup-{uuid4().hex}')
    staged_database_name = staging.database_path.name
    was_active = bool(active_workspace and active_workspace.id == existing.id)

    if was_active:
        close_active_workspace()

    try:
        # Keep the old workspace recoverable until the replacement is fully in
        # place.  Renaming within the managed volume is effectively instant,
        # even for very large workspace directories.
        if existing_root.exists():
            existing_root.rename(backup_root)
        staging_root.rename(existing_root)

        imported_database = existing_root / staged_database_name
        WorkspaceRegistry._move_database_bundle(imported_database, existing.database_path)
        if existing.database_path.exists():
            with sqlite3.connect(existing.database_path) as connection:
                has_datasets = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'datasets'"
                ).fetchone()
                if has_datasets:
                    connection.execute(
                        'UPDATE datasets SET stored_path = REPLACE(stored_path, ?, ?)',
                        (str(staging.input_dir), str(existing.input_dir)),
                    )
                has_generated_jobs = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'generated_jobs'"
                ).fetchone()
                if has_generated_jobs:
                    connection.execute(
                        'UPDATE generated_jobs SET output_path = REPLACE(output_path, ?, ?)',
                        (str(staging.output_dir), str(existing.output_dir)),
                    )

        # The original registry row and workspace id are deliberately kept so
        # user access grants and references continue to work unchanged.
        workspace_registry.remove(staging.id, delete_files=False)
    except Exception:
        replacement_root = existing_root
        if replacement_root.exists():
            shutil.rmtree(replacement_root, ignore_errors=True)
        if backup_root.exists():
            backup_root.rename(existing_root)
        if was_active:
            activate_workspace(existing.id)
        raise
    else:
        # Delete every file from the previous workspace only after the staged
        # database and directories have been installed successfully.
        shutil.rmtree(backup_root, ignore_errors=True)
        return workspace_registry.get(existing.id) or existing


def import_workspace_archive(payload: Path, workspace_info: dict[str, Any] | None, *, replace_existing: bool = False) -> Workspace:
    database_snapshot = payload / 'database.sqlite'
    if not database_snapshot.exists():
        raise ValueError('The workspace archive does not contain its database.')
    source_name = workspace_info.get('name') if workspace_info else None
    requested_name = str(source_name or 'Imported Workspace')
    existing_workspace = next((workspace for workspace in workspace_registry.list() if workspace.name.casefold() == requested_name.casefold()), None)
    replacing_workspace = existing_workspace if existing_workspace and replace_existing else None
    if replacing_workspace:
        staging_name = _unique_import_workspace_name(f'{requested_name[:70]} - Importing {uuid4().hex[:8]}')
        workspace = workspace_registry.create(staging_name)
    else:
        workspace = workspace_registry.create(requested_name if not existing_workspace else _unique_import_workspace_name(requested_name))
    try:
        for source, destination in (
            (payload / 'input', workspace.input_dir),
            (payload / 'output', workspace.output_dir),
            (payload / 'slides-templates', workspace.slides_templates_dir),
            # Archives created before generated Chart Sets were included used
            # this reports-only directory name.
            (payload / 'exports', workspace.export_dir),
        ):
            if source.exists():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                destination.mkdir(parents=True, exist_ok=True)
        # The database has already been fully materialised in staging. Keep
        # the fast same-filesystem rename path so multi-GB workspaces are not
        # written a second time; fall back to a copy for split Docker volumes.
        try:
            os.replace(database_snapshot, workspace.database_path)
        except OSError as exc:
            if getattr(exc, 'errno', None) != errno.EXDEV:
                raise
            shutil.copy2(database_snapshot, workspace.database_path)
        source_input_dir = workspace_info.get('source_input_dir') if workspace_info else None
        source_output_dir = workspace_info.get('source_output_dir') if workspace_info else None
        with sqlite3.connect(workspace.database_path) as connection:
            connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            if source_input_dir:
                connection.execute(
                    'UPDATE datasets SET stored_path = REPLACE(stored_path, ?, ?)',
                    (str(source_input_dir), str(workspace.input_dir)),
                )
            has_generated_jobs = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'generated_jobs'"
            ).fetchone()
            if source_output_dir and has_generated_jobs:
                connection.execute(
                    'UPDATE generated_jobs SET output_path = REPLACE(output_path, ?, ?)',
                    (str(source_output_dir), str(workspace.output_dir)),
                )
            if has_generated_jobs:
                # Older archives did not always retain source output metadata.
                # Resolve copied report files inside the destination workspace
                # so Reporting can expose their chart thumbnails immediately.
                report_rows = connection.execute(
                    "SELECT id, output_file FROM generated_jobs WHERE job_type = 'report'"
                ).fetchall()
                for report_id, output_file in report_rows:
                    file_name = Path(str(output_file or '')).name
                    target = workspace.export_dir / file_name
                    if file_name and target.is_file():
                        connection.execute(
                            'UPDATE generated_jobs SET output_path = ? WHERE id = ?',
                            (str(target), report_id),
                        )
    except Exception:
        workspace_registry.remove(workspace.id)
        repository.remove_workspace_access(workspace.id)
        raise
    if replacing_workspace:
        try:
            return _replace_workspace_from_staging(replacing_workspace, workspace)
        except Exception:
            if workspace_registry.get(workspace.id):
                workspace_registry.remove(workspace.id)
                repository.remove_workspace_access(workspace.id)
            raise
    return workspace


def register_workspace_template_files(workspace: Workspace) -> None:
    """Register a migrated/imported library without touching another workspace."""
    target_repository = Repository(workspace.database_path, global_db_path=repository.global_db_path)
    target_repository.initialize_template_registry()
    for technology in TEMPLATE_NAMES:
        known = {str(row['name']) for row in target_repository.list_report_templates(technology)}
        default_files = sorted((workspace.slides_templates_dir / 'default' / technology).glob('*.csv'))
        for area in ('library', 'default'):
            for path in sorted((workspace.slides_templates_dir / area / technology).glob('*.csv')):
                name = catalogue_registry_key(path.stem)
                if name not in known:
                    target_repository.add_report_template(technology, name, is_default=False)
                    known.add(name)
        if len(default_files) == 1:
            target_repository.set_default_report_template(technology, catalogue_registry_key(default_files[0].stem))


def migrate_workspace_template_registries() -> None:
    """Finish the one-time migration from the old global Slides Templates registry."""
    migration_key = 'workspace_templates_registry_v2'
    if workspace_registry.get_state(migration_key) == '1':
        return
    for workspace in workspace_registry.list():
        register_workspace_template_files(workspace)
    with repository.global_connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'report_templates'",
        ).fetchone()
        if exists:
            connection.execute('DROP TABLE report_templates')
    workspace_registry.set_state(migration_key, '1')


def matching_template_workspaces(manifest: dict[str, Any], workspaces: Iterable[Workspace]) -> list[str]:
    """Match portable ownership by name, never by a server-local numeric id."""
    source = manifest.get('source_workspace') or {}
    name = str(source.get('name') or '').strip().casefold() if isinstance(source, dict) else ''
    return [workspace.id for workspace in workspaces if name and workspace.name.casefold() == name]


def import_slides_templates_archive(
    staging_root: Path, destination_workspace_ids: Iterable[str] = (),
    manifest: dict[str, Any] | None = None,
) -> int:
    templates_payload = staging_root / 'slides-templates'
    if not templates_payload.exists():
        raise ValueError('The Slides Templates archive does not contain template files.')
    selected = list(dict.fromkeys(destination_workspace_ids))
    if not selected:
        selected = matching_template_workspaces(manifest or {}, workspace_registry.list())
    if not selected:
        raise ValueError('Select at least one destination workspace for the Slides Templates.')
    destinations = [workspace_registry.get(identifier) for identifier in selected]
    if any(workspace is None for workspace in destinations):
        raise ValueError('A destination workspace no longer exists.')
    for workspace in destinations:
        for path in templates_payload.rglob('*'):
            if not path.is_file() or path.suffix.lower() != '.csv':
                continue
            relative = path.relative_to(templates_payload)
            if len(relative.parts) != 3 or relative.parts[0] not in {'library', 'default'} or relative.parts[1] not in TEMPLATE_NAMES:
                raise ValueError('The package contains an invalid Slides Template path.')
            # Keep one default per technology; library copies remain available.
            target = workspace.slides_templates_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative.parts[0] == 'default':
                for previous in target.parent.glob('*.csv'):
                    if previous != target:
                        previous.unlink()
            atomic_write_template(target, path.read_bytes())
        register_workspace_template_files(workspace)
    _clear_chart_preview_caches()
    return len(destinations)


def import_config_archive(staging_root: Path, manifest: dict[str, Any]) -> None:
    config_payload = staging_root / 'config'
    if not config_payload.exists():
        raise ValueError('The configuration archive does not contain configuration files.')
    application_database_payload = config_payload / 'application.db'
    if not application_database_payload.is_file():
        raise ValueError('The configuration archive does not contain application.db.')

    # Users, roles and workspace access must be
    # restored as one exact application database snapshot.  In particular,
    # never infer the target from the active workspace: that can otherwise
    # leave the destination users in place while only ancillary files import.
    application_database = application_config_dir / 'application.db'
    repository.set_global_database(application_database)
    repository.replace_global_database_snapshot(application_database_payload)

    # Apply only the other files included in the package. This preserves
    # unrelated local configuration and makes a config import recoverable
    # file-by-file.
    for path in config_payload.rglob('*'):
        if not path.is_file():
            continue
        relative_path = path.relative_to(config_payload)
        if relative_path in {Path('application.db'), Path(workspace_registry.registry_path.name)}:
            continue
        target = settings.slides_templates_dir / relative_path.relative_to('slides-templates') if relative_path.parts[0] == 'slides-templates' else application_config_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    repository.set_global_database(application_database)
    repository.initialize()


def read_import_manifest(source: bytes | Path) -> dict[str, Any]:
    try:
        archive_source = io.BytesIO(source) if isinstance(source, bytes) else source
        with zipfile.ZipFile(archive_source) as archive:
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError('The selected file is not a valid Dashboard Analytic export package.') from exc
    if not isinstance(manifest, dict) or manifest.get('format') != ARCHIVE_FORMAT or manifest.get('version') != ARCHIVE_VERSION:
        raise ValueError('The selected file is not a compatible Dashboard Analytic export package.')
    return manifest


def import_workspace_collisions(manifest: dict[str, Any]) -> list[str]:
    kind = manifest.get('kind')
    entries = [manifest.get('workspace')] if kind == 'workspace' else manifest.get('workspaces') if kind == 'full-environment' else []
    if not isinstance(entries, list):
        entries = [entries]
    existing_names = {workspace.name.casefold(): workspace.name for workspace in workspace_registry.list()}
    return [existing_names[str(entry.get('name')).casefold()] for entry in entries if isinstance(entry, dict) and str(entry.get('name') or '').casefold() in existing_names]


def import_auto_calculated_fields(
    payload: object,
    destination_workspace_ids: Iterable[str],
    progress_callback: Callable[[str, float], None] | None = None,
) -> tuple[int, int]:
    """Merge fields by normalized name and materialize each selected workspace once."""
    imported = parse_calculated_dimensions(payload)
    available = {workspace.id: workspace for workspace in workspace_registry.list()}
    selected_ids = list(dict.fromkeys(str(workspace_id) for workspace_id in destination_workspace_ids))
    if not selected_ids:
        raise ValueError('Select at least one destination workspace for the auto-calculated fields.')
    if any(workspace_id not in available for workspace_id in selected_ids):
        raise ValueError('One or more selected destination workspaces no longer exist.')
    for index, workspace_id in enumerate(selected_ids):
        workspace = available[workspace_id]
        task_repository = Repository(
            workspace.database_path,
            global_db_path=repository.global_db_path,
            workspace_registry_db_path=workspace_registry.registry_path,
        )
        previous = parse_calculated_dimensions(task_repository.list_calculated_dimensions())
        merged = {_normalise_catalogue_dimension_name(item.name): item for item in previous}
        for item in imported:
            merged[_normalise_catalogue_dimension_name(item.name)] = item
        saved = parse_calculated_dimensions(calculated_dimensions_json(merged.values()))
        affected_sources = affected_calculated_dimension_sources(previous, saved)
        task_repository.replace_calculated_dimensions(calculated_dimensions_json(saved))
        if affected_sources:
            previous_by_key = {_normalise_catalogue_dimension_name(item.name): item for item in previous}
            imported_renames = {
                previous_by_key[_normalise_catalogue_dimension_name(item.name)].name: item.name
                for item in saved
                if _normalise_catalogue_dimension_name(item.name) in previous_by_key
                and previous_by_key[_normalise_catalogue_dimension_name(item.name)].name != item.name
            }
            job = start_auto_calculated_field_job(
                workspace, previous, saved, imported_renames, 'system', background=False,
            )
            if job.get('status') == 'failed':
                raise RuntimeError(str(job.get('error') or 'Auto-calculated field materialization failed.'))
        if progress_callback:
            progress_callback(
                f'updating workspace {index + 1} of {len(selected_ids)}',
                88.0 + ((index + 1) * 12.0 / len(selected_ids)),
            )
    return len(imported), len(selected_ids)


def _apply_import_archive(
    package_path: Path,
    manifest: dict[str, Any],
    progress_callback: Callable[[str, float], None] | None = None,
    destination_workspace_ids: Iterable[str] = (),
) -> str:
    """Apply a disk-backed package and return its user-facing completion message."""
    with zipfile.ZipFile(package_path) as archive, tempfile.TemporaryDirectory(prefix='dashboard-analytic-import-') as temporary_dir:
        staging_root = Path(temporary_dir)
        kind = manifest.get('kind')
        total_extract_bytes = max(sum(member.file_size for member in archive.infolist() if not member.is_dir()), 1)
        extracted_bytes = 0

        def extracted(size: int) -> None:
            nonlocal extracted_bytes
            extracted_bytes += size
            if progress_callback:
                progress_callback('extracting', min(85.0, extracted_bytes * 85.0 / total_extract_bytes))

        if progress_callback:
            progress_callback('validating', 0.0)
        if kind == 'workspace':
            _safe_extract_archive_prefix(archive, staging_root, 'workspace', extracted)
            workspace_info = manifest.get('workspace')
            if progress_callback:
                progress_callback('importing workspace', 90.0)
            workspace = import_workspace_archive(
                staging_root / 'workspace',
                workspace_info if isinstance(workspace_info, dict) else None,
                replace_existing=True,
            )
            if progress_callback:
                progress_callback('finalising', 100.0)
            return f'Workspace "{workspace.name}" imported successfully.'
        if kind == 'config':
            _safe_extract_archive_prefix(archive, staging_root, 'config', extracted)
            if progress_callback:
                progress_callback('importing configuration', 90.0)
            import_config_archive(staging_root, manifest)
            if progress_callback:
                progress_callback('finalising', 100.0)
            return 'Configuration imported successfully. Local workspaces were preserved.'
        if kind == 'slides-templates':
            _safe_extract_archive_prefix(archive, staging_root, 'slides-templates', extracted)
            if progress_callback:
                progress_callback('importing Slides Templates', 90.0)
            import_slides_templates_archive(staging_root, destination_workspace_ids, manifest)
            if progress_callback:
                progress_callback('finalising', 100.0)
            return 'Slides Templates imported successfully.'
        if kind == 'auto-calculated-fields':
            try:
                definitions = json.loads(archive.read('auto-calculated-fields.json').decode('utf-8'))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError('The package does not contain valid auto-calculated fields.') from exc
            imported_count, workspace_count = import_auto_calculated_fields(
                definitions, destination_workspace_ids, progress_callback,
            )
            return f'Imported {imported_count} auto-calculated fields into {workspace_count} workspaces.'
        if kind == 'full-environment':
            _safe_extract_archive_prefix(archive, staging_root, 'config', extracted)
            if progress_callback:
                progress_callback('importing configuration', 87.0)
            import_config_archive(staging_root, manifest)
            entries = manifest.get('workspaces')
            if not isinstance(entries, list):
                raise ValueError('The full-environment package has no workspace list.')
            imported_workspaces: list[Workspace] = []
            workspace_id_map: dict[str, str] = {}
            for entry in entries:
                if not isinstance(entry, dict) or not re.fullmatch(r'workspaces/\d+', str(entry.get('archive_path') or '')):
                    raise ValueError('The full-environment package contains an invalid workspace entry.')
                _safe_extract_archive_prefix(archive, staging_root, str(entry['archive_path']), extracted)
                if progress_callback:
                    progress_callback(f'importing workspace {len(imported_workspaces) + 1} of {len(entries)}', 90.0 + (len(imported_workspaces) * 9.0 / max(len(entries), 1)))
                imported_workspace = import_workspace_archive(staging_root / str(entry['archive_path']), entry, replace_existing=True)
                imported_workspaces.append(imported_workspace)
                source_workspace_id = str(entry.get('id') or '').strip()
                if source_workspace_id:
                    workspace_id_map[source_workspace_id] = imported_workspace.id
                access_usernames = entry.get('access_usernames')
                if isinstance(access_usernames, list):
                    repository.set_workspace_user_access(
                        imported_workspace.id,
                        [str(username) for username in access_usernames],
                    )
                shutil.rmtree(staging_root / str(entry['archive_path']), ignore_errors=True)
            repository.remap_workspace_access(workspace_id_map)
            if progress_callback:
                progress_callback('finalising', 100.0)
            return f'Full environment imported successfully ({len(imported_workspaces)} workspaces added).'
        raise ValueError('The export package type is not supported.')


def _run_import_job(job_id: str) -> None:
    with IMPORT_JOBS_LOCK:
        job = IMPORT_JOBS.get(job_id)
        if not job:
            return
        job['status'] = 'processing'
        package_path = Path(str(job['path']))
        manifest = dict(job['manifest'])

    def update_progress(phase: str, progress: float) -> None:
        with IMPORT_JOBS_LOCK:
            current = IMPORT_JOBS.get(job_id)
            if current:
                current.update({'phase': phase, 'progress': round(min(100.0, max(0.0, progress)), 1)})

    try:
        notice = _apply_import_archive(
            package_path, manifest, update_progress,
            destination_workspace_ids=job.get('destination_workspace_ids') or (),
        )
        with IMPORT_JOBS_LOCK:
            job.update({'status': 'ready', 'notice': notice, 'finished_at': datetime.now(timezone.utc).timestamp()})
    except Exception as exc:
        with IMPORT_JOBS_LOCK:
            job.update({'status': 'failed', 'error': str(exc), 'finished_at': datetime.now(timezone.utc).timestamp()})
    finally:
        package_path.unlink(missing_ok=True)
        with IMPORT_JOBS_LOCK:
            IMPORT_UPLOADS.pop(str(job.get('upload_id')), None)


def start_import_job(
    upload_id: str, user: SessionUser, destination_workspace_ids: Iterable[str] = (),
) -> dict[str, Any]:
    with IMPORT_JOBS_LOCK:
        upload = IMPORT_UPLOADS.get(upload_id)
        if not upload or upload.get('owner') != user.username:
            raise ValueError('The uploaded package is no longer available. Select it again.')
        if upload.get('claimed'):
            raise ValueError('This uploaded package is already being imported.')
        upload['claimed'] = True
        job_id = uuid4().hex
        job = {
            'id': job_id,
            'upload_id': upload_id,
            'owner': user.username,
            'path': upload['path'],
            'manifest': upload['manifest'],
            'status': 'queued',
            'destination_workspace_ids': list(destination_workspace_ids),
            'created_at': datetime.now(timezone.utc).timestamp(),
        }
        IMPORT_JOBS[job_id] = job
    Thread(target=_run_import_job, args=(job_id,), name=f'import-{job_id[:8]}', daemon=True).start()
    return job


def import_job_payload(job_id: str, user: SessionUser) -> dict[str, Any] | None:
    with IMPORT_JOBS_LOCK:
        job = IMPORT_JOBS.get(job_id)
        if not job or job.get('owner') != user.username:
            return None
        return {key: value for key, value in job.items() if key not in {'path', 'manifest', 'owner', 'upload_id'}}


def normalize_transfer_destination(destination_url: str, destination_port: int | None) -> str:
    raw_url = destination_url.strip()
    if not raw_url:
        raise ValueError('Enter the destination server URL or IP address.')
    has_explicit_scheme = '://' in raw_url
    if not has_explicit_scheme:
        raw_url = f'http://{raw_url}'
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter a valid HTTP or HTTPS destination server URL.')
    if parsed.query or parsed.fragment:
        raise ValueError('The destination URL cannot include query parameters or a fragment.')
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError('Enter a valid destination server port.') from exc
    # An explicit URL port is authoritative. The dialog's prefilled 7278 is a
    # fallback for bare hostnames and must not silently replace :443, a Docker
    # published host port, or any other port already entered in the URL.
    if parsed_port:
        port = parsed_port
    elif has_explicit_scheme and destination_port == DEFAULT_TRANSFER_PORT:
        # Port 7278 is the convenient default for a bare host/IP. A complete
        # URL with that untouched form default should retain the standard
        # HTTP/HTTPS port; :7278 can still be stated explicitly in the URL.
        port = None
    else:
        port = destination_port or DEFAULT_TRANSFER_PORT
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValueError('The destination port must be between 1 and 65535.')
    hostname = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
    netloc = f'{hostname}:{int(port)}' if port else hostname
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip('/'), '', ''))


def _transfer_api_url(base_url: str, path: str) -> str:
    return f'{base_url.rstrip("/")}/{path.lstrip("/")}'


def _transfer_workspace_names(workspace_ids: list[str] | None) -> list[str]:
    if workspace_ids is None:
        return []
    available = {workspace.id: workspace.name for workspace in workspace_registry.list()}
    return [available[workspace_id] for workspace_id in workspace_ids if workspace_id in available]


def _transfer_offer_workspace_names(target: str, workspace_ids: list[str] | None) -> list[str]:
    if target in {'auto-calculated-fields', 'slides-templates'}:
        return _transfer_workspace_names(workspace_ids)
    if target.startswith('workspace:'):
        workspace = workspace_registry.get(target.removeprefix('workspace:'))
        return [workspace.name] if workspace else []
    return _transfer_workspace_names(workspace_ids)


def _transfer_content_label(target: str) -> str:
    labels = {
        'config': 'Config',
        'slides-templates': 'Slides Templates',
        'config-with-templates': 'Config + Slides Templates',
        'full-environment': 'Full Environment',
        'auto-calculated-fields': 'Auto-calculated Fields',
    }
    if target.startswith('workspace:'):
        workspace = workspace_registry.get(target.removeprefix('workspace:'))
        return f'Workspace: {workspace.name}' if workspace else 'Workspace'
    return labels.get(target, target)


def _transfer_offer_secret_matches(offer: dict[str, Any], secret: str) -> bool:
    supplied = hashlib.sha256(secret.encode('utf-8')).hexdigest()
    return secrets.compare_digest(str(offer.get('secret_hash') or ''), supplied)


def _transfer_offer_state_path(offer_id: str) -> Path:
    return export_package_dir() / f'transfer-offer-{offer_id}.json'


def _persist_transfer_offer(offer: dict[str, Any]) -> None:
    """Persist handshake state in the global DB shared by all workers."""
    repository.save_transfer_offer(offer)


def _refresh_persisted_transfer_offers() -> None:
    # One-time migration from the former package-directory JSON storage.
    directory = export_package_dir()
    if directory.is_dir():
        for path in directory.glob('transfer-offer-*.json'):
            try:
                offer = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(offer, dict) or not offer.get('id'):
                    continue
                repository.save_transfer_offer(offer)
                path.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError, sqlite3.Error):
                continue
    persisted = {str(offer['id']): offer for offer in repository.list_transfer_offers()}
    TRANSFER_OFFERS.clear()
    TRANSFER_OFFERS.update(persisted)


def _save_transfer_offer(offer: dict[str, Any]) -> None:
    offer['updated_at'] = datetime.now(timezone.utc).timestamp()
    _persist_transfer_offer(offer)


def _run_received_transfer(offer_id: str) -> None:
    with TRANSFER_LOCK:
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer:
            return
        package_path = Path(str(offer['path']))
        manifest = dict(offer['manifest'])
        offer.update({'status': 'importing', 'phase': 'validating', 'progress': 0.0})
        _save_transfer_offer(offer)

    def update_progress(phase: str, progress: float) -> None:
        with TRANSFER_LOCK:
            current_offer = TRANSFER_OFFERS.get(offer_id)
            if current_offer:
                current_offer.update({'phase': phase, 'progress': round(min(100.0, max(0.0, progress)), 1)})
    try:
        notice = _apply_import_archive(
            package_path, manifest, update_progress,
            offer.get('destination_workspace_ids') or (),
        )
        with TRANSFER_LOCK:
            offer.update({'status': 'ready', 'phase': 'complete', 'progress': 100.0, 'notice': notice, 'finished_at': datetime.now(timezone.utc).timestamp()})
            _save_transfer_offer(offer)
    except Exception as exc:
        with TRANSFER_LOCK:
            offer.update({'status': 'failed', 'error': str(exc), 'finished_at': datetime.now(timezone.utc).timestamp()})
            _save_transfer_offer(offer)
    finally:
        package_path.unlink(missing_ok=True)


def _run_transfer_job(job_id: str) -> None:
    with TRANSFER_LOCK:
        job = TRANSFER_JOBS.get(job_id)
        if not job:
            return
        job['status'] = 'connecting'
        destination = str(job['destination'])
        target = str(job['target'])
        workspace_ids = job.get('workspace_ids')
        include_generated_outputs = bool(job.get('include_generated_outputs', True))
        package_path = Path(str(job['path']))
    offer_secret = secrets.token_urlsafe(32)
    offer_id = ''
    headers = {'X-Dashboard-Transfer-Secret': offer_secret, 'Accept': 'application/json'}
    def cancellation_requested() -> bool:
        with TRANSFER_LOCK:
            return bool(job.get('cancel_requested'))

    def stop_if_cancelled() -> None:
        if cancellation_requested():
            raise InterruptedError('The server transfer was cancelled.')

    try:
        with httpx.Client(timeout=httpx.Timeout(65.0, connect=5.0), follow_redirects=False) as client:
            offer_payload = {
                'source': __app_name__,
                'archive_version': ARCHIVE_VERSION,
                'kind': 'full-environment' if target == 'full-environment' else 'workspace' if target.startswith('workspace:') else 'config' if target in {'config', 'config-with-templates'} else target,
                'content': _transfer_content_label(target),
                'workspaces': _transfer_offer_workspace_names(target, workspace_ids),
            }
            # Retry a transient first connection (for example while a remote
            # container wakes up). The offer endpoint is idempotent for this
            # transfer secret, so a lost response cannot duplicate the offer.
            for attempt in range(3):
                try:
                    response = client.post(
                        _transfer_api_url(destination, '/api/import-export/transfers/offers'),
                        headers=headers,
                        json=offer_payload,
                    )
                    if getattr(response, 'status_code', 200) >= 500:
                        response.raise_for_status()
                    break
                except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError):
                    stop_if_cancelled()
                    if attempt == 2:
                        raise
                    with TRANSFER_LOCK:
                        job['phase'] = f'retrying destination connection ({attempt + 2}/3)'
                    sleep(1 << attempt)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    detail = str(response.json().get('detail') or '').strip()
                except (AttributeError, TypeError, ValueError):
                    detail = ''
                raise ValueError(detail or f'The destination server rejected the transfer request (HTTP {response.status_code}).') from exc
            offer_id = str(response.json().get('offer_id') or '')
            if not offer_id:
                raise ValueError('The destination server did not create a transfer offer.')
            if cancellation_requested():
                client.delete(_transfer_api_url(destination, f'/api/import-export/transfers/offers/{offer_id}'), headers=headers)
                stop_if_cancelled()
            with TRANSFER_LOCK:
                job.update({'status': 'awaiting_acceptance', 'remote_offer_id': offer_id})

            acceptance_deadline = monotonic() + 3600
            while monotonic() < acceptance_deadline:
                if cancellation_requested():
                    client.delete(_transfer_api_url(destination, f'/api/import-export/transfers/offers/{offer_id}'), headers=headers)
                    stop_if_cancelled()
                response = client.get(
                    _transfer_api_url(destination, f'/api/import-export/transfers/offers/{offer_id}'),
                    headers=headers,
                )
                response.raise_for_status()
                remote_status = str(response.json().get('status') or '')
                if remote_status == 'accepted':
                    break
                if remote_status in {'rejected', 'failed', 'expired', 'cancelled'}:
                    raise ValueError(response.json().get('error') or 'The destination server rejected the transfer.')
                sleep(2)
            else:
                raise TimeoutError('The destination server did not accept the transfer within one hour.')

            with TRANSFER_LOCK:
                job.update({
                    'status': 'exporting',
                    'export_total': estimate_export_bytes(target, workspace_ids, include_generated_outputs),
                    'exported_bytes': 0,
                    'progress': 0.0,
                })
            stop_if_cancelled()

            def update_export_progress(written: int) -> None:
                stop_if_cancelled()
                with TRANSFER_LOCK:
                    job['exported_bytes'] = int(job.get('exported_bytes') or 0) + written
                    total = max(int(job.get('export_total') or 1), 1)
                    job['progress'] = round(min(100.0, job['exported_bytes'] * 100.0 / total), 1)

            filename = build_export_archive_file(
                target, package_path, workspace_ids, update_export_progress,
                include_generated_outputs=include_generated_outputs,
            )
            package_size = package_path.stat().st_size
            with TRANSFER_LOCK:
                job.update({'status': 'transferring', 'filename': filename, 'size': package_size, 'bytes_sent': 0, 'progress': 0.0})

            def package_chunks() -> Iterable[bytes]:
                sent = 0
                with package_path.open('rb') as package_file:
                    while chunk := package_file.read(4 * 1024 * 1024):
                        stop_if_cancelled()
                        sent += len(chunk)
                        with TRANSFER_LOCK:
                            job['bytes_sent'] = sent
                            job['progress'] = round(sent * 100.0 / max(package_size, 1), 1)
                        yield chunk

            for attempt in range(3):
                try:
                    response = client.put(
                        _transfer_api_url(destination, f'/api/import-export/transfers/offers/{offer_id}/package'),
                        headers={**headers, 'Content-Type': 'application/zip', 'Content-Length': str(package_size), 'X-Export-Filename': filename},
                        content=package_chunks(),
                        timeout=httpx.Timeout(30.0, read=3600.0, write=3600.0),
                    )
                    if getattr(response, 'status_code', 200) >= 500:
                        response.raise_for_status()
                    break
                except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError):
                    if attempt == 2:
                        raise
                    with TRANSFER_LOCK:
                        job.update({'status': 'transferring', 'phase': f'retrying transmission ({attempt + 2}/3)', 'bytes_sent': 0, 'progress': 0.0})
                    sleep(2 ** attempt)
            response.raise_for_status()
            with TRANSFER_LOCK:
                job['status'] = 'remote_importing'
                job['bytes_sent'] = package_size
                job['progress'] = 0.0

            import_deadline = monotonic() + 86400
            while monotonic() < import_deadline:
                response = client.get(
                    _transfer_api_url(destination, f'/api/import-export/transfers/offers/{offer_id}'),
                    headers=headers,
                )
                response.raise_for_status()
                remote_payload = response.json()
                remote_status = str(remote_payload.get('status') or '')
                with TRANSFER_LOCK:
                    job.update({'remote_phase': remote_payload.get('phase') or '', 'progress': float(remote_payload.get('progress') or 0)})
                if remote_status == 'ready':
                    with TRANSFER_LOCK:
                        job.update({'status': 'ready', 'progress': 100.0, 'notice': remote_payload.get('notice') or 'Transfer imported successfully.', 'finished_at': datetime.now(timezone.utc).timestamp()})
                    return
                if remote_status in {'rejected', 'failed', 'expired', 'cancelled'}:
                    raise ValueError(remote_payload.get('error') or 'The destination server could not import the package.')
                sleep(2)
            raise TimeoutError('The destination server did not finish importing the package within 24 hours.')
    except InterruptedError as exc:
        if offer_id:
            try:
                httpx.delete(
                    _transfer_api_url(destination, f'/api/import-export/transfers/offers/{offer_id}'),
                    headers=headers,
                    timeout=5.0,
                )
            except (httpx.HTTPError, OSError):
                pass
        with TRANSFER_LOCK:
            job.update({'status': 'cancelled', 'error': str(exc), 'finished_at': datetime.now(timezone.utc).timestamp()})
    except Exception as exc:
        # Do not strand an accepted or pending destination offer when the
        # source has definitively abandoned the job. The remote DELETE is
        # idempotent and deliberately leaves an already completed offer alone.
        if offer_id:
            try:
                httpx.delete(
                    _transfer_api_url(destination, f'/api/import-export/transfers/offers/{offer_id}'),
                    headers=headers,
                    timeout=5.0,
                )
            except (httpx.HTTPError, OSError):
                pass
        if isinstance(exc, httpx.ConnectError):
            error = f'Could not connect to {destination}. The host was resolved, but no server accepted the connection at that address and port.'
        else:
            error = str(exc)
        with TRANSFER_LOCK:
            job.update({'status': 'failed', 'error': error, 'finished_at': datetime.now(timezone.utc).timestamp()})
    finally:
        package_path.unlink(missing_ok=True)


def start_transfer_job(
    destination_url: str, destination_port: int | None, target: str, workspace_ids: Iterable[str] | None,
    user: SessionUser, include_generated_outputs: bool = True,
) -> dict[str, Any]:
    require_export_permission(user, target)
    destination = normalize_transfer_destination(destination_url, destination_port)
    _cleanup_expired_export_packages()
    selected_workspace_ids = list(workspace_ids) if workspace_ids is not None else None
    if target in {'auto-calculated-fields', 'slides-templates'}:
        if not active_workspace:
            raise ValueError('Open a workspace before transferring workspace templates or fields.')
        if target == 'auto-calculated-fields':
            load_workspace_calculated_dimensions()
        selected_workspace_ids = [active_workspace.id]
    elif target.startswith('workspace:'):
        selected_workspace_ids = [target.removeprefix('workspace:')]
    if target == 'full-environment':
        _selected_export_workspaces(selected_workspace_ids)
    else:
        export_archive_filename(target)
    package_dir = export_package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    job = {
        'id': job_id,
        'owner': user.username,
        'destination': destination,
        'target': target,
        'workspace_ids': selected_workspace_ids,
        'include_generated_outputs': include_generated_outputs,
        'path': str(package_dir / f'transfer-{job_id}.zip'),
        'status': 'queued',
        'created_at': datetime.now(timezone.utc).timestamp(),
    }
    with TRANSFER_LOCK:
        TRANSFER_JOBS[job_id] = job
    Thread(target=_run_transfer_job, args=(job_id,), name=f'transfer-{job_id[:8]}', daemon=True).start()
    return job


def transfer_job_payload(job_id: str, user: SessionUser) -> dict[str, Any] | None:
    with TRANSFER_LOCK:
        job = TRANSFER_JOBS.get(job_id)
        if not job or job.get('owner') != user.username:
            return None
        payload = {key: value for key, value in job.items() if key not in {'owner', 'path'}}
    payload['progress'] = round(float(payload.get('progress') or 0), 1)
    return payload


def require_import_export_permission(user: SessionUser, target: str) -> None:
    """Authorize imports; admins may restore templates and fields into accessible workspaces."""
    if user.role == 'super-admin' or target in {'slides-templates', 'auto-calculated-fields'}:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail='Only super-admins can import or export configuration and workspaces.',
    )


def require_export_permission(user: SessionUser, target: str) -> None:
    """Authorize exports and transfers without exposing other workspaces."""
    if user.role == 'super-admin':
        return
    if target in {'auto-calculated-fields', 'slides-templates'}:
        if active_workspace and repository.user_has_workspace_access(user.username, active_workspace.id):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Open a workspace you can access first.')
    if target.startswith('workspace:'):
        workspace_id = target.removeprefix('workspace:')
        if workspace_registry.get(workspace_id) and repository.user_has_workspace_access(user.username, workspace_id):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have access to that workspace.')
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail='Only super-admins can export or transfer application configuration and full environments.',
    )


def would_remove_last_active_admin(target_user, normalized_role: str, will_be_active: bool) -> bool:
    if target_user['role'] not in {'admin', 'super-admin'} or not target_user['active']:
        return False
    if normalized_role in {'admin', 'super-admin'} and will_be_active:
        return False
    return repository.count_active_admin_users() <= 1


def would_remove_required_super_admin(target_user, normalized_role: str, will_be_active: bool) -> bool:
    """Keep one super-admin record and one active super-admin available."""
    if target_user['role'] != 'super-admin':
        return False
    removing_super_role = normalized_role != 'super-admin'
    removing_active_super_admin = bool(target_user['active']) and (removing_super_role or not will_be_active)
    if removing_super_role and repository.count_super_admin_users() <= 1:
        return True
    return removing_active_super_admin and repository.count_super_admin_users(active_only=True) <= 1


def render_admin_template(request: Request, user: SessionUser, error: str | None = None, status_code: int = 200) -> HTMLResponse:
    embedded_template_editor = request.query_params.get('embedded_template_editor') == '1'
    selected_technology = request.query_params.get('catalogue_technology') or None
    selected_catalogue = request.query_params.get('catalogue_id') or None
    if embedded_template_editor and selected_catalogue and not selected_technology:
        selected_technology = next((
            technology for technology in TEMPLATE_NAMES
            if any(item['identifier'] == selected_catalogue for item in report_catalogue_options(technology))
        ), None)
    selection = request.query_params.get('catalogue_selection') or ''
    if selection and ':' in selection:
        candidate_technology, candidate_catalogue = selection.split(':', 1)
        if candidate_technology in TEMPLATE_NAMES and candidate_catalogue:
            selected_technology, selected_catalogue = candidate_technology, candidate_catalogue
    report_catalogs: dict[str, dict[str, Any]] = {}
    if active_workspace:
        for technology in TEMPLATE_NAMES:
            catalogues = report_catalogue_options(technology)
            active_catalogue = next((catalogue for catalogue in catalogues if catalogue['active']), None)
            report_catalogs[technology] = {
                'path': active_catalogue['path'] if active_catalogue else None,
                'source': 'Active template' if active_catalogue else 'No default template configured',
                'catalogues': catalogues,
            }
    workspace_catalogues = [
        {
            **catalogue,
            'technology': technology,
            'created_at': format_local_timestamp(catalogue.get('created_at')),
            'updated_at': format_local_timestamp(catalogue.get('updated_at')),
        }
        for technology, payload in report_catalogs.items()
        for catalogue in payload['catalogues']
    ]
    template_names_by_technology = {
        technology: [str(catalogue['name']) for catalogue in payload['catalogues']]
        for technology, payload in report_catalogs.items()
    }
    admin_datasets = [serialize_dataset_row(dataset) for dataset in repository.list_datasets()] if active_workspace else []
    add_workspace_vendor_capabilities(admin_datasets)
    ready_admin_datasets = [dataset for dataset in admin_datasets if dataset['is_ready']]
    dataset_names = {
        int(dataset['id']): str(dataset['file_name'])
        for dataset in admin_datasets
    }
    database_table_groups: dict[str, list[dict[str, str]]] = {
        'Config Tables': [], 'Workspace Tables': [], 'Individual dataset rows': [], 'Combined CDR rows': [],
    }
    friendly_tables = {
        WORKSPACE_REGISTRY_TABLE: 'Workspace registry',
        'application_state': 'Application state',
        'audit_logs': 'Audit log',
        'dataset_profiles': 'Dataset profiles',
        'datasets': 'Datasets',
        'generated_jobs': 'Generated jobs',
        'report_templates': 'Slides Templates registry',
        'transfer_offers': 'Server transfer offers',
        'users': 'Users',
    }
    global_database_tables = (set(repository.list_global_database_tables()) - {'report_templates'}) if active_workspace else set()
    for table_name in repository.list_database_tables() if active_workspace else []:
        dataset_match = re.fullmatch(r'dataset_rows_(\d+)', table_name)
        reporting_match = re.fullmatch(r'reporting_rows_(data|voice|speech)', table_name)
        if dataset_match:
            dataset_id = int(dataset_match.group(1))
            if dataset_name := dataset_names.get(dataset_id):
                database_table_groups['Individual dataset rows'].append({'name': table_name, 'label': dataset_name})
        elif reporting_match:
            database_table_groups['Combined CDR rows'].append({
                'name': table_name,
                'label': f"Combined CDR-{reporting_match.group(1).title()}",
            })
        elif table_name in global_database_tables or table_name == WORKSPACE_REGISTRY_TABLE:
            database_table_groups['Config Tables'].append({'name': table_name, 'label': friendly_tables.get(table_name, table_name)})
        else:
            database_table_groups['Workspace Tables'].append({
                'name': table_name,
                'label': friendly_tables.get(table_name, table_name),
            })
    export_options = [
        {'value': 'config', 'label': 'Config'},
        {'value': 'slides-templates', 'label': 'Slides Templates', 'disabled': not active_workspace},
        {'value': 'auto-calculated-fields', 'label': 'Auto-calculated Fields', 'disabled': not active_workspace},
        {'value': 'full-environment', 'label': 'Full Environment (Config + Slides Templates + Selected Workspaces)'},
        *[
            {'value': f'workspace:{workspace.id}', 'label': f'Workspace: {workspace.name}'}
            for workspace in accessible_workspaces(user)
        ],
    ]
    if user.role != 'super-admin':
        # Do not leave a forbidden disabled option selected by default. A
        # disabled selected option is omitted from FormData by browsers, so an
        # admin's first export/transfer request had no export_target at all.
        export_options = [
            option for option in export_options
            if option['value'] in {'slides-templates', 'auto-calculated-fields'} or option['value'].startswith('workspace:')
        ]
    admin_users = [
        {**dict(row), 'created_at': format_local_timestamp(row['created_at']), 'workspace_ids': repository.list_user_workspace_ids(int(row['id']))}
        for row in repository.list_users()
    ]
    return render_template(
        request,
        'admin.html',
        {
            'user': user,
            'embedded_template_editor': embedded_template_editor,
            'users': admin_users,
            'workspaces': workspace_registry.list(),
            'datasets': admin_datasets,
            'vodafone_mapping_datasets': [dataset for dataset in ready_admin_datasets if dataset.get('dataset_kind') == 'mapping_vodafone'],
            'three_mapping_datasets': [dataset for dataset in ready_admin_datasets if dataset.get('dataset_kind') == 'mapping_three'],
            'report_catalogs': report_catalogs,
            'template_names_by_technology': template_names_by_technology,
            'workspace_catalogues': workspace_catalogues,
            'database_table_groups': database_table_groups,
            'database_notice': request.query_params.get('database_notice') or None,
            'catalogue_editor': catalogue_editor_payload(selected_technology, selected_catalogue) if active_workspace else None,
            'catalogue_notice': request.query_params.get('catalogue_notice') or None,
            'catalogue_error': request.query_params.get('catalogue_error') or None,
            'export_options': export_options,
            'recovered_transfer_packages': recovered_transfer_packages() if user.role == 'super-admin' else [],
            'import_export_notice': request.query_params.get('import_export_notice') or None,
            'import_export_error': request.query_params.get('import_export_error') or None,
            'error': error,
        },
        status_code=status_code,
    )


def describe_workspace_log_entry(log: dict[str, Any]) -> str:
    details = log.get('details')
    if isinstance(details, dict):
        if log['action'] == 'process_dataset_failed':
            return f"Dataset {details.get('dataset_id')}: {details.get('error', 'Processing failed')}"
        if log['action'] == 'analyze_dataset_failed':
            return f"Analysis failed for dataset {details.get('dataset_id')}: {details.get('error', 'Unknown analysis error')}"
        if log['action'] == 'analyze_dataset_warning':
            return f"Analysis warning for dataset {details.get('dataset_id')}: {details.get('warning', 'Warning emitted during analysis')}"
        if log['action'] == 'process_dataset':
            return f"Dataset {details.get('dataset_id')} processed successfully."
        if log['action'] == 'retry_dataset':
            return f"Retry requested for dataset {details.get('dataset_id')}."
        if log['action'] == 'map_dataset_vendors':
            return f"Vendor mapping applied to CDR dataset {details.get('dataset_id')}."
        if log['action'] == 'map_dataset_vendors_failed':
            return f"Vendor mapping failed for CDR dataset {details.get('dataset_id')}: {details.get('error', 'Unknown error')}"
        if log['action'] == 'vendor_mapping_skipped':
            return f"Vendor mapping was skipped for CDR dataset {details.get('dataset_id')}: {details.get('error', 'Unknown error')}"
        if log['action'] == 'clear_dataset_vendors':
            return f"Vendor mapping cleared from CDR dataset {details.get('dataset_id')}."
        if log['action'] == 'clear_dataset_vendors_failed':
            return f"Vendor clearing failed for CDR dataset {details.get('dataset_id')}: {details.get('error', 'Unknown error')}"
        if log['action'] in {'stop_dataset', 'stop_dataset_requested'}:
            return f"Stop requested for dataset {details.get('dataset_id')}."
        if log['action'] == 'delete_dataset':
            return f"Dataset {details.get('dataset_id')} deleted."
        if log['action'] == 'rename_dataset':
            return f"Dataset {details.get('dataset_id')} renamed to {details.get('file', 'the new file name')}."
        if log['action'] == 'analyze_dataset':
            return f"Analysis requested for dataset {details.get('dataset_id')}."
        if log['action'] == 'export_netcheck_cdr_report_failed':
            return f"Report job {details.get('report_id')} failed: {details.get('error', 'Unknown generation error')}"
        if log['action'] == 'chart_set_generation_failed':
            return f"Chart Set job {details.get('job_id')} failed: {details.get('error', 'Unknown generation error')}"
        if log['action'] == 'recover_interrupted_background_jobs':
            reports = details.get('reports') or []
            chart_jobs = details.get('chart_jobs') or []
            if reports or chart_jobs:
                return f"Application restart interrupted report jobs {reports} and Chart Set jobs {chart_jobs}."
    return str(log.get('details_text') or log.get('details') or '')


def classify_workspace_log_entry(log: dict[str, Any]) -> str:
    if log.get('action') == 'login' and isinstance(log.get('details'), dict) and not log['details'].get('success', False):
        return 'Error'
    if str(log.get('action') or '').endswith('_failed') or log.get('action') in {
        'process_dataset_failed', 'analyze_dataset_failed', 'analyze_dataset_warning',
        'map_dataset_vendors_failed', 'clear_dataset_vendors_failed',
    }:
        return 'Error'
    if log.get('action') == 'recover_interrupted_background_jobs' and isinstance(log.get('details'), dict):
        if log['details'].get('reports') or log['details'].get('chart_jobs'):
            return 'Error'
    return 'Info'


def build_app_logs() -> list[dict[str, Any]]:
    """Format the complete audit trail for the App Logs view."""
    if not active_workspace:
        return []
    logs: list[dict[str, Any]] = []
    for row in repository.list_logs():
        details_text = str(row['details'] or '')
        action = str(row['action'] or '').replace('_report_catalogue', '_report_template')
        details_text = re.sub(r'"catalogue_name"\s*:', '"template_name":', details_text)
        details_text = re.sub(r'"catalogue"\s*:', '"template":', details_text)
        try:
            details: Any = json.loads(details_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            details = details_text
        stored_username = str(row['username'] or '').strip().casefold()
        legacy_requested_by = (
            str(details.get('requested_by') or '').strip().casefold()
            if isinstance(details, dict) and details.get('requested_by') else ''
        )
        executed_by = (
            str(details.get('executed_by') or details.get('actioned_by') or '').strip().casefold()
            if isinstance(details, dict) and (details.get('executed_by') or details.get('actioned_by')) else ''
        )
        # Briefly published Chart Set events used `system` as User and placed
        # the originator in requested_by. Present them with the corrected
        # semantics without rewriting immutable audit history.
        display_username = legacy_requested_by if stored_username == 'system' and legacy_requested_by and not executed_by else stored_username
        if stored_username == 'system' and legacy_requested_by and not executed_by:
            executed_by = 'system'
        log = {
            'id': row['id'],
            'username': display_username,
            'executed_by': executed_by or '—',
            'action': action,
            'details': details,
            'details_text': details_text,
            'created_at': format_local_timestamp(row['created_at']),
            'date': str(row['created_at'] or '')[:10],
        }
        log['summary'] = describe_workspace_log_entry(log)
        log['log_type'] = classify_workspace_log_entry(log)
        logs.append(log)
    return logs


def build_dashboard_payload(selected_dataset: dict[str, Any] | None, request: Request, username: str | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str], dict[str, Any], str | None, bool]:
    if not selected_dataset:
        return None, [], [], {}, None, False
    if not selected_dataset['is_ready']:
        return None, [], [], {}, selected_dataset.get('last_error') if selected_dataset.get('status') == 'failed' else None, False

    filter_options = selected_dataset.get('filter_options') or {}
    filter_options = {'input_kind': [selected_dataset.get('dataset_kind') or 'generic'], **filter_options}
    if not should_load_analysis(request):
        return None, [], [], filter_options, None, False

    dataset_path = Path(selected_dataset['stored_path'])
    aggregation = request.query_params.get('aggregation') or selected_dataset.get('default_aggregation') or 'all'
    requested_metrics = [value for value in request.query_params.getlist('metric') if value]
    if not requested_metrics:
        fallback_metric = request.query_params.get('metric') or selected_dataset.get('default_metric') or ''
        if fallback_metric:
            requested_metrics = [fallback_metric]
    available_metrics = selected_dataset.get('available_metrics') or []
    selectable_metrics = selected_dataset.get('selectable_metrics') or available_metrics
    selected_metrics = [metric for metric in requested_metrics if metric in selectable_metrics]
    if not selected_metrics:
        default_metric = selected_dataset.get('default_metric') or (selectable_metrics[0] if selectable_metrics else '')
        selected_metrics = [default_metric] if default_metric else []
    aggregation_overrides = parse_aggregation_overrides(request.query_params.get('aggregation_overrides') or '')
    cdf_overrides = parse_cdf_overrides(request.query_params.get('cdf_overrides') or '')
    cdf_grouping = request.query_params.get('cdf_grouping') or 'all'
    filters = {
        'market': choose_filter_values(request.query_params.getlist('market'), filter_options, 'market'),
        'period': choose_filter_values(request.query_params.getlist('period'), filter_options, 'period'),
        'date_from': request.query_params.get('date_from') or None,
        'date_to': request.query_params.get('date_to') or None,
        'aggregation': aggregation,
        'cdf_grouping': cdf_grouping,
        'extra_filters': {},
        'explicit_empty_filters': set(),
    }
    explicit_empty_filters = set(value for value in request.query_params.getlist('__empty_filter') if value)
    filters['explicit_empty_filters'] = explicit_empty_filters
    for dimension in FILTER_DIMENSIONS:
        if dimension in {'market', 'period'}:
            if dimension in explicit_empty_filters:
                filters[dimension] = ['__none__']
            continue
        selected_values = choose_filter_values(request.query_params.getlist(dimension), filter_options, dimension)
        if dimension in explicit_empty_filters:
            filters['extra_filters'][dimension] = ['__none__']
        elif selected_values:
            filters['extra_filters'][dimension] = selected_values

    query_columns = build_analysis_query_columns(selected_dataset, selected_metrics, filters, aggregation_overrides, cdf_overrides)
    ensure_dataset_query_table(selected_dataset, query_columns, filters)
    if repository.dataset_rows_table_exists(selected_dataset['id']):
        df = repository.load_dataset_rows(selected_dataset['id'], query_columns, filters)
    else:
        if not dataset_path.exists():
            return None, [], selected_metrics, filter_options, 'The processed dataset is registered, but its source file is missing and no materialized query table exists. Reupload or retry processing this dataset.', False
        df = load_cached_dataset(dataset_path)
        repository.replace_dataset_rows(selected_dataset['id'], df)
    analyses: list[dict[str, Any]] = []
    for metric in selected_metrics:
        try:
            metric_filters = {
                **filters,
                'aggregation': aggregation_overrides.get(metric, aggregation),
                'cdf_grouping': cdf_overrides.get(metric, cdf_grouping),
                'extra_filters': dict(filters.get('extra_filters') or {}),
            }
            analysis = get_cached_analysis(dataset_path, metric_filters, metric)
            if analysis is None:
                with warnings.catch_warnings(record=True) as captured_warnings:
                    warnings.simplefilter('always')
                    analysis = store_cached_analysis(dataset_path, metric_filters, metric, build_analysis(df, metric_filters, metric, prefiltered=True))
                if username:
                    for captured in captured_warnings:
                        repository.add_log(
                            username,
                            'analyze_dataset_warning',
                            json.dumps({
                                'dataset_id': selected_dataset['id'],
                                'metric': metric,
                                'aggregation': metric_filters.get('aggregation') or 'all',
                                'warning': str(captured.message),
                            }),
                        )
            analyses.append({'metric': metric, 'result': analysis})
        except ValueError as exc:
            if username:
                repository.add_log(
                    username,
                    'analyze_dataset_failed',
                    json.dumps({
                        'dataset_id': selected_dataset['id'],
                        'metric': metric,
                        'aggregation': metric_filters.get('aggregation') or 'all',
                        'error': str(exc),
                    }),
                )
            if analyses:
                continue
            return None, [], selected_metrics, filter_options, str(exc), False
        except Exception as exc:
            if username:
                repository.add_log(
                    username,
                    'analyze_dataset_failed',
                    json.dumps({
                        'dataset_id': selected_dataset['id'],
                        'metric': metric,
                        'aggregation': metric_filters.get('aggregation') or 'all',
                        'error': str(exc),
                    }),
                )
            if analyses:
                continue
            return None, [], selected_metrics, filter_options, str(exc), False

    primary_analysis = analyses[0]['result'] if analyses else None
    if primary_analysis is not None:
        primary_analysis.table_rows = build_dashboard_table_rows(df, selected_metrics, primary_analysis.filters.get('aggregation'))
    return primary_analysis, analyses, selected_metrics, filter_options, None, True


@app.get('/healthz')
def healthz() -> dict[str, str]:
    return {'status': 'ok', 'version': __version__}


@app.get('/', response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if request.cookies.get(SESSION_COOKIE) in SESSIONS:
        return RedirectResponse('/documents/view/readme', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse('/login', status_code=status.HTTP_303_SEE_OTHER)


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    workspaces = workspace_registry.list()
    selected_workspace_id = active_workspace.id if active_workspace else workspace_registry.most_recent().id
    return render_template(
        request, 'login.html',
        {
            'error': None,
            'default_access_accounts': build_default_access_accounts(),
            'workspaces': workspaces,
            'active_workspace': active_workspace,
            'selected_workspace_id': selected_workspace_id,
        },
    )


@app.post('/login', response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    workspace_id: str | None = Form(default=None),
) -> Response:
    submitted_username = username.strip().casefold()
    record = repository.get_user(username)
    if not record or not record.active or not verify_password(password, record.password_hash):
        repository.add_log(submitted_username or '(blank)', 'login', json.dumps({
            'success': False, 'result': 'failed', 'reason': 'invalid_credentials',
            'workspace_id': workspace_id or '',
        }))
        workspaces = workspace_registry.list()
        return render_template(
            request,
            'login.html',
            {
                'error': 'Invalid credentials', 'default_access_accounts': build_default_access_accounts(),
                'workspaces': workspaces, 'active_workspace': active_workspace,
                'selected_workspace_id': active_workspace.id if active_workspace else workspace_registry.most_recent().id,
            },
            status_code=401,
        )

    if workspace_id:
        if record.role != 'super-admin' and not repository.user_has_workspace_access(record.username, workspace_id):
            repository.add_log(record.username, 'login', json.dumps({
                'success': False, 'result': 'failed', 'reason': 'workspace_access_denied',
                'workspace_id': workspace_id,
            }))
            return render_template(request, 'login.html', {
                'error': 'You do not have access to that workspace.',
                'error_tone': 'warning',
                'default_access_accounts': build_default_access_accounts(),
                'workspaces': workspace_registry.list(), 'active_workspace': active_workspace,
                'selected_workspace_id': workspace_id,
            }, status_code=403)
        try:
            activate_workspace(workspace_id)
        except ValueError as exc:
            repository.add_log(record.username, 'login', json.dumps({
                'success': False, 'result': 'failed', 'reason': 'workspace_activation_failed',
                'workspace_id': workspace_id, 'error': str(exc),
            }))
            return render_template(request, 'login.html', {
                'error': str(exc), 'default_access_accounts': build_default_access_accounts(),
                'workspaces': workspace_registry.list(), 'active_workspace': active_workspace,
                'selected_workspace_id': workspace_id,
            }, status_code=400)

    user = SessionUser(username=record.username, role=record.role)
    response = RedirectResponse('/documents/view/readme', status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, user)
    repository.add_log(record.username, 'login', json.dumps({
        'success': True, 'result': 'successful', 'role': record.role,
        'workspace_id': active_workspace.id if active_workspace else '',
        'workspace': active_workspace.name if active_workspace else '',
    }))
    return response


@app.get('/logout')
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    session_user = SESSIONS.get(token or '')
    if session_user:
        repository.add_log(session_user.username, 'logout', json.dumps({'success': True}))
    if token:
        SESSIONS.pop(token, None)
    response = RedirectResponse('/login', status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get('/documents/view/{doc_name}', response_class=HTMLResponse)
def documents_view(request: Request, doc_name: str, user: SessionUser = Depends(current_user)) -> HTMLResponse:
    normalized = str(doc_name or '').strip().lower()
    if normalized not in {'readme', 'changelog', 'help'}:
        raise HTTPException(status_code=404, detail='Document not found')
    pretty_title = {'readme': 'README.md', 'changelog': 'CHANGELOG.md', 'help': 'Help'}[normalized]
    return render_template(
        request,
        'doc_view.html',
        {
            'user': user,
            'doc_name': pretty_title,
            'doc_api_url': f'/api/documents/{normalized}',
            'help_navigation': normalized == 'help',
        },
    )


@app.get('/documents/view/help/{doc_file:path}', response_class=HTMLResponse)
def help_document_view(request: Request, doc_file: str, user: SessionUser = Depends(current_user)) -> HTMLResponse:
    path = resolve_help_doc_path(doc_file)
    return render_template(
        request,
        'doc_view.html',
        {
            'user': user,
            'doc_name': HELP_DOCUMENT_LABELS.get(
                doc_file,
                help_document_label(doc_file),
            ),
            'doc_api_url': f'/api/documents/help/{doc_file}',
            'help_navigation': True,
        },
    )


@app.get('/api/documents/help-index')
def get_help_documents_index(user: SessionUser = Depends(current_user)) -> dict[str, Any]:
    help_root = (PROJECT_ROOT / 'help').resolve()
    documents: list[dict[str, str]] = []
    for relative_path in HELP_NAVIGATION_DOCUMENTS:
        file_path = (help_root / relative_path).resolve()
        if not file_path.exists() or not file_path.is_file():
            continue
        documents.append({
            'name': file_path.name,
            'relative_path': relative_path,
            'number': help_document_number(relative_path),
            'label': HELP_DOCUMENT_LABELS.get(
                relative_path,
                help_document_label(relative_path),
            ),
            'url': '/documents/view/help' if relative_path == HELP_HOME_DOCUMENT else f'/documents/view/help/{relative_path}',
        })
    return {'root': str(help_root), 'documents': documents}


@app.get('/api/documents/help/{doc_file:path}')
def get_help_markdown_document(doc_file: str, user: SessionUser = Depends(current_user)) -> dict[str, Any]:
    path = resolve_help_doc_path(doc_file)
    return {
        'name': path.name,
        'path': str(path),
        'content': path.read_text(encoding='utf-8', errors='replace'),
    }


@app.get('/api/documents/{doc_name}')
def get_markdown_document(doc_name: str, user: SessionUser = Depends(current_user)) -> dict[str, Any]:
    path = resolve_doc_path(doc_name)
    return {
        'name': path.name,
        'path': str(path),
        'content': path.read_text(encoding='utf-8', errors='replace'),
    }


@app.get('/workspace', response_class=HTMLResponse)
def workspace(
    request: Request,
    background_tasks: BackgroundTasks,
    dataset_id: int | None = Query(default=None),
    input_kind: str | None = Query(default=None),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    workspace_users = [
        {**dict(row), 'workspace_ids': repository.list_user_workspace_ids(int(row['id']))}
        for row in (repository.list_users() if user.role in {'admin', 'super-admin'} else [])
    ]
    workspaces = workspace_registry.list()
    workspace_access = workspace_access_map(user, workspaces)
    workspace_sizes = {item.id: format_workspace_size(workspace_disk_usage(item)) for item in workspaces}
    if not active_workspace:
        return render_template(
            request,
            'workspace.html',
            {
                'user': user, 'datasets': [], 'ready_datasets': [], 'selected_dataset': None,
                'input_kind': None, 'input_kind_options': [], 'workspace_logs': [], 'error': None,
                'has_processing': False, 'vodafone_mapping_datasets': [], 'three_mapping_datasets': [],
                'mappable_cdr_datasets': [], 'clearable_cdr_datasets': [],
                'calculated_dimensions': [], 'combined_tables': [],
                'workspaces': workspaces, 'workspace_access': workspace_access, 'workspace_sizes': workspace_sizes, 'workspace_users': workspace_users, 'workspace_notice': request.query_params.get('workspace_notice'),
                'workspace_warning': request.query_params.get('workspace_warning'),
                'workspace_error': request.query_params.get('workspace_error'),
            },
        )
    datasets, ready_datasets, input_kind_options, selected_dataset = build_dataset_view_state(dataset_id, input_kind)
    if queue_legacy_vendor_mapping_recovery(background_tasks, datasets, user.username):
        # Reflect the queued recovery in this response instead of leaving a
        # legacy failed row unusable until the next manual refresh.
        datasets, ready_datasets, input_kind_options, selected_dataset = build_dataset_view_state(dataset_id, input_kind)
    has_processing = any(dataset['status'] in {'queued', 'processing'} for dataset in datasets)
    vodafone_mapping_datasets = [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'mapping_vodafone']
    three_mapping_datasets = [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'mapping_three']
    add_workspace_vendor_capabilities(datasets)
    mappable_cdr_datasets = [dataset for dataset in datasets if dataset.get('can_map_vendors')]
    clearable_cdr_datasets = [dataset for dataset in datasets if dataset.get('can_clear_vendors')]
    calculated_dimensions = calculated_dimensions_json(load_workspace_calculated_dimensions())
    combined_tables = workspace_combined_tables()
    queue_workspace_dimension_materialization(active_workspace)

    return render_template(
        request,
        'workspace.html',
        {
            'user': user,
            'datasets': datasets,
            'ready_datasets': ready_datasets,
            'selected_dataset': selected_dataset,
            'input_kind': input_kind,
            'input_kind_options': input_kind_options,
            'workspace_logs': [],
            'error': None,
            'has_processing': has_processing,
            'vodafone_mapping_datasets': vodafone_mapping_datasets,
            'three_mapping_datasets': three_mapping_datasets,
            'mappable_cdr_datasets': mappable_cdr_datasets,
            'clearable_cdr_datasets': clearable_cdr_datasets,
            'calculated_dimensions': calculated_dimensions,
            'combined_tables': combined_tables,
            'workspaces': workspaces,
            'workspace_access': workspace_access,
            'workspace_sizes': workspace_sizes,
            'workspace_users': workspace_users,
            'active_workspace': active_workspace,
            'workspace_notice': request.query_params.get('workspace_notice'),
            'workspace_warning': request.query_params.get('workspace_warning'),
            'workspace_error': request.query_params.get('workspace_error'),
            },
    )


@app.get('/api/workspaces/sizes')
def workspace_sizes_status(user: SessionUser = Depends(current_user)) -> JSONResponse:
    """Return current display sizes after operation-specific cache invalidation."""
    workspaces = workspace_registry.list()
    access = workspace_access_map(user, workspaces)
    visible = [item for item in workspaces if access.get(item.id, False)]
    return JSONResponse({
        'active_workspace_id': active_workspace.id if active_workspace else None,
        'active_workspace_name': active_workspace.name if active_workspace else 'None',
        'sizes': {item.id: format_workspace_size(workspace_disk_usage(item)) for item in visible},
    })


@app.post('/workspace/combined/{kind}/recreate')
def recreate_combined_cdr(
    kind: str, user: SessionUser = Depends(current_user),
) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before recreating combined tables.')
    normalized_kind = str(kind).casefold()
    if normalized_kind not in CDR_DATASET_KINDS:
        raise HTTPException(status_code=404, detail='Unknown combined CDR table.')
    require_workspace_access(user, active_workspace.id)
    job = start_combined_cdr_recreation_job(active_workspace, normalized_kind, user.username)
    repository.add_log(user.username, 'recreate_combined_cdr_table', json.dumps({
        'workspace': active_workspace.id, 'kind': normalized_kind, 'materialization_job': job['id'],
    }))
    return JSONResponse({
        'materialization_job': job['id'],
        'materialization_status_url': f'/api/workspace/auto-calculated-fields/materialization/{job["id"]}',
        'notice': f'The combined CDR-{normalized_kind.upper()} table is being recreated in the background.',
    })


@app.get('/api/workspace/combined/{kind}/integrity')
def combined_cdr_integrity_status(
    kind: str, user: SessionUser = Depends(current_user),
) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before checking combined tables.')
    require_workspace_access(user, active_workspace.id)
    try:
        return JSONResponse(combined_cdr_integrity(kind))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get('/api/workspaces/status')
def workspace_status(user: SessionUser = Depends(current_user)) -> JSONResponse:
    """Lightweight live data for the Workspace Management table."""
    workspaces = workspace_registry.list()
    access = workspace_access_map(user, workspaces)
    # A copy changes continuously; do not serve its 15-second size snapshot
    # to the five-second Workspace Management poller.
    for item in workspaces:
        if item.status == 'duplicating':
            invalidate_workspace_size_cache(item.database_path.parent)
    now = datetime.now(timezone.utc).timestamp()
    with WORKSPACE_LIFECYCLE_JOBS_LOCK:
        removed_workspace_ids = [
            str(job['workspace_id']) for job in WORKSPACE_LIFECYCLE_JOBS.values()
            if job.get('operation') == 'delete' and job.get('status') == 'ready'
            and float(job.get('finished_at') or 0) > now - 30
        ]
        for job_id in [
            job_id for job_id, job in WORKSPACE_LIFECYCLE_JOBS.items()
            if job.get('status') in {'ready', 'failed'} and float(job.get('finished_at') or 0) <= now - 30
        ]:
            WORKSPACE_LIFECYCLE_JOBS.pop(job_id, None)
    return JSONResponse({'workspaces': [
        {'id': item.id, 'status': item.status, 'size': format_workspace_size(workspace_disk_usage(item)),
         'accessible': bool(access.get(item.id, False))}
        for item in workspaces
        if access.get(item.id, False) or (user.role in {'admin', 'super-admin'} and item.status == 'duplicating')
    ], 'removed_workspace_ids': removed_workspace_ids}, headers={'Cache-Control': 'no-store'})


def _workspace_background_tasks(workspace: Workspace) -> list[dict[str, Any]]:
    """Read lightweight job progress without activating the workspace."""
    tasks: list[dict[str, Any]] = []
    if workspace.status == 'duplicating':
        tasks.append({
            'id': f'workspace-duplicate:{workspace.id}',
            'label': 'Duplicating workspace',
            'detail': 'Copying the workspace database and files',
            'progress': None,
        })
    if not workspace.database_path.is_file():
        return tasks
    try:
        with sqlite3.connect(workspace.database_path, timeout=0.15) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                str(row['name'])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            if {'datasets', 'dataset_profiles'} <= tables:
                rows = connection.execute(
                    """SELECT d.id, d.file_name, p.status, p.progress
                       FROM datasets d
                       JOIN dataset_profiles p ON p.dataset_id = d.id
                       WHERE p.status IN ('queued', 'processing')
                       ORDER BY d.uploaded_at, d.id"""
                ).fetchall()
                for row in rows:
                    task_status = str(row['status'] or 'queued').title()
                    tasks.append({
                        'id': f'dataset:{workspace.id}:{row["id"]}',
                        'label': f'Processing dataset: {row["file_name"]}',
                        'detail': task_status,
                        'progress': max(0, min(100, int(row['progress'] or 0))),
                    })
            if 'generated_jobs' in tables:
                rows = connection.execute(
                    """SELECT id, job_type, template_name, output_file, status, progress
                       FROM generated_jobs
                       WHERE status IN ('queued', 'processing')
                       ORDER BY created_at, id"""
                ).fetchall()
                for row in rows:
                    job_type = str(row['job_type'] or '')
                    template_name = str(row['template_name'] or '').strip()
                    output_file = Path(str(row['output_file'] or '')).name
                    if job_type == 'report':
                        label = f'Generating PowerPoint Report: {template_name or output_file or row["id"]}'
                    else:
                        label = f'Generating Chart Set: {template_name or row["id"]}'
                    tasks.append({
                        'id': f'generated:{workspace.id}:{row["id"]}',
                        'label': label,
                        'detail': str(row['status'] or 'queued').title(),
                        'progress': max(0, min(100, int(row['progress'] or 0))),
                    })
            if 'workspace_state' in tables:
                materialization = connection.execute(
                    "SELECT value FROM workspace_state WHERE key = 'calculated_dimensions_need_materialization'"
                ).fetchone()
                if materialization and str(materialization['value']) == 'processing':
                    tasks.append({
                        'id': f'auto-fields-state:{workspace.id}',
                        'label': 'Materializing Auto-calculated Fields',
                        'detail': 'Updating CDR tables',
                        'progress': None,
                    })
    except sqlite3.Error:
        # A worker may briefly hold the database while publishing a progress
        # update. The next browser poll will retry without disrupting the page.
        pass
    return tasks


def _global_background_tasks(user: SessionUser, accessible_ids: set[str]) -> list[dict[str, Any]]:
    """Return current process jobs that are not persisted in workspace databases."""
    tasks: list[dict[str, Any]] = []

    def append_job(job: dict[str, Any], prefix: str, label: str) -> None:
        workspace_ids = [str(value) for value in (job.get('workspace_ids') or []) if str(value)]
        workspace_id = workspace_ids[0] if len(workspace_ids) == 1 and workspace_ids[0] in accessible_ids else '__server__'
        progress_value = job.get('progress')
        progress = max(0, min(100, round(float(progress_value), 1))) if progress_value is not None else None
        tasks.append({
            'id': f'{prefix}:{job.get("id")}',
            'workspace_id': workspace_id,
            'label': label,
            'detail': str(job.get('phase') or job.get('status') or 'processing').replace('_', ' ').title(),
            'progress': progress,
        })

    with EXPORT_JOBS_LOCK:
        export_jobs = [dict(job) for job in EXPORT_JOBS.values()]
    for job in export_jobs:
        if job.get('status') not in {'queued', 'processing'} or (job.get('owner') and job.get('owner') != user.username):
            continue
        append_job(job, 'export', f'Exporting {str(job.get("target") or "package").replace("-", " ").title()}')

    with IMPORT_JOBS_LOCK:
        import_jobs = [dict(job) for job in IMPORT_JOBS.values()]
    for job in import_jobs:
        if job.get('status') not in {'queued', 'processing'} or job.get('owner') != user.username:
            continue
        append_job(job | {'workspace_ids': job.get('destination_workspace_ids')}, 'import', 'Importing package')

    with TRANSFER_LOCK:
        transfer_jobs = [dict(job) for job in TRANSFER_JOBS.values()]
        incoming_transfers = [dict(offer) for offer in TRANSFER_OFFERS.values()]
    for job in transfer_jobs:
        if job.get('status') in {'ready', 'failed', 'cancelled'} or job.get('owner') != user.username:
            continue
        append_job(job, 'transfer', f'Transferring {str(job.get("target") or "package").replace("-", " ").title()}')
    if user.role == 'super-admin':
        for offer in incoming_transfers:
            if offer.get('status') not in {'receiving', 'received', 'importing'}:
                continue
            label = 'Importing transferred package' if offer.get('status') == 'importing' else 'Receiving server transfer'
            append_job(
                offer | {'workspace_ids': offer.get('destination_workspace_ids')},
                'incoming-transfer',
                f'{label}: {offer.get("content") or "package"}',
            )
    return tasks


@app.get('/api/background-tasks')
def background_tasks_status(user: SessionUser = Depends(current_user)) -> JSONResponse:
    """Aggregate running work across accessible workspaces for the global UI."""
    workspaces = accessible_workspaces(user)
    if user.role in {'admin', 'super-admin'}:
        known_ids = {workspace.id for workspace in workspaces}
        workspaces.extend(
            workspace for workspace in workspace_registry.list()
            if workspace.status == 'duplicating' and workspace.id not in known_ids
        )
    accessible_ids = {workspace.id for workspace in workspaces}
    grouped: dict[str, dict[str, Any]] = {}
    for workspace in workspaces:
        workspace_tasks = _workspace_background_tasks(workspace)
        if workspace_tasks:
            grouped[workspace.id] = {
                'workspace_id': workspace.id,
                'workspace_name': workspace.name,
                'is_active': bool(active_workspace and active_workspace.id == workspace.id),
                'tasks': workspace_tasks,
            }

    with WORKSPACE_LIFECYCLE_JOBS_LOCK:
        lifecycle_jobs = [dict(job) for job in WORKSPACE_LIFECYCLE_JOBS.values()]
    now = datetime.now(timezone.utc).timestamp()
    for job in lifecycle_jobs:
        if job.get('operation') != 'delete' or job.get('owner') != user.username:
            continue
        if job.get('status') == 'ready' and float(job.get('finished_at') or 0) < now - 2:
            continue
        if job.get('status') not in {'queued', 'processing', 'ready'}:
            continue
        workspace_id = str(job.get('workspace_id') or '')
        grouped[workspace_id] = {
            'workspace_id': workspace_id,
            'workspace_name': str(job.get('workspace_name') or 'Workspace'),
            'is_active': False,
            'tasks': [{
                'id': f'workspace-delete:{job.get("id")}',
                'label': 'Deleting workspace',
                'detail': 'Removing workspace database and files' if job.get('delete_files') else 'Removing workspace database',
                'progress': 100 if job.get('status') == 'ready' else None,
            }],
        }

    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        auto_jobs = [dict(job) for job in AUTO_CALCULATED_FIELD_JOBS.values()]
    workspace_names = {workspace.id: workspace.name for workspace in workspaces}
    for job in auto_jobs:
        workspace_id = str(job.get('workspace_id') or '')
        if workspace_id not in accessible_ids or job.get('status') not in {'queued', 'processing'}:
            continue
        total = max(0, int(job.get('total') or 0))
        completed = max(0, int(job.get('completed') or 0))
        progress = min(99, round(completed * 100 / total, 1)) if total else None
        group = grouped.setdefault(workspace_id, {
            'workspace_id': workspace_id,
            'workspace_name': str(job.get('workspace_name') or workspace_names.get(workspace_id) or 'Workspace'),
            'is_active': bool(active_workspace and active_workspace.id == workspace_id),
            'tasks': [],
        })
        group['tasks'] = [
            task for task in group['tasks']
            if not str(task.get('id') or '').startswith('auto-fields-state:')
        ]
        group['tasks'].append({
            'id': f'auto-fields:{job.get("id")}',
            'label': 'Recreating combined CDR table' if job.get('operation') == 'combined_recreation' else 'Materializing Auto-calculated Fields',
            'detail': str(job.get('message') or 'Processing'),
            'progress': progress,
        })

    global_tasks = _global_background_tasks(user, accessible_ids)
    for task in global_tasks:
        workspace_id = str(task.pop('workspace_id'))
        if workspace_id == '__server__':
            group = grouped.setdefault('__server__', {
                'workspace_id': '__server__', 'workspace_name': 'Server tasks',
                'is_active': True, 'tasks': [],
            })
        else:
            group = grouped.setdefault(workspace_id, {
                'workspace_id': workspace_id,
                'workspace_name': workspace_names.get(workspace_id, 'Workspace'),
                'is_active': bool(active_workspace and active_workspace.id == workspace_id),
                'tasks': [],
            })
        group['tasks'].append(task)

    groups = sorted(grouped.values(), key=lambda group: (not group['is_active'], str(group['workspace_name']).casefold()))
    return JSONResponse({
        'active_workspace_id': active_workspace.id if active_workspace else None,
        'groups': groups,
    }, headers={'Cache-Control': 'no-store'})


def require_workspace_admin(user: SessionUser) -> None:
    if user.role not in {'admin', 'super-admin'}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only administrators can manage workspaces.')


def require_super_admin(user: SessionUser) -> None:
    if user.role != 'super-admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only super-admins can manage workspace access.')


def accessible_workspaces(user: SessionUser) -> list[Workspace]:
    workspaces = workspace_registry.list()
    if user.role == 'super-admin':
        return workspaces
    return [item for item in workspaces if repository.user_has_workspace_access(user.username, item.id)]


def workspace_access_map(user: SessionUser, workspaces: list[Workspace]) -> dict[str, bool]:
    if user.role == 'super-admin':
        return {workspace.id: True for workspace in workspaces}
    return {workspace.id: repository.user_has_workspace_access(user.username, workspace.id) for workspace in workspaces}


def require_workspace_access(user: SessionUser, workspace_id: str) -> None:
    if user.role != 'super-admin' and not repository.user_has_workspace_access(user.username, workspace_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not have access to that workspace.')


@app.post('/workspace/select')
def select_workspace(
    workspace_id: str = Form(...),
    return_to: str = Form('/workspace'),
    user: SessionUser = Depends(current_user),
) -> Response:
    # The header switcher should refresh the module currently being viewed,
    # never send the user to Workspace merely because the active data source
    # changed.  Restrict the destination to application modules so this form
    # cannot become an open redirect.
    target = return_to if return_to in {'/workspace', '/dashboard', '/reporting', '/admin'} else '/workspace'
    if user.role != 'super-admin' and not repository.user_has_workspace_access(user.username, workspace_id):
        return RedirectResponse(f'{target}?workspace_error=You+do+not+have+access+to+that+workspace.', status_code=status.HTTP_303_SEE_OTHER)
    try:
        activate_workspace(workspace_id)
    except Exception as exc:
        return RedirectResponse(
            f'{target}?{urlencode({"workspace_error": f"Unable to open the selected workspace: {exc}"})}',
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/close')
def close_workspace(workspace_id: str = Form(...), user: SessionUser = Depends(current_user)) -> Response:
    if not active_workspace or active_workspace.id != workspace_id:
        return RedirectResponse('/workspace?workspace_warning=Only+the+open+workspace+can+be+closed.', status_code=status.HTTP_303_SEE_OTHER)
    close_active_workspace()
    return RedirectResponse('/workspace?workspace_notice=Workspace+closed.', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/create')
def create_workspace(name: str = Form(...), usernames: list[str] = Form(default=[]), user: SessionUser = Depends(current_user)) -> Response:
    require_workspace_admin(user)
    try:
        workspace = workspace_registry.create(name)
        selected_usernames = {item.strip().casefold() for item in usernames if item.strip()}
        for account in repository.list_users():
            is_creator = str(account['username']).casefold() == user.username.casefold()
            is_selected_by_super_admin = user.role == 'super-admin' and str(account['username']).casefold() in selected_usernames
            if is_creator or is_selected_by_super_admin:
                repository.set_user_workspace_access(
                    int(account['id']),
                    [*repository.list_user_workspace_ids(int(account['id'])), workspace.id],
                )
        activate_workspace(workspace.id)
    except ValueError as exc:
        return RedirectResponse(f'/workspace?{urlencode({"workspace_error": str(exc)})}', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f'/workspace?{urlencode({"workspace_notice": f"Created and opened {workspace.name}."})}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/rename')
def rename_workspace(workspace_id: str = Form(...), name: str = Form(...), user: SessionUser = Depends(current_user)) -> Response:
    require_workspace_admin(user)
    require_workspace_access(user, workspace_id)
    try:
        workspace = workspace_registry.rename(workspace_id, name)
        if active_workspace and active_workspace.id == workspace.id:
            activate_workspace(workspace.id)
    except ValueError as exc:
        return RedirectResponse(f'/workspace?{urlencode({"workspace_error": str(exc)})}', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f'/workspace?{urlencode({"workspace_notice": f"Renamed workspace to {workspace.name}."})}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/save')
def save_workspace(
    request: Request,
    workspace_id: str = Form(...),
    name: str = Form(...),
    usernames: list[str] = Form(default=[]),
    user: SessionUser = Depends(current_user),
) -> Response:
    require_workspace_admin(user)
    require_workspace_access(user, workspace_id)
    try:
        current_workspace = workspace_registry.get(workspace_id)
        if not current_workspace:
            raise ValueError('Workspace not found.')
        # Saving access must not attempt a filesystem rename when the name is
        # unchanged: the managed directory already exists by design.
        workspace = current_workspace if name == current_workspace.name else workspace_registry.rename(workspace_id, name)
        if user.role == 'super-admin':
            repository.set_workspace_user_access(workspace.id, usernames)
        if active_workspace and active_workspace.id == workspace.id:
            activate_workspace(workspace.id)
    except ValueError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JSONResponse({'detail': str(exc)}, status_code=400)
        return RedirectResponse(f'/workspace?{urlencode({"workspace_error": str(exc)})}', status_code=status.HTTP_303_SEE_OTHER)
    notice = 'Workspace name and access updated.' if user.role == 'super-admin' else 'Workspace name updated.'
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JSONResponse({'ok': True, 'notice': notice, 'workspace': {'id': workspace.id, 'name': workspace.name}})
    return RedirectResponse(f'/workspace?{urlencode({"workspace_notice": notice})}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/duplicate')
def duplicate_workspace(
    workspace_id: str = Form(...),
    include_generated_outputs: bool = Form(False),
    user: SessionUser = Depends(current_user),
) -> Response:
    require_workspace_admin(user)
    require_workspace_access(user, workspace_id)
    source = workspace_registry.get(workspace_id)
    if source is None:
        return RedirectResponse('/workspace?workspace_error=Workspace+not+found.', status_code=status.HTTP_303_SEE_OTHER)

    def run_duplication() -> None:
      workspace: Workspace | None = None
      try:
        workspace = workspace_registry.duplicate(
            workspace_id,
            include_generated_outputs=include_generated_outputs,
        )
        # A duplicate must retain the origin workspace membership.  Otherwise
        # an administrator who is allowed to duplicate a workspace could not
        # open the new copy afterwards.
        source_members = [
            str(account['username'])
            for account in repository.list_users()
            if workspace_id in repository.list_user_workspace_ids(int(account['id']))
        ]
        repository.set_workspace_user_access(workspace.id, source_members)
        invalidate_workspace_size_cache(workspace.database_path.parent)
      except Exception:
        # Do not leave a registered but inaccessible/partially configured
        # workspace behind when the filesystem copy or permission copy fails.
        if workspace is not None:
            try:
                workspace_registry.delete(workspace.id, delete_files=True)
                repository.remove_workspace_access(workspace.id)
            except Exception:
                pass
    Thread(target=run_duplication, name=f'workspace-duplicate-{workspace_id}', daemon=True).start()
    return RedirectResponse('/workspace?workspace_notice=Workspace+duplication+started.+The+copy+will+appear+when+ready.', status_code=status.HTTP_303_SEE_OTHER)


@app.get('/workspace/duplicate')
def duplicate_workspace_get(user: SessionUser = Depends(current_user)) -> Response:
    """Keep direct/proxy GET requests from surfacing a misleading 404 page.

    Duplication is intentionally a POST-only state-changing operation; a direct
    navigation should return the user to Workspace with an actionable message.
    """
    return RedirectResponse(
        '/workspace?workspace_warning=Use+the+Duplicate+workspace+button+to+submit+the+duplication+request.',
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post('/workspace/delete')
def delete_workspace(
    workspace_id: str = Form(...),
    delete_workspace_files: bool = Form(False),
    user: SessionUser = Depends(current_user),
) -> Response:
    require_workspace_admin(user)
    # Allow administrators to clean up orphaned registry entries whose database
    # was removed or became inaccessible; valid workspaces still require access.
    registered_workspace = workspace_registry.get(workspace_id)
    if registered_workspace is None:
        return RedirectResponse('/workspace?workspace_error=Workspace+not+found.', status_code=status.HTTP_303_SEE_OTHER)
    require_workspace_access(user, workspace_id)
    if active_workspace and active_workspace.id == workspace_id:
        return RedirectResponse('/workspace?workspace_warning=Close+the+workspace+before+removing+it.', status_code=status.HTTP_303_SEE_OTHER)
    try:
        workspace_root = workspace_registry._managed_workspace_root(registered_workspace)
        workspace_registry.remove(workspace_id, delete_files=False)
        repository.remove_workspace_access(workspace_id)
    except ValueError as exc:
        return RedirectResponse(f'/workspace?{urlencode({"workspace_error": str(exc)})}', status_code=status.HTTP_303_SEE_OTHER)
    # Tiny workspaces can be removed before the redirect returns; larger
    # directories still use the worker below and keep the task visible while
    # their files are being removed.
    if delete_workspace_files and workspace_disk_usage(registered_workspace) <= 8 * 1024 * 1024:
        shutil.rmtree(workspace_root, ignore_errors=True)
    elif not delete_workspace_files:
        for database_file in (
            registered_workspace.database_path,
            *(Path(f'{registered_workspace.database_path}{suffix}') for suffix in ('-wal', '-shm')),
        ):
            database_file.unlink(missing_ok=True)
    job_id = uuid4().hex
    with WORKSPACE_LIFECYCLE_JOBS_LOCK:
        WORKSPACE_LIFECYCLE_JOBS[job_id] = {
            'id': job_id, 'operation': 'delete', 'workspace_id': workspace_id,
            'workspace_name': registered_workspace.name, 'owner': user.username,
            'delete_files': delete_workspace_files, 'status': 'queued',
            'created_at': datetime.now(timezone.utc).timestamp(),
        }

    def run_deletion() -> None:
        with WORKSPACE_LIFECYCLE_JOBS_LOCK:
            job = WORKSPACE_LIFECYCLE_JOBS.get(job_id)
            if job:
                job['status'] = 'processing'
        try:
            if delete_workspace_files:
                shutil.rmtree(workspace_root, ignore_errors=True)
            else:
                for database_file in (
                    registered_workspace.database_path,
                    *(Path(f'{registered_workspace.database_path}{suffix}') for suffix in ('-wal', '-shm')),
                ):
                    database_file.unlink(missing_ok=True)
            with WORKSPACE_LIFECYCLE_JOBS_LOCK:
                job = WORKSPACE_LIFECYCLE_JOBS.get(job_id)
                if job:
                    job.update(status='ready', finished_at=datetime.now(timezone.utc).timestamp())
        except Exception as exc:
            with WORKSPACE_LIFECYCLE_JOBS_LOCK:
                job = WORKSPACE_LIFECYCLE_JOBS.get(job_id)
                if job:
                    job.update(status='failed', error=str(exc), finished_at=datetime.now(timezone.utc).timestamp())

    Thread(target=run_deletion, name=f'workspace-delete-{workspace_id}', daemon=True).start()
    return RedirectResponse(
        '/workspace?workspace_notice=Workspace+deletion+started.+The+workspace+will+disappear+when+the+operation+finishes.',
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post('/workspace/access')
def update_workspace_access(
    request: Request,
    workspace_id: str = Form(...),
    usernames: list[str] = Form(default=[]),
    user: SessionUser = Depends(admin_user),
) -> Response:
    require_super_admin(user)
    if not workspace_registry.get(workspace_id):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JSONResponse({'detail': 'Workspace not found.'}, status_code=404)
        return RedirectResponse('/workspace?workspace_error=Workspace+not+found.', status_code=status.HTTP_303_SEE_OTHER)
    repository.set_workspace_user_access(workspace_id, usernames)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JSONResponse({'ok': True, 'notice': 'Workspace access updated.'})
    return RedirectResponse('/workspace?workspace_notice=Workspace+access+updated.', status_code=status.HTTP_303_SEE_OTHER)


@app.get('/workspace/preview/{dataset_id}', response_class=HTMLResponse)
def preview_dataset(
    dataset_id: int,
    request: Request,
    row_limit: int = Query(default=100, ge=1, le=5000),
    source_sheet: str | None = Query(default=None),
    mapping_vendor: str | None = Query(default=None),
    gcid: str | None = Query(default=None),
    cdr_operator: list[str] = Query(default=[]),
    cdr_vendor: list[str] = Query(default=[]),
    cdr_rat: list[str] = Query(default=[]),
    cdr_session_type: list[str] = Query(default=[]),
    cdr_call_status: list[str] = Query(default=[]),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    dataset_row = repository.get_dataset(dataset_id)
    if not dataset_row:
        raise HTTPException(status_code=404, detail='Dataset not found')
    dataset = serialize_dataset_row(dataset_row)
    if not dataset['is_ready']:
        raise HTTPException(status_code=400, detail='Only processed datasets can be previewed.')
    dataset = ensure_mapping_gcid(dataset)
    dataset = ensure_canonical_mapped_vendor_column(dataset) or dataset
    available_columns = repository.list_dataset_row_columns(dataset_id)
    vendor_preview_column = next(
        (column for column in ('Vendor', 'OP/ Vendor', 'OP_Vendor') if column in available_columns),
        None,
    ) if dataset['dataset_kind'] in {'mapping_vodafone', 'mapping_three'} else None
    vendor_preview_columns = {vendor_preview_column} if vendor_preview_column else set()
    vendor_filter_options = repository.list_distinct_dataset_row_values(dataset_id, vendor_preview_column) if vendor_preview_column else []
    preview_sheet_options: list[str] = []
    preview_source_sheet: str | None = None
    preview_filters: dict[str, Any] = {}
    workspace_dimensions = load_workspace_calculated_dimensions()
    all_calculated_dimension_keys = {
        _normalise_catalogue_dimension_name(dimension.name)
        for dimension in workspace_dimensions
    }
    derived_preview_columns = {
        dimension.name for dimension in workspace_dimensions
        if f"cdr-{dataset['dataset_kind']}" in dimension.sources
        and dimension.name in available_columns
    } if dataset['dataset_kind'] in CDR_DATASET_KINDS else set()
    if dataset['dataset_kind'] == 'mapping_vodafone':
        available_sheets = {sheet.casefold(): sheet for sheet in repository.list_distinct_dataset_row_values(dataset_id, 'source_sheet')}
        preview_sheet_options = [available_sheets[name] for name in ('4g', '5g') if name in available_sheets]
        if preview_sheet_options:
            requested_sheet = (source_sheet or '').casefold()
            preview_source_sheet = next(
                (sheet for sheet in preview_sheet_options if sheet.casefold() == requested_sheet),
                preview_sheet_options[0],
            )
            preview_filters['source_sheet'] = preview_source_sheet
    selected_mapping_vendor = mapping_vendor if mapping_vendor in vendor_filter_options else ''
    if selected_mapping_vendor and vendor_preview_column:
        preview_filters[vendor_preview_column] = selected_mapping_vendor
    selected_gcid = (gcid or '').strip()
    if selected_gcid:
        preview_filters['GCID'] = selected_gcid
    cdr_preview_filters: list[dict[str, object]] = []
    if dataset['dataset_kind'] in CDR_DATASET_KINDS:
        requested_by_parameter = {
            'cdr_operator': cdr_operator, 'cdr_vendor': cdr_vendor, 'cdr_rat': cdr_rat,
            'cdr_session_type': cdr_session_type, 'cdr_call_status': cdr_call_status,
        }
        for parameter, label, candidates in CDR_PREVIEW_FILTER_DEFINITIONS:
            requested_values = requested_by_parameter[parameter]
            column = next(
                (
                    resolved for candidate in candidates
                    if (resolved := repository.resolve_dataset_row_column_name(dataset_id, candidate))
                ),
                None,
            )
            if not column:
                continue
            options = repository.list_distinct_dataset_row_values(dataset_id, column)
            # A newly opened CDR preview represents the complete dataset, so
            # its multi-select controls must visibly start with every available
            # value selected.  Explicit query values continue to narrow the
            # selection when the user refreshes the preview.
            selected_values = (
                [value for value in requested_values if value in options]
                if requested_values else list(options)
            )
            if selected_values:
                preview_filters[column] = selected_values
            cdr_preview_filters.append({
                'parameter': parameter,
                'label': label,
                'options': options,
                'selected_values': selected_values,
            })
            if parameter == 'cdr_vendor':
                vendor_preview_columns.add(column)

    if dataset['dataset_kind'] == 'mapping_vodafone':
        source_columns = get_excel_sheet_columns(Path(dataset['stored_path']), preview_source_sheet) if preview_source_sheet else []
        preview_columns = [column for column in ('GCID',) if column in available_columns]
        preview_columns.extend(
            column for column in source_columns
            if column not in preview_columns and repository.resolve_dataset_row_column_name(dataset_id, column)
        )
        if not source_columns:
            preview_columns.extend(
                column for column in available_columns
                if column not in preview_columns and not is_mapping_preview_normalized_column(column)
            )
    elif dataset['dataset_kind'] == 'mapping_three':
        preview_columns = [column for column in ('GCID',) if column in available_columns]
        preview_columns.extend(
            column for column in available_columns
            if column not in preview_columns and not is_mapping_preview_normalized_column(column)
        )
    else:
        priority_columns = [
            'source_sheet', 'GCID', 'operator', 'vendor', 'market', 'period', 'region', 'city', 'technology_primary',
            'session_type', 'test_name', 'direction', 'event_start_time', 'status',
        ]
        preview_columns = [column for column in priority_columns if column in available_columns]
        # report_vendor is a renderer-only comparison field. The analyst sees
        # the calculated vendor column instead, highlighted near the start.
        preview_columns.extend(
            column for column in available_columns
            if column not in preview_columns
            and column != 'report_vendor'
            and column not in derived_preview_columns
            and _normalise_catalogue_dimension_name(column) not in all_calculated_dimension_keys
        )
        preview_columns.extend(column for column in available_columns if column in derived_preview_columns)
    preview_frame = repository.load_dataset_rows(dataset_id, preview_columns, preview_filters).head(row_limit)
    if 'GCID' in preview_frame.columns:
        preview_frame = preview_frame.copy()
        preview_frame['GCID'] = preview_frame['GCID'].map(format_preview_gcid)
    preview_rows = preview_frame.astype(object).where(pd.notna(preview_frame), '').to_dict(orient='records')

    return render_template(
        request,
        'dataset_preview.html',
        {
            'user': user,
            'dataset': dataset,
            'preview_columns': preview_columns,
            'preview_rows': preview_rows,
            'preview_row_limit': row_limit,
            'preview_sheet_options': preview_sheet_options,
            'preview_source_sheet': preview_source_sheet,
            'vendor_preview_columns': vendor_preview_columns,
            'derived_preview_columns': derived_preview_columns,
            'vendor_filter_options': vendor_filter_options,
            'selected_mapping_vendor': selected_mapping_vendor,
            'selected_gcid': selected_gcid,
            'cdr_preview_filters': cdr_preview_filters,
            'visible_column_count': len(preview_columns),
        },
    )


@app.get('/workspace/combined/{kind}/preview', response_class=HTMLResponse)
def preview_combined_dataset(
    kind: str,
    request: Request,
    row_limit: int = Query(default=100, ge=1, le=5000),
    allow_incomplete: bool = Query(default=False),
    cdr_operator: list[str] = Query(default=[]),
    cdr_vendor: list[str] = Query(default=[]),
    cdr_rat: list[str] = Query(default=[]),
    cdr_session_type: list[str] = Query(default=[]),
    cdr_call_status: list[str] = Query(default=[]),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    """Render a combined CDR through the same preview interface as an individual CDR."""
    normalized_kind = str(kind or '').casefold()
    if normalized_kind not in CDR_DATASET_KINDS:
        raise HTTPException(status_code=404, detail='Combined dataset not found')
    integrity = combined_cdr_integrity(normalized_kind)
    if integrity['has_missing_rows'] and not allow_incomplete:
        raise HTTPException(
            status_code=409,
            detail=(
                f"CDR-{normalized_kind.upper()} (combined) contains {integrity['row_count']} of "
                f"{integrity['expected_row_count']} rows. Recreate it from Workspace > Datasets before using it."
            ),
        )
    available_columns = [
        column for column in repository.list_reporting_row_columns(normalized_kind)
        if column not in {'dataset_id', 'source_row_id'}
    ]
    if not available_columns:
        raise HTTPException(status_code=404, detail='Combined dataset not found')
    workspace_dimensions = load_workspace_calculated_dimensions()
    all_calculated_dimension_keys = {
        _normalise_catalogue_dimension_name(dimension.name) for dimension in workspace_dimensions
    }
    derived_preview_columns = {
        dimension.name for dimension in workspace_dimensions
        if f'cdr-{normalized_kind}' in dimension.sources and dimension.name in available_columns
    }
    requested_by_parameter = {
        'cdr_operator': cdr_operator, 'cdr_vendor': cdr_vendor, 'cdr_rat': cdr_rat,
        'cdr_session_type': cdr_session_type, 'cdr_call_status': cdr_call_status,
    }
    preview_filters: dict[str, Any] = {}
    cdr_preview_filters: list[dict[str, object]] = []
    vendor_preview_columns: set[str] = set()
    for parameter, label, candidates in CDR_PREVIEW_FILTER_DEFINITIONS:
        column = next(
            (
                resolved for candidate in candidates
                if (resolved := repository.resolve_reporting_row_column_name(normalized_kind, candidate))
            ),
            None,
        )
        if not column:
            continue
        options = repository.list_distinct_reporting_row_values(normalized_kind, column)
        requested_values = requested_by_parameter[parameter]
        selected_values = [value for value in requested_values if value in options] if requested_values else list(options)
        if selected_values:
            preview_filters[column] = selected_values
        cdr_preview_filters.append({
            'parameter': parameter, 'label': label, 'options': options,
            'selected_values': selected_values,
        })
        if parameter == 'cdr_vendor':
            vendor_preview_columns.add(column)
    priority_columns = [
        'source_sheet', 'operator', 'vendor', 'market', 'period', 'region', 'city', 'technology_primary',
        'session_type', 'test_name', 'direction', 'event_start_time', 'status',
    ]
    preview_columns = [column for column in priority_columns if column in available_columns]
    preview_columns.extend(
        column for column in available_columns
        if column not in preview_columns
        and column != 'report_vendor'
        and column not in derived_preview_columns
        and _normalise_catalogue_dimension_name(column) not in all_calculated_dimension_keys
    )
    preview_columns.extend(column for column in available_columns if column in derived_preview_columns)
    preview_frame = repository.load_reporting_preview_rows(
        normalized_kind, preview_columns, preview_filters, row_limit,
    )
    preview_rows = preview_frame.astype(object).where(pd.notna(preview_frame), '').to_dict(orient='records')
    updated_at = repository.get_workspace_state(f'combined_reporting_updated_{normalized_kind}') or ''
    total_row_count = repository.reporting_row_count(normalized_kind)
    dataset = {
        'id': f'combined-{normalized_kind}',
        'file_name': f'CDR-{normalized_kind.title()} (combined)',
        'dataset_kind': normalized_kind,
        'input_kind_label': f'CDR-{normalized_kind.title()} (combined)',
        'status': 'ready', 'status_label': 'Ready', 'row_count': total_row_count,
        'uploaded_by': 'Workspace', 'is_combined': True,
    }
    return render_template(
        request,
        'dataset_preview.html',
        {
            'user': user,
            'dataset': dataset,
            'preview_columns': preview_columns,
            'preview_rows': preview_rows,
            'preview_row_limit': row_limit,
            'preview_sheet_options': [], 'preview_source_sheet': None,
            'vendor_preview_columns': vendor_preview_columns,
            'derived_preview_columns': derived_preview_columns,
            'vendor_filter_options': [], 'selected_mapping_vendor': '', 'selected_gcid': '',
            'cdr_preview_filters': cdr_preview_filters,
            'visible_column_count': len(preview_columns),
            'preview_action': f'/workspace/combined/{normalized_kind}/preview',
            'preview_metadata_label': 'Updated',
            'preview_metadata_value': format_local_timestamp(updated_at) if updated_at else '—',
        },
    )


@app.get('/app-logs', response_class=HTMLResponse)
def app_logs(request: Request, user: SessionUser = Depends(current_user)) -> HTMLResponse:
    logs = build_app_logs()
    return render_template(
        request,
        'app_logs.html',
        {
            'user': user,
            'logs': logs,
            'log_users': sorted({log['username'] for log in logs if log['username']}, key=str.casefold),
            'log_executors': sorted({log['executed_by'] for log in logs if log['executed_by']}, key=str.casefold),
            'log_dates': sorted({log['date'] for log in logs if log['date']}, reverse=True),
            'log_types': sorted({log['log_type'] for log in logs if log['log_type']}, key=str.casefold),
            'log_actions': sorted({log['action'] for log in logs if log['action']}, key=str.casefold),
        },
    )


@app.get('/api/app-logs')
def app_logs_data(user: SessionUser = Depends(current_user)) -> JSONResponse:
    """Return current workspace events for incremental App Logs refreshes."""
    return JSONResponse({'logs': build_app_logs()})


@app.get('/dashboard', response_class=HTMLResponse)
def dashboard(
    request: Request,
    dataset_id: int | None = Query(default=None),
    input_kind: str | None = Query(default=None),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    if not active_workspace:
        return RedirectResponse('/workspace?workspace_warning=Open+a+workspace+before+using+Dashboard.', status_code=status.HTTP_303_SEE_OTHER)
    datasets, ready_datasets, input_kind_options, selected_dataset = build_dataset_view_state(dataset_id, input_kind, CDR_DATASET_KINDS)
    selected_dataset = refresh_selected_dataset_if_stale(selected_dataset)
    selected_dataset = ensure_canonical_mapped_vendor_column(selected_dataset)
    selected_dataset = enrich_selected_dataset_for_dashboard(selected_dataset)
    analysis, analyses, selected_metrics, filter_options, analysis_error, analysis_loaded = build_dashboard_payload(selected_dataset, request, user.username)

    return render_template(
        request,
        'dashboard.html',
        {
            'user': user,
            'datasets': datasets,
            'ready_datasets': ready_datasets,
            'selected_dataset': selected_dataset,
            'analysis': analysis,
            'analyses': analyses,
            'analysis_loaded': analysis_loaded,
            'selected_metrics': selected_metrics,
            'selected_date_from': request.query_params.get('date_from') or '',
            'selected_date_to': request.query_params.get('date_to') or '',
            'selected_aggregation': request.query_params.get('aggregation') or (selected_dataset.get('default_aggregation') if selected_dataset else 'all') or 'all',
            'aggregation_overrides': parse_aggregation_overrides(request.query_params.get('aggregation_overrides') or ''),
            'selected_cdf_grouping': request.query_params.get('cdf_grouping') or 'all',
            'cdf_overrides': parse_cdf_overrides(request.query_params.get('cdf_overrides') or ''),
            'filter_options': filter_options,
            'input_kind': input_kind,
            'input_kind_options': input_kind_options,
            'filter_dimensions': [
                dimension for dimension in FILTER_DIMENSIONS_BY_KIND.get((selected_dataset or {}).get('dataset_kind') or 'generic', FILTER_DIMENSIONS)
            ],
            'error': analysis_error,
        },
    )


def _reporting_dataset(
    dataset_id: int,
    expected_kind: str,
    task_repository: Repository | None = None,
) -> dict[str, Any]:
    task_repository = task_repository or repository
    dataset = task_repository.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=400, detail=f'Selected {expected_kind} CDR was not found.')
    payload = serialize_dataset_row(dataset)
    if not payload['is_ready']:
        raise HTTPException(status_code=400, detail=f"{payload['file_name']} has not finished processing.")
    if payload.get('dataset_kind') != expected_kind:
        raise HTTPException(status_code=400, detail=f"{payload['file_name']} is not a {expected_kind.title()} CDR.")
    return payload


def _reporting_datasets(
    dataset_ids: list[int], expected_kind: str, task_repository: Repository | None = None,
) -> list[dict[str, Any]]:
    """Validate a non-empty, de-duplicated selection of compatible CDRs."""
    unique_ids = list(dict.fromkeys(int(dataset_id) for dataset_id in dataset_ids))
    if not unique_ids:
        raise HTTPException(status_code=400, detail=f'Select at least one {expected_kind.title()} CDR.')
    return [_reporting_dataset(dataset_id, expected_kind, task_repository) for dataset_id in unique_ids]


def _optional_reporting_datasets(
    dataset_ids: list[int], expected_kind: str, task_repository: Repository | None = None,
) -> list[dict[str, Any]]:
    """Validate one optional CDR-type selection while preserving non-empty validation."""
    return _reporting_datasets(dataset_ids, expected_kind, task_repository) if dataset_ids else []


def _reporting_frame(dataset_id: int, task_repository: Repository | None = None) -> pd.DataFrame:
    task_repository = task_repository or repository
    return task_repository.load_dataset_rows(dataset_id, task_repository.list_dataset_row_columns(dataset_id), {})


def reporting_query_columns(dataset_kind: str, catalog_entries: list[Any], multivendor: bool) -> list[str]:
    """Select only fields that can affect the chosen CDR report.

    The remaining per-CDR columns stay available in Workspace, but a report no
    longer transfers every historical source field just to render its charts.
    """
    requested = {
        'source_sheet', 'Operator', 'Campaign', 'vendor', 'report_vendor',
        'RAT', 'RAT_A', 'Sample_RAT_A', 'technology_primary',
        'L1_Call_Mode_A', 'L2_Call_Mode_A', 'Session_Type', 'session_type',
        'Type_of_Test', 'Test_Name', 'test_name', 'Test_Type', 'test_type',
    }
    for entry in catalog_entries:
        if entry.source_kind != dataset_kind:
            continue
        # Scatter and Map KPIs declare their two coordinates as
        # ``latitude vs longitude``. They are physical CDR columns, not one
        # combined column name.
        requested.update(
            part.strip(' `')
            for part in re.split(r'\s+vs\s+|\s*\|\s*', entry.kpi, flags=re.IGNORECASE)
            if part.strip()
        )
        requested.update(_legend_dimensions(entry.legend))
        requested.update(parse_catalog_grouping(entry.grouping_rows).dimensions)
        requested.update(parse_catalog_grouping(entry.grouping_columns).dimensions)
        requested.update(condition.column for condition in parse_catalog_filters(entry.filters))
        for dimension in entry.calculated_dimensions:
            if entry.cdr_source.casefold() not in dimension.sources:
                continue
            requested.update(dimension.default_from)
            for rule in dimension.rules:
                for condition in rule.conditions:
                    requested.update(part.strip() for part in condition.column.split('|') if part.strip())
    requested_identities = {
        re.sub(r'[^a-z0-9]', '', str(column).casefold())
        for column in requested
    }
    # Calculated Tableau dimensions are reconstructed in the renderer. Include
    # their physical dependencies in the compact reporting table so job output
    # matches Interactive Preview and direct rendering.
    derived_dependencies = {
        'vendorv3': {'vendor', 'report_vendor'},
        'firstltepccarfcn': {'LTE_PCC_EARFCN'},
        'tputabove': {'Mean_Data_Rate', 'Test_Name'},
        'tputbelow': {'Mean_Data_Rate', 'Test_Name'},
        'ttfp10sratio': {'VideoStream_Time_to_First_Picture'},
        'lowratesession': {'Mean_Data_Rate', 'Test_Name'},
        'ltedlaggregatedbwmhz': {'LTE_DL_Test_Bandwidth_Avg'},
        'ltedltestbandwidthavgint': {'LTE_DL_Test_Bandwidth_Avg'},
        'nrdlpcellnumerology1bandwidthnumber': {'NR_PCell_Numerology1_Bandwidth'},
        'nrultotalbandwidthmhz': {'NR_UL_RBs_Avg'},
        'totalbwltenr': {'LTE_DL_Test_Bandwidth_Avg', 'NR_DL_PCell_Bandwidth'},
        'emocnnnshystorical': {'Campaign', 'Test_Start_Time', 'NNS Activation Date (F)', 'MOCN Activation Date (F)'},
        'emocnnnshystoricalnew': {'Campaign', 'Test_Start_Time', 'NNS Activation Date (F)', 'MOCN Activation Date (F)'},
        'emocnnnshystoricalnew2': {'Test_Start_Time', 'NNS Activation Date (F)', 'MOCN Activation Date (F)'},
        'emocnnnshystoricalwithoperator': {'Campaign', 'Test_Start_Time', 'NNS Activation Date (F)', 'MOCN Activation Date (F)', 'Host Network'},
    }
    for identity, dependencies in derived_dependencies.items():
        if identity in requested_identities:
            requested.update(dependencies)
    # Derived grouping/filter labels resolve from their source fields above;
    # empty presentation fields are not database column requests.
    return sorted(column for column in requested if str(column).strip())


def _combined_reporting_frame(
    datasets: list[dict[str, Any]],
    technology: str,
    catalog_entries: list[Any],
    multivendor: bool,
    task_repository: Repository | None = None,
) -> pd.DataFrame:
    """Load selected campaigns in one query from their shared CDR table."""
    task_repository = task_repository or repository
    dataset_kind = str(datasets[0]['dataset_kind'])
    dataset_ids = [int(dataset['id']) for dataset in datasets]
    columns = reporting_query_columns(dataset_kind, catalog_entries, multivendor)
    for dataset_id in dataset_ids:
        task_repository.copy_dataset_rows_to_reporting(dataset_id, dataset_kind, columns)
    combined = task_repository.load_reporting_rows(dataset_kind, dataset_ids, columns)
    if combined.empty:
        raise ValueError(f'The selected {dataset_kind.title()} CDRs have no materialised reporting rows.')
    if 'source_sheet' in combined.columns:
        source_sheet_keys = combined['source_sheet'].fillna('').astype(str).str.strip().str.casefold()
        combined = combined.loc[~source_sheet_keys.isin(CDR_IGNORED_SHEET_KEYS)].copy()
    # Data tests may legitimately fall back to LTE or report NR SA at the
    # failure instant. Treating that sample RAT as a report-wide NSA/SA filter
    # silently removes valid attempts and corrupts completion percentages.
    # Voice and Speech still require call/session classification by technology.
    return combined if dataset_kind == 'data' else classify_sessions(combined, technology)


def _clear_chart_preview_caches() -> None:
    """Drop workspace-bound preview frames when their backing data can change."""
    with CHART_PREVIEW_CACHE_LOCK:
        CHART_PREVIEW_FRAME_CACHE.clear()
        CHART_PREVIEW_FILTER_CACHE.clear()
        CHART_PREVIEW_DATA_CACHE.clear()


def _chart_preview_cache_key(scope: str, material: dict[str, Any]) -> str:
    workspace = str(active_workspace.database_path.resolve()) if active_workspace else ''
    encoded = json.dumps({'scope': scope, 'workspace': workspace, **material}, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _bounded_preview_frame(cache: dict[str, pd.DataFrame], key: str, loader: Callable[[], pd.DataFrame], limit: int) -> pd.DataFrame:
    """Return one immutable cached frame while bounding preview memory usage."""
    with CHART_PREVIEW_CACHE_LOCK:
        cached = cache.get(key)
    if cached is not None:
        return cached
    loaded = loader()
    with CHART_PREVIEW_CACHE_LOCK:
        cached = cache.setdefault(key, loaded)
        while len(cache) > limit:
            cache.pop(next(iter(cache)))
    return cached


def _cached_filtered_chart_frame(
    source_key: str, frame: pd.DataFrame, entry: CatalogEntry, multivendor: bool,
) -> pd.DataFrame:
    """Reuse source/filter work when only grouping or presentation changes."""
    key = _chart_preview_cache_key('filtered-chart-frame', {
        'source_key': source_key,
        'cdr_source': entry.cdr_source,
        'chart_type': entry.chart_type,
        'kpi': entry.kpi,
        'filters': entry.filters,
        'multivendor': multivendor,
    })
    return _bounded_preview_frame(
        CHART_PREVIEW_FILTER_CACHE,
        key,
        lambda: prepare_catalog_chart_preview_frame(frame, entry, multivendor=multivendor)[0],
        8,
    )


def _report_dataset_names(selected: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {kind: [str(dataset['file_name']) for dataset in datasets] for kind, datasets in selected.items()}


def _report_job_output_path(row: Any) -> Path | None:
    """Resolve current and legacy report locations for persisted report jobs."""
    stored = str(row['output_path'] or '').strip()
    candidates: list[Path] = []
    if stored:
        candidates.append(Path(stored))
    file_name = Path(str(row['output_file'] or '')).name
    if file_name:
        # New reports live under the active workspace's output tree.  Keep the
        # former exports location as a compatibility fallback for old jobs.
        candidates.extend((
            Path(settings.output_dir) / 'reports' / file_name,
            Path(settings.export_dir) / file_name,
            Path(settings.output_dir) / file_name,
        ))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _report_job_directory(file_name: str, output_dir: Path | None = None) -> Path:
    """Return the dedicated directory for one generated PowerPoint report."""
    reports_dir = Path(output_dir or settings.output_dir) / 'reports'
    stem = Path(file_name).stem
    return safe_join(reports_dir, stem)


def _delete_report_job_artifacts(row: Any) -> None:
    """Remove a report file and its sibling rendered PNG charts."""
    file_name = Path(str(row['output_file'] or '')).name
    if file_name:
        # The job directory may still contain rendered charts or partial
        # output even when the PowerPoint itself is already missing.
        report_dir = _report_job_directory(file_name)
        if report_dir.is_dir():
            shutil.rmtree(report_dir)
    path = _report_job_output_path(row)
    if path is None:
        return
    if path.parent != _report_job_directory(path.name):
        path.unlink(missing_ok=True)


def _report_job_charts_directory(row: Any) -> Path | None:
    path = _report_job_output_path(row)
    if path is None or path.parent != _report_job_directory(path.name):
        return None
    directory = path.parent / 'report-charts'
    return directory if directory.is_dir() else None


def _report_job_charts_payload(row: Any) -> dict[str, Any] | None:
    directory = _report_job_charts_directory(row)
    if directory is None:
        return None
    try:
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    charts: list[dict[str, Any]] = []
    for item in manifest.get('charts', []) if isinstance(manifest, dict) else []:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get('file') or '')
        if not re.fullmatch(r'slide-\d+-chart-\d+\.png', file_name) or not (directory / file_name).is_file():
            return None
        charts.append({
            'slide': item.get('slide'), 'title': str(item.get('title') or ''),
            'source': str(item.get('source') or ''), 'chart_type': str(item.get('chart_type') or ''),
            'image_url': f"/reporting/jobs/{int(row['id'])}/charts/{file_name}",
        })
    if not charts:
        return None
    try:
        dataset_ids = json.loads(row['dataset_ids_json'] or '{}')
    except (TypeError, json.JSONDecodeError):
        dataset_ids = {}
    return {
        'report_job_id': int(row['id']),
        'report_name': str(row['output_file'] or ''),
        'template': str(row['template_name'] or ''), 'technology': str(row['technology'] or '').upper(),
        'scope': str(row['scope'] or 'single'),
        'generated_at': _local_report_date(row['created_at']),
        'dataset_counts': {kind: len(dataset_ids.get(kind, [])) for kind in ('data', 'voice', 'speech')},
        'charts': charts,
    }


def _temporary_chart_preview_context(source: str, identifier: str, chart_index: int) -> tuple[Any, dict[str, list[int]], str, bool, int]:
    """Resolve one persisted chart back to its immutable template definition."""
    if source == 'report':
        row = repository.get_report_run(int(identifier))
        scope = str(row['scope'] or 'single') if row else 'single'
    elif source == 'standalone':
        row = next((item for item in repository.list_report_chart_jobs(limit=None) if str(item['generation'] or '') == identifier), None)
        scope = str(row['scope'] or 'single') if row else 'single'
    else:
        row = None
        scope = 'single'
    if not row:
        raise HTTPException(status_code=404, detail='The selected Chart Set is no longer available.')
    try:
        dataset_ids = json.loads(row['dataset_ids_json'] or '{}')
        selected_ids = {kind: [int(value) for value in dataset_ids.get(kind, [])] for kind in ('data', 'voice', 'speech')}
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail='The selected Chart Set has invalid CDR references.') from exc
    technology = str(row['technology'] or '').strip().lower()
    template_name = str(row['template_name'] or '')
    template = next((item for item in report_catalogue_options(technology) if item['name'] == template_name), None)
    if technology not in TEMPLATE_NAMES or not template:
        raise HTTPException(status_code=404, detail='The Slides Template used by this Chart Set is no longer available.')
    indexed_entries = list(enumerate(load_template_catalogue(template['path'], technology)))
    # Standalone Chart Sets retain the CSV chart-row order. PowerPoint reports
    # render slides numerically, then retain chart order inside each slide.
    # The editor always presents every row sorted by slide. Keep the original
    # row identity while applying those different views so focus_row addresses
    # the exact chart shown in the viewer, including structural rows.
    chart_entries = [(index, entry) for index, entry in indexed_entries if entry.source_kind]
    if source == 'report':
        chart_entries.sort(key=lambda item: (item[1].slide, item[0]))
    if chart_index < 0 or chart_index >= len(chart_entries):
        raise HTTPException(status_code=404, detail='The selected chart definition is no longer available.')
    original_row_index, entry = chart_entries[chart_index]
    editor_entries = sorted(indexed_entries, key=lambda item: (item[1].slide, item[0]))
    template_row_index = next(
        editor_index for editor_index, (source_index, _entry) in enumerate(editor_entries)
        if source_index == original_row_index
    )
    return entry, selected_ids, technology, scope == 'multivendor', template_row_index


def _temporary_chart_definition_changes(editable: dict[str, Any]) -> dict[str, str]:
    """Normalise editable values shared by every Interactive Preview entry point."""
    allowed = {
        'chart_title', 'cdr_source', 'kpi', 'chart_type', 'filters',
        'grouping_rows', 'grouping_columns', 'legend', 'legend_position',
    }
    changes = {key: str(value or '') for key, value in editable.items() if key in allowed}
    if 'legend_position' in changes:
        changes['legend_position'] = parse_legend_position(changes['legend_position'])
    return changes


def _temporary_preview_dataset_ids(editable: dict[str, Any], selected_ids: dict[str, list[int]], source_kind: str) -> list[int]:
    """Resolve an optional dataset selection and constrain it to its CDR type."""
    raw_values = editable.get('dataset_ids')
    if raw_values is None:
        return selected_ids.get(source_kind, [])
    values = raw_values if isinstance(raw_values, list) else re.split(r'\s*(?:,|×|\bx\b)\s*', str(raw_values), flags=re.IGNORECASE)
    try:
        requested = list(dict.fromkeys(int(value) for value in values if str(value).strip()))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='Choose valid processed CDR datasets.') from exc
    available = {
        int(row['id']) for row in repository.list_datasets()
        if row['status'] == 'ready' and str(row['dataset_kind'] or '').casefold() == source_kind
    }
    if not requested or any(dataset_id not in available for dataset_id in requested):
        raise HTTPException(status_code=400, detail=f'Choose one or more processed {source_kind.title()} CDR datasets.')
    return requested


@app.get('/api/reporting/chart-preview/context')
def temporary_chart_preview_context(source: str, identifier: str, chart_index: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    """Return an immutable chart definition for the interactive viewer sandbox."""
    entry, selected_ids, _technology, _multivendor, template_row_index = _temporary_chart_preview_context(source, identifier, chart_index)
    dataset_rows = repository.list_datasets()
    selected_dataset_ids = {value for values in selected_ids.values() for value in values}
    # The controls only need the schemas backing this Chart Set. Inspecting
    # every historic dataset made opening the panel increasingly expensive.
    columns = catalogue_editor_columns(
        (row for row in dataset_rows if int(row['id']) in selected_dataset_ids),
        entry.calculated_dimensions,
    )
    datasets_by_source: dict[str, list[dict[str, Any]]] = {'cdr-data': [], 'cdr-voice': [], 'cdr-speech': []}
    for row in dataset_rows:
        kind = str(row['dataset_kind'] or '').casefold()
        if row['status'] == 'ready' and kind in {'data', 'voice', 'speech'}:
            datasets_by_source[f'cdr-{kind}'].append({'value': str(row['id']), 'label': str(row['file_name'])})
    return JSONResponse({
        'slide': entry.slide, 'chart_title': entry.chart_title, 'template_row_index': template_row_index,
        'source_available': bool(selected_ids.get(entry.source_kind or '')), 'cdr_source': entry.cdr_source,
        'dataset_ids': [str(value) for value in selected_ids.get(entry.source_kind or '', [])],
        'dataset_ids_by_source': {f'cdr-{kind}': [str(value) for value in values] for kind, values in selected_ids.items()},
        'datasets_by_source': datasets_by_source,
        'kpi': entry.kpi, 'chart_type': entry.chart_type, 'filters': entry.filters,
        'grouping_rows': entry.grouping_rows, 'grouping_columns': entry.grouping_columns,
        'legend': entry.legend, 'legend_position': entry.legend_position,
        'columns_by_source': columns,
    })


@app.post('/api/reporting/chart-preview')
async def temporary_chart_preview(request: Request, user: SessionUser = Depends(current_user)) -> Response:
    """Render a transient chart from viewer edits without altering stored output."""
    try:
        payload = await request.json()
        source = str(payload.get('source') or '')
        identifier = str(payload.get('identifier') or '')
        chart_index = int(payload.get('chart_index'))
        entry, selected_ids, technology, multivendor, _template_row_index = _temporary_chart_preview_context(source, identifier, chart_index)
        editable = payload.get('definition') if isinstance(payload.get('definition'), dict) else {}
        if not selected_ids.get(entry.source_kind or ''):
            return Response(content=render_unavailable_source_chart(entry), media_type='image/png', headers={'Cache-Control': 'no-store'})
        entry = replace(entry, **_temporary_chart_definition_changes(editable))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f'Invalid chart preview request: {exc}') from exc
    if not entry.source_kind:
        raise HTTPException(status_code=400, detail='Choose a valid CDR Source.')
    preview_dataset_ids = _temporary_preview_dataset_ids(editable, selected_ids, entry.source_kind)
    selected = _reporting_datasets(preview_dataset_ids, entry.source_kind)
    frame_key = _chart_preview_cache_key('reporting-source-frame', {
        'dataset_ids': preview_dataset_ids,
        'dataset_versions': [(item['id'], item.get('updated_at'), item.get('processed_at'), item.get('normalization_version')) for item in selected],
        'technology': technology,
        'multivendor': multivendor,
        'columns': reporting_query_columns(entry.source_kind, [entry], multivendor),
    })
    def load_frame() -> pd.DataFrame:
        combined = _combined_reporting_frame(selected, technology, [entry], multivendor)
        return ensure_report_vendor_group(combined) if multivendor else combined
    frame = _bounded_preview_frame(CHART_PREVIEW_FRAME_CACHE, frame_key, load_frame, 4)
    filtered = _cached_filtered_chart_frame(frame_key, frame, entry, multivendor)
    try:
        image = render_catalog_chart_preview(filtered, entry, multivendor=multivendor, prefiltered=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=image, media_type='image/png', headers={'Cache-Control': 'no-store'})


def _temporary_chart_preview_hover_targets(payload: dict[str, Any]) -> list[dict[str, object]]:
    """Build preview hover targets without delaying lightweight viewer setup requests."""
    try:
        source = str(payload.get('source') or '')
        identifier = str(payload.get('identifier') or '')
        chart_index = int(payload.get('chart_index'))
        entry, selected_ids, technology, multivendor, _template_row_index = _temporary_chart_preview_context(source, identifier, chart_index)
        editable = payload.get('definition') if isinstance(payload.get('definition'), dict) else {}
        if source == 'standalone' and not editable:
            if not _chart_set_tooltips_enabled(identifier):
                return []
            stored_targets = _stored_chart_hover_targets(identifier, chart_index)
            if stored_targets is not None:
                return stored_targets
        if source == 'report' and not editable:
            if not _report_tooltips_enabled(identifier):
                return []
            stored_targets = _stored_report_hover_targets(identifier, chart_index)
            if stored_targets is not None:
                return stored_targets
        entry = replace(entry, **_temporary_chart_definition_changes(editable))
        preview_dataset_ids = _temporary_preview_dataset_ids(editable, selected_ids, entry.source_kind)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f'Invalid chart hover request: {exc}') from exc
    if not entry.source_kind:
        raise HTTPException(status_code=400, detail='Choose a valid CDR Source.')
    selected = _reporting_datasets(preview_dataset_ids, entry.source_kind)
    frame_key = _chart_preview_cache_key('reporting-source-frame', {
        'dataset_ids': preview_dataset_ids,
        'dataset_versions': [(item['id'], item.get('updated_at'), item.get('processed_at'), item.get('normalization_version')) for item in selected],
        'technology': technology, 'multivendor': multivendor,
        'columns': reporting_query_columns(entry.source_kind, [entry], multivendor),
    })
    def load_frame() -> pd.DataFrame:
        combined = _combined_reporting_frame(selected, technology, [entry], multivendor)
        return ensure_report_vendor_group(combined) if multivendor else combined
    frame = _bounded_preview_frame(CHART_PREVIEW_FRAME_CACHE, frame_key, load_frame, 4)
    filtered = _cached_filtered_chart_frame(frame_key, frame, entry, multivendor)
    targets = catalog_chart_hover_targets(filtered, entry, multivendor=multivendor, prefiltered=True)
    if source == 'standalone' and not editable:
        _store_chart_hover_targets(identifier, chart_index, targets)
    if source == 'report' and not editable:
        _store_report_hover_targets(identifier, chart_index, targets)
    return targets


def _chart_set_tooltips_enabled(generation: str) -> bool:
    """Return whether a saved Chart Set permits semantic hover targets."""
    if not _valid_report_chart_generation(generation):
        return True
    try:
        manifest = json.loads((report_charts_directory() / generation / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return True
    return manifest.get('generate_tooltips') is not False if isinstance(manifest, dict) else True


def _report_tooltips_enabled(report_id: str) -> bool:
    """Return whether a saved PowerPoint report permits semantic hover targets."""
    try:
        row = repository.get_report_run(int(report_id))
        directory = _report_job_charts_directory(row) if row else None
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8')) if directory else {}
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return True
    return manifest.get('generate_tooltips') is not False if isinstance(manifest, dict) else True


def _stored_chart_hover_targets(generation: str, chart_index: int) -> list[dict[str, object]] | None:
    """Read precomputed semantic targets saved beside a generated Chart Set PNG."""
    if not _valid_report_chart_generation(generation):
        return None
    try:
        manifest = json.loads((report_charts_directory() / generation / 'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('hover_targets_version') != HOVER_TARGETS_VERSION:
            return None
        chart = manifest.get('charts', [])[chart_index]
        target_file = str(chart.get('hover_file') or '')
        if not re.fullmatch(r'chart-\d+\.hover\.json', target_file):
            return None
        targets = json.loads((report_charts_directory() / generation / target_file).read_text(encoding='utf-8'))
    except (IndexError, OSError, ValueError, json.JSONDecodeError, TypeError):
        return None
    return targets if isinstance(targets, list) else None


def _stored_report_hover_targets(report_id: str, chart_index: int) -> list[dict[str, object]] | None:
    """Read targets generated with a PowerPoint report chart."""
    try:
        row = repository.get_report_run(int(report_id))
        directory = _report_job_charts_directory(row) if row else None
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8')) if directory else {}
        if manifest.get('hover_targets_version') != HOVER_TARGETS_VERSION:
            return None
        chart = manifest.get('charts', [])[chart_index]
        target_file = str(chart.get('hover_file') or '')
        if not re.fullmatch(r'slide-\d+-chart-\d+\.hover\.json', target_file):
            return None
        targets = json.loads((directory / target_file).read_text(encoding='utf-8'))
    except (IndexError, OSError, ValueError, json.JSONDecodeError, TypeError):
        return None
    return targets if isinstance(targets, list) else None


def _store_chart_hover_targets(generation: str, chart_index: int, targets: list[dict[str, object]]) -> None:
    """Persist the first on-demand target calculation beside its Chart Set PNG."""
    if not _valid_report_chart_generation(generation):
        return
    directory = report_charts_directory() / generation
    try:
        with CHART_PREVIEW_CACHE_LOCK:
            manifest_path = directory / 'manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            chart = manifest.get('charts', [])[chart_index]
            file_name = str(chart.get('file') or '')
            if not re.fullmatch(r'chart-\d+\.png', file_name):
                return
            hover_file = f'{Path(file_name).stem}.hover.json'
            temporary = directory / f'.{hover_file}.tmp'
            temporary.write_text(json.dumps(targets, ensure_ascii=False), encoding='utf-8')
            temporary.replace(directory / hover_file)
            chart['hover_file'] = hover_file
            manifest['hover_targets_version'] = HOVER_TARGETS_VERSION
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    except (IndexError, OSError, ValueError, json.JSONDecodeError, TypeError):
        return


def _store_report_hover_targets(report_id: str, chart_index: int, targets: list[dict[str, object]]) -> None:
    """Replace an obsolete report sidecar with targets matching the current renderer."""
    try:
        row = repository.get_report_run(int(report_id))
        directory = _report_job_charts_directory(row) if row else None
        if directory is None:
            return
        with CHART_PREVIEW_CACHE_LOCK:
            manifest_path = directory / 'manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            chart = manifest.get('charts', [])[chart_index]
            file_name = str(chart.get('file') or '')
            if not re.fullmatch(r'slide-\d+-chart-\d+\.png', file_name):
                return
            hover_file = f'{Path(file_name).stem}.hover.json'
            temporary = directory / f'.{hover_file}.tmp'
            temporary.write_text(json.dumps(targets, ensure_ascii=False), encoding='utf-8')
            temporary.replace(directory / hover_file)
            chart['hover_file'] = hover_file
            manifest['hover_targets_version'] = HOVER_TARGETS_VERSION
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    except (IndexError, OSError, ValueError, json.JSONDecodeError, TypeError):
        return


@app.post('/api/reporting/chart-preview/hover')
async def temporary_chart_preview_hover(request: Request, user: SessionUser = Depends(current_user)) -> JSONResponse:
    """Return semantic chart hit areas for the interactive PNG preview."""
    try:
        payload = await request.json()
    except ClientDisconnect:
        # The browser deliberately aborts superseded hover requests while the
        # user navigates. That is not an application error.
        return Response(status_code=204)
    targets = await run_in_threadpool(_temporary_chart_preview_hover_targets, payload)
    return JSONResponse({'targets': targets})


@app.post('/api/reporting/chart-preview/data')
async def temporary_chart_preview_data(request: Request, user: SessionUser = Depends(current_user)) -> JSONResponse:
    """Return the bounded filtered chart dataset for the viewer sandbox."""
    try:
        payload = await request.json()
        source = str(payload.get('source') or '')
        identifier = str(payload.get('identifier') or '')
        chart_index = int(payload.get('chart_index'))
        entry, selected_ids, technology, multivendor, _template_row_index = _temporary_chart_preview_context(
            source, identifier, chart_index,
        )
        editable = payload.get('definition') if isinstance(payload.get('definition'), dict) else {}
        entry = replace(entry, **_temporary_chart_definition_changes(editable))
        page = max(0, int(payload.get('page', 0)))
        page_size = max(1, min(250, int(payload.get('page_size', 100))))
        raw_column_filters = payload.get('column_filters') if isinstance(payload.get('column_filters'), dict) else {}
        column_filters = {
            str(column): tuple(str(value) for value in values if value is not None)
            for column, values in raw_column_filters.items() if isinstance(values, list)
        }
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f'Invalid chart data request: {exc}') from exc
    if not entry.source_kind:
        raise HTTPException(status_code=400, detail='Choose a valid CDR Source.')
    try:
        preview_dataset_ids = _temporary_preview_dataset_ids(editable, selected_ids, entry.source_kind)
        cache_material = json.dumps({
            'scope': 'report-chart-viewer', 'workspace': str(active_workspace.database_path) if active_workspace else '',
            'source': source, 'identifier': identifier, 'chart_index': chart_index,
            'selected_ids': preview_dataset_ids, 'definition': editable,
        }, sort_keys=True, default=str)
        cache_key = hashlib.sha256(cache_material.encode('utf-8')).hexdigest()
        cached = CHART_PREVIEW_DATA_CACHE.get(cache_key)
        if cached is None:
            selected = _reporting_datasets(preview_dataset_ids, entry.source_kind)
            frame = _combined_reporting_frame(selected, technology, [entry], multivendor)
            if multivendor:
                frame = ensure_report_vendor_group(frame)
            full_preview, base_summary = preview_catalog_chart_data(frame, entry, limit=100_000)
            cached = (full_preview, base_summary)
            CHART_PREVIEW_DATA_CACHE[cache_key] = cached
            while len(CHART_PREVIEW_DATA_CACHE) > 12:
                CHART_PREVIEW_DATA_CACHE.pop(next(iter(CHART_PREVIEW_DATA_CACHE)))
        full_preview, base_summary = cached
        filtered_preview = full_preview
        for column, values in column_filters.items():
            if column in filtered_preview.columns and values:
                accepted = set(values)
                filtered_preview = filtered_preview[filtered_preview[column].map(lambda value: '' if pd.isna(value) else str(value)).isin(accepted)]
        offset = page * page_size
        preview = filtered_preview.iloc[offset:offset + page_size].copy()
        summary = {
            **base_summary,
            'shown_rows': len(preview.index), 'visible_rows': len(filtered_preview.index), 'page_offset': offset,
            'columns': list(preview.columns),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({
        'columns': [str(column) for column in preview.columns],
        'rows': preview.where(pd.notna(preview), '').astype(str).to_dict(orient='records'),
        'summary': {key: value for key, value in summary.items() if key != 'filter_values'},
        'filter_values': summary.get('filter_values', {}),
    })


def _chart_png_zip_response(directory: Path, filename: str) -> FileResponse:
    """Return a temporary ZIP containing every rendered PNG in *directory*."""
    charts = sorted(path for path in directory.glob('*.png') if path.is_file())
    if not charts:
        raise HTTPException(status_code=404, detail='Rendered charts are not available.')
    with tempfile.NamedTemporaryFile(prefix='dashboard-analytic-charts-', suffix='.zip', delete=False) as handle:
        archive_path = Path(handle.name)
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for chart in charts:
            archive.write(chart, chart.name)
    return FileResponse(
        archive_path, filename=filename, media_type='application/zip',
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


def _local_report_date(value: Any) -> str:
    """Format persisted UTC timestamps in the server's local timezone."""
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return raw


def serialize_report_job(row: Any) -> dict[str, Any]:
    """Expose a report job without relying on the mutable active workspace."""
    try:
        dataset_names = json.loads(row['dataset_names_json'] or '{}')
    except (TypeError, json.JSONDecodeError):
        dataset_names = {}
    labels = [
        f"{kind.title()}: {', '.join(str(name) for name in names)}"
        for kind, names in dataset_names.items() if names
    ]
    dataset_groups = [
        {'kind': kind.title(), 'names': [str(name) for name in names]}
        for kind, names in dataset_names.items() if names
    ]
    report_id = int(row['id'])
    status_value = str(row['status'] or 'ready')
    output_available = status_value == 'ready' and _report_job_output_path(row) is not None
    slide_count = int(row['slide_count'] or 0)
    charts_payload = _report_job_charts_payload(row) if output_available else None
    return {
        'id': report_id,
        'date': _local_report_date(row['created_at']),
        'charts_date': _local_report_date(row['finished_at'] or row['created_at']),
        'report_name': str(row['output_file']),
        'datasets': ' · '.join(labels) or 'Historical report',
        'dataset_groups': dataset_groups,
        'template': str(row['template_name'] or '—'),
        'slides': slide_count or None,
        'charts': len(charts_payload.get('charts', [])) if charts_payload else None,
        'type': str(row['technology'] or '').upper() or '—',
        'multivendor': 'Yes' if str(row['scope'] or '').casefold() == 'multivendor' else 'No',
        'scope': 'Multivendor Comparison' if str(row['scope'] or '').casefold() == 'multivendor' else 'Operator Comparison',
        'generated_by': str(row['created_by'] or '—'),
        'status': status_value,
        'progress': int(row['progress'] or 0),
        'error': str(row['last_error'] or ''),
        'download_url': f'/reporting/jobs/{report_id}/download' if output_available else None,
        'open_url': f'/reporting/jobs/{report_id}/open' if output_available else None,
        'charts_url': f'/api/reporting/jobs/{report_id}/charts' if charts_payload else None,
        'charts_download_url': f'/reporting/jobs/{report_id}/charts/download' if charts_payload else None,
        'delete_url': f'/reporting/jobs/{report_id}/delete',
        'stop_url': f'/reporting/jobs/{report_id}/stop' if status_value == 'processing' else None,
        'retry_url': f'/reporting/jobs/{report_id}/retry' if status_value in {'failed', 'stopped', 'ready'} else None,
    }


def serialize_report_chart_job(row: Any) -> dict[str, Any]:
    """Expose an independent background Chart Set job to the Reporting UI."""
    try:
        dataset_names = json.loads(row['dataset_names_json'] or '{}')
    except (TypeError, json.JSONDecodeError):
        dataset_names = {}
    dataset_groups = [
        {'kind': kind.title(), 'names': [str(name) for name in names]}
        for kind, names in dataset_names.items() if names
    ]
    job_id = int(row['id'])
    status_value = str(row['status'] or 'queued')
    generation = str(row['generation'] or '')
    # A ready Chart Set has one canonical generation timestamp: the value in
    # its manifest.  Reuse it in Charts Jobs rather than showing the earlier
    # queue-creation time alongside the completed set.
    chart_set = load_persisted_report_charts(generation) if status_value == 'ready' and generation else None
    return {
        'id': job_id,
        'date': str(chart_set['generated_at']) if chart_set else _local_report_date(row['created_at']),
        'type': str(row['technology'] or '').upper() or '—',
        'template': str(row['template_name'] or '—'),
        'scope': 'Multivendor Comparison' if str(row['scope'] or '').casefold() == 'multivendor' else 'Operator Comparison',
        'dataset_groups': dataset_groups,
        'charts': int(row['chart_count'] or 0) or None,
        'generated_by': str(row['created_by'] or '—'),
        'status': status_value,
        'progress': int(row['progress'] or 0),
        'error': str(row['last_error'] or ''),
        'generation': generation or None,
        'open_url': f'/api/reporting/chart-sets/{generation}' if status_value == 'ready' and generation else None,
        'charts_download_url': f'/reporting/chart-sets/{generation}/download' if chart_set else None,
        'delete_url': f'/reporting/chart-jobs/{job_id}/delete',
        'stop_url': f'/reporting/chart-jobs/{job_id}/stop' if status_value == 'processing' else None,
        'retry_url': f'/reporting/chart-jobs/{job_id}/retry' if status_value in {'failed', 'stopped', 'ready'} else None,
    }


class ReportJobStopped(Exception):
    """Raised in a background worker after its job was stopped or deleted."""


def _ensure_report_job_active(task_repository: Repository, report_id: int, *, chart_job: bool = False) -> None:
    job = task_repository.get_report_chart_job(report_id) if chart_job else task_repository.get_report_run(report_id)
    if job is None or str(job['status'] or '').casefold() == 'stopped':
        raise ReportJobStopped()


def _run_netcheck_report_job(
    report_id: int, task_repository: Repository, selected: dict[str, list[dict[str, Any]]],
    technology: str, multivendor: bool, catalog_entries: list[Any], template: Path,
    destination: Path, username: str, catalogue_name: str, generate_tooltips: bool = True,
) -> None:
    """Serialize every report/chart render for one workspace."""
    workspace_key = str(task_repository.db_path.resolve())
    with REPORT_CHART_JOB_LOCKS_LOCK:
        workspace_lock = REPORT_CHART_JOB_LOCKS.setdefault(workspace_key, Lock())
    with workspace_lock:
        _run_netcheck_report_job_locked(
            report_id, task_repository, selected, technology, multivendor, catalog_entries,
            template, destination, username, catalogue_name, generate_tooltips,
        )


def _run_netcheck_report_job_locked(
    report_id: int, task_repository: Repository, selected: dict[str, list[dict[str, Any]]],
    technology: str, multivendor: bool, catalog_entries: list[Any], template: Path,
    destination: Path, username: str, catalogue_name: str, generate_tooltips: bool = True,
) -> None:
    """Generate a report independently of the request/session that started it."""
    try:
        _ensure_report_job_active(task_repository, report_id)
        task_repository.update_report_job(report_id, status='processing', progress=5, last_error='')
        loaded_kinds: set[str] = set()
        chart_metrics: list[dict[str, Any]] = []
        chart_entries = [entry for entry in catalog_entries if entry.source_kind]
        rendered_count = 0
        def load_frame(kind: str) -> pd.DataFrame:
            _ensure_report_job_active(task_repository, report_id)
            if not selected[kind]:
                frame = pd.DataFrame()
                frame.attrs['report_source_unavailable'] = True
                return frame
            frame = _combined_reporting_frame(selected[kind], technology, catalog_entries, multivendor, task_repository)
            if multivendor:
                frame = ensure_report_vendor_group(frame)
            loaded_kinds.add(kind)
            return frame
        def chart_rendered(entry: Any, source_rows: int, empty: bool) -> None:
            nonlocal rendered_count
            rendered_count += 1
            chart_metrics.append({
                'slide': entry.slide, 'source': entry.cdr_source, 'source_rows': source_rows,
                'empty_placeholder': empty, 'rss_mb': _reporting_memory_mb(),
            })
            task_repository.update_report_job(
                report_id, status='processing', progress=10 + int(rendered_count * 85 / max(len(chart_entries), 1)),
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _ensure_report_job_active(task_repository, report_id)
        task_repository.update_report_job(report_id, status='processing', progress=10)
        render_cdr_report(
            destination, template, None, technology, multivendor, catalog_entries,
            chart_output_dir=destination.parent / 'report-charts',
            frame_loader=load_frame,
            on_chart_rendered=chart_rendered,
            generate_tooltips=generate_tooltips,
        )
        gc.collect()
        _ensure_report_job_active(task_repository, report_id)
        task_repository.update_report_job(report_id, status='ready', progress=100, last_error='', finished=True)
        invalidate_workspace_size_cache(task_repository.db_path.parent)
        task_repository.add_log(username, 'export_netcheck_cdr_report', json.dumps({
            'report_id': report_id,
            'datasets': {kind: [dataset['id'] for dataset in datasets] for kind, datasets in selected.items()},
            'technology': technology,
            'scope': 'multivendor' if multivendor else 'single',
            'slides_templates': catalogue_name,
            'file': destination.name,
            'generate_tooltips': generate_tooltips,
            'chart_metrics': chart_metrics,
        }))
    except ReportJobStopped:
        if destination.parent == _report_job_directory(destination.name):
            shutil.rmtree(destination.parent, ignore_errors=True)
        else:
            destination.unlink(missing_ok=True)
        invalidate_workspace_size_cache(task_repository.db_path.parent)
    except Exception as exc:
        if destination.parent == _report_job_directory(destination.name):
            shutil.rmtree(destination.parent, ignore_errors=True)
        else:
            destination.unlink(missing_ok=True)
        invalidate_workspace_size_cache(task_repository.db_path.parent)
        task_repository.update_report_job(report_id, status='failed', progress=100, last_error=str(exc), finished=True)
        task_repository.add_log(username, 'export_netcheck_cdr_report_failed', json.dumps({
            'report_id': report_id, 'error': str(exc),
        }))


@app.get('/reporting', response_class=HTMLResponse)
def reporting(request: Request, user: SessionUser = Depends(current_user)) -> HTMLResponse:
    if not active_workspace:
        return RedirectResponse('/workspace?workspace_warning=Open+a+workspace+before+using+Reporting.', status_code=status.HTTP_303_SEE_OTHER)
    ready_datasets = [serialize_dataset_row(row) for row in repository.list_datasets() if row['status'] == 'ready']
    chart_job_rows = repository.list_report_chart_jobs(limit=None)
    # A Chart Set is published to disk just before its job is marked ready.
    # Keep that brief in-between state out of the selector after a reload.
    unpublished_generations = {
        str(row['generation']) for row in chart_job_rows
        if str(row['generation'] or '') and str(row['status'] or '').casefold() != 'ready'
    }
    report_chart_sets = [
        chart_set for chart_set in list_persisted_report_chart_sets()
        if str(chart_set['generation']) not in unpublished_generations
    ]
    chart_jobs_by_generation = {
        str(row['generation']): row for row in chart_job_rows if str(row['generation'] or '')
    }
    for chart_set in report_chart_sets:
        if chart_set.get('technology'):
            continue
        job = chart_jobs_by_generation.get(str(chart_set['generation']))
        if job:
            chart_set['technology'] = str(job['technology'] or '').upper()
    report_job_rows = repository.list_report_runs(limit=None)
    report_jobs = [serialize_report_job(row) for row in report_job_rows]
    report_chart_report_sets = [job for job in report_jobs if job.get('charts_url')]
    report_rows_by_id = {int(row['id']): row for row in report_job_rows}
    available_chart_sets = sorted(
        [
            *({'kind': 'report', 'value': report} for report in report_chart_report_sets),
            *({'kind': 'standalone', 'value': chart_set} for chart_set in report_chart_sets),
        ],
        key=lambda item: str(item['value'].get('charts_date') or item['value'].get('generated_at') or item['value'].get('date') or ''),
        reverse=True,
    )
    default_report_charts = None
    if available_chart_sets:
        newest = available_chart_sets[0]
        if newest['kind'] == 'report':
            default_report_charts = _report_job_charts_payload(report_rows_by_id[int(newest['value']['id'])])
        else:
            default_report_charts = load_persisted_report_charts(str(newest['value']['generation']))
    return render_template(request, 'reporting.html', {
        'user': user,
        'data_datasets': [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'data'],
        'voice_datasets': [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'voice'],
        'speech_datasets': [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'speech'],
        'report_catalogues': {technology: report_catalogue_options(technology) for technology in TEMPLATE_NAMES},
        'report_jobs': report_jobs, 'report_chart_report_sets': report_chart_report_sets,
        'report_chart_jobs': [serialize_report_chart_job(row) for row in chart_job_rows],
        'report_chart_sets': report_chart_sets,
        'report_charts': default_report_charts,
        'calculated_dimensions': calculated_dimensions_json(load_workspace_calculated_dimensions()),
    })


def _chart_builder_context(payload: dict[str, Any]) -> tuple[pd.DataFrame, CatalogEntry]:
    """Build an ad-hoc chart from explicitly selected ready CDRs."""
    selected_ids = {int(value) for value in payload.get('dataset_ids', [])}
    if not selected_ids:
        raise HTTPException(status_code=400, detail='Select at least one processed CDR Source.')
    selected_datasets: list[dict[str, Any]] = []
    dataset_columns: dict[int, list[str]] = {}
    for dataset in repository.list_datasets():
        if int(dataset['id']) not in selected_ids or dataset['status'] != 'ready':
            continue
        item = serialize_dataset_row(dataset)
        selected_datasets.append(item)
        dataset_columns[int(dataset['id'])] = repository.list_dataset_row_columns(int(dataset['id']))
    if not selected_datasets:
        raise HTTPException(status_code=400, detail='The selected CDR Sources are not ready.')
    definition = payload.get('definition') if isinstance(payload.get('definition'), dict) else {}
    entry = CatalogEntry(
        slide=1, slide_title='Chart Builder', slide_subtitle='', layout='',
        chart_title=str(definition.get('chart_title') or 'Ad-hoc chart'), cdr_source=str(definition.get('cdr_source') or 'CDR-Data'),
        kpi=str(definition.get('kpi') or ''), chart_type=str(definition.get('chart_type') or '100% Stacked Vertical Bars'),
        legend=str(definition.get('legend') or ''), filters=str(definition.get('filters') or ''),
        grouping_rows=str(definition.get('grouping_rows') or ''), grouping_columns=str(definition.get('grouping_columns') or ''),
        legend_position=parse_legend_position(str(definition.get('legend_position') or 'Top')),
    )
    frame_key = _chart_preview_cache_key('chart-builder-source-frame', {
        'dataset_ids': sorted(selected_ids),
        'dataset_versions': [(item['id'], item.get('updated_at'), item.get('processed_at'), item.get('normalization_version')) for item in selected_datasets],
        'columns': dataset_columns,
    })
    def load_frame() -> pd.DataFrame:
        frames = [
            repository.load_dataset_rows(dataset_id, columns, {})
            for dataset_id, columns in dataset_columns.items() if columns
        ]
        if not frames:
            raise HTTPException(status_code=400, detail='The selected CDR Sources are not ready.')
        return pd.concat(frames, ignore_index=True, sort=False)
    return _bounded_preview_frame(CHART_PREVIEW_FRAME_CACHE, frame_key, load_frame, 4), entry


@app.get('/chart-builder', response_class=HTMLResponse)
def chart_builder(request: Request, user: SessionUser = Depends(current_user)) -> HTMLResponse:
    if not active_workspace:
        return RedirectResponse('/workspace?workspace_warning=Open+a+workspace+before+using+Chart+Builder.', status_code=status.HTTP_303_SEE_OTHER)
    datasets = []
    for row in repository.list_datasets():
        if row['status'] != 'ready':
            continue
        datasets.append({'id': int(row['id']), 'name': str(row['file_name']), 'kind': str(row['dataset_kind']), 'columns': repository.list_dataset_row_columns(int(row['id']))})
    return render_template(request, 'chart_builder.html', {'user': user, 'datasets': datasets})


@app.post('/api/chart-builder/preview')
async def chart_builder_preview(request: Request, user: SessionUser = Depends(current_user)) -> Response:
    payload = await request.json()
    frame, entry = _chart_builder_context(payload)
    try:
        source_key = _chart_preview_cache_key('chart-builder-selection', {'dataset_ids': payload.get('dataset_ids', [])})
        filtered = _cached_filtered_chart_frame(source_key, frame, entry, False)
        return Response(content=render_catalog_chart_preview(filtered, entry, prefiltered=True), media_type='image/png', headers={'Cache-Control': 'no-store'})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/reporting/netcheck-cdr')
def generate_netcheck_cdr_report(
    data_dataset_id: list[int] = Form([]),
    voice_dataset_id: list[int] = Form([]),
    speech_dataset_id: list[int] = Form([]),
    technology: str = Form(...),
    report_scope: str = Form('single'),
    slides_templates: str = Form(''),
    generate_tooltips: bool = Form(True),
    user: SessionUser = Depends(current_user),
) -> JSONResponse:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=400, detail='Choose NSA or SA for the CDR report.')
    if report_scope not in {'single', 'multivendor'}:
        raise HTTPException(status_code=400, detail='Choose a valid report scope.')
    multivendor = report_scope == 'multivendor'
    selected = {
        'data': _optional_reporting_datasets(data_dataset_id, 'data'),
        'voice': _optional_reporting_datasets(voice_dataset_id, 'voice'),
        'speech': _optional_reporting_datasets(speech_dataset_id, 'speech'),
    }
    if not any(selected.values()):
        raise HTTPException(status_code=400, detail='Select at least one Data, Voice or Speech CDR.')
    if multivendor and not all(
        dataset.get('vendor_mapping_applied')
        for datasets in selected.values()
        for dataset in datasets
    ):
        raise HTTPException(status_code=400, detail='Multivendor reporting requires every selected Data, Voice and Speech CDR to have a Workspace Vendor mapping.')
    template = settings.ppt_templates_dir / TEMPLATE_NAMES[technology]
    available_catalogues = {item['identifier']: item for item in report_catalogue_options(technology)}
    selected_catalogue = next((item for item in available_catalogues.values() if item['active']), None)
    if slides_templates:
        catalogue_technology, separator, catalogue_identifier = slides_templates.partition(':')
        if separator != ':' or catalogue_technology != technology or catalogue_identifier not in available_catalogues:
            raise HTTPException(status_code=400, detail='Choose a Slides Template compatible with the selected technology.')
        selected_catalogue = available_catalogues[catalogue_identifier]
    if selected_catalogue is None:
        raise HTTPException(status_code=400, detail=f'No {technology.upper()} Slides Template is available.')
    catalog_path = selected_catalogue['path']
    try:
        catalog_entries = load_template_catalogue(catalog_path, technology)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unable to load the selected {technology.upper()} report template: {exc}") from exc
    generated_at = datetime.now().strftime('%Y%m%d-%H%M%S')
    scope_token = 'vendor-comparison' if multivendor else 'operator-comparison'
    file_name = f"{generated_at}_NetCheck_CDR_{technology.upper()}_{scope_token}.pptx"
    report_dir = _report_job_directory(file_name)
    destination = safe_join(report_dir, file_name)
    dataset_ids = {kind: [int(dataset['id']) for dataset in datasets] for kind, datasets in selected.items()}
    report_id = repository.create_report_job(
        report_type='netcheck_cdr', technology=technology, scope=report_scope,
        data_dataset_id=selected['data'][0]['id'] if selected['data'] else None,
        voice_dataset_id=selected['voice'][0]['id'] if selected['voice'] else None,
        speech_dataset_id=selected['speech'][0]['id'] if selected['speech'] else None,
        dataset_ids=dataset_ids, dataset_names=_report_dataset_names(selected),
        slide_count=len({entry.slide for entry in catalog_entries}), template_name=selected_catalogue['name'],
        output_file=file_name, output_path=destination, created_by=user.username,
        generate_tooltips=generate_tooltips,
    )
    task_repository = Repository(Path(repository.db_path))
    Thread(
        target=_run_netcheck_report_job,
        args=(report_id, task_repository, selected, technology, multivendor, catalog_entries, template, destination, user.username, selected_catalogue['name'], generate_tooltips),
        name=f'report-{report_id}', daemon=True,
    ).start()
    repository.add_log(user.username, 'generate_powerpoint_report_requested', json.dumps({
        'report_id': report_id, 'technology': technology, 'scope': report_scope,
        'template': selected_catalogue['name'], 'datasets': dataset_ids,
        'generate_tooltips': generate_tooltips,
    }))
    return JSONResponse({'job_id': report_id, 'status': 'queued'}, status_code=status.HTTP_202_ACCEPTED)


@app.post('/reporting/netcheck-cdr/charts')
def generate_netcheck_cdr_charts(
    data_dataset_id: list[int] = Form([]),
    voice_dataset_id: list[int] = Form([]),
    speech_dataset_id: list[int] = Form([]),
    technology: str = Form(...),
    report_scope: str = Form('single'),
    slides_templates: str = Form(''),
    generate_tooltips: bool = Form(True),
    user: SessionUser = Depends(current_user),
) -> JSONResponse:
    """Queue every automated chart in the selected Slides Template."""
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=400, detail='Choose NSA or SA for the CDR report.')
    if report_scope not in {'single', 'multivendor'}:
        raise HTTPException(status_code=400, detail='Choose a valid report scope.')
    multivendor = report_scope == 'multivendor'
    selected = {
        'data': _optional_reporting_datasets(data_dataset_id, 'data'),
        'voice': _optional_reporting_datasets(voice_dataset_id, 'voice'),
        'speech': _optional_reporting_datasets(speech_dataset_id, 'speech'),
    }
    if not any(selected.values()):
        raise HTTPException(status_code=400, detail='Select at least one Data, Voice or Speech CDR.')
    if multivendor and not all(
        dataset.get('vendor_mapping_applied')
        for datasets in selected.values()
        for dataset in datasets
    ):
        raise HTTPException(status_code=400, detail='Multivendor reporting requires every selected Data, Voice and Speech CDR to have a Workspace Vendor mapping.')
    available_catalogues = {item['identifier']: item for item in report_catalogue_options(technology)}
    selected_catalogue = next((item for item in available_catalogues.values() if item['active']), None)
    if slides_templates:
        catalogue_technology, separator, catalogue_identifier = slides_templates.partition(':')
        if separator != ':' or catalogue_technology != technology or catalogue_identifier not in available_catalogues:
            raise HTTPException(status_code=400, detail='Choose a Slides Template compatible with the selected technology.')
        selected_catalogue = available_catalogues[catalogue_identifier]
    if selected_catalogue is None:
        raise HTTPException(status_code=400, detail=f'No {technology.upper()} Slides Template is available.')
    dataset_ids = {kind: [int(dataset['id']) for dataset in datasets] for kind, datasets in selected.items()}
    job_id = repository.create_report_chart_job(
        technology=technology, scope=report_scope, dataset_ids=dataset_ids,
        dataset_names=_report_dataset_names(selected), template_name=selected_catalogue['name'], created_by=user.username,
        generate_tooltips=generate_tooltips,
    )
    task_repository = Repository(Path(repository.db_path), repository.global_db_path)
    output_dir = Path(settings.output_dir)
    repository.add_log(user.username, 'chart_set_generation_requested', json.dumps({
        'job_id': job_id, 'technology': technology, 'scope': report_scope, 'template': selected_catalogue['name'],
        'datasets': dataset_ids,
        'generate_tooltips': generate_tooltips,
    }))
    Thread(
        target=_run_report_chart_job,
        args=(job_id, task_repository, dataset_ids, technology, report_scope, selected_catalogue['name'], output_dir, user.username, generate_tooltips),
        name=f'report-charts-{job_id}', daemon=True,
    ).start()
    return JSONResponse({'job_id': job_id, 'status': 'queued'}, status_code=status.HTTP_202_ACCEPTED)


def _run_report_chart_job(
    job_id: int, task_repository: Repository, dataset_ids: dict[str, list[int]], technology: str,
    report_scope: str, template_name: str, output_dir: Path, username: str, generate_tooltips: bool = True,
) -> None:
    """Render one persisted Chart Set without holding the HTTP request open."""
    workspace_key = str(task_repository.db_path.resolve())
    with REPORT_CHART_JOB_LOCKS_LOCK:
        workspace_lock = REPORT_CHART_JOB_LOCKS.setdefault(workspace_key, Lock())
    with workspace_lock:
        report_charts: dict[str, Any] | None = None
        try:
            _ensure_report_job_active(task_repository, job_id, chart_job=True)
            task_repository.update_report_chart_job(job_id, status='processing', progress=5, last_error='')
            selected = {
                kind: _optional_reporting_datasets([int(value) for value in dataset_ids.get(kind, [])], kind, task_repository)
                for kind in ('data', 'voice', 'speech')
            }
            if not any(selected.values()):
                raise ValueError('Select at least one Data, Voice or Speech CDR.')
            multivendor = report_scope == 'multivendor'
            if multivendor and not all(dataset.get('vendor_mapping_applied') for datasets in selected.values() for dataset in datasets):
                raise ValueError('Multivendor reporting requires every selected Data, Voice and Speech CDR to have a Workspace Vendor mapping.')
            template_root = task_repository.db_path.parent / 'slides-templates'
            metadata = next((row for row in task_repository.list_report_templates(technology)
                             if row['name'] == template_name), None)
            area = 'default' if metadata and metadata['is_default'] else 'library'
            template_path = template_root / area / technology / template_filename(template_name)
            if not metadata or not template_path.is_file():
                raise ValueError('The Slides Template used by this Chart Set is no longer available.')
            catalog_entries = load_template_catalogue(template_path, technology, task_repository=task_repository)
            _ensure_report_job_active(task_repository, job_id, chart_job=True)
            task_repository.update_report_chart_job(job_id, status='processing', progress=12)
            chart_entries = [entry for entry in catalog_entries if entry.source_kind]
            if not chart_entries:
                raise ValueError('The selected Slides Template does not contain automated CDR charts.')
            def rendered_charts() -> Iterable[tuple[dict[str, Any], bytes]]:
                rendered = 0
                empty_charts: list[dict[str, Any]] = []
                chart_metrics: list[dict[str, Any]] = []
                hover_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chart-hover') if generate_tooltips else None
                try:
                    for kind in ('data', 'voice', 'speech'):
                        entries = [
                            (order, entry) for order, entry in enumerate(chart_entries)
                            if entry.source_kind == kind
                        ]
                        if not entries:
                            continue
                        _ensure_report_job_active(task_repository, job_id, chart_job=True)
                        if not selected[kind]:
                            for order, entry in entries:
                                image = render_unavailable_source_chart(entry)
                                rendered += 1
                                chart_metrics.append({
                                    'slide': entry.slide, 'source': entry.cdr_source, 'source_rows': 0,
                                    'empty_placeholder': True, 'unavailable_source': True, 'rss_mb': _reporting_memory_mb(),
                                })
                                task_repository.update_report_chart_job(
                                    job_id, status='processing', progress=12 + int(rendered * 83 / len(chart_entries)),
                                )
                                yield ({
                                    'order': order, 'slide': entry.slide,
                                    'title': entry.chart_title or entry.slide_title or f'Slide {entry.slide}',
                                    'source': entry.cdr_source, 'chart_type': entry.chart_type,
                                    'hover_targets': [],
                                }, image)
                            continue
                        frame = _combined_reporting_frame(selected[kind], technology, catalog_entries, multivendor, task_repository)
                        if multivendor:
                            frame = ensure_report_vendor_group(frame)
                        task_repository.update_report_chart_job(job_id, status='processing', progress=12 + int(rendered * 83 / len(chart_entries)))
                        for order, entry in entries:
                            _ensure_report_job_active(task_repository, job_id, chart_job=True)
                            try:
                                hover_future = hover_executor.submit(
                                    catalog_chart_hover_targets, frame, entry, multivendor=multivendor,
                                ) if hover_executor else None
                                image = render_catalog_chart_preview(frame, entry, multivendor=multivendor)
                            except Exception as exc:
                                chart_name = entry.chart_title or entry.slide_title or 'Untitled chart'
                                raise ValueError(f"Slide {entry.slide}, chart '{chart_name}': {exc}") from exc
                            for _attempt in range(2):
                                if not is_empty_catalog_chart(image, entry):
                                    break
                                # Rebuild this CDR frame before retrying.  A retry
                                # against the same pressured DataFrame could only
                                # reproduce the same empty placeholder.
                                del image
                                del frame
                                gc.collect()
                                frame = _combined_reporting_frame(selected[kind], technology, catalog_entries, multivendor, task_repository)
                                if multivendor:
                                    frame = ensure_report_vendor_group(frame)
                                image = render_catalog_chart_preview(frame, entry, multivendor=multivendor)
                            if is_empty_catalog_chart(image, entry):
                                empty_charts.append({'slide': entry.slide, 'source': entry.cdr_source, 'source_rows': len(frame.index)})
                            chart_metrics.append({
                                'slide': entry.slide, 'source': entry.cdr_source, 'source_rows': len(frame.index),
                                'empty_placeholder': is_empty_catalog_chart(image, entry), 'rss_mb': _reporting_memory_mb(),
                            })
                            task_repository.update_report_chart_job(
                                job_id, status='processing', progress=12 + int((rendered + .5) * 83 / len(chart_entries)),
                            )
                            try:
                                hover_targets = hover_future.result() if hover_future else None
                            except Exception as exc:
                                chart_name = entry.chart_title or entry.slide_title or 'Untitled chart'
                                raise ValueError(f"Slide {entry.slide}, chart '{chart_name}' tooltip generation: {exc}") from exc
                            rendered += 1
                            task_repository.update_report_chart_job(
                                job_id, status='processing', progress=12 + int(rendered * 83 / len(chart_entries)),
                            )
                            yield ({
                                'order': order,
                                'slide': entry.slide,
                                'title': entry.chart_title or entry.slide_title or f'Slide {entry.slide}',
                                'source': entry.cdr_source,
                                'chart_type': entry.chart_type,
                                **({'hover_targets': hover_targets} if isinstance(hover_targets, list) else {}),
                            }, image)
                        del frame
                        gc.collect()
                finally:
                    if hover_executor:
                        hover_executor.shutdown(wait=True)
                if empty_charts:
                    task_repository.add_log(username, 'chart_set_rendering_warning', json.dumps({
                        'job_id': job_id, 'executed_by': 'system', 'charts': empty_charts,
                    }))
                task_repository.add_log(username, 'chart_set_rendering_completed', json.dumps({
                    'job_id': job_id, 'executed_by': 'system', 'charts': chart_metrics,
                }))
            _ensure_report_job_active(task_repository, job_id, chart_job=True)
            report_charts = persist_report_charts(
                template_name, report_scope, rendered_charts(),
                {kind: len(datasets) for kind, datasets in selected.items()}, output_dir,
                before_publish=lambda generation: task_repository.update_report_chart_job(
                    job_id, status='processing', generation=generation,
                ),
                generate_tooltips=generate_tooltips,
                technology=technology,
            )
            _ensure_report_job_active(task_repository, job_id, chart_job=True)
            task_repository.update_report_chart_job(
                job_id, status='ready', progress=100, last_error='', chart_count=len(chart_entries),
                generation=str(report_charts['generation']), finished=True,
            )
            invalidate_workspace_size_cache(task_repository.db_path.parent)
            task_repository.add_log(username, 'chart_set_published', json.dumps({
                'job_id': job_id, 'executed_by': 'system', 'generation': report_charts['generation'], 'technology': technology,
                'scope': report_scope, 'template': template_name, 'charts': len(chart_entries),
            }))
        except ReportJobStopped:
            if report_charts:
                shutil.rmtree(report_charts_directory(output_dir) / str(report_charts['generation']), ignore_errors=True)
            invalidate_workspace_size_cache(task_repository.db_path.parent)
        except Exception as exc:
            task_repository.add_log(username, 'chart_set_generation_failed', json.dumps({
                'job_id': job_id, 'executed_by': 'system', 'error': str(exc),
            }))
            task_repository.update_report_chart_job(job_id, status='failed', progress=100, last_error=str(exc), finished=True)
            invalidate_workspace_size_cache(task_repository.db_path.parent)
            invalidate_workspace_size_cache(task_repository.db_path.parent)


def report_charts_directory(output_dir: Path | None = None) -> Path:
    """Return the active workspace directory containing timestamped chart sets."""
    return Path(output_dir or settings.output_dir) / 'charts'


def _migrate_report_charts_root(output_dir: Path | None = None) -> None:
    """Move pre-v0.2.1 Chart Sets from output/report-charts to output/charts."""
    root = Path(output_dir or settings.output_dir)
    legacy = root / 'report-charts'
    destination = report_charts_directory(output_dir)
    if not legacy.is_dir() or legacy == destination:
        return
    destination.mkdir(parents=True, exist_ok=True)
    for child in legacy.iterdir():
        target = destination / child.name
        if target.exists():
            if child.is_dir():
                suffix = 2
                while (destination / f'{child.name}-{suffix}').exists():
                    suffix += 1
                target = destination / f'{child.name}-{suffix}'
            else:
                child.unlink(missing_ok=True)
                continue
        child.replace(target)
    legacy.rmdir()


def _valid_report_chart_generation(value: str) -> bool:
    return bool(re.fullmatch(r'\d{8}-\d{6}(?:-\d+)?', value))


def _report_chart_payload(manifest: dict[str, Any], generation: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    directory = report_charts_directory(output_dir)
    if not _valid_report_chart_generation(generation) or str(manifest.get('generation') or '') != generation:
        return None
    charts: list[dict[str, Any]] = []
    for item in manifest.get('charts', []):
        if not isinstance(item, dict):
            continue
        file_name = str(item.get('file') or '')
        if not re.fullmatch(r'chart-\d+\.png', file_name) or not (directory / generation / file_name).is_file():
            return None
        charts.append({
            'slide': item.get('slide'),
            'title': str(item.get('title') or ''),
            'source': str(item.get('source') or ''),
            'chart_type': str(item.get('chart_type') or ''),
            'image_url': f'/reporting/charts/{generation}/{file_name}?v={manifest.get("generated_at", "")}',
        })
    if not charts:
        return None
    return {
        'generation': generation,
        'template': str(manifest.get('template') or ''),
        'technology': str(manifest.get('technology') or '').upper(),
        'scope': str(manifest.get('scope') or 'single'),
        'dataset_counts': _report_chart_dataset_counts(manifest.get('dataset_counts')),
        'generated_at': format_local_timestamp(manifest.get('generated_at')),
        'charts': charts,
    }


def _report_chart_dataset_counts(value: Any) -> dict[str, int]:
    """Return safe per-source CDR counts from a Report Charts manifest."""
    source = value if isinstance(value, dict) else {}
    counts: dict[str, int] = {}
    for kind in ('data', 'voice', 'speech'):
        try:
            counts[kind] = max(0, int(source.get(kind, 0)))
        except (TypeError, ValueError):
            counts[kind] = 0
    return counts


def _migrate_legacy_report_charts(output_dir: Path | None = None) -> None:
    """Move the pre-library latest-set layout into its timestamped directory once."""
    directory = report_charts_directory(output_dir)
    manifest_path = directory / 'manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return
    generation = str(manifest.get('generation') or '')
    if not isinstance(manifest, dict) or not _valid_report_chart_generation(generation):
        return
    target = directory / generation
    suffix = 2
    while target.exists():
        target = directory / f'{generation}-{suffix}'
        suffix += 1
    target.mkdir(parents=True)
    manifest['generation'] = target.name
    for item in manifest.get('charts', []):
        file_name = str(item.get('file') or '') if isinstance(item, dict) else ''
        if re.fullmatch(r'chart-\d+\.png', file_name) and (directory / file_name).is_file():
            (directory / file_name).replace(target / file_name)
    manifest_path.unlink(missing_ok=True)
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')


def load_persisted_report_charts(generation: str) -> dict[str, Any] | None:
    """Load one complete timestamped chart set from the active workspace."""
    if not _valid_report_chart_generation(generation):
        return None
    manifest_path = report_charts_directory() / generation / 'manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return _report_chart_payload(manifest, generation) if isinstance(manifest, dict) else None


def list_persisted_report_chart_sets() -> list[dict[str, Any]]:
    """List valid saved chart sets, newest first, after migrating the old layout."""
    _migrate_report_charts_root()
    _migrate_legacy_report_charts()
    directory = report_charts_directory()
    if not directory.is_dir():
        return []
    sets: list[dict[str, Any]] = []
    for child in directory.iterdir():
        if not child.is_dir() or not _valid_report_chart_generation(child.name):
            continue
        payload = load_persisted_report_charts(child.name)
        if payload:
            sets.append({
                'generation': child.name,
                'template': str(payload['template']),
                'technology': str(payload.get('technology') or ''),
                'scope': str(payload['scope']),
                'dataset_counts': payload['dataset_counts'],
                'generated_at': str(payload['generated_at']),
            })
    return sorted(sets, key=lambda item: (item['generated_at'], item['generation']), reverse=True)


def persist_report_charts(
    template_name: str,
    scope: str,
    rendered_charts: Iterable[tuple[dict[str, Any], bytes]],
    dataset_counts: dict[str, int],
    output_dir: Path | None = None,
    before_publish: Callable[[str], None] | None = None,
    generate_tooltips: bool = True,
    technology: str = '',
) -> dict[str, Any]:
    """Persist a new timestamped Chart Set directly in its final directory."""
    _migrate_report_charts_root(output_dir)
    destination = report_charts_directory(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_report_charts(output_dir)
    # Versions before v0.2.2 could leave hidden staging directories behind
    # after a worker stopped. Only remove old remnants, since a recent one may
    # still belong to a worker started by another application process.
    stale_before = datetime.now().timestamp() - 6 * 60 * 60
    for child in destination.glob('.report-charts-*'):
        try:
            if child.is_dir() and child.stat().st_mtime < stale_before:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue
    generated_at = datetime.now().astimezone()
    generation = generated_at.strftime('%Y%m%d-%H%M%S')
    suffix = 2
    target = destination / generation
    while target.exists():
        target = destination / f'{generation}-{suffix}'
        suffix += 1
    target.mkdir(parents=True)
    if before_publish:
        before_publish(target.name)
    try:
        manifest_charts: list[tuple[int, dict[str, Any]]] = []
        used_indexes: set[int] = set()
        for fallback_index, (chart, image) in enumerate(rendered_charts, start=1):
            try:
                chart_index = int(chart.get('order', fallback_index - 1)) + 1
            except (TypeError, ValueError):
                chart_index = fallback_index
            if chart_index < 1 or chart_index in used_indexes:
                chart_index = fallback_index
                while chart_index in used_indexes:
                    chart_index += 1
            used_indexes.add(chart_index)
            file_name = f'chart-{chart_index:03d}.png'
            (target / file_name).write_bytes(image)
            hover_targets = chart.get('hover_targets')
            metadata = {key: value for key, value in chart.items() if key not in {'order', 'hover_targets'}} | {'file': file_name}
            if isinstance(hover_targets, list):
                hover_file = f'chart-{chart_index:03d}.hover.json'
                (target / hover_file).write_text(json.dumps(hover_targets, ensure_ascii=False), encoding='utf-8')
                metadata['hover_file'] = hover_file
            manifest_charts.append((chart_index, metadata))
        manifest_charts.sort(key=lambda item: item[0])
        manifest = {
            'template': template_name,
            'technology': technology.strip().upper(),
            'scope': scope,
            'dataset_counts': _report_chart_dataset_counts(dataset_counts),
            'generation': target.name,
            'generated_at': generated_at.isoformat(timespec='seconds'),
            'generate_tooltips': generate_tooltips,
            'hover_targets_version': HOVER_TARGETS_VERSION,
            'charts': [chart for _, chart in manifest_charts],
        }
        # The manifest is the completion marker consumed by selectors. Write
        # it last so an in-progress generation is never offered as ready.
        (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    payload = _report_chart_payload(manifest, target.name, output_dir)
    if payload is None:
        raise ValueError('Unable to save generated report charts.')
    return payload


@app.get('/reporting/charts/{generation}/{chart_file}')
def report_chart_image(generation: str, chart_file: str, user: SessionUser = Depends(current_user)) -> FileResponse:
    if not _valid_report_chart_generation(generation) or not re.fullmatch(r'chart-\d+\.png', chart_file):
        raise HTTPException(status_code=404, detail='Chart not found.')
    chart_path = safe_join(report_charts_directory() / generation, chart_file)
    if not chart_path.is_file():
        raise HTTPException(status_code=404, detail='Chart not found.')
    return FileResponse(chart_path, media_type='image/png')


@app.get('/reporting/chart-sets/{generation}/download')
def download_report_chart_set(generation: str, user: SessionUser = Depends(current_user)) -> FileResponse:
    """Download every PNG belonging to one standalone Chart Set."""
    if not _valid_report_chart_generation(generation) or load_persisted_report_charts(generation) is None:
        raise HTTPException(status_code=404, detail='Chart set not found.')
    directory = safe_join(report_charts_directory(), generation)
    return _chart_png_zip_response(directory, f'Chart_Set_{generation}.zip')


@app.get('/api/reporting/chart-sets/{generation}')
def report_chart_set(generation: str, user: SessionUser = Depends(current_user)) -> JSONResponse:
    payload = load_persisted_report_charts(generation)
    if payload is None:
        raise HTTPException(status_code=404, detail='Chart set not found.')
    return JSONResponse(payload)


@app.post('/reporting/chart-sets/delete-all')
def delete_all_report_chart_sets(user: SessionUser = Depends(admin_user)) -> JSONResponse:
    """Remove every standalone Chart Set and every Charts Job row."""
    chart_sets = list_persisted_report_chart_sets()
    charts_root = report_charts_directory()
    if charts_root.is_dir():
        # Clear valid, incomplete and legacy/unregistered set directories.
        shutil.rmtree(charts_root)
    charts_root.mkdir(parents=True, exist_ok=True)
    jobs = repository.list_report_chart_jobs(limit=None)
    removed_jobs = sum(repository.delete_report_chart_job(int(job['id'])) is not None for job in jobs)
    invalidate_workspace_size_cache()
    repository.add_log(user.username, 'delete_all_report_chart_sets', json.dumps({'count': len(chart_sets), 'jobs': removed_jobs}))
    return JSONResponse({'chart_sets': [], 'deleted_jobs': removed_jobs})


@app.post('/reporting/chart-sets/{generation}/delete')
def delete_report_chart_set(generation: str, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    if not _valid_report_chart_generation(generation):
        raise HTTPException(status_code=404, detail='Chart set not found.')
    directory = safe_join(report_charts_directory(), generation)
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail='Chart set not found.')
    shutil.rmtree(directory)
    removed_jobs = repository.delete_report_chart_jobs_for_generations([generation])
    invalidate_workspace_size_cache()
    repository.add_log(user.username, 'delete_report_chart_set', json.dumps({'generation': generation, 'jobs': removed_jobs}))
    return JSONResponse({'chart_sets': list_persisted_report_chart_sets()})


@app.get('/api/reporting/chart-jobs')
def report_chart_jobs(user: SessionUser = Depends(current_user)) -> JSONResponse:
    return JSONResponse({'jobs': [serialize_report_chart_job(row) for row in repository.list_report_chart_jobs(limit=None)]})


@app.post('/reporting/chart-jobs/{job_id}/delete')
def delete_report_chart_job(job_id: int, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    job = repository.get_report_chart_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Report Charts job not found.')
    if str(job['status'] or '').casefold() == 'processing':
        raise HTTPException(status_code=409, detail='A running Report Charts job cannot be deleted.')
    generation = str(job['generation'] or '')
    if generation and _valid_report_chart_generation(generation):
        directory = safe_join(report_charts_directory(), generation)
        if directory.is_dir():
            shutil.rmtree(directory)
    repository.delete_report_chart_job(job_id)
    invalidate_workspace_size_cache()
    repository.add_log(user.username, 'delete_report_chart_job', json.dumps({'job_id': job_id}))
    return JSONResponse({'deleted': job_id, 'generation': generation or None})


@app.post('/reporting/chart-jobs/{job_id}/stop')
def stop_report_chart_job(job_id: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    if not repository.stop_report_chart_job(job_id):
        raise HTTPException(status_code=409, detail='Only processing Chart Set jobs can be stopped.')
    repository.add_log(user.username, 'stop_report_chart_job', json.dumps({'job_id': job_id}))
    return JSONResponse({'stopped': job_id})


@app.post('/reporting/chart-jobs/{job_id}/retry')
def retry_report_chart_job(job_id: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before retrying Report Charts.')
    previous = repository.get_report_chart_job(job_id)
    if not previous:
        raise HTTPException(status_code=404, detail='Report Charts job not found.')
    previous_status = str(previous['status'] or '').casefold()
    if previous_status not in {'failed', 'stopped', 'ready'}:
        raise HTTPException(status_code=400, detail='Only failed, stopped or ready Report Charts jobs can be relaunched.')
    try:
        dataset_ids = json.loads(previous['dataset_ids_json'] or '{}')
        normalized_ids = {kind: [int(value) for value in dataset_ids.get(kind, [])] for kind in ('data', 'voice', 'speech')}
        if not any(normalized_ids.values()):
            raise HTTPException(status_code=400, detail='The Chart Set job does not contain any selected CDR.')
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail='The Chart Set job does not contain a valid dataset selection.') from exc
    technology = str(previous['technology'] or '').strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=400, detail='The Chart Set job has an unsupported technology.')
    template_name = str(previous['template_name'] or '')
    if not any(option['name'] == template_name for option in report_catalogue_options(technology)):
        raise HTTPException(status_code=400, detail='The Slides Template used by this Chart Set is no longer available.')
    generation = str(previous['generation'] or '')
    if previous_status == 'ready' and generation and _valid_report_chart_generation(generation):
        # A completed job owns this exact Chart Set. Remove it before reuse so
        # a relaunch never retains PNGs or a manifest from the prior run.
        shutil.rmtree(safe_join(report_charts_directory(), generation), ignore_errors=True)
        invalidate_workspace_size_cache()
    if not repository.retry_report_chart_job(job_id):
        raise HTTPException(status_code=409, detail='This Chart Set job is no longer available for retry.')
    task_repository = Repository(Path(repository.db_path), repository.global_db_path)
    output_dir = Path(settings.output_dir)
    generate_tooltips = bool(previous['generate_tooltips'])
    Thread(
        target=_run_report_chart_job,
        args=(job_id, task_repository, normalized_ids, technology, str(previous['scope'] or 'single'), template_name, output_dir, user.username, generate_tooltips),
        name=f'report-charts-{job_id}', daemon=True,
    ).start()
    repository.add_log(user.username, 'retry_report_chart_job', json.dumps({
        'job_id': job_id, 'reused': True, 'relaunched': previous_status == 'ready',
        'generate_tooltips': generate_tooltips,
    }))
    return JSONResponse({'job_id': job_id, 'status': 'queued'}, status_code=status.HTTP_202_ACCEPTED)


@app.get('/api/reporting/jobs')
def reporting_jobs(user: SessionUser = Depends(current_user)) -> JSONResponse:
    return JSONResponse({'jobs': [serialize_report_job(row) for row in repository.list_report_runs(limit=None)]})


def _report_job_file(report_id: int) -> tuple[dict[str, Any], Path]:
    report = repository.get_report_run(report_id)
    if not report:
        raise HTTPException(status_code=404, detail='Report job not found.')
    payload = serialize_report_job(report)
    if payload['status'] != 'ready':
        raise HTTPException(status_code=409, detail='The report is still being generated.')
    path = _report_job_output_path(report)
    if path is None:
        raise HTTPException(status_code=404, detail='The generated report file is no longer available.')
    return payload, path


@app.get('/reporting/jobs/{report_id}/download')
def download_report_job(report_id: int, user: SessionUser = Depends(current_user)) -> FileResponse:
    payload, path = _report_job_file(report_id)
    return FileResponse(path, filename=payload['report_name'], media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation')


@app.get('/reporting/jobs/{report_id}/open')
def open_report_job(report_id: int, user: SessionUser = Depends(current_user)) -> FileResponse:
    payload, path = _report_job_file(report_id)
    return FileResponse(path, filename=payload['report_name'], media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation', content_disposition_type='inline')


@app.get('/api/reporting/jobs/{report_id}/charts')
def report_job_charts(report_id: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    report = repository.get_report_run(report_id)
    payload = _report_job_charts_payload(report) if report else None
    if payload is None:
        raise HTTPException(status_code=404, detail='Rendered report charts are not available.')
    return JSONResponse(payload)


@app.get('/reporting/jobs/{report_id}/charts/download')
def download_report_job_charts(report_id: int, user: SessionUser = Depends(current_user)) -> FileResponse:
    """Download the PNG charts rendered while generating one PowerPoint report."""
    report = repository.get_report_run(report_id)
    directory = _report_job_charts_directory(report) if report else None
    if directory is None or _report_job_charts_payload(report) is None:
        raise HTTPException(status_code=404, detail='Rendered report charts are not available.')
    report_name = Path(str(report['output_file'] or 'report')).stem
    return _chart_png_zip_response(directory, f'{report_name}_charts.zip')


@app.get('/reporting/jobs/{report_id}/charts/{chart_file}')
def report_job_chart_image(report_id: int, chart_file: str, user: SessionUser = Depends(current_user)) -> FileResponse:
    if not re.fullmatch(r'slide-\d+-chart-\d+\.png', chart_file):
        raise HTTPException(status_code=404, detail='Chart not found.')
    report = repository.get_report_run(report_id)
    directory = _report_job_charts_directory(report) if report else None
    if directory is None:
        raise HTTPException(status_code=404, detail='Chart not found.')
    chart_path = safe_join(directory, chart_file)
    if not chart_path.is_file():
        raise HTTPException(status_code=404, detail='Chart not found.')
    return FileResponse(chart_path, media_type='image/png')


@app.post('/reporting/jobs/{report_id}/charts/delete')
def delete_report_job_charts(report_id: int, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    """Delete only the rendered-chart folder belonging to one report."""
    report = repository.get_report_run(report_id)
    directory = _report_job_charts_directory(report) if report else None
    if directory is None:
        raise HTTPException(status_code=404, detail='Rendered report charts are not available.')
    shutil.rmtree(directory)
    invalidate_workspace_size_cache()
    repository.add_log(user.username, 'delete_report_job_charts', json.dumps({'report_id': report_id}))
    return JSONResponse({'deleted': report_id})


@app.post('/reporting/jobs/{report_id}/delete')
def delete_report_job(report_id: int, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    report = repository.delete_report_run(report_id)
    if not report:
        raise HTTPException(status_code=404, detail='Report job not found.')
    _delete_report_job_artifacts(report)
    invalidate_workspace_size_cache()
    return JSONResponse({'deleted': report_id})


@app.post('/reporting/jobs/{report_id}/stop')
def stop_report_job(report_id: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    if not repository.stop_report_job(report_id):
        raise HTTPException(status_code=409, detail='Only processing report jobs can be stopped.')
    repository.add_log(user.username, 'stop_report_job', json.dumps({'report_id': report_id}))
    return JSONResponse({'stopped': report_id})


@app.post('/reporting/jobs/delete-all')
def delete_all_report_jobs(user: SessionUser = Depends(admin_user)) -> JSONResponse:
    """Delete every persisted PowerPoint report job and its generated file."""
    reports = repository.list_report_runs(limit=None)
    for report in reports:
        deleted = repository.delete_report_run(int(report['id']))
        if deleted:
            _delete_report_job_artifacts(deleted)
    # Also remove incomplete and orphaned report directories which no longer
    # have a usable database row or PowerPoint file.
    reports_root = Path(settings.output_dir) / 'reports'
    if reports_root.is_dir():
        shutil.rmtree(reports_root)
    reports_root.mkdir(parents=True, exist_ok=True)
    invalidate_workspace_size_cache()
    repository.add_log(user.username, 'delete_all_report_jobs', json.dumps({'count': len(reports)}))
    return JSONResponse({'deleted': len(reports)})


@app.post('/reporting/jobs/{report_id}/retry')
def retry_report_job(report_id: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before retrying a report.')
    previous = repository.get_report_run(report_id)
    if not previous:
        raise HTTPException(status_code=404, detail='Report job not found.')
    if str(previous['status'] or '').casefold() not in {'failed', 'stopped', 'ready'}:
        raise HTTPException(status_code=400, detail='Only failed, stopped or ready report jobs can be relaunched.')
    try:
        dataset_ids = json.loads(previous['dataset_ids_json'] or '{}')
        selected = {
            kind: _optional_reporting_datasets([int(value) for value in dataset_ids.get(kind, [])], kind)
            for kind in ('data', 'voice', 'speech')
        }
        if not any(selected.values()):
            raise HTTPException(status_code=400, detail='The report does not contain any selected CDR.')
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail='The report does not contain a valid dataset selection.') from exc
    technology = str(previous['technology'] or '').strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=400, detail='The report has an unsupported technology.')
    multivendor = str(previous['scope'] or '').casefold() == 'multivendor'
    if multivendor and not all(dataset.get('vendor_mapping_applied') for datasets in selected.values() for dataset in datasets):
        raise HTTPException(status_code=400, detail='Retry requires every selected CDR to retain its Workspace Vendor mapping.')
    template_option = next(
        (option for option in report_catalogue_options(technology) if option['name'] == str(previous['template_name'] or '')),
        None,
    )
    if not template_option:
        raise HTTPException(status_code=400, detail='The Slides Template used by this report is no longer available.')
    try:
        catalog_entries = load_template_catalogue(template_option['path'], technology)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'Unable to load the selected {technology.upper()} report template: {exc}') from exc
    file_name = Path(str(previous['output_file'] or '')).name
    if not file_name:
        raise HTTPException(status_code=400, detail='The report does not have a valid output file name.')
    destination = safe_join(_report_job_directory(file_name), file_name)
    # Remove the full dedicated directory even if a prior run failed before it
    # created the PPTX itself, so reruns never inherit partial charts or files.
    _delete_report_job_artifacts(previous)
    shutil.rmtree(destination.parent, ignore_errors=True)
    invalidate_workspace_size_cache()
    if not repository.retry_report_job(report_id):
        raise HTTPException(status_code=409, detail='This report job is no longer available for relaunch.')
    task_repository = Repository(Path(repository.db_path))
    generate_tooltips = bool(previous['generate_tooltips'])
    Thread(
        target=_run_netcheck_report_job,
        args=(report_id, task_repository, selected, technology, multivendor, catalog_entries, settings.ppt_templates_dir / TEMPLATE_NAMES[technology], destination, user.username, template_option['name'], generate_tooltips),
        name=f'report-{report_id}', daemon=True,
    ).start()
    repository.add_log(user.username, 'retry_report_job', json.dumps({
        'report_id': report_id, 'reused': True, 'generate_tooltips': generate_tooltips,
    }))
    return JSONResponse({'job_id': report_id, 'status': 'queued'}, status_code=status.HTTP_202_ACCEPTED)


@app.get('/api/datasets/status')
def dataset_status(user: SessionUser = Depends(current_user)) -> dict[str, Any]:
    datasets = [serialize_dataset_row(row) for row in repository.list_datasets()]
    add_workspace_vendor_capabilities(datasets)
    return {'datasets': datasets}


@app.post('/dashboard/upload', response_class=HTMLResponse)
async def upload_dataset(
    request: Request,
    background_tasks: BackgroundTasks,
    dataset_files: Annotated[list[UploadFile], File(...)],
    dataset_kinds: Annotated[list[str] | None, Form()] = None,
    vodafone_mapping_dataset_ids: Annotated[list[str] | None, Form()] = None,
    three_mapping_dataset_ids: Annotated[list[str] | None, Form()] = None,
    user: SessionUser = Depends(current_user),
) -> Response:
    if not dataset_files:
        datasets = [serialize_dataset_row(row) for row in repository.list_datasets()]
        return render_template(
            request,
            'workspace.html',
            {
                'user': user,
                'datasets': datasets,
                'ready_datasets': [dataset for dataset in datasets if dataset['is_ready']],
                'selected_dataset': None,
                'workspace_logs': [{**log, 'created_at': format_local_timestamp(log.get('created_at'))} for log in repository.list_workspace_logs()],
                'input_kind_options': sorted({(dataset.get('dataset_kind') or 'generic') for dataset in datasets}),
                'input_kind': None,
                'has_processing': any(dataset['status'] in {'queued', 'processing'} for dataset in datasets),
                'error': 'No files were provided.',
            },
            status_code=400,
        )
    invalid_extensions = sorted({
        Path(dataset_file.filename or '').suffix.lower()
        for dataset_file in dataset_files
        if Path(dataset_file.filename or '').suffix.lower() not in settings.allowed_extensions
    })
    if invalid_extensions:
        datasets = [serialize_dataset_row(row) for row in repository.list_datasets()]
        return render_template(
            request,
            'workspace.html',
            {
                'user': user,
                'datasets': datasets,
                'ready_datasets': [dataset for dataset in datasets if dataset['is_ready']],
                'selected_dataset': None,
                'workspace_logs': [{**log, 'created_at': format_local_timestamp(log.get('created_at'))} for log in repository.list_workspace_logs()],
                'input_kind_options': sorted({(dataset.get('dataset_kind') or 'generic') for dataset in datasets}),
                'input_kind': None,
                'has_processing': any(dataset['status'] in {'queued', 'processing'} for dataset in datasets),
                'error': f"Unsupported file type: {', '.join(invalid_extensions)}",
            },
            status_code=400,
        )
    selected_kinds = [str(kind or '').strip().lower() for kind in (dataset_kinds or [])]
    if selected_kinds and len(selected_kinds) != len(dataset_files):
        raise HTTPException(status_code=422, detail='Choose a file type for every uploaded file.')
    if any(kind not in UPLOAD_DATASET_KINDS for kind in selected_kinds):
        raise HTTPException(status_code=422, detail='Unsupported dataset type selection.')

    def parse_mapping_selection(values: list[str] | None, label: str) -> list[str | None]:
        if not values:
            return [None] * len(dataset_files)
        if len(values) != len(dataset_files):
            raise HTTPException(status_code=422, detail=f'Choose one {label} value for every uploaded file.')
        selected_ids: list[str | None] = []
        for value in values:
            value = str(value or '').strip()
            selected_ids.append(value or None)
        return selected_ids

    selected_vodafone_mappings = parse_mapping_selection(vodafone_mapping_dataset_ids, 'VFUK mapping')
    selected_three_mappings = parse_mapping_selection(three_mapping_dataset_ids, '3UK mapping')

    def validate_mapping_selection(selection: str | None, expected_kind: str, label: str) -> None:
        if not selection:
            return
        if selection.startswith('upload:'):
            try:
                upload_index = int(selection.removeprefix('upload:'))
                selected_kind = selected_kinds[upload_index]
            except (IndexError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f'Invalid {label} selection.') from exc
            if selected_kind != expected_kind:
                raise HTTPException(status_code=422, detail=f'The selected uploaded file is not a {label}.')
            return
        try:
            mapping_id = int(selection)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f'Invalid {label} selection.') from exc
        _reporting_dataset(mapping_id, expected_kind)

    for index, selected_kind in enumerate(selected_kinds or [''] * len(dataset_files)):
        if selected_kind in CDR_DATASET_KINDS:
            validate_mapping_selection(selected_vodafone_mappings[index], 'mapping_vodafone', 'VFUK mapping')
            validate_mapping_selection(selected_three_mappings[index], 'mapping_three', '3UK mapping')

    queued_dataset_ids: list[int] = []
    uploaded_datasets: list[dict[str, Any]] = []
    for index, dataset_file in enumerate(dataset_files):
        extension = Path(dataset_file.filename or '').suffix.lower()
        destination = safe_join(settings.input_dir, dataset_file.filename or f'upload{extension}')
        await save_upload_file(dataset_file, destination)
        invalidate_workspace_size_cache()
        dataset_id, created = repository.add_dataset(dataset_file.filename or destination.name, str(destination), user.username)
        selected_kind = selected_kinds[index] if selected_kinds else None
        if selected_kind:
            repository.update_dataset_profile(dataset_id, dataset_kind=selected_kind)
        uploaded_datasets.append({
            'index': index,
            'dataset_id': dataset_id,
            'destination': destination,
            'dataset_kind': selected_kind,
            'created': created,
            'vodafone_mapping_selection': selected_vodafone_mappings[index],
            'three_mapping_selection': selected_three_mappings[index],
        })
        queued_dataset_ids.append(dataset_id)

    def resolve_mapping_selection(
        selection: str | None, expected_kind: str, label: str,
    ) -> int | None:
        if not selection:
            return None
        if selection.startswith('upload:'):
            try:
                upload_index = int(selection.removeprefix('upload:'))
                uploaded = uploaded_datasets[upload_index]
            except (IndexError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f'Invalid {label} selection.') from exc
            if uploaded['dataset_kind'] != expected_kind:
                raise HTTPException(status_code=422, detail=f'The selected uploaded file is not a {label}.')
            return int(uploaded['dataset_id'])
        try:
            mapping_id = int(selection)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f'Invalid {label} selection.') from exc
        _reporting_dataset(mapping_id, expected_kind)
        return mapping_id

    # Process mappings before CDRs uploaded in the same request. Background
    # tasks run in submission order, so the selected mapping is ready when its
    # dependent CDR begins optional Vendor enrichment.
    for uploaded in sorted(
        uploaded_datasets,
        key=lambda item: 0 if item['dataset_kind'] in {'mapping_vodafone', 'mapping_three'} else 1,
    ):
        dataset_kind = uploaded['dataset_kind']
        vodafone_mapping_dataset_id = (
            resolve_mapping_selection(uploaded['vodafone_mapping_selection'], 'mapping_vodafone', 'VFUK mapping')
            if dataset_kind in CDR_DATASET_KINDS else None
        )
        three_mapping_dataset_id = (
            resolve_mapping_selection(uploaded['three_mapping_selection'], 'mapping_three', '3UK mapping')
            if dataset_kind in CDR_DATASET_KINDS else None
        )
        repository.add_log(user.username, 'upload_dataset' if uploaded['created'] else 'reprocess_dataset', json.dumps({
            'file': uploaded['destination'].name,
            'dataset_kind': dataset_kind or 'auto-detected',
            'dataset_id': uploaded['dataset_id'],
            'vodafone_mapping_dataset_id': vodafone_mapping_dataset_id,
            'three_mapping_dataset_id': three_mapping_dataset_id,
        }))
        enqueue_dataset_processing(
            background_tasks,
            int(uploaded['dataset_id']),
            uploaded['destination'],
            user.username,
            vodafone_mapping_dataset_id,
            three_mapping_dataset_id,
        )

    if not queued_dataset_ids:
        return RedirectResponse('/workspace', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f'/workspace?dataset_id={queued_dataset_ids[0]}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/datasets/{dataset_id}/rename')
def rename_dataset_file(
    dataset_id: int,
    request: Request,
    file_name: str = Form(...),
    user: SessionUser = Depends(admin_user),
) -> Response:
    dataset_row = repository.get_dataset(dataset_id)
    if not dataset_row:
        raise HTTPException(status_code=404, detail='Dataset not found.')
    dataset = serialize_dataset_row(dataset_row)
    if dataset['status'] in {'queued', 'processing'}:
        raise HTTPException(status_code=400, detail='A dataset cannot be renamed while it is queued or processing.')

    new_name = file_name.strip()
    old_path = Path(dataset['stored_path'])
    if not new_name or new_name in {'.', '..'} or '/' in new_name or '\\' in new_name or Path(new_name).name != new_name:
        raise HTTPException(status_code=400, detail='Enter a file name without folders or path separators.')
    if Path(new_name).suffix.lower() != old_path.suffix.lower():
        raise HTTPException(status_code=400, detail='Keep the original file extension when renaming a dataset.')
    if not old_path.exists():
        raise HTTPException(status_code=400, detail='The source file is missing, so this dataset cannot be renamed.')

    new_path = old_path.with_name(new_name)
    if new_path != old_path and new_path.exists():
        raise HTTPException(status_code=400, detail='A file with that name already exists in this workspace.')
    if new_path == old_path:
        return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)

    try:
        old_path.rename(new_path)
        try:
            repository.rename_dataset_file(dataset_id, new_name, str(new_path))
        except Exception:
            new_path.rename(old_path)
            raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f'Unable to rename the dataset file: {exc}') from exc

    # Cache keys include file metadata, which is no longer available at the
    # old path after the move. Clear both caches so no view can retain the
    # previous source-file label or path.
    ANALYSIS_CACHE.clear()
    DATAFRAME_CACHE.clear()
    repository.add_log(user.username, 'rename_dataset', json.dumps({
        'dataset_id': dataset_id,
        'previous_file': dataset['file_name'],
        'file': new_name,
    }))
    if 'application/json' in request.headers.get('accept', '').casefold():
        return JSONResponse({
            'dataset_id': dataset_id,
            'file_name': new_name,
            'stored_path': str(new_path),
        })
    return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/dashboard/retry/{dataset_id}')
def retry_dataset(dataset_id: int, background_tasks: BackgroundTasks, user: SessionUser = Depends(current_user)) -> Response:
    dataset = repository.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail='Dataset not found')
    dataset_payload = serialize_dataset_row(dataset)
    if dataset_payload['status'] not in {'failed', 'stopped'}:
        raise HTTPException(status_code=400, detail='Only failed or stopped datasets can be retried')
    enqueue_dataset_processing(background_tasks, dataset_id, Path(dataset_payload['stored_path']), user.username)
    repository.add_log(user.username, 'retry_dataset', json.dumps({'dataset_id': dataset_id, 'file': dataset_payload['file_name']}))
    return RedirectResponse(f'/workspace?dataset_id={dataset_id}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/map-vendors')
def map_dataset_vendors(
    background_tasks: BackgroundTasks,
    cdr_dataset_ids: Annotated[list[int] | None, Form()] = None,
    cdr_dataset_id: int | None = Form(default=None),
    vodafone_mapping_dataset_id: int | None = Form(default=None),
    three_mapping_dataset_id: int | None = Form(default=None),
    return_to: str = Form(''),
    user: SessionUser = Depends(current_user),
) -> Response:
    selected_ids = list(dict.fromkeys(cdr_dataset_ids or ([] if cdr_dataset_id is None else [cdr_dataset_id])))
    if not selected_ids:
        raise HTTPException(status_code=400, detail='Select at least one processed NetCheck CDR to map Vendors.')
    if not vodafone_mapping_dataset_id and not three_mapping_dataset_id:
        raise HTTPException(status_code=400, detail='Select at least one processed VFUK or 3UK Multivendor Mapping.')

    try:
        vodafone_mapping = (
            _reporting_dataset(vodafone_mapping_dataset_id, 'mapping_vodafone')
            if vodafone_mapping_dataset_id else None
        )
        three_mapping = (
            _reporting_dataset(three_mapping_dataset_id, 'mapping_three')
            if three_mapping_dataset_id else None
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    selected_datasets: list[dict[str, Any]] = []
    for dataset_id in selected_ids:
        cdr_row = repository.get_dataset(dataset_id)
        if not cdr_row:
            raise HTTPException(status_code=404, detail='One selected CDR was not found.')
        cdr_dataset = serialize_dataset_row(cdr_row)
        if not cdr_dataset['is_ready'] or cdr_dataset.get('dataset_kind') not in CDR_DATASET_KINDS:
            raise HTTPException(status_code=400, detail='Vendor mapping is only available for processed NetCheck CDR datasets.')
        if cdr_dataset.get('vendor_mapping_applied'):
            raise HTTPException(status_code=400, detail=f"{cdr_dataset['file_name']} already has a Vendor mapping. Clear it before mapping again.")
        selected_datasets.append(cdr_dataset)

    for cdr_dataset in selected_datasets:
        enqueue_vendor_mapping(
            background_tasks,
            int(cdr_dataset['id']),
            user.username,
            vodafone_mapping['id'] if vodafone_mapping else None,
            three_mapping['id'] if three_mapping else None,
        )
    repository.add_log(user.username, 'queue_vendor_mapping', json.dumps({
        'dataset_ids': selected_ids,
        'vodafone_mapping_dataset_id': vodafone_mapping_dataset_id,
        'three_mapping_dataset_id': three_mapping_dataset_id,
    }))
    destination = '/admin' if return_to == 'admin' else f'/workspace?dataset_id={selected_ids[0]}'
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


def _validate_clearable_vendor_datasets(dataset_ids: list[int]) -> list[dict[str, Any]]:
    selected_datasets: list[dict[str, Any]] = []
    for dataset_id in dataset_ids:
        dataset_row = repository.get_dataset(dataset_id)
        if not dataset_row:
            raise HTTPException(status_code=404, detail='One selected CDR was not found.')
        dataset = serialize_dataset_row(dataset_row)
        if not dataset['is_ready'] or dataset.get('dataset_kind') not in CDR_DATASET_KINDS:
            raise HTTPException(status_code=400, detail='Vendor clearing is only available for processed NetCheck CDR datasets.')
        if not dataset.get('vendor_mapping_applied'):
            raise HTTPException(status_code=400, detail=f"{dataset['file_name']} does not have a tool-applied Vendor mapping to clear.")
        selected_datasets.append(dataset)
    return selected_datasets


@app.post('/workspace/clear-vendors')
def clear_vendor_datasets(
    background_tasks: BackgroundTasks,
    cdr_dataset_ids: Annotated[list[int] | None, Form()] = None,
    cdr_dataset_id: int | None = Form(default=None),
    return_to: str = Form(''),
    user: SessionUser = Depends(current_user),
) -> Response:
    selected_ids = list(dict.fromkeys(cdr_dataset_ids or ([] if cdr_dataset_id is None else [cdr_dataset_id])))
    if not selected_ids:
        raise HTTPException(status_code=400, detail='Select at least one CDR with a Vendor mapping to clear.')
    _validate_clearable_vendor_datasets(selected_ids)
    for dataset_id in selected_ids:
        enqueue_vendor_clearing(background_tasks, dataset_id, user.username)
    repository.add_log(user.username, 'queue_vendor_clearing', json.dumps({'dataset_ids': selected_ids}))
    destination = '/admin' if return_to == 'admin' else f'/workspace?dataset_id={selected_ids[0]}'
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/clear-vendors/{dataset_id}')
def clear_dataset_vendors(dataset_id: int, background_tasks: BackgroundTasks, user: SessionUser = Depends(current_user)) -> Response:
    """Backward-compatible single-dataset entry point; use the queued operation."""
    _validate_clearable_vendor_datasets([dataset_id])
    enqueue_vendor_clearing(background_tasks, dataset_id, user.username)
    repository.add_log(user.username, 'queue_vendor_clearing', json.dumps({'dataset_ids': [dataset_id]}))
    return RedirectResponse(f'/workspace?dataset_id={dataset_id}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/dashboard/stop/{dataset_id}')
def stop_dataset(dataset_id: int, user: SessionUser = Depends(current_user)) -> Response:
    dataset = repository.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail='Dataset not found')
    dataset_payload = serialize_dataset_row(dataset)
    if dataset_payload['status'] != 'processing':
        raise HTTPException(status_code=400, detail='Only processing datasets can be stopped')
    request_stop(dataset_id)
    repository.update_dataset_profile(
        dataset_id,
        status='stopped',
        last_error='Processing stopped by user.',
        processed_at=now_iso(),
    )
    repository.add_log(user.username, 'stop_dataset_requested', json.dumps({'dataset_id': dataset_id, 'file': dataset_payload['file_name']}))
    return RedirectResponse(f'/workspace?dataset_id={dataset_id}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/dashboard/delete/{dataset_id}')
def delete_dataset(dataset_id: int, return_to: str = Form(''), user: SessionUser = Depends(current_user)) -> Response:
    dataset = repository.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail='Dataset not found')
    dataset_payload = serialize_dataset_row(dataset)
    if dataset_payload['status'] == 'processing':
        raise HTTPException(status_code=400, detail='Processing datasets must be stopped before deletion')
    request_stop(dataset_id)
    deleted = repository.delete_dataset(dataset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='Dataset not found')
    dataset_path = Path(deleted['stored_path'])
    if dataset_path.exists():
        dataset_path.unlink()
    repository.drop_dataset_rows(dataset_id)
    repository.drop_reporting_rows(dataset_id, dataset_payload.get('dataset_kind'))
    # Keep the combined stores compact after a dataset is removed, without
    # imposing a full-table cleanup on every Admin page load.
    repository.remove_orphaned_dataset_row_tables()
    repository.remove_orphaned_reporting_rows()
    invalidate_workspace_size_cache()
    stale_keys = [key for key in ANALYSIS_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_keys:
        ANALYSIS_CACHE.pop(key, None)
    stale_dataset_keys = [key for key in DATAFRAME_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_dataset_keys:
        DATAFRAME_CACHE.pop(key, None)
    repository.add_log(user.username, 'delete_dataset', json.dumps({'dataset_id': dataset_id, 'file': deleted['file_name']}))
    return RedirectResponse('/admin' if return_to == 'admin' else '/workspace', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/dashboard/analyze', response_class=HTMLResponse)
def analyze_dataset(
    dataset_id: int = Form(...),
    metric: str = Form(''),
    market: str = Form(''),
    period: str = Form(''),
    aggregation: str = Form('all'),
    extra_filters: str = Form(''),
    user: SessionUser = Depends(current_user),
) -> Response:
    params: dict[str, str] = {'dataset_id': str(dataset_id), 'metric': metric, 'aggregation': aggregation, 'load': '1'}
    if market:
        params['market'] = market
    if period:
        params['period'] = period
    parsed_filters = parse_extra_filters(extra_filters)
    for key, value in parsed_filters.items():
        params[key] = value
    query = urlencode({key: value for key, value in params.items() if value})
    repository.add_log(user.username, 'analyze_dataset', json.dumps(params))
    return RedirectResponse(f'/dashboard?{query}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/dashboard/export/{export_kind}')
def export_report(
    export_kind: str,
    dataset_id: int = Form(...),
    metric: list[str] | None = Form(default=None),
    market: list[str] | None = Form(default=None),
    period: list[str] | None = Form(default=None),
    date_from: str = Form(''),
    date_to: str = Form(''),
    aggregation: str = Form('all'),
    cdf_grouping: str = Form('all'),
    extra_filters: str = Form(''),
    aggregation_overrides: str = Form(''),
    cdf_overrides: str = Form(''),
    empty_filters: list[str] | None = Form(default=None, alias='__empty_filter'),
    user: SessionUser = Depends(current_user),
) -> FileResponse:
    if export_kind not in {'word', 'powerpoint'}:
        raise HTTPException(status_code=404, detail='Unsupported export type')

    dataset = repository.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail='Dataset not found')
    selected_dataset = enrich_selected_dataset_for_dashboard(serialize_dataset_row(dataset))
    if not selected_dataset or not selected_dataset['is_ready']:
        raise HTTPException(status_code=400, detail='Dataset is not ready for export')
    if selected_dataset.get('dataset_kind') not in CDR_DATASET_KINDS:
        raise HTTPException(status_code=400, detail='Only NetCheck CDR Data, Voice and Speech datasets can be exported from E2E Dashboard.')

    query_items: list[tuple[str, str]] = [
        ('dataset_id', str(dataset_id)),
        ('load', '1'),
        ('aggregation', aggregation or 'all'),
        ('cdf_grouping', cdf_grouping or 'all'),
    ]
    for metric_name in metric or []:
        if metric_name:
            query_items.append(('metric', metric_name))
    for value in market or []:
        if value:
            query_items.append(('market', value))
    for value in period or []:
        if value:
            query_items.append(('period', value))
    if date_from:
        query_items.append(('date_from', date_from))
    if date_to:
        query_items.append(('date_to', date_to))
    if aggregation_overrides:
        query_items.append(('aggregation_overrides', aggregation_overrides))
    if cdf_overrides:
        query_items.append(('cdf_overrides', cdf_overrides))
    for filter_name in empty_filters or []:
        if filter_name:
            query_items.append(('__empty_filter', filter_name))
    for key, value in parse_extra_filters(extra_filters).items():
        if isinstance(value, list):
            for item in value:
                if item:
                    query_items.append((key, str(item)))
        elif value:
            query_items.append((key, str(value)))

    export_request = type('ExportRequest', (), {'query_params': QueryParams(query_items)})()
    analysis, analyses, selected_metrics, _, analysis_error, analysis_loaded = build_dashboard_payload(selected_dataset, export_request, user.username)
    if not analysis_loaded or not analysis or not analyses:
        raise HTTPException(status_code=400, detail=analysis_error or 'Dashboard state is not ready for export')

    file_stem = Path(selected_dataset['stored_path']).stem
    filters_text = _summarize_export_filters(analysis.filters)
    report_payload = {
        'dataset_name': selected_dataset['file_name'],
        'dataset_type': selected_dataset.get('input_kind_label') or 'Other',
        'filters_text': filters_text,
        'selected_metrics': selected_metrics,
        'analyses': [{'metric': item['metric'], 'result': asdict(item['result'])} for item in analyses],
    }

    if export_kind == 'word':
        destination = safe_join(settings.export_dir, f'{file_stem}_report.docx')
        export_word_report(destination, asdict(analysis))
        media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    else:
        report_hash = hashlib.sha1(
            json.dumps(
                {
                    'version': POWERPOINT_EXPORT_VERSION,
                    'payload': report_payload,
                },
                sort_keys=True,
                default=str,
            ).encode('utf-8')
        ).hexdigest()[:10]
        destination = safe_join(settings.export_dir, f'{file_stem}_report_{report_hash}.pptx')
        if not destination.exists():
            export_powerpoint_report(destination, report_payload)
        media_type = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

    repository.add_log(user.username, f'export_{export_kind}', destination.name)
    original_name = Path(selected_dataset['file_name']).name
    original_stem = Path(original_name).stem
    download_name = f'{original_stem}.docx' if export_kind == 'word' else f'{original_stem}.pptx'
    return FileResponse(destination, filename=download_name, media_type=media_type)


@app.get('/admin', response_class=HTMLResponse)
def admin_panel(request: Request, user: SessionUser = Depends(admin_user)) -> HTMLResponse:
    return render_admin_template(request, user)


@app.get('/admin/report-templates/{technology}/{catalogue_id}/editor', response_class=HTMLResponse)
def embedded_report_template_editor(
    request: Request,
    technology: str,
    catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    """Render only the selected Slides Template editor for modal iframes."""
    technology = technology.strip().lower()
    if technology == 'auto':
        technology = next((
            candidate for candidate in TEMPLATE_NAMES
            if any(item['identifier'] == catalogue_id for item in report_catalogue_options(candidate))
        ), '')
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    editor = catalogue_editor_payload(technology, catalogue_id)
    if not editor:
        raise HTTPException(status_code=404, detail='Slides Template not found')
    return render_template(request, 'admin.html', {
        'user': user,
        'embedded_template_editor': True,
        'catalogue_editor': editor,
        'report_catalogs': {},
        'error': None,
    })


@app.post('/api/import-export/transfers/offers')
async def receive_transfer_offer(request: Request) -> JSONResponse:
    _cleanup_expired_export_packages()
    secret = request.headers.get('X-Dashboard-Transfer-Secret', '')
    if len(secret) < 32:
        raise HTTPException(status_code=401, detail='A valid transfer secret is required.')
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail='The transfer offer is not valid JSON.') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='The transfer offer is invalid.')
    kind = str(payload.get('kind') or '')
    if kind not in {'config', 'workspace', 'full-environment', 'slides-templates', 'auto-calculated-fields'}:
        raise HTTPException(status_code=400, detail='The offered export type is not supported.')
    if payload.get('archive_version') != ARCHIVE_VERSION:
        raise HTTPException(status_code=409, detail='The source server uses an incompatible export package version.')
    source_address = request.client.host if request.client else 'unknown'
    source = str(payload.get('source') or 'Dashboard Analytic server')[:160]
    content = str(payload.get('content') or kind)[:160]
    workspaces = [str(value)[:160] for value in payload.get('workspaces', []) if value] if isinstance(payload.get('workspaces'), list) else []
    secret_hash = hashlib.sha256(secret.encode('utf-8')).hexdigest()
    # The source retries transient first-contact failures. Return the original
    # offer if its response was lost, instead of showing duplicate approvals.
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        existing_offer = next((
            existing for existing in TRANSFER_OFFERS.values()
            if existing.get('secret_hash') == secret_hash
            and existing.get('source_address') == source_address
            and existing.get('status') not in {'rejected', 'failed', 'expired'}
        ), None)
        if existing_offer:
            return JSONResponse({'offer_id': existing_offer['id'], 'status': existing_offer['status']})
        # A repeated click has a fresh secret but still represents the same
        # unreviewed request. Supersede the equivalent pending offer so retries
        # cannot fill all admission slots while the destination is unattended.
        reusable_offer = next((
            existing for existing in sorted(
                TRANSFER_OFFERS.values(),
                key=lambda item: float(item.get('created_at') or 0),
                reverse=True,
            )
            if existing.get('status') == 'pending'
            and existing.get('source_address') == source_address
            and existing.get('source') == source
            and existing.get('kind') == kind
            and existing.get('content') == content
            and list(existing.get('workspaces') or []) == workspaces
        ), None)
        if reusable_offer:
            reusable_offer.update({
                'secret_hash': secret_hash,
                'phase': 'awaiting approval',
                'created_at': datetime.now(timezone.utc).timestamp(),
            })
            _save_transfer_offer(reusable_offer)
            return JSONResponse({'offer_id': reusable_offer['id'], 'status': reusable_offer['status'], 'reused': True})
    offer_id = uuid4().hex
    offer = {
        'id': offer_id,
        'source': source,
        'source_address': source_address,
        'kind': kind,
        'content': content,
        'workspaces': workspaces,
        'secret_hash': secret_hash,
        'status': 'pending',
        'phase': 'awaiting approval',
        'progress': 0.0,
        'created_at': datetime.now(timezone.utc).timestamp(),
    }
    # Do this as one SQLite write transaction. Process-local locks cannot
    # protect the handshake when Docker runs multiple application workers.
    with TRANSFER_LOCK:
        repository.replace_pending_transfer_offers(offer)
        _refresh_persisted_transfer_offers()
    try:
        repository.add_log('system', 'incoming_server_transfer_offer_received', json.dumps({
            'offer_id': offer_id,
            'source': offer['source'],
            'source_address': source_address,
            'content': offer['content'],
            'workspaces': offer['workspaces'],
            'executed_by': 'system',
        }))
    except sqlite3.Error:
        pass
    return JSONResponse({'offer_id': offer_id, 'status': 'pending'})


@app.get('/api/import-export/transfers/offers/{offer_id}')
def get_transfer_offer_status(offer_id: str, request: Request) -> JSONResponse:
    _cleanup_expired_export_packages()
    secret = request.headers.get('X-Dashboard-Transfer-Secret', '')
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer or not _transfer_offer_secret_matches(offer, secret):
            raise HTTPException(status_code=404, detail='The transfer offer does not exist.')
        payload = {key: offer.get(key) for key in ('status', 'phase', 'progress', 'notice', 'error') if offer.get(key) is not None}
    return JSONResponse(payload)


@app.delete('/api/import-export/transfers/offers/{offer_id}')
def cancel_transfer_offer(offer_id: str, request: Request) -> JSONResponse:
    secret = request.headers.get('X-Dashboard-Transfer-Secret', '')
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer or not _transfer_offer_secret_matches(offer, secret):
            raise HTTPException(status_code=404, detail='The transfer offer does not exist.')
        if offer.get('status') not in {'ready', 'failed', 'rejected', 'expired', 'cancelled'}:
            offer.update({'status': 'cancelled', 'phase': 'cancelled by source', 'error': 'The source server cancelled the transfer.', 'finished_at': datetime.now(timezone.utc).timestamp()})
            _save_transfer_offer(offer)
    return JSONResponse({'cancelled': True})


@app.put('/api/import-export/transfers/offers/{offer_id}/package')
async def receive_transfer_package(offer_id: str, request: Request) -> JSONResponse:
    secret = request.headers.get('X-Dashboard-Transfer-Secret', '')
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer or not _transfer_offer_secret_matches(offer, secret):
            raise HTTPException(status_code=404, detail='The transfer offer does not exist.')
        if offer.get('status') not in {'accepted', 'receiving'}:
            raise HTTPException(status_code=409, detail='The transfer has not been accepted by the destination server.')
        expected_size = max(int(request.headers.get('Content-Length') or 0), 0)
        offer.update({'status': 'receiving', 'phase': 'receiving package', 'size': expected_size, 'bytes_received': 0, 'progress': 0.0})
        _save_transfer_offer(offer)
    package_dir = export_package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / f'incoming-transfer-{offer_id}.upload'
    try:
        with package_path.open('wb') as output:
            async for chunk in request.stream():
                output.write(chunk)
                with TRANSFER_LOCK:
                    offer['bytes_received'] = int(offer.get('bytes_received') or 0) + len(chunk)
                    size = int(offer.get('size') or 0)
                    if size:
                        offer['progress'] = round(min(100.0, offer['bytes_received'] * 100.0 / size), 1)
        manifest = read_import_manifest(package_path)
        if str(manifest.get('kind') or '') != str(offer['kind']):
            raise ValueError('The received package type does not match the accepted transfer offer.')
        with TRANSFER_LOCK:
            offer.update({'path': str(package_path), 'manifest': manifest, 'status': 'received', 'phase': 'package received', 'progress': 100.0})
            _save_transfer_offer(offer)
        Thread(target=_run_received_transfer, args=(offer_id,), name=f'incoming-transfer-{offer_id[:8]}', daemon=True).start()
        return JSONResponse({'offer_id': offer_id, 'status': 'received'})
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        package_path.unlink(missing_ok=True)
        with TRANSFER_LOCK:
            offer.update({'status': 'failed', 'error': str(exc), 'finished_at': datetime.now(timezone.utc).timestamp()})
            _save_transfer_offer(offer)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        package_path.unlink(missing_ok=True)
        with TRANSFER_LOCK:
            offer.update({'status': 'accepted', 'phase': 'waiting for transmission retry', 'error': 'The package transfer was interrupted; waiting for the source to retry.', 'progress': 0.0})
            _save_transfer_offer(offer)
        raise HTTPException(status_code=503, detail='The package transfer was interrupted; the source may retry.') from exc


@app.get('/admin/import-export/transfers/offers')
def list_pending_transfer_offers(user: SessionUser = Depends(super_admin_user)) -> JSONResponse:
    _cleanup_expired_export_packages()
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        offers = [
            {key: offer.get(key) for key in ('id', 'source', 'source_address', 'kind', 'content', 'workspaces', 'created_at')}
            for offer in TRANSFER_OFFERS.values()
            if offer.get('status') == 'pending'
        ]
    return JSONResponse({
        'offers': sorted(offers, key=lambda offer: float(offer.get('created_at') or 0)),
        'destination_workspaces': [
            {'id': workspace.id, 'name': workspace.name} for workspace in workspace_registry.list()
        ],
    })


@app.get('/admin/import-export/transfers/offers/{offer_id}')
def get_admin_transfer_offer(offer_id: str, user: SessionUser = Depends(super_admin_user)) -> JSONResponse:
    """Expose safe progress fields to the destination super-admin UI."""
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer:
            raise HTTPException(status_code=404, detail='The transfer offer no longer exists.')
        return JSONResponse({
            key: offer.get(key)
            for key in ('id', 'source', 'content', 'status', 'phase', 'progress', 'size', 'bytes_received', 'notice', 'error')
            if offer.get(key) is not None
        })


@app.get('/admin/import-export/transfers/recoveries')
def list_recovered_transfer_packages(user: SessionUser = Depends(super_admin_user)) -> JSONResponse:
    return JSONResponse({'offers': recovered_transfer_packages()})


@app.post('/admin/import-export/transfers/recoveries/{offer_id}/import')
def import_recovered_transfer_package(offer_id: str, user: SessionUser = Depends(super_admin_user)) -> JSONResponse:
    with TRANSFER_LOCK:
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer or offer.get('status') != 'recovered':
            raise HTTPException(status_code=404, detail='The recovered transfer package is no longer available.')
        package_path = Path(str(offer.get('path') or ''))
        if not package_path.is_file():
            TRANSFER_OFFERS.pop(offer_id, None)
            repository.delete_transfer_offer(offer_id)
            raise HTTPException(status_code=404, detail='The recovered transfer package is no longer available.')
        offer.update({'status': 'received', 'phase': 'starting recovered import', 'progress': 100.0, 'accepted_by': user.username})
    Thread(target=_run_received_transfer, args=(offer_id,), name=f'recovered-transfer-{offer_id[:8]}', daemon=True).start()
    return JSONResponse({'offer_id': offer_id, 'status': 'received'})


@app.post('/admin/import-export/transfers/recoveries/{offer_id}/delete')
def delete_recovered_transfer_package(offer_id: str, user: SessionUser = Depends(super_admin_user)) -> JSONResponse:
    with TRANSFER_LOCK:
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer or offer.get('status') != 'recovered':
            raise HTTPException(status_code=404, detail='The recovered transfer package is no longer available.')
        package_path = Path(str(offer.get('path') or ''))
        TRANSFER_OFFERS.pop(offer_id, None)
        repository.delete_transfer_offer(offer_id)
    package_path.unlink(missing_ok=True)
    try:
        repository.add_log(user.username, 'delete_recovered_transfer_package', f'Deleted recovered {offer["content"]} transfer package.')
    except sqlite3.Error:
        pass
    return JSONResponse({'deleted': offer_id})


@app.post('/admin/import-export/transfers/offers/{offer_id}/accept')
async def accept_transfer_offer(
    offer_id: str, request: Request, user: SessionUser = Depends(super_admin_user),
) -> JSONResponse:
    _cleanup_expired_export_packages()
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    destination_workspace_ids = list(dict.fromkeys(
        str(value) for value in payload.get('workspace_ids', [])
    )) if isinstance(payload, dict) and isinstance(payload.get('workspace_ids'), list) else []
    accepted_now = False
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer:
            raise HTTPException(status_code=404, detail='The pending transfer offer no longer exists.')
        if offer.get('status') == 'pending':
            if offer.get('kind') in {'auto-calculated-fields', 'slides-templates'}:
                available = {workspace.id for workspace in workspace_registry.list()}
                if not destination_workspace_ids:
                    raise HTTPException(status_code=400, detail='Select at least one destination workspace.')
                if any(workspace_id not in available for workspace_id in destination_workspace_ids):
                    raise HTTPException(status_code=400, detail='One or more destination workspaces no longer exist.')
            offer.update({
                'status': 'accepted', 'phase': 'waiting for source package',
                'accepted_by': user.username, 'accepted_at': datetime.now(timezone.utc).timestamp(),
                'destination_workspace_ids': destination_workspace_ids,
            })
            accepted_now = True
        elif offer.get('status') not in {'accepted', 'receiving', 'received', 'importing', 'ready'}:
            raise HTTPException(status_code=409, detail='This transfer offer can no longer be accepted.')
        _save_transfer_offer(offer)
    if accepted_now:
        try:
            repository.add_log(user.username, 'accept_server_transfer', f'Accepted incoming {offer["content"]} transfer from {offer["source"]}.')
        except sqlite3.Error:
            pass
    return JSONResponse({'accepted': True})


@app.post('/admin/import-export/transfers/offers/{offer_id}/reject')
def reject_transfer_offer(offer_id: str, user: SessionUser = Depends(super_admin_user)) -> JSONResponse:
    _cleanup_expired_export_packages()
    with TRANSFER_LOCK:
        _refresh_persisted_transfer_offers()
        offer = TRANSFER_OFFERS.get(offer_id)
        if not offer or offer.get('status') != 'pending':
            raise HTTPException(status_code=404, detail='The pending transfer offer no longer exists.')
        offer.update({'status': 'rejected', 'error': 'The destination super-admin rejected the transfer.', 'finished_at': datetime.now(timezone.utc).timestamp()})
        _save_transfer_offer(offer)
    try:
        repository.add_log(user.username, 'reject_server_transfer', f'Rejected incoming {offer["content"]} transfer from {offer["source"]}.')
    except sqlite3.Error:
        pass
    return JSONResponse({'rejected': True})


@app.post('/admin/import-export/transfers/jobs')
def create_admin_transfer_job(
    destination_url: str = Form(...),
    destination_port: int | None = Form(None),
    export_target: str = Form(...),
    workspace_ids: list[str] | None = Form(None),
    include_generated_outputs: bool = Form(True),
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    require_export_permission(user, export_target)
    try:
        job = start_transfer_job(
            destination_url,
            destination_port,
            export_target,
            workspace_ids if export_target == 'full-environment' else None,
            user,
            include_generated_outputs=include_generated_outputs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=f'The transfer state database could not be prepared: {exc}',
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f'The transfer working directory could not be prepared: {exc}',
        ) from exc
    return JSONResponse({
        'job_id': job['id'],
        'status': job['status'],
        'status_url': f"/admin/import-export/transfers/jobs/{job['id']}",
        'cancel_url': f"/admin/import-export/transfers/jobs/{job['id']}/cancel",
    })


@app.get('/admin/import-export/transfers/jobs/{job_id}')
def get_admin_transfer_job(job_id: str, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    if not (payload := transfer_job_payload(job_id, user)):
        raise HTTPException(status_code=404, detail='The transfer job no longer exists.')
    return JSONResponse(payload)


@app.post('/admin/import-export/transfers/jobs/{job_id}/cancel')
def cancel_admin_transfer_job(job_id: str, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    with TRANSFER_LOCK:
        job = TRANSFER_JOBS.get(job_id)
        if not job or job.get('owner') != user.username:
            raise HTTPException(status_code=404, detail='The transfer job no longer exists.')
        if job.get('status') in {'ready', 'failed', 'cancelled'}:
            return JSONResponse({'status': job.get('status')})
        job.update({'cancel_requested': True, 'status': 'cancelling', 'phase': 'cancellation requested'})
    return JSONResponse({'status': 'cancelling'})


@app.get('/admin/import-export/export')
def export_admin_package(
    export_target: str = Query(...),
    user: SessionUser = Depends(admin_user),
) -> FileResponse:
    require_export_permission(user, export_target)
    try:
        _cleanup_expired_export_packages()
        destination = export_package_dir() / f'legacy-{uuid4().hex}.zip'
        filename = build_export_archive_file(export_target, destination)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(destination, filename=filename, media_type='application/zip')


@app.post('/admin/import-export/export/jobs')
def create_admin_export_job(
    export_target: str = Form(...),
    workspace_ids: list[str] | None = Form(None),
    include_generated_outputs: bool = Form(True),
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    require_export_permission(user, export_target)
    try:
        job = start_export_job(
            export_target, workspace_ids if export_target == 'full-environment' else None,
            include_generated_outputs=include_generated_outputs,
            owner=user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({
        'job_id': job['id'],
        'status': job['status'],
        'status_url': f"/admin/import-export/export/jobs/{job['id']}",
    })


@app.get('/admin/import-export/export/jobs/{job_id}')
def get_admin_export_job(job_id: str, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    if not (payload := export_job_payload(job_id)):
        raise HTTPException(status_code=404, detail='The export job no longer exists. Start a new export.')
    require_export_permission(user, str(payload['target']))
    return JSONResponse(payload)


@app.get('/admin/import-export/export/jobs/{job_id}/download')
def download_admin_export_job(job_id: str, user: SessionUser = Depends(admin_user)) -> FileResponse:
    if not (payload := export_job_payload(job_id)):
        raise HTTPException(status_code=404, detail='The export job no longer exists. Start a new export.')
    require_export_permission(user, str(payload['target']))
    if payload['status'] != 'ready':
        raise HTTPException(status_code=409, detail='The export package is still being prepared.')
    with EXPORT_JOBS_LOCK:
        path = Path(str(EXPORT_JOBS[job_id]['path']))
    if not path.is_file():
        raise HTTPException(status_code=404, detail='The prepared export package is no longer available.')
    return FileResponse(path, filename=str(payload['filename']), media_type='application/zip')


@app.post('/admin/import-export/inspect')
async def inspect_admin_import_package(
    package: UploadFile = File(...),
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    """Compatibility endpoint for multipart clients.

    The browser UI uses the direct-stream endpoint below so large imports do
    not first become a multipart temporary file and then get copied again.
    """
    _cleanup_expired_export_packages()
    upload_id = uuid4().hex
    package_dir = export_package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / f'import-{upload_id}.upload'
    try:
        await save_upload_file(package, package_path)
        return _retain_import_upload(upload_id, package_path, user)
    except ValueError as exc:
        package_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        package_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        package_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f'The import package could not be stored: {exc}') from exc
    finally:
        await package.close()


def _retain_import_upload(upload_id: str, package_path: Path, user: SessionUser) -> JSONResponse:
    """Validate and retain an already disk-backed import upload."""
    manifest = read_import_manifest(package_path)
    kind = str(manifest.get('kind') or '')
    if kind not in {'config', 'workspace', 'full-environment', 'slides-templates', 'auto-calculated-fields'}:
        raise ValueError('The export package type is not supported.')
    require_import_export_permission(user, kind)
    with IMPORT_JOBS_LOCK:
        IMPORT_UPLOADS[upload_id] = {
            'path': str(package_path),
            'manifest': manifest,
            'owner': user.username,
            'created_at': datetime.now(timezone.utc).timestamp(),
            'claimed': False,
        }
    response_payload = {
        'kind': kind,
        'includes_slides_templates': bool(manifest.get('includes_slides_templates')),
        'workspace_collisions': import_workspace_collisions(manifest),
    }
    if kind in {'auto-calculated-fields', 'slides-templates'}:
        response_payload['selected_workspace_ids'] = matching_template_workspaces(manifest, accessible_workspaces(user))
        response_payload['destination_workspaces'] = [
            {'id': workspace.id, 'name': workspace.name} for workspace in accessible_workspaces(user)
        ]
    return JSONResponse(response_payload, headers={'X-Import-Upload-Id': upload_id})


@app.post('/admin/import-export/inspect/upload')
async def inspect_admin_import_package_stream(
    request: Request,
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    """Receive an import ZIP directly to its retained disk path.

    Unlike multipart uploads this avoids a second multi-gigabyte disk copy.
    """
    _cleanup_expired_export_packages()
    upload_id = uuid4().hex
    package_dir = export_package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / f'import-{upload_id}.upload'
    try:
        with package_path.open('wb') as output:
            async for chunk in request.stream():
                output.write(chunk)
        if not package_path.stat().st_size:
            raise ValueError('Select an export package to import.')
        return _retain_import_upload(upload_id, package_path, user)
    except ValueError as exc:
        package_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        package_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        package_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f'The import package could not be stored: {exc}') from exc


@app.delete('/admin/import-export/import/uploads/{upload_id}')
def discard_admin_import_upload(upload_id: str, user: SessionUser = Depends(admin_user)) -> Response:
    with IMPORT_JOBS_LOCK:
        upload = IMPORT_UPLOADS.get(upload_id)
        if not upload or upload.get('owner') != user.username:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        if upload.get('claimed'):
            raise HTTPException(status_code=409, detail='The package import has already started.')
        IMPORT_UPLOADS.pop(upload_id, None)
        package_path = Path(str(upload['path']))
    package_path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post('/admin/import-export/import/jobs')
def create_admin_import_job(
    upload_id: str = Form(...),
    confirmed_import: bool = Form(False),
    workspace_ids: list[str] | None = Form(None),
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    if not confirmed_import:
        raise HTTPException(status_code=400, detail='Confirm the import warning before applying this package.')
    with IMPORT_JOBS_LOCK:
        upload = IMPORT_UPLOADS.get(upload_id)
        if not upload or upload.get('owner') != user.username:
            raise HTTPException(status_code=404, detail='The uploaded package is no longer available. Select it again.')
        kind = str(upload['manifest'].get('kind') or '')
    require_import_export_permission(user, kind)
    selected_workspaces = list(dict.fromkeys(workspace_ids or []))
    if kind in {'auto-calculated-fields', 'slides-templates'}:
        if not selected_workspaces and kind == 'slides-templates':
            selected_workspaces = matching_template_workspaces(upload['manifest'], accessible_workspaces(user))
        allowed = {workspace.id for workspace in accessible_workspaces(user)}
        if not selected_workspaces:
            raise HTTPException(status_code=400, detail='Select at least one destination workspace.')
        if any(workspace_id not in allowed for workspace_id in selected_workspaces):
            raise HTTPException(status_code=403, detail='You do not have access to one or more destination workspaces.')
    try:
        job = start_import_job(upload_id, user, selected_workspaces)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({
        'job_id': job['id'],
        'status': job['status'],
        'status_url': f"/admin/import-export/import/jobs/{job['id']}",
    })


@app.get('/admin/import-export/import/jobs/{job_id}')
def get_admin_import_job(job_id: str, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    if not (payload := import_job_payload(job_id, user)):
        raise HTTPException(status_code=404, detail='The import job no longer exists.')
    return JSONResponse(payload)


@app.post('/admin/import-export/import')
async def import_admin_package(
    package: UploadFile = File(...),
    confirmed_import: bool = Form(False),
    user: SessionUser = Depends(admin_user),
) -> Response:
    package_dir = export_package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / f'legacy-import-{uuid4().hex}.upload'
    try:
        await save_upload_file(package, package_path)
        manifest = read_import_manifest(package_path)
        if not confirmed_import:
            raise ValueError('Confirm the import warning before applying this package.')
        require_import_export_permission(user, str(manifest.get('kind')))
        destinations = []
        if manifest.get('kind') == 'slides-templates':
            destinations = matching_template_workspaces(manifest, accessible_workspaces(user))
            if not destinations:
                raise ValueError('Select destination workspaces using the Export / Import panel.')
        notice = _apply_import_archive(package_path, manifest, destination_workspace_ids=destinations)
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        return RedirectResponse(
            f'/admin?{urlencode({"import_export_error": str(exc)})}',
            status_code=status.HTTP_303_SEE_OTHER,
        )
    finally:
        await package.close()
        package_path.unlink(missing_ok=True)
    return RedirectResponse(
        f'/admin?{urlencode({"import_export_notice": notice})}',
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post('/admin/database/cleanup')
def cleanup_admin_database(user: SessionUser = Depends(admin_user)) -> Response:
    if not active_workspace:
        return RedirectResponse(
            f'/admin?{urlencode({"database_notice": "Open a workspace before cleaning its database."})}',
            status_code=status.HTTP_303_SEE_OTHER,
        )
    removed_tables = repository.remove_orphaned_dataset_row_tables()
    removed_rows = repository.remove_orphaned_reporting_rows()
    repository.add_log(user.username, 'cleanup_database', json.dumps({
        'dataset_row_tables': len(removed_tables),
        'reporting_rows': removed_rows,
    }))
    return RedirectResponse(
        f'/admin?{urlencode({"database_notice": f"Database cleanup complete: {len(removed_tables)} stale tables and {removed_rows} combined rows removed."})}',
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get('/admin/database/table')
def admin_database_table(
    table: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=250),
    filters: str = Query('{}'),
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before viewing its database.')
    try:
        parsed_filters = json.loads(filters)
        if not isinstance(parsed_filters, dict):
            raise ValueError('Database filters must be an object.')
        return JSONResponse(repository.database_table_page(table, offset=offset, limit=limit, filters=parsed_filters))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post('/admin/database/table/query')
async def query_admin_database_table(request: Request, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before viewing its database.')
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Send a valid table query payload.') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Send a valid table query payload.')
    table = str(payload.get('table') or '').strip()
    filters = payload.get('filters') or {}
    if not isinstance(filters, dict):
        raise HTTPException(status_code=400, detail='Database filters must be an object.')
    try:
        return JSONResponse(repository.database_table_page(
            table,
            offset=int(payload.get('offset') or 0),
            limit=int(payload.get('limit') or 100),
            filters=filters,
        ))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/admin/database/table/values')
def admin_database_table_values(
    table: str = Query(...),
    column: str = Query(...),
    filters: str = Query('{}'),
    search: str = Query(''),
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before viewing its database.')
    try:
        parsed_filters = json.loads(filters)
        if not isinstance(parsed_filters, dict):
            raise ValueError('Database filters must be an object.')
        return JSONResponse(repository.database_table_distinct_values(table, column, filters=parsed_filters, search=search))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/admin/database/table')
async def update_admin_database_table(request: Request, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before editing its database.')
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Send a valid table update payload.') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Send a valid table update payload.')
    table = str(payload.get('table') or '').strip()
    updates = payload.get('updates')
    try:
        rowid = int(payload.get('rowid'))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='The selected row is invalid.') from exc
    try:
        repository.update_database_table_row(table, rowid, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f'The update violates a database constraint: {exc}.') from exc
    ANALYSIS_CACHE.clear()
    DATAFRAME_CACHE.clear()
    repository.add_log(user.username, 'database_table_update', f'Updated row {rowid} in {table}.')
    return JSONResponse({'ok': True, 'message': 'Row saved.'})


@app.post('/admin/database/table/delete')
async def delete_admin_database_table_row(request: Request, user: SessionUser = Depends(admin_user)) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before editing its database.')
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Send a valid row deletion payload.') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Send a valid row deletion payload.')
    table = str(payload.get('table') or '').strip()
    try:
        rowid = int(payload.get('rowid'))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='The selected row is invalid.') from exc
    try:
        repository.delete_database_table_row(table, rowid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f'The row cannot be deleted because of a database constraint: {exc}.') from exc
    ANALYSIS_CACHE.clear()
    DATAFRAME_CACHE.clear()
    repository.add_log(user.username, 'database_table_delete', f'Deleted row {rowid} from {table}.')
    return JSONResponse({'ok': True, 'message': 'Row deleted.'})


@app.get('/admin/catalogue-filter-values')
def catalogue_filter_values(
    source: str,
    column: str,
    technology: str = '',
    catalogue_id: str = '',
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    """Return values only for the field currently being configured in the editor."""
    normalized_source = source.strip().casefold()
    if normalized_source not in {'cdr-data', 'cdr-voice', 'cdr-speech'} or not column.strip():
        raise HTTPException(status_code=400, detail='Unsupported CDR source or filter field.')
    kind = normalized_source.removeprefix('cdr-')
    values: set[str] = set()
    definition = None
    normalized_technology = technology.strip().casefold()
    if normalized_technology in TEMPLATE_NAMES and catalogue_id.strip():
        catalogue = _named_catalogue(normalized_technology, catalogue_id.strip())
        if catalogue:
            definition = next((
                item for item in load_workspace_calculated_dimensions()
                if _normalise_catalogue_dimension_name(item.name) == _normalise_catalogue_dimension_name(column)
                and normalized_source in item.sources
            ), None)
    if definition:
        values.update(rule.value for rule in definition.rules)
        if definition.default:
            values.add(definition.default)
    for dataset in repository.list_datasets():
        if str(dataset['dataset_kind'] or '').casefold() != kind or dataset['status'] != 'ready':
            continue
        if not repository.dataset_rows_table_exists(dataset['id']):
            continue
        requested_columns = definition.default_from if definition else (column,)
        for requested_column in requested_columns:
            values.update(repository.list_distinct_dataset_row_values(dataset['id'], requested_column, limit=200))
    return JSONResponse({'values': sorted(values, key=str.casefold)[:200]})


def _import_report_catalogue(
    request: Request,
    technology: str,
    catalogue_file: UploadFile | None,
    catalogue_name: str,
    convert_catalogue: bool,
    overwrite_existing: bool,
    user: SessionUser,
) -> HTMLResponse:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    if not catalogue_file or not catalogue_file.filename or Path(catalogue_file.filename).suffix.lower() != '.csv':
        query = urlencode({'catalogue_error': 'Select a CSV Slides Template.'})
        return RedirectResponse(f'/admin?{query}', status_code=status.HTTP_303_SEE_OTHER)
    try:
        # Preserve meaningful hyphens in the uploaded filename; only turn
        # underscores into spaces when deriving a display name automatically.
        catalogue_name = catalogue_name.strip() or re.sub(r'_+', ' ', Path(catalogue_file.filename).stem).strip()
        if not catalogue_name:
            raise ValueError('Enter a name for the template.')
        identifier = catalogue_registry_key(catalogue_name)
        content = catalogue_file.file.read()
        if convert_catalogue:
            content = convert_catalog_csv(content, technology)
        entries = parse_catalog_csv(content, technology)
        existing_template = next(
            (str(row['name']) for row in repository.list_report_templates(technology)
             if str(row['name']).casefold() == identifier.casefold()),
            None,
        )
        if existing_template and not overwrite_existing:
            raise ValueError(
                f"A {technology.upper()} template named '{existing_template}' already exists. "
                'Confirm overwrite to replace it.'
            )
        # A case-insensitive name match is still the same template. Retain its
        # existing display spelling and registry key rather than creating a
        # second entry on case-insensitive filesystems.
        identifier = existing_template or identifier
        catalogue_name = identifier
        destination = named_catalogue_path(technology, identifier, identifier)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        if existing_template:
            repository.touch_report_template(technology, identifier)
            if next(row for row in repository.list_report_templates(technology) if str(row['name']) == identifier)['is_default']:
                promote_report_template_to_default(technology, identifier)
        else:
            repository.add_report_template(technology, identifier)
            promote_report_template_to_default(technology, identifier)
        # Keep the registry aligned with the files promoted by this import.
        # This is intentionally limited to the template library; it no longer
        # rebuilds the PowerPoint help document.
        synchronize_template_file_names(technology)
    except Exception as exc:
        repository.add_log(user.username, 'import_report_template_failed', json.dumps({
            'technology': technology,
            'file': catalogue_file.filename,
            'error': str(exc),
        }))
        query = urlencode({'catalogue_error': str(exc)})
        return RedirectResponse(f'/admin?{query}', status_code=status.HTTP_303_SEE_OTHER)
    repository.add_log(user.username, 'import_report_template', json.dumps({
        'technology': technology,
        'template_name': catalogue_name,
        'file': catalogue_file.filename,
        'chart_rows': sum(1 for entry in entries if entry.source_kind),
    }))
    action = 'Overwrote' if existing_template else 'Imported'
    query = urlencode({'catalogue_notice': f"{action} {catalogue_name} ({technology.upper()})."})
    return RedirectResponse(f'/admin?{query}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/report-templates/{technology}', response_class=HTMLResponse)
def import_report_catalogue(
    request: Request,
    technology: str,
    catalogue_file: UploadFile | None = File(default=None),
    catalogue_name: str = Form(''),
    convert_catalogue: bool = Form(False),
    overwrite_existing: bool = Form(False),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    """Compatibility endpoint for existing NSA/SA-specific imports."""
    return _import_report_catalogue(request, technology, catalogue_file, catalogue_name, convert_catalogue, overwrite_existing, user)


@app.post('/admin/slides-templates/import', response_class=HTMLResponse)
def import_slides_template(
    request: Request,
    template_type: str = Form('nsa'),
    catalogue_file: UploadFile | None = File(default=None),
    catalogue_name: str = Form(''),
    convert_catalogue: bool = Form(False),
    overwrite_existing: bool = Form(False),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    """Import one Slides Template after the user has selected its NSA/SA type."""
    return _import_report_catalogue(request, template_type, catalogue_file, catalogue_name, convert_catalogue, overwrite_existing, user)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/activate', response_class=HTMLResponse)
def activate_report_catalogue(
    request: Request,
    technology: str,
    catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    available = {option['identifier']: option for option in report_catalogue_options(technology)}
    if catalogue_id not in available:
        return render_admin_template(request, user, error='Slides Template not found.', status_code=404)
    promote_report_template_to_default(technology, catalogue_id)
    repository.add_log(user.username, 'activate_report_template', json.dumps({
        'technology': technology,
        'template': available[catalogue_id]['name'],
    }))
    return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)


def _named_catalogue(technology: str, catalogue_id: str) -> dict[str, Any] | None:
    return next((item for item in report_catalogue_options(technology) if item['identifier'] == catalogue_id), None)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/type', response_class=HTMLResponse)
def change_report_catalogue_type(
    request: Request,
    technology: str,
    catalogue_id: str,
    template_type: str = Form(...),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    """Move a non-default Slides Template between the NSA and SA libraries."""
    technology = technology.strip().lower()
    target_technology = template_type.strip().lower()
    catalogue = _named_catalogue(technology, catalogue_id) if technology in TEMPLATE_NAMES else None
    if not catalogue or target_technology not in TEMPLATE_NAMES:
        return render_admin_template(request, user, error='Slides Template or target type was not found.', status_code=404)
    if target_technology == technology:
        return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)
    if catalogue['active']:
        return render_admin_template(
            request,
            user,
            error='Set another template as default before changing the type of the current default template.',
            status_code=400,
        )
    try:
        source_names = {str(row['name']) for row in repository.list_report_templates(technology)}
        target_names = {str(row['name']) for row in repository.list_report_templates(target_technology)}
        if catalogue_id not in source_names:
            raise ValueError('Named template metadata was not found.')
        name = catalogue_id
        identifier = catalogue_registry_key(name)
        source_path = named_catalogue_path(technology, catalogue_id, name)
        destination_path = named_catalogue_path(target_technology, identifier, name)
        if identifier in target_names or destination_path.exists():
            raise ValueError(f"A {target_technology.upper()} template named '{name}' already exists.")
        if not source_path.exists():
            raise ValueError('The named template CSV could not be found.')
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.rename(destination_path)
        repository.move_report_template(technology, catalogue_id, target_technology)
    except ValueError as exc:
        return render_admin_template(request, user, error=str(exc), status_code=400)
    repository.add_log(user.username, 'change_report_template_type', json.dumps({
        'source_type': technology,
        'target_type': target_technology,
        'template': name,
    }))
    return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/rename', response_class=HTMLResponse)
def rename_report_catalogue(
    request: Request,
    technology: str,
    catalogue_id: str,
    catalogue_name: str = Form(...),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    technology = technology.strip().lower()
    catalogue = _named_catalogue(technology, catalogue_id) if technology in TEMPLATE_NAMES else None
    if not catalogue:
        if 'application/json' in request.headers.get('accept', ''):
            return JSONResponse({'error': 'Slides Template not found.'}, status_code=404)
        return render_admin_template(request, user, error='Slides Template not found.', status_code=404)
    try:
        name = catalogue_name.strip()
        if not name:
            raise ValueError('Enter a template name.')
        names = {str(row['name']) for row in repository.list_report_templates(technology)}
        new_identifier = catalogue_registry_key(name)
        if catalogue_id not in names:
            raise ValueError('Slides Template was not found.')
        if new_identifier != catalogue_id and new_identifier in names:
            raise ValueError(f"A {technology.upper()} template named '{new_identifier}' already exists.")
        library_source_path = named_catalogue_path(technology, catalogue_id, catalogue_id)
        library_destination_path = named_catalogue_path(technology, new_identifier, name)
        if not library_source_path.exists():
            raise ValueError('The named template CSV could not be found.')
        if library_destination_path.exists() and library_destination_path != library_source_path:
            raise ValueError(f"The template file '{library_destination_path.name}' already exists.")
        if catalogue['active']:
            source_path = default_report_slides_template_path(technology, catalogue_id)
            destination_path = source_path.parent / template_filename(name)
            if destination_path.exists() and destination_path != source_path:
                raise ValueError(f"The template file '{destination_path.name}' already exists.")
            if destination_path != source_path:
                source_path.rename(destination_path)
        if library_destination_path != library_source_path:
            library_source_path.rename(library_destination_path)
        if new_identifier != catalogue_id:
            repository.rename_report_template(technology, catalogue_id, new_identifier)
            catalogue_id = new_identifier
    except ValueError as exc:
        if 'application/json' in request.headers.get('accept', ''):
            return JSONResponse({'error': str(exc)}, status_code=400)
        return render_admin_template(request, user, error=str(exc), status_code=400)
    repository.add_log(user.username, 'rename_report_template', json.dumps({'technology': technology, 'template': catalogue_id, 'name': name}))
    if 'application/json' in request.headers.get('accept', ''):
        payload = {'name': name}
        payload['identifier'] = name
        return JSONResponse(payload)
    return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/duplicate', response_class=HTMLResponse)
def duplicate_report_catalogue(
    request: Request,
    technology: str,
    catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    technology = technology.strip().lower()
    catalogue = _named_catalogue(technology, catalogue_id) if technology in TEMPLATE_NAMES else None
    if not catalogue:
        return render_admin_template(request, user, error='Slides Template not found.', status_code=404)
    names = {str(row['name']) for row in repository.list_report_templates(technology)}
    # The physical CSV name is the canonical template name.  Deriving the
    # duplicate label from it prevents a stale/default registry label from
    # turning every duplicate into the generic NSA/SA starter name.
    source_name = catalogue['path'].stem.strip() or str(catalogue['name']).strip()
    base_name = f"{source_name} - Copy"
    suffix = 2
    name = base_name
    identifier = catalogue_registry_key(name)
    while identifier in names or named_catalogue_path(technology, identifier, name).exists():
        name = f"{base_name} {suffix}"
        identifier = catalogue_registry_key(name)
        suffix += 1
    destination = named_catalogue_path(technology, identifier, name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(catalogue['path'].read_bytes())
    repository.add_report_template(technology, identifier)
    repository.add_log(user.username, 'duplicate_report_template', json.dumps({'technology': technology, 'source': catalogue_id, 'template': name}))
    return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/slides-templates/new', response_class=HTMLResponse)
def create_empty_report_catalogue(
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    """Create a blank NSA template that can immediately be renamed or edited."""
    technology = 'nsa'
    names = {str(row['name']) for row in repository.list_report_templates(technology)}
    base_name = 'New Template'
    name = base_name
    suffix = 2
    while name in names or named_catalogue_path(technology, name, name).exists():
        name = f'{base_name} {suffix}'
        suffix += 1
    destination = named_catalogue_path(technology, name, name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(catalogue_csv([]))
    repository.add_report_template(technology, name)
    repository.add_log(user.username, 'create_report_template', json.dumps({
        'technology': technology,
        'template': name,
    }))
    query = urlencode({'catalogue_technology': technology, 'catalogue_id': name})
    return RedirectResponse(f'/admin?{query}#catalogue-editor', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/delete', response_class=HTMLResponse)
def delete_report_catalogue(
    request: Request,
    technology: str,
    catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    catalogue = _named_catalogue(technology, catalogue_id)
    if not catalogue:
        return render_admin_template(request, user, error='Slides Template not found.', status_code=404)
    if catalogue['active']:
        return render_admin_template(request, user, error='The default template cannot be deleted.', status_code=400)
    catalogue['path'].unlink(missing_ok=True)
    repository.delete_report_template(technology, catalogue_id)
    repository.add_log(user.username, 'delete_report_template', json.dumps({'technology': technology, 'template': catalogue['name']}))
    return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)


def finalize_template_save(
    task_repository: Repository,
    username: str,
    technology: str,
    template_name: str,
    chart_rows: int,
) -> None:
    """Update metadata/audit after the template file is safely available."""
    try:
        task_repository.touch_report_template(technology, template_name)
    except (sqlite3.Error, OSError) as exc:
        warnings.warn(f'Unable to update Slides Template metadata: {exc}', RuntimeWarning)
        try:
            task_repository.add_log(username, 'save_report_template_metadata_failed', json.dumps({
                'technology': technology, 'template': template_name, 'error': str(exc),
            }))
        except (sqlite3.Error, OSError) as log_exc:
            warnings.warn(f'Unable to log Slides Template metadata failure: {log_exc}', RuntimeWarning)
        return
    try:
        task_repository.add_log(username, 'save_report_template', json.dumps({
            'technology': technology, 'template': template_name, 'chart_rows': chart_rows,
        }))
    except (sqlite3.Error, OSError) as exc:
        warnings.warn(f'Unable to log Slides Template save: {exc}', RuntimeWarning)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/save')
def save_report_catalogue(
    request: Request,
    background_tasks: BackgroundTasks,
    technology: str,
    catalogue_id: str,
    catalogue_content: str = Form(...),
    user: SessionUser = Depends(admin_user),
) -> Response:
    wants_json = 'application/json' in request.headers.get('accept', '')
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    try:
        metadata = next((row for row in repository.list_report_templates(technology) if str(row['name']) == catalogue_id), None)
        if not metadata:
            raise FileNotFoundError('Slides Template not found.')
        template_name = str(metadata['name'])
        is_default = bool(metadata['is_default'])
        destination = (
            default_report_slides_template_path(technology, template_name)
            if is_default else named_catalogue_path(technology, template_name, template_name)
        )
        entries = [entry for _index, entry in sorted(enumerate(parse_catalog_csv(catalogue_content, technology)), key=lambda item: (item[1].slide, item[0]))]
        content = catalogue_csv(entries)
        # The lock only covers the short atomic replacements. Expensive
        # metadata and audit writes run after the response is sent.
        with TEMPLATE_SAVE_LOCK:
            if is_default:
                atomic_write_template(named_catalogue_path(technology, template_name, template_name), content)
            atomic_write_template(destination, content)
    except ValueError as exc:
        if wants_json:
            return JSONResponse({'detail': str(exc)}, status_code=400)
        return render_admin_template(request, user, error=str(exc), status_code=400)
    except (FileNotFoundError, OSError, sqlite3.Error) as exc:
        detail = f'Unable to save the Slides Template: {exc}'
        if wants_json:
            return JSONResponse({'detail': detail}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return render_admin_template(request, user, error=detail, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    chart_rows = sum(1 for entry in entries if entry.source_kind)
    task_repository = Repository(Path(repository.db_path), Path(repository.global_db_path))
    background_tasks.add_task(finalize_template_save, task_repository, user.username, technology, template_name, chart_rows)
    if wants_json:
        return JSONResponse({
            'template': template_name,
            'technology': technology,
            'chart_rows': chart_rows,
        })
    query = urlencode({'catalogue_technology': technology, 'catalogue_id': catalogue_id})
    return RedirectResponse(f'/admin?{query}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/chart-preview')
async def preview_report_template_chart(
    request: Request,
    technology: str,
    catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    """Preview one unsaved editor chart against ready CDRs in this workspace."""
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before previewing chart data.')
    technology = technology.strip().lower()
    catalogue = _named_catalogue(technology, catalogue_id) if technology in TEMPLATE_NAMES else None
    if not catalogue:
        raise HTTPException(status_code=404, detail='Slides Template not found.')
    try:
        payload = await request.json()
        dimensions = load_workspace_calculated_dimensions()
        entries = [
            replace(entry, calculated_dimensions=dimensions)
            for entry in parse_catalog_csv(str(payload.get('catalogue_content') or ''), technology)
        ]
        row_index = int(payload.get('row_index'))
        entry = entries[row_index]
        editable = payload.get('definition') if isinstance(payload.get('definition'), dict) else {}
        entry = replace(entry, **_temporary_chart_definition_changes(editable))
    except (ValueError, TypeError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f'Unable to preview this chart: {exc}') from exc
    if not entry.source_kind:
        raise HTTPException(status_code=400, detail='Only chart rows with a CDR source can be previewed.')

    try:
        page = max(0, int(payload.get('page') or 0))
        page_size = max(1, min(int(payload.get('page_size') or 100), 250))
        raw_column_filters = payload.get('column_filters') if isinstance(payload.get('column_filters'), dict) else {}
        column_filters = {
            str(column): tuple(str(value) for value in values)
            for column, values in raw_column_filters.items() if isinstance(values, list)
        }
        cache_material = json.dumps({
            'workspace': str(active_workspace.database_path), 'catalogue': str(payload.get('catalogue_content') or ''),
            'row': row_index, 'definition': editable, 'technology': technology,
        }, sort_keys=True, default=str)
        selected_datasets = [
            serialize_dataset_row(dataset)
            for dataset in repository.list_datasets()
            if str(dataset['dataset_kind'] or '').casefold() == entry.source_kind and dataset['status'] == 'ready'
        ]
        if not selected_datasets:
            raise HTTPException(status_code=400, detail=f'No processed {entry.cdr_source} datasets are available in the active workspace.')
        cache_key = hashlib.sha256(json.dumps({
            'preview': cache_material,
            'dataset_versions': [
                (item['id'], item.get('updated_at'), item.get('processed_at'), item.get('normalization_version'))
                for item in selected_datasets
            ],
        }, sort_keys=True, default=str).encode('utf-8')).hexdigest()
        cached = CHART_PREVIEW_DATA_CACHE.get(cache_key)
        if cached is None:
            # The chart definition and source data do not change while the user
            # moves between pages. The shared reporting table already contains
            # the materialized CDR rows, so use it rather than rebuilding a
            # pandas frame from every individual CDR table.
            full_preview, base_summary = preview_catalog_chart_data(
                _combined_reporting_frame(selected_datasets, technology, [entry], False), entry, limit=100_000,
            )
            cached = (full_preview, base_summary)
            CHART_PREVIEW_DATA_CACHE[cache_key] = cached
            # Keep temporary preview state bounded; the newest entry is always retained.
            while len(CHART_PREVIEW_DATA_CACHE) > 12:
                CHART_PREVIEW_DATA_CACHE.pop(next(iter(CHART_PREVIEW_DATA_CACHE)))
        full_preview, base_summary = cached
        filtered_preview = full_preview
        for column, values in column_filters.items():
            if column in filtered_preview.columns and values:
                accepted = set(values)
                filtered_preview = filtered_preview[filtered_preview[column].map(lambda value: '' if pd.isna(value) else str(value)).isin(accepted)]
        offset = page * page_size
        preview = filtered_preview.iloc[offset:offset + page_size].copy()
        summary = {
            **base_summary,
            'shown_rows': len(preview.index), 'visible_rows': len(filtered_preview.index), 'page_offset': offset,
            'columns': list(preview.columns),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({
        'chart_title': entry.chart_title or f'Slide {entry.slide}',
        'source': entry.cdr_source,
        'filters': entry.filters or 'No filters',
        'summary': summary,
        'columns': summary.get('columns', []),
        'filter_values': summary.get('filter_values', {}),
        'rows': preview.where(pd.notna(preview), '').astype(str).to_dict(orient='records'),
    })


@app.post('/admin/report-templates/{technology}/{catalogue_id}/chart-image-preview')
async def preview_report_template_chart_image(
    request: Request,
    technology: str,
    catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> Response:
    """Render one unsaved editor chart using the regular report renderer."""
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before previewing a chart.')
    technology = technology.strip().lower()
    catalogue = _named_catalogue(technology, catalogue_id) if technology in TEMPLATE_NAMES else None
    if not catalogue:
        raise HTTPException(status_code=404, detail='Slides Template not found.')
    try:
        payload = await request.json()
        dimensions = load_workspace_calculated_dimensions()
        entries = [
            replace(entry, calculated_dimensions=dimensions)
            for entry in parse_catalog_csv(str(payload.get('catalogue_content') or ''), technology)
        ]
        entry = entries[int(payload.get('row_index'))]
        editable = payload.get('definition') if isinstance(payload.get('definition'), dict) else {}
        entry = replace(entry, **_temporary_chart_definition_changes(editable))
    except (ValueError, TypeError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f'Unable to preview this chart: {exc}') from exc
    if not entry.source_kind:
        raise HTTPException(status_code=400, detail='Only chart rows with a CDR source can be previewed.')
    selected_datasets: list[dict[str, Any]] = []
    for dataset in repository.list_datasets():
        if str(dataset['dataset_kind'] or '').casefold() != entry.source_kind or dataset['status'] != 'ready':
            continue
        selected_datasets.append(serialize_dataset_row(dataset))
    if not selected_datasets:
        raise HTTPException(status_code=400, detail=f'No processed {entry.cdr_source} datasets are available in the active workspace.')
    query_columns = reporting_query_columns(entry.source_kind, [entry], False)
    frame_key = _chart_preview_cache_key('template-editor-source-frame', {
        'dataset_versions': [(item['id'], item.get('updated_at'), item.get('processed_at'), item.get('normalization_version')) for item in selected_datasets],
        'technology': technology,
        'columns': query_columns,
    })
    def load_frame() -> pd.DataFrame:
        return _combined_reporting_frame(selected_datasets, technology, [entry], False)
    frame = _bounded_preview_frame(CHART_PREVIEW_FRAME_CACHE, frame_key, load_frame, 4)
    filtered = _cached_filtered_chart_frame(frame_key, frame, entry, False)
    try:
        image = render_catalog_chart_preview(filtered, entry, prefiltered=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=image, media_type='image/png')


@app.get('/admin/report-templates/{technology}/export')
def export_report_catalogue(technology: str, user: SessionUser = Depends(admin_user)) -> Response:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    active = next((item for item in report_catalogue_options(technology) if item['active']), None)
    if not active:
        raise HTTPException(status_code=404, detail='Slides Template not found')
    # Export is a file retrieval operation. Keep legacy/manual filter captions
    # intact even when they cannot be executed as current Filter Builder rules.
    entries = load_template_catalogue(active['path'], technology, validate_filters=False)
    filename = template_download_filename(active['name']) if active else f'{technology.upper()} Slide Template.csv'
    return Response(
        content=catalogue_csv(entries),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.get('/admin/report-templates/export-selected')
def export_selected_report_catalogue(
    catalogue_selection: str,
    user: SessionUser = Depends(admin_user),
) -> Response:
    if ':' not in catalogue_selection:
        raise HTTPException(status_code=400, detail='Select a Slides Template to export.')
    technology, catalogue_id = catalogue_selection.split(':', 1)
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    catalogue = next((item for item in report_catalogue_options(technology) if item['identifier'] == catalogue_id), None)
    if not catalogue:
        raise HTTPException(status_code=404, detail='Slides Template not found')
    return Response(
        content=catalogue_csv(load_template_catalogue(catalogue['path'], technology, validate_filters=False)),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{template_download_filename(catalogue["name"])}"'},
    )


@app.get('/admin/report-templates/{technology}/{catalogue_id}/export')
def export_named_report_catalogue(technology: str, catalogue_id: str, user: SessionUser = Depends(admin_user)) -> Response:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    catalogue = next((item for item in report_catalogue_options(technology) if item['identifier'] == catalogue_id), None)
    if not catalogue:
        raise HTTPException(status_code=404, detail='Slides Template not found')
    entries = load_template_catalogue(catalogue['path'], technology, validate_filters=False)
    filename = template_download_filename(catalogue['name'])
    return Response(
        content=catalogue_csv(entries),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.post('/admin/users', response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    workspace_ids: list[str] = Form(default=[]),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    try:
        normalized_role = role.strip().lower()
        if normalized_role not in {'admin', 'user', 'super-admin'}:
            raise ValueError('Unsupported role')
        if user.role != 'super-admin' and normalized_role not in {'admin', 'user'}:
            raise ValueError('Only super-admins can create super-admin users.')
        repository.create_user(username, password, normalized_role)
        created = repository.get_user_by_id(max(int(row['id']) for row in repository.list_users() if row['username'] == username.strip()))
        if created:
            if user.role == 'super-admin':
                repository.set_user_workspace_access(int(created['id']), workspace_ids)
        repository.add_log(user.username, 'create_user', username)
        return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        return render_admin_template(request, user, error=str(exc), status_code=400)


@app.post('/admin/users/{target_user_id}/update', response_class=HTMLResponse)
def update_user_account(
    request: Request,
    target_user_id: int,
    username: str = Form(...),
    password: str = Form(''),
    role: str = Form(...),
    active: str | None = Form(default=None),
    workspace_ids: list[str] = Form(default=[]),
    edited_field: str = Form(default=''),
    user: SessionUser = Depends(admin_user),
) -> Response:
    def wants_json() -> bool:
        return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def payload_for(row) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            'id': int(row['id']),
            'username': row['username'],
            'role': row['role'],
            'active': bool(row['active']),
            'workspace_ids': repository.list_user_workspace_ids(int(row['id'])),
        }

    def failure(message: str, status_code: int, row=None) -> Response:
        if wants_json():
            return JSONResponse({'detail': message, 'user': payload_for(row)}, status_code=status_code)
        return render_admin_template(request, user, error=message, status_code=status_code)

    normalized_role = role.strip().lower()
    target_user = repository.get_user_by_id(target_user_id)
    if not target_user:
        return failure('User not found', 404)
    normalized_username = username.strip() if not edited_field or edited_field == 'username' else str(target_user['username'])
    if not normalized_username:
        return failure('Username cannot be empty', 400, target_user)
    if normalized_role not in {'admin', 'user', 'super-admin'}:
        return failure('Unsupported role', 400, target_user)
    if user.role != 'super-admin' and (
        target_user['role'] == 'super-admin' or normalized_role == 'super-admin'
    ):
        return failure('Only super-admins can assign or modify super-admin accounts.', 403, target_user)
    will_be_active = active == '1'
    if would_remove_required_super_admin(target_user, normalized_role, will_be_active):
        return failure(
            'At least one active super-admin must remain. Create or activate another super-admin before changing or deactivating this account.',
            400,
            target_user,
        )
    if would_remove_last_active_admin(target_user, normalized_role, will_be_active):
        return failure('At least one active admin user must remain. You cannot demote or deactivate the last active admin.', 400, target_user)
    try:
        repository.update_user(
            target_user_id,
            normalized_username,
            normalized_role,
            will_be_active,
            password.strip() or None,
        )
        if user.role == 'super-admin':
            repository.set_user_workspace_access(target_user_id, workspace_ids)
        repository.add_log(
            user.username,
            'update_user',
            json.dumps({'user_id': target_user_id, 'username': normalized_username, 'role': normalized_role, 'active': will_be_active}),
        )
        updated_user = repository.get_user_by_id(target_user_id)
        if wants_json():
            return JSONResponse({'ok': True, 'user': payload_for(updated_user)})
        return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        return failure(str(exc), 400, repository.get_user_by_id(target_user_id))


@app.post('/admin/users/{target_user_id}/delete', response_class=HTMLResponse)
def delete_user_account(
    request: Request,
    target_user_id: int,
    user: SessionUser = Depends(admin_user),
) -> Response:
    target_user = repository.get_user_by_id(target_user_id)
    if not target_user:
        return render_admin_template(request, user, error='User not found', status_code=404)
    if user.role != 'super-admin' and target_user['role'] == 'super-admin':
        return render_admin_template(
            request,
            user,
            error='Only super-admins can assign or modify super-admin accounts.',
            status_code=403,
        )
    if target_user['username'] == user.username:
        return render_admin_template(request, user, error='You cannot delete the current signed-in admin user', status_code=400)
    if target_user['role'] == 'super-admin' and repository.count_super_admin_users() <= 1:
        return render_admin_template(
            request,
            user,
            error='At least one super-admin must remain. Create another super-admin before deleting this account.',
            status_code=400,
        )
    if target_user['role'] == 'super-admin' and target_user['active'] and repository.count_super_admin_users(active_only=True) <= 1:
        return render_admin_template(
            request,
            user,
            error='At least one active super-admin must remain. Create or activate another super-admin before deleting this account.',
            status_code=400,
        )
    if target_user['role'] in {'admin', 'super-admin'} and target_user['active'] and repository.count_active_admin_users() <= 1:
        return render_admin_template(
            request,
            user,
            error='At least one active admin user must remain. You cannot delete the last active admin.',
            status_code=400,
        )
    try:
        repository.delete_user(target_user_id)
        repository.add_log(
            user.username,
            'delete_user',
            json.dumps({'user_id': target_user_id, 'username': target_user['username']}),
        )
        return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        return render_admin_template(request, user, error=str(exc), status_code=400)


@app.post('/admin/users/{target_user_id}/reset-password', response_class=HTMLResponse)
def reset_user_password(
    request: Request,
    target_user_id: int,
    user: SessionUser = Depends(admin_user),
) -> Response:
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def failure(message: str, status_code: int) -> Response:
        if wants_json:
            return JSONResponse({'detail': message}, status_code=status_code)
        return render_admin_template(request, user, error=message, status_code=status_code)

    target_user = repository.get_user_by_id(target_user_id)
    if not target_user:
        return failure('User not found', 404)
    if user.role != 'super-admin' and target_user['role'] == 'super-admin':
        return failure('Only super-admins can assign or modify super-admin accounts.', 403)
    default_passwords = {
        'super': 'super123',
        'admin': 'admin123',
        'demo': 'demo123',
    }
    reset_password = default_passwords.get(str(target_user['username']).casefold(), 'Ericsson123')
    repository.update_password(str(target_user['username']), reset_password)
    repository.add_log(user.username, 'reset_user_password', json.dumps({'user_id': target_user_id, 'username': target_user['username']}))
    if wants_json:
        return JSONResponse({'ok': True, 'user': {'id': int(target_user['id']), 'username': target_user['username']}})
    return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)


def _catalogue_slide_blocks(entries: list[CatalogEntry]) -> list[list[CatalogEntry]]:
    blocks: list[list[CatalogEntry]] = []
    for entry in entries:
        if not blocks or blocks[-1][0].slide != entry.slide:
            blocks.append([])
        blocks[-1].append(entry)
    return blocks


@app.get('/api/admin/report-templates/copy-options')
def report_catalogue_copy_options(user: SessionUser = Depends(admin_user)) -> JSONResponse:
    templates: list[dict[str, Any]] = []
    for technology in TEMPLATE_NAMES:
        for catalogue in report_catalogue_options(technology):
            try:
                entries = load_template_catalogue(catalogue['path'], technology, validate_filters=False)
            except ValueError:
                entries = []
            slides = [
                {
                    'position': index + 1,
                    'slide': block[0].slide,
                    'title': block[0].slide_title or f'Slide {index + 1}',
                    'charts': len(block),
                }
                for index, block in enumerate(_catalogue_slide_blocks(entries))
            ]
            templates.append({
                'technology': technology,
                'identifier': catalogue['identifier'],
                'name': catalogue['name'],
                'slides': slides,
            })
    return JSONResponse({'templates': templates})


async def _save_workspace_dimensions(request: Request, user: SessionUser) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before managing auto-calculated fields.')
    try:
        payload = await request.json()
        previous = load_workspace_calculated_dimensions()
        dimensions = write_workspace_calculated_dimensions(payload.get('dimensions'))
        affected_sources = affected_calculated_dimension_sources(previous, dimensions)
        renames = calculated_dimension_rename_map(payload, previous, dimensions)
        renamed_templates = rename_calculated_dimension_template_references(renames)
        job = start_auto_calculated_field_job(
            active_workspace, previous, dimensions, renames, user.username,
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail=f'Unable to save auto-calculated fields: {exc}') from exc
    repository.add_log(user.username, 'save_workspace_calculated_dimensions', json.dumps({
        'workspace': active_workspace.id, 'count': len(dimensions), 'materialization_job': job['id'],
        'renamed_templates': renamed_templates, 'affected_sources': sorted(affected_sources),
    }))
    return JSONResponse({
        'dimensions': calculated_dimensions_json(dimensions),
        'materialization_job': job['id'],
        'materialization_status_url': f'/api/workspace/auto-calculated-fields/materialization/{job["id"]}',
        'renamed_templates': renamed_templates,
        'notice': (
            'The fields were saved. Updating applicable CDR tables can take a while and is running in the background.'
            if affected_sources else 'The fields were already up to date; no CDR tables required changes.'
        ),
    })


@app.put('/api/workspace/calculated-dimensions')
async def save_workspace_calculated_dimensions(
    request: Request, user: SessionUser = Depends(current_user),
) -> JSONResponse:
    return await _save_workspace_dimensions(request, user)


@app.put('/api/admin/report-templates/{technology}/{catalogue_id}/calculated-dimensions')
async def save_report_template_calculated_dimensions(
    request: Request, technology: str, catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    """Backward-compatible editor endpoint backed by the active workspace."""
    return await _save_workspace_dimensions(request, user)


@app.get('/api/workspace/auto-calculated-fields/materialization/{job_id}')
def auto_calculated_field_materialization_status(
    job_id: str, user: SessionUser = Depends(current_user),
) -> JSONResponse:
    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        job = dict(AUTO_CALCULATED_FIELD_JOBS.get(job_id) or {})
    if not job or not repository.user_has_workspace_access(user.username, str(job['workspace_id'])):
        raise HTTPException(status_code=404, detail='Materialization job not found.')
    return JSONResponse({
        key: value for key, value in job.items()
        if key not in {'previous_definitions', 'affected_sources', 'renames', 'username'}
    })


@app.get('/api/workspace/auto-calculated-fields/materialization')
def latest_auto_calculated_field_materialization(
    user: SessionUser = Depends(current_user),
) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace first.')
    with AUTO_CALCULATED_FIELD_JOBS_LOCK:
        workspace_jobs = [
            dict(job) for job in AUTO_CALCULATED_FIELD_JOBS.values()
            if job.get('workspace_id') == active_workspace.id
        ]
    if workspace_jobs:
        active_jobs = [job for job in workspace_jobs if job.get('status') in {'queued', 'processing'}]
        processing_jobs = [job for job in active_jobs if job.get('status') == 'processing']
        job = max(processing_jobs or active_jobs or workspace_jobs, key=lambda item: float(item.get('created_at') or 0))
        return JSONResponse({
            key: value for key, value in job.items()
            if key not in {'previous_definitions', 'affected_sources', 'renames', 'username'}
        })
    workspace_state = repository.get_workspace_state('calculated_dimensions_need_materialization')
    if workspace_state in {'1', 'processing'}:
        return JSONResponse({
            'status': 'processing', 'completed': 0, 'total': 0,
            'message': 'Updating CDR tables', 'workspace_id': active_workspace.id,
        })
    return JSONResponse({
        'status': 'idle', 'completed': 0, 'total': 0,
        'message': 'All materialized fields are up to date', 'workspace_id': active_workspace.id,
    })


@app.post('/api/workspace/auto-calculated-fields/rematerialize')
def rematerialize_workspace_auto_calculated_fields(
    user: SessionUser = Depends(current_user),
) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before rematerializing auto-calculated fields.')
    current = list(load_workspace_calculated_dimensions())
    job = start_auto_calculated_field_job(
        active_workspace, (), current, {}, user.username,
    )
    repository.add_log(user.username, 'rematerialize_workspace_auto_calculated_fields', json.dumps({
        'workspace': active_workspace.id, 'count': len(current), 'materialization_job': job['id'],
    }))
    return JSONResponse({
        'materialization_job': job['id'],
        'materialization_status_url': f'/api/workspace/auto-calculated-fields/materialization/{job["id"]}',
        'notice': 'All applicable auto-calculated fields are being rematerialized in the background.',
    })


@app.get('/workspace/calculated-dimensions/export')
def export_workspace_calculated_dimensions(
    name: str = '', user: SessionUser = Depends(current_user),
) -> Response:
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before exporting auto-calculated fields.')
    dimensions = list(load_workspace_calculated_dimensions())
    if name.strip():
        identity = _normalise_catalogue_dimension_name(name)
        dimensions = [item for item in dimensions if _normalise_catalogue_dimension_name(item.name) == identity]
        if not dimensions:
            raise HTTPException(status_code=404, detail='Auto-calculated field not found.')
    content = json.dumps(calculated_dimensions_json(dimensions), indent=2, ensure_ascii=False).encode('utf-8')
    suffix = re.sub(r'[^A-Za-z0-9_-]+', '-', name.strip()).strip('-') if name.strip() else 'all'
    filename = f'{active_workspace.name}-auto-calculated-fields-{suffix}.json'.replace('"', '')
    repository.add_log(user.username, 'export_workspace_calculated_dimensions', json.dumps({
        'workspace': active_workspace.id, 'count': len(dimensions),
    }))
    return Response(content, media_type='application/json', headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.post('/workspace/calculated-dimensions/import')
async def import_workspace_calculated_dimensions(
    dimensions_file: UploadFile = File(...),
    user: SessionUser = Depends(current_user),
) -> RedirectResponse:
    if not active_workspace:
        raise HTTPException(status_code=400, detail='Open a workspace before importing auto-calculated fields.')
    try:
        payload = json.loads((await dimensions_file.read()).decode('utf-8-sig'))
        imported = parse_calculated_dimensions(payload)
        previous = list(load_workspace_calculated_dimensions())
        merged = { _normalise_catalogue_dimension_name(item.name): item for item in previous }
        for item in imported:
            merged[_normalise_catalogue_dimension_name(item.name)] = item
        saved = write_workspace_calculated_dimensions(calculated_dimensions_json(merged.values()))
        affected_sources = affected_calculated_dimension_sources(previous, saved)
        job = start_auto_calculated_field_job(
            active_workspace, previous, saved, {}, user.username,
        )
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return RedirectResponse(f'/workspace?{urlencode({"workspace_error": str(exc)})}#calculated-dimensions', status_code=303)
    repository.add_log(user.username, 'import_workspace_calculated_dimensions', json.dumps({
        'workspace': active_workspace.id, 'imported': len(imported), 'count': len(saved),
    }))
    notice = (
        f'Imported {len(imported)} auto-calculated fields. Applicable CDR tables are being updated '
        'in the background; you can continue working.'
        if affected_sources else
        f'Imported {len(imported)} auto-calculated fields; matching definitions were already up to date.'
    )
    query = urlencode({'workspace_notice': notice, 'auto_fields_job_id': job['id']})
    return RedirectResponse(f'/workspace?{query}#calculated-dimensions', status_code=303)


@app.post('/admin/report-templates/{technology}/{catalogue_id}/copy-items')
async def copy_report_catalogue_items(
    request: Request,
    technology: str,
    catalogue_id: str,
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail='The copy request is not valid JSON.') from exc
    technology = technology.strip().lower()
    kind = str(payload.get('kind') or '').strip().lower()
    target_technology = str(payload.get('target_technology') or '').strip().lower()
    target_identifier = str(payload.get('target_identifier') or '').strip()
    if technology not in TEMPLATE_NAMES or target_technology not in TEMPLATE_NAMES or kind not in {'slide', 'chart'}:
        raise HTTPException(status_code=400, detail='The template copy request is invalid.')
    try:
        source_entries = parse_catalog_csv(str(payload.get('catalogue_content') or ''), technology, validate_filters=False)
        source_index = int(payload.get('source_row_index'))
        source_entry = source_entries[source_index]
        target = next((item for item in report_catalogue_options(target_technology) if item['identifier'] == target_identifier), None)
        if not target:
            raise FileNotFoundError('Destination Slides Template not found.')
        try:
            target_entries = load_template_catalogue(target['path'], target_technology, validate_filters=False)
        except ValueError as exc:
            if str(exc) != 'The report template does not contain any rows.':
                raise
            target_entries = []
        target_blocks = _catalogue_slide_blocks(target_entries)
        source_blocks = _catalogue_slide_blocks(source_entries)
        if kind == 'slide':
            source_block = next(block for block in source_blocks if source_entry in block)
            position = max(0, min(int(payload.get('slide_position', len(target_blocks))), len(target_blocks)))
            target_blocks.insert(position, [replace(entry) for entry in source_block])
        else:
            target_slide_index = int(payload.get('target_slide_index'))
            if target_slide_index < 0 or target_slide_index >= len(target_blocks):
                raise ValueError('Choose an existing destination slide.')
            target_block = target_blocks[target_slide_index]
            target_slide = target_block[0]
            copied = replace(
                source_entry,
                slide=target_slide.slide,
                slide_title=target_slide.slide_title,
                slide_subtitle=target_slide.slide_subtitle,
                layout=target_slide.layout,
            )
            position = max(0, min(int(payload.get('chart_position', len(target_block))), len(target_block)))
            target_block.insert(position, copied)
        copied_entries = [
            replace(entry, slide=slide_index)
            for slide_index, block in enumerate(target_blocks, start=1)
            for entry in block
        ]
        content = catalogue_csv(copied_entries)
        with TEMPLATE_SAVE_LOCK:
            atomic_write_template(Path(target['path']), content)
            if target['active']:
                atomic_write_template(named_catalogue_path(target_technology, target_identifier, target_identifier), content)
    except (IndexError, StopIteration, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or 'The selected template content is unavailable.') from exc
    except (FileNotFoundError, OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail=f'Unable to copy template content: {exc}') from exc
    repository.add_log(user.username, 'copy_report_template_content', json.dumps({
        'kind': kind,
        'source_technology': technology,
        'source_template': catalogue_id,
        'target_technology': target_technology,
        'target_template': target_identifier,
    }))
    return JSONResponse({'copied': True, 'kind': kind, 'target_template': target_identifier})


templates.env.globals['format_extra_filters'] = format_extra_filters
templates.env.globals['format_aggregation_overrides'] = format_aggregation_overrides
templates.env.globals['format_cdf_overrides'] = format_cdf_overrides
templates.env.globals['format_aggregation_label'] = format_aggregation_label
