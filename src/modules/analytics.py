from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.modules.ingestion import DatasetSummary, infer_dataset_kind
from src.utils.charts import build_chart_payload, build_multi_series_chart_payload


@dataclass(slots=True)
class AnalysisResult:
    summary: DatasetSummary
    selected_metric: str
    filters: dict[str, Any]
    kpis: dict[str, Any]
    global_kpis: dict[str, Any]
    metric_kpis: dict[str, Any]
    cdf_chart: dict[str, Any]
    comparison_chart: dict[str, Any]
    table_rows: list[dict[str, Any]]
    scorecard: list[dict[str, Any]]
    scorecard_groups: list[dict[str, Any]]


DEFAULT_METRICS: dict[str, list[str]] = {
    'voice': ['POLQA_LQ_Avg', 'quality_score', 'Call_Setup_Time', 'Call_Duration', 'setup_time_seconds'],
    'speech': ['LQ', 'quality_score', 'Receive_Delay', 'jitter_ms', 'packet_loss_pct'],
    'data': ['Mean_Data_Rate', 'throughput_mbps', 'TCP_Throughput', 'Test_Duration', 'setup_time_seconds'],
    'generic': ['quality_score'],
}
AGGREGATION_CANDIDATES: dict[str, list[str]] = {
    'voice': ['operator', 'session_type', 'region', 'city', 'vendor', 'technology_primary', 'source_sheet', 'market', 'period'],
    'speech': ['operator', 'session_type', 'region', 'city', 'vendor', 'Playing_Technology', 'source_sheet', 'market', 'period'],
    'data': ['operator', 'test_name', 'direction', 'region', 'city', 'vendor', 'Type_of_Test', 'source_sheet', 'market', 'period'],
    'generic': ['operator', 'region', 'city', 'market', 'period', 'source_sheet'],
}
CDF_COMPARISON_CANDIDATES = ['vendor', 'market', 'operator', 'region', 'city']
MAX_CDF_POINTS = 2048
METRIC_AXIS_TITLES = {
    'polqa_lq_avg': 'POLQA LQ Avg',
    'lq': 'LQ',
    'quality_score': 'Quality Score',
    'throughput_mbps': 'Throughput',
    'mean_data_rate': 'Mean Data Rate',
    'tcp_throughput': 'TCP Throughput',
    'latency_ms': 'Latency',
    'receive_delay': 'Receive Delay',
    'jitter_ms': 'Jitter',
    'packet_loss_pct': 'Packet Loss',
    'setup_time_seconds': 'Setup Time',
    'call_setup_time': 'Call Setup Time',
    'duration_seconds': 'Duration',
    'call_duration': 'Call Duration',
    'test_duration': 'Test Duration',
}
METRIC_AXIS_UNITS = {
    'polqa_lq_avg': '',
    'lq': '',
    'quality_score': '',
    'throughput_mbps': 'Mbps',
    'mean_data_rate': 'Mbps',
    'tcp_throughput': 'Mbps',
    'latency_ms': 'ms',
    'receive_delay': 'ms',
    'jitter_ms': 'ms',
    'packet_loss_pct': '%',
    'setup_time_seconds': 's',
    'call_setup_time': 's',
    'duration_seconds': 's',
    'call_duration': 's',
    'test_duration': 's',
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
    date_from = filters.get('date_from')
    date_to = filters.get('date_to')
    if 'event_start_time' in filtered.columns and (date_from or date_to):
        event_times = pd.to_datetime(filtered['event_start_time'], errors='coerce')
        if date_from:
            filtered = filtered[event_times.dt.date >= pd.to_datetime(date_from).date()]
            event_times = pd.to_datetime(filtered['event_start_time'], errors='coerce')
        if date_to:
            filtered = filtered[event_times.dt.date <= pd.to_datetime(date_to).date()]

    for key, raw_value in filters.items():
        if key in {'aggregation', 'extra_filters', 'date_from', 'date_to'} or raw_value in (None, '', []):
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
    if cleaned.size > MAX_CDF_POINTS:
        sample_indexes = np.linspace(0, cleaned.size - 1, MAX_CDF_POINTS, dtype=int)
        sample_indexes = np.unique(sample_indexes)
        sampled = cleaned[sample_indexes]
        cumulative = (sample_indexes + 1) / cleaned.size
        if sample_indexes[-1] != cleaned.size - 1:
            sampled = np.append(sampled, cleaned[-1])
            cumulative = np.append(cumulative, 1.0)
        return list(zip(sampled.tolist(), cumulative.tolist(), strict=False))
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


def compute_grouped_scorecards(df: pd.DataFrame, metric: str, aggregation: str | None, table_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if metric not in df.columns:
        return []
    if not aggregation:
        return [{
            'group': 'Overall',
            'items': compute_scorecard(df, metric),
        }]

    resolved_aggregation = _resolve_column(df, aggregation)
    if not resolved_aggregation:
        return [{
            'group': 'Overall',
            'items': compute_scorecard(df, metric),
        }]

    if table_rows:
        group_order = [str(row.get(aggregation, '')).strip() for row in table_rows if str(row.get(aggregation, '')).strip()]
    else:
        group_order = [
            str(value).strip() for value in df[resolved_aggregation].dropna().tolist()
            if str(value).strip()
        ]

    seen: set[str] = set()
    ordered_groups: list[str] = []
    for group_name in group_order:
        normalized = group_name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered_groups.append(group_name)

    grouped_scorecards: list[dict[str, Any]] = []
    for group_name in ordered_groups[:8]:
        group_df = df[df[resolved_aggregation].astype(str).str.strip().str.lower() == group_name.lower()]
        items = compute_scorecard(group_df, metric)
        if not items:
            continue
        grouped_scorecards.append({
            'group': group_name,
            'items': items,
        })
    if grouped_scorecards:
        return grouped_scorecards
    return [{
        'group': 'Overall',
        'items': compute_scorecard(df, metric),
    }]


def _infer_metric(df: pd.DataFrame, requested_metric: str, dataset_kind: str) -> str:
    candidate = _resolve_column(df, requested_metric)
    if candidate:
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


def _infer_cdf_grouping(df: pd.DataFrame, requested: str | None) -> str | None:
    normalized = str(requested or '').strip()
    if not normalized or normalized == 'all':
        return None
    if normalized not in CDF_COMPARISON_CANDIDATES:
        return None
    return _resolve_column(df, normalized)


def _format_metric_axis_label(metric: str) -> str:
    normalized = str(metric or '').strip()
    if not normalized:
        return 'Metric value'
    key = normalized.lower()
    unit = METRIC_AXIS_UNITS.get(key, '')
    pretty = METRIC_AXIS_TITLES.get(key, normalized.replace('_', ' '))
    return f'{pretty} ({unit})' if unit else pretty


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


def _selected_count(filters: dict[str, Any], key: str) -> int | None:
    if key in {'market', 'period'}:
        selected = filters.get(key)
    else:
        selected = (filters.get('extra_filters') or {}).get(key)
    values = _coerce_filter_values(selected)
    return len(values) if values else None


def _build_global_kpis(df: pd.DataFrame, dataset_kind: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = filters or {}
    kpis: dict[str, Any] = {
        'dataset_kind': dataset_kind,
        'rows': int(len(df.index)),
        'operators': _selected_count(filters, 'operator') if _selected_count(filters, 'operator') is not None else (int(df['operator'].dropna().nunique()) if 'operator' in df.columns else 0),
        'regions': _selected_count(filters, 'region') if _selected_count(filters, 'region') is not None else (int(df['region'].dropna().nunique()) if 'region' in df.columns else 0),
        'cities': _selected_count(filters, 'city') if _selected_count(filters, 'city') is not None else (int(df['city'].dropna().nunique()) if 'city' in df.columns else 0),
        'vendors': _selected_count(filters, 'vendor') if _selected_count(filters, 'vendor') is not None else (int(df['vendor'].dropna().nunique()) if 'vendor' in df.columns else 0),
        'success_rate_pct': _rate(df['success']) if 'success' in df.columns else 0.0,
        'failure_rate_pct': _rate(df['failure']) if 'failure' in df.columns else 0.0,
    }
    if 'dropped' in df.columns:
        kpis['dropped_calls'] = int(df['dropped'].fillna(False).astype(bool).sum())
        kpis['drop_call_rate_pct'] = _rate(df['dropped'])
    if 'event_start_time' in df.columns:
        event_times = pd.to_datetime(df['event_start_time'], errors='coerce').dropna()
        if not event_times.empty:
            kpis['date_from'] = event_times.min().date().isoformat()
            kpis['date_to'] = event_times.max().date().isoformat()

    if dataset_kind == 'voice':
        kpis.update({
            'completed_calls': int(df['success'].sum()) if 'success' in df.columns else 0,
            'disturbed_rate_pct': _rate(df['disturbed']) if 'disturbed' in df.columns else 0.0,
            'impaired_rate_pct': _rate(df['impaired']) if 'impaired' in df.columns else 0.0,
            'avg_setup_time_s': _series_mean(df, 'setup_time_seconds'),
            'avg_call_duration_s': _series_mean(df, 'duration_seconds'),
        })
    elif dataset_kind == 'speech':
        kpis.update({
            'completed_calls': int(df['success'].sum()) if 'success' in df.columns else 0,
            'disturbed_rate_pct': _rate(df['disturbed']) if 'disturbed' in df.columns else 0.0,
            'impaired_rate_pct': _rate(df['impaired']) if 'impaired' in df.columns else 0.0,
            'avg_jitter_ms': _series_mean(df, 'jitter_ms'),
            'avg_packet_loss_pct': _series_mean(df, 'packet_loss_pct'),
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
            'avg_access_time_s': _series_mean(df, 'setup_time_seconds'),
            'avg_test_duration_s': _series_mean(df, 'duration_seconds'),
            'avg_dns_success_pct': _round(dns_success.dropna().mean(), 2) if not dns_success.empty else 0.0,
        })

    return kpis


def _build_metric_kpis(df: pd.DataFrame, selected_metric: str) -> dict[str, Any]:
    values = pd.to_numeric(df[selected_metric], errors='coerce').dropna() if selected_metric in df.columns else pd.Series(dtype='float64')
    if values.empty:
        return {
            'metric': selected_metric,
            'samples': 0,
            'mean_metric': 0.0,
            'avg_metric': 0.0,
            'p10_metric': 0.0,
            'p90_metric': 0.0,
            'min_metric': 0.0,
            'max_metric': 0.0,
        }
    return {
        'metric': selected_metric,
        'samples': int(values.shape[0]),
        'mean_metric': _round(values.mean()),
        'avg_metric': _round(values.mean()),
        'p10_metric': _round(np.percentile(values, 10)),
        'p90_metric': _round(np.percentile(values, 90)),
        'min_metric': _round(values.min()),
        'max_metric': _round(values.max()),
    }


def _build_cdf_chart(df: pd.DataFrame, metric: str, filters: dict[str, Any], cdf_grouping: str | None) -> dict[str, Any]:
    metric_values = pd.to_numeric(df[metric], errors='coerce').dropna() if metric in df.columns else pd.Series(dtype='float64')
    if metric_values.empty:
        return {'labels': [], 'series': [], 'type': 'line'}

    x_axis_label = _format_metric_axis_label(metric)
    y_axis_label = 'Cumulative probability'

    grouping_column = _infer_cdf_grouping(df, cdf_grouping)
    if not grouping_column:
        chart = build_chart_payload(compute_cdf(metric_values))
        chart['x_axis_label'] = x_axis_label
        chart['y_axis_label'] = y_axis_label
        return chart

    if grouping_column in {'market', 'period'}:
        selected_groups = _coerce_filter_values(filters.get(grouping_column))
    else:
        selected_groups = _coerce_filter_values((filters.get('extra_filters') or {}).get(grouping_column))

    grouped_values: dict[str, dict[str, Any]] = {}
    for raw_group_value, group_frame in df.dropna(subset=[grouping_column]).groupby(grouping_column, dropna=False):
        display_name = str(raw_group_value).strip()
        normalized_name = display_name.lower()
        if not display_name or normalized_name in grouped_values:
            continue
        values = pd.to_numeric(group_frame[metric], errors='coerce').dropna() if metric in group_frame.columns else pd.Series(dtype='float64')
        if values.empty:
            continue
        grouped_values[normalized_name] = {
            'name': display_name,
            'values': values,
        }

    if selected_groups:
        preferred_keys: list[str] = []
        seen_selected: set[str] = set()
        for value in selected_groups:
            normalized = str(value).strip().lower()
            if not normalized or normalized in seen_selected or normalized not in grouped_values:
                continue
            seen_selected.add(normalized)
            preferred_keys.append(normalized)
        ordered_keys = preferred_keys
    else:
        ordered_keys = list(grouped_values.keys())

    series_collection: list[dict[str, Any]] = []
    for group_key in ordered_keys[:8]:
        item = grouped_values.get(group_key)
        if not item:
            continue
        pairs = compute_cdf(item['values'])
        if not pairs:
            continue
        series_collection.append({
            'name': item['name'],
            'labels': [pair[0] for pair in pairs],
            'series': [pair[1] for pair in pairs],
        })

    if not series_collection:
        chart = build_chart_payload(compute_cdf(metric_values))
        chart['x_axis_label'] = x_axis_label
        chart['y_axis_label'] = y_axis_label
        return chart
    if len(series_collection) == 1:
        only = series_collection[0]
        return {
            'labels': [round(float(value), 4) for value in only['labels']],
            'series': [round(float(value), 4) for value in only['series']],
            'type': 'line',
            'legend': [only['name']],
            'x_axis_label': x_axis_label,
            'y_axis_label': y_axis_label,
        }
    chart = build_multi_series_chart_payload(series_collection)
    chart['x_axis_label'] = x_axis_label
    chart['y_axis_label'] = y_axis_label
    return chart


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
    preferred_columns: list[str] = []
    seen: set[str] = set()
    for column in [
        'operator', 'session_type', 'test_name', 'direction', 'status', 'market', 'period', 'region', 'vendor', metric,
        'city',
        'setup_time_seconds', 'duration_seconds', 'throughput_mbps', 'quality_score', 'technology_primary', 'source_sheet',
    ]:
        if column in df.columns and column not in seen:
            preferred_columns.append(column)
            seen.add(column)
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


def build_analysis(df: pd.DataFrame, filters: dict[str, Any], metric: str, *, prefiltered: bool = False) -> AnalysisResult:
    filtered = df if prefiltered else apply_filters(df, filters)
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

    requested_aggregation = str(filters.get('aggregation') or '').strip().lower()
    requested_cdf_grouping = str(filters.get('cdf_grouping') or '').strip().lower()
    aggregation = _infer_aggregation(analysis_frame, requested_aggregation, dataset_kind)
    cdf_grouping = _infer_cdf_grouping(analysis_frame, requested_cdf_grouping)
    normalized_filters = {
        **filters,
        'aggregation': requested_aggregation if aggregation else 'all',
        'cdf_grouping': requested_cdf_grouping if cdf_grouping else 'all',
    }
    table_rows = _aggregate_table(analysis_frame, aggregation, selected_metric, dataset_kind) if aggregation else _top_records(analysis_frame, selected_metric)

    global_kpis = _build_global_kpis(filtered, dataset_kind, normalized_filters)

    return AnalysisResult(
        summary=summary,
        selected_metric=selected_metric,
        filters=normalized_filters,
        kpis=global_kpis,
        global_kpis=global_kpis,
        metric_kpis=_build_metric_kpis(analysis_frame, selected_metric),
        cdf_chart=_build_cdf_chart(analysis_frame, selected_metric, normalized_filters, cdf_grouping),
        comparison_chart=_build_comparison_chart(table_rows, aggregation),
        table_rows=table_rows,
        scorecard=compute_scorecard(analysis_frame, selected_metric),
        scorecard_groups=compute_grouped_scorecards(analysis_frame, selected_metric, aggregation, table_rows),
    )
