from __future__ import annotations

import pandas as pd

from src.modules.analytics import build_analysis, compute_cdf


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
