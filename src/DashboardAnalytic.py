from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
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
repository = Repository(settings.database_path)
FILTER_DIMENSIONS = ['market', 'period', 'operator', 'region', 'vendor', 'session_type', 'test_name', 'direction', 'technology_primary', 'source_sheet']
FILTER_DIMENSIONS_BY_KIND = {
    'voice': ['market', 'period', 'operator', 'region', 'vendor', 'session_type', 'technology_primary', 'source_sheet'],
    'speech': ['market', 'period', 'operator', 'region', 'vendor', 'session_type', 'technology_primary', 'source_sheet'],
    'data': ['market', 'period', 'operator', 'region', 'vendor', 'test_name', 'direction', 'technology_primary', 'source_sheet'],
    'generic': ['market', 'period', 'operator', 'region', 'vendor', 'source_sheet'],
}
STATUS_LABELS = {
    'queued': 'Queued',
    'processing': 'Processing',
    'ready': 'Processed',
    'failed': 'Failed',
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


def get_cached_analysis(dataset_path: Path, filters: dict[str, Any], metric: str) -> dict[str, Any] | None:
    return ANALYSIS_CACHE.get(build_analysis_cache_key(dataset_path, filters, metric))


def store_cached_analysis(dataset_path: Path, filters: dict[str, Any], metric: str, analysis: Any) -> Any:
    ANALYSIS_CACHE[build_analysis_cache_key(dataset_path, filters, metric)] = analysis
    if len(ANALYSIS_CACHE) > 64:
        oldest_key = next(iter(ANALYSIS_CACHE))
        ANALYSIS_CACHE.pop(oldest_key, None)
    return analysis


def process_dataset(dataset_id: int, dataset_path: Path, username: str) -> None:
    repository.update_dataset_profile(dataset_id, status='processing', progress=10, last_error=None)
    try:
        df = load_dataset(dataset_path)
        repository.update_dataset_profile(dataset_id, progress=45, dataset_kind=infer_dataset_kind(df, dataset_path.name))
        summary = summarise_dataset(df)
        available_metrics = derive_available_metrics(df)
        analysis = build_analysis(df, {'aggregation': 'all', 'extra_filters': {}}, '')
        profile_df = restrict_frame_to_metric(df, analysis.selected_metric)
        filter_options = derive_filter_options(profile_df)
        available_aggregations = derive_available_aggregations(filter_options)
        default_aggregation = analysis.filters.get('aggregation')
        if default_aggregation == 'all' and available_aggregations:
            default_aggregation = available_aggregations[0]
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
    except Exception as exc:
        repository.update_dataset_profile(dataset_id, status='failed', progress=100, last_error=str(exc), processed_at=now_iso())
        repository.add_log(username, 'process_dataset_failed', json.dumps({'dataset_id': dataset_id, 'file': dataset_path.name, 'error': str(exc)}))


def enqueue_dataset_processing(background_tasks: BackgroundTasks, dataset_id: int, dataset_path: Path, username: str) -> None:
    stale_keys = [key for key in ANALYSIS_CACHE if str(dataset_path.resolve()) in key]
    for key in stale_keys:
        ANALYSIS_CACHE.pop(key, None)
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
    filtered_datasets = [dataset for dataset in datasets if not input_kind or dataset.get('dataset_kind') == input_kind]
    candidate_datasets = filtered_datasets or datasets
    if dataset_id is not None:
        for dataset in candidate_datasets:
            if dataset['id'] == dataset_id:
                return dataset
    for dataset in candidate_datasets:
        if dataset['is_ready']:
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


def build_dashboard_payload(selected_dataset: dict[str, Any] | None, request: Request) -> tuple[dict[str, Any] | None, dict[str, Any], str | None, bool]:
    if not selected_dataset:
        return None, {}, None, False
    if not selected_dataset['is_ready']:
        return None, {}, 'The selected dataset has not finished processing yet.' if selected_dataset.get('status') != 'failed' else selected_dataset.get('last_error'), False

    filter_options = selected_dataset.get('filter_options') or {}
    filter_options = {'input_kind': [selected_dataset.get('dataset_kind') or 'generic'], **filter_options}
    if not should_load_analysis(request):
        return None, filter_options, None, False

    dataset_path = Path(selected_dataset['stored_path'])
    metric = request.query_params.get('metric') or selected_dataset.get('default_metric') or ''
    aggregation = request.query_params.get('aggregation') or selected_dataset.get('default_aggregation') or 'all'
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

    analysis = get_cached_analysis(dataset_path, filters, metric)
    if analysis is None:
        df = load_dataset(dataset_path)
        analysis = store_cached_analysis(dataset_path, filters, metric, build_analysis(df, filters, metric))
    return analysis, filter_options, None, True


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
    return render_template(request, 'login.html', {'error': None})


@app.post('/login', response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)) -> Response:
    record = repository.get_user(username)
    if not record or not record.active or not verify_password(password, record.password_hash):
        return render_template(request, 'login.html', {'error': 'Invalid credentials'}, status_code=401)

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
    input_kind_options = sorted({dataset.get('dataset_kind') or 'generic' for dataset in datasets})
    selected_dataset = choose_selected_dataset(datasets, dataset_id, input_kind)
    analysis, filter_options, analysis_error, analysis_loaded = build_dashboard_payload(selected_dataset, request)
    has_processing = any(dataset['status'] in {'queued', 'processing'} for dataset in datasets)

    return render_template(
        request,
        'dashboard.html',
        {
            'user': user,
            'datasets': datasets,
            'selected_dataset': selected_dataset,
            'analysis': analysis,
            'analysis_loaded': analysis_loaded,
            'filter_options': filter_options,
            'input_kind': input_kind or ((selected_dataset or {}).get('dataset_kind') if selected_dataset else None),
            'input_kind_options': input_kind_options,
            'filter_dimensions': [
                dimension for dimension in FILTER_DIMENSIONS_BY_KIND.get((selected_dataset or {}).get('dataset_kind') or 'generic', FILTER_DIMENSIONS)
                if filter_options.get(dimension)
            ],
            'error': analysis_error,
            'has_processing': has_processing,
        },
    )

