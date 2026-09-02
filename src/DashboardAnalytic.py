from __future__ import annotations

import json
import io
import os
import re
import secrets
import hashlib
import shutil
import sqlite3
import warnings
import tempfile
import zipfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from threading import Lock, Thread
from time import monotonic
from typing import Annotated
from typing import Any
from typing import Callable
from urllib.parse import urlencode
from uuid import uuid4

import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import QueryParams

from src.config import PROJECT_ROOT, settings
from src.modules.analytics import build_analysis
from src.modules.auth import SessionUser, verify_password
from src.modules.cdr_reporting import CATALOG_HEADERS, CHART_TYPES, STRUCTURAL_SLIDE_TYPES, TEMPLATE_NAMES, active_catalog_path, assign_cdr_vendors, catalogue_csv, classify_sessions, convert_catalog_csv, ensure_report_vendor_group, enrich_multivendor, load_catalog_csv, parse_catalog_csv, parse_catalog_filters, parse_catalog_grouping, render_cdr_report, update_catalogue_document
from src.modules.exports import POWERPOINT_EXPORT_VERSION, export_powerpoint_report, export_word_report
from src.modules.ingestion import add_three_gcid_column, add_vfuk_gcid_column, get_excel_sheet_columns, infer_dataset_kind, load_dataset, summarise_dataset
from src.modules.repository import Repository
from src.modules.workspaces import Workspace, WorkspaceRegistry
from src.version import __app_name__, __release_date__, __version__
from src.utils.filesystem import ensure_directories, safe_join


SESSION_COOKIE = 'bench_automations_session'
SESSIONS: dict[str, SessionUser] = {}
ANALYSIS_CACHE: dict[str, dict[str, Any]] = {}
DATAFRAME_CACHE: dict[str, pd.DataFrame] = {}
STOP_REQUESTS: set[int] = set()
STOP_REQUESTS_LOCK = Lock()
DATASET_PROCESSING_LOCKS: dict[str, Lock] = {}
DATASET_PROCESSING_LOCKS_LOCK = Lock()
EXPORT_JOBS: dict[str, dict[str, Any]] = {}
EXPORT_JOBS_LOCK = Lock()
EXPORT_PACKAGE_TTL = timedelta(hours=24)
DEFAULT_SLIDES_TEMPLATES_DIR = settings.slides_templates_dir
application_config_dir = settings.database_path.parent


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
LEGACY_VENDOR_MAPPING_FAILURE_MARKERS = (
    'to assign vendors',
    'assign vendors',
    'duplicate column name: vendor_2',
)
DATASET_NORMALIZATION_VERSION = 6
DERIVED_CDR_PREVIEW_COLUMNS = frozenset({'Call Family', 'Test Family'})
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


