from __future__ import annotations

from io import BytesIO
from pathlib import Path
import warnings

from src.modules.auth import hash_password

def login(client) -> None:
    response = client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False)
    assert response.status_code == 303


def test_login_page_loads(client) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert "Dashboard Analytic" in response.text
    assert "2026-07-14" in response.text
    assert "Default Access:" in response.text
    assert "admin / admin123" in response.text
    assert "demo / demo123" in response.text


def test_login_page_hides_missing_default_access_accounts(client) -> None:
    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", ("demo",))

    response = client.get("/login")
    assert response.status_code == 200
    assert "Default Access:" in response.text
    assert "admin / admin123" in response.text
    assert "demo / demo123" not in response.text


def test_login_page_hides_default_access_when_password_differs_from_default(client) -> None:
    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password("changed-password"), "demo"),
        )

    response = client.get("/login")
    assert response.status_code == 200
    assert "Default Access:" in response.text
    assert "admin / admin123" in response.text
    assert "demo / demo123" not in response.text


def test_login_page_hides_default_access_section_when_no_default_users_exist(client) -> None:
    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        conn.execute("DELETE FROM users WHERE username IN (?, ?)", ("admin", "demo"))

    response = client.get("/login")
    assert response.status_code == 200
    assert "Default Access:" not in response.text
    assert "admin / admin123" not in response.text
    assert "demo / demo123" not in response.text


def test_admin_can_login_upload_and_see_automatic_dashboard(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\nDE,2026-Q2,76,5.2\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
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


def test_dashboard_disables_metrics_without_non_null_values(client) -> None:
    login(client)
    csv_content = (
        b"market,period,operator,region,latency_ms,score\n"
        b"ES,2026-Q1,Vodafone,North,,91\n"
        b"ES,2026-Q1,Orange,South,,87\n"
    )
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200
    assert 'value="score"' in response.text
    assert 'value="latency_ms" disabled' in response.text
    assert "data-table-wrap" in response.text
    assert "Global Aggregation" in response.text


def test_admin_can_retry_stuck_dataset(client) -> None:
    login(client)
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(1, status="failed", progress=100, dataset_kind=None, row_count=None, column_count=None, default_metric=None)
    retry_response = client.post("/dashboard/retry/1", follow_redirects=False)
    assert retry_response.status_code == 303

    dashboard_response = client.get(retry_response.headers["location"])
    assert dashboard_response.status_code == 200
    assert "Workspace opened from cache" in dashboard_response.text


def test_admin_cannot_retry_queued_dataset(client) -> None:
    login(client)
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.post("/dashboard/retry/1")
    assert response.status_code == 400
    assert "Only failed or stopped datasets can be retried" in response.text


def test_admin_can_delete_queued_dataset(client) -> None:
    login(client)
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    dataset_path = Path(dataset["stored_path"])
    assert dataset_path.exists()
    response = client.post("/dashboard/delete/1", follow_redirects=False)
    assert response.status_code == 303
    assert app_module.repository.get_dataset(1) is None
    assert not dataset_path.exists()


def test_admin_can_stop_processing_dataset(client) -> None:
    login(client)
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(1, status="processing", progress=33)
    response = client.post("/dashboard/stop/1", follow_redirects=False)
    assert response.status_code == 303

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    assert dataset["status"] == "stopped"


def test_reupload_same_file_reuses_existing_dataset_entry(client) -> None:
    login(client)
    payload = b"market,period,score\nES,2026-Q1,91\n"
    first_upload = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(payload), "text/csv")},
        follow_redirects=False,
    )
    second_upload = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(payload), "text/csv")},
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


