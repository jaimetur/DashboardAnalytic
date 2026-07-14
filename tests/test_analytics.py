from __future__ import annotations

import pandas as pd

from src.modules.analytics import MAX_CDF_POINTS, _top_records, build_analysis, compute_cdf
from src.modules.ingestion import infer_dataset_kind, load_dataset
from src.DashboardAnalytic import derive_available_metrics


def test_compute_cdf_orders_and_normalizes_values() -> None:
    series = pd.Series([5, 1, 3])
    result = compute_cdf(series)
    assert result == [(1.0, 1 / 3), (3.0, 2 / 3), (5.0, 1.0)]


def test_compute_cdf_caps_large_series_to_fixed_resolution() -> None:
    series = pd.Series(range(5000))
    result = compute_cdf(series)
    assert len(result) <= MAX_CDF_POINTS + 1
    assert result[0][0] == 0.0
    assert result[-1] == (4999.0, 1.0)


def test_build_analysis_returns_kpis_and_scorecard() -> None:
    df = pd.DataFrame({
        "market": ["ES", "ES", "DE"],
        "period": ["2026-Q1", "2026-Q1", "2026-Q2"],
        "score": [92, 87, 75],
        "gap": [1.2, 3.4, 5.6],
    })
    analysis = build_analysis(df, {"market": "ES", "period": "2026-Q1", "aggregation": "all"}, "score")
    assert analysis.kpis["rows"] == 2
    assert analysis.selected_metric == "score"
    assert len(analysis.scorecard) == 5
    assert analysis.cdf_chart["series"][-1] == 1.0
    assert analysis.cdf_chart["x_axis_label"] == "score"
    assert analysis.cdf_chart["y_axis_label"] == "Cumulative probability"


def test_load_dataset_combines_cdr_workbook_operator_sheets(tmp_path) -> None:
    workbook = tmp_path / "sample_voice.xlsm"
    vodafone = pd.DataFrame({
        "Campaign": ["DE_Q3_2025"],
        "Operator": ["Vodafone"],
        "Call_Status": ["Completed"],
        "Call_Setup_Time": [2.5],
        "Call_Duration": [120.0],
        "POLQA_LQ_Avg": [4.3],
        "Region": ["NORD_OST"],
        "Vendor": ["Huawei"],
    })
    telefonica = pd.DataFrame({
        "Campaign": ["DE_Q3_2025"],
        "Operator": ["o2 - de"],
        "Call_Status": ["Drop"],
        "Call_Setup_Time": [4.1],
        "Call_Duration": [34.0],
        "POLQA_LQ_Avg": [3.6],
        "Region": ["NORD_OST"],
        "Vendor": ["Huawei"],
    })
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame({"skip": [1]}).to_excel(writer, sheet_name="MASTER", index=False)
        vodafone.to_excel(writer, sheet_name="Vodafone", index=False)
        telefonica.to_excel(writer, sheet_name="Telefonica", index=False)

    dataset = load_dataset(workbook)

    assert len(dataset) == 2
    assert set(dataset["operator"]) == {"Vodafone", "o2 - de"}
    assert set(dataset["market"]) == {"DE"}
    assert set(dataset["period"]) == {"2025-Q3"}
    assert set(dataset["dataset_kind"]) == {"voice"}


