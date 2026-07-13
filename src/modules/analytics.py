from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.modules.ingestion import DatasetSummary, infer_dataset_kind
from src.utils.charts import build_chart_payload


@dataclass(slots=True)
class AnalysisResult:
    summary: DatasetSummary
    selected_metric: str
    filters: dict[str, Any]
    kpis: dict[str, Any]
    cdf_chart: dict[str, Any]
    comparison_chart: dict[str, Any]
    table_rows: list[dict[str, Any]]
    scorecard: list[dict[str, Any]]


DEFAULT_METRICS: dict[str, list[str]] = {
    'voice': ['POLQA_LQ_Avg', 'quality_score', 'Call_Setup_Time', 'Call_Duration', 'setup_time_seconds'],
    'speech': ['LQ', 'quality_score', 'Receive_Delay', 'jitter_ms', 'packet_loss_pct'],
    'data': ['Mean_Data_Rate', 'throughput_mbps', 'TCP_Throughput', 'Test_Duration', 'setup_time_seconds'],
    'generic': ['quality_score'],
}
AGGREGATION_CANDIDATES: dict[str, list[str]] = {
    'voice': ['operator', 'session_type', 'region', 'vendor', 'technology_primary', 'source_sheet', 'market', 'period'],
    'speech': ['operator', 'session_type', 'region', 'vendor', 'Playing_Technology', 'source_sheet', 'market', 'period'],
    'data': ['operator', 'test_name', 'direction', 'region', 'vendor', 'Type_of_Test', 'source_sheet', 'market', 'period'],
    'generic': ['operator', 'market', 'period', 'source_sheet'],
}


def _resolve_column(df: pd.DataFrame, requested: str) -> str | None:
    if not requested:
        return None
    if requested in df.columns:
        return requested
    lowered = requested.strip().lower()
    for column in df.columns:
        if str(column).strip().lower() == lowered:
            return column
    return None


def _coerce_filter_values(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple, set)):
        return [str(value).strip() for value in raw_value if str(value).strip()]
    return [item.strip() for item in str(raw_value).split(',') if item.strip()]


def apply_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    filtered = df.copy()
    for key, raw_value in filters.items():
        if key in {'aggregation', 'extra_filters'} or raw_value in (None, '', []):
            continue
        column = _resolve_column(filtered, key)
        if not column:
            continue
        values = _coerce_filter_values(raw_value)
        if not values:
            continue
        normalized_values = {value.lower() for value in values}
        filtered = filtered[filtered[column].astype(str).str.strip().str.lower().isin(normalized_values)]

    for key, value in (filters.get('extra_filters') or {}).items():
        column = _resolve_column(filtered, key)
        if not column:
            continue
        values = _coerce_filter_values(value)
        if not values:
            continue
        normalized_values = {entry.lower() for entry in values}
        filtered = filtered[filtered[column].astype(str).str.strip().str.lower().isin(normalized_values)]

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
    values = pd.to_numeric(df[metric], errors='coerce').dropna()
    if values.empty:
        return []
    percentiles = np.percentile(values, [10, 25, 50, 75, 90])
    labels = ['P10', 'P25', 'P50', 'P75', 'P90']
    return [{'label': label, 'value': round(float(value), 4)} for label, value in zip(labels, percentiles, strict=False)]


def _infer_metric(df: pd.DataFrame, requested_metric: str, dataset_kind: str) -> str:
    candidate = _resolve_column(df, requested_metric)
    if candidate and pd.api.types.is_numeric_dtype(df[candidate]) and pd.to_numeric(df[candidate], errors='coerce').notna().any():
        return candidate
    for metric in DEFAULT_METRICS.get(dataset_kind, []) + DEFAULT_METRICS['generic']:
        column = _resolve_column(df, metric)
        if column and pd.api.types.is_numeric_dtype(df[column]) and pd.to_numeric(df[column], errors='coerce').notna().any():
            return column
    numeric_columns = [
        column for column in df.select_dtypes(include=['number']).columns.tolist()
        if pd.to_numeric(df[column], errors='coerce').notna().any()
    ]
    if not numeric_columns:
        raise ValueError('No numeric metric available to analyse')
    return numeric_columns[0]


def _infer_aggregation(df: pd.DataFrame, requested: str, dataset_kind: str) -> str | None:
    if requested and requested != 'all':
        return _resolve_column(df, requested)
    for candidate in AGGREGATION_CANDIDATES.get(dataset_kind, []):
        column = _resolve_column(df, candidate)
        if column and df[column].dropna().nunique() > 1:
            return column
    return None


def _round(value: Any, digits: int = 4) -> float | int:
    if pd.isna(value):
        return 0.0
    number = float(value)
    rounded = round(number, digits)
    return int(rounded) if rounded.is_integer() else rounded


