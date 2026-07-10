from __future__ import annotations

from io import BytesIO

from src.config import settings


def login(client) -> None:
    response = client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False)
    assert response.status_code == 303


def test_login_page_loads(client) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_admin_can_login_upload_and_analyze_dataset(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\nDE,2026-Q2,76,5.2\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_file": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    dashboard_response = client.get("/dashboard")
    assert "sample.csv" in dashboard_response.text

    analysis_response = client.post(
        "/dashboard/analyze",
        data={
            "dataset_path": str(settings.input_dir / "sample.csv"),
            "metric": "score",
            "market": "ES",
            "period": "2026-Q1",
            "aggregation": "all",
        },
    )
    assert analysis_response.status_code == 200
    assert "CDF curve" in analysis_response.text
    assert "Percentile scorecard" in analysis_response.text


def test_admin_panel_is_available_for_admin(client) -> None:
    login(client)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin panel" in response.text
