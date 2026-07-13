from __future__ import annotations

import json
import secrets
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

from src.config import PROJECT_ROOT, settings
from src.modules.analytics import build_analysis
from src.modules.auth import SessionUser, verify_password
from src.modules.exports import export_powerpoint_report, export_word_report
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
FILTER_DIMENSIONS = ['market', 'period', 'operator', 'region', 'vendor', 'session_type', 'test_name', 'direction', 'technology_primary', 'source_sheet']
FILTER_DIMENSIONS_BY_KIND = {
    'voice': ['market', 'period', 'operator', 'region', 'vendor', 'session_type', 'technology_primary', 'source_sheet'],
    'speech': ['market', 'period', 'operator', 'region', 'vendor', 'session_type', 'technology_primary', 'source_sheet'],
    'data': ['market', 'period', 'operator', 'region', 'vendor', 'test_name', 'direction', 'technology_primary', 'source_sheet'],
    'generic': ['market', 'period', 'operator', 'region', 'vendor', 'source_sheet'],
}
ANALYSIS_SUPPORT_COLUMNS = [
    'dataset_kind', 'source_file', 'market', 'period', 'operator', 'region', 'vendor', 'session_type', 'test_name',
    'direction', 'technology_primary', 'source_sheet', 'status', 'success', 'failure', 'dropped', 'disturbed',
    'impaired', 'setup_time_seconds', 'duration_seconds', 'throughput_mbps', 'quality_score', 'latency_ms',
    'jitter_ms', 'packet_loss_pct', 'handovers', 'POLQA_LQ_Avg', 'LQ', 'Receive_Delay', 'Mean_Data_Rate',
    'TCP_RTT_Service_Access_Delay', 'DNS_Resolution_Success_Ratio', 'DNS_Resolution_Success',
    'DNS_Resolution_Attempts', 'VideoStream_Freezing_Time_Sum', 'Call_Setup_Time', 'Call_Duration',
    'TCP_Throughput', 'Test_Duration', 'Playing_Technology', 'Type_of_Test',
]
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


def parse_extra_filters(raw_filters: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    for chunk in raw_filters.split(';'):
        entry = chunk.strip()
        if not entry or '=' not in entry:
            continue
        key, value = entry.split('=', 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            filters[key] = value
    return filters


def format_extra_filters(filters: dict[str, Any] | None) -> str:
    if not filters:
        return ''
    return '; '.join(f'{key}={value}' for key, value in filters.items())


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


def derive_available_metrics(df) -> list[str]:
    preferred = [
        'POLQA_LQ_Avg', 'LQ', 'Mean_Data_Rate', 'quality_score', 'throughput_mbps', 'setup_time_seconds', 'duration_seconds',
        'jitter_ms', 'packet_loss_pct', 'latency_ms', 'Call_Setup_Time', 'Call_Duration', 'Receive_Delay', 'TCP_RTT_Service_Access_Delay',
    ]
    numeric_columns = df.select_dtypes(include=['number']).columns.tolist()
    ordered = [column for column in preferred if column in numeric_columns]
    ordered.extend(column for column in numeric_columns if column not in ordered and not str(column).startswith('_'))
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
    return item


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
    dataset = repository.get_dataset(dataset_id)
    if dataset and (dataset['status'] or '') == 'stopped':
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


def build_analysis_query_columns(selected_dataset: dict[str, Any], selected_metrics: list[str]) -> list[str]:
    requested = set(ANALYSIS_SUPPORT_COLUMNS)
    requested.update(selected_metrics)
    return sorted(requested)


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
    filtered_datasets = [dataset for dataset in ready_datasets if not input_kind or dataset.get('dataset_kind') == input_kind]
    candidate_datasets = filtered_datasets or ready_datasets
    if dataset_id is not None:
        for dataset in candidate_datasets:
            if dataset['id'] == dataset_id:
                return dataset
    return candidate_datasets[0] if candidate_datasets else None


def choose_filter_value(query_value: str | None, options: dict[str, list[str]], key: str) -> str | None:
    values = options.get(key, [])
    if query_value and query_value in values:
        return query_value
    if len(values) == 1:
        return values[0]
    return None


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


def build_dashboard_payload(selected_dataset: dict[str, Any] | None, request: Request) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str], dict[str, Any], str | None, bool]:
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
    selected_metrics = [metric for metric in requested_metrics if metric in available_metrics]
    if not selected_metrics:
        default_metric = selected_dataset.get('default_metric') or (available_metrics[0] if available_metrics else '')
        selected_metrics = [default_metric] if default_metric else []
    filters = {
        'market': choose_filter_value(request.query_params.get('market'), filter_options, 'market'),
        'period': choose_filter_value(request.query_params.get('period'), filter_options, 'period'),
        'aggregation': aggregation,
        'extra_filters': {},
    }
    for dimension in FILTER_DIMENSIONS:
        if dimension in {'market', 'period'}:
            continue
        selected_value = request.query_params.get(dimension)
        if selected_value and selected_value in filter_options.get(dimension, []):
            filters['extra_filters'][dimension] = selected_value

    query_columns = build_analysis_query_columns(selected_dataset, selected_metrics)
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
            analysis = get_cached_analysis(dataset_path, filters, metric)
            if analysis is None:
                analysis = store_cached_analysis(dataset_path, filters, metric, build_analysis(df, filters, metric))
            analyses.append({'metric': metric, 'result': analysis})
        except ValueError as exc:
            if analyses:
                continue
            return None, [], selected_metrics, filter_options, str(exc), False

    primary_analysis = analyses[0]['result'] if analyses else None
    resolved_metrics = [entry['result'].selected_metric for entry in analyses]
    return primary_analysis, analyses, resolved_metrics, filter_options, None, True


