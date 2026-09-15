"""Workspace dashboard definitions and shared-table, template-driven previews."""
from __future__ import annotations

import json
import html
import re
import shutil
import sqlite3
import tempfile
import zipfile
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Lock, RLock, Thread
from time import monotonic
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

import pandas as pd
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from pptx import Presentation
from starlette.background import BackgroundTask

from src.modules.cdr_reporting import (
    _catalog_spec, _clear_commentary, _layout_chart_frames, _legend_dimensions, _named_slide_layout,
    _remove_all_slides, _remove_template_chart_placeholders, _render_dashboard_payload,
    _set_commentary, _set_slide_header, _set_structural_slide_text, catalog_chart_payload,
    ensure_report_vendor_group, normalise_report_operator_aliases, parse_catalog_filters,
    parse_catalog_grouping,
    prepare_catalog_chart_preview_frame, render_catalog_chart_preview,
)

from src.modules.repository import Repository

KINDS = ('data', 'voice', 'speech')
STATE_KEY = 'e2e_dashboards_v2'
LEGACY_STATE_KEY = 'e2e_dashboard_sets_v1'
DEFAULT_FILTERS_MIGRATION_KEY = 'e2e_dashboard_default_filters_v6'
DASHBOARD_PPT_JOBS_TABLE = 'dashboard_ppt_jobs'


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
    date_from: date | Literal['Oldest'] | None = 'Oldest'
    date_to: date | Literal['Newest'] | None = 'Newest'


class DashboardPptExportRequest(BaseModel):
    definition: DashboardDefinition | None = None
    preparation_token: str | None = None


class DashboardFilterOptionsRequest(BaseModel):
    definition: DashboardDefinition
    field: str = Field(min_length=1, max_length=255)


class DashboardChartFilterPreviewRequest(BaseModel):
    filters: str = ''
    chart_title: str | None = None
    cdr_source: str | None = None
    dataset_ids: list[int] | str | None = None
    kpi: str | None = None
    chart_type: str | None = None
    grouping_rows: str | None = None
    grouping_columns: str | None = None
    legend: str | None = None
    legend_position: str | None = None


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
    'Region': ('Region', 'G_Level_2', 'G Level 2'),
    'City': ('City', 'G_Level_4', 'G Level 4'), 'Campaign': ('Campaign', 'campaign'),
    'Session Type': ('session_type',),
    'RAT': ('RAT_A', 'RAT', 'Sample_RAT_A'),
    'Call Status': ('Call_Status', 'call_status', 'status'),
}
ADAPTATIVE_FILTER_FIELDS = (
    'Market', 'Operator', 'Vendor', 'Region', 'City', 'Campaign', 'RAT', 'Session Type', 'Call Status',
)
DASHBOARD_RENDER_CACHE_VERSION = 1
DASHBOARD_SELECTION_CACHE_VERSION = 9
DASHBOARD_SELECTION_ROW_LIMIT = 25_000
DASHBOARD_SELECTION_CACHE_LIMIT = 128
DASHBOARD_PROFILE_SELECTION_THRESHOLD = 100_000
DASHBOARD_PROJECTION_CACHE_VERSION = 1
DASHBOARD_PROJECTION_DISK_LIMIT = 6
DASHBOARD_PROJECTION_PAGE_SIZE = 32_768
DASHBOARD_PROJECTION_CACHE_KIB = 256 * 1024
DASHBOARD_PROJECTION_MMAP_SIZE = 4 * 1024 ** 3
DASHBOARD_CHART_MODEL_CACHE_VERSION = 9
DASHBOARD_CHART_MODEL_DISK_LIMIT = 500
DASHBOARD_CHART_RENDER_WORKERS = 3
DASHBOARD_PREVIEW_MANIFEST_VERSION = 7
DASHBOARD_DATE_BOUNDS_CACHE_VERSION = 1


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
    return next((
        column for column in candidates
        if frame[column].fillna('').astype(str).str.strip().ne('').any()
    ), candidates[0] if candidates else None)


def filter_value_series(frame, field):
    """Resolve geographic aliases per row, skipping empty higher-priority values."""
    columns = {identity(column): column for column in frame.columns}
    aliases = next((values for label, values in FILTER_COLUMNS.items() if identity(label) == identity(field)), (field,))
    candidates = [columns[identity(alias)] for alias in aliases if identity(alias) in columns]
    if not candidates:
        return None
    values = frame[candidates[0]].fillna('').astype(str)
    if identity(field) in {identity('City'), identity('Region')}:
        for column in candidates[1:]:
            empty = values.str.strip().eq('')
            if not empty.any():
                break
            values = values.where(~empty, frame[column].fillna('').astype(str))
    return values


def filter_mask(frame, definition, exclude=None):
    """Filter row indices so adaptive facets never copy complete, wide CDR tables."""
    columns = {identity(column): column for column in frame.columns}
    mask = pd.Series(True, index=frame.index)
    for field, values in definition.filters.items():
        if identity(field) == identity(exclude):
            continue
        field_values = filter_value_series(frame, field)
        if field_values is None:
            return pd.Series(False, index=frame.index)
        mask &= field_values.isin(values)
    concrete_from = definition.date_from if isinstance(definition.date_from, date) else None
    concrete_to = definition.date_to if isinstance(definition.date_to, date) else None
    if concrete_from or concrete_to:
        time_column = next((columns[key] for key in ('eventstarttime', 'teststarttime', 'timestamp', 'datetime', 'date') if key in columns), None)
        if time_column is None:
            return pd.Series(False, index=frame.index)
        times = pd.to_datetime(frame[time_column], errors='coerce', utc=True, format='mixed')
        if concrete_from:
            mask &= times >= pd.Timestamp(concrete_from, tz='UTC')
        if concrete_to:
            mask &= times < pd.Timestamp(concrete_to + timedelta(days=1), tz='UTC')
    return mask