def test_build_analysis_returns_voice_specific_kpis_and_aggregation() -> None:
    df = pd.DataFrame({
        "dataset_kind": ["voice", "voice", "voice"],
        "operator": ["Vodafone", "Vodafone", "o2 - de"],
        "market": ["DE", "DE", "DE"],
        "period": ["2025-Q3", "2025-Q3", "2025-Q3"],
        "region": ["NORD_OST", "NORD_OST", "NORD_OST"],
        "vendor": ["Huawei", "Huawei", "Huawei"],
        "success": [True, True, False],
        "failure": [False, False, True],
        "dropped": [False, False, True],
        "disturbed": [False, True, False],
        "impaired": [False, False, True],
        "setup_time_seconds": [2.0, 3.0, 6.0],
        "duration_seconds": [100.0, 120.0, 30.0],
        "POLQA_LQ_Avg": [4.5, 4.0, 3.1],
        "quality_score": [4.5, 4.0, 3.1],
    })

    analysis = build_analysis(df, {"market": "DE", "period": "2025-Q3", "aggregation": "operator"}, "POLQA_LQ_Avg")

    assert analysis.global_kpis["dataset_kind"] == "voice"
    assert analysis.global_kpis["success_rate_pct"] == 66.67
    assert analysis.global_kpis["completed_calls"] == 2
    assert analysis.metric_kpis["metric"] == "POLQA_LQ_Avg"
    assert analysis.metric_kpis["mean_metric"] == 3.8667
    assert analysis.metric_kpis["p10_metric"] == 3.28
    assert analysis.metric_kpis["p90_metric"] == 4.4
    assert analysis.filters["aggregation"] == "operator"
    assert analysis.table_rows[0]["operator"] == "Vodafone"
    assert len(analysis.scorecard_groups) == 2
    assert analysis.scorecard_groups[0]["group"] == "Vodafone"
    assert [item["label"] for item in analysis.scorecard_groups[0]["items"]] == ["P10", "P25", "P50", "P75", "P90"]


def test_build_analysis_applies_date_range_filters_from_event_start_time() -> None:
    df = pd.DataFrame({
        "dataset_kind": ["voice", "voice", "voice"],
        "market": ["DE", "DE", "DE"],
        "period": ["2025-Q3", "2025-Q3", "2025-Q3"],
        "operator": ["Vodafone", "Vodafone", "o2 - de"],
        "event_start_time": ["2025-07-10 10:00:00", "2025-07-11 11:00:00", "2025-07-13 09:00:00"],
        "success": [True, True, False],
        "failure": [False, False, True],
        "POLQA_LQ_Avg": [4.5, 4.0, 3.1],
    })

    analysis = build_analysis(
        df,
        {"aggregation": "all", "date_from": "2025-07-11", "date_to": "2025-07-13"},
        "POLQA_LQ_Avg",
    )

    assert analysis.global_kpis["rows"] == 2
    assert analysis.global_kpis["date_from"] == "2025-07-11"
    assert analysis.global_kpis["date_to"] == "2025-07-13"
    assert analysis.metric_kpis["samples"] == 2


def test_build_analysis_supports_multi_value_city_and_region_filters() -> None:
    df = pd.DataFrame({
        "dataset_kind": ["voice", "voice", "voice"],
        "market": ["DE", "DE", "DE"],
        "period": ["2025-Q3", "2025-Q3", "2025-Q3"],
        "region": ["North", "South", "East"],
        "city": ["Berlin", "Munich", "Hamburg"],
        "operator": ["Vodafone", "Vodafone", "o2 - de"],
        "success": [True, True, False],
        "failure": [False, False, True],
        "POLQA_LQ_Avg": [4.5, 4.0, 3.1],
    })

    analysis = build_analysis(
        df,
        {"aggregation": "city", "extra_filters": {"region": ["North", "South"], "city": ["Berlin", "Munich"]}},
        "POLQA_LQ_Avg",
    )

    assert analysis.global_kpis["rows"] == 2
    assert analysis.global_kpis["cities"] == 2
    assert analysis.global_kpis["regions"] == 2
    assert analysis.filters["aggregation"] == "city"


def test_build_analysis_builds_multi_series_cdf_when_cdf_grouping_is_selected() -> None:
    df = pd.DataFrame({
        "dataset_kind": ["voice", "voice", "voice", "voice"],
        "market": ["DE", "DE", "DE", "DE"],
        "period": ["2025-Q3", "2025-Q3", "2025-Q3", "2025-Q3"],
        "vendor": ["Nokia", "Nokia", "Huawei", "Huawei"],
        "operator": ["Vodafone", "Vodafone", "Vodafone", "Vodafone"],
        "quality_score": [4.5, 4.0, 3.5, 3.1],
    })

    analysis = build_analysis(
        df,
        {"aggregation": "all", "cdf_grouping": "vendor", "extra_filters": {"vendor": ["Nokia", "Huawei"]}},
        "quality_score",
    )

    assert analysis.filters["cdf_grouping"] == "vendor"
    assert "series_collection" in analysis.cdf_chart
    assert len(analysis.cdf_chart["series_collection"]) == 2
    assert {item["name"] for item in analysis.cdf_chart["series_collection"]} == {"Nokia", "Huawei"}
    assert analysis.cdf_chart["x_axis_label"] == "Quality Score"
    assert analysis.cdf_chart["y_axis_label"] == "Cumulative probability"


