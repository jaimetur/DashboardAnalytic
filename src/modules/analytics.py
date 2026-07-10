from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.modules.ingestion import DatasetSummary
from src.utils.charts import build_chart_payload


@dataclass(slots=True)
class AnalysisResult:
    summary: DatasetSummary
    selected_metric: str
    filters: dict[str, Any]
    kpis: dict[str, Any]
    cdf_chart: dict[str, Any]
    table_rows: list[dict[str, Any]]
    scorecard: list[dict[str, Any]]


def apply_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    filtered = df.copy()
    market = filters.get("market")
    period = filters.get("period")
    aggregation = filters.get("aggregation")

    if market and "market" in filtered.columns:
        filtered = filtered[filtered["market"].astype(str) == str(market)]
    if period and "period" in filtered.columns:
        filtered = filtered[filtered["period"].astype(str) == str(period)]
    if aggregation and aggregation != "all" and aggregation in filtered.columns:
        filtered = filtered[filtered[aggregation].notna()]
    return filtered


def compute_cdf(series: pd.Series) -> list[tuple[float, float]]:
    cleaned = series.dropna().astype(float).sort_values().to_numpy()
    if cleaned.size == 0:
        return []
    cumulative = np.arange(1, cleaned.size + 1) / cleaned.size
    return list(zip(cleaned.tolist(), cumulative.tolist(), strict=False))


def compute_scorecard(df: pd.DataFrame, metric: str) -> list[dict[str, Any]]:
    if metric not in df.columns:
        return []
    values = df[metric].dropna().astype(float)
    if values.empty:
        return []
    percentiles = np.percentile(values, [10, 25, 50, 75, 90])
    labels = ["P10", "P25", "P50", "P75", "P90"]
    return [{"label": label, "value": round(float(value), 4)} for label, value in zip(labels, percentiles, strict=False)]


def build_analysis(df: pd.DataFrame, filters: dict[str, Any], metric: str) -> AnalysisResult:
    filtered = apply_filters(df, filters)
    summary = DatasetSummary(
        rows=len(filtered.index),
        columns=filtered.columns.tolist(),
        numeric_columns=filtered.select_dtypes(include=["number"]).columns.tolist(),
        categorical_columns=filtered.select_dtypes(exclude=["number"]).columns.tolist(),
    )
    selected_metric = metric if metric in filtered.columns else (summary.numeric_columns[0] if summary.numeric_columns else "")
    if not selected_metric:
        raise ValueError("No numeric metric available to analyse")

    metric_series = filtered[selected_metric].dropna().astype(float)
    cdf_pairs = compute_cdf(metric_series)
    top_records = filtered.sort_values(selected_metric, ascending=False).head(10)

    kpis = {
        "rows": int(summary.rows),
        "metric": selected_metric,
        "mean": round(float(metric_series.mean()), 4) if not metric_series.empty else 0.0,
        "median": round(float(metric_series.median()), 4) if not metric_series.empty else 0.0,
        "std_dev": round(float(metric_series.std(ddof=0)), 4) if not metric_series.empty else 0.0,
        "gap": round(float(metric_series.mean() - metric_series.median()), 4) if not metric_series.empty else 0.0,
        "best_score": round(float(metric_series.max()), 4) if not metric_series.empty else 0.0,
        "worst_score": round(float(metric_series.min()), 4) if not metric_series.empty else 0.0,
    }

    return AnalysisResult(
        summary=summary,
        selected_metric=selected_metric,
        filters=filters,
        kpis=kpis,
        cdf_chart=build_chart_payload(cdf_pairs),
        table_rows=top_records.to_dict(orient="records"),
        scorecard=compute_scorecard(filtered, selected_metric),
    )
