"""Workspace dashboard definitions and shared-table, template-driven previews."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from threading import RLock, Thread
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
DASHBOARD_RENDER_CACHE_VERSION = 1
DASHBOARD_SELECTION_ROW_LIMIT = 25_000
DASHBOARD_PROFILE_SELECTION_THRESHOLD = 100_000
DASHBOARD_PROJECTION_CACHE_VERSION = 1
DASHBOARD_PROJECTION_DISK_LIMIT = 6
DASHBOARD_CHART_MODEL_CACHE_VERSION = 3
DASHBOARD_CHART_MODEL_DISK_LIMIT = 500


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
    chart_frames: dict[int, pd.DataFrame] = field(default_factory=dict)
    filtered_frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    chart_payloads: dict[int, dict[str, object]] = field(default_factory=dict)
    frame_locks: dict[str, RLock] = field(default_factory=dict)
    projections: dict[str, tuple[Path, str, list[str]]] = field(default_factory=dict)


def install_dashboard_routes(core):
    app = core.app
    lock = RLock()
    snapshots = OrderedDict()
    images = OrderedDict()
    projection_load_locks: dict[str, RLock] = {}
    warming_workspaces: set[str] = set()

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
        schedule_dashboard_warmup(task_repository.db_path, (definition.model_copy(deep=True),))
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
            clauses.append(f"COALESCE(CAST({quote(column)} AS TEXT), '') IN ({value_placeholders})")
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
            'scope': definition.scope,
            'datasets': definition.datasets,
            'filters': definition.filters,
            'custom_fields': definition.custom_fields,
            'hidden_filters': definition.hidden_filters,
            'date_from': definition.date_from,
            'date_to': definition.date_to,
        }
        payload = {
            'schema': 1,
            'definition': selection_definition,
            'versions': versions,
            'combined_revisions': revisions,
            'dimensions': core.calculated_dimensions_json(dimensions),
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def profile_filter_options(definition, dimensions, selected_by_kind, fields, connection):
        """Resolve large-dashboard facets without scanning wide combined CDR tables."""
        options = {field_name: set() for field_name in fields}
        for selected in selected_by_kind.values():
            for dataset in selected:
                stored = dataset.get('filter_options')
                if not isinstance(stored, dict):
                    try:
                        stored = json.loads(dataset.get('filter_options_json') or '{}')
                    except (TypeError, json.JSONDecodeError):
                        stored = {}
                stored_lookup = {identity(column): values for column, values in stored.items()}
                for field_name in fields:
                    aliases = next(
                        (values for label, values in FILTER_COLUMNS.items() if identity(label) == identity(field_name)),
                        (field_name,),
                    )
                    for alias in aliases:
                        values = stored_lookup.get(identity(alias), ())
                        if isinstance(values, list):
                            options[field_name].update(str(value) for value in values if value is not None)

        # Auto-calculated fields have a finite result domain in their rules,
        # so their filter values are available immediately from the saved
        # definitions even before any CDR rows are loaded.
        dimension_lookup = {identity(dimension.name): dimension for dimension in dimensions}
        for field_name in fields:
            dimension = dimension_lookup.get(identity(field_name))
            if not dimension:
                continue
            options[field_name].update(
                str(rule.value) for rule in dimension.rules if str(rule.value).strip()
            )
            if str(dimension.default).strip():
                options[field_name].add(str(dimension.default))

        # Older processed datasets may not yet have RAT or an arbitrary field
        # in their profile. Reuse a previously persisted value catalogue when
        # available instead of reopening the combined table.
        missing = {field_name for field_name, values in options.items() if not values}
        if missing:
            rows = connection.execute(
                'SELECT options_json FROM dashboard_filter_selections '
                'ORDER BY last_accessed_at DESC, id DESC LIMIT 8'
            ).fetchall()
            for row in rows:
                try:
                    cached_options = json.loads(row['options_json'] or '{}')
                except (TypeError, json.JSONDecodeError):
                    continue
                cached_lookup = {identity(column): values for column, values in cached_options.items()}
                for field_name in tuple(missing):
                    values = cached_lookup.get(identity(field_name), ())
                    if isinstance(values, list):
                        options[field_name].update(str(value) for value in values if value is not None)
                    if options[field_name]:
                        missing.discard(field_name)

        for field_name, selected_values in definition.filters.items():
            matching = next((field for field in fields if identity(field) == identity(field_name)), None)
            if matching:
                options[matching].update(str(value) for value in selected_values)
        return {
            field_name: sorted(values, key=str.casefold)
            for field_name, values in options.items()
        }

    def materialize_selection(definition, task_repository, dimensions, selected_by_kind, fields):
        cache_key = persistent_selection_key(definition, task_repository, dimensions, selected_by_kind)
        estimated_rows = {
            kind: sum(int(row.get('row_count') or 0) for row in selected)
            for kind, selected in selected_by_kind.items()
        }
        profile_only = sum(estimated_rows.values()) > DASHBOARD_PROFILE_SELECTION_THRESHOLD
        with lock, task_repository.connection() as connection:
            cached = connection.execute(
                'SELECT id, options_json, row_counts_json, materialized FROM dashboard_filter_selections WHERE cache_key = ?',
                (cache_key,),
            ).fetchone()
            if cached:
                connection.execute('UPDATE dashboard_filter_selections SET last_accessed_at = CURRENT_TIMESTAMP WHERE id = ?', (cached['id'],))
                return (
                    int(cached['id']), cache_key, bool(cached['materialized']),
                    json.loads(cached['options_json']), json.loads(cached['row_counts_json']), not profile_only,
                )
            cursor = connection.execute('INSERT INTO dashboard_filter_selections (cache_key) VALUES (?)', (cache_key,))
            selection_id = int(cursor.lastrowid)
            if profile_only:
                options = profile_filter_options(definition, dimensions, selected_by_kind, fields, connection)
                connection.execute(
                    'UPDATE dashboard_filter_selections SET options_json = ?, row_counts_json = ?, materialized = 0 WHERE id = ?',
                    (json.dumps(options), json.dumps(estimated_rows), selection_id),
                )
                stale = connection.execute(
                    'SELECT id FROM dashboard_filter_selections ORDER BY last_accessed_at DESC, id DESC LIMIT -1 OFFSET 8'
                ).fetchall()
                for row in stale:
                    connection.execute('DELETE FROM dashboard_filter_selection_rows WHERE selection_id = ?', (row['id'],))
                    connection.execute('DELETE FROM dashboard_filter_selections WHERE id = ?', (row['id'],))
                return selection_id, cache_key, False, options, estimated_rows, False
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
            # Most Dashboard openings have no active categorical filter.  The
            # former implementation scanned a combined CDR table once per
            # facet in that case.  Aggregate all facets sharing a predicate in
            # one pass, keeping individual passes only for selected facets
            # whose own filter must be excluded from their available values.
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

    def build_preview(definition, user):
        workspace = workspace_key()
        task_repository = Repository(Path(workspace), core.repository.global_db_path)
        entries = validate(definition, task_repository)
        dimensions = core.load_repository_calculated_dimensions(task_repository)
        selected_by_kind = selected_sources(definition, task_repository)
        ensure_filter_projection(definition, task_repository, dimensions, selected_by_kind, entries)
        selected_dataset_ids = {dataset_id for ids in definition.datasets.values() for dataset_id in ids}
        available_fields = {column for dataset_id in selected_dataset_ids for column in task_repository.list_dataset_row_columns(dataset_id)}
        available_fields.update(dimension.name for dimension in dimensions)
        hidden_filter_keys = {identity(field) for field in definition.hidden_filters}
        fields = {field for field in ADAPTATIVE_FILTER_FIELDS if identity(field) not in hidden_filter_keys}
        fields.update(definition.custom_fields)
        fields = sorted(fields, key=str.casefold)
        selection_id, selection_key, selection_materialized, options, row_counts, rows_exact = materialize_selection(
            definition, task_repository, dimensions, selected_by_kind, fields,
        )
        slides = OrderedDict()
        deck = Presentation(core.settings.ppt_templates_dir / 'Template_CDR_analysis.pptx')
        for editor_index, (index, entry) in enumerate(sorted(enumerate(entries), key=lambda item: (item[1].slide, item[0]))):
            slide = slides.setdefault(entry.slide, {'number': entry.slide, 'title': entry.slide_title, 'subtitle': entry.slide_subtitle, 'layout': entry.layout, 'charts': [], 'focus_row': editor_index})
            if not entry.structural_type:
                slide['charts'].append({'index': index, 'title': entry.chart_title, 'source': entry.source_kind, 'available': entry.source_kind in selected_by_kind})
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
        }
        with lock:
            snapshots[token] = Snapshot(
                workspace, user.username, entries, {}, definition.scope == 'multivendor',
                definition.model_copy(deep=True), tuple(dimensions), selection_id, selection_key, selection_materialized,
            )
            while len(snapshots) > 3:
                snapshots.popitem(last=False)
        return {**payload, 'token': token}

    @app.post('/api/e2e-dashboards/prepare')
    def prepare(definition: DashboardDefinition, user=Depends(dashboard_user)):
        try:
            return build_preview(definition, user)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

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
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute('PRAGMA temp_store=FILE')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS projection_cache ('
            'cache_key TEXT PRIMARY KEY, dataset_kind TEXT NOT NULL, table_name TEXT NOT NULL UNIQUE, '
            'created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, last_accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'
        )
        return connection

    def ensure_projection(snapshot, kind, task_repository):
        with lock:
            existing = snapshot.projections.get(kind)
        if existing is not None:
            return existing
        selected, requested_columns, cache_key = source_spec(snapshot, kind, task_repository)
        with lock:
            projection_lock = projection_load_locks.setdefault(cache_key, RLock())
        with projection_lock:
            with lock:
                existing = snapshot.projections.get(kind)
            if existing is not None:
                return existing
            cache_dir = Path(snapshot.workspace).parent / '.dashboard-data-cache'
            cache_dir.mkdir(parents=True, exist_ok=True)
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
                connection.execute('BEGIN IMMEDIATE')
                found = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,),
                ).fetchone()
                if not found:
                    dataset_ids = [int(row['id']) for row in selected]
                    placeholders = ', '.join('?' for _ in dataset_ids)
                    select_clause = ', '.join(
                        task_repository._quote_identifier(column) for column in projected_columns
                    )
                    connection.execute(
                        f'CREATE TABLE {task_repository._quote_identifier(temporary)} AS '
                        f'SELECT {select_clause} FROM workspace_source.'
                        f'{task_repository._quote_identifier(task_repository.reporting_rows_table_name(kind))} '
                        f'WHERE dataset_id IN ({placeholders})',
                        dataset_ids,
                    )
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
                for indexed_column in indexed_columns:
                    index_name = f'idx_{table_name}_{sha256(indexed_column.encode()).hexdigest()[:8]}'
                    connection.execute(
                        f'CREATE INDEX IF NOT EXISTS {task_repository._quote_identifier(index_name)} '
                        f'ON {task_repository._quote_identifier(table_name)} '
                        f'({task_repository._quote_identifier(indexed_column)})'
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
                    connection.execute(
                        f'DROP TABLE IF EXISTS {task_repository._quote_identifier(stale_projection["table_name"])}'
                    )
                    connection.execute('DELETE FROM projection_cache WHERE cache_key = ?', (stale_projection['cache_key'],))
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

    def load_projection_frame(cache_path, table_name, projection_columns, requested_columns, where, parameters):
        lookup = {identity(column): column for column in projection_columns}
        selected_columns = []
        for requested in requested_columns:
            actual = lookup.get(identity(requested))
            if actual and actual not in selected_columns:
                selected_columns.append(actual)
        if not selected_columns:
            return pd.DataFrame()
        quote = lambda column: '"' + str(column).replace('"', '""') + '"'
        query = f'SELECT {", ".join(quote(column) for column in selected_columns)} FROM {quote(table_name)} WHERE {where}'
        connection = sqlite3.connect(cache_path, timeout=120.0)
        try:
            return pd.read_sql_query(query, connection, params=parameters)
        finally:
            connection.close()

    def schedule_dashboard_warmup(workspace_path, definitions=None):
        """Build narrow analytical projections without delaying the calling request."""
        resolved_workspace = str(Path(workspace_path).resolve())
        with lock:
            if resolved_workspace in warming_workspaces:
                return
            warming_workspaces.add(resolved_workspace)

        def warm():
            try:
                task_repository = Repository(Path(resolved_workspace), core.repository.global_db_path)
                items = list(definitions or ())
                if not items:
                    try:
                        stored = task_repository.get_workspace_state(STATE_KEY)
                        if stored is None:
                            stored = task_repository.get_workspace_state(LEGACY_STATE_KEY) or '{}'
                        items = [
                            DashboardDefinition.model_validate(item)
                            for item in json.loads(stored or '{}').values()
                        ]
                    except (json.JSONDecodeError, TypeError, ValueError):
                        items = []
                for definition in items:
                    try:
                        entries = validate(definition, task_repository)
                        dimensions = core.load_repository_calculated_dimensions(task_repository)
                        selected_by_kind = selected_sources(definition, task_repository)
                        ensure_filter_projection(definition, task_repository, dimensions, selected_by_kind, entries)
                        snapshot = Snapshot(
                            resolved_workspace, 'system', entries, {}, definition.scope == 'multivendor',
                            definition, tuple(dimensions), 0, '', False,
                        )
                        for kind in selected_by_kind:
                            ensure_projection(snapshot, kind, task_repository)
                    except (HTTPException, KeyError, OSError, sqlite3.Error, TypeError, ValueError):
                        continue
            finally:
                with lock:
                    warming_workspaces.discard(resolved_workspace)

        Thread(
            target=warm,
            name=f'dashboard-warmup-{sha256(resolved_workspace.encode()).hexdigest()[:8]}',
            daemon=True,
        ).start()

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
            raw_key = sha256(json.dumps({
                'kind': entry.source_kind, 'columns': requested_columns, 'where': where, 'parameters': parameters,
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
                            )[0]
                        except ValueError as exc:
                            raise HTTPException(400, str(exc)) from exc
                        with lock:
                            prepared_frame = snapshot.filtered_frames.setdefault(filtered_key, prepared_frame)
            with lock:
                frame = snapshot.chart_frames.setdefault(index, prepared_frame)
        return snapshot, entry, frame

    @app.get('/api/e2e-dashboards/chart/{token}/{index}')
    def interactive_chart(token: str, index: int, user=Depends(dashboard_user)):
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False)
        with lock:
            payload = snapshot.chart_payloads.get(index)
        model_dir = Path(snapshot.workspace).parent / '.dashboard-data-cache' / 'charts'
        entry_key = sha256(repr(entry).encode()).hexdigest()
        model_path = model_dir / sha256(
            f'{DASHBOARD_CHART_MODEL_CACHE_VERSION}:{snapshot.selection_key}:{entry_key}'.encode()
        ).hexdigest()
        model_path = model_path.with_suffix('.json')
        if payload is None and model_path.is_file():
            try:
                payload = json.loads(model_path.read_text(encoding='utf-8'))
                model_path.touch()
            except (OSError, json.JSONDecodeError):
                model_path.unlink(missing_ok=True)
                payload = None
        if payload is None:
            snapshot, entry, frame = snapshot_chart(token, index, user)
            payload = catalog_chart_payload(
                frame, entry, multivendor=snapshot.multivendor, prefiltered=True,
            )
            with lock:
                payload = snapshot.chart_payloads.setdefault(index, payload)
            try:
                model_dir.mkdir(parents=True, exist_ok=True)
                temporary = model_path.with_suffix(f'.{uuid4().hex}.tmp')
                temporary.write_text(json.dumps(payload, separators=(',', ':')), encoding='utf-8')
                temporary.replace(model_path)
                cached_models = sorted(model_dir.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)
                for stale in cached_models[DASHBOARD_CHART_MODEL_DISK_LIMIT:]:
                    stale.unlink(missing_ok=True)
            except OSError:
                pass
        with lock:
            snapshot.chart_payloads.setdefault(index, payload)
        return JSONResponse(payload, headers={'Cache-Control': 'private, max-age=3600'})

    @app.get('/api/e2e-dashboards/preview/{token}/{index}.png')
    def chart(token: str, index: int, user=Depends(dashboard_user)):
        snapshot, entry, _ = snapshot_chart(token, index, user, include_frame=False)
        entry_key = sha256(repr(entry).encode()).hexdigest()
        key = (snapshot.selection_key, entry_key)
        cache_dir = Path(snapshot.workspace).parent / '.dashboard-chart-cache'
        cache_path = cache_dir / sha256(
            f'{DASHBOARD_RENDER_CACHE_VERSION}:{snapshot.selection_key}:{entry_key}'.encode()
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

    core.schedule_e2e_dashboard_warmup = schedule_dashboard_warmup