def materialize_cdr_derived_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Add stable, report-facing CDR dimensions as inspectable columns."""
    result = frame.copy()
    columns = {str(column).casefold(): str(column) for column in result.columns}

    def column(*names: str) -> str | None:
        return next((columns.get(name.casefold()) for name in names if columns.get(name.casefold())), None)

    session_column = column('Session_Type', 'session_type')
    call_mode_column = column('L1_Call_Mode_A', 'L1_Call_Mode_B', 'Call_Mode', 'call_mode')
    if session_column:
        session = result[session_column].fillna('').astype(str)
        family = pd.Series('CALL', index=result.index, dtype='string')
        family.loc[session.str.contains('multirab', case=False, na=False)] = 'MultiRAB'
        family.loc[session.str.contains('whatsapp', case=False, na=False)] = 'WhatsApp'
        family.loc[session.str.contains('volte', case=False, na=False)] = 'VoLTE'
        family.loc[session.str.contains('vonr', case=False, na=False)] = 'VoNR'
        if call_mode_column:
            modes = result[call_mode_column].fillna('').astype(str)
            family.loc[(family == 'CALL') & modes.str.contains('volte', case=False, na=False)] = 'VoLTE'
            family.loc[(family == 'CALL') & modes.str.contains('vonr', case=False, na=False)] = 'VoNR'
        result['Call Family'] = family

    type_column = column('Type_of_Test', 'Test_Type', 'test_type')
    name_column = column('Test_Name', 'test_name')
    if type_column or name_column:
        test_family = (
            result[type_column].fillna('').astype(str)
            if type_column else pd.Series('', index=result.index, dtype='string')
        )
        if name_column:
            test_names = result[name_column].fillna('').astype(str)
            test_family.loc[test_names.str.contains('youtube', case=False, na=False)] = 'YouTube'
            test_family.loc[test_names.str.contains('fdfs', case=False, na=False)] = 'FDFS'
            test_family.loc[test_names.str.contains('fdtt', case=False, na=False)] = 'FDTT'
        result['Test Family'] = test_family
    return result
HELP_HOME_DOCUMENT = '00-help.md'
HELP_NAVIGATION_DOCUMENTS = (
    HELP_HOME_DOCUMENT,
    '01-configuration-file.md',
    '02-web-interface.md',
    '03-data-ingestion.md',
    '04-e2e-dashboard-analysis.md',
    '05-e2e-ppt-reporting.md',
    '06-admin-panel.md',
    '07-docker-deployment.md',
    '08-project-structure.md',
    '09-roadmap.md',
)
HELP_DOCUMENT_LABELS = {
    '04-e2e-dashboard-analysis.md': 'E2E Dashboard',
    '05-e2e-ppt-reporting.md': 'E2E PowerPoint Reporting',
}
REPORT_CATALOGUE_DOCUMENT = PROJECT_ROOT / 'help' / '05-e2e-ppt-reporting.md'


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


def named_catalogue_path(technology: str, identifier: str, template_name: str | None = None) -> Path:
    """Return the canonical library location, named exactly after the template."""
    filename = template_filename(template_name) if template_name else f'{identifier}.csv'
    return settings.slides_templates_dir / 'library' / technology / filename


def synchronize_template_file_names(technology: str) -> None:
    """Synchronize the per-workspace index with the shared config CSVs."""
    library_dir = settings.slides_templates_dir / 'library' / technology
    library_dir.mkdir(parents=True, exist_ok=True)
    default_dir = settings.slides_templates_dir / 'default' / technology
    default_dir.mkdir(parents=True, exist_ok=True)
    existing = {str(row['name']): bool(row['is_default']) for row in repository.list_report_templates(technology)}
    default_files = sorted(default_dir.glob('*.csv'))
    physical_names = {catalogue_registry_key(path.stem) for path in [*library_dir.glob('*.csv'), *default_files]}
    for name in set(existing) - physical_names:
        repository.delete_report_template(technology, name)
        existing.pop(name, None)
    for path in [*sorted(library_dir.glob('*.csv')), *default_files]:
        name = catalogue_registry_key(path.stem)
        if name not in existing:
            repository.add_report_template(technology, name, is_default=False)
            existing[name] = False
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
    return load_catalog_csv(reporting_catalog_path(technology), technology)


def catalogue_editor_columns() -> dict[str, list[str]]:
    """Offer the processed CDR fields that can be used in the template editor."""
    common = {'Operator', 'Campaign', 'source_sheet', 'vendor', 'RAT_A', 'RAT'}
    derived = {'Call Family', 'Test Family', 'Rate Bucket', 'Threshold', 'Buckets'}
    columns: dict[str, set[str]] = {
        'cdr-data': set(common) | {'Test_Result', 'Test_Name', 'Type_of_Test', 'Direction', 'G Level 4'},
        'cdr-voice': set(common) | {'Call_Status', 'Session_Type', 'Call_Setup_Time', 'G Level 4'},
        'cdr-speech': set(common) | {'Call_Status', 'Session_Type', 'LQ', 'G Level 4'},
    }
    for dataset in repository.list_datasets():
        kind = str(dataset['dataset_kind'] or '').casefold()
        source = f'cdr-{kind}'
        if source not in columns or dataset['status'] != 'ready':
            continue
        columns[source].update(str(column) for column in repository.list_dataset_row_columns(dataset['id']))
    return {source: sorted(values | derived, key=str.casefold) for source, values in columns.items()}


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
    try:
        entries = load_catalog_csv(catalogue['path'], technology)
    except ValueError as exc:
        # A newly created template deliberately contains only the current CSV
        # headers.  It is valid to open that blank canvas in the editor, while
        # the report-generation parser continues to reject a template that
        # has not yet been configured with any slides.
        if str(exc) != 'The report template does not contain any rows.':
            raise
        entries = []
    # CSVs are allowed to have been edited out of order. The editor always
    # presents coherent slide blocks while preserving the chart order inside a
    # slide when it is saved again.
    entries = [entry for _index, entry in sorted(enumerate(entries), key=lambda item: (item[1].slide, item[0]))]
    rows = [
        {
            'Slide': entry.slide,
            'Slide tittle': entry.slide_title,
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
    columns = catalogue_editor_columns()
    return {
        'technology': technology,
        'catalogue': catalogue,
        'rows': rows,
        'headers': CATALOG_HEADERS,
        'suggestions': {
            'layouts': catalogue_layout_names(technology),
            'chart_types': sorted(CHART_TYPES | STRUCTURAL_SLIDE_TYPES, key=str.casefold),
            'legend_positions': ['Top', 'Bottom', 'Left', 'Right'],
            'columns': columns,
        },
    }


def synchronize_reporting_catalogue_document() -> None:
    update_catalogue_document(
        REPORT_CATALOGUE_DOCUMENT,
        reporting_catalog_entries('nsa'),
        reporting_catalog_entries('sa'),
    )


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
    # Authentication and shared Slides Template metadata belong to the
    # application configuration database, not to the selected workspace.
    repository.set_global_database(application_config_dir / 'application.db')
    for path in (workspace.database_path.parent, workspace.input_dir, workspace.output_dir, workspace.export_dir):
        path.mkdir(parents=True, exist_ok=True)
    object.__setattr__(settings, 'database_path', workspace.database_path)
    object.__setattr__(settings, 'input_dir', workspace.input_dir)
    object.__setattr__(settings, 'output_dir', workspace.output_dir)
    object.__setattr__(settings, 'export_dir', workspace.export_dir)
    repository.db_path = workspace.database_path
    ANALYSIS_CACHE.clear()
    DATAFRAME_CACHE.clear()
    active_workspace = workspace
    if initialize:
        repository.initialize()
        synchronize_reporting_row_store()
        for technology in TEMPLATE_NAMES:
            synchronize_template_file_names(technology)
    return workspace


def close_active_workspace() -> None:
    global active_workspace
    if active_workspace:
        workspace_registry.close_active(active_workspace.id)
    ANALYSIS_CACHE.clear()
    DATAFRAME_CACHE.clear()
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


def format_workspace_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        value = size_bytes / (1024 ** 3)
        unit = 'GB'
    else:
        value = size_bytes / (1024 ** 2)
        unit = 'MB'
    formatted = f'{value:.1f}'.rstrip('0').rstrip('.')
    return f'{formatted} {unit}'


def migrate_uk_slides_templates_to_global_config() -> None:
    """Move the user-designated UK library into the shared config location."""
    source_root = PROJECT_ROOT / 'data' / 'workspaces' / 'UK' / 'slides-templates'
    if not source_root.exists() or not any(source_root.rglob('*.csv')):
        return
    for technology in TEMPLATE_NAMES:
        for area in ('library', 'default'):
            source_dir = source_root / area / technology
            source_files = sorted(source_dir.glob('*.csv')) if source_dir.exists() else []
            if not source_files:
                continue
            target_dir = DEFAULT_SLIDES_TEMPLATES_DIR / area / technology
            target_dir.mkdir(parents=True, exist_ok=True)
            for existing in target_dir.glob('*.csv'):
                existing.unlink()
            for source_file in source_files:
                shutil.move(str(source_file), str(target_dir / source_file.name))
    shutil.rmtree(source_root)


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
    # Versions before the global configuration database could leave copies of
    # users/template metadata inside workspace databases.  Clean every
    # workspace at startup so only config/application.db can own that state.
    for workspace in workspace_registry.list():
        workspace_repository = Repository(workspace.database_path, repository.global_db_path)
        workspace_repository.remove_legacy_global_tables()
        interrupted_datasets, interrupted_reports = workspace_repository.fail_interrupted_background_jobs()
        if interrupted_datasets or interrupted_reports:
            workspace_repository.add_log(
                'system',
                'recover_interrupted_background_jobs',
                json.dumps({'datasets': interrupted_datasets, 'reports': interrupted_reports}),
            )
    migrate_access = not repository.has_workspace_access_entries()
    for workspace in workspace_registry.list():
        if migrate_access:
            repository.grant_all_workspace_access(workspace.id)
    export_package_dir().mkdir(parents=True, exist_ok=True)
    _cleanup_expired_export_packages()
    migrate_uk_slides_templates_to_global_config()
    if (workspace_id := workspace_registry.active_id()):
        activate_workspace(workspace_id)
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
    numeric_columns = df.select_dtypes(include=['number']).columns.tolist()
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
        df = materialize_cdr_derived_columns(df)
    store_cached_dataset_frame(dataset_path, df)
    task_repository.replace_dataset_rows(dataset_id, df)
    if dataset_kind in CDR_DATASET_KINDS:
        task_repository.replace_reporting_rows(dataset_id, dataset_kind, df)
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
        frame = materialize_cdr_derived_columns(frame)
    repository.replace_dataset_rows(dataset_id, frame)
    dataset_kind = str(dataset.get('dataset_kind') or '').casefold()
    if dataset_kind in CDR_DATASET_KINDS:
        repository.replace_reporting_rows(dataset_id, dataset_kind, frame)
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
    header_workspaces = workspace_registry.list() if isinstance(template_user, SessionUser) else []
    header_workspace_access = workspace_access_map(template_user, header_workspaces) if isinstance(template_user, SessionUser) else {}
    payload = {
        'request': request,
        'app_name': __app_name__,
        'app_version': __version__,
        'app_release_date': __release_date__,
        'asset_version': asset_version,
        'static_path': lambda asset_path: str(request.app.url_path_for('static', path=asset_path)),
        'active_workspace': active_workspace,
        'active_workspace_size': format_workspace_size(workspace_disk_usage(active_workspace)) if active_workspace else None,
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


def _archive_file(archive: zipfile.ZipFile, source: Path, archive_name: str) -> None:
    archive.write(source, archive_name, compress_type=_archive_compression(source))


def _archive_database(archive: zipfile.ZipFile, database_path: Path, archive_name: str, scratch_dir: Path | None = None) -> None:
    """Add a consistent SQLite snapshot, including databases currently in WAL mode."""
    if not database_path.exists():
        return
    with tempfile.TemporaryDirectory(prefix='dashboard-analytic-export-', dir=scratch_dir) as temporary_dir:
        snapshot = Path(temporary_dir) / 'snapshot.db'
        with sqlite3.connect(database_path) as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        _archive_file(archive, snapshot, archive_name)


def _archive_tree(archive: zipfile.ZipFile, source: Path, archive_prefix: str, *, exclude_slides_templates: bool = False) -> None:
    if not source.exists():
        return
    for path in source.rglob('*'):
        if not path.is_file() or path.name.endswith(('-wal', '-shm')):
            continue
        relative_path = path.relative_to(source)
        if exclude_slides_templates and relative_path.parts and relative_path.parts[0] == 'slides-templates':
            continue
        _archive_file(archive, path, f'{archive_prefix}/{relative_path.as_posix()}')


def _workspace_archive_metadata(workspace: Workspace) -> dict[str, str]:
    return {'name': workspace.name, 'source_input_dir': str(workspace.input_dir)}


def _archive_workspace(archive: zipfile.ZipFile, workspace: Workspace, archive_prefix: str, scratch_dir: Path | None = None) -> None:
    _archive_database(archive, workspace.database_path, f'{archive_prefix}/database.sqlite', scratch_dir)
    _archive_tree(archive, workspace.input_dir, f'{archive_prefix}/input')
    _archive_tree(archive, workspace.export_dir, f'{archive_prefix}/exports')


def export_archive_filename(target: str) -> str:
    # The generated package is unique on the server, but a static download
    # filename makes it too easy to re-import an older browser download.
    # Include seconds so each visible download can be identified unambiguously.
    generated_at = datetime.now().strftime('%Y%m%d-%H%M%S')
    if target == 'config':
        return f'dashboard-analytic-config_{generated_at}.zip'
    if target == 'slides-templates':
        return f'dashboard-analytic-slides-templates_{generated_at}.zip'
    if target == 'config-with-templates':
        return f'dashboard-analytic-config-with-slides-templates_{generated_at}.zip'
    if target == 'full-environment':
        return f'dashboard-analytic-full-environment_{generated_at}.zip'
    if target.startswith('workspace:'):
        workspace = workspace_registry.get(target.removeprefix('workspace:'))
        if workspace:
            return f'{workspace.name}_{generated_at}.zip'
    raise ValueError('Select a valid export option.')


def build_export_archive_file(target: str, destination: Path) -> str:
    """Create a portable archive on disk, keeping large exports out of RAM."""
    filename = export_archive_filename(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # ``settings.database_path`` changes with the active workspace and the
    # registry lives with workspace data, so retain the configured app root.
    config_root = application_config_dir
    def archive_configuration(archive: zipfile.ZipFile, *, include_templates: bool) -> None:
        """Archive application configuration, with its database as a known payload.

        ``application.db`` owns users, roles, workspace access and the shared
        Slides Template registry.  Do not rely on the currently selected
        workspace when deciding which database to export.
        """
        application_database = application_config_dir / 'application.db'
        if not application_database.is_file():
            raise FileNotFoundError('The application configuration database was not found.')
        _archive_database(archive, application_database, 'config/application.db', destination.parent)
        for path in config_root.iterdir():
            if (
                path == application_database
                or path == workspace_registry.registry_path
                or path == settings.slides_templates_dir
                or not path.is_file()
                or path.name.endswith(('-wal', '-shm'))
            ):
                continue
            _archive_file(archive, path, f'config/{path.name}')
        if include_templates:
            _archive_tree(archive, settings.slides_templates_dir, 'config/slides-templates')

    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
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
            manifest = {
                'format': ARCHIVE_FORMAT,
                'version': ARCHIVE_VERSION,
                'kind': 'slides-templates',
                'includes_slides_templates': True,
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            _archive_tree(archive, settings.slides_templates_dir, 'slides-templates')
        elif target.startswith('workspace:'):
            workspace = workspace_registry.get(target.removeprefix('workspace:'))
            if not workspace:
                raise ValueError('Workspace not found.')
            manifest = {
                'format': ARCHIVE_FORMAT,
                'version': ARCHIVE_VERSION,
                'kind': 'workspace',
                'workspace': _workspace_archive_metadata(workspace),
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            _archive_workspace(archive, workspace, 'workspace', destination.parent)
        elif target == 'full-environment':
            workspaces = workspace_registry.list()
            manifest = {
                'format': ARCHIVE_FORMAT,
                'version': ARCHIVE_VERSION,
                'kind': 'full-environment',
                'includes_slides_templates': True,
                'workspaces': [
                    {**_workspace_archive_metadata(workspace), 'archive_path': f'workspaces/{index}'}
                    for index, workspace in enumerate(workspaces, start=1)
                ],
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            archive_configuration(archive, include_templates=True)
            for entry, workspace in zip(manifest['workspaces'], workspaces, strict=True):
                _archive_workspace(archive, workspace, str(entry['archive_path']), destination.parent)
        else:
            raise ValueError('Select a valid export option.')
    return filename


def build_export_archive(target: str) -> tuple[bytes, str]:
    """Compatibility helper for small programmatic exports and tests."""
    with tempfile.TemporaryDirectory(prefix='dashboard-analytic-export-') as temporary_dir:
        destination = Path(temporary_dir) / 'package.zip'
        filename = build_export_archive_file(target, destination)
        return destination.read_bytes(), filename


def _cleanup_expired_export_packages() -> None:
    package_dir = export_package_dir()
    if not package_dir.exists():
        return
    cutoff = datetime.now(timezone.utc).timestamp() - EXPORT_PACKAGE_TTL.total_seconds()
    active_paths: set[Path] = set()
    with EXPORT_JOBS_LOCK:
        for job in EXPORT_JOBS.values():
            if job.get('status') in {'queued', 'processing'}:
                active_paths.add(Path(str(job['path'])))
        stale_jobs = [job_id for job_id, job in EXPORT_JOBS.items() if job.get('status') in {'ready', 'failed'} and float(job.get('finished_at', 0)) < cutoff]
        for job_id in stale_jobs:
            EXPORT_JOBS.pop(job_id, None)
    for path in package_dir.iterdir():
        if path in active_paths or path.stat().st_mtime >= cutoff:
            continue
        if path.is_file():
            path.unlink(missing_ok=True)


def _run_export_job(job_id: str, target: str) -> None:
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        if not job:
            return
        job['status'] = 'processing'
    destination = Path(str(job['path']))
    partial_path = destination.with_suffix('.part')
    try:
        filename = build_export_archive_file(target, partial_path)
        partial_path.replace(destination)
        with EXPORT_JOBS_LOCK:
            job.update({'status': 'ready', 'filename': filename, 'size': destination.stat().st_size, 'finished_at': datetime.now(timezone.utc).timestamp()})
    except Exception as exc:
        partial_path.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        with EXPORT_JOBS_LOCK:
            job.update({'status': 'failed', 'error': str(exc), 'finished_at': datetime.now(timezone.utc).timestamp()})


def start_export_job(target: str) -> dict[str, Any]:
    """Start a disk-backed ZIP build that continues independently of the page."""
    filename = export_archive_filename(target)
    _cleanup_expired_export_packages()
    package_dir = export_package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    destination = package_dir / f'{job_id}.zip'
    job = {
        'id': job_id,
        'target': target,
        'status': 'queued',
        'filename': filename,
        'path': str(destination),
        'created_at': datetime.now(timezone.utc).timestamp(),
    }
    with EXPORT_JOBS_LOCK:
        EXPORT_JOBS[job_id] = job
    Thread(target=_run_export_job, args=(job_id, target), name=f'export-{job_id[:8]}', daemon=True).start()
    return job


def export_job_payload(job_id: str) -> dict[str, Any] | None:
    with EXPORT_JOBS_LOCK:
        job = EXPORT_JOBS.get(job_id)
        if not job:
            return None
        payload = {key: value for key, value in job.items() if key not in {'path'}}
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
            shutil.copyfileobj(source, output)


def _unique_import_workspace_name(name: str) -> str:
    base_name = ' '.join(name.split()) or 'Imported Workspace'
    existing = {workspace.name.casefold() for workspace in workspace_registry.list()}
    candidate = base_name
    suffix = 2
    while candidate.casefold() in existing:
        candidate = f'{base_name} - Imported' if suffix == 2 else f'{base_name} - Imported {suffix}'
        suffix += 1
    return candidate


def import_workspace_archive(payload: Path, workspace_info: dict[str, Any] | None, *, replace_existing: bool = False) -> Workspace:
    database_snapshot = payload / 'database.sqlite'
    if not database_snapshot.exists():
        raise ValueError('The workspace archive does not contain its database.')
    source_name = workspace_info.get('name') if workspace_info else None
    requested_name = str(source_name or 'Imported Workspace')
    existing_workspace = next((workspace for workspace in workspace_registry.list() if workspace.name.casefold() == requested_name.casefold()), None)
    if existing_workspace and replace_existing:
        if active_workspace and active_workspace.id == existing_workspace.id:
            raise ValueError(f'Close workspace "{existing_workspace.name}" before replacing it through import.')
        workspace_registry.remove(existing_workspace.id)
        repository.remove_workspace_access(existing_workspace.id)
    workspace = workspace_registry.create(requested_name if replace_existing or not existing_workspace else _unique_import_workspace_name(requested_name))
    try:
        for source, destination in (
            (payload / 'input', workspace.input_dir),
            (payload / 'exports', workspace.export_dir),
        ):
            if source.exists():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(database_snapshot, workspace.database_path)
        source_input_dir = workspace_info.get('source_input_dir') if workspace_info else None
        with sqlite3.connect(workspace.database_path) as connection:
            if source_input_dir:
                connection.execute('UPDATE datasets SET stored_path = REPLACE(stored_path, ?, ?)', (str(source_input_dir), str(workspace.input_dir)))
            connection.execute('PRAGMA quick_check').fetchone()
    except Exception:
        workspace_registry.remove(workspace.id)
        repository.remove_workspace_access(workspace.id)
        raise
    return workspace


def import_slides_templates_archive(staging_root: Path) -> None:
    templates_payload = staging_root / 'slides-templates'
    if not templates_payload.exists():
        raise ValueError('The Slides Templates archive does not contain template files.')
    for path in templates_payload.rglob('*'):
        if not path.is_file():
            continue
        target = settings.slides_templates_dir / path.relative_to(templates_payload)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def import_config_archive(staging_root: Path, manifest: dict[str, Any]) -> None:
    config_payload = staging_root / 'config'
    if not config_payload.exists():
        raise ValueError('The configuration archive does not contain configuration files.')
    application_database_payload = config_payload / 'application.db'
    if not application_database_payload.is_file():
        raise ValueError('The configuration archive does not contain application.db.')

    # Users, roles, workspace access and shared template metadata must be
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


def read_import_manifest(contents: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
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


def require_import_export_permission(user: SessionUser, target: str) -> None:
    if user.role == 'super-admin' or target == 'slides-templates':
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail='Only super-admins can import or export configuration and workspaces.',
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
    selected_technology = request.query_params.get('catalogue_technology') or None
    selected_catalogue = request.query_params.get('catalogue_id') or None
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
    admin_datasets = [serialize_dataset_row(dataset) for dataset in repository.list_datasets()] if active_workspace else []
    add_workspace_vendor_capabilities(admin_datasets)
    ready_admin_datasets = [dataset for dataset in admin_datasets if dataset['is_ready']]
    dataset_names = {
        int(dataset['id']): str(dataset['file_name'])
        for dataset in admin_datasets
    }
    database_table_groups: dict[str, list[dict[str, str]]] = {
        'Config Tables': [], 'Workspace Tables': [], 'Individual dataset rows': [], 'Combined CDR rows': [], 'Other tables': [],
    }
    friendly_tables = {
        'audit_logs': 'Audit log',
        'dataset_profiles': 'Dataset profiles',
        'datasets': 'Datasets',
        'report_runs': 'Generated reports',
        'report_templates': 'Slides Templates registry',
        'users': 'Users',
    }
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
        elif table_name in {'users', 'report_templates'}:
            database_table_groups['Config Tables'].append({'name': table_name, 'label': friendly_tables[table_name]})
        elif table_name in friendly_tables:
            database_table_groups['Workspace Tables'].append({'name': table_name, 'label': friendly_tables[table_name]})
        else:
            database_table_groups['Other tables'].append({'name': table_name, 'label': table_name})
    export_options = [
        {'value': 'config', 'label': 'Config'},
        {'value': 'slides-templates', 'label': 'Slides Templates'},
        {'value': 'config-with-templates', 'label': 'Config + Slides Templates'},
        {'value': 'full-environment', 'label': 'Full Environment (Config + Slides Templates + All Workspaces)'},
        *[
            {'value': f'workspace:{workspace.id}', 'label': f'Workspace: {workspace.name}'}
            for workspace in workspace_registry.list()
        ],
    ]
    if user.role != 'super-admin':
        export_options = [{**option, 'disabled': option['value'] != 'slides-templates'} for option in export_options]
    admin_users = [
        {**dict(row), 'created_at': format_local_timestamp(row['created_at']), 'workspace_ids': repository.list_user_workspace_ids(int(row['id']))}
        for row in repository.list_users()
    ]
    admin_logs = []
    for row in (repository.list_logs() if active_workspace else []):
        log = dict(row)
        log['action'] = str(log.get('action') or '').replace('_report_catalogue', '_report_template')
        log['details'] = re.sub(r'"catalogue_name"\s*:', '"template_name":', str(log.get('details') or ''))
        log['details'] = re.sub(r'"catalogue"\s*:', '"template":', log['details'])
        log['created_at'] = format_local_timestamp(log.get('created_at'))
        admin_logs.append(log)
    return render_template(
        request,
        'admin.html',
        {
            'user': user,
            'users': admin_users,
            'workspaces': workspace_registry.list(),
            'datasets': admin_datasets,
            'vodafone_mapping_datasets': [dataset for dataset in ready_admin_datasets if dataset.get('dataset_kind') == 'mapping_vodafone'],
            'three_mapping_datasets': [dataset for dataset in ready_admin_datasets if dataset.get('dataset_kind') == 'mapping_three'],
            'logs': admin_logs,
            'report_catalogs': report_catalogs,
            'workspace_catalogues': workspace_catalogues,
            'database_table_groups': database_table_groups,
            'database_notice': request.query_params.get('database_notice') or None,
            'catalogue_editor': catalogue_editor_payload(selected_technology, selected_catalogue) if active_workspace else None,
            'catalogue_notice': request.query_params.get('catalogue_notice') or None,
            'catalogue_error': request.query_params.get('catalogue_error') or None,
            'export_options': export_options,
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
    return str(log.get('details_text') or log.get('details') or '')


def classify_workspace_log_entry(log: dict[str, Any]) -> str:
    if log.get('action') in {
        'process_dataset_failed', 'analyze_dataset_failed', 'analyze_dataset_warning',
        'map_dataset_vendors_failed', 'clear_dataset_vendors_failed',
    }:
        return 'Error'
    return 'Info'


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
        return RedirectResponse('/workspace', status_code=status.HTTP_303_SEE_OTHER)
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
    record = repository.get_user(username)
    if not record or not record.active or not verify_password(password, record.password_hash):
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
            return render_template(request, 'login.html', {
                'error': str(exc), 'default_access_accounts': build_default_access_accounts(),
                'workspaces': workspace_registry.list(), 'active_workspace': active_workspace,
                'selected_workspace_id': workspace_id,
            }, status_code=400)

    user = SessionUser(username=record.username, role=record.role)
    response = RedirectResponse('/workspace', status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, user)
    repository.add_log(username, 'login', 'User logged in')
    return response


@app.get('/logout')
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
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
    workspace_logs = repository.list_workspace_logs(selected_dataset['id'] if selected_dataset else None)
    for log in workspace_logs:
        log['created_at'] = format_local_timestamp(log.get('created_at'))
        log['summary'] = describe_workspace_log_entry(log)
        log['log_type'] = classify_workspace_log_entry(log)

    vodafone_mapping_datasets = [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'mapping_vodafone']
    three_mapping_datasets = [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'mapping_three']
    add_workspace_vendor_capabilities(datasets)
    mappable_cdr_datasets = [dataset for dataset in datasets if dataset.get('can_map_vendors')]
    clearable_cdr_datasets = [dataset for dataset in datasets if dataset.get('can_clear_vendors')]

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
            'workspace_logs': workspace_logs,
            'error': None,
            'has_processing': has_processing,
            'vodafone_mapping_datasets': vodafone_mapping_datasets,
            'three_mapping_datasets': three_mapping_datasets,
            'mappable_cdr_datasets': mappable_cdr_datasets,
            'clearable_cdr_datasets': clearable_cdr_datasets,
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
    except ValueError as exc:
        return RedirectResponse(f'{target}?{urlencode({"workspace_error": str(exc)})}', status_code=status.HTTP_303_SEE_OTHER)
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
def duplicate_workspace(workspace_id: str = Form(...), user: SessionUser = Depends(current_user)) -> Response:
    require_workspace_admin(user)
    require_workspace_access(user, workspace_id)
    try:
        workspace = workspace_registry.duplicate(workspace_id)
    except ValueError as exc:
        return RedirectResponse(f'/workspace?{urlencode({"workspace_error": str(exc)})}', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f'/workspace?{urlencode({"workspace_notice": f"Created {workspace.name}."})}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/workspace/delete')
def delete_workspace(
    workspace_id: str = Form(...),
    delete_workspace_files: bool = Form(False),
    user: SessionUser = Depends(current_user),
) -> Response:
    require_workspace_admin(user)
    require_workspace_access(user, workspace_id)
    if active_workspace and active_workspace.id == workspace_id:
        return RedirectResponse('/workspace?workspace_warning=Close+the+workspace+before+removing+it.', status_code=status.HTTP_303_SEE_OTHER)
    try:
        workspace_registry.delete(workspace_id, delete_files=delete_workspace_files)
        repository.remove_workspace_access(workspace_id)
    except ValueError as exc:
        return RedirectResponse(f'/workspace?{urlencode({"workspace_error": str(exc)})}', status_code=status.HTTP_303_SEE_OTHER)
    notice = 'Workspace and all of its files deleted.' if delete_workspace_files else 'Workspace deleted. Its input and output files were preserved.'
    return RedirectResponse(f'/workspace?{urlencode({"workspace_notice": notice})}', status_code=status.HTTP_303_SEE_OTHER)


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
    cdr_call_family: list[str] = Query(default=[]),
    cdr_test_family: list[str] = Query(default=[]),
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
    if dataset['dataset_kind'] in CDR_DATASET_KINDS:
        # Backfill older CDRs only when they are actually inspected.  Running
        # a full-table migration for every historical dataset during startup
        # can delay the entire server by several minutes on large workspaces.
        if repository.materialize_cdr_derived_dimensions(dataset_id):
            repository.update_dataset_profile(dataset_id, normalization_version=DATASET_NORMALIZATION_VERSION)
            refreshed = repository.get_dataset(dataset_id)
            if refreshed:
                dataset = serialize_dataset_row(refreshed)

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
        cdr_filter_definitions = [
            ('cdr_operator', 'Operator', cdr_operator, ('operator', 'Operator')),
            ('cdr_vendor', 'Vendor', cdr_vendor, ('vendor', 'Vendor')),
            ('cdr_rat', 'RAT', cdr_rat, ('RAT_A', 'RAT', 'Sample_RAT_A')),
            ('cdr_session_type', 'Session Type', cdr_session_type, ('Session_Type', 'session_type', 'Type_of_Test')),
            ('cdr_call_status', 'Call Status', cdr_call_status, ('Call_Status', 'call_status', 'status')),
            ('cdr_call_family', 'Call Family', cdr_call_family, ('Call Family',)),
            ('cdr_test_family', 'Test Family', cdr_test_family, ('Test Family',)),
        ]
        for parameter, label, requested_values, candidates in cdr_filter_definitions:
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
            if column not in preview_columns and column != 'report_vendor'
        )
    derived_preview_columns = {
        column for column in preview_columns
        if str(column).casefold() in {name.casefold() for name in DERIVED_CDR_PREVIEW_COLUMNS}
    }
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


def _reporting_datasets(dataset_ids: list[int], expected_kind: str) -> list[dict[str, Any]]:
    """Validate a non-empty, de-duplicated selection of compatible CDRs."""
    unique_ids = list(dict.fromkeys(int(dataset_id) for dataset_id in dataset_ids))
    if not unique_ids:
        raise HTTPException(status_code=400, detail=f'Select at least one {expected_kind.title()} CDR.')
    return [_reporting_dataset(dataset_id, expected_kind) for dataset_id in unique_ids]


def _reporting_frame(dataset_id: int, task_repository: Repository | None = None) -> pd.DataFrame:
    task_repository = task_repository or repository
    return task_repository.load_dataset_rows(dataset_id, task_repository.list_dataset_row_columns(dataset_id), {})


def reporting_query_columns(dataset_kind: str, catalog_entries: list[Any], multivendor: bool) -> list[str]:
    """Select only fields that can affect the chosen CDR report.

    The remaining per-CDR columns stay available in Workspace, but a report no
    longer transfers every historical source field just to render its charts.
    """
    requested = {
        'Operator', 'Campaign', 'vendor', 'report_vendor',
        'RAT', 'RAT_A', 'Sample_RAT_A', 'technology_primary',
        'L1_Call_Mode_A', 'L2_Call_Mode_A', 'Session_Type', 'session_type',
        'Type_of_Test', 'Test_Name', 'test_name', 'Test_Type', 'test_type',
    }
    for entry in catalog_entries:
        if entry.source_kind != dataset_kind:
            continue
        requested.add(entry.kpi)
        requested.add(entry.legend)
        requested.update(parse_catalog_grouping(entry.grouping_rows).dimensions)
        requested.update(parse_catalog_grouping(entry.grouping_columns).dimensions)
        requested.update(condition.column for condition in parse_catalog_filters(entry.filters))
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
        task_repository.materialize_cdr_derived_dimensions(dataset_id)
        task_repository.copy_dataset_rows_to_reporting(dataset_id, dataset_kind, columns)
    combined = task_repository.load_reporting_rows(dataset_kind, dataset_ids, columns)
    if combined.empty:
        raise ValueError(f'The selected {dataset_kind.title()} CDRs have no materialised reporting rows.')
    return classify_sessions(combined, technology)


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
    return {
        'id': report_id,
        'date': _local_report_date(row['created_at']),
        'report_name': str(row['output_file']),
        'datasets': ' · '.join(labels) or 'Historical report',
        'dataset_groups': dataset_groups,
        'template': str(row['template_name'] or '—'),
        'slides': slide_count or None,
        'type': str(row['technology'] or '').upper() or '—',
        'multivendor': 'Yes' if str(row['scope'] or '').casefold() == 'multivendor' else 'No',
        'generated_by': str(row['created_by'] or '—'),
        'status': status_value,
        'progress': int(row['progress'] or 0),
        'error': str(row['last_error'] or ''),
        'download_url': f'/reporting/jobs/{report_id}/download' if output_available else None,
        'open_url': f'/reporting/jobs/{report_id}/open' if output_available else None,
        'delete_url': f'/reporting/jobs/{report_id}/delete',
        'retry_url': f'/reporting/jobs/{report_id}/retry' if status_value == 'failed' else None,
    }


def _run_netcheck_report_job(
    report_id: int, task_repository: Repository, selected: dict[str, list[dict[str, Any]]],
    technology: str, multivendor: bool, catalog_entries: list[Any], template: Path,
    destination: Path, username: str, catalogue_name: str,
) -> None:
    """Generate a report independently of the request/session that started it."""
    try:
        task_repository.update_report_job(report_id, status='processing', progress=5, last_error='')
        frames: dict[str, pd.DataFrame] = {}
        for index, (kind, datasets) in enumerate(selected.items(), start=1):
            frames[kind] = _combined_reporting_frame(
                datasets, technology, catalog_entries, multivendor, task_repository,
            )
            task_repository.update_report_job(report_id, status='processing', progress=10 + index * 15)
        if multivendor:
            frames = {kind: ensure_report_vendor_group(frame) for kind, frame in frames.items()}
        destination.parent.mkdir(parents=True, exist_ok=True)
        task_repository.update_report_job(report_id, status='processing', progress=60)
        render_cdr_report(destination, template, frames, technology, multivendor, catalog_entries)
        task_repository.update_report_job(report_id, status='ready', progress=100, last_error='', finished=True)
        task_repository.add_log(username, 'export_netcheck_cdr_report', json.dumps({
            'report_id': report_id,
            'datasets': {kind: [dataset['id'] for dataset in datasets] for kind, datasets in selected.items()},
            'technology': technology,
            'scope': 'multivendor' if multivendor else 'single',
            'slides_templates': catalogue_name,
            'file': destination.name,
        }))
    except Exception as exc:
        destination.unlink(missing_ok=True)
        task_repository.update_report_job(report_id, status='failed', progress=100, last_error=str(exc), finished=True)
        task_repository.add_log(username, 'export_netcheck_cdr_report_failed', json.dumps({
            'report_id': report_id, 'error': str(exc),
        }))


@app.get('/reporting', response_class=HTMLResponse)
def reporting(request: Request, user: SessionUser = Depends(current_user)) -> HTMLResponse:
    if not active_workspace:
        return RedirectResponse('/workspace?workspace_warning=Open+a+workspace+before+using+Reporting.', status_code=status.HTTP_303_SEE_OTHER)
    ready_datasets = [serialize_dataset_row(row) for row in repository.list_datasets() if row['status'] == 'ready']
    return render_template(
        request,
        'reporting.html',
        {
            'user': user,
            'data_datasets': [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'data'],
            'voice_datasets': [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'voice'],
            'speech_datasets': [dataset for dataset in ready_datasets if dataset.get('dataset_kind') == 'speech'],
            'report_catalogues': {
                technology: report_catalogue_options(technology)
                for technology in TEMPLATE_NAMES
            },
            'report_jobs': [serialize_report_job(row) for row in repository.list_report_runs(limit=None)],
        },
    )


@app.post('/reporting/netcheck-cdr')
def generate_netcheck_cdr_report(
    data_dataset_id: list[int] = Form(...),
    voice_dataset_id: list[int] = Form(...),
    speech_dataset_id: list[int] = Form(...),
    technology: str = Form(...),
    report_scope: str = Form('single'),
    slides_templates: str = Form(''),
    user: SessionUser = Depends(current_user),
) -> JSONResponse:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=400, detail='Choose NSA or SA for the CDR report.')
    if report_scope not in {'single', 'multivendor'}:
        raise HTTPException(status_code=400, detail='Choose a valid report scope.')
    multivendor = report_scope == 'multivendor'
    selected = {
        'data': _reporting_datasets(data_dataset_id, 'data'),
        'voice': _reporting_datasets(voice_dataset_id, 'voice'),
        'speech': _reporting_datasets(speech_dataset_id, 'speech'),
    }
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
        catalog_entries = load_catalog_csv(catalog_path, technology)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unable to load the selected {technology.upper()} report template: {exc}") from exc
    generated_at = datetime.now().strftime('%Y%m%d-%H%M%S')
    file_name = f"NetCheck_CDR_{technology.upper()}_{'multivendor' if multivendor else 'single_vendor'}_{generated_at}.pptx"
    reports_dir = Path(settings.output_dir) / 'reports'
    destination = safe_join(reports_dir, file_name)
    dataset_ids = {kind: [int(dataset['id']) for dataset in datasets] for kind, datasets in selected.items()}
    report_id = repository.create_report_job(
        report_type='netcheck_cdr', technology=technology, scope=report_scope,
        data_dataset_id=selected['data'][0]['id'], voice_dataset_id=selected['voice'][0]['id'], speech_dataset_id=selected['speech'][0]['id'],
        dataset_ids=dataset_ids, dataset_names=_report_dataset_names(selected),
        slide_count=len({entry.slide for entry in catalog_entries}), template_name=selected_catalogue['name'],
        output_file=file_name, output_path=destination, created_by=user.username,
    )
    task_repository = Repository(Path(repository.db_path))
    Thread(
        target=_run_netcheck_report_job,
        args=(report_id, task_repository, selected, technology, multivendor, catalog_entries, template, destination, user.username, selected_catalogue['name']),
        name=f'report-{report_id}', daemon=True,
    ).start()
    return JSONResponse({'job_id': report_id, 'status': 'queued'}, status_code=status.HTTP_202_ACCEPTED)


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


@app.post('/reporting/jobs/{report_id}/delete')
def delete_report_job(report_id: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    report = repository.delete_report_run(report_id)
    if not report:
        raise HTTPException(status_code=404, detail='Report job not found.')
    path = _report_job_output_path(report)
    if path is not None:
        path.unlink()
    return JSONResponse({'deleted': report_id})


@app.post('/reporting/jobs/{report_id}/retry')
def retry_report_job(report_id: int, user: SessionUser = Depends(current_user)) -> JSONResponse:
    if not active_workspace:
        raise HTTPException(status_code=409, detail='Open a workspace before retrying a report.')
    previous = repository.get_report_run(report_id)
    if not previous:
        raise HTTPException(status_code=404, detail='Report job not found.')
    if str(previous['status'] or '').casefold() != 'failed':
        raise HTTPException(status_code=400, detail='Only failed report jobs can be retried.')
    try:
        dataset_ids = json.loads(previous['dataset_ids_json'] or '{}')
        selected = {
            kind: _reporting_datasets([int(value) for value in dataset_ids.get(kind, [])], kind)
            for kind in ('data', 'voice', 'speech')
        }
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail='The failed report does not contain a valid dataset selection.') from exc
    technology = str(previous['technology'] or '').strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=400, detail='The failed report has an unsupported technology.')
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
        catalog_entries = load_catalog_csv(template_option['path'], technology)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'Unable to load the selected {technology.upper()} report template: {exc}') from exc
    generated_at = datetime.now().strftime('%Y%m%d-%H%M%S')
    file_name = f"NetCheck_CDR_{technology.upper()}_{'multivendor' if multivendor else 'single_vendor'}_{generated_at}.pptx"
    destination = safe_join(Path(settings.output_dir) / 'reports', file_name)
    new_report_id = repository.create_report_job(
        report_type=str(previous['report_type'] or 'netcheck_cdr'), technology=technology, scope=str(previous['scope'] or 'single'),
        data_dataset_id=selected['data'][0]['id'], voice_dataset_id=selected['voice'][0]['id'], speech_dataset_id=selected['speech'][0]['id'],
        dataset_ids={kind: [int(dataset['id']) for dataset in datasets] for kind, datasets in selected.items()},
        dataset_names=_report_dataset_names(selected), slide_count=len({entry.slide for entry in catalog_entries}),
        template_name=template_option['name'], output_file=file_name, output_path=destination, created_by=user.username,
    )
    task_repository = Repository(Path(repository.db_path))
    Thread(
        target=_run_netcheck_report_job,
        args=(new_report_id, task_repository, selected, technology, multivendor, catalog_entries, settings.ppt_templates_dir / TEMPLATE_NAMES[technology], destination, user.username, template_option['name']),
        name=f'report-{new_report_id}', daemon=True,
    ).start()
    repository.add_log(user.username, 'retry_report_job', json.dumps({'previous_report_id': report_id, 'report_id': new_report_id}))
    return JSONResponse({'job_id': new_report_id, 'status': 'queued'}, status_code=status.HTTP_202_ACCEPTED)


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

    def parse_mapping_selection(values: list[str] | None, label: str) -> list[int | None]:
        if not values:
            return [None] * len(dataset_files)
        if len(values) != len(dataset_files):
            raise HTTPException(status_code=422, detail=f'Choose one {label} value for every uploaded file.')
        selected_ids: list[int | None] = []
        for value in values:
            value = str(value or '').strip()
            if not value:
                selected_ids.append(None)
                continue
            try:
                selected_ids.append(int(value))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f'Invalid {label} selection.') from exc
        return selected_ids

    selected_vodafone_mappings = parse_mapping_selection(vodafone_mapping_dataset_ids, 'VFUK mapping')
    selected_three_mappings = parse_mapping_selection(three_mapping_dataset_ids, '3UK mapping')
    for index, selected_kind in enumerate(selected_kinds or [''] * len(dataset_files)):
        if selected_kind not in CDR_DATASET_KINDS:
            continue
        try:
            if selected_vodafone_mappings[index]:
                _reporting_dataset(selected_vodafone_mappings[index], 'mapping_vodafone')
            if selected_three_mappings[index]:
                _reporting_dataset(selected_three_mappings[index], 'mapping_three')
        except HTTPException:
            raise

    queued_dataset_ids: list[int] = []
    for index, dataset_file in enumerate(dataset_files):
        extension = Path(dataset_file.filename or '').suffix.lower()
        destination = safe_join(settings.input_dir, dataset_file.filename or f'upload{extension}')
        await save_upload_file(dataset_file, destination)
        dataset_id, created = repository.add_dataset(dataset_file.filename or destination.name, str(destination), user.username)
        selected_kind = selected_kinds[index] if selected_kinds else None
        if selected_kind:
            repository.update_dataset_profile(dataset_id, dataset_kind=selected_kind)
        vodafone_mapping_dataset_id = selected_vodafone_mappings[index] if selected_kind in CDR_DATASET_KINDS else None
        three_mapping_dataset_id = selected_three_mappings[index] if selected_kind in CDR_DATASET_KINDS else None
        repository.add_log(user.username, 'upload_dataset' if created else 'reprocess_dataset', json.dumps({
            'file': destination.name,
            'dataset_kind': selected_kind or 'auto-detected',
            'vodafone_mapping_dataset_id': vodafone_mapping_dataset_id,
            'three_mapping_dataset_id': three_mapping_dataset_id,
        }))
        enqueue_dataset_processing(
            background_tasks,
            dataset_id,
            destination,
            user.username,
            vodafone_mapping_dataset_id,
            three_mapping_dataset_id,
        )
        queued_dataset_ids.append(dataset_id)

    if not queued_dataset_ids:
        return RedirectResponse('/workspace', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f'/workspace?dataset_id={queued_dataset_ids[0]}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/datasets/{dataset_id}/rename')
def rename_dataset_file(
    dataset_id: int,
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


@app.get('/admin/import-export/export')
def export_admin_package(
    export_target: str = Query(...),
    user: SessionUser = Depends(admin_user),
) -> FileResponse:
    require_import_export_permission(user, export_target)
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
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    require_import_export_permission(user, export_target)
    try:
        job = start_export_job(export_target)
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
    require_import_export_permission(user, str(payload['target']))
    return JSONResponse(payload)


@app.get('/admin/import-export/export/jobs/{job_id}/download')
def download_admin_export_job(job_id: str, user: SessionUser = Depends(admin_user)) -> FileResponse:
    if not (payload := export_job_payload(job_id)):
        raise HTTPException(status_code=404, detail='The export job no longer exists. Start a new export.')
    require_import_export_permission(user, str(payload['target']))
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
    try:
        manifest = read_import_manifest(await package.read())
        kind = str(manifest.get('kind') or '')
        if kind not in {'config', 'workspace', 'full-environment', 'slides-templates'}:
            raise ValueError('The export package type is not supported.')
        require_import_export_permission(user, kind)
        return JSONResponse({
            'kind': kind,
            'includes_slides_templates': bool(manifest.get('includes_slides_templates')),
            'workspace_collisions': import_workspace_collisions(manifest),
        })
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await package.close()


@app.post('/admin/import-export/import')
async def import_admin_package(
    package: UploadFile = File(...),
    confirmed_import: bool = Form(False),
    user: SessionUser = Depends(admin_user),
) -> Response:
    try:
        contents = await package.read()
        with zipfile.ZipFile(io.BytesIO(contents)) as archive, tempfile.TemporaryDirectory(prefix='dashboard-analytic-import-') as temporary_dir:
            manifest = read_import_manifest(contents)
            if not confirmed_import:
                raise ValueError('Confirm the import warning before applying this package.')
            staging_root = Path(temporary_dir)
            _safe_extract_archive(archive, staging_root)
            kind = manifest.get('kind')
            require_import_export_permission(user, str(kind))
            if kind == 'workspace':
                workspace_info = manifest.get('workspace')
                workspace = import_workspace_archive(staging_root / 'workspace', workspace_info if isinstance(workspace_info, dict) else None, replace_existing=True)
                notice = f'Workspace "{workspace.name}" imported successfully.'
            elif kind == 'config':
                import_config_archive(staging_root, manifest)
                notice = 'Configuration imported successfully. Local workspaces were preserved.'
            elif kind == 'slides-templates':
                import_slides_templates_archive(staging_root)
                notice = 'Slides Templates imported successfully.'
            elif kind == 'full-environment':
                import_config_archive(staging_root, manifest)
                entries = manifest.get('workspaces')
                if not isinstance(entries, list):
                    raise ValueError('The full-environment package has no workspace list.')
                imported_workspaces: list[Workspace] = []
                for entry in entries:
                    if not isinstance(entry, dict) or not re.fullmatch(r'workspaces/\d+', str(entry.get('archive_path') or '')):
                        raise ValueError('The full-environment package contains an invalid workspace entry.')
                    imported_workspaces.append(import_workspace_archive(staging_root / str(entry['archive_path']), entry, replace_existing=True))
                notice = f'Full environment imported successfully ({len(imported_workspaces)} workspaces added).'
            else:
                raise ValueError('The export package type is not supported.')
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        return RedirectResponse(
            f'/admin?{urlencode({"import_export_error": str(exc)})}',
            status_code=status.HTTP_303_SEE_OTHER,
        )
    finally:
        await package.close()
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
    user: SessionUser = Depends(admin_user),
) -> JSONResponse:
    """Return values only for the field currently being configured in the editor."""
    normalized_source = source.strip().casefold()
    if normalized_source not in {'cdr-data', 'cdr-voice', 'cdr-speech'} or not column.strip():
        raise HTTPException(status_code=400, detail='Unsupported CDR source or filter field.')
    kind = normalized_source.removeprefix('cdr-')
    values: set[str] = set()
    for dataset in repository.list_datasets():
        if str(dataset['dataset_kind'] or '').casefold() != kind or dataset['status'] != 'ready':
            continue
        if not repository.dataset_rows_table_exists(dataset['id']):
            continue
        values.update(repository.list_distinct_dataset_row_values(dataset['id'], column, limit=200))
    return JSONResponse({'values': sorted(values, key=str.casefold)[:200]})


def _import_report_catalogue(
    request: Request,
    technology: str,
    catalogue_file: UploadFile | None,
    catalogue_name: str,
    convert_catalogue: bool,
    user: SessionUser,
) -> HTMLResponse:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    if not catalogue_file or not catalogue_file.filename or Path(catalogue_file.filename).suffix.lower() != '.csv':
        query = urlencode({'catalogue_error': 'Select a CSV Slides Template.'})
        return RedirectResponse(f'/admin?{query}', status_code=status.HTTP_303_SEE_OTHER)
    try:
        catalogue_name = catalogue_name.strip() or re.sub(r'[_-]+', ' ', Path(catalogue_file.filename).stem).strip()
        if not catalogue_name:
            raise ValueError('Enter a name for the template.')
        identifier = catalogue_registry_key(catalogue_name)
        content = catalogue_file.file.read()
        if convert_catalogue:
            content = convert_catalog_csv(content, technology)
        entries = parse_catalog_csv(content, technology)
        if identifier in {str(row['name']) for row in repository.list_report_templates(technology)}:
            raise ValueError(f"A {technology.upper()} template named '{identifier}' already exists.")
        destination = named_catalogue_path(technology, identifier, catalogue_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        repository.add_report_template(technology, identifier)
        promote_report_template_to_default(technology, identifier)
        synchronize_reporting_catalogue_document()
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
    query = urlencode({'catalogue_notice': f"Imported {catalogue_name} ({technology.upper()})."})
    return RedirectResponse(f'/admin?{query}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/admin/report-templates/{technology}', response_class=HTMLResponse)
def import_report_catalogue(
    request: Request,
    technology: str,
    catalogue_file: UploadFile | None = File(default=None),
    catalogue_name: str = Form(''),
    convert_catalogue: bool = Form(False),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    """Compatibility endpoint for existing NSA/SA-specific imports."""
    return _import_report_catalogue(request, technology, catalogue_file, catalogue_name, convert_catalogue, user)


@app.post('/admin/slides-templates/import', response_class=HTMLResponse)
def import_slides_template(
    request: Request,
    template_type: str = Form('nsa'),
    catalogue_file: UploadFile | None = File(default=None),
    catalogue_name: str = Form(''),
    convert_catalogue: bool = Form(False),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    """Import one Slides Template after the user has selected its NSA/SA type."""
    return _import_report_catalogue(request, template_type, catalogue_file, catalogue_name, convert_catalogue, user)


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
    synchronize_reporting_catalogue_document()
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
        synchronize_reporting_catalogue_document()
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


@app.post('/admin/report-templates/{technology}/{catalogue_id}/save', response_class=HTMLResponse)
def save_report_catalogue(
    request: Request,
    technology: str,
    catalogue_id: str,
    catalogue_content: str = Form(...),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    catalogue = next((item for item in report_catalogue_options(technology) if item['identifier'] == catalogue_id), None)
    if not catalogue:
        return render_admin_template(request, user, error='Slides Template not found.', status_code=404)
    try:
        entries = parse_catalog_csv(catalogue_content, technology)
        entries = [entry for _index, entry in sorted(enumerate(entries), key=lambda item: (item[1].slide, item[0]))]
        catalogue['path'].parent.mkdir(parents=True, exist_ok=True)
        catalogue['path'].write_bytes(catalogue_csv(entries))
        if catalogue['active']:
            default_path = default_report_slides_template_path(technology, catalogue['name'])
            # The selected default is edited through its active mirror. Keep
            # the canonical library copy byte-for-byte aligned with it.
            if catalogue['path'] == default_path:
                default_name = catalogue['name']
                library_path = named_catalogue_path(technology, catalogue_registry_key(default_name), default_name)
                library_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(default_path, library_path)
            synchronize_reporting_catalogue_document()
        repository.touch_report_template(technology, catalogue_id)
    except ValueError as exc:
        return render_admin_template(request, user, error=str(exc), status_code=400)
    repository.add_log(user.username, 'save_report_template', json.dumps({
        'technology': technology,
        'template': catalogue['name'],
        'chart_rows': sum(1 for entry in entries if entry.source_kind),
    }))
    query = urlencode({'catalogue_technology': technology, 'catalogue_id': catalogue_id})
    return RedirectResponse(f'/admin?{query}', status_code=status.HTTP_303_SEE_OTHER)


@app.get('/admin/report-templates/{technology}/export')
def export_report_catalogue(technology: str, user: SessionUser = Depends(admin_user)) -> Response:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    entries = reporting_catalog_entries(technology)
    return Response(
        content=catalogue_csv(entries),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{technology}-slides-template.csv"'},
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
        content=catalogue_csv(load_catalog_csv(catalogue['path'], technology)),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{technology}-{catalogue["identifier"]}-slides-template.csv"'},
    )


@app.get('/admin/report-templates/{technology}/{catalogue_id}/export')
def export_named_report_catalogue(technology: str, catalogue_id: str, user: SessionUser = Depends(admin_user)) -> Response:
    technology = technology.strip().lower()
    if technology not in TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail='Report technology not found')
    catalogue = next((item for item in report_catalogue_options(technology) if item['identifier'] == catalogue_id), None)
    if not catalogue:
        raise HTTPException(status_code=404, detail='Slides Template not found')
    entries = load_catalog_csv(catalogue['path'], technology)
    filename = f"{technology}-{catalogue['identifier']}-slides-template.csv"
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


templates.env.globals['format_extra_filters'] = format_extra_filters
templates.env.globals['format_aggregation_overrides'] = format_aggregation_overrides
templates.env.globals['format_cdf_overrides'] = format_cdf_overrides
templates.env.globals['format_aggregation_label'] = format_aggregation_label