def test_dashboard_upload_accepts_multiple_files(client) -> None:
    login(client)

    response = client.post(
        "/dashboard/upload",
        files=[
            ("dataset_files", ("sample-a.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")),
            ("dataset_files", ("sample-b.csv", BytesIO(b"market,period,score\nDE,2026-Q2,78\n"), "text/csv")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303

    import src.DashboardAnalytic as app_module

    datasets = app_module.repository.list_datasets()
    assert len(datasets) == 2


def test_dataset_selector_shows_all_datasets_when_no_input_kind_filter_is_set(client) -> None:
    login(client)

    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("voice.csv", BytesIO(b"POLQA_LQ_Avg,market,period\n4.2,ES,2026-Q1\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("data.csv", BytesIO(b"Mean_Data_Rate,market,period\n25.1,DE,2026-Q2\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/dashboard?dataset_id=2")
    assert response.status_code == 200
    assert '<option value="1"' in response.text
    assert '<option value="2"' in response.text


def test_dataset_selector_only_lists_ready_datasets(client) -> None:
    login(client)

    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("ready.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("stopped.csv", BytesIO(b"market,period,score\nDE,2026-Q2,78\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(2, status="stopped", progress=50)

    response = client.get("/dashboard")
    selector_fragment = response.text.split('data-dataset-select', 1)[1].split('</select>', 1)[0]
    assert response.status_code == 200
    assert 'value="1"' in selector_fragment
    assert 'ready.csv' in selector_fragment
    assert 'value="2"' not in selector_fragment
    assert 'stopped.csv' not in selector_fragment


def test_dashboard_ignores_non_ready_dataset_id_in_selector_flow(client) -> None:
    login(client)

    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("ready.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("failed.csv", BytesIO(b"market,period,score\nDE,2026-Q2,78\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(2, status="failed", progress=100, last_error="broken")

    response = client.get("/dashboard?dataset_id=2")
    selector_fragment = response.text.split('data-dataset-select', 1)[1].split('</select>', 1)[0]
    assert response.status_code == 200
    assert 'option value="1"' in selector_fragment
    assert 'option value="2"' not in selector_fragment


def test_admin_can_update_user_identity_fields(client) -> None:
    login(client)

    create_response = client.post(
        "/admin/users",
        data={"username": "analyst", "password": "start123", "role": "user"},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    import src.DashboardAnalytic as app_module

    users = app_module.repository.list_users()
    analyst = next(row for row in users if row["username"] == "analyst")

    update_response = client.post(
        f"/admin/users/{analyst['id']}/update",
        data={"username": "analyst-updated", "password": "newpass456", "role": "admin"},
        follow_redirects=False,
    )
    assert update_response.status_code == 303

    updated = app_module.repository.get_user("analyst-updated")
    assert updated is not None
    assert updated.role == "admin"
    assert updated.active is False
    assert app_module.verify_password("newpass456", updated.password_hash)


def test_admin_can_delete_user(client) -> None:
    login(client)

    create_response = client.post(
        "/admin/users",
        data={"username": "temporary", "password": "temp123", "role": "user"},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    import src.DashboardAnalytic as app_module

    user_row = next(row for row in app_module.repository.list_users() if row["username"] == "temporary")
    delete_response = client.post(f"/admin/users/{user_row['id']}/delete", follow_redirects=False)
    assert delete_response.status_code == 303
    assert app_module.repository.get_user("temporary") is None


def test_admin_cannot_delete_current_signed_in_user(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    admin_row = next(row for row in app_module.repository.list_users() if row["username"] == "admin")
    response = client.post(f"/admin/users/{admin_row['id']}/delete")
    assert response.status_code == 400
    assert "You cannot delete the current signed-in admin user" in response.text


def test_admin_cannot_demote_or_deactivate_last_active_admin(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    admin_row = next(row for row in app_module.repository.list_users() if row["username"] == "admin")
    response = client.post(
        f"/admin/users/{admin_row['id']}/update",
        data={"username": "admin", "password": "", "role": "user"},
    )
    assert response.status_code == 400
    assert "At least one active admin user must remain" in response.text

    response = client.post(
        f"/admin/users/{admin_row['id']}/update",
        data={"username": "admin", "password": "", "role": "admin"},
    )
    assert response.status_code == 400
    assert "At least one active admin user must remain" in response.text


def test_admin_cannot_delete_last_active_admin_even_if_not_current_user(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    create_response = client.post(
        "/admin/users",
        data={"username": "backup-admin", "password": "backup123", "role": "admin"},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    users = app_module.repository.list_users()
    backup_admin = next(row for row in users if row["username"] == "backup-admin")
    admin_row = next(row for row in users if row["username"] == "admin")

    switch_session = client.post(
        "/login",
        data={"username": "backup-admin", "password": "backup123"},
        follow_redirects=False,
    )
    assert switch_session.status_code == 303

    disable_backup = client.post(
        f"/admin/users/{backup_admin['id']}/update",
        data={"username": "backup-admin", "password": "", "role": "admin"},
        follow_redirects=False,
    )
    assert disable_backup.status_code == 303

    response = client.post(f"/admin/users/{admin_row['id']}/delete")
    assert response.status_code == 400
    assert "At least one active admin user must remain" in response.text


def test_top_navigation_shows_document_links(client) -> None:
    login(client)
    response = client.get("/workspace")
    assert response.status_code == 200
    assert "<h1>Dashboard Analytic</h1>" in response.text
    assert "v0.1.0 · 2026-07-14" in response.text
    assert 'href="/documents/view/readme"' in response.text
    assert 'href="/documents/view/changelog"' in response.text
    assert 'target="_blank"' in response.text
    assert 'href="/dashboard"' in response.text
    assert 'href="/logout"' in response.text
    assert '<span class="title-badge title-user-badge title-user-badge-admin">admin</span>' in response.text


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
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    calls = {"count": 0}
    original_load_dataset = app_module.load_dataset
    app_module.ANALYSIS_CACHE.clear()
    app_module.DATAFRAME_CACHE.clear()
    assert app_module.repository.dataset_rows_table_exists(1)

    def counting_load_dataset(path):
        calls["count"] += 1
        return original_load_dataset(path)

    monkeypatch.setattr(app_module, "load_dataset", counting_load_dataset)

    first_response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert first_response.status_code == 200
    assert calls["count"] == 0

    second_response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert second_response.status_code == 200
    assert calls["count"] == 0


def test_dashboard_analysis_reuses_cached_dataset_frame_across_metric_changes(client, monkeypatch) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    calls = {"count": 0}
    original_load_dataset = app_module.load_dataset
    app_module.ANALYSIS_CACHE.clear()
    app_module.DATAFRAME_CACHE.clear()
    assert app_module.repository.dataset_rows_table_exists(1)

    def counting_load_dataset(path):
        calls["count"] += 1
        return original_load_dataset(path)

    monkeypatch.setattr(app_module, "load_dataset", counting_load_dataset)

    first_response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert first_response.status_code == 200
    assert calls["count"] == 0

    second_response = client.get("/dashboard?dataset_id=1&metric=gap&aggregation=all&load=1")
    assert second_response.status_code == 200
    assert calls["count"] == 0


def test_dashboard_renders_multiple_selected_metrics(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/dashboard?dataset_id=1&metric=score&metric=gap&aggregation=all&load=1")
    assert response.status_code == 200
    assert "Use the dropdown to select one, several, or all KPIs." in response.text
    assert response.text.count("Metric View") >= 2
    assert response.text.count("Selected Metric") >= 2
    assert "mean metric" in response.text.lower()
    assert "score" in response.text
    assert "gap" in response.text


def test_dashboard_shows_date_range_filters_and_applies_them(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,Call Start Time\n"
        b"ES,2026-Q1,91,2026-07-10 10:00:00\n"
        b"ES,2026-Q1,87,2026-07-11 12:00:00\n"
    )
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&date_from=2026-07-11&load=1")
    assert response.status_code == 200
    assert 'name="date_from"' in response.text
    assert 'name="date_to"' in response.text
    assert 'value="2026-07-11"' in response.text
    assert "2026-07-10" not in response.text


def test_dashboard_adaptive_filters_include_city_and_multi_select_fields(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,City,Region\n"
        b"ES,2026-Q1,91,Madrid,Central\n"
        b"ES,2026-Q1,87,Barcelona,East\n"
    )
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200
    assert 'select name="city" multiple' in response.text
    assert 'select name="region" multiple' in response.text
    assert ">Madrid<" in response.text
    assert ">Barcelona<" in response.text
    assert "All values are selected by default. Clearing all values applies an empty filter." in response.text


def test_dashboard_comparison_chart_exposes_per_metric_aggregation_override_control(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap,operator,region\nES,2026-Q1,91,2.1,Vodafone,North\nES,2026-Q1,87,3.3,o2,South\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/dashboard?dataset_id=1&metric=score&metric=gap&aggregation=region&aggregation_overrides=score=operator&load=1")
    assert response.status_code == 200
    assert 'data-chart-aggregation-select' in response.text
    assert 'data-metric="score"' in response.text
    assert 'data-current-overrides="score=operator"' in response.text


def test_dashboard_exposes_global_and_per_metric_cdf_comparison_controls(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,vendor,region,operator,city\n"
        b"ES,2026-Q1,91,Nokia,North,Vodafone,Madrid\n"
        b"ES,2026-Q1,87,Huawei,South,Vodafone,Barcelona\n"
    )
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/dashboard?dataset_id=1&metric=score&load=1&cdf_grouping=vendor")
    assert response.status_code == 200
    assert "Global CDF Comparison" in response.text
    assert 'data-global-cdf-grouping-select' in response.text
    assert 'data-chart-cdf-grouping-select' in response.text
    assert 'Compare CDF by' in response.text


def test_dashboard_powerpoint_export_includes_visual_analytics_payload(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,gap,vendor,operator,region,city,Call Start Time\n"
        b"ES,2026-Q1,91,2.1,Nokia,Vodafone,North,Madrid,2026-07-10 10:00:00\n"
        b"ES,2026-Q1,87,3.3,Huawei,Orange,South,Barcelona,2026-07-11 11:00:00\n"
    )
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.post(
        "/dashboard/export/powerpoint",
        data={
            "dataset_id": "1",
            "metric": ["score", "gap"],
            "market": ["ES"],
            "aggregation": "operator",
            "cdf_grouping": "vendor",
            "date_from": "2026-07-10",
            "date_to": "2026-07-11",
            "extra_filters": "vendor=Nokia,Huawei; region=North,South",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    from pptx import Presentation

    presentation = Presentation(BytesIO(response.content))
    assert len(presentation.slides) >= 4
    slide_text = "\n".join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if hasattr(shape, "text")
    )
    assert "sample.csv" in slide_text
    assert "Visual Analytics - score" in slide_text
    assert "Visual Analytics - gap" in slide_text
    assert "Date From: 2026-07-10" in slide_text


def test_workspace_logs_capture_analysis_warnings(client, monkeypatch) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    original_build_analysis = app_module.build_analysis

    def warned_build_analysis(*args, **kwargs):
        warnings.warn("Synthetic analysis warning for workspace logs", UserWarning)
        return original_build_analysis(*args, **kwargs)

    monkeypatch.setattr(app_module, "build_analysis", warned_build_analysis)

    response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200

    logs = app_module.repository.list_workspace_logs(1)
    warning_logs = [log for log in logs if log["action"] == "analyze_dataset_warning"]
    assert warning_logs
    assert "Synthetic analysis warning for workspace logs" in warning_logs[0]["details_text"]


def test_dashboard_handles_empty_table_rows_without_template_failure(client) -> None:
    login(client)
    csv_content = b"market,period,operator,score\nES,2026-Q1,VDF,91\nES,2026-Q1,VDF,87\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=operator&market=DE&load=1")
    assert response.status_code == 200
    assert "No rows match the selected filters" in response.text or "No tabular rows match the selected filters" in response.text


def test_dashboard_materializes_legacy_ready_dataset_on_first_analysis(client) -> None:
    login(client)
    csv_content = b"market,period,operator,score\nES,2026-Q1,VDF,91\nES,2026-Q1,VDF,87\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    app_module.repository.drop_dataset_rows(1)
    assert not app_module.repository.dataset_rows_table_exists(1)

    response = client.get("/dashboard?dataset_id=1&metric=score&aggregation=operator&load=1")
    assert response.status_code == 200
    assert "Charts and Scorecards" in response.text
    assert app_module.repository.dataset_rows_table_exists(1)


def test_dataset_status_endpoint_returns_queue_payload(client) -> None:
    login(client)
    client.post(
        "/dashboard/upload",
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/api/datasets/status")
    assert response.status_code == 200
    payload = response.json()
    assert "datasets" in payload
    assert payload["datasets"][0]["file_name"] == "sample.csv"


def test_dashboard_handles_missing_source_file_without_500(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        conn.execute(
            "INSERT INTO datasets (id, file_name, stored_path, uploaded_by) VALUES (?, ?, ?, ?)",
            (99, "missing.xlsx", "/tmp/does-not-exist.xlsx", "admin"),
        )
        conn.execute(
            """
            INSERT INTO dataset_profiles (
                dataset_id, status, progress, dataset_kind, default_metric, default_aggregation,
                available_metrics_json, available_aggregations_json, filter_options_json, summary_json, kpis_json
            ) VALUES (?, 'ready', 100, 'data', 'throughput_mbps', 'operator', '["throughput_mbps"]', '["operator"]', '{}', '{}', '{}')
            """,
            (99,),
        )

    response = client.get("/dashboard?dataset_id=99&metric=throughput_mbps&aggregation=operator&load=1")
    assert response.status_code == 200
    assert "source file is missing" in response.text


def test_materialized_dataset_handles_case_insensitive_duplicate_columns(client) -> None:
    login(client)
    csv_content = b"Campaign,campaign,score\nES_Q1_2026,manual-campaign,91\n"
    upload_response = client.post(
        "/dashboard/upload",
        files={"dataset_files": ("duplicate-columns.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    assert dataset["status"] == "ready"
    assert dataset["last_error"] in (None, "")


def test_failed_dataset_shows_last_error_in_queue(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        conn.execute(
            "INSERT INTO datasets (id, file_name, stored_path, uploaded_by) VALUES (?, ?, ?, ?)",
            (50, "broken.csv", "/tmp/broken.csv", "admin"),
        )
        conn.execute(
            """
            INSERT INTO dataset_profiles (
                dataset_id, status, progress, dataset_kind, last_error, available_metrics_json,
                available_aggregations_json, filter_options_json, summary_json, kpis_json
            ) VALUES (?, 'failed', 100, 'generic', 'duplicate column name: campaign', '[]', '[]', '{}', '{}', '{}')
            """,
            (50,),
        )

    response = client.get("/workspace")
    assert response.status_code == 200
    assert "duplicate column name: campaign" in response.text


def test_workspace_shows_operational_logs_panel(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    app_module.repository.add_log(
        "admin",
        "process_dataset_failed",
        '{"dataset_id": 1, "file": "sample.csv", "error": "Synthetic processing failure"}',
    )

    response = client.get("/workspace")
    assert response.status_code == 200
    assert "Workspace Logs" in response.text
    assert "Execution and Error Trail" in response.text
    assert "All events" in response.text
    assert "Info only" in response.text
    assert "Error only" in response.text
    assert "Type" in response.text
    assert "Error" in response.text
    assert "Synthetic processing failure" in response.text