@app.get('/healthz')
def healthz() -> dict[str, str]:
    return {'status': 'ok', 'version': __version__}


@app.get('/', response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if request.cookies.get(SESSION_COOKIE) in SESSIONS:
        return RedirectResponse('/dashboard', status_code=status.HTTP_303_SEE_OTHER)
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
    response = RedirectResponse('/dashboard', status_code=status.HTTP_303_SEE_OTHER)
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


@app.get('/dashboard', response_class=HTMLResponse)
def dashboard(
    request: Request,
    dataset_id: int | None = Query(default=None),
    input_kind: str | None = Query(default=None),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    datasets = [serialize_dataset_row(row) for row in repository.list_datasets()]
    ready_datasets = [dataset for dataset in datasets if dataset['is_ready']]
    input_kind_options = sorted({dataset.get('dataset_kind') or 'generic' for dataset in datasets})
    selected_dataset = choose_selected_dataset(datasets, dataset_id, input_kind)
    analysis, analyses, selected_metrics, filter_options, analysis_error, analysis_loaded = build_dashboard_payload(selected_dataset, request)
    has_processing = any(dataset['status'] in {'queued', 'processing'} for dataset in datasets)

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
            'filter_options': filter_options,
            'input_kind': input_kind,
            'input_kind_options': input_kind_options,
            'filter_dimensions': [
                dimension for dimension in FILTER_DIMENSIONS_BY_KIND.get((selected_dataset or {}).get('dataset_kind') or 'generic', FILTER_DIMENSIONS)
                if filter_options.get(dimension)
            ],
            'error': analysis_error,
            'has_processing': has_processing,
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
        return render_template(
            request,
            'dashboard.html',
            {
                'user': user,
                'datasets': [serialize_dataset_row(row) for row in repository.list_datasets()],
                'selected_dataset': None,
                'analysis': None,
                'filter_options': {},
                'filter_dimensions': [],
                'input_kind_options': sorted({(serialize_dataset_row(row).get('dataset_kind') or 'generic') for row in repository.list_datasets()}),
                'input_kind': None,
                'has_processing': any(serialize_dataset_row(row)['status'] in {'queued', 'processing'} for row in repository.list_datasets()),
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
        return render_template(
            request,
            'dashboard.html',
            {
                'user': user,
                'datasets': [serialize_dataset_row(row) for row in repository.list_datasets()],
                'selected_dataset': None,
                'analysis': None,
                'filter_options': {},
                'filter_dimensions': [],
                'input_kind_options': sorted({(serialize_dataset_row(row).get('dataset_kind') or 'generic') for row in repository.list_datasets()}),
                'input_kind': None,
                'has_processing': any(serialize_dataset_row(row)['status'] in {'queued', 'processing'} for row in repository.list_datasets()),
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
        return RedirectResponse('/dashboard', status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f'/dashboard?dataset_id={queued_dataset_ids[0]}', status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(f'/dashboard?dataset_id={dataset_id}', status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(f'/dashboard?dataset_id={dataset_id}', status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse('/dashboard', status_code=status.HTTP_303_SEE_OTHER)


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
    metric: str = Form(''),
    market: str = Form(''),
    period: str = Form(''),
    aggregation: str = Form('all'),
    extra_filters: str = Form(''),
    user: SessionUser = Depends(current_user),
) -> FileResponse:
    if export_kind not in {'word', 'powerpoint'}:
        raise HTTPException(status_code=404, detail='Unsupported export type')

    dataset = repository.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail='Dataset not found')
    selected_dataset = serialize_dataset_row(dataset)
    filters = {
        'market': market or None,
        'period': period or None,
        'aggregation': aggregation or 'all',
        'extra_filters': parse_extra_filters(extra_filters),
    }
    dataset_path = Path(selected_dataset['stored_path'])
    analysis = get_cached_analysis(dataset_path, filters, metric)
    if analysis is None:
        analysis = store_cached_analysis(dataset_path, filters, metric, build_analysis(load_cached_dataset(dataset_path), filters, metric))
    file_stem = Path(selected_dataset['stored_path']).stem

    if export_kind == 'word':
        destination = safe_join(settings.export_dir, f'{file_stem}_report.docx')
        export_word_report(destination, asdict(analysis))
        media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    else:
        destination = safe_join(settings.export_dir, f'{file_stem}_report.pptx')
        export_powerpoint_report(destination, asdict(analysis))
        media_type = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

    repository.add_log(user.username, f'export_{export_kind}', destination.name)
    return FileResponse(destination, filename=destination.name, media_type=media_type)


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
