from __future__ import annotations

from pathlib import Path
import shutil
import time

import pytest
from fastapi.testclient import TestClient

import src.DashboardAnalytic as app_module
from src.config import settings


BACKGROUND_UPLOAD_PATHS = (
    '/datasets-analysis/upload', '/datasets-analysis/retry/', '/workspace/reprocess-datasets',
    '/workspace/map-', '/workspace/clear-',
)


def wait_for_background_dataset_work(timeout: float = 30.0) -> None:
    """Wait until uploaded sources and their combined CDR rebuilds finish.

    Dataset sources are parsed by isolated workers after the upload response
    is returned, so tests that inspect processed rows must wait for them.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with app_module.ACTIVE_DATASET_PROCESSING_LOCK:
            datasets_busy = bool(app_module.ACTIVE_DATASET_PROCESSING)
        with app_module.AUTO_CALCULATED_FIELD_JOBS_LOCK:
            jobs_busy = any(
                job.get('status') in {'queued', 'processing'}
                for job in app_module.AUTO_CALCULATED_FIELD_JOBS.values()
            )
        if not datasets_busy and not jobs_busy:
            return
        time.sleep(0.02)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    input_dir = data_dir / "input"
    output_dir = data_dir / "output"
    export_dir = data_dir / "exports"
    slides_templates_dir = data_dir / "slides-templates"
    ppt_templates_dir = data_dir / "ppt-templates"

    for directory in (config_dir, input_dir, output_dir, export_dir, slides_templates_dir, ppt_templates_dir):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_module.PROJECT_ROOT / "assets" / "ppt-templates" / "Template_CDR_analysis.pptx", ppt_templates_dir / "Template_CDR_analysis.pptx")
    nsa_target = slides_templates_dir / "default" / "nsa" / "NSA Slide Template.csv"
    nsa_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).parent / "fixtures" / "NSA Slide Template.csv", nsa_target)
    sa_target = slides_templates_dir / "default" / "sa" / "SA Slide Template.csv"
    sa_target.parent.mkdir(parents=True, exist_ok=True)
    sa_target.write_text(
        "Slide,Slide tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Filters,Rows Aggregation,Column Aggregation,Legend,Legend Position\n"
        "1,SA test template,,Title Page,,,,Title Slide,,,,,Top\n",
        encoding="utf-8",
    )

    object.__setattr__(settings, "database_path", config_dir / "application.db")
    object.__setattr__(settings, "input_dir", input_dir)
    object.__setattr__(settings, "output_dir", output_dir)
    object.__setattr__(settings, "export_dir", export_dir)
    object.__setattr__(settings, "slides_templates_dir", slides_templates_dir)
    object.__setattr__(settings, "ppt_templates_dir", ppt_templates_dir)
    app_module.repository.db_path = settings.database_path
    app_module.repository.set_global_database(settings.database_path)
    app_module.SESSIONS.clear()

    with TestClient(app_module.app) as test_client:
        original_post = test_client.post

        def post_and_wait_for_uploads(url, *args, **kwargs):
            response = original_post(url, *args, **kwargs)
            if str(url).startswith(BACKGROUND_UPLOAD_PATHS):
                wait_for_background_dataset_work()
            return response

        test_client.post = post_and_wait_for_uploads
        # Tests that need a library explicitly import it; new workspaces stay empty.
        if slides_templates_dir.is_dir():
            shutil.copytree(slides_templates_dir, app_module.active_workspace.slides_templates_dir, dirs_exist_ok=True)
        app_module.register_workspace_template_files(app_module.active_workspace)
        yield test_client