@app.post('/dashboard/upload', response_class=HTMLResponse)
async def upload_dataset(
    request: Request,
    background_tasks: BackgroundTasks,
    dataset_file: UploadFile = File(...),
    user: SessionUser = Depends(current_user),
) -> Response:
    extension = Path(dataset_file.filename or '').suffix.lower()
    if extension not in settings.allowed_extensions:
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
                'has_processing': False,
                'error': f'Unsupported file type: {extension}',
            },
            status_code=400,
        )

    destination = safe_join(settings.input_dir, dataset_file.filename or f'upload{extension}')
    destination.write_bytes(await dataset_file.read())
    dataset_id, created = repository.add_dataset(dataset_file.filename or destination.name, str(destination), user.username)
    repository.add_log(user.username, 'upload_dataset' if created else 'reprocess_dataset', destination.name)
    enqueue_dataset_processing(background_tasks, dataset_id, destination, user.username)
    return RedirectResponse(f'/dashboard?dataset_id={dataset_id}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/dashboard/retry/{dataset_id}')
def retry_dataset(dataset_id: int, background_tasks: BackgroundTasks, user: SessionUser = Depends(current_user)) -> Response:
    dataset = repository.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail='Dataset not found')
    dataset_payload = serialize_dataset_row(dataset)
    enqueue_dataset_processing(background_tasks, dataset_id, Path(dataset_payload['stored_path']), user.username)
    repository.add_log(user.username, 'retry_dataset', json.dumps({'dataset_id': dataset_id, 'file': dataset_payload['file_name']}))
    return RedirectResponse(f'/dashboard?dataset_id={dataset_id}', status_code=status.HTTP_303_SEE_OTHER)


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
        analysis = store_cached_analysis(dataset_path, filters, metric, build_analysis(load_dataset(dataset_path), filters, metric))
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
    return render_template(
        request,
        'admin.html',
        {
            'user': user,
            'users': repository.list_users(),
            'datasets': repository.list_datasets(),
            'logs': repository.list_logs(),
            'error': None,
        },
    )


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
        return render_template(
            request,
            'admin.html',
            {
                'user': user,
                'users': repository.list_users(),
                'datasets': repository.list_datasets(),
                'logs': repository.list_logs(),
                'error': str(exc),
            },
            status_code=400,
        )


templates.env.globals['format_extra_filters'] = format_extra_filters
