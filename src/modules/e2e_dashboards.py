"""Workspace dashboard definitions and shared-table, template-driven previews."""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

import pandas as pd
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from pptx import Presentation

from src.modules.cdr_reporting import (
    _layout_chart_frames, _named_slide_layout, classify_sessions,
    ensure_report_vendor_group, materialize_calculated_dimensions, normalise_report_operator_aliases,
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
    date_from: date | None = None
    date_to: date | None = None


def identity(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


FILTER_COLUMNS = {
    'Market': ('market',), 'Operator': ('operator',), 'Vendor': ('vendor',),
    'Region': ('region',), 'City': ('city',), 'Session Type': ('session_type',),
    'Technology': ('technology_primary', 'technology'),
    'RAT': ('RAT', 'RAT_A', 'Sample_RAT_A'),
}
ADAPTATIVE_FILTER_FIELDS = tuple(FILTER_COLUMNS)


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
            mask &= times < pd.Timestamp(definition.date_to, tz='UTC') + pd.Timedelta(days=1)
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


def install_dashboard_routes(core):
    app = core.app
    lock = RLock()
    snapshots = OrderedDict()
    images = OrderedDict()
    source_frames = OrderedDict()

    def workspace_key():
        if not core.active_workspace:
            raise HTTPException(400, 'Open a workspace before using E2E Dashboards.')
        return str(core.repository.db_path)

    def dashboard_user(user=Depends(core.current_user)):
        if user.role != 'super-admin' and user.username.casefold() != 'ejaitur':
            raise HTTPException(403, 'E2E Dashboards is available only to super-admins and EJAITUR.')
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
            return read_dashboards(bound_repository())

    @app.put('/api/e2e-dashboards/{dashboard_id}')
    def save_dashboard(dashboard_id: str, definition: DashboardDefinition, user=Depends(dashboard_user)):
        with lock:
            task_repository = bound_repository()
            validate(definition, task_repository)
            dashboards = read_dashboards(task_repository)
            if any(key != dashboard_id and item['name'].strip().casefold() == definition.name.strip().casefold() for key, item in dashboards.items()):
                raise HTTPException(409, 'A Dashboard with this name already exists.')
            definition.name = definition.name.strip()
            dashboards[dashboard_id] = definition.model_dump(mode='json')
            task_repository.set_workspace_state(STATE_KEY, json.dumps(dashboards))
            task_repository.add_log(user.username, 'save_dashboard', json.dumps({'id': dashboard_id, 'name': definition.name}))
        return {'id': dashboard_id}

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

    def data_stamp(path):
        return tuple((item.stat().st_mtime_ns, item.stat().st_size) if item.exists() else None
                     for item in (Path(path), Path(str(path) + '-wal')))

    def load_frames(definition, task_repository, dimensions, workspace, entries):
        template_columns = set()
        for kind in KINDS:
            template_columns.update(core.reporting_query_columns(kind, entries, definition.scope == 'multivendor'))
        requested_dimension_keys = {identity(column) for column in template_columns} | {identity(name) for name in definition.custom_fields}
        active_dimensions = tuple(item for item in dimensions if identity(item.name) in requested_dimension_keys)
        selection_key = json.dumps([workspace, definition.datasets, definition.technology, definition.scope, definition.custom_fields], sort_keys=True)
        cache_key = (selection_key, data_stamp(workspace))
        with lock:
            cached = source_frames.get(cache_key)
        if cached is not None:
            return cached
        frames = {}
        for kind in KINDS:
            selected = core._optional_reporting_datasets(definition.datasets.get(kind, []), kind, task_repository)
            if not selected:
                continue
            if definition.scope == 'multivendor' and any(not row.get('vendor_mapping_applied') for row in selected):
                raise HTTPException(400, 'Map Vendors for every selected CDR before using Multivendor Comparison.')
            # Loading every source column for several campaigns can transfer
            # millions of cells before a single filter is shown. Reuse the
            # compact Reporting projection, extending it only with adaptive
            # filter and workspace-field dependencies.
            requested = set(core.reporting_query_columns(kind, entries, definition.scope == 'multivendor'))
            requested.update(core.combined_reporting_required_columns(active_dimensions, kind))
            requested.update(definition.custom_fields)
            requested.update(alias for aliases in FILTER_COLUMNS.values() for alias in aliases)
            requested.update(('event_start_time', 'Test_Start_Time', 'Timestamp', 'Date'))
            columns = sorted(requested, key=str.casefold)
            for row in selected:
                task_repository.copy_dataset_rows_to_reporting(row['id'], kind, columns)
            frame = task_repository.load_reporting_rows(kind, [row['id'] for row in selected], columns)
            if 'source_sheet' in frame:
                frame = frame.loc[~frame.source_sheet.fillna('').astype(str).str.strip().str.casefold().isin(core.CDR_IGNORED_SHEET_KEYS)]
            if kind != 'data':
                frame = classify_sessions(frame, definition.technology)
            frame = materialize_calculated_dimensions(frame, active_dimensions, f'CDR-{kind.title()}')
            frames[kind] = ensure_report_vendor_group(frame) if definition.scope == 'multivendor' else frame
        with lock:
            source_frames[(selection_key, data_stamp(workspace))] = frames
            while len(source_frames) > 2:
                source_frames.popitem(last=False)
        return frames

    def build_preview(definition, user):
        workspace = workspace_key()
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        entries = validate(definition, task_repository)
        dimensions = core.load_repository_calculated_dimensions(task_repository)
        frames = load_frames(definition, task_repository, dimensions, workspace, entries)
        if not frames:
            raise HTTPException(400, 'Select at least one CDR dataset.')
        selected_dataset_ids = {dataset_id for ids in definition.datasets.values() for dataset_id in ids}
        available_fields = {column for dataset_id in selected_dataset_ids for column in task_repository.list_dataset_row_columns(dataset_id)}
        available_fields.update(dimension.name for dimension in dimensions)
        hidden_filter_keys = {identity(field) for field in definition.hidden_filters}
        fields = {field for field in ADAPTATIVE_FILTER_FIELDS if identity(field) not in hidden_filter_keys}
        fields.update(definition.custom_fields)
        for frame in frames.values():
            for label in FILTER_COLUMNS:
                column = resolve_filter_column(frame, label)
                if column is not None and frame[column].fillna('').astype(str).str.strip().ne('').any():
                    fields.add(label)
        fields = sorted(fields, key=str.casefold)
        options = {}
        for field in fields:
            values = set()
            for frame in frames.values():
                column = resolve_filter_column(frame, field)
                if column is not None:
                    mask = filter_mask(frame, definition, exclude=field)
                    values.update(frame.loc[mask, column].fillna('').astype(str).unique())
            options[field] = sorted(values, key=str.casefold)
        filtered_frames = {}
        for kind, frame in frames.items():
            # Adaptive facets keep their original CDR values. Once filtered,
            # normalise the snapshot only once so every chart on every slide
            # reuses it instead of copying millions of rows per render.
            filtered = normalise_report_operator_aliases(filter_frame(frame, definition))
            filtered.attrs['report_operator_aliases_normalized'] = True
            filtered_frames[kind] = filtered
        slides = OrderedDict()
        deck = Presentation(core.settings.ppt_templates_dir / 'Template_CDR_analysis.pptx')
        for editor_index, (index, entry) in enumerate(sorted(enumerate(entries), key=lambda item: (item[1].slide, item[0]))):
            slide = slides.setdefault(entry.slide, {'number': entry.slide, 'title': entry.slide_title, 'subtitle': entry.slide_subtitle, 'layout': entry.layout, 'charts': [], 'focus_row': editor_index})
            if not entry.structural_type:
                slide['charts'].append({'index': index, 'title': entry.chart_title, 'source': entry.source_kind, 'available': entry.source_kind in frames})
        for slide in slides.values():
            bounds = _layout_chart_frames(_named_slide_layout(deck, slide['layout']))
            if bounds and len(bounds) >= len(slide['charts']):
                left, top = min(b[0] for b in bounds), min(b[1] for b in bounds)
                width = max(b[0] + b[2] for b in bounds) - left
                height = max(b[1] + b[3] for b in bounds) - top
                for chart, (x, y, w, h) in zip(slide['charts'], bounds):
                    chart['position'] = [(x-left)/width*100, (y-top)/height*100, w/width*100, h/height*100]
        token = uuid4().hex
        with lock:
            snapshots[token] = Snapshot(workspace, user.username, entries, filtered_frames, definition.scope == 'multivendor')
            while len(snapshots) > 6:
                snapshots.popitem(last=False)
        return {'token': token, 'slides': list(slides.values()), 'options': options, 'filter_fields': list(ADAPTATIVE_FILTER_FIELDS), 'available_fields': sorted(available_fields, key=str.casefold), 'rows': {kind: len(frame) for kind, frame in filtered_frames.items()}}

    @app.post('/api/e2e-dashboards/prepare')
    def prepare(definition: DashboardDefinition, user=Depends(dashboard_user)):
        try:
            return build_preview(definition, user)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def snapshot_chart(token, index, user, *, include_frame=True):
        with lock:
            snapshot = snapshots.get(token)
        if snapshot is None or snapshot.workspace != workspace_key() or snapshot.owner != user.username:
            raise HTTPException(410, 'Dashboard preview expired. Refresh the Dashboard.')
        if index < 0 or index >= len(snapshot.entries):
            raise HTTPException(404, 'Chart not found.')
        entry = snapshot.entries[index]
        if not include_frame:
            return snapshot, entry, None
        frame = snapshot.frames.get(entry.source_kind)
        if frame is None:
            raise HTTPException(400, 'Unavailable source type: select a matching CDR dataset.')
        try:
            return snapshot, entry, prepare_catalog_chart_preview_frame(frame, entry, multivendor=snapshot.multivendor)[0]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get('/api/e2e-dashboards/preview/{token}/{index}.png')
    def chart(token: str, index: int, user=Depends(dashboard_user)):
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False)
        key = (token, index)
        # PIL chart renderers have no shared global canvas. Let browser image
        # requests for the same slide render concurrently instead of placing
        # every chart behind one process-wide lock; only cache mutation needs
        # synchronization.
        with lock:
            png = images.get(key)
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
        return Response(png, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})

    @app.get('/api/e2e-dashboards/data/{token}/{index}')
    def chart_data(token: str, index: int, page: int = 0, download: bool = False, user=Depends(dashboard_user)):
        _, _, frame = snapshot_chart(token, index, user)
        if download:
            return Response(frame.to_csv(index=False), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="dashboard-chart-data.csv"'})
        page = max(page, 0)
        visible = frame.iloc[page*100:(page+1)*100].fillna('').astype(str)
        return {'columns': list(visible.columns), 'rows': visible.values.tolist(), 'total': len(frame), 'page': page}