def test_build_analysis_cdf_axis_label_includes_metric_units_when_known() -> None:
    df = pd.DataFrame({
        "dataset_kind": ["data", "data", "data"],
        "market": ["DE", "DE", "DE"],
        "period": ["2025-Q3", "2025-Q3", "2025-Q3"],
        "throughput_mbps": [120.0, 90.0, 70.0],
    })

    analysis = build_analysis(df, {"aggregation": "all"}, "throughput_mbps")

    assert analysis.cdf_chart["x_axis_label"] == "Throughput (Mbps)"


def test_global_kpis_reflect_selected_dimension_counts_when_filters_are_active() -> None:
    df = pd.DataFrame({
        "dataset_kind": ["generic", "generic", "generic"],
        "market": ["ES", "ES", "ES"],
        "period": ["2026-Q1", "2026-Q1", "2026-Q1"],
        "operator": ["Vodafone", "Vodafone", "o2"],
        "region": ["North", "North", "South"],
        "city": ["Madrid", "Barcelona", "Sevilla"],
        "vendor": ["Huawei", "Huawei", "Ericsson"],
        "score": [10, 20, 30],
    })

    analysis = build_analysis(
        df,
        {"aggregation": "all", "extra_filters": {"operator": ["Vodafone", "o2"], "region": ["North", "South"], "city": ["Madrid", "Sevilla"], "vendor": ["Huawei", "Ericsson"]}},
        "score",
    )

    assert analysis.global_kpis["operators"] == 2
    assert analysis.global_kpis["regions"] == 2
    assert analysis.global_kpis["cities"] == 2
    assert analysis.global_kpis["vendors"] == 2


def test_infer_dataset_kind_detects_speech_and_data_from_columns() -> None:
    speech_df = pd.DataFrame({
        "RTP_Jitter_Avg_A": [12.0],
        "Receive_Delay": [80.0],
        "Recording_Technology": ["NR"],
    })
    data_df = pd.DataFrame({
        "Mean_Data_Rate": [42.0],
        "TCP_RTT_Service_Access_Delay": [120.0],
        "Transfer_Duration": [30.0],
    })

    assert infer_dataset_kind(speech_df, "session.xlsx") == "speech"
    assert infer_dataset_kind(data_df, "session.xlsx") == "data"


def test_derive_available_metrics_excludes_time_parts_and_ids() -> None:
    df = pd.DataFrame({
        "score": [1.0, 2.0],
        "latency_ms": [10.0, 20.0],
        "Year": [2026, 2026],
        "Week": [28, 28],
        "Hour": [10, 11],
        "call_id": [1001, 1002],
        "session_id": [2001, 2002],
        "customer_uuid": [3001, 3002],
    })

    metrics = derive_available_metrics(df)

    assert "score" in metrics
    assert "latency_ms" in metrics
    assert "Year" not in metrics
    assert "Week" not in metrics
    assert "Hour" not in metrics
    assert "call_id" not in metrics
    assert "session_id" not in metrics
    assert "customer_uuid" not in metrics


def test_top_records_deduplicates_metric_column_when_metric_is_preferred_field() -> None:
    df = pd.DataFrame({
        "market": ["ES", "ES"],
        "period": ["2026-Q1", "2026-Q1"],
        "operator": ["Vodafone", "Orange"],
        "region": ["North", "South"],
        "vendor": ["Huawei", "Ericsson"],
        "quality_score": [4.4, 3.8],
        "throughput_mbps": [120.0, 90.0],
        "setup_time_seconds": [1.2, 1.7],
    })

    rows = _top_records(df, "quality_score")

    assert rows
    first_row = rows[0]
    assert list(first_row.keys()).count("quality_score") == 1