def filter_frame(frame, definition, exclude=None):
    """Apply selections, including explicit empty selections and missing fields."""
    if not definition.filters and not isinstance(definition.date_from, date) and not isinstance(definition.date_to, date):
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
    initialized_ppt_job_databases: set[str] = set()
    dashboard_ppt_runs: dict[tuple[str, int], str] = {}
    dashboard_ppt_data_tokens: dict[tuple[str, int, str], str] = {}
    prefetch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='e2e-dashboard-models')
    dashboard_work_gate = Lock()
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

    def dashboard_admin_user(user=Depends(dashboard_user)):
        if user.role not in {'admin', 'super-admin'}:
            raise HTTPException(403, 'Admin access required.')
        return user

    def bound_repository():
        return Repository(Path(workspace_key()), core.repository.global_db_path)

    def ensure_dashboard_ppt_jobs(task_repository):
        database_key = str(Path(task_repository.db_path).resolve())
        with lock:
            first_check = database_key not in initialized_ppt_job_databases
            initialized_ppt_job_databases.add(database_key)
        with task_repository.connection() as connection:
            connection.execute(f'''CREATE TABLE IF NOT EXISTS {DASHBOARD_PPT_JOBS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dashboard_id TEXT NOT NULL,
                dashboard_name TEXT NOT NULL,
                template_name TEXT NOT NULL,
                nr_mode TEXT NOT NULL DEFAULT 'nsa',
                scope TEXT NOT NULL DEFAULT 'single',
                filters_json TEXT NOT NULL DEFAULT '[]',
                output_file TEXT NOT NULL,
                output_path TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                slide_count INTEGER NOT NULL DEFAULT 0,
                chart_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                finished_at TEXT
            )''')
            columns = {str(row['name']) for row in connection.execute(
                f'PRAGMA table_info({DASHBOARD_PPT_JOBS_TABLE})'
            ).fetchall()}
            if 'scope' not in columns:
                connection.execute(
                    f"ALTER TABLE {DASHBOARD_PPT_JOBS_TABLE} ADD COLUMN scope TEXT NOT NULL DEFAULT 'single'"
                )
            if 'nr_mode' not in columns:
                connection.execute(
                    f"ALTER TABLE {DASHBOARD_PPT_JOBS_TABLE} ADD COLUMN nr_mode TEXT NOT NULL DEFAULT 'nsa'"
                )
            if 'filters_json' not in columns:
                connection.execute(
                    f"ALTER TABLE {DASHBOARD_PPT_JOBS_TABLE} ADD COLUMN filters_json TEXT NOT NULL DEFAULT '[]'"
                )
            if first_check:
                connection.execute(
                    f'''UPDATE {DASHBOARD_PPT_JOBS_TABLE}
                        SET status = 'failed', progress = 100,
                            last_error = 'Dashboard export was interrupted by an application restart.',
                            finished_at = ?
                        WHERE status IN ('queued', 'processing')''',
                    (datetime.now(timezone.utc).isoformat(),),
                )

    def dashboard_ppt_job(task_repository, job_id):
        ensure_dashboard_ppt_jobs(task_repository)
        with task_repository.connection() as connection:
            return connection.execute(
                f'SELECT * FROM {DASHBOARD_PPT_JOBS_TABLE} WHERE id = ?', (job_id,),
            ).fetchone()

    def update_dashboard_ppt_job(task_repository, job_id, **changes):
        if not changes:
            return
        assignments = ', '.join(f'{key} = ?' for key in changes)
        with task_repository.connection() as connection:
            connection.execute(
                f'UPDATE {DASHBOARD_PPT_JOBS_TABLE} SET {assignments} WHERE id = ?',
                (*changes.values(), job_id),
            )

    def dashboard_filter_lines(definition: dict, task_repository) -> list[str]:
        lines = []
        for kind in KINDS:
            datasets = core._optional_reporting_datasets(definition.get('datasets', {}).get(kind, []), kind, task_repository)
            names = [str(dataset.get('file_name') or dataset.get('display_name') or dataset.get('id')) for dataset in datasets]
            if names:
                lines.append(f'CDR {kind.title()}: {", ".join(names)}')
        date_from = str(definition.get('date_from') or '').strip()
        date_to = str(definition.get('date_to') or '').strip()
        if date_from and date_to:
            lines.append(f'Date: {date_from} to {date_to}')
        elif date_from:
            lines.append(f'Date from: {date_from}')
        elif date_to:
            lines.append(f'Date to: {date_to}')
        filters = definition.get('filters')
        if not isinstance(filters, dict):
            return lines
        for field, values in filters.items():
            if isinstance(values, (list, tuple, set)):
                selected = [str(value).strip() for value in values if str(value).strip()]
            elif str(values).strip():
                selected = [str(values).strip()]
            else:
                selected = []
            if selected:
                label = re.sub(r'[_-]+', ' ', str(field)).strip().title() or 'Filter'
                lines.append(f'{label}: {", ".join(selected)}')
        return lines

    def serialize_dashboard_ppt_job(row):
        output_path = Path(str(row['output_path'] or ''))
        output_file = str(row['output_file'] or '')
        timestamp_match = re.match(r'^(\d{8}_\d{6})', output_file)
        charts_dir = output_path.parent / 'dashboard-charts'
        ready = str(row['status']) == 'ready' and output_path.is_file()
        charts_ready = ready and (charts_dir / 'manifest.json').is_file()
        job_id = int(row['id'])
        duration = None
        if row['finished_at']:
            try:
                duration = max(0, (
                    datetime.fromisoformat(str(row['finished_at']))
                    - datetime.fromisoformat(str(row['created_at']))
                ).total_seconds())
            except ValueError:
                pass
        try:
            filters = json.loads(str(row['filters_json'] or '[]'))
            filters = [str(item) for item in filters if str(item).strip()] if isinstance(filters, list) else []
        except (TypeError, json.JSONDecodeError):
            filters = []
        return {
            'id': job_id, 'dashboard_id': str(row['dashboard_id']),
            'dashboard_name': str(row['dashboard_name']),
            'timestamp': timestamp_match.group(1) if timestamp_match else '',
            'template': str(row['template_name'] or ''),
            'nr_mode': str(row['nr_mode'] or 'nsa').upper(),
            'scope': 'Multivendor Comparison' if str(row['scope'] or '').casefold() == 'multivendor' else 'Operator Comparison',
            'filters': filters,
            'generated_by': str(row['created_by']),
            'date': core._local_report_date(row['created_at']).replace(' ', '\n', 1),
            'status': str(row['status']), 'progress': int(row['progress'] or 0),
            'duration_seconds': duration,
            'slides': int(row['slide_count'] or 0), 'charts': int(row['chart_count'] or 0),
            'error': str(row['last_error'] or ''),
            'download_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/download' if ready else None,
            'charts_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/charts' if charts_ready else None,
            'charts_api_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/charts.json' if charts_ready else None,
            'charts_download_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/charts.zip' if charts_ready else None,
            'retry_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/retry' if str(row['status']) in {'ready', 'failed', 'stopped'} else None,
            'stop_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/stop' if str(row['status']) in {'queued', 'processing'} else None,
            'delete_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/delete',
        }

    def dashboard_preview_fingerprint(raw_definition, task_repository):
        """Include the current Report Template content in the prepared-preview identity."""
        definition = DashboardDefinition.model_validate(
            runtime_dashboard_definition(raw_definition, task_repository)
        )
        template_content = task_repository.report_template_content(
            definition.template_technology, definition.template,
        )
        material = {
            'definition': definition.model_dump(mode='json'),
            'template_content': sha256(template_content).hexdigest(),
        }
        return sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()

    def dashboard_export_snapshot(dashboard_id, raw_definition, task_repository):
        workspace = str(Path(task_repository.db_path).resolve())
        fingerprint = dashboard_preview_fingerprint(raw_definition, task_repository)
        preview = restore_preview_manifest(workspace, dashboard_id, fingerprint)
        if preview is None:
            with lock:
                job = prefetch_jobs.get(f'{workspace}:{dashboard_id}:{fingerprint}')
                preview = {'token': job.get('token')} if job and job.get('token') else None
        snapshot = snapshots.get(str(preview.get('token') or '')) if preview else None
        if snapshot is None:
            raise ValueError('The Dashboard dataset is not prepared.')
        return validate_dashboard_export_snapshot(snapshot, task_repository)

    def validate_dashboard_export_snapshot(snapshot, task_repository):
        missing = [
            index for index, entry in enumerate(snapshot.entries)
            if entry.source_kind in selected_sources(snapshot.definition, task_repository)
            and not canvas_model_path(snapshot, entry).is_file()
        ]
        if missing:
            raise ValueError('The Dashboard charts are not ready.')
        return snapshot

    def dashboard_chart_render_size(placement) -> tuple[int, int]:
        """Return a placeholder-ratio Canvas size with one unchanged logical axis."""
        _left, _top, width, height = placement
        frame_ratio = float(width) / float(height)
        if frame_ratio >= 1600 / 900:
            return min(4096, max(320, round(900 * frame_ratio))), 900
        return 1600, min(4096, max(240, round(1600 / frame_ratio)))

    def add_dashboard_chart_picture(slide, png: bytes, placement) -> None:
        """Fill a same-ratio chart placeholder without PowerPoint cropping or distortion."""
        left, top, width, height = placement
        slide.shapes.add_picture(BytesIO(png), left, top, width, height)

    def render_dashboard_ppt_job(
        job_id, run_token, task_repository, snapshot, definition, user,
        destination, dashboard_id, preview_fingerprint,
    ):
        run_key = (str(Path(task_repository.db_path).resolve()), job_id)

        def run_is_active():
            with lock:
                if dashboard_ppt_runs.get(run_key) != run_token:
                    return False
            current = dashboard_ppt_job(task_repository, job_id)
            return current is not None and str(current['status']) in {'queued', 'processing'}

        try:
            if not run_is_active():
                return
            if snapshot is None:
                update_dashboard_ppt_job(task_repository, job_id, status='processing', progress=1, last_error='')

                def preparation_progress(percent, _detail):
                    if run_is_active():
                        update_dashboard_ppt_job(
                            task_repository, job_id, progress=max(1, min(4, round(percent * 0.04))),
                        )

                with dashboard_work_gate:
                    preview = build_preview(
                        definition, user, workspace=str(Path(task_repository.db_path).resolve()),
                        cancelled=lambda: not run_is_active(), progress=preparation_progress,
                    )
                token = str(preview['token'])
                with lock:
                    snapshot = snapshots.get(token)
                    dashboard_ppt_data_tokens[(
                        str(Path(task_repository.db_path).resolve()), job_id, user.username,
                    )] = token
                if snapshot is None:
                    raise RuntimeError('The refreshed Dashboard snapshot could not be created.')
                persist_preview_manifest(
                    str(Path(task_repository.db_path).resolve()), dashboard_id,
                    preview_fingerprint, token,
                )
                indexes = list(dict.fromkeys(
                    int(chart['index'])
                    for slide in preview.get('slides', [])
                    for chart in slide.get('charts', [])
                    if chart.get('available')
                ))
                for index in indexes:
                    if not run_is_active():
                        return
                    chart_model(
                        token, index, user,
                        expected_workspace=str(Path(task_repository.db_path).resolve()),
                    )
                snapshot = validate_dashboard_export_snapshot(snapshot, task_repository)
            update_dashboard_ppt_job(task_repository, job_id, status='processing', progress=5, last_error='')
            presentation = Presentation(core.settings.ppt_templates_dir / 'Template_CDR_analysis.pptx')
            _remove_all_slides(presentation)
            grouped = defaultdict(list)
            for index, entry in enumerate(snapshot.entries):
                grouped[entry.slide].append((index, entry))
            charts_dir = destination.parent / 'dashboard-charts'
            charts_dir.mkdir(parents=True, exist_ok=True)
            manifest = []
            focus_rows = {
                entry_index: editor_index
                for editor_index, (entry_index, _entry) in enumerate(
                    sorted(enumerate(snapshot.entries), key=lambda item: (item[1].slide, item[0]))
                )
            }
            chart_total = sum(
                1 for entries in grouped.values() for _index, entry in entries
                if entry.source_kind and snapshot.definition.datasets.get(entry.source_kind)
            )
            rendered = 0
            for slide_number in sorted(grouped):
                if not run_is_active():
                    return
                slide_entries = grouped[slide_number]
                header = slide_entries[0][1]
                comments = snapshot.definition.slide_comments.get(str(slide_number), ())
                if header.structural_type:
                    layout = _named_slide_layout(presentation, header.layout or 'Title Page')
                    if layout is None:
                        raise ValueError(f"Slide {slide_number}: layout '{header.layout}' is unavailable.")
                    slide = presentation.slides.add_slide(layout)
                    _set_structural_slide_text(slide, header.slide_title, header.slide_subtitle)
                    _set_commentary(slide, comments)
                    continue
                chart_entries = [
                    (index, entry) for index, entry in slide_entries
                    if entry.source_kind and snapshot.definition.datasets.get(entry.source_kind)
                ]
                if not chart_entries:
                    continue
                layout = _named_slide_layout(presentation, header.layout)
                placements = _layout_chart_frames(layout)
                if layout is None or len(placements) < len(chart_entries):
                    raise ValueError(f'Slide {slide_number}: the PowerPoint layout has insufficient chart placeholders.')
                slide = presentation.slides.add_slide(layout)
                _set_slide_header(slide, header.slide_title, header.slide_subtitle)
                _clear_commentary(slide)
                _set_commentary(slide, comments)
                _remove_template_chart_placeholders(slide)
                for chart_number, ((index, entry), placement) in enumerate(zip(chart_entries, placements, strict=False), 1):
                    if not run_is_active():
                        return
                    model_path = canvas_model_path(snapshot, entry)
                    payload = json.loads(model_path.read_text(encoding='utf-8'))
                    render_width, render_height = dashboard_chart_render_size(placement)
                    png, hover_targets = _render_dashboard_payload(
                        payload, width=render_width, height=render_height,
                    )
                    if not run_is_active():
                        return
                    file_name = f'slide-{slide_number:03d}-chart-{chart_number:02d}.png'
                    hover_file = f'slide-{slide_number:03d}-chart-{chart_number:02d}.hover.json'
                    model_file = f'slide-{slide_number:03d}-chart-{chart_number:02d}.model.json'
                    (charts_dir / file_name).write_bytes(png)
                    (charts_dir / hover_file).write_text(
                        json.dumps(hover_targets, ensure_ascii=False), encoding='utf-8',
                    )
                    (charts_dir / model_file).write_text(
                        json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8',
                    )
                    add_dashboard_chart_picture(slide, png, placement)
                    manifest.append({
                        'slide': slide_number, 'title': entry.chart_title or header.slide_title,
                        'source': entry.cdr_source, 'chart_type': entry.chart_type,
                        'entry_index': index, 'focus_row': focus_rows[index],
                        'file': file_name, 'hover_file': hover_file, 'model_file': model_file,
                    })
                    rendered += 1
                    update_dashboard_ppt_job(
                        task_repository, job_id,
                        progress=5 + round(rendered * 85 / max(chart_total, 1)), chart_count=rendered,
                    )
            if not run_is_active():
                return
            (charts_dir / 'manifest.json').write_text(
                json.dumps({
                    'generate_tooltips': True,
                    'dashboard_id': dashboard_id,
                    'preview_fingerprint': preview_fingerprint,
                    'definition': snapshot.definition.model_dump(mode='json'),
                    'charts': manifest,
                }, ensure_ascii=False),
                encoding='utf-8',
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            presentation.save(destination)
            if not run_is_active():
                shutil.rmtree(destination.parent, ignore_errors=True)
                return
            update_dashboard_ppt_job(
                task_repository, job_id, status='ready', progress=100,
                slide_count=len(presentation.slides), chart_count=rendered,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            if run_is_active():
                update_dashboard_ppt_job(
                    task_repository, job_id, status='failed', progress=100, last_error=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )

    def read_dashboards(task_repository):
        stored = task_repository.get_workspace_state(STATE_KEY)
        if stored is None:
            stored = task_repository.get_workspace_state(LEGACY_STATE_KEY)
        if stored is None:
            return {}
        dashboards = json.loads(stored or '{}')
        if not isinstance(dashboards, dict):
            return dashboards
        reset_defaults = task_repository.get_workspace_state(DEFAULT_FILTERS_MIGRATION_KEY) != '1'
        migrated = {
            dashboard_id: normalize_dashboard_filters(definition, reset_defaults=reset_defaults)
            for dashboard_id, definition in dashboards.items()
        }
        if migrated != dashboards or reset_defaults or task_repository.get_workspace_state(STATE_KEY) is None:
            task_repository.set_workspace_state(STATE_KEY, json.dumps(migrated))
        if reset_defaults:
            task_repository.set_workspace_state(DEFAULT_FILTERS_MIGRATION_KEY, '1')
        return migrated

    def normalize_dashboard_filters(definition, *, reset_defaults=False):
        """Migrate retired filters and apply the current defaults once per workspace."""
        if not isinstance(definition, dict):
            return definition
        normalized = dict(definition)
        # Scope, source CDRs and dates define the temporary dataset universe.
        # They are rebuilt when a Dashboard opens and are never saved as
        # persistent Dashboard filters.
        for field in ('scope', 'datasets', 'date_from', 'date_to'):
            normalized.pop(field, None)
        filters = normalized.get('filters')
        retired_filter_keys = {identity('Technology'), identity('Zone')}
        migrated_filters = {}
        region_values = []
        for field, values in (filters.items() if isinstance(filters, dict) else []):
            field_key = identity(field)
            if field_key == identity('Zone'):
                region_values.extend(values or [])
            elif field_key == identity('Region'):
                region_values = list(values or []) + region_values
            elif field_key not in retired_filter_keys:
                migrated_filters[field] = values
        if region_values:
            migrated_filters['Region'] = list(dict.fromkeys(region_values))
        normalized['filters'] = migrated_filters
        custom_fields = normalized.get('custom_fields')
        normalized['custom_fields'] = [
            field for field in custom_fields or []
            if identity(field) not in retired_filter_keys and identity(field) != identity('Region')
        ]
        default_keys = {identity(field) for field in ADAPTATIVE_FILTER_FIELDS}
        hidden_filters = normalized.get('hidden_filters')
        normalized['hidden_filters'] = [
            field for field in hidden_filters or []
            if identity(field) not in retired_filter_keys
            and (not reset_defaults or identity(field) not in default_keys)
        ]
        return normalized

    def runtime_dashboard_definition(definition, task_repository):
        """Add a fresh default universe to a persisted Dashboard definition."""
        effective = dict(definition)
        effective.setdefault('scope', 'single')
        if 'datasets' not in effective:
            selected = {kind: [] for kind in KINDS}
            ready = [
                core.serialize_dataset_row(row) for row in task_repository.list_datasets()
                if row['status'] == 'ready' and row['dataset_kind'] in KINDS
            ]

            def recency(row):
                for field in ('uploaded_at', 'updated_at', 'processed_at', 'created_at'):
                    try:
                        return datetime.fromisoformat(str(row.get(field) or '').replace('Z', '+00:00')).timestamp()
                    except ValueError:
                        continue
                return float(row.get('id') or 0)

            count = 1 if effective['scope'] == 'multivendor' else 2
            for kind in KINDS:
                selected[kind] = [
                    int(row['id']) for row in sorted(
                        (row for row in ready if row.get('dataset_kind') == kind),
                        key=lambda row: (recency(row), int(row.get('id') or 0)), reverse=True,
                    )[:count]
                ]
            effective['datasets'] = selected
        else:
            effective['datasets'] = {
                kind: list((effective.get('datasets') or {}).get(kind, [])) for kind in KINDS
            }
        effective.setdefault('date_from', 'Oldest')
        effective.setdefault('date_to', 'Newest')
        return effective

    def automatic_scope_universe(definition: DashboardDefinition, task_repository) -> DashboardDefinition:
        """Build the temporary latest-CDR universe used by library PPT exports."""
        raw_definition = definition.model_dump(mode='json')
        # Pydantic supplies empty defaults for these fields.  Remove them so
        # runtime_dashboard_definition selects the latest CDRs for the Scope.
        for field in ('datasets', 'date_from', 'date_to'):
            raw_definition.pop(field, None)
        return DashboardDefinition.model_validate(runtime_dashboard_definition(raw_definition, task_repository))

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
        if isinstance(definition.date_from, date) and isinstance(definition.date_to, date) and definition.date_from > definition.date_to:
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
            'dashboard_filter_aliases': {
                field: list(aliases) for field, aliases in FILTER_COLUMNS.items() if len(aliases) > 1
            },
        })

    @app.get('/api/e2e-dashboards')
    def list_dashboards(user=Depends(dashboard_user)):
        with lock:
            dashboards = read_dashboards(bound_repository())
        # Listing the library is on the page's critical path. Restoring a
        # persistent manifest for every Dashboard can involve validating many
        # CDR revisions, so enqueue those warm-ups after returning the list.
        # The opened Dashboard prepares or restores independently and is never
        # held behind this maintenance work.
        definitions = [(dashboard_id, dict(definition)) for dashboard_id, definition in dashboards.items()]

        def enqueue_library_prefetches():
            for dashboard_id, definition in definitions:
                enqueue_prefetch(dashboard_id, definition, user)

        Thread(target=enqueue_library_prefetches, daemon=True, name='e2e-dashboard-library-prefetch').start()
        return JSONResponse(
                dashboards,
            headers={'Cache-Control': 'no-store, max-age=0, must-revalidate'},
        )

    @app.get('/api/e2e-dashboards/{dashboard_id}/export')
    def export_dashboard_definition(dashboard_id: str, user=Depends(dashboard_user)):
        """Create the same Dashboard archive accepted by Admin Import."""
        task_repository = bound_repository()
        with lock:
            definition = read_dashboards(task_repository).get(dashboard_id)
        if not isinstance(definition, dict):
            raise HTTPException(404, 'Dashboard not found.')
        workspace = core.active_workspace
        workspace_name = str(workspace.name if workspace else 'Workspace')
        archive_path = f'workspaces/{workspace_name}/dashboards/dashboards.json'
        payload = json.dumps({
            'format': 'dashboard-analytic-dashboards', 'version': 1,
            'dashboards': {dashboard_id: definition},
        }, ensure_ascii=False, indent=2).encode('utf-8')
        temporary = tempfile.NamedTemporaryFile(prefix='dashboard-export-', suffix='.zip', delete=False)
        temporary.close()
        archive = Path(temporary.name)
        try:
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
                bundle.writestr('manifest.json', json.dumps({
                    'format': 'dashboard-analytic-export', 'version': 1, 'kind': 'dashboards',
                    'components': ['workspace_components'], 'workspace_components': ['dashboards'],
                    'source_workspace': {'id': workspace.id, 'name': workspace_name} if workspace else {},
                    'archive_path': archive_path,
                }, indent=2, sort_keys=True))
                bundle.writestr(archive_path, payload)
        except Exception:
            archive.unlink(missing_ok=True)
            raise
        safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', str(definition.get('name') or dashboard_id)).strip('._') or 'Dashboard'
        return FileResponse(
            archive, filename=f'{safe_name}_dashboard.zip', media_type='application/zip',
            background=BackgroundTask(archive.unlink, missing_ok=True),
        )

    def queue_dashboard_ppt_export(
        dashboard_id, user, *, reuse_job_id=None, export_definition: DashboardDefinition | None = None,
        preparation_token: str | None = None,
    ):
        task_repository = bound_repository()
        workspace = workspace_key()
        with lock:
            preparing = any(
                task.get('workspace') == workspace and task.get('dashboard_id') == dashboard_id
                for task in direct_preparation_tasks.values()
            )
        if preparing:
            raise HTTPException(409, 'The Dashboard dataset is still being prepared.')
        with lock:
            stored_definition = read_dashboards(task_repository).get(dashboard_id)
        if not isinstance(stored_definition, dict):
            raise HTTPException(404, 'Dashboard not found.')
        raw_definition = export_definition.model_dump(mode='json') if export_definition is not None else stored_definition
        if not any((raw_definition.get('datasets') or {}).values()):
            raw_definition.pop('datasets', None)
            raw_definition = runtime_dashboard_definition(raw_definition, task_repository)
        snapshot_definition = DashboardDefinition.model_validate(raw_definition)
        try:
            if preparation_token:
                with lock:
                    snapshot = snapshots.get(preparation_token)
                if (
                    snapshot is None
                    or snapshot.workspace != workspace
                    or snapshot.owner not in {user.username, '*'}
                ):
                    raise ValueError('The prepared Dashboard has expired. Refresh it before generating the PPT.')
                if export_definition is not None and snapshot.definition.scope != export_definition.scope:
                    raise ValueError('The prepared Dashboard Scope no longer matches the selected Scope.')
                snapshot = validate_dashboard_export_snapshot(snapshot, task_repository)
                raw_definition = snapshot.definition.model_dump(mode='json')
            else:
                snapshot = dashboard_export_snapshot(dashboard_id, raw_definition, task_repository)
        except ValueError as exc:
            if reuse_job_id is None:
                raise HTTPException(409, str(exc)) from exc
            # A deliberate relaunch may follow a Report Template edit. Build
            # its new snapshot and Canvas models inside the replacement Job.
            snapshot = None
        dashboard_name = str(raw_definition.get('name') or dashboard_id)
        preview_fingerprint = dashboard_preview_fingerprint(raw_definition, task_repository)
        filters_json = json.dumps(dashboard_filter_lines(raw_definition, task_repository), ensure_ascii=False)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', dashboard_name).strip() or 'Dashboard'
        output_file = f'{timestamp}  - {safe_name}.pptx'
        job_dir = Path(task_repository.db_path).parent / 'output' / 'dashboards' / Path(output_file).stem
        destination = job_dir / output_file
        ensure_dashboard_ppt_jobs(task_repository)
        if reuse_job_id is None:
            with task_repository.connection() as connection:
                cursor = connection.execute(
                    f'''INSERT INTO {DASHBOARD_PPT_JOBS_TABLE} (
                        dashboard_id, dashboard_name, template_name, nr_mode, scope, filters_json, output_file, output_path,
                        created_by, created_at, status, progress
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0)''',
                    (
                        dashboard_id, dashboard_name, str(raw_definition.get('template') or ''),
                        str(raw_definition.get('technology') or raw_definition.get('template_technology') or 'nsa'),
                        str(raw_definition.get('scope') or 'single'), filters_json,
                        output_file, str(destination), user.username,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                job_id = int(cursor.lastrowid)
        else:
            job_id = int(reuse_job_id)
            shutil.rmtree(Path(str(dashboard_ppt_job(task_repository, job_id)['output_path'])).parent, ignore_errors=True)
            update_dashboard_ppt_job(
                task_repository, job_id, dashboard_name=dashboard_name,
                template_name=str(raw_definition.get('template') or ''),
                nr_mode=str(raw_definition.get('technology') or raw_definition.get('template_technology') or 'nsa'),
                scope=str(raw_definition.get('scope') or 'single'), filters_json=filters_json,
                output_file=output_file, output_path=str(destination), created_at=datetime.now(timezone.utc).isoformat(),
                status='queued', progress=0, slide_count=0, chart_count=0,
                last_error='', finished_at=None,
            )
        run_token = uuid4().hex
        with lock:
            dashboard_ppt_runs[(str(Path(task_repository.db_path).resolve()), job_id)] = run_token
            snapshot_token = next((token for token, value in snapshots.items() if value is snapshot), '')
            if snapshot_token:
                dashboard_ppt_data_tokens[(str(Path(task_repository.db_path).resolve()), job_id, user.username)] = snapshot_token
        Thread(
            target=render_dashboard_ppt_job,
            args=(
                job_id, run_token, task_repository, snapshot, snapshot_definition, user, destination,
                dashboard_id, preview_fingerprint,
            ),
            name=f'dashboard-ppt-{job_id}', daemon=True,
        ).start()
        task_repository.add_log(user.username, 'export_dashboard_ppt', json.dumps({
            'dashboard_id': dashboard_id, 'job_id': job_id, 'output': str(destination),
        }))
        return job_id

    @app.post('/api/e2e-dashboards/{dashboard_id}/export-ppt')
    def export_dashboard_ppt(
        dashboard_id: str, request: DashboardPptExportRequest | None = None,
        user=Depends(dashboard_user),
    ):
        job_id = queue_dashboard_ppt_export(
            dashboard_id, user,
            export_definition=request.definition if request else None,
            preparation_token=request.preparation_token if request else None,
        )
        return JSONResponse({'job_id': job_id, 'status': 'queued'}, status_code=202)

    @app.get('/api/e2e-dashboards/ppt-jobs')
    def dashboard_ppt_jobs(user=Depends(dashboard_user)):
        task_repository = bound_repository()
        ensure_dashboard_ppt_jobs(task_repository)
        with task_repository.connection() as connection:
            rows = connection.execute(
                f'SELECT * FROM {DASHBOARD_PPT_JOBS_TABLE} ORDER BY id DESC LIMIT 100'
            ).fetchall()
        return {'jobs': [serialize_dashboard_ppt_job(row) for row in rows]}

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/download')
    def download_dashboard_ppt(job_id: int, user=Depends(dashboard_user)):
        row = dashboard_ppt_job(bound_repository(), job_id)
        path = Path(str(row['output_path'])) if row else None
        if row is None or str(row['status']) != 'ready' or not path.is_file():
            raise HTTPException(404, 'Dashboard PowerPoint is not available.')
        return FileResponse(
            path, filename=path.name,
            media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',
        )

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/charts')
    def open_dashboard_ppt_charts(job_id: int, user=Depends(dashboard_user)):
        row = dashboard_ppt_job(bound_repository(), job_id)
        if row is None:
            raise HTTPException(404, 'Dashboard charts are not available.')
        charts_dir = Path(str(row['output_path'])).parent / 'dashboard-charts'
        try:
            manifest = json.loads((charts_dir / 'manifest.json').read_text(encoding='utf-8'))
        except (AttributeError, OSError, json.JSONDecodeError):
            raise HTTPException(404, 'Dashboard charts are not available.')
        cards = ''.join(
            f'<article><h2>{html.escape(str(item.get("title") or "Chart"))}</h2>'
            f'<img src="/api/e2e-dashboards/ppt-jobs/{job_id}/charts/{html.escape(str(item.get("file") or ""))}" alt=""></article>'
            for item in manifest.get('charts', []) if isinstance(item, dict)
        )
        return HTMLResponse(
            '<!doctype html><html><head><title>Dashboard charts</title><style>'
            'body{font-family:Arial;margin:24px;background:#f5f2f8}article{margin:0 0 24px;padding:16px;background:white;border-radius:12px}'
            'img{display:block;width:100%;height:auto}h2{font-size:18px}</style></head><body>' + cards + '</body></html>'
        )

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/charts.json')
    def dashboard_ppt_charts_manifest(job_id: int, user=Depends(dashboard_user)):
        row = dashboard_ppt_job(bound_repository(), job_id)
        if row is None:
            raise HTTPException(404, 'Dashboard charts are not available.')
        charts_dir = Path(str(row['output_path'])).parent / 'dashboard-charts'
        try:
            manifest = json.loads((charts_dir / 'manifest.json').read_text(encoding='utf-8'))
        except (AttributeError, OSError, json.JSONDecodeError):
            raise HTTPException(404, 'Dashboard charts are not available.')
        charts = []
        definition_available = isinstance(manifest.get('definition'), dict)
        fallback_focus_rows = []
        if any(not isinstance(item.get('focus_row'), int) for item in manifest.get('charts', []) if isinstance(item, dict)):
            try:
                nr_mode = str(row['nr_mode'] or 'nsa').casefold()
                definition = DashboardDefinition(
                    name=str(row['dashboard_name']), template=str(row['template_name']),
                    template_technology=nr_mode, technology=nr_mode,
                    scope='multivendor' if str(row['scope']).casefold() == 'multivendor' else 'single',
                )
                entries = validate(definition, bound_repository())
                focus_by_index = {
                    entry_index: editor_index
                    for editor_index, (entry_index, _entry) in enumerate(
                        sorted(enumerate(entries), key=lambda value: (value[1].slide, value[0]))
                    )
                }
                unused = set(range(len(entries)))
                for item in manifest.get('charts', []):
                    matched = next((
                        entry_index for entry_index, entry in enumerate(entries)
                        if entry_index in unused
                        and entry.slide == int(item.get('slide') or 0)
                        and str(entry.chart_title or entry.slide_title) == str(item.get('title') or '')
                        and str(entry.cdr_source) == str(item.get('source') or '')
                        and str(entry.chart_type) == str(item.get('chart_type') or '')
                    ), None)
                    fallback_focus_rows.append(focus_by_index.get(matched) if matched is not None else None)
                    if matched is not None:
                        unused.discard(matched)
            except (TypeError, ValueError):
                fallback_focus_rows = []
        for chart_index, item in enumerate(manifest.get('charts', [])):
            if not isinstance(item, dict):
                continue
            chart_file = str(item.get('file') or '')
            if not re.fullmatch(r'slide-\d+-chart-\d+\.png', chart_file):
                continue
            model_file = str(item.get('model_file') or '')
            model_available = bool(
                re.fullmatch(r'slide-\d+-chart-\d+\.model\.json', model_file)
                and (charts_dir / model_file).is_file()
            )
            charts.append({
                'index': len(charts),
                'slide': int(item.get('slide') or 0),
                'title': str(item.get('title') or 'Chart'),
                'source': str(item.get('source') or ''),
                'chart_type': str(item.get('chart_type') or ''),
                'focus_row': int(item['focus_row']) if isinstance(item.get('focus_row'), int) else (
                    fallback_focus_rows[chart_index] if chart_index < len(fallback_focus_rows) else None
                ),
                'image_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/charts/{chart_file}',
                'payload_url': f'/api/e2e-dashboards/ppt-jobs/{job_id}/chart-models/{model_file}' if model_available else None,
                'data_url': f'/ppt-jobs/{job_id}/data/{chart_index}' if definition_available and isinstance(item.get('entry_index'), int) else None,
            })
        return {
            'job': serialize_dashboard_ppt_job(row),
            'generate_tooltips': bool(manifest.get('generate_tooltips')),
            'charts': charts,
        }

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/charts/{chart_index}/filter-context')
    def dashboard_ppt_chart_filter_context(
        job_id: int, chart_index: int, prepare: bool = False, user=Depends(dashboard_user),
    ):
        """Load PPT chart metadata immediately and restore its data only on demand."""
        task_repository = bound_repository()
        row = dashboard_ppt_job(task_repository, job_id)
        charts_dir = Path(str(row['output_path'])).parent / 'dashboard-charts' if row else None
        try:
            manifest = json.loads((charts_dir / 'manifest.json').read_text(encoding='utf-8'))
            definition = DashboardDefinition.model_validate(manifest['definition'])
            entry_index = int(manifest['charts'][chart_index]['entry_index'])
            entry = validate(definition, task_repository)[entry_index]
        except (AttributeError, IndexError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(404, 'Chart filters are not available for this PowerPoint Job.')
        workspace = str(Path(task_repository.db_path).resolve())
        token = ''
        if prepare:
            preview = restore_preview_manifest(
                workspace, str(manifest.get('dashboard_id') or row['dashboard_id']),
                str(manifest.get('preview_fingerprint') or ''),
            ) or build_preview(definition, user, workspace=workspace)
            token = str(preview['token'])
        hidden = {identity('dataset_id'), identity('source_row_id')}
        datasets_by_source = {f'cdr-{kind}': [] for kind in KINDS}
        columns_by_source = {f'cdr-{kind}': [] for kind in KINDS}
        for dataset in task_repository.list_datasets():
            kind = str(dataset['dataset_kind'] or '').casefold()
            if kind in KINDS and dataset['status'] == 'ready':
                datasets_by_source[f'cdr-{kind}'].append({'value': str(dataset['id']), 'label': str(dataset['file_name'])})
                columns_by_source[f'cdr-{kind}'].extend(
                    str(column) for column in task_repository.list_dataset_row_columns(int(dataset['id']))
                )
        for source, source_columns in columns_by_source.items():
            columns_by_source[source] = sorted({
                column for column in source_columns if identity(column) not in hidden
            }, key=str.casefold)
        columns = columns_by_source.get(f'cdr-{entry.source_kind}', [])
        template_available = user.role in {'admin', 'super-admin'} and any(
            str(item['name']) == definition.template
            for item in task_repository.list_report_templates(definition.template_technology)
        )
        return JSONResponse({
            'token': token, 'chart_index': entry_index, 'cdr_source': entry.cdr_source,
            'chart_type': entry.chart_type, 'chart_title': entry.chart_title, 'kpi': entry.kpi,
            'dataset_ids': [str(value) for value in definition.datasets.get(entry.source_kind, [])],
            'filters': entry.filters, 'grouping_rows': entry.grouping_rows,
            'grouping_columns': entry.grouping_columns, 'legend': entry.legend,
            'legend_position': entry.legend_position, 'template_available': template_available, 'datasets_by_source': datasets_by_source,
            'columns_by_source': columns_by_source, 'columns': columns,
        })

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/chart-models/{model_file}')
    def dashboard_ppt_chart_model(job_id: int, model_file: str, user=Depends(dashboard_user)):
        if not re.fullmatch(r'slide-\d+-chart-\d+\.model\.json', model_file):
            raise HTTPException(404, 'Chart model not found.')
        row = dashboard_ppt_job(bound_repository(), job_id)
        path = Path(str(row['output_path'])).parent / 'dashboard-charts' / model_file if row else None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (AttributeError, OSError, json.JSONDecodeError):
            raise HTTPException(404, 'Chart model not found.')
        return JSONResponse(payload)

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/data/{chart_index}')
    def dashboard_ppt_chart_data(
        job_id: int, chart_index: int, page: int = 0, download: bool = False,
        column_filters: str = '', include_filter_values: bool = False,
        user=Depends(dashboard_user),
    ):
        task_repository = bound_repository()
        row = dashboard_ppt_job(task_repository, job_id)
        charts_dir = Path(str(row['output_path'])).parent / 'dashboard-charts' if row else None
        try:
            manifest = json.loads((charts_dir / 'manifest.json').read_text(encoding='utf-8'))
            chart = manifest['charts'][chart_index]
            definition = DashboardDefinition.model_validate(manifest['definition'])
            entry_index = int(chart['entry_index'])
        except (AttributeError, IndexError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(404, 'The filtered dataset is not available for this PowerPoint Job.')
        workspace = str(Path(task_repository.db_path).resolve())
        token_key = (workspace, job_id, user.username)
        with lock:
            token = dashboard_ppt_data_tokens.get(token_key)
            cached_snapshot = snapshots.get(token) if token else None
        if cached_snapshot is None:
            preview = restore_preview_manifest(
                workspace,
                str(manifest.get('dashboard_id') or row['dashboard_id']),
                str(manifest.get('preview_fingerprint') or ''),
            )
            if preview is None:
                preview = build_preview(definition, user, workspace=workspace)
            token = str(preview['token'])
            with lock:
                dashboard_ppt_data_tokens[token_key] = token
        snapshot, entry, _ = snapshot_chart(
            token, entry_index, user, include_frame=False, expected_workspace=workspace,
        )
        selected_column_filters = parse_chart_column_filters(column_filters)
        if not download:
            projected_page = projection_chart_data_page(
                snapshot, entry, page, selected_column_filters, include_filter_values,
            )
            if projected_page is not None:
                visible, total, chart_total, filter_values = projected_page
                return {
                    'columns': list(visible.columns),
                    'rows': visible.fillna('').astype(str).values.tolist(),
                    'total': total, 'chart_total': chart_total,
                    'filter_values': filter_values, 'page': max(page, 0),
                }
        _, _, frame = snapshot_chart(token, entry_index, user, expected_workspace=workspace)
        frame = unique_chart_dataset_rows(snapshot, entry, frame)
        chart_total = len(frame)
        filter_values = chart_dataset_filter_values(frame) if include_filter_values else {}
        frame = apply_chart_column_filters(frame, selected_column_filters)
        if download:
            return Response(
                frame.to_csv(index=False), media_type='text/csv',
                headers={'Content-Disposition': 'attachment; filename="dashboard-chart-data.csv"'},
            )
        page = max(page, 0)
        visible = frame.iloc[page * 100:(page + 1) * 100].fillna('').astype(str)
        return {
            'columns': list(visible.columns), 'rows': visible.values.tolist(),
            'total': len(frame), 'chart_total': chart_total,
            'filter_values': filter_values, 'page': page,
        }

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/charts/{chart_file}')
    def dashboard_ppt_chart(job_id: int, chart_file: str, user=Depends(dashboard_user)):
        if not re.fullmatch(r'slide-\d+-chart-\d+\.png', chart_file):
            raise HTTPException(404, 'Chart not found.')
        row = dashboard_ppt_job(bound_repository(), job_id)
        path = Path(str(row['output_path'])).parent / 'dashboard-charts' / chart_file if row else None
        if path is None or not path.is_file():
            raise HTTPException(404, 'Chart not found.')
        return FileResponse(path, media_type='image/png')

    @app.get('/api/e2e-dashboards/ppt-jobs/{job_id}/charts.zip')
    def download_dashboard_ppt_charts(job_id: int, user=Depends(dashboard_user)):
        row = dashboard_ppt_job(bound_repository(), job_id)
        charts_dir = Path(str(row['output_path'])).parent / 'dashboard-charts' if row else None
        if charts_dir is None or not (charts_dir / 'manifest.json').is_file():
            raise HTTPException(404, 'Dashboard charts are not available.')
        temporary = tempfile.NamedTemporaryFile(prefix='dashboard-ppt-charts-', suffix='.zip', delete=False)
        temporary.close()
        archive = Path(temporary.name)
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in charts_dir.glob('*.png'):
                bundle.write(path, path.name)
        return FileResponse(
            archive, filename=f'{Path(str(row["output_file"])).stem}_charts.zip',
            media_type='application/zip', background=BackgroundTask(archive.unlink, missing_ok=True),
        )

    @app.post('/api/e2e-dashboards/ppt-jobs/{job_id}/stop')
    def stop_dashboard_ppt(job_id: int, user=Depends(dashboard_user)):
        task_repository = bound_repository()
        row = dashboard_ppt_job(task_repository, job_id)
        if row is None or str(row['status']) not in {'queued', 'processing'}:
            raise HTTPException(409, 'Only queued or processing Dashboard exports can be stopped.')
        update_dashboard_ppt_job(
            task_repository, job_id, status='stopped',
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return {'stopped': job_id}

    @app.post('/api/e2e-dashboards/ppt-jobs/{job_id}/retry')
    def retry_dashboard_ppt(job_id: int, user=Depends(dashboard_user)):
        task_repository = bound_repository()
        row = dashboard_ppt_job(task_repository, job_id)
        if row is None or str(row['status']) not in {'ready', 'failed', 'stopped'}:
            raise HTTPException(409, 'This Dashboard export cannot be relaunched.')
        queue_dashboard_ppt_export(str(row['dashboard_id']), user, reuse_job_id=job_id)
        return JSONResponse({'job_id': job_id, 'status': 'queued'}, status_code=202)

    @app.post('/api/e2e-dashboards/ppt-jobs/delete-all')
    def delete_all_dashboard_ppts(user=Depends(dashboard_admin_user)):
        task_repository = bound_repository()
        ensure_dashboard_ppt_jobs(task_repository)
        with task_repository.connection() as connection:
            rows = connection.execute(
                f'SELECT id, output_path FROM {DASHBOARD_PPT_JOBS_TABLE}'
            ).fetchall()
            connection.execute(f'DELETE FROM {DASHBOARD_PPT_JOBS_TABLE}')
        database_key = str(Path(task_repository.db_path).resolve())
        with lock:
            for row in rows:
                dashboard_ppt_runs.pop((database_key, int(row['id'])), None)
        for row in rows:
            shutil.rmtree(Path(str(row['output_path'])).parent, ignore_errors=True)
        task_repository.add_log(user.username, 'delete_all_dashboard_ppts', json.dumps({'count': len(rows)}))
        return {'deleted': len(rows)}

    @app.post('/api/e2e-dashboards/ppt-jobs/{job_id}/delete')
    def delete_dashboard_ppt(job_id: int, user=Depends(dashboard_admin_user)):
        task_repository = bound_repository()
        row = dashboard_ppt_job(task_repository, job_id)
        if row is None:
            raise HTTPException(404, 'Dashboard export job not found.')
        if str(row['status']) in {'queued', 'processing'}:
            raise HTTPException(409, 'A running Dashboard export cannot be deleted.')
        shutil.rmtree(Path(str(row['output_path'])).parent, ignore_errors=True)
        with task_repository.connection() as connection:
            connection.execute(f'DELETE FROM {DASHBOARD_PPT_JOBS_TABLE} WHERE id = ?', (job_id,))
        return {'deleted': job_id}

    @app.put('/api/e2e-dashboards/{dashboard_id}')
    def save_dashboard(dashboard_id: str, definition: DashboardDefinition, user=Depends(dashboard_user)):
        with lock:
            task_repository = bound_repository()
            validate(definition, task_repository)
            dashboards = read_dashboards(task_repository)
            if any(key != dashboard_id and item['name'].strip().casefold() == definition.name.strip().casefold() for key, item in dashboards.items()):
                raise HTTPException(409, 'A Dashboard with this name already exists.')
            definition.name = definition.name.strip()
            saved_definition = normalize_dashboard_filters(definition.model_dump(mode='json'))
            dashboards[dashboard_id] = saved_definition
            task_repository.set_workspace_state(STATE_KEY, json.dumps(dashboards))
            task_repository.add_log(user.username, 'save_dashboard', json.dumps({'id': dashboard_id, 'name': definition.name}))
        enqueue_prefetch(dashboard_id, definition.model_dump(mode='json'), user)
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

    def filter_sql_value_expression(task_repository, columns, field):
        """Return a text value expression with row-level fallback aliases."""
        lookup = {identity(column): column for column in columns}
        aliases = next((values for label, values in FILTER_COLUMNS.items() if identity(label) == identity(field)), (field,))
        resolved = list(dict.fromkeys(
            lookup[identity(alias)] for alias in aliases if identity(alias) in lookup
        ))
        if not resolved:
            return None
        quote = task_repository._quote_identifier
        if identity(field) in {identity('City'), identity('Region')}:
            candidates = ', '.join(
                f"NULLIF(TRIM(CAST({quote(column)} AS TEXT)), '')" for column in resolved
            )
            return f"COALESCE({candidates}, '')"
        return f"COALESCE(CAST({quote(resolved[0])} AS TEXT), '')"

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
            value_expression = filter_sql_value_expression(task_repository, columns, field_name)
            if value_expression is None or not values:
                clauses.append('0')
                continue
            value_placeholders = ', '.join('?' for _ in values)
            clauses.append(f"{value_expression} IN ({value_placeholders})")
            params.extend(str(value) for value in values)
        concrete_from = definition.date_from if isinstance(definition.date_from, date) else None
        concrete_to = definition.date_to if isinstance(definition.date_to, date) else None
        if concrete_from or concrete_to:
            date_column = next((resolve_sql_column(columns, candidate) for candidate in ('event_start_time', 'Test_Start_Time', 'Timestamp', 'Date') if resolve_sql_column(columns, candidate)), None)
            if date_column is None:
                clauses.append('0')
            else:
                if concrete_from:
                    clauses.append(f"datetime({quote(date_column)}) >= datetime(?)")
                    params.append(concrete_from.isoformat())
                if concrete_to:
                    clauses.append(f"datetime({quote(date_column)}) < datetime(?, '+1 day')")
                    params.append(concrete_to.isoformat())
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
            # copy_dataset_rows_to_reporting correctly repairs incomplete
            # columns, but its verification aggregates every requested field
            # over each CDR.  Remember a successful validation for this exact
            # source revision and requested-column set so a cache hit does not
            # re-scan the complete Dataset Universe before using its cached
            # filtered selection.
            signature_payload = {
                'schema': 1,
                'datasets': [
                    (row['id'], row.get('updated_at'), row.get('processed_at'), row.get('normalization_version'), row.get('row_count'))
                    for row in selected
                ],
                'requested': sorted(identity(column) for column in requested),
            }
            signature = sha256(json.dumps(signature_payload, sort_keys=True, default=str).encode()).hexdigest()
            signature_key = f'dashboard_filter_projection_v1_{kind}'
            if task_repository.get_workspace_state(signature_key) == signature:
                continue
            changed = False
            for row in selected:
                # Existing rows can still have NULL values for fields added by
                # another dataset or by a later normalization pass. The copy
                # helper has a fast no-change path and repairs only incomplete
                # requested columns for this selected dataset.
                if task_repository.copy_dataset_rows_to_reporting(
                    row['id'], kind, sorted(requested, key=str.casefold),
                ):
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
            task_repository.set_workspace_state(signature_key, signature)

    def persistent_selection_key(definition, task_repository, dimensions, selected_by_kind):
        versions = {
            kind: sorted([
                (row['id'], row.get('updated_at'), row.get('processed_at'), row.get('normalization_version'), row.get('row_count'))
                for row in selected
            ], key=lambda row: row[0])
            for kind, selected in selected_by_kind.items()
        }
        revisions = {kind: task_repository.get_workspace_state(f'combined_reporting_updated_{kind}') for kind in selected_by_kind}
        selection_definition = {
            'technology': definition.technology,
            'datasets': {
                kind: sorted(set(dataset_ids))
                for kind, dataset_ids in definition.datasets.items()
            },
            'filters': {
                field: sorted(set(values))
                for field, values in definition.filters.items()
            },
            'custom_fields': sorted(set(definition.custom_fields), key=str.casefold),
            'hidden_filters': sorted(set(definition.hidden_filters), key=str.casefold),
            'date_from': definition.date_from,
            'date_to': definition.date_to,
        }
        payload = {
            # Scope changes only how charts group the already selected rows.
            # Keep that presentation setting out of the selection cache key.
            'schema': DASHBOARD_SELECTION_CACHE_VERSION,
            'definition': selection_definition,
            'versions': versions,
            'combined_revisions': revisions,
            'dimensions': core.calculated_dimensions_json(dimensions),
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def selected_date_bounds(task_repository, selected_by_kind):
        """Return the inclusive calendar bounds across the selected source datasets."""
        sources = {}
        for kind, selected in selected_by_kind.items():
            columns = task_repository.list_reporting_row_columns(kind)
            date_column = next((
                resolve_sql_column(columns, candidate)
                for candidate in ('event_start_time', 'Test_Start_Time', 'Timestamp', 'Date')
                if resolve_sql_column(columns, candidate)
            ), None)
            sources[kind] = {
                'datasets': sorted((
                    row['id'], row.get('updated_at'), row.get('processed_at'),
                    row.get('normalization_version'), row.get('row_count'),
                ) for row in selected),
                'revision': task_repository.get_workspace_state(f'combined_reporting_updated_{kind}'),
                'date_column': date_column,
            }
        cache_signature = sha256(json.dumps({
            'schema': DASHBOARD_DATE_BOUNDS_CACHE_VERSION, 'sources': sources,
        }, sort_keys=True, default=str).encode()).hexdigest()
        cache_state_key = f'dashboard_date_bounds_v{DASHBOARD_DATE_BOUNDS_CACHE_VERSION}'
        try:
            cached_bounds = json.loads(task_repository.get_workspace_state(cache_state_key) or '{}')
            if not isinstance(cached_bounds, dict):
                cached_bounds = {}
            if cache_signature in cached_bounds:
                return cached_bounds[cache_signature]
        except (TypeError, ValueError, json.JSONDecodeError):
            cached_bounds = {}
        lower = upper = None
        with task_repository.connection() as connection:
            for kind, selected in selected_by_kind.items():
                date_column = sources[kind]['date_column']
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
        bounds = None if lower is None or upper is None else {'min': lower.isoformat(), 'max': upper.isoformat()}
        # This result is immutable while the selected datasets and their
        # combined-table revisions are unchanged.  Persist a small bounded
        # map so restarting the server does not repeat a full date scan just
        # to validate a Dashboard preview manifest.
        cached_bounds[cache_signature] = bounds
        if len(cached_bounds) > 128:
            cached_bounds = dict(list(cached_bounds.items())[-128:])
        task_repository.set_workspace_state(cache_state_key, json.dumps(cached_bounds, separators=(',', ':')))
        return bounds

    def apply_selected_date_bounds(definition, bounds):
        if not bounds:
            return
        lower, upper = date.fromisoformat(bounds['min']), date.fromisoformat(bounds['max'])
        definition.date_from = lower if definition.date_from == 'Oldest' or definition.date_from is None or not lower <= definition.date_from <= upper else definition.date_from
        definition.date_to = upper if definition.date_to == 'Newest' or definition.date_to is None or not lower <= definition.date_to <= upper else definition.date_to

    def profile_filter_options(definition, dimensions, selected_by_kind, fields, task_repository):
        """Load large-dashboard facet values from selected CDR profiles."""
        options = {field_name: set() for field_name in fields}
        incomplete_fields = set()
        for selected in selected_by_kind.values():
            for dataset in selected:
                try:
                    stored = dataset.get('filter_options') or json.loads(dataset.get('filter_options_json') or '{}')
                except (TypeError, json.JSONDecodeError):
                    stored = {}
                lookup = {identity(column): values for column, values in stored.items()} if isinstance(stored, dict) else {}
                for field_name in fields:
                    aliases = next((values for label, values in FILTER_COLUMNS.items() if identity(label) == identity(field_name)), (field_name,))
                    resolved = next((
                        column for alias in aliases
                        if (column := task_repository.resolve_dataset_row_column_name(int(dataset['id']), alias))
                    ), None)
                    if resolved is None:
                        continue
                    lookup_keys = list(dict.fromkeys([
                        identity(resolved), identity(field_name),
                        *(identity(alias) for alias in aliases),
                    ]))
                    values = next((lookup[key] for key in lookup_keys if isinstance(lookup.get(key), list)), None)
                    if not isinstance(values, list):
                        incomplete_fields.add(field_name)
                        continue
                    options[field_name].update(str(value) for value in values if value is not None)
        dimensions_by_name = {identity(dimension.name): dimension for dimension in dimensions}
        for field_name in fields:
            dimension = dimensions_by_name.get(identity(field_name))
            if dimension:
                incomplete_fields.discard(field_name)
                options[field_name].update(str(rule.value) for rule in dimension.rules if str(rule.value).strip())
                if str(dimension.default).strip():
                    options[field_name].add(str(dimension.default))
            options[field_name].update(str(value) for value in definition.filters.get(field_name, ()) if value is not None)
        missing_fields = [
            field_name for field_name in fields
            if not options[field_name] or field_name in incomplete_fields
        ]
        if missing_fields:
            # Older upload profiles do not contain every Dashboard facet. Read
            # only the missing catalogues from the narrow combined tables. An
            # adaptive facet must ignore its own current restriction so users
            # can see and select values outside the saved selection.
            with task_repository.connection() as connection:
                for kind, selected in selected_by_kind.items():
                    columns = task_repository.list_reporting_row_columns(kind)
                    table = task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))
                    active_filter_keys = {identity(field_name) for field_name in definition.filters}
                    facet_groups: dict[str | None, list[str]] = {None: []}
                    for field_name in missing_fields:
                        excluded = field_name if identity(field_name) in active_filter_keys else None
                        facet_groups.setdefault(excluded, []).append(field_name)
                    for excluded, group_fields in facet_groups.items():
                        available = [
                            (field_name, filter_sql_value_expression(task_repository, columns, field_name))
                            for field_name in group_fields
                        ]
                        available = [(field_name, expression) for field_name, expression in available if expression is not None]
                        if not available:
                            continue
                        where, params = selection_where(
                            task_repository, kind, [int(row['id']) for row in selected], definition,
                            exclude=excluded, columns=columns,
                        )
                        select_clause = ', '.join(
                            f'json_group_array(DISTINCT {expression}) AS facet_{index}'
                            for index, (_field_name, expression) in enumerate(available)
                        )
                        row = connection.execute(f'SELECT {select_clause} FROM {table} WHERE {where}', params).fetchone()
                        for index, (field_name, _column) in enumerate(available):
                            encoded_values = row[f'facet_{index}'] if row else '[]'
                            options[field_name].update(str(value) for value in json.loads(encoded_values or '[]'))
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
                options = profile_filter_options(
                    definition, dimensions, selected_by_kind, fields, task_repository,
                )
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
                        available = [
                            (field_name, filter_sql_value_expression(task_repository, columns, field_name))
                            for field_name in group_fields
                        ]
                        available = [(field_name, expression) for field_name, expression in available if expression is not None]
                        if not available:
                            continue
                        where, params = selection_where(
                            task_repository, kind, [int(row['id']) for row in selected], definition, exclude=excluded,
                        )
                        select_clause = ', '.join(
                            f'json_group_array(DISTINCT {expression}) AS facet_{index}'
                            for index, (_field_name, expression) in enumerate(available)
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
                'SELECT id FROM dashboard_filter_selections ORDER BY last_accessed_at DESC, id DESC LIMIT -1 OFFSET ?',
                (DASHBOARD_SELECTION_CACHE_LIMIT,),
            ).fetchall()
            for row in stale:
                connection.execute('DELETE FROM dashboard_filter_selection_rows WHERE selection_id = ?', (row['id'],))
                connection.execute('DELETE FROM dashboard_filter_selections WHERE id = ?', (row['id'],))
            return selection_id, cache_key, materialized, options, row_counts, True

    def load_filter_options(definition, field_name, task_repository):
        """Load one adaptive filter catalogue without preparing Dashboard charts."""
        field_name = field_name.strip()
        entries = validate(definition, task_repository)
        dimensions = core.load_repository_calculated_dimensions(task_repository)
        selected_by_kind = selected_sources(definition, task_repository)
        requested_definition = definition.model_copy(deep=True)
        known_default = any(identity(field_name) == identity(field) for field in ADAPTATIVE_FILTER_FIELDS)
        if not known_default and not any(identity(field_name) == identity(field) for field in requested_definition.custom_fields):
            requested_definition.custom_fields.append(field_name)
        ensure_filter_projection(requested_definition, task_repository, dimensions, selected_by_kind, entries)
        apply_selected_date_bounds(requested_definition, selected_date_bounds(task_repository, selected_by_kind))
        values = set()
        resolved = False
        with task_repository.connection() as connection:
            for kind, selected in selected_by_kind.items():
                columns = task_repository.list_reporting_row_columns(kind)
                value_expression = filter_sql_value_expression(task_repository, columns, field_name)
                if value_expression is None:
                    continue
                resolved = True
                where, params = selection_where(
                    task_repository, kind, [int(row['id']) for row in selected],
                    requested_definition, exclude=field_name, columns=columns,
                )
                table = task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))
                rows = connection.execute(
                    f'SELECT DISTINCT {value_expression} AS value '
                    f'FROM {table} WHERE {where}', params,
                ).fetchall()
                values.update(str(row['value']) for row in rows)
        if not resolved:
            raise HTTPException(400, f'The selected CDRs do not contain the {field_name} field.')
        return sorted(values, key=str.casefold)

    def build_preview(definition, user, *, workspace: str | None = None, cancelled=None, progress=None):
        def ensure_not_cancelled():
            if callable(cancelled) and cancelled():
                raise RuntimeError('Dashboard preparation cancelled.')

        def report(percent, detail):
            if callable(progress):
                progress(percent, detail)

        workspace = workspace or workspace_key()
        report(5, 'Validating Dashboard sources')
        ensure_not_cancelled()
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        entries = validate(definition, task_repository)
        dimensions = core.load_repository_calculated_dimensions(task_repository)
        selected_by_kind = selected_sources(definition, task_repository)
        selected_source_rows = {
            kind: sum(int(dataset.get('row_count') or 0) for dataset in selected)
            for kind, selected in selected_by_kind.items()
        }
        report(20, 'Preparing Dashboard source columns')
        ensure_filter_projection(definition, task_repository, dimensions, selected_by_kind, entries)
        ensure_not_cancelled()
        report(45, 'Resolving Dataset Universe dates')
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
        report(60, 'Building filtered Dashboard selection')
        selection_id, selection_key, selection_materialized, options, row_counts, rows_exact = materialize_selection(
            definition, task_repository, dimensions, selected_by_kind, fields, use_profile_options=use_profile_options,
        )
        report(82, 'Preparing Dashboard slides')
        full_date_range = bool(
            date_bounds
            and str(definition.date_from) == date_bounds['min']
            and str(definition.date_to) == date_bounds['max']
        )
        universe_rows = (
            dict(row_counts) if not definition.filters and (full_date_range or not date_bounds)
            else selected_source_rows
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
            'universe_rows': universe_rows,
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
        projection_kinds = tuple(selected_by_kind)
        for position, kind in enumerate(projection_kinds, start=1):
            ensure_not_cancelled()
            report(68 + round((position - 1) * 14 / max(len(projection_kinds), 1)), f'Preparing {kind.title()} Dashboard projection')
            ensure_projection(snapshot, kind, task_repository)
        ensure_not_cancelled()
        report(82, 'Dashboard dataset is ready')
        # Canvas inputs are chart work. Leave them to the warm-up queue so an
        # applied selection becomes usable as soon as its compact projections
        # are ready instead of reading and filtering the CDR once per chart.
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
            core.invalidate_workspace_size_cache(Path(workspace).parent)
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

    def preview_cache_identity(definition):
        """Return the parts of a Dashboard definition that affect its prepared data."""
        identity_definition = definition.model_dump(mode='json')
        identity_definition.pop('name', None)
        identity_definition.pop('slide_comments', None)
        return identity_definition

    def restore_matching_preview_manifest(workspace: str, dashboard_id: str, definition: DashboardDefinition):
        """Restore a persistent preview by definition, including non-default session universes."""
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        requested = definition.model_copy(deep=True)
        try:
            requested_fingerprint = dashboard_preview_fingerprint(
                requested.model_dump(mode='json'), task_repository,
            )
            apply_selected_date_bounds(requested, selected_date_bounds(
                task_repository, selected_sources(requested, task_repository),
            ))
            requested_identity = preview_cache_identity(requested)
            for manifest_path in preview_manifest_cache_dir(workspace).glob('*.json'):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                    if (
                        manifest.get('version') != DASHBOARD_PREVIEW_MANIFEST_VERSION
                        or manifest.get('dashboard_id') != dashboard_id
                        or not isinstance(manifest.get('fingerprint'), str)
                        or manifest.get('fingerprint') != requested_fingerprint
                    ):
                        continue
                    stored_definition = DashboardDefinition.model_validate(manifest['definition'])
                    if preview_cache_identity(stored_definition) != requested_identity:
                        continue
                    restored = restore_preview_manifest(workspace, dashboard_id, manifest['fingerprint'])
                    if restored is not None:
                        return restored
                except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
                    continue
        except (ValueError, sqlite3.Error):
            return None
        return None

    @app.post('/api/e2e-dashboards/prepare')
    def prepare(
        definition: DashboardDefinition,
        dashboard_id: str | None = None,
        rendering_only: bool = False,
        preparation_id: str | None = None,
        use_scope_universe: bool = False,
        user=Depends(dashboard_user),
    ):
        if use_scope_universe:
            definition = automatic_scope_universe(definition, bound_repository())
        preparation_id = preparation_id or f'dashboard-preparation:{uuid4().hex}'
        workspace = workspace_key()
        cancellation = {'requested': False}
        deferred_prefetches = []
        with lock:
            # Foreground work has priority over every automatic Dashboard
            # warm-up. Cancel all queued/running warm-ups before waiting for
            # the shared gate, then put the unrelated ones back afterwards.
            for job in prefetch_jobs.values():
                if job.get('status') not in {'queued', 'processing'} or job.get('cancel_requested'):
                    continue
                raw_definition = job.get('raw_definition')
                if isinstance(raw_definition, dict):
                    deferred_prefetches.append((
                        str(job.get('dashboard_id') or ''), raw_definition,
                        job.get('user') or SimpleNamespace(username='*'), str(job.get('workspace') or ''),
                    ))
                job['cancel_requested'] = True
                if job.get('status') == 'queued':
                    job['status'] = 'cancelled'
            for task_id, task in direct_preparation_tasks.items():
                if task_id == preparation_id:
                    continue
                existing_cancellation = task.get('cancellation')
                if isinstance(existing_cancellation, dict):
                    existing_cancellation['requested'] = True
            direct_preparation_tasks[preparation_id] = {
                'id': preparation_id, 'workspace': workspace, 'name': definition.name,
                'dashboard_id': dashboard_id,
                'rendering_only': rendering_only, 'cancellation': cancellation,
                'progress': 0, 'detail': 'Starting Dashboard preparation',
            }
        try:
            def preparation_cancelled():
                return bool(cancellation['requested'])

            def update_preparation_progress(percent, detail):
                with lock:
                    task = direct_preparation_tasks.get(preparation_id)
                    if task is not None:
                        task.update(progress=percent, detail=detail)

            with dashboard_work_gate:
                preview = build_preview(
                    definition, user, workspace=workspace, cancelled=preparation_cancelled,
                    progress=update_preparation_progress,
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
        except RuntimeError as exc:
            if cancellation['requested']:
                raise HTTPException(409, 'Dashboard preparation was interrupted.') from exc
            raise
        finally:
            with lock:
                direct_preparation_tasks.pop(preparation_id, None)
            def restore_deferred_prefetches():
                requeued = set()
                for deferred_id, deferred_definition, deferred_user, deferred_workspace in deferred_prefetches:
                    deferred_key = (deferred_workspace, deferred_id)
                    if not deferred_id or deferred_key in requeued or (
                        dashboard_id == deferred_id and workspace == deferred_workspace
                    ):
                        continue
                    requeued.add(deferred_key)
                    enqueue_prefetch(
                        deferred_id, deferred_definition, deferred_user, workspace=deferred_workspace,
                    )
                # A foreground request may arrive after an older implementation
                # removed a warm-up from the in-memory queue. Re-read the saved
                # definitions so every other Dashboard is restored to the serial
                # warm-up queue, while the current Dashboard continues through
                # its already-returned prepared preview.
                if not dashboard_id:
                    return
                try:
                    task_repository = Repository(Path(workspace), core.repository.global_db_path)
                    for saved_id, saved_definition in read_dashboards(task_repository).items():
                        saved_key = (workspace, str(saved_id))
                        if str(saved_id) == dashboard_id or saved_key in requeued:
                            continue
                        requeued.add(saved_key)
                        enqueue_prefetch(
                            str(saved_id), saved_definition, user, workspace=workspace,
                        )
                except (OSError, sqlite3.Error, json.JSONDecodeError):
                    pass
            # Returning the completed selection must not wait for unrelated
            # manifest lookups or warm-up queue reconstruction.
            Thread(target=restore_deferred_prefetches, daemon=True, name='e2e-dashboard-prefetch-requeue').start()

    @app.post('/api/e2e-dashboards/filter-options')
    def filter_options(request: DashboardFilterOptionsRequest, user=Depends(dashboard_user)):
        try:
            task_repository = bound_repository()
            values = load_filter_options(request.definition, request.field, task_repository)
            return {'field': request.field.strip(), 'values': values}
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get('/api/e2e-dashboards/prepared/{token}')
    def prepared_preview(token: str, user=Depends(dashboard_user)):
        with lock:
            snapshot = snapshots.get(token)
            if snapshot is None or snapshot.workspace != workspace_key() or snapshot.owner not in {user.username, '*'}:
                raise HTTPException(410, 'Dashboard preview expired. Refresh the Dashboard.')
            return {**snapshot.payload, 'token': token}

    @app.get('/api/e2e-dashboards/preparation-progress/{preparation_id}')
    def preparation_progress(preparation_id: str, user=Depends(dashboard_user)):
        workspace = workspace_key()
        with lock:
            task = direct_preparation_tasks.get(preparation_id)
            if task is None or task.get('workspace') != workspace:
                raise HTTPException(404, 'Dashboard preparation is no longer active.')
            return {
                'progress': task.get('progress', 0),
                'detail': task.get('detail') or 'Preparing Dashboard dataset',
            }

    def prefetched_dashboard_response(dashboard_id: str, definition: DashboardDefinition, user):
        workspace = workspace_key()
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        with lock:
            raw_definition = definition.model_dump(mode='json')
            fingerprint = dashboard_preview_fingerprint(raw_definition, task_repository)
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
            if token and snapshot is not None and snapshot.owner in {user.username, '*'}:
                snapshots.move_to_end(token)
                return {**snapshot.payload, 'token': token}
        # Jobs and snapshots are intentionally in-memory, but this manifest is
        # shared, revision-validated and survives server restarts.  Restore it
        # before asking a user to prepare the same universe again.
        restored = restore_matching_preview_manifest(workspace, dashboard_id, definition)
        if restored is not None:
            enqueue_prefetch(dashboard_id, definition.model_dump(mode='json'), user,
                             workspace=workspace, prepared_preview=restored)
            return restored
        raise HTTPException(409, 'Dashboard preparation is still running.')

    @app.get('/api/e2e-dashboards/prefetched/{dashboard_id}')
    def prefetched_dashboard(dashboard_id: str, user=Depends(dashboard_user)):
        task_repository = bound_repository()
        with lock:
            raw_definition = read_dashboards(task_repository).get(dashboard_id)
            if not isinstance(raw_definition, dict):
                raise HTTPException(404, 'Dashboard not found.')
            definition = DashboardDefinition.model_validate(runtime_dashboard_definition(raw_definition, task_repository))
        return prefetched_dashboard_response(dashboard_id, definition, user)

    @app.post('/api/e2e-dashboards/prefetched/{dashboard_id}')
    def prefetched_dashboard_for_definition(
        dashboard_id: str,
        definition: DashboardDefinition,
        use_scope_universe: bool = False,
        user=Depends(dashboard_user),
    ):
        task_repository = bound_repository()
        with lock:
            if dashboard_id not in read_dashboards(task_repository):
                raise HTTPException(404, 'Dashboard not found.')
        if use_scope_universe:
            definition = automatic_scope_universe(definition, task_repository)
        return prefetched_dashboard_response(dashboard_id, definition, user)

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
                core.invalidate_workspace_size_cache(Path(snapshot.workspace).parent)
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

    def parse_chart_column_filters(encoded):
        try:
            payload = json.loads(encoded or '{}')
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(column): [str(value) for value in values]
            for column, values in payload.items() if isinstance(values, list)
        }

    def chart_dataset_filter_values(frame):
        return {
            str(column): sorted(
                {'' if pd.isna(value) else str(value) for value in frame[column]},
                key=lambda value: value.casefold(),
            )
            for column in frame.columns
        }

    def apply_chart_column_filters(frame, column_filters):
        result = frame
        lookup = {identity(column): column for column in frame.columns}
        for requested, values in column_filters.items():
            column = lookup.get(identity(requested))
            if column is None or not values:
                return result.iloc[0:0]
            accepted = set(values)
            result = result.loc[
                result[column].map(lambda value: '' if pd.isna(value) else str(value)).isin(accepted)
            ]
        return result

    def chart_row_universe(snapshot, entry, selected=None):
        """Return the strongest known upper bound for one chart's source rows."""
        if selected is None:
            task_repository = Repository(Path(snapshot.workspace), core.repository.global_db_path)
            selected = core._optional_reporting_datasets(
                snapshot.definition.datasets.get(entry.source_kind, []), entry.source_kind, task_repository,
            )
        limits = []
        source_total = sum(int(row.get('row_count') or 0) for row in selected)
        if source_total:
            limits.append(source_total)
        filtered_rows = (snapshot.payload.get('rows') or {}).get(entry.source_kind)
        if filtered_rows is not None:
            limits.append(max(0, int(filtered_rows)))
        return min(limits) if limits else 0

    def projection_chart_data_page(
        snapshot, entry, page, column_filters=None, include_filter_values=False,
    ):
        """Read one exact chart-data page without rebuilding its full DataFrame."""
        spec = _catalog_spec(entry)
        if spec.get('operators'):
            return None
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
        source_filters = (
            (spec.get('sessions'), ('Session_Type', 'session_type', 'Test_Name', 'Test_Type')),
            (spec.get('tests'), ('Test_Name', 'test_name', 'Type_of_Test', 'Test_Type')),
            (spec.get('directions'), ('Direction', 'direction', 'Call_Direction')),
            ((spec.get('city_scope'),) if spec.get('city_scope') else None, ('city', 'City', 'G_Level_1', 'G_Level_2')),
        )
        for values, candidates in source_filters:
            if not values:
                continue
            column = next((resolve_sql_column(projection_columns, name) for name in candidates if resolve_sql_column(projection_columns, name)), None)
            if not column:
                continue
            expression = ' OR '.join(
                f'LOWER(COALESCE(CAST({task_repository._quote_identifier(column)} AS TEXT), \'\')) LIKE ?'
                for _value in values
            )
            where = f'({where}) AND ({expression})'
            parameters.extend(f'%{str(value).casefold()}%' for value in values)
        template_where, template_parameters, filters_applied = chart_filter_sql(
            entry, projection_columns, snapshot.multivendor,
        )
        if not filters_applied:
            return None
        if template_where:
            where = f'({where}) AND ({template_where})'
            parameters.extend(template_parameters)
        lookup = {identity(column): column for column in projection_columns}
        selected_columns = []
        for requested in chart_query_columns(entry, snapshot.multivendor):
            actual = lookup.get(identity(requested))
            if actual and actual not in selected_columns:
                selected_columns.append(actual)
        dataset_column = lookup.get(identity('dataset_id'))
        source_row_column = lookup.get(identity('source_row_id'))
        if not selected_columns or not dataset_column or not source_row_column:
            return None
        quote = lambda column: '"' + str(column).replace('"', '""') + '"'
        identity_columns = f'{quote(dataset_column)}, {quote(source_row_column)}'
        page = max(0, int(page))
        connection = sqlite3.connect(cache_path, timeout=120.0)
        try:
            chart_total = int(connection.execute(
                f'SELECT COUNT(*) FROM ('
                f'SELECT 1 FROM {quote(table_name)} WHERE {where} GROUP BY {identity_columns}'
                f')',
                parameters,
            ).fetchone()[0])
            chart_total = min(chart_total, chart_row_universe(snapshot, entry, selected))
            filter_values = {}
            if include_filter_values:
                values_query = ', '.join(
                    f'json_group_array(DISTINCT COALESCE(CAST({quote(column)} AS TEXT), \'\')) AS filter_{index}'
                    for index, column in enumerate(selected_columns)
                )
                values_row = connection.execute(
                    f'SELECT {values_query} FROM {quote(table_name)} WHERE {where}', parameters,
                ).fetchone()
                filter_values = {
                    column: sorted(
                        (str(value) for value in json.loads(values_row[index] or '[]')),
                        key=lambda value: value.casefold(),
                    )
                    for index, column in enumerate(selected_columns)
                }
            filtered_where = where
            filtered_parameters = list(parameters)
            for requested, values in (column_filters or {}).items():
                column = lookup.get(identity(requested))
                if column is None or not values:
                    filtered_where = f'({filtered_where}) AND 0'
                    continue
                placeholders = ', '.join('?' for _value in values)
                filtered_where = (
                    f'({filtered_where}) AND '
                    f'COALESCE(CAST({quote(column)} AS TEXT), \'\') IN ({placeholders})'
                )
                filtered_parameters.extend(values)
            total = chart_total
            if column_filters:
                total = int(connection.execute(
                    f'SELECT COUNT(*) FROM ('
                    f'SELECT 1 FROM {quote(table_name)} WHERE {filtered_where} GROUP BY {identity_columns}'
                    f')',
                    filtered_parameters,
                ).fetchone()[0])
                total = min(total, chart_total)
            page_size = min(100, max(0, total - page * 100))
            query = (
                f'SELECT {", ".join(quote(column) for column in selected_columns)} '
                f'FROM {quote(table_name)} WHERE {filtered_where} GROUP BY {identity_columns} '
                f'ORDER BY {identity_columns} LIMIT ? OFFSET ?'
            )
            visible = pd.read_sql_query(
                query, connection, params=(*filtered_parameters, page_size, page * 100),
            )
        finally:
            connection.close()
        if snapshot.multivendor:
            visible = ensure_report_vendor_group(visible)
        visible = normalise_report_operator_aliases(visible)
        return visible, total, chart_total, filter_values

    def unique_chart_dataset_rows(snapshot, entry, frame):
        """Keep one preview row per source row and never exceed its filtered CDR universe."""
        lookup = {identity(column): column for column in frame.columns}
        identity_columns = [
            lookup[key] for key in (identity('dataset_id'), identity('source_row_id')) if key in lookup
        ]
        result = frame.drop_duplicates(subset=identity_columns, keep='first') if identity_columns else frame
        universe = chart_row_universe(snapshot, entry)
        return result.iloc[:universe] if len(result) > universe else result

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

    def chart_model(
        token: str,
        index: int,
        user,
        *,
        expected_workspace: str | None = None,
        force: bool = False,
    ):
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False, expected_workspace=expected_workspace)
        model_path = canvas_model_path(snapshot, entry)
        model_dir = model_path.parent
        if force:
            with lock:
                snapshot.chart_payloads.pop(index, None)
            model_path.unlink(missing_ok=True)
        with lock:
            payload = snapshot.chart_payloads.get(index)
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
                core.invalidate_workspace_size_cache(Path(snapshot.workspace).parent)
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

    @app.post('/api/e2e-dashboards/chart/{token}/{index}/refresh')
    def refresh_interactive_chart(token: str, index: int, user=Depends(dashboard_user)):
        """Invalidate and rebuild only the requested Canvas chart model."""
        payload = chart_model(token, index, user, force=True)
        return JSONResponse(payload, headers={'Cache-Control': 'no-store'})

    @app.post('/api/e2e-dashboards/charts/{token}/refresh')
    def refresh_interactive_charts(token: str, user=Depends(dashboard_user)):
        """Invalidate and rebuild every available Canvas model in a Dashboard snapshot."""
        with lock:
            snapshot = snapshots.get(token)
        workspace = workspace_key()
        if snapshot is None or snapshot.workspace != workspace or snapshot.owner not in {user.username, '*'}:
            raise HTTPException(410, 'Dashboard preview expired. Refresh the Dashboard.')
        indexes = list(dict.fromkeys(
            int(chart['index'])
            for slide in snapshot.payload.get('slides', [])
            for chart in slide.get('charts', [])
            if chart.get('available')
        ))
        with ThreadPoolExecutor(
            max_workers=DASHBOARD_CHART_RENDER_WORKERS,
            thread_name_prefix='e2e-dashboard-refresh',
        ) as chart_executor:
            futures = [
                chart_executor.submit(
                    chart_model, token, index, user, expected_workspace=workspace, force=True,
                )
                for index in indexes
            ]
            for future in as_completed(futures):
                future.result()
        core.invalidate_workspace_size_cache(Path(workspace).parent)
        return {'refreshed': len(indexes)}

    @app.get('/api/e2e-dashboards/chart/{token}/{index}/filter-context')
    def interactive_chart_filter_context(token: str, index: int, user=Depends(dashboard_user)):
        """Return filter fields available to an expanded Dashboard chart."""
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False)
        task_repository = Repository(Path(snapshot.workspace), core.repository.global_db_path)
        _cache_path, _table_name, columns = ensure_projection(snapshot, entry.source_kind, task_repository)
        hidden = {identity('dataset_id'), identity('source_row_id')}
        datasets_by_source = {f'cdr-{kind}': [] for kind in KINDS}
        columns_by_source = {f'cdr-{kind}': [] for kind in KINDS}
        for row in task_repository.list_datasets():
            kind = str(row['dataset_kind'] or '').casefold()
            if kind in KINDS and row['status'] == 'ready':
                datasets_by_source[f'cdr-{kind}'].append({
                    'value': str(row['id']), 'label': str(row['file_name']),
                })
                columns_by_source[f'cdr-{kind}'].extend(
                    str(column) for column in task_repository.list_dataset_row_columns(int(row['id']))
                )
        for source, source_columns in columns_by_source.items():
            columns_by_source[source] = sorted({
                column for column in source_columns if identity(column) not in hidden
            }, key=str.casefold)
        template_available = user.role in {'admin', 'super-admin'} and any(
            str(row['name']) == snapshot.definition.template
            for row in task_repository.list_report_templates(snapshot.definition.template_technology)
        )
        return JSONResponse({
            'cdr_source': entry.cdr_source,
            'chart_type': entry.chart_type,
            'chart_title': entry.chart_title,
            'kpi': entry.kpi,
            'dataset_ids': [str(value) for value in snapshot.definition.datasets.get(entry.source_kind, [])],
            'filters': entry.filters,
            'grouping_rows': entry.grouping_rows,
            'grouping_columns': entry.grouping_columns,
            'legend': entry.legend,
            'legend_position': entry.legend_position, 'template_available': template_available,
            'datasets_by_source': datasets_by_source, 'columns_by_source': columns_by_source,
            'columns': columns_by_source.get(f'cdr-{entry.source_kind}', [str(column) for column in columns if identity(column) not in hidden]),
        })

    @app.post('/api/e2e-dashboards/chart/{token}/{index}/filter-preview')
    def interactive_chart_filter_preview(
        token: str,
        index: int,
        request: DashboardChartFilterPreviewRequest,
        user=Depends(dashboard_user),
    ):
        """Render one expanded chart with temporary, unsaved template filters."""
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False)
        changes = {
            key: value for key, value in request.model_dump().items()
            if value is not None and key in {
                'filters', 'chart_title', 'cdr_source', 'kpi', 'chart_type', 'grouping_rows',
                'grouping_columns', 'legend', 'legend_position',
            }
        }
        # The template owns these required chart attributes. Custom dropdowns
        # can briefly report an empty value while their available fields are
        # being rebuilt, which must not erase the template KPI/source/type.
        for key in ('cdr_source', 'kpi', 'chart_type'):
            if not str(changes.get(key, '')).strip():
                changes.pop(key, None)
        preview_entry = replace(entry, **changes)
        if not preview_entry.source_kind:
            raise HTTPException(400, 'Select a valid CDR type.')
        task_repository = Repository(Path(snapshot.workspace), core.repository.global_db_path)
        preview_definition = snapshot.definition.model_copy(deep=True)
        if request.dataset_ids is not None:
            values = request.dataset_ids if isinstance(request.dataset_ids, list) else str(request.dataset_ids).split(',')
            try:
                preview_definition.datasets[preview_entry.source_kind] = list(dict.fromkeys(
                    int(str(value).strip()) for value in values if str(value).strip()
                ))
            except ValueError as exc:
                raise HTTPException(400, 'Selected datasets must have valid identifiers.') from exc
        # The Dashboard snapshot projection is deliberately narrow. An expanded
        # chart may introduce any available field, so create a short-lived
        # projection specification from its current definition instead of
        # silently dropping newly entered grouping, KPI or legend fields.
        preview_snapshot = replace(
            snapshot, entries=[preview_entry], definition=preview_definition,
            projections={}, frames={}, chart_frames={}, filtered_frames={}, chart_payloads={}, frame_locks={},
        )
        selected = core._optional_reporting_datasets(
            preview_definition.datasets.get(preview_entry.source_kind, []), preview_entry.source_kind,
            task_repository,
        )
        cache_path, table_name, projection_columns = ensure_projection(
            preview_snapshot, preview_entry.source_kind, task_repository,
        )
        where, parameters = selection_where(
            task_repository, preview_entry.source_kind, [int(row['id']) for row in selected],
            preview_definition, columns=projection_columns, include_dataset_scope=False,
        )
        requested_columns = chart_query_columns(preview_entry, snapshot.multivendor)
        template_where, template_parameters, template_filters_applied = chart_filter_sql(
            preview_entry, projection_columns, snapshot.multivendor,
        )
        if template_where:
            where = f'({where}) AND ({template_where})'
            parameters.extend(template_parameters)
        aggregation_columns = chart_aggregation_columns(
            preview_entry, projection_columns, snapshot.multivendor, template_filters_applied,
        )
        raw_frame = load_projection_frame(
            cache_path, table_name, projection_columns, requested_columns, where, parameters,
            aggregation_columns,
        )
        if snapshot.multivendor:
            raw_frame = ensure_report_vendor_group(raw_frame)
        raw_frame = normalise_report_operator_aliases(raw_frame)
        raw_frame.attrs['report_operator_aliases_normalized'] = True
        try:
            frame, _ = prepare_catalog_chart_preview_frame(
                raw_frame, preview_entry, multivendor=snapshot.multivendor,
                template_filters_applied=template_filters_applied,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(catalog_chart_payload(
            frame, preview_entry, multivendor=snapshot.multivendor, prefiltered=True,
        ), headers={'Cache-Control': 'no-store'})

    @app.post('/api/e2e-dashboards/chart/{token}/{index}/update-template')
    def update_interactive_chart_template(
        token: str,
        index: int,
        request: DashboardChartFilterPreviewRequest,
        user=Depends(dashboard_admin_user),
    ):
        """Persist the expanded Chart Definition into its source template row."""
        snapshot, _entry, _ = snapshot_chart(token, index, user, include_frame=False)
        task_repository = Repository(Path(snapshot.workspace), core.repository.global_db_path)
        technology, template_name = snapshot.definition.template_technology, snapshot.definition.template
        template = next((
            row for row in task_repository.list_report_templates(technology)
            if str(row['name']) == template_name
        ), None)
        if template is None:
            raise HTTPException(404, 'The Report Template used by this chart is no longer available.')
        entries = catalogue(snapshot.definition, task_repository)
        if index >= len(entries):
            raise HTTPException(404, 'The chart row is no longer available in the Report Template.')
        changes = {
            key: value for key, value in request.model_dump().items()
            if value is not None and key in {
                'filters', 'chart_title', 'cdr_source', 'kpi', 'chart_type', 'grouping_rows',
                'grouping_columns', 'legend', 'legend_position',
            }
        }
        for key in ('cdr_source', 'kpi', 'chart_type'):
            if not str(changes.get(key, '')).strip():
                changes.pop(key, None)
        entries[index] = replace(entries[index], **changes)
        try:
            task_repository.set_report_template_content(technology, template_name, core.catalogue_csv(entries))
        except (OSError, ValueError) as exc:
            raise HTTPException(503, f'Unable to update the Report Template: {exc}') from exc
        task_repository.add_log(user.username, 'update_dashboard_chart_template', json.dumps({
            'technology': technology, 'template': template_name, 'chart_index': index,
        }))
        return {'template': template_name, 'technology': technology, 'chart_index': index}

    @app.post('/api/e2e-dashboards/prefetched/{dashboard_id}/priority')
    def prioritize_prefetched_dashboard(
        dashboard_id: str, payload: DashboardPrefetchPriority, user=Depends(dashboard_user),
    ):
        """Move models from the currently visible slide ahead of later work."""
        workspace = workspace_key()
        with lock:
            task_repository = bound_repository()
            raw_definition = read_dashboards(task_repository).get(dashboard_id)
            if not isinstance(raw_definition, dict):
                raise HTTPException(404, 'Dashboard not found.')
            fingerprint = dashboard_preview_fingerprint(raw_definition, task_repository)
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
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        raw_definition = runtime_dashboard_definition(raw_definition, task_repository)
        fingerprint = dashboard_preview_fingerprint(raw_definition, task_repository)
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
                'created_at': monotonic(), 'started_at': datetime.now(timezone.utc).timestamp(),
                'raw_definition': dict(raw_definition), 'user': user,
                'progress': 0, 'detail': 'Queued'}
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
        def run_job():
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

                    def update_warmup_progress(percent, detail):
                        with lock:
                            if not job.get('cancel_requested'):
                                job.update(progress=percent, detail=detail)

                    with dashboard_work_gate:
                        preview = build_preview(
                            definition, user, workspace=workspace, cancelled=preparation_cancelled,
                            progress=update_warmup_progress,
                        )
                persist_preview_manifest(workspace, dashboard_id, fingerprint, preview['token'])
                charts = [chart['index'] for slide in preview['slides'] for chart in slide['charts'] if chart['available']]
                with lock:
                    preview_snapshot = snapshots.get(preview['token'])
                    job.update(
                        token=preview['token'], total=len(charts),
                        progress=100 if not charts else 82,
                        detail='Rendering Dashboard charts' if charts else 'Dashboard dataset is ready',
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
                                job['progress'] = round(82 + job['completed'] * 18 / max(job['total'], 1))
                                job['detail'] = f'{job["completed"]} of {job["total"]} Canvas models'
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
                    job.update(
                        status='ready', token=preview['token'],
                        completed_at=datetime.now(timezone.utc).timestamp(),
                        duration_seconds=round(monotonic() - float(job['created_at']), 3),
                    )
            except Exception as exc:
                with lock:
                    if job.get('cancel_requested') or job.get('generation') != prefetch_generation.get(workspace, 0):
                        job['status'] = 'cancelled'
                    else:
                        job.update(status='failed', error=str(exc))
        def run():
            run_job()

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
            direct_jobs = {}
            for dashboard_id in dashboards:
                direct_jobs[dashboard_id] = next((
                    dict(task) for task in direct_preparation_tasks.values()
                    if task.get('workspace') == workspace and task.get('dashboard_id') == dashboard_id
                ), None)
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
            direct_job = direct_jobs.get(dashboard_id)
            if direct_job is not None:
                rendering_only = bool(direct_job.get('rendering_only'))
                result[dashboard_id] = {
                    'state': 'rendering' if rendering_only else 'loading-data',
                    'label': 'Rendering' if rendering_only else 'Loading data',
                }
                continue
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
                dashboards = read_dashboards(task_repository)
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
            direct_dashboard_ids = {
                str(task.get('dashboard_id')) for task in direct_tasks
                if task.get('dashboard_id')
            }
            pending = [
                job for job in prefetch_jobs.values()
                if (
                    job['status'] in {'queued', 'processing'}
                    and not job.get('restoring_cached_models')
                    and not job.get('cancel_requested')
                    and job.get('generation') == prefetch_generation.get(job.get('workspace'), 0)
                )
            ]
            # A direct request takes priority over automatic warming.  Do not
            # show its cancelling warm-up as a second preparation card for the
            # same Dashboard while the foreground task is already visible.
            workspace_jobs = [
                job for job in pending
                if job['workspace'] == database_path
                and str(job.get('dashboard_id') or '') not in direct_dashboard_ids
            ]
            tasks = []
            for job in workspace_jobs:
                if job['status'] == 'processing':
                    tasks.append({
                        'id': job['task_id'],
                        'dashboard_name': job['name'],
                        'label': 'Rendering Dashboard Charts' if job['total'] else 'Preparing Dashboard dataset',
                        'detail': (
                            f'{job["completed"]} of {job["total"]} Canvas models'
                            if job['total'] else str(job.get('detail') or 'Preparing filtered Dashboard selection')
                        ),
                        'started_at': job.get('started_at'),
                        'progress': round(job['completed'] * 100 / job['total']) if job['total'] else job.get('progress', 0),
                        'stop_task_id': f'dashboard-prepare:{job["task_id"]}',
                        'stop_url': f'/api/background-tasks/{workspace.id}/stop',
                    })
                else:
                    tasks.append({
                        'id': job['task_id'],
                        'dashboard_name': job['name'],
                        'label': 'Queued Dashboard Charts' if job['total'] else 'Queued Dashboard dataset',
                        'detail': 'Queued',
                        'started_at': job.get('started_at'),
                        'progress': 0,
                        'stop_task_id': f'dashboard-prepare:{job["task_id"]}',
                        'stop_url': f'/api/background-tasks/{workspace.id}/stop',
                    })
            tasks.extend({
                'id': task['id'],
                'dashboard_name': task['name'],
                'label': 'Rendering Dashboard Charts' if task.get('rendering_only') else 'Preparing Dashboard dataset',
                'detail': (
                    'Rendering charts with the current Dashboard scope'
                    if task.get('rendering_only')
                    else str(task.get('detail') or 'Building filtered Dashboard selection')
                ),
                'progress': task.get('progress', 0),
                'stop_task_id': f'dashboard-prepare:{task["id"]}',
                'stop_url': f'/api/background-tasks/{workspace.id}/stop',
            } for task in direct_tasks)
            return tasks

    def stop_dashboard_task(workspace_path, task_id):
        database_path = str(Path(workspace_path).resolve())
        stopped = False
        with lock:
            direct = direct_preparation_tasks.get(task_id)
            if direct and direct.get('workspace') == database_path:
                cancellation = direct.get('cancellation')
                if isinstance(cancellation, dict):
                    cancellation['requested'] = True
                    stopped = True
            for job in prefetch_jobs.values():
                if (
                    job.get('workspace') == database_path
                    and job.get('task_id') == task_id
                    and job.get('status') in {'queued', 'processing'}
                    and not job.get('cancel_requested')
                ):
                    job['cancel_requested'] = True
                    if job.get('status') == 'queued':
                        job['status'] = 'cancelled'
                    stopped = True
        return stopped

    core.e2e_dashboard_prefetch_tasks = prefetch_task_payloads
    core.e2e_dashboard_prefetch_workspace = prefetch_workspace_dashboards
    core.e2e_dashboard_cancel_prefetch_workspace = cancel_workspace_prefetch
    core.e2e_dashboard_stop_task = stop_dashboard_task

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
    def chart_data(
        token: str, index: int, page: int = 0, download: bool = False,
        column_filters: str = '', include_filter_values: bool = False,
        user=Depends(dashboard_user),
    ):
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False)
        selected_column_filters = parse_chart_column_filters(column_filters)
        if not download:
            projected_page = projection_chart_data_page(
                snapshot, entry, page, selected_column_filters, include_filter_values,
            )
            if projected_page is not None:
                visible, total, chart_total, filter_values = projected_page
                return {
                    'columns': list(visible.columns),
                    'rows': visible.fillna('').astype(str).values.tolist(),
                    'total': total, 'chart_total': chart_total,
                    'filter_values': filter_values, 'page': max(page, 0),
                }
        _, _, frame = snapshot_chart(token, index, user)
        frame = unique_chart_dataset_rows(snapshot, entry, frame)
        chart_total = len(frame)
        filter_values = chart_dataset_filter_values(frame) if include_filter_values else {}
        frame = apply_chart_column_filters(frame, selected_column_filters)
        if download:
            return Response(frame.to_csv(index=False), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="dashboard-chart-data.csv"'})
        page = max(page, 0)
        visible = frame.iloc[page*100:(page+1)*100].fillna('').astype(str)
        return {
            'columns': list(visible.columns), 'rows': visible.values.tolist(),
            'total': len(frame), 'chart_total': chart_total,
            'filter_values': filter_values, 'page': page,
        }
