"""Workspace dashboard definitions and shared-table, template-driven previews."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from threading import RLock
from time import monotonic
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

import pandas as pd
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from pptx import Presentation

from src.modules.cdr_reporting import (
    _layout_chart_frames, _legend_dimensions, _named_slide_layout, catalog_chart_payload,
    ensure_report_vendor_group, normalise_report_operator_aliases, parse_catalog_filters,
    parse_catalog_grouping,
    prepare_catalog_chart_preview_frame, render_catalog_chart_preview,
)

from src.modules.repository import Repository

KINDS = ('data', 'voice', 'speech')
STATE_KEY = 'e2e_dashboards_v2'
LEGACY_STATE_KEY = 'e2e_dashboard_sets_v1'


class DashboardDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template: str = Field(min_length=1)
    template_technology: Literal['nsa', 'sa'] = 'nsa'
    technology: Literal['nsa', 'sa'] = 'nsa'
    scope: Literal['single', 'multivendor'] = 'single'
    datasets: dict[str, list[int]] = Field(default_factory=dict)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    custom_fields: list[str] = Field(default_factory=list)
    hidden_filters: list[str] = Field(default_factory=list)
    slide_comments: dict[str, list[str]] = Field(default_factory=dict)
    date_from: date | None = None
    date_to: date | None = None


class DashboardComments(BaseModel):
    slide_comments: dict[str, list[str]] = Field(default_factory=dict)


class DashboardName(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class DashboardPrefetchPriority(BaseModel):
    token: str = Field(min_length=1)
    indexes: list[int] = Field(default_factory=list)


def identity(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


FILTER_COLUMNS = {
    'Market': ('market',), 'Operator': ('operator',), 'Vendor': ('vendor',),
    'Region': ('region',), 'City': ('city',), 'Session Type': ('session_type',),
    'Technology': ('technology_primary', 'technology'),
    'RAT': ('RAT', 'RAT_A', 'Sample_RAT_A'),
}
ADAPTATIVE_FILTER_FIELDS = tuple(FILTER_COLUMNS)
DASHBOARD_RENDER_CACHE_VERSION = 1
DASHBOARD_SELECTION_ROW_LIMIT = 25_000
DASHBOARD_PROFILE_SELECTION_THRESHOLD = 100_000
DASHBOARD_PROJECTION_CACHE_VERSION = 1
DASHBOARD_PROJECTION_DISK_LIMIT = 6
DASHBOARD_PROJECTION_PAGE_SIZE = 32_768
DASHBOARD_PROJECTION_CACHE_KIB = 256 * 1024
DASHBOARD_PROJECTION_MMAP_SIZE = 4 * 1024 ** 3
DASHBOARD_CHART_MODEL_CACHE_VERSION = 9
DASHBOARD_CHART_MODEL_DISK_LIMIT = 500
DASHBOARD_CHART_RENDER_WORKERS = 3
DASHBOARD_PREVIEW_MANIFEST_VERSION = 3


def dashboard_cache_dir(workspace: str | Path) -> Path:
    return Path(workspace).parent / '.dashboard-data-cache'


def canvas_model_cache_dir(workspace: str | Path) -> Path:
    return dashboard_cache_dir(workspace) / 'charts-canvas'


def pil_chart_cache_dir(workspace: str | Path) -> Path:
    return dashboard_cache_dir(workspace) / 'charts-pil'


def dashboard_projection_scan_hint(
    selected_dataset_ids: list[int], available_dataset_ids: list[int],
) -> str:
    """Prefer a sequential source scan only when every materialized row is selected."""
    selected = {int(dataset_id) for dataset_id in selected_dataset_ids}
    available = {int(dataset_id) for dataset_id in available_dataset_ids}
    return ' NOT INDEXED' if selected and selected == available else ''


def preview_manifest_cache_dir(workspace: str | Path) -> Path:
    return dashboard_cache_dir(workspace) / 'dashboard-previews'


def resolve_filter_column(frame, field):
    columns = {identity(column): column for column in frame.columns}
    aliases = next((values for label, values in FILTER_COLUMNS.items() if identity(label) == identity(field)), (field,))
    candidates = [columns[identity(alias)] for alias in aliases if identity(alias) in columns]
    return next((column for column in candidates if frame[column].notna().any()), candidates[0] if candidates else None)


def filter_mask(frame, definition, exclude=None):
    """Filter row indices so adaptive facets never copy complete, wide CDR tables."""
    columns = {identity(column): column for column in frame.columns}
    mask = pd.Series(True, index=frame.index)
    for field, values in definition.filters.items():
        if identity(field) == identity(exclude):
            continue
        column = resolve_filter_column(frame, field)
        if column is None:
            return pd.Series(False, index=frame.index)
        mask &= frame[column].fillna('').astype(str).isin(values)
    if definition.date_from or definition.date_to:
        time_column = next((columns[key] for key in ('eventstarttime', 'teststarttime', 'timestamp', 'datetime', 'date') if key in columns), None)
        if time_column is None:
            return pd.Series(False, index=frame.index)
        times = pd.to_datetime(frame[time_column], errors='coerce', utc=True, format='mixed')
        if definition.date_from:
            mask &= times >= pd.Timestamp(definition.date_from, tz='UTC')
        if definition.date_to:
            mask &= times < pd.Timestamp(definition.date_to + timedelta(days=1), tz='UTC')
    return mask


def filter_frame(frame, definition, exclude=None):
    """Apply selections, including explicit empty selections and missing fields."""
    if not definition.filters and not definition.date_from and not definition.date_to:
        return frame
    return frame.loc[filter_mask(frame, definition, exclude)]


@dataclass
class Snapshot:
    workspace: str
    owner: str
    entries: list
    frames: dict
    multivendor: bool
    definition: DashboardDefinition
    dimensions: tuple
    selection_id: int
    selection_key: str
    selection_materialized: bool
    payload: dict[str, object]
    chart_frames: dict[int, pd.DataFrame] = field(default_factory=dict)
    filtered_frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    chart_payloads: dict[int, dict[str, object]] = field(default_factory=dict)
    frame_locks: dict[str, RLock] = field(default_factory=dict)
    projections: dict[str, tuple[Path, str, list[str]]] = field(default_factory=dict)
    cancelled: object = None


def install_dashboard_routes(core):
    app = core.app
    lock = RLock()
    snapshots = OrderedDict()
    images = OrderedDict()
    projection_load_locks: dict[str, RLock] = {}
    prefetch_jobs: dict[str, dict] = {}
    direct_preparation_tasks: dict[str, dict] = {}
    prefetch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='e2e-dashboard-models')
    prefetch_dispatch_active = False
    prefetch_generation: dict[str, int] = {}

    def schedule_next_prefetch() -> None:
        """Run one queued Dashboard, selecting its name-order at dispatch time."""
        nonlocal prefetch_dispatch_active
        with lock:
            if prefetch_dispatch_active:
                return
            candidates = [
                job for job in prefetch_jobs.values()
                if job.get('status') == 'queued' and callable(job.get('runner'))
            ]
            if not candidates:
                return
            job = min(candidates, key=lambda candidate: float(candidate.get('created_at') or 0))
            prefetch_dispatch_active = True

        def dispatch():
            nonlocal prefetch_dispatch_active
            try:
                job['runner']()
            finally:
                with lock:
                    prefetch_dispatch_active = False
                schedule_next_prefetch()

        future = prefetch_executor.submit(dispatch)
        with lock:
            job['future'] = future

    def workspace_key():
        if not core.active_workspace:
            raise HTTPException(400, 'Open a workspace before using E2E Dashboards.')
        return str(Path(core.repository.db_path).resolve())

    def dashboard_user(user=Depends(core.current_user)):
        if core.active_workspace and user.role != 'super-admin' and not core.repository.user_has_workspace_access(user.username, core.active_workspace.id):
            raise HTTPException(403, 'You do not have access to the active workspace.')
        return user

    def bound_repository():
        return Repository(Path(workspace_key()), core.repository.global_db_path)

    def read_dashboards(task_repository):
        stored = task_repository.get_workspace_state(STATE_KEY)
        if stored is None:
            stored = task_repository.get_workspace_state(LEGACY_STATE_KEY) or '{}'
            task_repository.set_workspace_state(STATE_KEY, stored)
        return json.loads(stored or '{}')

    def catalogue(definition, task_repository=None):
        task_repository = task_repository or core.repository
        rows = task_repository.list_report_templates(definition.template_technology)
        row = next((row for row in rows if row['name'] == definition.template), None)
        if row is None:
            raise HTTPException(400, 'The selected template is no longer available.')
        try:
            return core.load_template_catalogue(bytes(row['content']), definition.template_technology, task_repository=task_repository)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def validate(definition, task_repository=None):
        if not definition.name.strip():
            raise HTTPException(400, 'Enter a Dashboard name.')
        if definition.date_from and definition.date_to and definition.date_from > definition.date_to:
            raise HTTPException(400, 'The start date must not follow the end date.')
        if set(definition.datasets) - set(KINDS):
            raise HTTPException(400, 'Unsupported dataset type.')
        return catalogue(definition, task_repository)

    @app.get('/e2e-dashboards', response_class=HTMLResponse)
    def page(request: Request, user=Depends(dashboard_user)):
        workspace_key()
        ready = [core.serialize_dataset_row(row) for row in core.repository.list_datasets() if row['status'] == 'ready']
        options = {tech: core.report_catalogue_options(tech) for tech in ('nsa', 'sa')}
        return core.render_template(request, 'e2e_dashboards.html', {
            'user': user, 'dashboard_datasets': {kind: [row for row in ready if row.get('dataset_kind') == kind] for kind in KINDS},
            'dashboard_templates': {tech: [{'name': row['name'], 'identifier': row['identifier']} for row in rows] for tech, rows in options.items()},
            'dashboard_workspace_id': core.active_workspace.id,
            'calculated_dimensions': core.calculated_dimensions_json(core.load_workspace_calculated_dimensions()),
            'dashboard_filter_fields': ADAPTATIVE_FILTER_FIELDS,
        })

    @app.get('/api/e2e-dashboards')
    def list_dashboards(user=Depends(dashboard_user)):
        with lock:
            dashboards = read_dashboards(bound_repository())
        for dashboard_id, definition in dashboards.items():
            enqueue_prefetch(dashboard_id, definition, user)
        return JSONResponse(
                dashboards,
                headers={'Cache-Control': 'no-store, max-age=0, must-revalidate'},
            )

    @app.put('/api/e2e-dashboards/{dashboard_id}')
    def save_dashboard(dashboard_id: str, definition: DashboardDefinition, user=Depends(dashboard_user)):
        with lock:
            task_repository = bound_repository()
            validate(definition, task_repository)
            dashboards = read_dashboards(task_repository)
            if any(key != dashboard_id and item['name'].strip().casefold() == definition.name.strip().casefold() for key, item in dashboards.items()):
                raise HTTPException(409, 'A Dashboard with this name already exists.')
            definition.name = definition.name.strip()
            saved_definition = definition.model_dump(mode='json')
            dashboards[dashboard_id] = saved_definition
            task_repository.set_workspace_state(STATE_KEY, json.dumps(dashboards))
            task_repository.add_log(user.username, 'save_dashboard', json.dumps({'id': dashboard_id, 'name': definition.name}))
        enqueue_prefetch(dashboard_id, saved_definition, user)
        return {'id': dashboard_id, 'definition': saved_definition}

    @app.patch('/api/e2e-dashboards/{dashboard_id}/name')
    def rename_dashboard(dashboard_id: str, payload: DashboardName, user=Depends(dashboard_user)):
        name = payload.name.strip()
        if not name:
            raise HTTPException(400, 'Enter a Dashboard name.')
        with lock:
            task_repository = bound_repository()
            dashboards = read_dashboards(task_repository)
            if dashboard_id not in dashboards:
                raise HTTPException(404, 'Dashboard not found.')
            if any(key != dashboard_id and item['name'].strip().casefold() == name.casefold() for key, item in dashboards.items()):
                raise HTTPException(409, 'A Dashboard with this name already exists.')
            dashboards[dashboard_id]['name'] = name
            task_repository.set_workspace_state(STATE_KEY, json.dumps(dashboards))
            task_repository.add_log(user.username, 'rename_dashboard', json.dumps({'id': dashboard_id, 'name': name}))
        return {'id': dashboard_id, 'name': name}

    @app.delete('/api/e2e-dashboards/{dashboard_id}')
    def delete_dashboard(dashboard_id: str, user=Depends(dashboard_user)):
        with lock:
            task_repository = bound_repository()
            dashboards = read_dashboards(task_repository)
            if dashboard_id not in dashboards:
                raise HTTPException(404, 'Dashboard not found.')
            del dashboards[dashboard_id]
            task_repository.set_workspace_state(STATE_KEY, json.dumps(dashboards))
            task_repository.add_log(user.username, 'delete_dashboard', json.dumps({'id': dashboard_id}))
        return {'deleted': True}

    @app.patch('/api/e2e-dashboards/{dashboard_id}/comments')
    def save_dashboard_comments(dashboard_id: str, payload: DashboardComments, user=Depends(dashboard_user)):
        with lock:
            task_repository = bound_repository()
            dashboards = read_dashboards(task_repository)
            if dashboard_id not in dashboards:
                raise HTTPException(404, 'Dashboard not found.')
            comments = {
                str(slide): [str(comment).strip() for comment in values if str(comment).strip()][:50]
                for slide, values in payload.slide_comments.items()
            }
            dashboards[dashboard_id]['slide_comments'] = {slide: values for slide, values in comments.items() if values}
            task_repository.set_workspace_state(STATE_KEY, json.dumps(dashboards))
            task_repository.add_log(user.username, 'save_dashboard_comments', json.dumps({'id': dashboard_id}))
        return {'slide_comments': dashboards[dashboard_id]['slide_comments']}

    def selected_sources(definition, task_repository):
        selected_by_kind = {}
        for kind in KINDS:
            selected = core._optional_reporting_datasets(definition.datasets.get(kind, []), kind, task_repository)
            if definition.scope == 'multivendor' and any(not row.get('vendor_mapping_applied') for row in selected):
                raise HTTPException(400, 'Map Vendors for every selected CDR before using Multivendor Comparison.')
            if selected:
                selected_by_kind[kind] = selected
        if not selected_by_kind:
            raise HTTPException(400, 'Select at least one CDR dataset.')
        return selected_by_kind

    def resolve_sql_column(columns, field):
        lookup = {identity(column): column for column in columns}
        aliases = next((values for label, values in FILTER_COLUMNS.items() if identity(label) == identity(field)), (field,))
        return next((lookup[identity(alias)] for alias in aliases if identity(alias) in lookup), None)

    def nr_mode_sql(columns, technology):
        rat = resolve_sql_column(columns, 'RAT')
        call_modes = [resolve_sql_column(columns, name) for name in ('L1_Call_Mode_A', 'L2_Call_Mode_A')]
        call_modes = list(dict.fromkeys(column for column in call_modes if column))
        if not rat and not call_modes:
            raise ValueError('The selected CDR does not contain RAT or Call Mode fields required to separate NSA and SA sessions.')
        quote = lambda column: '"' + str(column).replace('"', '""') + '"'
        rat_text = f"UPPER(COALESCE(CAST({quote(rat)} AS TEXT), ''))" if rat else "''"
        mode_text = " || ' ' || ".join(f"UPPER(COALESCE(CAST({quote(column)} AS TEXT), ''))" for column in call_modes) or "''"
        session = resolve_sql_column(columns, 'Session Type')
        session_text = f"UPPER(COALESCE(CAST({quote(session)} AS TEXT), ''))" if session else "''"
        whatsapp = f"({session_text} LIKE '%WHATSAPP%')"
        recognised = f"({mode_text} LIKE '%VOLTE%' OR {mode_text} LIKE '%EPSFB%' OR {mode_text} LIKE '%VONR%')"
        rat_nsa = f"(REPLACE(REPLACE({rat_text}, '-', ''), ' ', '') LIKE '%ENDC%')"
        rat_sa = f"({rat_text} LIKE '%NR%' AND NOT {rat_nsa})"
        mode_nsa = f"(({mode_text} LIKE '%VOLTE%' OR {mode_text} LIKE '%EPSFB%') AND NOT {mode_text} LIKE '%VONR%')"
        mode_sa = f"({mode_text} LIKE '%VONR%' AND NOT ({mode_text} LIKE '%VOLTE%' OR {mode_text} LIKE '%EPSFB%'))"
        lte_fallback = f"({session_text} LIKE '%MULTIRAB%' AND ('/' || REPLACE({rat_text}, ' ', '') || '/') LIKE '%/LTE/%')"
        if technology == 'nsa':
            return f"(({whatsapp} AND {rat_nsa}) OR (NOT {whatsapp} AND ({mode_nsa} OR (NOT {recognised} AND ({rat_nsa} OR {lte_fallback})))))"
        return f"(({whatsapp} AND {rat_sa}) OR (NOT {whatsapp} AND ({mode_sa} OR (NOT {recognised} AND {rat_sa}))))"

    def selection_where(
        task_repository, kind, dataset_ids, definition, exclude=None, *, columns=None, include_dataset_scope=True,
    ):
        columns = columns or task_repository.list_reporting_row_columns(kind)
        quote = task_repository._quote_identifier
        clauses = []
        params = []
        if include_dataset_scope:
            placeholders = ', '.join('?' for _ in dataset_ids)
            clauses.append(f"dataset_id IN ({placeholders})")
            params.extend(int(dataset_id) for dataset_id in dataset_ids)
        excluded = identity(exclude) if exclude else ''
        for field_name, values in definition.filters.items():
            if identity(field_name) == excluded:
                continue
            column = resolve_sql_column(columns, field_name)
            if column is None or not values:
                clauses.append('0')
                continue
            value_placeholders = ', '.join('?' for _ in values)
            selected_column = (
                f"COALESCE(CAST({quote(column)} AS TEXT), '')"
                if any(str(value) == '' for value in values)
                else quote(column)
            )
            clauses.append(f"{selected_column} IN ({value_placeholders})")
            params.extend(str(value) for value in values)
        if definition.date_from or definition.date_to:
            date_column = next((resolve_sql_column(columns, candidate) for candidate in ('event_start_time', 'Test_Start_Time', 'Timestamp', 'Date') if resolve_sql_column(columns, candidate)), None)
            if date_column is None:
                clauses.append('0')
            else:
                if definition.date_from:
                    clauses.append(f"datetime({quote(date_column)}) >= datetime(?)")
                    params.append(definition.date_from.isoformat())
                if definition.date_to:
                    clauses.append(f"datetime({quote(date_column)}) < datetime(?, '+1 day')")
                    params.append(definition.date_to.isoformat())
        source_sheet = resolve_sql_column(columns, 'source_sheet')
        if source_sheet and core.CDR_IGNORED_SHEET_KEYS:
            ignored = sorted(core.CDR_IGNORED_SHEET_KEYS)
            clauses.append(f"({quote(source_sheet)} IS NULL OR LOWER(TRIM(CAST({quote(source_sheet)} AS TEXT))) NOT IN ({', '.join('?' for _ in ignored)}))")
            params.extend(ignored)
        if kind != 'data':
            clauses.append(nr_mode_sql(columns, definition.technology))
        return ' AND '.join(f'({clause})' for clause in clauses) or '1', params

    def ensure_filter_projection(definition, task_repository, dimensions, selected_by_kind, entries):
        selected_dimension_keys = {identity(name) for name in definition.custom_fields}
        active_dimensions = tuple(dimension for dimension in dimensions if identity(dimension.name) in selected_dimension_keys)
        for kind, selected in selected_by_kind.items():
            requested = set(core.combined_reporting_required_columns(active_dimensions, kind))
            requested.update(core.reporting_query_columns(kind, entries, definition.scope == 'multivendor'))
            requested.update(definition.custom_fields)
            requested.update(definition.filters)
            requested.update(alias for aliases in FILTER_COLUMNS.values() for alias in aliases)
            requested.update(('event_start_time', 'Test_Start_Time', 'Timestamp', 'Date'))
            existing = {identity(column) for column in task_repository.list_reporting_row_columns(kind)}
            source_columns = {
                identity(column)
                for row in selected
                for column in task_repository.list_dataset_row_columns(row['id'])
            }
            required = {identity(column) for column in requested if identity(column) in source_columns}
            repair = not required.issubset(existing)
            changed = False
            for row in selected:
                if repair or not task_repository.reporting_rows_exist_for_dataset(row['id'], kind):
                    task_repository.copy_dataset_rows_to_reporting(row['id'], kind, sorted(requested, key=str.casefold))
                    changed = True
            current = {identity(column) for column in task_repository.list_reporting_row_columns(kind)}
            missing_dimensions = tuple(
                dimension for dimension in active_dimensions
                if f'cdr-{kind}' in dimension.sources and identity(dimension.name) not in current
            )
            if missing_dimensions:
                core._incremental_auto_field_table_update(
                    task_repository, task_repository.reporting_rows_table_name(kind),
                    f'cdr-{kind}', (), missing_dimensions, {},
                )
                changed = True
            if changed:
                task_repository.set_workspace_state(f'combined_reporting_updated_{kind}', core.now_iso())

    def persistent_selection_key(definition, task_repository, dimensions, selected_by_kind):
        versions = {
            kind: [
                (row['id'], row.get('updated_at'), row.get('processed_at'), row.get('normalization_version'), row.get('row_count'))
                for row in selected
            ]
            for kind, selected in selected_by_kind.items()
        }
        revisions = {kind: task_repository.get_workspace_state(f'combined_reporting_updated_{kind}') for kind in selected_by_kind}
        selection_definition = {
            'technology': definition.technology,
            'datasets': definition.datasets,
            'filters': definition.filters,
            'custom_fields': definition.custom_fields,
            'hidden_filters': definition.hidden_filters,
            'date_from': definition.date_from,
            'date_to': definition.date_to,
        }
        payload = {
            # Scope changes only how charts group the already selected rows.
            # Keep that presentation setting out of the selection cache key.
            'schema': 4,
            'definition': selection_definition,
            'versions': versions,
            'combined_revisions': revisions,
            'dimensions': core.calculated_dimensions_json(dimensions),
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def selected_date_bounds(task_repository, selected_by_kind):
        """Return the inclusive calendar bounds across the selected source datasets."""
        lower = upper = None
        with task_repository.connection() as connection:
            for kind, selected in selected_by_kind.items():
                columns = task_repository.list_reporting_row_columns(kind)
                date_column = next((
                    resolve_sql_column(columns, candidate)
                    for candidate in ('event_start_time', 'Test_Start_Time', 'Timestamp', 'Date')
                    if resolve_sql_column(columns, candidate)
                ), None)
                if not date_column:
                    continue
                dataset_ids = [int(row['id']) for row in selected]
                placeholders = ', '.join('?' for _ in dataset_ids)
                table = task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))
                column = task_repository._quote_identifier(date_column)
                row = connection.execute(
                    f'SELECT MIN(date({column})) AS first_date, MAX(date({column})) AS last_date '
                    f'FROM {table} WHERE dataset_id IN ({placeholders})', dataset_ids,
                ).fetchone()
                for value, is_lower in ((row['first_date'], True), (row['last_date'], False)):
                    try:
                        parsed = date.fromisoformat(str(value)) if value else None
                    except ValueError:
                        parsed = None
                    if parsed is not None and (lower is None or parsed < lower) and is_lower:
                        lower = parsed
                    if parsed is not None and (upper is None or parsed > upper) and not is_lower:
                        upper = parsed
        if lower is None or upper is None:
            return None
        return {'min': lower.isoformat(), 'max': upper.isoformat()}

    def apply_selected_date_bounds(definition, bounds):
        if not bounds:
            return
        lower, upper = date.fromisoformat(bounds['min']), date.fromisoformat(bounds['max'])
        definition.date_from = lower if definition.date_from is None or not lower <= definition.date_from <= upper else definition.date_from
        definition.date_to = upper if definition.date_to is None or not lower <= definition.date_to <= upper else definition.date_to

    def profile_filter_options(definition, dimensions, selected_by_kind, fields):
        """Load large-dashboard facet values from selected CDR profiles."""
        options = {field_name: set() for field_name in fields}
        for selected in selected_by_kind.values():
            for dataset in selected:
                try:
                    stored = dataset.get('filter_options') or json.loads(dataset.get('filter_options_json') or '{}')
                except (TypeError, json.JSONDecodeError):
                    stored = {}
                lookup = {identity(column): values for column, values in stored.items()} if isinstance(stored, dict) else {}
                for field_name in fields:
                    aliases = next((values for label, values in FILTER_COLUMNS.items() if identity(label) == identity(field_name)), (field_name,))
                    for alias in aliases:
                        values = lookup.get(identity(alias), ())
                        if isinstance(values, list):
                            options[field_name].update(str(value) for value in values if value is not None)
        dimensions_by_name = {identity(dimension.name): dimension for dimension in dimensions}
        for field_name in fields:
            dimension = dimensions_by_name.get(identity(field_name))
            if dimension:
                options[field_name].update(str(rule.value) for rule in dimension.rules if str(rule.value).strip())
                if str(dimension.default).strip():
                    options[field_name].add(str(dimension.default))
            options[field_name].update(str(value) for value in definition.filters.get(field_name, ()) if value is not None)
        return {field_name: sorted(values, key=str.casefold) for field_name, values in options.items()}

    def materialize_selection(definition, task_repository, dimensions, selected_by_kind, fields, *, use_profile_options=False):
        cache_key = persistent_selection_key(definition, task_repository, dimensions, selected_by_kind)
        estimated_rows = sum(sum(int(row.get('row_count') or 0) for row in selected) for selected in selected_by_kind.values())
        use_profile_options = use_profile_options or estimated_rows > DASHBOARD_PROFILE_SELECTION_THRESHOLD
        with lock, task_repository.connection() as connection:
            cached = connection.execute(
                'SELECT id, options_json, row_counts_json, materialized FROM dashboard_filter_selections WHERE cache_key = ?',
                (cache_key,),
            ).fetchone()
            if cached:
                connection.execute('UPDATE dashboard_filter_selections SET last_accessed_at = CURRENT_TIMESTAMP WHERE id = ?', (cached['id'],))
                return (
                    int(cached['id']), cache_key, bool(cached['materialized']),
                    json.loads(cached['options_json']), json.loads(cached['row_counts_json']), True,
                )
            cursor = connection.execute('INSERT INTO dashboard_filter_selections (cache_key) VALUES (?)', (cache_key,))
            selection_id = int(cursor.lastrowid)
            predicates = {}
            row_counts = {}
            for kind, selected in selected_by_kind.items():
                dataset_ids = [int(row['id']) for row in selected]
                where, params = selection_where(task_repository, kind, dataset_ids, definition)
                table = task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))
                predicates[kind] = (where, params, table)
                row_counts[kind] = int(connection.execute(
                    f'SELECT COUNT(*) AS count FROM {table} WHERE {where}', params,
                ).fetchone()['count'])
            materialized = sum(row_counts.values()) <= DASHBOARD_SELECTION_ROW_LIMIT
            if materialized:
                for kind, (where, params, table) in predicates.items():
                    connection.execute(
                        'INSERT INTO dashboard_filter_selection_rows (selection_id, dataset_kind, dataset_id, source_row_id) '
                        f'SELECT ?, ?, dataset_id, source_row_id FROM {table} WHERE {where}',
                        (selection_id, kind, *params),
                    )
            # A full, unfiltered CDR selection can use its upload-time profile
            # catalogue. This avoids wide DISTINCT scans while row counts and
            # chart previews remain exact from the combined reporting tables.
            if use_profile_options:
                options = profile_filter_options(definition, dimensions, selected_by_kind, fields)
            else:
                # Active filters need facet values that exclude each field's
                # own restriction. Aggregate fields sharing a predicate in one
                # pass, keeping individual passes only where necessary.
                options = {field_name: set() for field_name in fields}
                active_filter_keys = {identity(field_name) for field_name in definition.filters}
                facet_groups: dict[str | None, list[str]] = {None: []}
                for field_name in fields:
                    excluded = field_name if identity(field_name) in active_filter_keys else None
                    facet_groups.setdefault(excluded, []).append(field_name)
                for kind, selected in selected_by_kind.items():
                    columns = task_repository.list_reporting_row_columns(kind)
                    table = task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))
                    for excluded, group_fields in facet_groups.items():
                        available = [(field_name, resolve_sql_column(columns, field_name)) for field_name in group_fields]
                        available = [(field_name, column) for field_name, column in available if column is not None]
                        if not available:
                            continue
                        where, params = selection_where(
                            task_repository, kind, [int(row['id']) for row in selected], definition, exclude=excluded,
                        )
                        select_clause = ', '.join(
                            f"json_group_array(DISTINCT COALESCE(CAST({task_repository._quote_identifier(column)} AS TEXT), '')) AS facet_{index}"
                            for index, (_field_name, column) in enumerate(available)
                        )
                        row = connection.execute(f'SELECT {select_clause} FROM {table} WHERE {where}', params).fetchone()
                        for index, (field_name, _column) in enumerate(available):
                            encoded_values = row[f'facet_{index}'] if row else '[]'
                            options[field_name].update(str(value) for value in json.loads(encoded_values or '[]'))
                options = {field_name: sorted(values, key=str.casefold) for field_name, values in options.items()}
            connection.execute(
                'UPDATE dashboard_filter_selections SET options_json = ?, row_counts_json = ?, materialized = ? WHERE id = ?',
                (json.dumps(options), json.dumps(row_counts), int(materialized), selection_id),
            )
            stale = connection.execute(
                'SELECT id FROM dashboard_filter_selections ORDER BY last_accessed_at DESC, id DESC LIMIT -1 OFFSET 8'
            ).fetchall()
            for row in stale:
                connection.execute('DELETE FROM dashboard_filter_selection_rows WHERE selection_id = ?', (row['id'],))
                connection.execute('DELETE FROM dashboard_filter_selections WHERE id = ?', (row['id'],))
            return selection_id, cache_key, materialized, options, row_counts, True

    def build_preview(definition, user, *, workspace: str | None = None, cancelled=None):
        def ensure_not_cancelled():
            if callable(cancelled) and cancelled():
                raise RuntimeError('Dashboard preparation cancelled.')

        workspace = workspace or workspace_key()
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        entries = validate(definition, task_repository)
        dimensions = core.load_repository_calculated_dimensions(task_repository)
        selected_by_kind = selected_sources(definition, task_repository)
        ensure_filter_projection(definition, task_repository, dimensions, selected_by_kind, entries)
        date_bounds = selected_date_bounds(task_repository, selected_by_kind)
        apply_selected_date_bounds(definition, date_bounds)
        selected_dataset_ids = {dataset_id for ids in definition.datasets.values() for dataset_id in ids}
        available_fields = {column for dataset_id in selected_dataset_ids for column in task_repository.list_dataset_row_columns(dataset_id)}
        available_fields.update(dimension.name for dimension in dimensions)
        hidden_filter_keys = {identity(field) for field in definition.hidden_filters}
        fields = {field for field in ADAPTATIVE_FILTER_FIELDS if identity(field) not in hidden_filter_keys}
        fields.update(definition.custom_fields)
        fields = sorted(fields, key=str.casefold)
        use_profile_options = bool(
            date_bounds
            and not definition.filters
            and str(definition.date_from) == date_bounds['min']
            and str(definition.date_to) == date_bounds['max']
        )
        selection_id, selection_key, selection_materialized, options, row_counts, rows_exact = materialize_selection(
            definition, task_repository, dimensions, selected_by_kind, fields, use_profile_options=use_profile_options,
        )
        slides = OrderedDict()
        deck = Presentation(core.settings.ppt_templates_dir / 'Template_CDR_analysis.pptx')
        for editor_index, (index, entry) in enumerate(sorted(enumerate(entries), key=lambda item: (item[1].slide, item[0]))):
            slide = slides.setdefault(entry.slide, {
                'number': entry.slide,
                'title': entry.slide_title,
                'subtitle': entry.slide_subtitle,
                'layout': entry.layout,
                'structural_type': entry.structural_type or '',
                'charts': [],
                'focus_row': editor_index,
            })
            if not entry.structural_type:
                slide['charts'].append({
                    'index': index, 'title': entry.chart_title, 'source': entry.source_kind,
                    'available': entry.source_kind in selected_by_kind, 'focus_row': editor_index,
                })
        for slide in slides.values():
            bounds = _layout_chart_frames(_named_slide_layout(deck, slide['layout']))
            if bounds and len(bounds) >= len(slide['charts']):
                left, top = min(b[0] for b in bounds), min(b[1] for b in bounds)
                width = max(b[0] + b[2] for b in bounds) - left
                height = max(b[1] + b[3] for b in bounds) - top
                for chart, (x, y, w, h) in zip(slide['charts'], bounds):
                    chart['position'] = [(x-left)/width*100, (y-top)/height*100, w/width*100, h/height*100]
        token = uuid4().hex
        payload = {
            'slides': list(slides.values()), 'options': options,
            'filter_fields': list(ADAPTATIVE_FILTER_FIELDS),
            'available_fields': sorted(available_fields, key=str.casefold),
            'rows': row_counts,
            'rows_exact': rows_exact,
            'date_bounds': date_bounds,
        }
        with lock:
            snapshots[token] = Snapshot(
                workspace, user.username, entries, {}, definition.scope == 'multivendor',
                definition.model_copy(deep=True), tuple(dimensions), selection_id, selection_key, selection_materialized, payload,
                cancelled=cancelled,
            )
            # Background-warmed Dashboards keep only lightweight snapshots so
            # users can switch between them without rebuilding their filters.
            while len(snapshots) > 128:
                snapshots.popitem(last=False)
            snapshot = snapshots[token]
        # Build or restore the narrow source projections while the task is
        # still in its data-preparation phase. Chart rendering then reads a
        # small indexed table instead of paying this one-time cost per chart.
        for kind in selected_by_kind:
            ensure_not_cancelled()
            ensure_projection(snapshot, kind, task_repository)
        ensure_not_cancelled()
        # Load and filter the inputs for uncached Canvas models while the job
        # is still preparing Dashboard data. The rendering phase then only
        # performs the chart aggregation/serialisation work measured by its
        # task, rather than charging SQLite reads to every individual chart.
        pending_frames = [
            index for index, entry in enumerate(snapshot.entries)
            if entry.source_kind in selected_by_kind
            and not canvas_model_path(snapshot, entry).is_file()
        ]
        with ThreadPoolExecutor(
            max_workers=DASHBOARD_CHART_RENDER_WORKERS,
            thread_name_prefix='e2e-dashboard-data',
        ) as data_executor:
            while pending_frames:
                ensure_not_cancelled()
                batch = pending_frames[:DASHBOARD_CHART_RENDER_WORKERS]
                pending_frames = pending_frames[DASHBOARD_CHART_RENDER_WORKERS:]
                futures = [
                    data_executor.submit(
                        snapshot_chart, token, index, user, expected_workspace=workspace,
                    )
                    for index in batch
                ]
                for future in as_completed(futures):
                    future.result()
                ensure_not_cancelled()
        return {**payload, 'token': token}

    def preview_manifest_path(workspace: str, dashboard_id: str, fingerprint: str) -> Path:
        cache_key = sha256(
            f'{DASHBOARD_PREVIEW_MANIFEST_VERSION}:{dashboard_id}:{fingerprint}'.encode()
        ).hexdigest()
        return preview_manifest_cache_dir(workspace) / f'{cache_key}.json'

    def persist_preview_manifest(
        workspace: str,
        dashboard_id: str,
        fingerprint: str,
        token: str,
    ) -> None:
        with lock:
            snapshot = snapshots.get(token)
            if snapshot is None:
                return
            manifest = {
                'version': DASHBOARD_PREVIEW_MANIFEST_VERSION,
                'dashboard_id': dashboard_id,
                'fingerprint': fingerprint,
                'definition': snapshot.definition.model_dump(mode='json'),
                'selection_id': snapshot.selection_id,
                'selection_key': snapshot.selection_key,
                'selection_materialized': snapshot.selection_materialized,
                'payload': snapshot.payload,
            }
        manifest_path = preview_manifest_path(workspace, dashboard_id, fingerprint)
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = manifest_path.with_suffix(f'.{uuid4().hex}.tmp')
            temporary.write_text(json.dumps(manifest, separators=(',', ':')), encoding='utf-8')
            temporary.replace(manifest_path)
        except OSError:
            pass

    def restore_preview_manifest(
        workspace: str,
        dashboard_id: str,
        fingerprint: str,
    ) -> dict | None:
        manifest_path = preview_manifest_path(workspace, dashboard_id, fingerprint)
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if (
                manifest.get('version') != DASHBOARD_PREVIEW_MANIFEST_VERSION
                or manifest.get('dashboard_id') != dashboard_id
                or manifest.get('fingerprint') != fingerprint
            ):
                return None
            definition = DashboardDefinition.model_validate(manifest['definition'])
            task_repository = Repository(Path(workspace), core.repository.global_db_path)
            entries = validate(definition, task_repository)
            dimensions = core.load_repository_calculated_dimensions(task_repository)
            selected_by_kind = selected_sources(definition, task_repository)
            selection_key = persistent_selection_key(definition, task_repository, dimensions, selected_by_kind)
            if selection_key != manifest.get('selection_key'):
                return None
            selection_id = int(manifest['selection_id'])
            with task_repository.connection() as connection:
                selection = connection.execute(
                    'SELECT id FROM dashboard_filter_selections WHERE id = ? AND cache_key = ?',
                    (selection_id, selection_key),
                ).fetchone()
            if selection is None:
                return None
            payload = manifest['payload']
            if not isinstance(payload, dict) or not isinstance(payload.get('slides'), list):
                return None
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, sqlite3.Error):
            return None
        token = uuid4().hex
        with lock:
            snapshots[token] = Snapshot(
                workspace, '*', entries, {}, definition.scope == 'multivendor',
                definition, tuple(dimensions), selection_id, selection_key,
                bool(manifest.get('selection_materialized')), payload,
            )
            while len(snapshots) > 128:
                snapshots.popitem(last=False)
        return {**payload, 'token': token}

    @app.post('/api/e2e-dashboards/prepare')
    def prepare(
        definition: DashboardDefinition,
        dashboard_id: str | None = None,
        rendering_only: bool = False,
        preparation_id: str | None = None,
        user=Depends(dashboard_user),
    ):
        preparation_id = preparation_id or f'dashboard-preparation:{uuid4().hex}'
        workspace = workspace_key()
        cancellation = {'requested': False}
        with lock:
            direct_preparation_tasks[preparation_id] = {
                'id': preparation_id, 'workspace': workspace, 'name': definition.name,
                'rendering_only': rendering_only, 'cancellation': cancellation,
            }
        try:
            def preparation_cancelled():
                return bool(cancellation['requested'])

            preview = build_preview(
                definition, user, workspace=workspace, cancelled=preparation_cancelled,
            )
            if dashboard_id:
                enqueue_prefetch(
                    dashboard_id,
                    definition.model_dump(mode='json'),
                    user,
                    prepared_preview=preview,
                )
            return preview
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            with lock:
                direct_preparation_tasks.pop(preparation_id, None)

    @app.get('/api/e2e-dashboards/prepared/{token}')
    def prepared_preview(token: str, user=Depends(dashboard_user)):
        with lock:
            snapshot = snapshots.get(token)
            if snapshot is None or snapshot.workspace != workspace_key() or snapshot.owner not in {user.username, '*'}:
                raise HTTPException(410, 'Dashboard preview expired. Refresh the Dashboard.')
            return {**snapshot.payload, 'token': token}

    @app.get('/api/e2e-dashboards/prefetched/{dashboard_id}')
    def prefetched_dashboard(dashboard_id: str, user=Depends(dashboard_user)):
        workspace = workspace_key()
        with lock:
            dashboards = read_dashboards(bound_repository())
            raw_definition = dashboards.get(dashboard_id)
            if not isinstance(raw_definition, dict):
                raise HTTPException(404, 'Dashboard not found.')
            fingerprint = sha256(json.dumps(raw_definition, sort_keys=True, default=str).encode()).hexdigest()
            # Warm-up jobs are shared by every permitted user of the
            # workspace.  Their snapshot owner is the system user (`*`), so
            # use the same key created by enqueue_prefetch rather than a
            # user-specific variant that can never be found.
            key = f'{workspace}:{dashboard_id}:{fingerprint}'
            job = prefetch_jobs.get(key)
            if job and job.get('status') == 'failed':
                raise HTTPException(500, str(job.get('error') or 'Dashboard preparation failed.'))
            # The snapshot is available as soon as the selection is built.
            # It remains safe to serve while the worker fills missing Canvas
            # models because chart_model reads a disk hit when present and
            # computes only the chart requested by the viewer when absent.
            # A restored partial manifest already has a usable snapshot while
            # its remaining Canvas models wait behind another dashboard in the
            # serial worker queue. Serve it immediately instead of returning
            # 409 until that queue position starts.
            token = str(job.get('token') or '') if job and job.get('status') in {'queued', 'processing', 'ready'} else ''
            snapshot = snapshots.get(token)
            if not token or snapshot is None or snapshot.owner not in {user.username, '*'}:
                raise HTTPException(409, 'Dashboard preparation is still running.')
            snapshots.move_to_end(token)
            return {**snapshot.payload, 'token': token}

    def source_spec(snapshot, kind, task_repository):
        selected = core._optional_reporting_datasets(
            snapshot.definition.datasets.get(kind, []), kind, task_repository,
        )
        if not selected:
            raise HTTPException(400, 'Unavailable source type: select a matching CDR dataset.')
        entries = [entry for entry in snapshot.entries if entry.source_kind == kind]
        columns = set(core.reporting_query_columns(kind, entries, snapshot.multivendor))
        columns.update(alias for aliases in FILTER_COLUMNS.values() for alias in aliases)
        columns.update(snapshot.definition.filters)
        columns.update(snapshot.definition.custom_fields)
        columns.update(('event_start_time', 'Test_Start_Time', 'Timestamp', 'Date', 'dataset_id', 'source_row_id'))
        requested_keys = {identity(column) for column in columns}
        active_dimensions = tuple(
            dimension for dimension in snapshot.dimensions if identity(dimension.name) in requested_keys
        )
        columns.update(core.combined_reporting_required_columns(active_dimensions, kind))
        ordered_columns = sorted(columns, key=lambda column: (identity(column), str(column)))
        material = {
            'schema': DASHBOARD_PROJECTION_CACHE_VERSION,
            'workspace': str(Path(snapshot.workspace).resolve()),
            'kind': kind,
            'datasets': [
                (row['id'], row.get('updated_at'), row.get('processed_at'), row.get('normalization_version'), row.get('row_count'))
                for row in selected
            ],
            'revision': task_repository.get_workspace_state(f'combined_reporting_updated_{kind}'),
            'columns': ordered_columns,
        }
        cache_key = sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()
        return selected, ordered_columns, cache_key

    def projection_connection(cache_path):
        connection = sqlite3.connect(cache_path, timeout=120.0)
        connection.row_factory = sqlite3.Row
        connection.execute(f'PRAGMA page_size={DASHBOARD_PROJECTION_PAGE_SIZE}')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute('PRAGMA temp_store=MEMORY')
        connection.execute(f'PRAGMA cache_size=-{DASHBOARD_PROJECTION_CACHE_KIB}')
        connection.execute(f'PRAGMA mmap_size={DASHBOARD_PROJECTION_MMAP_SIZE}')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS projection_cache ('
            'cache_key TEXT PRIMARY KEY, dataset_kind TEXT NOT NULL, table_name TEXT NOT NULL UNIQUE, '
            'created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, last_accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'
        )
        return connection

    def ensure_snapshot_not_cancelled(snapshot):
        if callable(snapshot.cancelled) and snapshot.cancelled():
            raise RuntimeError('Dashboard preparation cancelled.')

    def ensure_projection(snapshot, kind, task_repository):
        ensure_snapshot_not_cancelled(snapshot)
        with lock:
            existing = snapshot.projections.get(kind)
        if existing is not None:
            return existing
        selected, requested_columns, cache_key = source_spec(snapshot, kind, task_repository)
        with lock:
            projection_lock = projection_load_locks.setdefault(cache_key, RLock())
        with projection_lock:
            ensure_snapshot_not_cancelled(snapshot)
            with lock:
                existing = snapshot.projections.get(kind)
            if existing is not None:
                return existing
            cache_dir = Path(snapshot.workspace).parent / '.dashboard-data-cache'
            cache_dir.mkdir(parents=True, exist_ok=True)
            ensure_snapshot_not_cancelled(snapshot)
            cache_path = cache_dir / 'dashboard-analytics.sqlite3'
            table_name = f'projection_{kind}_{cache_key[:20]}'
            source_columns = task_repository.list_reporting_row_columns(kind)
            source_lookup = {identity(column): column for column in source_columns}
            projected_columns = []
            for requested in requested_columns:
                actual = source_lookup.get(identity(requested))
                if actual and actual not in projected_columns:
                    projected_columns.append(actual)
            for required in ('dataset_id', 'source_row_id'):
                actual = source_lookup.get(identity(required))
                if actual and actual not in projected_columns:
                    projected_columns.insert(0, actual)
            if not projected_columns:
                raise ValueError(f'The selected {kind.title()} CDRs have no materialised reporting columns.')
            connection = projection_connection(cache_path)
            temporary = f'building_{kind}_{uuid4().hex}'
            try:
                connection.execute('ATTACH DATABASE ? AS workspace_source', (snapshot.workspace,))
                connection.execute(f'PRAGMA workspace_source.cache_size=-{DASHBOARD_PROJECTION_CACHE_KIB}')
                connection.execute(f'PRAGMA workspace_source.mmap_size={DASHBOARD_PROJECTION_MMAP_SIZE}')
                connection.execute('BEGIN IMMEDIATE')
                found = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,),
                ).fetchone()
                if not found:
                    dataset_ids = [int(row['id']) for row in selected]
                    available_dataset_ids = [
                        int(row['dataset_id']) for row in connection.execute(
                            f'SELECT DISTINCT dataset_id FROM workspace_source.'
                            f'{task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))}'
                        ).fetchall()
                    ]
                    scan_hint = dashboard_projection_scan_hint(dataset_ids, available_dataset_ids)
                    placeholders = ', '.join('?' for _ in dataset_ids)
                    select_clause = ', '.join(
                        task_repository._quote_identifier(column) for column in projected_columns
                    )
                    connection.execute(
                        f'CREATE TABLE {task_repository._quote_identifier(temporary)} AS '
                        f'SELECT {select_clause} FROM workspace_source.'
                        f'{task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))}'
                        f'{scan_hint} '
                        f'WHERE dataset_id IN ({placeholders})',
                        dataset_ids,
                    )
                    ensure_snapshot_not_cancelled(snapshot)
                    connection.execute(
                        f'ALTER TABLE {task_repository._quote_identifier(temporary)} '
                        f'RENAME TO {task_repository._quote_identifier(table_name)}'
                    )
                projection_columns = [
                    row['name'] for row in connection.execute(
                        f'PRAGMA table_info({task_repository._quote_identifier(table_name)})'
                    ).fetchall()
                ]
                projection_lookup = {identity(column): column for column in projection_columns}
                indexed_columns = []
                for aliases in FILTER_COLUMNS.values():
                    actual = next(
                        (projection_lookup[identity(alias)] for alias in aliases if identity(alias) in projection_lookup),
                        None,
                    )
                    if actual and actual not in indexed_columns:
                        indexed_columns.append(actual)
                for entry in snapshot.entries:
                    if entry.source_kind != kind:
                        continue
                    filter_fields = (
                        part.strip()
                        for condition in parse_catalog_filters(entry.filters)
                        for part in condition.column.split('|')
                    )
                    for field_name in filter_fields:
                        actual = resolve_sql_column(projection_columns, field_name)
                        if actual and actual not in indexed_columns:
                            indexed_columns.append(actual)
                for indexed_column in indexed_columns:
                    ensure_snapshot_not_cancelled(snapshot)
                    legacy_index_name = f'idx_{table_name}_{sha256(indexed_column.encode()).hexdigest()[:8]}'
                    index_name = f'idx_{table_name}_{sha256(f"nocase:{indexed_column}".encode()).hexdigest()[:8]}'
                    connection.execute(
                        f'DROP INDEX IF EXISTS {task_repository._quote_identifier(legacy_index_name)}'
                    )
                    connection.execute(
                        f'CREATE INDEX IF NOT EXISTS {task_repository._quote_identifier(index_name)} '
                        f'ON {task_repository._quote_identifier(table_name)} '
                        f'({task_repository._quote_identifier(indexed_column)} COLLATE NOCASE)'
                    )
                connection.execute(
                    'INSERT INTO projection_cache (cache_key, dataset_kind, table_name) VALUES (?, ?, ?) '
                    'ON CONFLICT(cache_key) DO UPDATE SET last_accessed_at = CURRENT_TIMESTAMP',
                    (cache_key, kind, table_name),
                )
                stale = connection.execute(
                    'SELECT cache_key, table_name FROM projection_cache '
                    'ORDER BY last_accessed_at DESC, created_at DESC LIMIT -1 OFFSET ?',
                    (DASHBOARD_PROJECTION_DISK_LIMIT,),
                ).fetchall()
                for stale_projection in stale:
                    ensure_snapshot_not_cancelled(snapshot)
                    connection.execute(
                        f'DROP TABLE IF EXISTS {task_repository._quote_identifier(stale_projection["table_name"])}'
                    )
                    connection.execute('DELETE FROM projection_cache WHERE cache_key = ?', (stale_projection['cache_key'],))
                ensure_snapshot_not_cancelled(snapshot)
                connection.commit()
            except Exception:
                connection.rollback()
                try:
                    connection.execute(f'DROP TABLE IF EXISTS {task_repository._quote_identifier(temporary)}')
                    connection.commit()
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
            for legacy in cache_dir.glob('*.pkl'):
                legacy.unlink(missing_ok=True)
            result = (cache_path, table_name, projection_columns)
            with lock:
                snapshot.projections[kind] = result
                if len(projection_load_locks) > DASHBOARD_PROJECTION_DISK_LIMIT * 3:
                    projection_load_locks.pop(next(iter(projection_load_locks)))
            return result

    def chart_query_columns(entry, multivendor):
        reported = core.reporting_query_columns(entry.source_kind, [entry], multivendor)
        explicit = {
            part.strip(' `')
            for part in re.split(r'\s+vs\s+|\s*\|\s*', entry.kpi, flags=re.I)
            if part.strip()
        }
        explicit.update(_legend_dimensions(entry.legend))
        explicit.update(parse_catalog_grouping(entry.grouping_rows).dimensions)
        explicit.update(parse_catalog_grouping(entry.grouping_columns).dimensions)
        explicit.update(condition.column for condition in parse_catalog_filters(entry.filters))
        for dimension in entry.calculated_dimensions:
            explicit.update(dimension.default_from)
            for rule in dimension.rules:
                for condition in rule.conditions:
                    explicit.update(part.strip() for part in condition.column.split('|') if part.strip())
        explicit_keys = {identity(column) for column in explicit}
        core_keys = {identity(column) for column in Repository.REPORTING_CORE_COLUMNS}
        always = {identity('report_vendor')} if multivendor else set()
        selected = [
            column for column in reported
            if identity(column) not in core_keys or identity(column) in explicit_keys or identity(column) in always
        ]
        selected.extend(('dataset_id', 'source_row_id'))
        return list(dict.fromkeys(selected))

    def chart_filter_sql(entry, columns, multivendor):
        """Push safe physical template filters into SQLite before DataFrame creation."""
        clauses = []
        parameters = []
        complete = True
        quote = lambda value: '"' + str(value).replace('"', '""') + '"'
        for condition in parse_catalog_filters(entry.filters):
            normalized = identity(condition.column)
            if normalized in {'threshold', 'buckets'}:
                continue
            if multivendor and normalized in {'operator', 'vendor', 'reportvendor', 'vendorv3'}:
                complete = False
                continue
            column = next((
                resolve_sql_column(columns, candidate.strip())
                for candidate in condition.column.split('|')
                if resolve_sql_column(columns, candidate.strip())
            ), None)
            if not column:
                complete = False
                continue
            values = [str(value) for value in condition.values]
            if normalized == 'operator':
                operator_aliases = {
                    'vf': ('VF', 'Vodafone', 'Vodafone UK'),
                    'vodafone': ('VF', 'Vodafone', 'Vodafone UK'),
                    'vodafoneuk': ('VF', 'Vodafone', 'Vodafone UK'),
                    '3': ('3', 'Three', '3 UK'),
                    'three': ('3', 'Three', '3 UK'),
                    '3uk': ('3', 'Three', '3 UK'),
                    'ee': ('EE',),
                    'o2': ('O2', 'Telefonica', 'Telefónica'),
                    'telefonica': ('O2', 'Telefonica', 'Telefónica'),
                }
                values = list(dict.fromkeys(
                    alias
                    for value in values
                    for alias in operator_aliases.get(identity(value), (value,))
                ))
            selected = (
                f"COALESCE(CAST({quote(column)} AS TEXT), '') COLLATE NOCASE"
                if '' in values
                else f'{quote(column)} COLLATE NOCASE'
            )
            if normalized in {'vendor', 'reportvendor', 'vendorv3'} and condition.operator not in {'CONTAINS', 'NOT CONTAINS'}:
                complete = False
                continue
            if condition.operator in {'=', '!='} and len(values) > 1:
                placeholders = ', '.join('?' for _value in values)
                expression = f'{selected} IN ({placeholders})'
                clauses.append(f'NOT ({expression})' if condition.operator == '!=' else expression)
                parameters.extend(values)
            elif condition.operator in {'=', '!='}:
                clauses.append(f'{selected} {condition.operator} ?')
                parameters.append(values[0])
            elif condition.operator in {'IN', 'NOT IN'}:
                placeholders = ', '.join('?' for _value in values)
                expression = f'{selected} IN ({placeholders})'
                clauses.append(f'NOT ({expression})' if condition.operator == 'NOT IN' else expression)
                parameters.extend(values)
            elif condition.operator in {'CONTAINS', 'NOT CONTAINS'}:
                checks = [f'instr(LOWER(COALESCE(CAST({quote(column)} AS TEXT), \'\')), LOWER(?)) > 0' for _value in values]
                expression = f'({" OR ".join(checks)})'
                clauses.append(f'NOT {expression}' if condition.operator == 'NOT CONTAINS' else expression)
                parameters.extend(values)
            else:
                complete = False
        return ' AND '.join(clauses), parameters, complete

    def chart_aggregation_columns(entry, columns, multivendor, filters_applied):
        """Return physical dimensions that SQLite can aggregate without changing chart semantics."""
        if (
            multivendor
            or not filters_applied
            or entry.calculated_dimensions
            or entry.chart_type.casefold() != '100% stacked vertical bars'
        ):
            return None
        requested = [
            *parse_catalog_grouping(entry.grouping_rows).dimensions,
            *parse_catalog_grouping(entry.grouping_columns).dimensions,
            *(
                part.strip(' `')
                for part in re.split(r'\s+vs\s+|\s*\|\s*', entry.kpi, flags=re.I)
                if part.strip()
            ),
        ]
        resolved = [resolve_sql_column(columns, name) for name in requested]
        if any(column is None for column in resolved):
            return None
        return list(dict.fromkeys(resolved))

    def load_projection_frame(
        cache_path, table_name, projection_columns, requested_columns, where, parameters,
        aggregation_columns=None,
    ):
        lookup = {identity(column): column for column in projection_columns}
        selected_columns = []
        for requested in aggregation_columns or requested_columns:
            actual = lookup.get(identity(requested))
            if actual and actual not in selected_columns:
                selected_columns.append(actual)
        if not selected_columns:
            return pd.DataFrame()
        quote = lambda column: '"' + str(column).replace('"', '""') + '"'
        select_clause = ", ".join(quote(column) for column in selected_columns)
        if aggregation_columns:
            select_clause += ', COUNT(*) AS "__catalog_weight"'
        query = f'SELECT {select_clause} FROM {quote(table_name)} WHERE {where}'
        if aggregation_columns:
            query += f' GROUP BY {", ".join(quote(column) for column in selected_columns)}'
        connection = sqlite3.connect(cache_path, timeout=120.0)
        try:
            return pd.read_sql_query(query, connection, params=parameters)
        finally:
            connection.close()

    def snapshot_chart(token, index, user, *, include_frame=True, expected_workspace: str | None = None):
        with lock:
            snapshot = snapshots.get(token)
        if snapshot is None or snapshot.workspace != (expected_workspace or workspace_key()) or snapshot.owner not in {user.username, '*'}:
            raise HTTPException(410, 'Dashboard preview expired. Refresh the Dashboard.')
        if index < 0 or index >= len(snapshot.entries):
            raise HTTPException(404, 'Chart not found.')
        entry = snapshot.entries[index]
        if not include_frame:
            return snapshot, entry, None
        with lock:
            frame = snapshot.chart_frames.get(index)
        if frame is None:
            task_repository = Repository(Path(snapshot.workspace), core.repository.global_db_path)
            selected = core._optional_reporting_datasets(
                snapshot.definition.datasets.get(entry.source_kind, []), entry.source_kind, task_repository,
            )
            cache_path, table_name, projection_columns = ensure_projection(
                snapshot, entry.source_kind, task_repository,
            )
            where, parameters = selection_where(
                task_repository, entry.source_kind, [int(row['id']) for row in selected], snapshot.definition,
                columns=projection_columns, include_dataset_scope=False,
            )
            requested_columns = chart_query_columns(entry, snapshot.multivendor)
            template_where, template_parameters, template_filters_applied = chart_filter_sql(
                entry, projection_columns, snapshot.multivendor,
            )
            if template_where:
                where = f'({where}) AND ({template_where})'
                parameters.extend(template_parameters)
            aggregation_columns = chart_aggregation_columns(
                entry, projection_columns, snapshot.multivendor, template_filters_applied,
            )
            raw_key = sha256(json.dumps({
                'kind': entry.source_kind, 'columns': requested_columns, 'where': where, 'parameters': parameters,
                'aggregation_columns': aggregation_columns,
            }, sort_keys=True, default=str).encode()).hexdigest()
            with lock:
                raw_frame = snapshot.frames.get(raw_key)
                frame_lock = snapshot.frame_locks.setdefault(raw_key, RLock())
            if raw_frame is None:
                with frame_lock:
                    with lock:
                        raw_frame = snapshot.frames.get(raw_key)
                    if raw_frame is None:
                        raw_frame = load_projection_frame(
                            cache_path, table_name, projection_columns, requested_columns, where, parameters,
                            aggregation_columns,
                        )
                        if snapshot.multivendor:
                            raw_frame = ensure_report_vendor_group(raw_frame)
                        raw_frame = normalise_report_operator_aliases(raw_frame)
                        raw_frame.attrs['report_operator_aliases_normalized'] = True
                        with lock:
                            snapshot.frames[raw_key] = raw_frame
            # A CDF and its companion Average/Median chart normally use the
            # same source, KPI and template filters. Share that expensive
            # filtering pass while keeping each chart's aggregation and visual
            # model independent.
            filtered_key = sha256(repr((
                raw_key, entry.cdr_source, entry.kpi, entry.filters,
                entry.calculated_dimensions, snapshot.multivendor,
            )).encode()).hexdigest()
            with lock:
                prepared_frame = snapshot.filtered_frames.get(filtered_key)
                filter_lock = snapshot.frame_locks.setdefault(f'filtered:{filtered_key}', RLock())
            if prepared_frame is None:
                with filter_lock:
                    with lock:
                        prepared_frame = snapshot.filtered_frames.get(filtered_key)
                    if prepared_frame is None:
                        try:
                            prepared_frame = prepare_catalog_chart_preview_frame(
                                raw_frame, entry, multivendor=snapshot.multivendor,
                                template_filters_applied=template_filters_applied,
                            )[0]
                        except ValueError as exc:
                            raise HTTPException(400, str(exc)) from exc
                        with lock:
                            prepared_frame = snapshot.filtered_frames.setdefault(filtered_key, prepared_frame)
            with lock:
                frame = snapshot.chart_frames.setdefault(index, prepared_frame)
        return snapshot, entry, frame

    def chart_model(token: str, index: int, user, *, expected_workspace: str | None = None):
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False, expected_workspace=expected_workspace)
        with lock:
            payload = snapshot.chart_payloads.get(index)
        model_path = canvas_model_path(snapshot, entry)
        model_dir = model_path.parent
        if payload is None and model_path.is_file():
            try:
                payload = json.loads(model_path.read_text(encoding='utf-8'))
                model_path.touch()
            except (OSError, json.JSONDecodeError):
                model_path.unlink(missing_ok=True)
                payload = None
        if payload is None:
            snapshot, entry, frame = snapshot_chart(token, index, user, expected_workspace=expected_workspace)
            payload = catalog_chart_payload(
                frame, entry, multivendor=snapshot.multivendor, prefiltered=True,
            )
            with lock:
                payload = snapshot.chart_payloads.setdefault(index, payload)
            try:
                if callable(snapshot.cancelled) and snapshot.cancelled():
                    return payload
                model_dir.mkdir(parents=True, exist_ok=True)
                temporary = model_path.with_suffix(f'.{uuid4().hex}.tmp')
                temporary.write_text(json.dumps(payload, separators=(',', ':')), encoding='utf-8')
                if callable(snapshot.cancelled) and snapshot.cancelled():
                    temporary.unlink(missing_ok=True)
                    return payload
                temporary.replace(model_path)
                cached_models = sorted(model_dir.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)
                for stale in cached_models[DASHBOARD_CHART_MODEL_DISK_LIMIT:]:
                    stale.unlink(missing_ok=True)
            except OSError:
                pass
        with lock:
            snapshot.chart_payloads.setdefault(index, payload)
        return payload

    def canvas_model_path(snapshot, entry) -> Path:
        """Return the persistent Canvas-model location for one chart entry."""
        entry_key = sha256(repr(entry).encode()).hexdigest()
        filename = sha256(
            f'{DASHBOARD_CHART_MODEL_CACHE_VERSION}:{snapshot.selection_key}:{snapshot.definition.scope}:{entry_key}'.encode()
        ).hexdigest()
        return canvas_model_cache_dir(snapshot.workspace) / f'{filename}.json'

    def cached_canvas_model_indexes(token: str) -> set[int]:
        """Return Canvas models already available for a restored snapshot."""
        with lock:
            snapshot = snapshots.get(token)
            if snapshot is None:
                return set()
            indexes = {
                int(chart['index'])
                for slide in snapshot.payload.get('slides', [])
                for chart in slide.get('charts', [])
                if chart.get('available')
            }
            return {
                index for index in indexes
                if 0 <= index < len(snapshot.entries)
                and canvas_model_path(snapshot, snapshot.entries[index]).is_file()
            }

    def snapshot_canvas_model_paths(snapshot: Snapshot) -> list[str]:
        indexes = {
            int(chart['index'])
            for slide in snapshot.payload.get('slides', [])
            for chart in slide.get('charts', [])
            if chart.get('available')
        }
        return [
            str(canvas_model_path(snapshot, snapshot.entries[index]))
            for index in sorted(indexes)
            if 0 <= index < len(snapshot.entries)
        ]

    def cached_models_complete(definition, workspace: str) -> bool:
        """Check the persistent Canvas cache without materialising chart frames."""
        candidate = definition.model_copy(deep=True)
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        entries = validate(candidate, task_repository)
        dimensions = core.load_repository_calculated_dimensions(task_repository)
        selected_by_kind = selected_sources(candidate, task_repository)
        apply_selected_date_bounds(candidate, selected_date_bounds(task_repository, selected_by_kind))
        selection_key = persistent_selection_key(candidate, task_repository, dimensions, selected_by_kind)
        model_dir = canvas_model_cache_dir(workspace)
        for entry in entries:
            if entry.structural_type or entry.source_kind not in selected_by_kind:
                continue
            entry_key = sha256(repr(entry).encode()).hexdigest()
            model_path = model_dir / sha256(
                f'{DASHBOARD_CHART_MODEL_CACHE_VERSION}:{selection_key}:{candidate.scope}:{entry_key}'.encode()
            ).hexdigest()
            if not model_path.with_suffix('.json').is_file():
                return False
        return True

    @app.get('/api/e2e-dashboards/chart/{token}/{index}')
    def interactive_chart(token: str, index: int, user=Depends(dashboard_user)):
        payload = chart_model(token, index, user)
        return JSONResponse(payload, headers={'Cache-Control': 'private, max-age=3600'})

    @app.post('/api/e2e-dashboards/prefetched/{dashboard_id}/priority')
    def prioritize_prefetched_dashboard(
        dashboard_id: str, payload: DashboardPrefetchPriority, user=Depends(dashboard_user),
    ):
        """Move models from the currently visible slide ahead of later work."""
        workspace = workspace_key()
        with lock:
            raw_definition = read_dashboards(bound_repository()).get(dashboard_id)
            if not isinstance(raw_definition, dict):
                raise HTTPException(404, 'Dashboard not found.')
            fingerprint = sha256(json.dumps(raw_definition, sort_keys=True, default=str).encode()).hexdigest()
            job = prefetch_jobs.get(f'{workspace}:{dashboard_id}:{fingerprint}')
            if not job or job.get('token') != payload.token:
                job = next((
                    candidate for candidate in prefetch_jobs.values()
                    if candidate.get('workspace') == workspace
                    and candidate.get('dashboard_id') == dashboard_id
                    and candidate.get('token') == payload.token
                ), None)
            if not job or job.get('status') not in {'queued', 'processing'} or job.get('token') != payload.token:
                return Response(status_code=204)
            snapshot = snapshots.get(payload.token)
            if snapshot is None or snapshot.workspace != workspace:
                return Response(status_code=204)
            available = {
                int(chart['index'])
                for slide in snapshot.payload.get('slides', [])
                for chart in slide.get('charts', [])
                if chart.get('available')
            }
            requested = [index for index in payload.indexes if index in available]
            queued = [index for index in job.get('priority_indexes', []) if index in available]
            job['priority_indexes'] = list(dict.fromkeys([*requested, *queued]))
        return Response(status_code=204)

    def enqueue_prefetch(
        dashboard_id: str,
        raw_definition: dict,
        user,
        *,
        workspace: str | None = None,
        expected_generation: int | None = None,
        prepared_preview: dict | None = None,
    ) -> None:
        """Warm Canvas JSON models only; PNG render caches are intentionally excluded."""
        workspace = workspace or workspace_key()
        fingerprint = sha256(json.dumps(raw_definition, sort_keys=True, default=str).encode()).hexdigest()
        key = f'{workspace}:{dashboard_id}:{fingerprint}'
        definition = DashboardDefinition.model_validate(raw_definition)
        # The manifest is itself enough to restore the filtered selection and
        # slide metadata. Do not gate it on a separate all-models check: an
        # interrupted warm-up can have a valid partial cache, which should be
        # served immediately while this worker fills its remaining models.
        restored_preview = prepared_preview or restore_preview_manifest(workspace, dashboard_id, fingerprint)
        with lock:
            generation = prefetch_generation.get(workspace, 0)
            if expected_generation is not None and generation != expected_generation:
                return
            existing = prefetch_jobs.get(key)
            if existing and (
                existing.get('cancel_requested')
                or existing.get('generation') != generation
            ):
                # A cache clear invalidates the active job before deleting its
                # files. Replace that stale job immediately so the new cache
                # generation begins again with data preparation.
                existing['cancel_requested'] = True
                existing = None
            if existing and existing.get('status') in {'queued', 'processing'}:
                existing_snapshot = snapshots.get(str(existing.get('token') or ''))
                restored_snapshot = snapshots.get(str(restored_preview.get('token') or '')) if restored_preview else None
                if (
                    restored_snapshot is None
                    or existing_snapshot is None
                    or existing_snapshot.selection_key == restored_snapshot.selection_key
                ):
                    return
                existing['cancel_requested'] = True
            if existing and existing.get('status') == 'ready' and restored_preview is not None:
                total = sum(
                    1 for slide in restored_preview['slides'] for chart in slide['charts'] if chart['available']
                )
                if len(cached_canvas_model_indexes(restored_preview['token'])) >= total:
                    return
            job = prefetch_jobs[key] = {'id': key, 'workspace': workspace, 'dashboard_id': dashboard_id,
                'name': str(raw_definition.get('name') or dashboard_id), 'status': 'queued', 'completed': 0, 'total': 0,
                'restoring_cached_models': False, 'generation': generation, 'cancel_requested': False, 'priority_indexes': [],
                'task_id': f'dashboard-prefetch:{dashboard_id}' if prepared_preview is None else f'dashboard-prefetch:{dashboard_id}:{fingerprint[:12]}',
                'created_at': monotonic()}
            if restored_preview is not None:
                total = sum(
                    1 for slide in restored_preview['slides'] for chart in slide['charts'] if chart['available']
                )
                completed = len(cached_canvas_model_indexes(restored_preview['token']))
                restored_snapshot = snapshots.get(restored_preview['token'])
                job.update(
                    status='ready' if completed >= total else 'queued', completed=completed, total=total,
                    token=restored_preview['token'], restored_from_manifest=prepared_preview is None,
                    selection_key=restored_snapshot.selection_key if restored_snapshot else '',
                    definition=restored_snapshot.definition.model_dump(mode='json') if restored_snapshot else raw_definition,
                    model_paths=snapshot_canvas_model_paths(restored_snapshot) if restored_snapshot else [],
                )
                if completed >= total:
                    return
        def run():
            preview = restored_preview
            try:
                with lock:
                    if job.get('cancel_requested') or job.get('generation') != prefetch_generation.get(workspace, 0):
                        job['status'] = 'cancelled'
                        return
                    job['status'] = 'processing'
                if preview is None:
                    def preparation_cancelled():
                        with lock:
                            return (
                                bool(job.get('cancel_requested'))
                                or job.get('generation') != prefetch_generation.get(workspace, 0)
                            )

                    preview = build_preview(
                        definition, user, workspace=workspace, cancelled=preparation_cancelled,
                    )
                persist_preview_manifest(workspace, dashboard_id, fingerprint, preview['token'])
                charts = [chart['index'] for slide in preview['slides'] for chart in slide['charts'] if chart['available']]
                with lock:
                    preview_snapshot = snapshots.get(preview['token'])
                    job.update(
                        token=preview['token'], total=len(charts),
                        selection_key=preview_snapshot.selection_key if preview_snapshot else '',
                        definition=preview_snapshot.definition.model_dump(mode='json') if preview_snapshot else raw_definition,
                        model_paths=snapshot_canvas_model_paths(preview_snapshot) if preview_snapshot else [],
                    )
                cached_indexes = cached_canvas_model_indexes(preview['token'])
                pending_indexes = list(dict.fromkeys(charts))
                # Keep Dashboards serial in the outer queue, but render a
                # small batch of independent chart models concurrently.
                # Their snapshot caches use per-frame locks, so companion
                # charts still share their source data safely.
                with ThreadPoolExecutor(
                    max_workers=DASHBOARD_CHART_RENDER_WORKERS,
                    thread_name_prefix='e2e-dashboard-chart',
                ) as chart_executor:
                    while pending_indexes:
                        with lock:
                            if job.get('cancel_requested') or job.get('generation') != prefetch_generation.get(workspace, 0):
                                job['status'] = 'cancelled'
                                return
                            priority_indexes = [
                                index for index in job.get('priority_indexes', []) if index in pending_indexes
                            ]
                            ordered_indexes = [*priority_indexes, *(
                                index for index in pending_indexes if index not in priority_indexes
                            )]
                            batch = ordered_indexes[:DASHBOARD_CHART_RENDER_WORKERS]
                            pending_indexes = [index for index in pending_indexes if index not in batch]
                            job['priority_indexes'] = [
                                candidate for candidate in job.get('priority_indexes', []) if candidate not in batch
                            ]
                        futures = [
                            chart_executor.submit(chart_model, preview['token'], index, user, expected_workspace=workspace)
                            for index in batch if index not in cached_indexes
                        ]
                        for future in as_completed(futures):
                            future.result()
                            with lock:
                                job['completed'] += 1
                with lock:
                    if job.get('cancel_requested') or job.get('generation') != prefetch_generation.get(workspace, 0):
                        job['status'] = 'cancelled'
                        return
                    snapshot = snapshots.get(preview['token'])
                    if snapshot is not None:
                        # Models now live on disk. Discard large frames while
                        # retaining the selection metadata and reusable token.
                        snapshot.frames.clear()
                        snapshot.chart_frames.clear()
                        snapshot.filtered_frames.clear()
                        snapshot.chart_payloads.clear()
                        snapshot.frame_locks.clear()
                        snapshot.projections.clear()
                        snapshots.move_to_end(preview['token'])
                    job.update(status='ready', token=preview['token'])
            except Exception as exc:
                with lock:
                    if job.get('cancel_requested') or job.get('generation') != prefetch_generation.get(workspace, 0):
                        job['status'] = 'cancelled'
                    else:
                        job.update(status='failed', error=str(exc))
        with lock:
            job['runner'] = run
        schedule_next_prefetch()

    @app.get('/api/e2e-dashboards/statuses')
    def dashboard_statuses(user=Depends(dashboard_user)):
        """Return short cache and rendering states for the Dashboard library."""
        workspace = workspace_key()
        dashboards = read_dashboards(bound_repository())
        result = {}
        with lock:
            latest_jobs = {}
            for dashboard_id in dashboards:
                matching_jobs = [
                    job for job in prefetch_jobs.values()
                    if job.get('workspace') == workspace and job.get('dashboard_id') == dashboard_id
                    and not job.get('cancel_requested')
                    and job.get('generation') == prefetch_generation.get(workspace, 0)
                ]
                latest_jobs[dashboard_id] = dict(max(
                    matching_jobs, key=lambda candidate: float(candidate.get('created_at') or 0), default={}
                ))
        for dashboard_id, job in latest_jobs.items():
            if not job or job.get('status') == 'cancelled':
                result[dashboard_id] = {'state': 'not-cached', 'label': 'Not cached'}
                continue
            if job.get('status') == 'failed':
                result[dashboard_id] = {
                    'state': 'error', 'label': 'Error',
                    'detail': str(job.get('error') or 'Dashboard rendering failed.'),
                }
                continue
            if job.get('status') == 'processing':
                result[dashboard_id] = {
                    'state': 'rendering' if job.get('total') else 'loading-data',
                    'label': 'Rendering' if job.get('total') else 'Loading data',
                }
                continue
            if job.get('status') == 'queued':
                result[dashboard_id] = {
                    'state': 'charts-queued' if job.get('token') else 'data-queued',
                    'label': 'Charts queued' if job.get('token') else 'Data queued',
                }
                continue
            try:
                definition = DashboardDefinition.model_validate(job.get('definition') or dashboards[dashboard_id])
                task_repository = Repository(Path(workspace), core.repository.global_db_path)
                dimensions = core.load_repository_calculated_dimensions(task_repository)
                selected_by_kind = selected_sources(definition, task_repository)
                selection_current = persistent_selection_key(
                    definition, task_repository, dimensions, selected_by_kind,
                ) == job.get('selection_key')
            except (HTTPException, KeyError, OSError, sqlite3.Error, TypeError, ValueError):
                selection_current = False
            if not selection_current:
                result[dashboard_id] = {'state': 'data-needed', 'label': 'Data needed'}
                continue
            models_complete = all(Path(path).is_file() for path in job.get('model_paths', []))
            if not models_complete:
                result[dashboard_id] = {'state': 'charts-needed', 'label': 'Charts needed'}
            else:
                result[dashboard_id] = {'state': 'ready', 'label': 'Ready'}
        return JSONResponse(result, headers={'Cache-Control': 'no-store, max-age=0, must-revalidate'})

    def cancel_workspace_prefetch(workspace: str | Path) -> list:
        """Invalidate Dashboard warming and return any still-running futures."""
        database_path = str(Path(workspace).resolve())
        running_futures = []
        with lock:
            prefetch_generation[database_path] = prefetch_generation.get(database_path, 0) + 1
            for task in direct_preparation_tasks.values():
                if task.get('workspace') == database_path:
                    cancellation = task.get('cancellation')
                    if isinstance(cancellation, dict):
                        cancellation['requested'] = True
            for job in prefetch_jobs.values():
                if job.get('workspace') != database_path or job.get('status') not in {'queued', 'processing'}:
                    continue
                job['cancel_requested'] = True
                if job.get('status') == 'queued':
                    # The dispatcher owns one future at a time. Let its
                    # runner observe this cancellation and schedule the next
                    # Dashboard instead of cancelling that shared dispatch.
                    job['status'] = 'cancelled'
                    continue
                future = job.get('future')
                if future is not None:
                    running_futures.append(future)
            stale_tokens = [token for token, snapshot in snapshots.items() if snapshot.workspace == database_path]
            for token in stale_tokens:
                snapshots.pop(token, None)
        return running_futures

    def prefetch_workspace_dashboards(workspaces) -> None:
        """Queue saved Dashboards at application start without requiring the page."""
        system_user = SimpleNamespace(username='*')
        for workspace in workspaces:
            try:
                database_path = str(workspace.database_path.resolve())
                with lock:
                    expected_generation = prefetch_generation.get(database_path, 0)
                task_repository = Repository(workspace.database_path, core.repository.global_db_path)
                # Do not create an empty canonical state during startup: that
                # would mask a legacy state written by an older application.
                stored = task_repository.get_workspace_state(STATE_KEY)
                if stored is None:
                    stored = task_repository.get_workspace_state(LEGACY_STATE_KEY)
                dashboards = json.loads(stored or '{}')
                if not isinstance(dashboards, dict):
                    continue
                for dashboard_id, definition in dashboards.items():
                    enqueue_prefetch(
                        dashboard_id, definition, system_user,
                        workspace=database_path, expected_generation=expected_generation,
                    )
            except (OSError, sqlite3.Error, json.JSONDecodeError):
                continue

    def prefetch_task_payloads(workspace):
        database_path = str(workspace.database_path.resolve())
        with lock:
            direct_tasks = [
                task for task in direct_preparation_tasks.values()
                if task['workspace'] == database_path
                and not bool((task.get('cancellation') or {}).get('requested'))
            ]
            pending = [
                job for job in prefetch_jobs.values()
                if (
                    job['status'] in {'queued', 'processing'}
                    and not job.get('restoring_cached_models')
                    and not job.get('cancel_requested')
                    and job.get('generation') == prefetch_generation.get(job.get('workspace'), 0)
                )
            ]
            workspace_jobs = [job for job in pending if job['workspace'] == database_path]
            tasks = []
            for job in workspace_jobs:
                if job['status'] == 'processing':
                    tasks.append({
                        'id': job['task_id'],
                        'dashboard_name': job['name'],
                        'label': 'Rendering Dashboard Charts' if job['total'] else 'Preparing Dashboard data',
                        'detail': (
                            f'{job["completed"]} of {job["total"]} Canvas models'
                            if job['total'] else 'Preparing filtered Dashboard selection'
                        ),
                        'progress': round(job['completed'] * 100 / job['total']) if job['total'] else None,
                    })
                else:
                    tasks.append({
                        'id': job['task_id'],
                        'dashboard_name': job['name'],
                        'label': 'Queued Dashboard Charts' if job['total'] else 'Queued Dashboard data',
                        'detail': 'Queued',
                        'progress': 0,
                    })
            tasks.extend({
                'id': task['id'],
                'dashboard_name': task['name'],
                'label': 'Rendering Dashboard Charts' if task.get('rendering_only') else 'Preparing Dashboard data',
                'detail': (
                    'Rendering charts with the current Dashboard scope'
                    if task.get('rendering_only')
                    else 'Building filtered Dashboard selection'
                ),
                'progress': None,
            } for task in direct_tasks)
            return tasks
    core.e2e_dashboard_prefetch_tasks = prefetch_task_payloads
    core.e2e_dashboard_prefetch_workspace = prefetch_workspace_dashboards
    core.e2e_dashboard_cancel_prefetch_workspace = cancel_workspace_prefetch

    @app.get('/api/e2e-dashboards/preview/{token}/{index}.png')
    def chart(token: str, index: int, user=Depends(dashboard_user)):
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False)
        entry_key = sha256(repr(entry).encode()).hexdigest()
        key = (snapshot.selection_key, snapshot.definition.scope, entry_key)
        cache_dir = pil_chart_cache_dir(snapshot.workspace)
        cache_path = cache_dir / sha256(
            f'{DASHBOARD_RENDER_CACHE_VERSION}:{snapshot.selection_key}:{snapshot.definition.scope}:{entry_key}'.encode()
        ).hexdigest()
        cache_path = cache_path.with_suffix('.png')
        # PIL chart renderers have no shared global canvas. Let browser image
        # requests for the same slide render concurrently instead of placing
        # every chart behind one process-wide lock; only cache mutation needs
        # synchronization.
        with lock:
            png = images.get(key)
        if png is None and cache_path.is_file():
            try:
                png = cache_path.read_bytes()
                cache_path.touch()
            except OSError:
                png = None
        if png is None:
            _, _, frame = snapshot_chart(token, index, user)
            try:
                rendered = render_catalog_chart_preview(frame, entry, multivendor=snapshot.multivendor, prefiltered=True)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            with lock:
                png = images.setdefault(key, rendered)
                images[key] = png
                while len(images) > 100:
                    images.popitem(last=False)
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(f'.{uuid4().hex}.tmp')
                temporary.write_bytes(png)
                temporary.replace(cache_path)
                cached_files = sorted(cache_dir.glob('*.png'), key=lambda path: path.stat().st_mtime, reverse=True)
                for stale in cached_files[200:]:
                    stale.unlink(missing_ok=True)
            except OSError:
                pass
        return Response(png, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})

    @app.get('/api/e2e-dashboards/data/{token}/{index}')
    def chart_data(token: str, index: int, page: int = 0, download: bool = False, user=Depends(dashboard_user)):
        _, _, frame = snapshot_chart(token, index, user)
        if download:
            return Response(frame.to_csv(index=False), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="dashboard-chart-data.csv"'})
        page = max(page, 0)
        visible = frame.iloc[page*100:(page+1)*100].fillna('').astype(str)
        return {'columns': list(visible.columns), 'rows': visible.values.tolist(), 'total': len(frame), 'page': page}
