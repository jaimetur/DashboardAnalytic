from __future__ import annotations

import json
import secrets
import hashlib
import warnings
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated
from typing import Any
from urllib.parse import urlencode

import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import QueryParams

from src.config import PROJECT_ROOT, settings
from src.modules.analytics import build_analysis
from src.modules.auth import SessionUser, verify_password
from src.modules.exports import POWERPOINT_EXPORT_VERSION, export_powerpoint_report, export_word_report
from src.modules.ingestion import infer_dataset_kind, load_dataset, summarise_dataset
from src.modules.repository import Repository
from src.version import __app_name__, __release_date__, __version__
from src.utils.filesystem import ensure_directories, safe_join


SESSION_COOKIE = 'bench_automations_session'
SESSIONS: dict[str, SessionUser] = {}
ANALYSIS_CACHE: dict[str, dict[str, Any]] = {}
DATAFRAME_CACHE: dict[str, pd.DataFrame] = {}
STOP_REQUESTS: set[int] = set()
STOP_REQUESTS_LOCK = Lock()
repository = Repository(settings.database_path)
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
    'generic': 'Other',
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_directories([
        settings.database_path.parent,
        settings.input_dir,
        settings.output_dir,
        settings.export_dir,
        settings.template_dir,
        settings.static_dir,
    ])
    repository.initialize(settings.admin_username, settings.admin_password)
    yield


app = FastAPI(title=__app_name__, version=__version__, lifespan=lifespan)
app.mount('/static', StaticFiles(directory=settings.static_dir), name='static')
templates = Jinja2Templates(directory=str(settings.template_dir))


def asset_version(relative_path: str) -> str:
    asset_path = settings.static_dir / relative_path
    if not asset_path.exists():
        return __version__
    return str(int(asset_path.stat().st_mtime))


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
    )
    if lowered in excluded_exact:
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
    item['available_metrics'] = parse_json_field(item.get('available_metrics_json'), [])
    item['available_aggregations'] = parse_json_field(item.get('available_aggregations_json'), [])
    item['filter_options'] = parse_json_field(item.get('filter_options_json'), {})
    item['summary'] = parse_json_field(item.get('summary_json'), {})
    item['kpis_snapshot'] = parse_json_field(item.get('kpis_json'), {})
    item['status_label'] = STATUS_LABELS.get(item.get('status') or 'queued', 'Queued')
    item['input_kind_label'] = INPUT_KIND_LABELS.get(item.get('dataset_kind') or 'generic', 'Other')
    item['progress'] = int(item.get('progress') or 0)
    item['is_ready'] = item.get('status') == 'ready'
    dataset_path = Path(item.get('stored_path') or '')
    size_bytes = dataset_path.stat().st_size if dataset_path.exists() else 0
    item['size_bytes'] = int(size_bytes)
    item['size_mb'] = round(size_bytes / (1024 * 1024), 2) if size_bytes else 0.0
    item['size_mb_label'] = f"{item['size_mb']:.2f} MB"
    return item


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
    return datetime.now(timezone.utc).isoformat()


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


