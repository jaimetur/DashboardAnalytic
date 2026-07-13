from __future__ import annotations

from io import BytesIO

def login(client) -> None:
    response = client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False)
    assert response.status_code == 303


def test_login_page_loads(client) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert "Dashboard Analytic" in response.text
    assert "2026-07-13" in response.text


def test_admin_can_login_upload_and_see_automatic_dashboard(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\nDE,2026-Q2,76,5.2\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_file": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    dashboard_response = client.get(upload_response.headers["location"])
    assert dashboard_response.status_code == 200
    assert "sample.csv" in dashboard_response.text
    assert "Automatic CDR Pipeline" in dashboard_response.text
    assert "Data Ingestion" in dashboard_response.text
    assert "Workspace opened from cache" in dashboard_response.text

    analysis_redirect = client.post(
        "/dashboard/analyze",
        data={
            "dataset_id": 1,
            "metric": "score",
            "market": "ES",
            "period": "2026-Q1",
            "aggregation": "all",
        },
        follow_redirects=False,
    )
    assert analysis_redirect.status_code == 303
    filtered_dashboard = client.get(analysis_redirect.headers["location"])
    assert filtered_dashboard.status_code == 200
    assert "Processed Metrics" in filtered_dashboard.text
    assert "CDF Curve" in filtered_dashboard.text
    assert "89" in filtered_dashboard.text


def test_admin_can_retry_stuck_dataset(client) -> None:
    login(client)
    client.post(
        "/dashboard/upload",
        files={"dataset_file": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(1, status="queued", progress=0, dataset_kind=None, row_count=None, column_count=None, default_metric=None)
    retry_response = client.post("/dashboard/retry/1", follow_redirects=False)
    assert retry_response.status_code == 303

    dashboard_response = client.get(retry_response.headers["location"])
    assert dashboard_response.status_code == 200
    assert "Workspace opened from cache" in dashboard_response.text


def test_reupload_same_file_reuses_existing_dataset_entry(client) -> None:
    login(client)
    payload = b"market,period,score\nES,2026-Q1,91\n"
    first_upload = client.post(
        "/dashboard/upload",
        files={"dataset_file": ("sample.csv", BytesIO(payload), "text/csv")},
        follow_redirects=False,
    )
    second_upload = client.post(
        "/dashboard/upload",
        files={"dataset_file": ("sample.csv", BytesIO(payload), "text/csv")},
        follow_redirects=False,
    )
    assert first_upload.status_code == 303
    assert second_upload.status_code == 303

    import src.DashboardAnalytic as app_module

    datasets = app_module.repository.list_datasets()
    assert len(datasets) == 1


def test_admin_panel_is_available_for_admin(client) -> None:
    login(client)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin panel" in response.text


def test_top_navigation_shows_document_links(client) -> None:
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "<h1>Dashboard Analytic</h1>" in response.text
    assert "v0.1.0 · 2026-07-13" in response.text
    assert 'href="/documents/view/readme"' in response.text
    assert 'href="/documents/view/changelog"' in response.text
    assert 'target="_blank"' in response.text
    assert 'href="/dashboard"' in response.text
    assert 'href="/logout"' in response.text


def test_docs_routes_expose_readme_and_changelog(client) -> None:
    login(client)

    readme_view = client.get("/documents/view/readme")
    assert readme_view.status_code == 200
    assert "Loading document..." in readme_view.text
    assert "/api/documents/readme" in readme_view.text

    changelog_api = client.get("/api/documents/changelog")
    assert changelog_api.status_code == 200
    payload = changelog_api.json()
    assert payload["name"] == "CHANGELOG.md"
    assert "0.1.0" in payload["content"]


def test_dashboard_analysis_reuses_cached_result_on_reload(client, monkeypatch) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_file": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    calls = {"count": 0}
    original_load_dataset = app_module.load_dataset

    def counting_load_dataset(path):
        calls["count"] += 1
        return original_load_dataset(path)

    monkeypatch.setattr(app_module, "load_dataset", counting_load_dataset)

    first_response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert first_response.status_code == 200
    assert calls["count"] == 1

    second_response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert second_response.status_code == 200
    assert calls["count"] == 1
