from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient

import src.DashboardAnalytic as app_module
from src.config import settings


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
        "Slide,Slide tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Legend,Filters,Grouping_Rows,Grouping_Columns\n"
        "1,SA test template,,Title Page,,,,Title Slide,,,,\n",
        encoding="utf-8",
    )

    object.__setattr__(settings, "database_path", config_dir / "app.db")
    object.__setattr__(settings, "input_dir", input_dir)
    object.__setattr__(settings, "output_dir", output_dir)
    object.__setattr__(settings, "export_dir", export_dir)
    object.__setattr__(settings, "slides_templates_dir", slides_templates_dir)
    object.__setattr__(settings, "ppt_templates_dir", ppt_templates_dir)
    app_module.repository.db_path = settings.database_path
    app_module.SESSIONS.clear()

    with TestClient(app_module.app) as test_client:
        yield test_client