def _series_mean(df: pd.DataFrame, column: str) -> float:
    resolved = _resolve_column(df, column)
    if not resolved:
        return 0.0
    values = pd.to_numeric(df[resolved], errors='coerce').dropna()
    return _round(values.mean()) if not values.empty else 0.0


def _series_percentile(df: pd.DataFrame, column: str, percentile: int) -> float:
    resolved = _resolve_column(df, column)
    if not resolved:
        return 0.0
    values = pd.to_numeric(df[resolved], errors='coerce').dropna()
    return _round(np.percentile(values, percentile)) if not values.empty else 0.0


def _rate(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return _round(series.fillna(False).astype(bool).mean() * 100, 2)


def _build_common_kpis(df: pd.DataFrame, selected_metric: str, dataset_kind: str) -> dict[str, Any]:
    kpis: dict[str, Any] = {
        'dataset_kind': dataset_kind,
        'rows': int(len(df.index)),
        'metric': selected_metric,
        'operators': int(df['operator'].dropna().nunique()) if 'operator' in df.columns else 0,
        'regions': int(df['region'].dropna().nunique()) if 'region' in df.columns else 0,
        'vendors': int(df['vendor'].dropna().nunique()) if 'vendor' in df.columns else 0,
        'success_rate_pct': _rate(df['success']) if 'success' in df.columns else 0.0,
        'failure_rate_pct': _rate(df['failure']) if 'failure' in df.columns else 0.0,
        'mean_metric': _series_mean(df, selected_metric),
        'p90_metric': _series_percentile(df, selected_metric, 90),
    }

    if dataset_kind == 'voice':
        kpis.update({
            'completed_calls': int(df['success'].sum()) if 'success' in df.columns else 0,
            'dropped_calls': int(df['dropped'].sum()) if 'dropped' in df.columns else 0,
            'disturbed_rate_pct': _rate(df['disturbed']) if 'disturbed' in df.columns else 0.0,
            'impaired_rate_pct': _rate(df['impaired']) if 'impaired' in df.columns else 0.0,
            'avg_setup_time_s': _series_mean(df, 'setup_time_seconds'),
            'p90_setup_time_s': _series_percentile(df, 'setup_time_seconds', 90),
            'avg_call_duration_s': _series_mean(df, 'duration_seconds'),
            'avg_polqa': _series_mean(df, 'POLQA_LQ_Avg'),
        })
    elif dataset_kind == 'speech':
        kpis.update({
            'completed_calls': int(df['success'].sum()) if 'success' in df.columns else 0,
            'disturbed_rate_pct': _rate(df['disturbed']) if 'disturbed' in df.columns else 0.0,
            'impaired_rate_pct': _rate(df['impaired']) if 'impaired' in df.columns else 0.0,
            'avg_lq': _series_mean(df, 'LQ'),
            'avg_jitter_ms': _series_mean(df, 'jitter_ms'),
            'avg_packet_loss_pct': _series_mean(df, 'packet_loss_pct'),
            'avg_receive_delay_ms': _series_mean(df, 'Receive_Delay'),
            'poor_lq_rate_pct': _round((pd.to_numeric(df.get('LQ'), errors='coerce') < 3.5).fillna(False).mean() * 100, 2) if 'LQ' in df.columns else 0.0,
        })
    elif dataset_kind == 'data':
        dns_success = pd.to_numeric(df.get('DNS_Resolution_Success_Ratio'), errors='coerce') if 'DNS_Resolution_Success_Ratio' in df.columns else pd.Series(dtype='float64')
        if dns_success.empty and 'DNS_Resolution_Success' in df.columns and 'DNS_Resolution_Attempts' in df.columns:
            attempts = pd.to_numeric(df['DNS_Resolution_Attempts'], errors='coerce')
            success = pd.to_numeric(df['DNS_Resolution_Success'], errors='coerce')
            dns_success = (success / attempts.replace(0, np.nan)) * 100
        kpis.update({
            'completed_tests': int(df['success'].sum()) if 'success' in df.columns else 0,
            'avg_mean_data_rate_mbps': _series_mean(df, 'Mean_Data_Rate'),
            'p90_mean_data_rate_mbps': _series_percentile(df, 'Mean_Data_Rate', 90),
            'avg_access_time_s': _series_mean(df, 'setup_time_seconds'),
            'avg_test_duration_s': _series_mean(df, 'duration_seconds'),
            'avg_dns_success_pct': _round(dns_success.dropna().mean(), 2) if not dns_success.empty else 0.0,
            'avg_tcp_rtt_ms': _series_mean(df, 'TCP_RTT_Service_Access_Delay'),
            'avg_video_freezing_s': _series_mean(df, 'VideoStream_Freezing_Time_Sum'),
        })

    return kpis


def _aggregate_table(df: pd.DataFrame, aggregation: str, metric: str, dataset_kind: str) -> list[dict[str, Any]]:
    grouped = df.dropna(subset=[aggregation]).groupby(aggregation, dropna=False)
    extra_metrics_by_kind = {
        'voice': [('setup_time_seconds', 'avg_setup_time_s'), ('duration_seconds', 'avg_duration_s'), ('quality_score', 'avg_quality_score'), ('handovers', 'avg_handovers')],
        'speech': [('quality_score', 'avg_quality_score'), ('latency_ms', 'avg_latency_ms'), ('jitter_ms', 'avg_jitter_ms'), ('packet_loss_pct', 'avg_packet_loss_pct'), ('handovers', 'avg_handovers')],
        'data': [('setup_time_seconds', 'avg_setup_time_s'), ('duration_seconds', 'avg_duration_s'), ('throughput_mbps', 'avg_throughput_mbps'), ('latency_ms', 'avg_latency_ms'), ('handovers', 'avg_handovers')],
        'generic': [('quality_score', 'avg_quality_score')],
    }
    rows: list[dict[str, Any]] = []
    for group_name, group in grouped:
        metric_values = pd.to_numeric(group[metric], errors='coerce').dropna()
        row: dict[str, Any] = {
            aggregation: group_name,
            'samples': int(len(group.index)),
            'success_rate_pct': _rate(group['success']) if 'success' in group.columns else 0.0,
            'mean_metric': _round(metric_values.mean()) if not metric_values.empty else 0.0,
            'median_metric': _round(metric_values.median()) if not metric_values.empty else 0.0,
            'p90_metric': _round(np.percentile(metric_values, 90)) if not metric_values.empty else 0.0,
        }
        for extra_column, label in extra_metrics_by_kind.get(dataset_kind, extra_metrics_by_kind['generic']):
            if extra_column in group.columns:
                row[label] = _series_mean(group, extra_column)
        rows.append(row)

    return sorted(rows, key=lambda item: (-item['samples'], -item['mean_metric']))[:25]


def _top_records(df: pd.DataFrame, metric: str) -> list[dict[str, Any]]:
    preferred_columns = [
        column for column in [
            'operator', 'session_type', 'test_name', 'direction', 'status', 'market', 'period', 'region', 'vendor', metric,
            'setup_time_seconds', 'duration_seconds', 'throughput_mbps', 'quality_score', 'technology_primary', 'source_sheet',
        ] if column in df.columns
    ]
    rows = df.sort_values(metric, ascending=False).head(25)
    if preferred_columns:
        rows = rows[preferred_columns]
    return rows.to_dict(orient='records')


def _build_comparison_chart(table_rows: list[dict[str, Any]], aggregation: str | None) -> dict[str, Any]:
    if not aggregation:
        return {'labels': [], 'series': [], 'type': 'bar'}
    compact_rows = table_rows[:8]
    return {
        'labels': [str(row.get(aggregation, 'n/a')) for row in compact_rows],
        'series': [round(float(row.get('mean_metric', 0.0)), 4) for row in compact_rows],
        'type': 'bar',
    }


def build_analysis(df: pd.DataFrame, filters: dict[str, Any], metric: str) -> AnalysisResult:
    filtered = apply_filters(df, filters)
    if filtered.empty:
        raise ValueError('No rows match the selected filters')

    dataset_kind = infer_dataset_kind(filtered, str(filtered.get('source_file', pd.Series(dtype='object')).iloc[0]) if 'source_file' in filtered.columns else '')
    selected_metric = _infer_metric(filtered, metric, dataset_kind)
    analysis_frame = filtered[pd.to_numeric(filtered[selected_metric], errors='coerce').notna()].copy()
    summary = DatasetSummary(
        rows=len(analysis_frame.index),
        columns=analysis_frame.columns.tolist(),
        numeric_columns=analysis_frame.select_dtypes(include=['number']).columns.tolist(),
        categorical_columns=analysis_frame.select_dtypes(exclude=['number']).columns.tolist(),
    )
    metric_series = pd.to_numeric(analysis_frame[selected_metric], errors='coerce').dropna()
    if metric_series.empty:
        raise ValueError(f'Metric {selected_metric} does not contain numeric values after filtering')

    aggregation = _infer_aggregation(analysis_frame, str(filters.get('aggregation') or ''), dataset_kind)
    normalized_filters = {**filters, 'aggregation': aggregation or 'all'}
    cdf_pairs = compute_cdf(metric_series)
    table_rows = _aggregate_table(analysis_frame, aggregation, selected_metric, dataset_kind) if aggregation else _top_records(analysis_frame, selected_metric)

    return AnalysisResult(
        summary=summary,
        selected_metric=selected_metric,
        filters=normalized_filters,
        kpis=_build_common_kpis(analysis_frame, selected_metric, dataset_kind),
        cdf_chart=build_chart_payload(cdf_pairs),
        comparison_chart=_build_comparison_chart(table_rows, aggregation),
        table_rows=table_rows,
        scorecard=compute_scorecard(analysis_frame, selected_metric),
    )
