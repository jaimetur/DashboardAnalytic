from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import settings
from src.modules.analytics import build_analysis
from src.modules.auth import SessionUser, verify_password
from src.modules.exports import export_powerpoint_report, export_word_report
from src.modules.ingestion import load_dataset, summarise_dataset
from src.modules.repository import Repository
from src.version import __version__
from src.utils.filesystem import ensure_directories, safe_join


SESSION_COOKIE = "bench_automations_session"
SESSIONS: dict[str, SessionUser] = {}
repository = Repository(settings.database_path)


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


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
templates = Jinja2Templates(directory=str(settings.template_dir))


def create_session(response: Response, user: SessionUser) -> None:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")


def current_user(request: Request) -> SessionUser:
    token = request.cookies.get(SESSION_COOKIE)
    user = SESSIONS.get(token or "")
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def admin_user(user: SessionUser = Depends(current_user)) -> SessionUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def render_template(request: Request, template_name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    payload = {
        "request": request,
        "app_name": settings.app_name,
        "app_version": __version__,
        **context,
    }
    return templates.TemplateResponse(request, template_name, payload, status_code=status_code)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if request.cookies.get(SESSION_COOKIE) in SESSIONS:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return render_template(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)) -> Response:
    record = repository.get_user(username)
    if not record or not record.active or not verify_password(password, record.password_hash):
        return render_template(request, "login.html", {"error": "Invalid credentials"}, status_code=401)

    user = SessionUser(username=record.username, role=record.role)
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, user)
    repository.add_log(username, "login", "User logged in")
    return response


@app.get("/logout")
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        SESSIONS.pop(token, None)
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: SessionUser = Depends(current_user)) -> HTMLResponse:
    return render_template(
        request,
        "dashboard.html",
        {"user": user, "datasets": repository.list_datasets(), "analysis": None, "error": None},
    )


@app.post("/dashboard/upload", response_class=HTMLResponse)
async def upload_dataset(request: Request, dataset_file: UploadFile = File(...), user: SessionUser = Depends(current_user)) -> Response:
    extension = Path(dataset_file.filename or "").suffix.lower()
    if extension not in settings.allowed_extensions:
        return render_template(
            request,
            "dashboard.html",
            {
                "user": user,
                "datasets": repository.list_datasets(),
                "analysis": None,
                "error": f"Unsupported file type: {extension}",
            },
            status_code=400,
        )

    destination = safe_join(settings.input_dir, dataset_file.filename or f"upload{extension}")
    destination.write_bytes(await dataset_file.read())
    repository.add_dataset(dataset_file.filename or destination.name, str(destination), user.username)
    repository.add_log(user.username, "upload_dataset", destination.name)
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/dashboard/analyze", response_class=HTMLResponse)
def analyze_dataset(
    request: Request,
    dataset_path: str = Form(...),
    metric: str = Form(""),
    market: str = Form(""),
    period: str = Form(""),
    aggregation: str = Form("all"),
    user: SessionUser = Depends(current_user),
) -> HTMLResponse:
    filters = {"market": market.strip() or None, "period": period.strip() or None, "aggregation": aggregation.strip() or "all"}
    try:
        df = load_dataset(Path(dataset_path))
        analysis = build_analysis(df, filters, metric)
        repository.add_log(user.username, "analyze_dataset", json.dumps({"dataset_path": dataset_path, **filters}))
        return render_template(
            request,
            "dashboard.html",
            {
                "user": user,
                "datasets": repository.list_datasets(),
                "analysis": analysis,
                "summary": summarise_dataset(df),
                "active_dataset_path": dataset_path,
                "error": None,
            },
        )
    except Exception as exc:
        return render_template(
            request,
            "dashboard.html",
            {"user": user, "datasets": repository.list_datasets(), "analysis": None, "error": str(exc)},
            status_code=400,
        )


@app.post("/dashboard/export/{export_kind}")
def export_report(
    export_kind: str,
    dataset_path: str = Form(...),
    metric: str = Form(""),
    market: str = Form(""),
    period: str = Form(""),
    aggregation: str = Form("all"),
    user: SessionUser = Depends(current_user),
) -> FileResponse:
    if export_kind not in {"word", "powerpoint"}:
        raise HTTPException(status_code=404, detail="Unsupported export type")

    filters = {"market": market or None, "period": period or None, "aggregation": aggregation or "all"}
    analysis = build_analysis(load_dataset(Path(dataset_path)), filters, metric)
    file_stem = Path(dataset_path).stem

    if export_kind == "word":
        destination = safe_join(settings.export_dir, f"{file_stem}_report.docx")
        export_word_report(destination, asdict(analysis))
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        destination = safe_join(settings.export_dir, f"{file_stem}_report.pptx")
        export_powerpoint_report(destination, asdict(analysis))
        media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    repository.add_log(user.username, f"export_{export_kind}", destination.name)
    return FileResponse(destination, filename=destination.name, media_type=media_type)


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, user: SessionUser = Depends(admin_user)) -> HTMLResponse:
    return render_template(
        request,
        "admin.html",
        {
            "user": user,
            "users": repository.list_users(),
            "datasets": repository.list_datasets(),
            "logs": repository.list_logs(),
            "error": None,
        },
    )


@app.post("/admin/users", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    user: SessionUser = Depends(admin_user),
) -> HTMLResponse:
    try:
        repository.create_user(username, password, role)
        repository.add_log(user.username, "create_user", username)
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        return render_template(
            request,
            "admin.html",
            {
                "user": user,
                "users": repository.list_users(),
                "datasets": repository.list_datasets(),
                "logs": repository.list_logs(),
                "error": str(exc),
            },
            status_code=400,
        )