def process_dataset(dataset_id: int, dataset_path: Path, username: str) -> None:
    if not repository.get_dataset(dataset_id) or not dataset_path.exists():
        clear_stop_request(dataset_id)
        return
    clear_stop_request(dataset_id)
    repository.update_dataset_profile(dataset_id, status='processing', progress=10, last_error=None)
    try:
        def progress_update(value: int) -> None:
            ensure_not_stopped(dataset_id)
            repository.update_dataset_profile(dataset_id, progress=max(10, min(95, int(value))))

        df = load_dataset(dataset_path, progress_callback=progress_update)
        store_cached_dataset_frame(dataset_path, df)
        repository.replace_dataset_rows(dataset_id, df)
        ensure_not_stopped(dataset_id)
        repository.update_dataset_profile(dataset_id, progress=62, dataset_kind=infer_dataset_kind(df, dataset_path.name))
        summary = summarise_dataset(df)
        ensure_not_stopped(dataset_id)
        repository.update_dataset_profile(dataset_id, progress=72)
        available_metrics = derive_available_metrics(df)
        analysis = build_analysis(df, {'aggregation': 'all', 'extra_filters': {}}, '')
        ensure_not_stopped(dataset_id)
        repository.update_dataset_profile(dataset_id, progress=84)
        profile_df = restrict_frame_to_metric(df, analysis.selected_metric)
        filter_options = derive_filter_options(profile_df)
        available_aggregations = derive_available_aggregations(filter_options)
        default_aggregation = analysis.filters.get('aggregation')
        if default_aggregation == 'all' and available_aggregations:
            default_aggregation = available_aggregations[0]
        repository.update_dataset_profile(dataset_id, progress=94)
        repository.update_dataset_profile(
            dataset_id,
            status='ready',
            progress=100,
            dataset_kind=df['dataset_kind'].iloc[0] if 'dataset_kind' in df.columns and not df.empty else infer_dataset_kind(df, dataset_path.name),
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
        repository.add_log(username, 'process_dataset', json.dumps({'dataset_id': dataset_id, 'file': dataset_path.name, 'status': 'ready'}))
    except ProcessingStopped as exc:
        progress = int((repository.get_dataset(dataset_id) or {}).get('progress') or 0)
        repository.update_dataset_profile(
            dataset_id,
            status='stopped',
            progress=max(0, min(99, progress)),
            last_error=str(exc),
            processed_at=now_iso(),
        )
        repository.add_log(username, 'stop_dataset', json.dumps({'dataset_id': dataset_id, 'file': dataset_path.name}))
    except Exception as exc:
        repository.update_dataset_profile(dataset_id, status='failed', progress=100, last_error=str(exc), processed_at=now_iso())
        repository.add_log(username, 'process_dataset_failed', json.dumps({'dataset_id': dataset_id, 'file': dataset_path.name, 'error': str(exc)}))
    finally:
        clear_stop_request(dataset_id)


def enqueue_dataset_processing(background_tasks: BackgroundTasks, dataset_id: int, dataset_path: Path, username: str) -> None:
    clear_stop_request(dataset_id)
    stale_keys = [key for key in ANALYSIS_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_keys:
        ANALYSIS_CACHE.pop(key, None)
    stale_dataset_keys = [key for key in DATAFRAME_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_dataset_keys:
        DATAFRAME_CACHE.pop(key, None)
    repository.update_dataset_profile(dataset_id, status='queued', progress=0, last_error=None, processed_at=None)
    background_tasks.add_task(process_dataset, dataset_id, dataset_path, username)


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


def admin_user(user: SessionUser = Depends(current_user)) -> SessionUser:
    if user.role != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin access required')
    return user


def render_template(request: Request, template_name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    payload = {
        'request': request,
        'app_name': __app_name__,
        'app_version': __version__,
        'app_release_date': __release_date__,
        'asset_version': asset_version,
        'static_path': lambda asset_path: str(request.app.url_path_for('static', path=asset_path)),
        **context,
    }
    return templates.TemplateResponse(request, template_name, payload, status_code=status_code)


def resolve_doc_path(doc_name: str) -> Path:
    normalized = str(doc_name or '').strip().lower()
    allowed = {
        'readme': 'README.md',
        'changelog': 'CHANGELOG.md',
    }
    relative_path = allowed.get(normalized)
    if not relative_path:
        raise HTTPException(status_code=404, detail='Document not found')
    target = (PROJECT_ROOT / relative_path).resolve()
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f'Document not found: {relative_path}')
    return target


def choose_selected_dataset(datasets: list[dict[str, Any]], dataset_id: int | None, input_kind: str | None) -> dict[str, Any] | None:
    ready_datasets = [dataset for dataset in datasets if dataset.get('is_ready')]
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


def build_dataset_view_state(dataset_id: int | None, input_kind: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any] | None]:
    datasets = [serialize_dataset_row(row) for row in repository.list_datasets()]
    ready_datasets = [dataset for dataset in datasets if dataset['is_ready']]
    input_kind_options = sorted({dataset.get('dataset_kind') or 'generic' for dataset in datasets})
    selected_dataset = choose_selected_dataset(datasets, dataset_id, input_kind)
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
    defaults = [
        {'username': settings.admin_username, 'password': settings.admin_password},
        {'username': 'demo', 'password': 'demo123'},
    ]
    available_accounts: list[dict[str, str]] = []
    for item in defaults:
        record = repository.get_user(item['username'])
        if record and record.active and verify_password(item['password'], record.password_hash):
            available_accounts.append(item)
    return available_accounts


def would_remove_last_active_admin(target_user, normalized_role: str, will_be_active: bool) -> bool:
    if target_user['role'] != 'admin' or not target_user['active']:
        return False
    if normalized_role == 'admin' and will_be_active:
        return False
    return repository.count_active_admin_users() <= 1


def render_admin_template(request: Request, user: SessionUser, error: str | None = None, status_code: int = 200) -> HTMLResponse:
    return render_template(
        request,
        'admin.html',
        {
            'user': user,
            'users': repository.list_users(),
            'datasets': repository.list_datasets(),
            'logs': repository.list_logs(),
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
        if log['action'] in {'stop_dataset', 'stop_dataset_requested'}:
            return f"Stop requested for dataset {details.get('dataset_id')}."
        if log['action'] == 'delete_dataset':
            return f"Dataset {details.get('dataset_id')} deleted."
        if log['action'] == 'analyze_dataset':
            return f"Analysis requested for dataset {details.get('dataset_id')}."
    return str(log.get('details_text') or log.get('details') or '')


def classify_workspace_log_entry(log: dict[str, Any]) -> str:
    if log.get('action') in {'process_dataset_failed', 'analyze_dataset_failed', 'analyze_dataset_warning'}:
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
    return render_template(request, 'login.html', {'error': None, 'default_access_accounts': build_default_access_accounts()})


@app.post('/login', response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)) -> Response:
    record = repository.get_user(username)
    if not record or not record.active or not verify_password(password, record.password_hash):
        return render_template(
            request,
            'login.html',
            {'error': 'Invalid credentials', 'default_access_accounts': build_default_access_accounts()},
            status_code=401,
        )

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
    if normalized not in {'readme', 'changelog'}:
        raise HTTPException(status_code=404, detail='Document not found')
    pretty_title = 'README.md' if normalized == 'readme' else 'CHANGELOG.md'
    return render_template(
        request,
        'doc_view.html',
        {
            'user': user,
            'doc_name': pretty_title,
            'doc_api_url': f'/api/documents/{normalized}',
        },
    )


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
    dataset_id: int | None = Query(default=None),
    input_kind: str | None = Query(default=None),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    datasets, ready_datasets, input_kind_options, selected_dataset = build_dataset_view_state(dataset_id, input_kind)
    has_processing = any(dataset['status'] in {'queued', 'processing'} for dataset in datasets)
    workspace_logs = repository.list_workspace_logs(selected_dataset['id'] if selected_dataset else None)
    for log in workspace_logs:
        log['summary'] = describe_workspace_log_entry(log)
        log['log_type'] = classify_workspace_log_entry(log)

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
        },
    )


@app.get('/dashboard', response_class=HTMLResponse)
def dashboard(
    request: Request,
    dataset_id: int | None = Query(default=None),
    input_kind: str | None = Query(default=None),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    datasets, ready_datasets, input_kind_options, selected_dataset = build_dataset_view_state(dataset_id, input_kind)
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


@app.get('/api/datasets/status')
def dataset_status(user: SessionUser = Depends(current_user)) -> dict[str, Any]:
    datasets = [serialize_dataset_row(row) for row in repository.list_datasets()]
    return {'datasets': datasets}


@app.post('/dashboard/upload', response_class=HTMLResponse)
async def upload_dataset(
    request: Request,
    background_tasks: BackgroundTasks,
    dataset_files: Annotated[list[UploadFile], File(...)],
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
                'workspace_logs': repository.list_workspace_logs(),
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
                'workspace_logs': repository.list_workspace_logs(),
                'input_kind_options': sorted({(dataset.get('dataset_kind') or 'generic') for dataset in datasets}),
                'input_kind': None,
                'has_processing': any(dataset['status'] in {'queued', 'processing'} for dataset in datasets),
                'error': f"Unsupported file type: {', '.join(invalid_extensions)}",
            },
            status_code=400,
        )
    queued_dataset_ids: list[int] = []
    for dataset_file in dataset_files:
        extension = Path(dataset_file.filename or '').suffix.lower()
        destination = safe_join(settings.input_dir, dataset_file.filename or f'upload{extension}')
        await save_upload_file(dataset_file, destination)
        dataset_id, created = repository.add_dataset(dataset_file.filename or destination.name, str(destination), user.username)
        repository.add_log(user.username, 'upload_dataset' if created else 'reprocess_dataset', destination.name)
        enqueue_dataset_processing(background_tasks, dataset_id, destination, user.username)
        queued_dataset_ids.append(dataset_id)

    if not queued_dataset_ids:
        return RedirectResponse('/workspace', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f'/workspace?dataset_id={queued_dataset_ids[0]}', status_code=status.HTTP_303_SEE_OTHER)


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
def delete_dataset(dataset_id: int, user: SessionUser = Depends(current_user)) -> Response:
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
    stale_keys = [key for key in ANALYSIS_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_keys:
        ANALYSIS_CACHE.pop(key, None)
    stale_dataset_keys = [key for key in DATAFRAME_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_dataset_keys:
        DATAFRAME_CACHE.pop(key, None)
    repository.add_log(user.username, 'delete_dataset', json.dumps({'dataset_id': dataset_id, 'file': deleted['file_name']}))
    return RedirectResponse('/workspace', status_code=status.HTTP_303_SEE_OTHER)


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


@app.post('/admin/users', response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    try:
        repository.create_user(username, password, role)
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
    user: SessionUser = Depends(admin_user),
) -> Response:
    normalized_username = username.strip()
    normalized_role = role.strip().lower()
    if not normalized_username:
        return render_admin_template(request, user, error='Username cannot be empty', status_code=400)
    if normalized_role not in {'admin', 'user'}:
        return render_admin_template(request, user, error='Unsupported role', status_code=400)
    target_user = repository.get_user_by_id(target_user_id)
    if not target_user:
        return render_admin_template(request, user, error='User not found', status_code=404)
    will_be_active = active == '1'
    if would_remove_last_active_admin(target_user, normalized_role, will_be_active):
        return render_admin_template(
            request,
            user,
            error='At least one active admin user must remain. You cannot demote or deactivate the last active admin.',
            status_code=400,
        )
    try:
        repository.update_user(
            target_user_id,
            normalized_username,
            normalized_role,
            will_be_active,
            password.strip() or None,
        )
        repository.add_log(
            user.username,
            'update_user',
            json.dumps({'user_id': target_user_id, 'username': normalized_username, 'role': normalized_role, 'active': will_be_active}),
        )
        return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        return render_admin_template(request, user, error=str(exc), status_code=400)


@app.post('/admin/users/{target_user_id}/delete', response_class=HTMLResponse)
def delete_user_account(
    request: Request,
    target_user_id: int,
    user: SessionUser = Depends(admin_user),
) -> Response:
    target_user = repository.get_user_by_id(target_user_id)
    if not target_user:
        return render_admin_template(request, user, error='User not found', status_code=404)
    if target_user['username'] == user.username:
        return render_admin_template(request, user, error='You cannot delete the current signed-in admin user', status_code=400)
    if target_user['role'] == 'admin' and target_user['active'] and repository.count_active_admin_users() <= 1:
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


templates.env.globals['format_extra_filters'] = format_extra_filters
templates.env.globals['format_aggregation_overrides'] = format_aggregation_overrides
templates.env.globals['format_cdf_overrides'] = format_cdf_overrides
templates.env.globals['format_aggregation_label'] = format_aggregation_label
