from __future__ import annotations

import pandas as pd

from src.modules.analytics import build_analysis, compute_cdf
from src.modules.ingestion import load_dataset


def test_compute_cdf_orders_and_normalizes_values() -> None:
    series = pd.Series([5, 1, 3])
    result = compute_cdf(series)
    assert result == [(1.0, 1 / 3), (3.0, 2 / 3), (5.0, 1.0)]


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

    assert analysis.kpis["dataset_kind"] == "voice"
    assert analysis.kpis["success_rate_pct"] == 66.67
    assert analysis.kpis["avg_polqa"] == 3.8667
    assert analysis.filters["aggregation"] == "operator"
    assert analysis.table_rows[0]["operator"] == "Vodafone"
