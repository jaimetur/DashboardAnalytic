"""Presentation-ready scoring and GAP tables derived from saved job results."""
from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

from src.modules.scoring_config import validate_scoring_configuration


_ENVIRONMENT_ORDER = ('DriveCity', 'DriveConnectionroad', 'Combined')
_SCOPE_FIELDS = ('campaign', 'region', 'city', 'vendor', 'dataset_type')
THRESHOLD_COLORS = {
    'Low': '#F8CCCC',
    'Medium': '#FFE3A3',
    'High': '#D8EFCA',
    'UltraHigh': '#98D8D7',
    'Unavailable': '#ECEFF1',
}
THRESHOLD_LEGEND = [
    {'band': 'Low', 'color': THRESHOLD_COLORS['Low'], 'definition': 'Score below the configured Medium score anchor.'},
    {'band': 'Medium', 'color': THRESHOLD_COLORS['Medium'], 'definition': 'Score at Medium and below the configured High score anchor.'},
    {'band': 'High', 'color': THRESHOLD_COLORS['High'], 'definition': 'Score at the configured High score anchor, below Ultra.'},
    {'band': 'UltraHigh', 'color': THRESHOLD_COLORS['UltraHigh'], 'definition': 'Score at or above the configured Ultra score anchor.'},
    {'band': 'Unavailable', 'color': THRESHOLD_COLORS['Unavailable'], 'definition': 'Score is incomplete or unavailable.'},
]
_GAP_NEUTRAL = '#FFFFFF'
_GAP_POSITIVE_MAX = '#70AD47'
_GAP_NEGATIVE_MAX = '#E57373'


def normalize_result_gaps(result: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copied result using positive=operator-above-reference GAP signs."""
    normalized = copy.deepcopy(result) if isinstance(result, dict) else {}
    direction = normalized.get('gap_direction')
    if direction != 'operator_minus_reference':
        if direction in {None, '', 'baseline_minus_operator'}:
            for key in ('gap', 'gap_totals'):
                rows = normalized.get(key, [])
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    gap = _number(row.get('gap_points'))
                    if gap is not None:
                        row['gap_points'] = _clean_number(-gap)
        normalized['gap_direction'] = 'operator_minus_reference'
    return normalized


def build_scoring_views(job: dict[str, Any] | None, result: dict[str, Any] | None,
                        operator_mapping_groups: list[dict[str, Any]] | None = None,
                        workspace_configuration: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Build reference-style KPI matrices and signed, priority-ordered GAP tables.

    The source ``result`` remains untouched. City and road rows are combined only
    when both environments actually occur in the same aggregation context.
    """
    job = job if isinstance(job, dict) else {}
    result = result if isinstance(result, dict) else {}
    configuration_payload = result.get('configuration')
    if configuration_payload is None:
        configuration_payload = job.get('configuration')
    if configuration_payload is None:
        configuration_payload = workspace_configuration
    if configuration_payload is None:
        raise ValueError(
            'The scoring result has no configuration snapshot. Supply the saved workspace configuration to build its views.'
        )
    configuration = validate_scoring_configuration(configuration_payload)
    metrics = configuration['metrics']
    gap_priority = list(configuration.get('gap_priority') or [metric['code'] for metric in metrics])
    gap_priority_rank = {code: index for index, code in enumerate(gap_priority)}
    levels = job.get('levels', job.get('aggregation_levels', [])) or []
    if isinstance(levels, str):
        levels = [levels]
    include_dataset_type = any(_level_identity(level) == 'datasettype' for level in levels)
    requested_baseline = str(job.get('baseline_operator') or job.get('baseline') or 'EE').strip() or 'EE'
    baseline_aliases = job.get('baseline_aliases') or result.get('baseline_aliases') or _mapping_aliases(
        requested_baseline, operator_mapping_groups or [],
    )

    score_records = _records(result.get('scoring', result.get('score_rows', [])))
    total_records = _records(result.get('totals', result.get('charts', [])))
    context_records = score_records + total_records
    if not context_records:
        return {'score_tables': [], 'gap_tables': [], 'gap_summary_tables': [],
                'hierarchy_score_tables': [], 'hierarchy_gap_tables': [],
                'threshold_legend': [dict(item) for item in THRESHOLD_LEGEND],
                'gap_direction': 'operator_minus_reference'}

    contexts: dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = {}
    all_operators: dict[tuple[Any, ...], set[str]] = {}
    for record in context_records:
        scope = _scope_key(record, include_dataset_type)
        environment = _canonical_environment(_field(record, 'environment'))
        contexts.setdefault(scope, {}).setdefault(environment, []).append(record)
        all_operators.setdefault(scope, set()).update(_operators_in(record))

    score_tables: list[dict[str, Any]] = []
    gap_tables: list[dict[str, Any]] = []
    gap_summary_tables: list[dict[str, Any]] = []
    for scope in sorted(contexts, key=_scope_sort_key):
        environment_records = contexts[scope]
        styles = _operator_styles(all_operators.get(scope, set()), operator_mapping_groups or [])
        operators = sorted(styles, key=lambda name: (styles[name]['position'], styles[name]['label'].casefold(), name.casefold()))
        actual_environments = {environment for environment in environment_records if environment != 'Combined'}
        environments = sorted(actual_environments, key=_environment_sort_key)
        if {'DriveCity', 'DriveConnectionroad'} <= actual_environments:
            environments.append('Combined')

        for environment in environments:
            context = _make_context(scope, environment, include_dataset_type)
            env_rows = environment_records.get(environment, [])
            city_rows = environment_records.get('DriveCity', []) if environment == 'Combined' else []
            road_rows = environment_records.get('DriveConnectionroad', []) if environment == 'Combined' else []
            baseline_operator = _matching_baseline(operators, requested_baseline, baseline_aliases)
            table = _build_score_table(
                context, operators, baseline_operator,
                env_rows, city_rows, road_rows, include_dataset_type,
                actual_environments, metrics, configuration, baseline_aliases,
                gap_priority_rank,
            )
            table['operator_styles'] = styles
            score_tables.append(table)
            gap_summary_tables.append(_build_gap_summary_table(table, gap_priority_rank, baseline_aliases))
            gap_tables.extend(_build_gap_tables(table, gap_priority_rank, baseline_aliases))

    hierarchy_levels = _hierarchy_levels(job, result)
    hierarchy_score_tables, hierarchy_gap_tables = _build_hierarchy_tables(
        score_tables, hierarchy_levels, requested_baseline, baseline_aliases,
        operator_mapping_groups or [], metrics, gap_priority_rank,
    ) if hierarchy_levels else ([], [])

    return {
        'score_tables': score_tables,
        'gap_tables': gap_tables,
        'gap_summary_tables': gap_summary_tables,
        'hierarchy_score_tables': hierarchy_score_tables,
        'hierarchy_gap_tables': hierarchy_gap_tables,
        'threshold_legend': [dict(item) for item in THRESHOLD_LEGEND],
        'gap_direction': 'operator_minus_reference',
        'gap_legend': {
            'positive': 'Compared operator has more weighted points than the reference.',
            'negative': 'Compared operator has fewer weighted points than the reference.',
            'colors': {'positive': _GAP_POSITIVE_MAX, 'negative': _GAP_NEGATIVE_MAX, 'zero': _GAP_NEUTRAL},
        },
    }


_HIERARCHY_LEVELS = {
    'operator': 'Operator',
    'vendor': 'Vendor',
    'ranvendor': 'Vendor',
    'region': 'Region',
    'city': 'City',
    'campaign': 'Campaign',
    'datasettype': 'Dataset Type',
}
_HIERARCHY_CONTEXT_FIELDS = {
    'Vendor': 'vendor',
    'Region': 'region',
    'City': 'city',
    'Campaign': 'campaign',
    'Dataset Type': 'dataset_type',
}


def _hierarchy_levels(job: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Return selected hierarchy levels only for jobs using the new aggregation contract."""
    try:
        contract_version = int(job.get('aggregation_contract_version') or result.get('aggregation_contract_version') or 0)
    except (TypeError, ValueError):
        contract_version = 0
    if contract_version != 2:
        return []
    levels = job.get('aggregation_levels') or job.get('levels') or result.get('aggregation_levels') or []
    if isinstance(levels, str):
        levels = [levels]
    if not isinstance(levels, list):
        return []
    canonical = []
    for level in levels:
        name = _HIERARCHY_LEVELS.get(_level_identity(level))
        if name and name not in canonical:
            canonical.append(name)
    if 'Operator' not in canonical:
        canonical.insert(0, 'Operator')
    return canonical


def _hierarchy_leaf_id(path: list[dict[str, Any]]) -> str:
    return json.dumps(
        [[entry['level'], entry.get('value')] for entry in path],
        ensure_ascii=False, separators=(',', ':'), sort_keys=False,
    )


def _hierarchy_context_key(path: list[dict[str, Any]]) -> str:
    return _hierarchy_leaf_id([entry for entry in path if entry['level'] != 'Operator'])


def _hierarchy_column_sort_key(column: dict[str, Any]) -> tuple[Any, ...]:
    values = []
    for item in column['path']:
        value = item.get('value')
        if item['level'] == 'Operator':
            values.append((0, column.get('operator_position', 0), str(value or '').casefold()))
        else:
            values.append((1, '' if value is None else str(value).casefold(), '' if value is None else str(value)))
    return tuple(values)


def _missing_hierarchy_value() -> dict[str, Any]:
    return {
        'points': None, 'complete': False, 'value': None, 'score': None, 'sample_count': 0,
        'threshold_band': 'Unavailable', 'color': THRESHOLD_COLORS['Unavailable'],
    }


def _build_hierarchy_tables(
    score_tables: list[dict[str, Any]], hierarchy_levels: list[str], requested_baseline: str,
    baseline_aliases: list[str], operator_mapping_groups: list[dict[str, Any]],
    metrics: list[dict[str, Any]], gap_priority_rank: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flatten new-contract per-context views into one complete leaf matrix per Environment."""
    levels = [level for level in hierarchy_levels if level == 'Operator' or level in _HIERARCHY_CONTEXT_FIELDS]
    if 'Operator' not in levels:
        return [], []
    by_environment: dict[str, list[dict[str, Any]]] = {}
    actual_environments: set[str] = set()
    for table in score_tables:
        environment = str(table.get('context', {}).get('environment') or 'Unspecified')
        by_environment.setdefault(environment, []).append(table)
        if environment != 'Combined':
            actual_environments.add(environment)

    hierarchy_scores = []
    hierarchy_gaps = []
    for environment in sorted(by_environment, key=_environment_sort_key):
        context_tables = by_environment[environment]
        columns_by_id: dict[str, dict[str, Any]] = {}
        leaf_sources: dict[str, tuple[dict[str, Any], str]] = {}
        for table in context_tables:
            context = table.get('context', {})
            styles = table.get('operator_styles', {})
            for raw_operator in table.get('operators', []):
                base_style = styles.get(raw_operator, {})
                canonical_operator = str(base_style.get('label') or raw_operator)
                operator_position = _number(base_style.get('position'))
                path = []
                leaf_context = {'environment': environment}
                for level in levels:
                    if level == 'Operator':
                        value = canonical_operator
                    else:
                        context_field = _HIERARCHY_CONTEXT_FIELDS[level]
                        value = context.get(context_field)
                        leaf_context[context_field] = value
                    path.append({'level': level, 'value': value})
                leaf_id = _hierarchy_leaf_id(path)
                label = ' · '.join(
                    f'{item["level"]}: {item.get("value") if item.get("value") is not None else "Not specified"}'
                    for item in path
                )
                is_reference = _same_baseline_identity(canonical_operator, requested_baseline, baseline_aliases)
                column = {
                    'id': leaf_id,
                    'operator': canonical_operator,
                    'label': label,
                    'path': path,
                    'context': leaf_context,
                    'is_reference': is_reference,
                    'operator_position': int(operator_position) if operator_position is not None else 1_000_000,
                    'color': str(base_style.get('color') or '#365F91').upper(),
                }
                if leaf_id not in columns_by_id:
                    columns_by_id[leaf_id] = column
                    leaf_sources[leaf_id] = (table, raw_operator)

        columns = sorted(columns_by_id.values(), key=_hierarchy_column_sort_key)
        leaf_ids = [column['id'] for column in columns]
        if not columns:
            continue
        operator_styles = {
            column['id']: {
                'label': column['label'], 'fullpath': column['label'], 'operator': column['operator'],
                'color': column['color'], 'position': index,
                'operator_position': column['operator_position'], 'is_reference': column['is_reference'],
            }
            for index, column in enumerate(columns)
        }
        templates: dict[str, dict[str, Any]] = {}
        source_rows: dict[str, dict[str, dict[str, Any]]] = {}
        for leaf_id, (table, raw_operator) in leaf_sources.items():
            by_code = {row['kpi_code']: row for row in table.get('rows', [])}
            source_rows[leaf_id] = by_code
            for code, row in by_code.items():
                if code not in templates:
                    templates[code] = {
                        key: copy.deepcopy(value) for key, value in row.items()
                        if key not in {'values', 'gaps', 'gap_colors'}
                    }

        metric_order = {metric['code']: index for index, metric in enumerate(metrics)}
        ordered_codes = sorted(
            templates,
            key=lambda code: (metric_order.get(code, len(metric_order)), gap_priority_rank.get(code, len(gap_priority_rank)), code),
        )
        baseline_by_context = {
            _hierarchy_context_key(column['path']): column['id']
            for column in columns if column['is_reference']
        }

        rows = []
        for code in ordered_codes:
            row = dict(templates[code])
            row['values'] = {}
            for leaf_id in leaf_ids:
                table, raw_operator = leaf_sources[leaf_id]
                source_row = source_rows[leaf_id].get(code)
                cell = source_row.get('values', {}).get(raw_operator) if source_row else None
                row['values'][leaf_id] = copy.deepcopy(cell) if cell is not None else _missing_hierarchy_value()
            row['gaps'] = {}
            for column in columns:
                baseline_id = baseline_by_context.get(_hierarchy_context_key(column['path']))
                row['gaps'][column['id']] = _signed_gap(
                    row['values'].get(baseline_id) if baseline_id else None,
                    row['values'][column['id']], column['operator'], requested_baseline, baseline_aliases,
                )
            rows.append(row)

        all_gaps = [abs(value) for row in rows for value in row['gaps'].values() if value is not None]
        gap_scale_max = max(all_gaps, default=0.0)
        for row in rows:
            row['gap_colors'] = {
                column['id']: gap_color(row['gaps'].get(column['id']), gap_scale_max)
                for column in columns
            }

        first_table = context_tables[0]
        total_values = {}
        for leaf_id in leaf_ids:
            table, raw_operator = leaf_sources[leaf_id]
            raw_total = table.get('total', {}).get('values', {}).get(raw_operator)
            total_values[leaf_id] = copy.deepcopy(raw_total) if raw_total is not None else {'points': None, 'complete': False}
        total_gaps = {}
        for column in columns:
            baseline_id = baseline_by_context.get(_hierarchy_context_key(column['path']))
            baseline_total = total_values.get(baseline_id) if baseline_id else None
            current_total = total_values.get(column['id'])
            if (column['is_reference'] and current_total and current_total.get('complete')
                    and current_total.get('points') is not None):
                total_gaps[column['id']] = 0.0
            elif (baseline_total and current_total and baseline_total.get('complete') and current_total.get('complete')
                  and baseline_total.get('points') is not None and current_total.get('points') is not None):
                total_gaps[column['id']] = _clean_number(current_total['points'] - baseline_total['points'])
            else:
                total_gaps[column['id']] = None
        total = {
            'max_points': first_table.get('total', {}).get('max_points'),
            'weight_percent': first_table.get('total', {}).get('weight_percent'),
            'values': total_values,
            'gaps': total_gaps,
        }
        score_matrix = {
            'context': {'environment': environment},
            'title': f'Scoring Table — {environment}',
            'operators': leaf_ids,
            'baseline_operator': requested_baseline,
            'operator_styles': operator_styles,
            'hierarchy_columns': columns,
            'hierarchy_levels': list(levels),
            'rows': rows,
            'total': total,
            'gap_scale_max': gap_scale_max,
            'gap_scale_colors': {'zero': _GAP_NEUTRAL, 'positive': _GAP_POSITIVE_MAX, 'negative': _GAP_NEGATIVE_MAX},
            'coverage_note': _coverage_note(rows, leaf_ids, environment, actual_environments),
            'gap_priority': [code for code in gap_priority_rank],
            'gap_direction': 'operator_minus_reference',
        }
        hierarchy_scores.append(score_matrix)

        gap_rows = []
        for row in rows:
            gap_rows.append({
                key: copy.deepcopy(row[key]) for key in ('category', 'kpi', 'kpi_code', 'kpi_type') if key in row
            } | {
                'gaps': dict(row['gaps']), 'gap_colors': dict(row['gap_colors']),
            })
        gap_rows.sort(key=lambda row: (
            gap_priority_rank.get(row['kpi_code'], len(gap_priority_rank)),
            row['kpi_code'],
        ))
        hierarchy_gaps.append({
            'context': {'environment': environment},
            'title': f'GAP Analysis — All vs reference — {environment}',
            'operators': leaf_ids,
            'baseline_operator': requested_baseline,
            'operator_styles': operator_styles,
            'hierarchy_columns': columns,
            'hierarchy_levels': list(levels),
            'rows': gap_rows,
            'total': {'gaps': dict(total_gaps)},
            'gap_scale_max': gap_scale_max,
            'gap_scale_colors': {'zero': _GAP_NEUTRAL, 'positive': _GAP_POSITIVE_MAX, 'negative': _GAP_NEGATIVE_MAX},
            'note': 'GAP comparisons use the reference operator in the same selected context. Missing matches are N/A.',
            'gap_direction': 'operator_minus_reference',
        })
    return hierarchy_scores, hierarchy_gaps


def gap_color(value: Any, scale_max: Any) -> str:
    """Return the signed GAP gradient color, using a context-wide scale."""
    gap = _number(value)
    if gap is None:
        return THRESHOLD_COLORS['Unavailable']
    maximum = _number(scale_max) or 0.0
    magnitude = abs(gap)
    ratio = min(1.0, magnitude / maximum) if maximum > 0 else (1.0 if magnitude else 0.0)
    if gap == 0:
        return _GAP_NEUTRAL
    intensity = max(0.15, math.sqrt(ratio))
    return _blend_hex(_GAP_NEUTRAL, _GAP_POSITIVE_MAX if gap > 0 else _GAP_NEGATIVE_MAX, intensity)


def _build_score_table(
    context: dict[str, Any], operators: list[str], baseline_operator: str,
    env_rows: list[dict[str, Any]],
    city_rows: list[dict[str, Any]], road_rows: list[dict[str, Any]],
    include_dataset_type: bool, actual_environments: set[str],
    metrics: list[dict[str, Any]], configuration: dict[str, Any],
    baseline_aliases: list[str], gap_priority_rank: dict[str, int],
) -> dict[str, Any]:
    environment = context['environment']
    global_max_points = _number(configuration.get('scope', {}).get('total_max_points')) or 0.0
    selected_metrics = _metrics_for_context(context, include_dataset_type, metrics)
    unknown = _unknown_metrics(env_rows if environment != 'Combined' else city_rows + road_rows, metrics)
    metric_specs = [(metric['code'], metric) for metric in selected_metrics]
    known_codes = {code for code, _ in metric_specs}
    metric_specs.extend((code, spec) for code, spec in unknown.items() if code not in known_codes)

    rows = []
    for code, metric in metric_specs:
        row_values: dict[str, dict[str, Any]] = {}
        for operator in operators:
            if environment == 'Combined':
                value = _combined_metric_value(code, operator, city_rows, road_rows, metric)
            else:
                source = _find_metric_record(code, operator, env_rows)
                value = _metric_value(source, metric, environment)
            row_values[operator] = value
        maximum = _metric_max_points(metric, environment)
        if maximum is None:
            maximum = _unknown_max_points(
                code, env_rows if environment != 'Combined' else city_rows + road_rows,
                environment,
            )
        weight_percent = maximum * 100.0 / global_max_points if maximum is not None and global_max_points > 0 else None
        gaps = {}
        for operator in operators:
            gaps[operator] = _signed_gap(
                row_values.get(baseline_operator), row_values.get(operator),
                operator, baseline_operator, baseline_aliases,
            )
        rows.append({
            'kpi_code': code,
            'category': metric.get('category', 'Other'),
            'kpi': metric.get('kpi', _fallback_kpi_label(code)),
            'kpi_type': metric.get('kpi_type', 'Unknown'),
            'weight_percent': weight_percent,
            'max_points': maximum,
            'values': row_values,
            'gaps': gaps,
        })

    total_max_points = sum(row['max_points'] for row in rows if row['max_points'] is not None)
    total_values: dict[str, dict[str, Any]] = {}
    total_gaps: dict[str, float | None] = {}
    for operator in operators:
        cells = [row['values'][operator] for row in rows]
        known_points = [cell['points'] for cell in cells if cell['points'] is not None]
        complete = bool(cells) and all(
            cell['complete'] for row, cell in zip(rows, cells)
            if (_number(row.get('max_points')) or 0.0) > 0
        )
        zero_weight_only = all((_number(row.get('max_points')) or 0.0) == 0 for row in rows)
        total_points = sum(known_points) if known_points else (0.0 if zero_weight_only else None)
        total_values[operator] = {'points': total_points, 'complete': complete}
    for operator in operators:
        baseline_total = total_values.get(baseline_operator)
        operator_total = total_values.get(operator)
        if (_same_baseline_identity(operator, baseline_operator, baseline_aliases) or not baseline_total or not operator_total
                or not baseline_total['complete'] or not operator_total['complete']
                or baseline_total['points'] is None or operator_total['points'] is None):
            total_gaps[operator] = None
        else:
            total_gaps[operator] = _clean_number(operator_total['points'] - baseline_total['points'])

    total = {
        'max_points': total_max_points,
        'weight_percent': total_max_points * 100.0 / global_max_points if global_max_points > 0 else None,
        'values': total_values,
        'gaps': total_gaps,
    }
    gap_scale_max = max(
        (abs(gap) for row in rows for gap in row['gaps'].values() if gap is not None),
        default=0.0,
    )
    for row in rows:
        row['gap_colors'] = {operator: gap_color(row['gaps'].get(operator), gap_scale_max) for operator in operators}
        row['weight_percent'] = row['max_points'] * 100.0 / global_max_points if row['max_points'] is not None and global_max_points > 0 else None
    title = _make_title('Scoring Table', context)
    return {
        'context': context,
        'title': title,
        'operators': operators,
        'baseline_operator': baseline_operator,
        'rows': rows,
        'total': total,
        'gap_scale_max': gap_scale_max,
        'gap_scale_colors': {'zero': _GAP_NEUTRAL, 'positive': _GAP_POSITIVE_MAX, 'negative': _GAP_NEGATIVE_MAX},
        'coverage_note': _coverage_note(rows, operators, environment, actual_environments),
        'gap_priority': [code for code in gap_priority_rank],
        'gap_direction': 'operator_minus_reference',
    }


def _build_gap_summary_table(
    score_table: dict[str, Any], gap_priority_rank: dict[str, int], baseline_aliases: list[str],
) -> dict[str, Any]:
    """Project all operator gaps into one priority-ordered comparison matrix."""
    baseline = score_table['baseline_operator']
    operators = [operator for operator in score_table['operators']
                 if not _same_baseline_identity(operator, baseline, baseline_aliases)]
    rows = [{
        **{key: row[key] for key in ('category', 'kpi', 'kpi_code', 'kpi_type')},
        'gaps': {operator: row['gaps'].get(operator) for operator in operators},
        'gap_colors': {operator: gap_color(row['gaps'].get(operator), score_table['gap_scale_max'])
                       for operator in operators},
    } for row in score_table['rows']]
    rows.sort(key=lambda row: gap_priority_rank.get(row['kpi_code'], len(gap_priority_rank)))
    return {
        'context': dict(score_table['context']),
        'title': _make_title(f'GAP Analysis: All vs {baseline}', score_table['context']),
        'operators': operators,
        'baseline_operator': baseline,
        'operator_styles': score_table.get('operator_styles', {}),
        'rows': rows,
        'total': {'gaps': {operator: score_table['total']['gaps'].get(operator) for operator in operators}},
        'gap_scale_max': score_table['gap_scale_max'],
        'gap_scale_colors': dict(score_table['gap_scale_colors']),
        'note': 'Operator − reference. Positive values are green; negative values are red. Missing comparisons are N/A.',
    }


def _build_gap_tables(
    score_table: dict[str, Any], gap_priority_rank: dict[str, int], baseline_aliases: list[str],
) -> list[dict[str, Any]]:
    tables = []
    baseline = score_table['baseline_operator']
    for operator in score_table['operators']:
        if _same_baseline_identity(operator, baseline, baseline_aliases):
            continue
        prioritized = []
        for row in score_table['rows']:
            gap = row['gaps'].get(operator)
            if gap is not None:
                prioritized.append({
                    'kpi_code': row['kpi_code'],
                    'category': row['category'],
                    'kpi': row['kpi'],
                    'gap_points': gap,
                    'kpi_type': row['kpi_type'],
                    'gap_color': gap_color(gap, score_table['gap_scale_max']),
                })
        prioritized.sort(key=lambda row: (gap_priority_rank.get(row['kpi_code'], len(gap_priority_rank)), -row['gap_points']))
        total_gap = score_table['total']['gaps'].get(operator)
        tables.append({
            'context': dict(score_table['context']),
            'title': _make_title(f'GAP Analysis: {operator} vs {baseline}', score_table['context']),
            'operator': operator,
            'baseline_operator': baseline,
            'operator_styles': score_table.get('operator_styles', {}),
            'rows': prioritized,
            'total_gap_points': total_gap,
            'gap_scale_max': score_table['gap_scale_max'],
            'gap_scale_colors': dict(score_table['gap_scale_colors']),
            'note': 'Positive values mean the compared operator scores above the reference; negative values mean it scores below.',
            'gap_direction': 'operator_minus_reference',
        })
    return tables


def _metric_value(record: dict[str, Any] | None, metric: dict[str, Any], environment: str) -> dict[str, Any]:
    if record is None:
        return {
            'points': None, 'complete': False, 'value': None, 'score': None, 'sample_count': 0,
            'threshold_band': 'Unavailable', 'color': THRESHOLD_COLORS['Unavailable'],
        }
    points = _number(_field(record, 'weighted_points', 'points', 'total_points'))
    raw_score = _number(_field(record, 'score', 'score_fraction'))
    maximum = _metric_max_points(metric, environment)
    if maximum is None:
        maximum = _number(_field(record, 'max_points', 'maximum_points'))
    score = raw_score if raw_score is not None else (points / maximum if points is not None and maximum else None)
    raw_value = _field(record, 'value', 'raw_value', 'kpi_value')
    explicit_complete = _field(record, 'complete', 'complete_coverage')
    complete = (points is not None and score is not None) if explicit_complete is None else bool(explicit_complete) and points is not None and score is not None
    threshold_band = _threshold_band(score, metric, environment, complete)
    return {
        'points': points,
        'complete': complete,
        'value': raw_value,
        'score': score,
        'sample_count': _integer(_field(record, 'sample_count', 'samples', 'count')),
        'threshold_band': threshold_band,
        'color': THRESHOLD_COLORS[threshold_band],
    }


def _combined_metric_value(
    code: str, operator: str, city_rows: list[dict[str, Any]],
    road_rows: list[dict[str, Any]], metric: dict[str, Any],
) -> dict[str, Any]:
    city = _metric_value(_find_metric_record(code, operator, city_rows), metric, 'DriveCity')
    road = _metric_value(_find_metric_record(code, operator, road_rows), metric, 'DriveConnectionroad')
    known_points = [cell['points'] for cell in (city, road) if cell['points'] is not None]
    points = sum(known_points) if known_points else None
    maximum = _metric_max_points(metric, 'Combined')
    score = points / maximum if points is not None and maximum else None
    complete = city['complete'] and road['complete']
    threshold_band = _threshold_band(score, metric, 'Combined', complete)
    return {
        'points': points,
        'complete': complete,
        'value': None,
        'score': score,
        'sample_count': city['sample_count'] + road['sample_count'],
        'threshold_band': threshold_band,
        'color': THRESHOLD_COLORS[threshold_band],
    }


def _signed_gap(
    baseline: dict[str, Any] | None, compared: dict[str, Any] | None,
    operator: str, baseline_operator: str, baseline_aliases: list[str] | None = None,
) -> float | None:
    if _same_baseline_identity(operator, baseline_operator, baseline_aliases or []):
        return 0.0 if compared and compared['complete'] else None
    if not baseline or not compared or not baseline['complete'] or not compared['complete']:
        return None
    if baseline['points'] is None or compared['points'] is None:
        return None
    return _clean_number(compared['points'] - baseline['points'])


def _find_metric_record(code: str, operator: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    found = None
    for record in records:
        row_code = _record_view_code(record)
        row_operator = _operator_name(record)
        if row_code == code and row_operator == operator:
            found = record
    return found


def _metrics_for_context(
    context: dict[str, Any], include_dataset_type: bool, metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not include_dataset_type or not context.get('dataset_type'):
        return list(metrics)
    kind = _canonical_dataset_type(context['dataset_type'])
    if kind is None:
        return list(metrics)
    return [metric for metric in metrics if metric.get('source_kind', '').casefold() == kind.casefold()]


def _unknown_metrics(records: list[dict[str, Any]], metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    unknown: dict[str, dict[str, Any]] = {}
    known_codes = {metric['code'] for metric in metrics}
    for record in records:
        code = _record_view_code(record)
        if code and code in known_codes:
            continue
        label = str(_field(record, 'kpi', 'metric', 'name') or '').strip()
        if not code and not label:
            continue
        fallback = _fallback_kpi_label(code) if code else label
        stable_code = str(code) if code else f"LEGACY-KPI:{_slug(label or 'unknown')}"
        spec = unknown.setdefault(stable_code, {
            'code': stable_code,
            'category': _field(record, 'category') or 'Other',
            'kpi': label or fallback,
            'kpi_type': _field(record, 'kpi_type', 'type') or 'Unknown',
            'contexts': {},
        })
        if not spec.get('kpi'):
            spec['kpi'] = fallback
    return unknown


def _unknown_max_points(code: str, records: list[dict[str, Any]], environment: str) -> float | None:
    candidates: dict[str, float] = {}
    for record in records:
        if _record_view_code(record) == code:
            value = _number(_field(record, 'max_points', 'maximum_points'))
            if value is not None:
                row_environment = _canonical_environment(_field(record, 'environment'))
                if environment == 'Combined':
                    candidates[row_environment] = max(candidates.get(row_environment, value), value)
                else:
                    candidates[environment] = max(candidates.get(environment, value), value)
    if not candidates:
        return None
    return sum(candidates.values()) if environment == 'Combined' else max(candidates.values())


def _metric_max_points(metric: dict[str, Any], environment: str) -> float | None:
    contexts = metric.get('contexts', {})
    if environment == 'Combined':
        city = _metric_max_points(metric, 'DriveCity')
        road = _metric_max_points(metric, 'DriveConnectionroad')
        return city + road if city is not None and road is not None else None
    canonical = _canonical_environment(environment)
    context = contexts.get(canonical)
    return _number(context.get('max_points')) if isinstance(context, dict) else None


def _threshold_band(score: float | None, metric: dict[str, Any], environment: str, complete: bool) -> str:
    if not complete or score is None:
        return 'Unavailable'
    contexts = metric.get('contexts', {})
    if environment == 'Combined':
        metric_contexts = [contexts.get('DriveCity'), contexts.get('DriveConnectionroad')]
    else:
        metric_contexts = [contexts.get(_canonical_environment(environment))]
    available = [context for context in metric_contexts
                 if isinstance(context, dict) and isinstance(context.get('thresholds'), dict)]
    if not available:
        return 'Unavailable'
    weights = [max(0.0, _number(context.get('max_points')) or 0.0) for context in available]
    weight_total = sum(weights)
    if not weight_total:
        weights = [1.0] * len(available)
        weight_total = float(len(available))
    anchors = {key: 0.0 for key in ('medium_score', 'high_score', 'ultra_score')}
    for context, weight in zip(available, weights):
        mapping = context.get('score_mapping') or {
            'medium_score': 0.8,
            'high_score': 0.95 if context['thresholds'].get('ultra') is not None else 1.0,
            'ultra_score': 1.0,
        }
        for key in anchors:
            anchors[key] += (_number(mapping.get(key)) or 0.0) * weight / weight_total
    has_ultra = any(context['thresholds'].get('ultra') is not None for context in available)
    if has_ultra and score >= anchors['ultra_score']:
        return 'UltraHigh'
    high_anchor = anchors['high_score']
    if score >= high_anchor:
        return 'High'
    if score >= anchors['medium_score']:
        return 'Medium'
    return 'Low'


def _blend_hex(start: str, end: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    start_rgb = tuple(int(start[index:index + 2], 16) for index in (1, 3, 5))
    end_rgb = tuple(int(end[index:index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(round(left + (right - left) * ratio) for left, right in zip(start_rgb, end_rgb))
    return '#{:02X}{:02X}{:02X}'.format(*mixed)


def _scope_key(record: dict[str, Any], include_dataset_type: bool) -> tuple[Any, ...]:
    values = []
    for field in _SCOPE_FIELDS:
        value = _field(record, field)
        if field == 'dataset_type' and not include_dataset_type:
            value = None
        values.append(_hashable(value))
    return tuple(values)


def _make_context(scope: tuple[Any, ...], environment: str, include_dataset_type: bool) -> dict[str, Any]:
    context = dict(zip(_SCOPE_FIELDS, scope))
    context['environment'] = environment
    if not include_dataset_type:
        context.pop('dataset_type', None)
    return context


def _canonical_environment(value: Any) -> str:
    text = str(value or '').strip()
    identity = re.sub(r'[^a-z0-9]+', '', text.casefold())
    if identity in {'drivecity', 'city', 'driveandcity'}:
        return 'DriveCity'
    if identity in {'driveconnectionroad', 'connectionroad', 'road', 'driveandroad'}:
        return 'DriveConnectionroad'
    if identity == 'combined':
        return 'Combined'
    return text or 'Unspecified'


def _canonical_dataset_type(value: Any) -> str | None:
    identity = _level_identity(value)
    return {'data': 'data', 'datasetkind': None, 'voice': 'voice', 'speech': 'speech'}.get(identity)


def _level_identity(value: Any) -> str:
    text = re.sub(r'[^a-z0-9]+', '', str(value or '').casefold())
    return {'datasettype': 'datasettype', 'datasetkind': 'datasettype', 'datatype': 'datasettype'}.get(text, text)


def _field(record: dict[str, Any], *names: str) -> Any:
    wanted = {_key(name) for name in names}
    for key, value in record.items():
        if _key(key) in wanted:
            return value
    return None


def _key(value: Any) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value).casefold())


def _record_code(record: dict[str, Any]) -> str | None:
    value = _field(record, 'kpi_code', 'code', 'metric_code')
    return str(value).strip() if value is not None and str(value).strip() else None


def _record_view_code(record: dict[str, Any]) -> str | None:
    code = _record_code(record)
    if code:
        return code
    label = str(_field(record, 'kpi', 'metric', 'name') or '').strip()
    return f"LEGACY-KPI:{_slug(label)}" if label else None


def _operator_name(record: dict[str, Any]) -> str | None:
    value = _field(record, 'operator', 'operator_name')
    return str(value).strip() if value is not None and str(value).strip() else None


def _operators_in(record: dict[str, Any]) -> set[str]:
    result = set()
    operator = _operator_name(record)
    if operator:
        result.add(operator)
    actual = _field(record, 'baseline_actual_operator')
    if actual is not None and str(actual).strip():
        result.add(str(actual).strip())
    for key in ('weighted_points', 'points', 'total_points', 'score', 'value'):
        values = _field(record, key)
        if isinstance(values, dict):
            result.update(str(name).strip() for name in values if str(name).strip())
    return result


def _operator_styles(operators: set[str], groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resolve configured aliases without merging historical measurement columns."""
    configured = {}
    for index, group in enumerate(groups):
        label = str(group.get('canonical') or '').strip()
        if not label:
            continue
        color = str(group.get('color') or '')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            color = '#365F91'
        try:
            position = int(group.get('position', index))
        except (TypeError, ValueError):
            position = index
        style = {'label': label, 'color': color.upper(), 'position': position}
        for alias in [label, *(group.get('aliases') or [])]:
            configured[str(alias).strip().casefold()] = style
    fallback_position = max((style['position'] for style in configured.values()), default=-1) + 1
    return {name: dict(configured.get(name.casefold(), {
        'label': name, 'color': '#365F91', 'position': fallback_position,
    })) for name in operators}


def _mapping_aliases(requested: str, groups: list[dict[str, Any]]) -> list[str]:
    requested_key = requested.strip().casefold()
    for group in groups:
        if not isinstance(group, dict):
            continue
        canonical = str(group.get('canonical') or '').strip()
        aliases = [str(value).strip() for value in group.get('aliases', []) if str(value).strip()]
        labels = [canonical, *aliases]
        if requested_key in {label.casefold() for label in labels if label}:
            return list(dict.fromkeys([requested, *(label for label in labels if label)]))
    return [requested]


def _operator_identity(name: str) -> str:
    identity = re.sub(r'[^a-z0-9]+', '', str(name).casefold())
    if identity.endswith('uk'):
        identity = identity[:-2]
    if identity in {'everythingeverywhere', 'everythingeverywhereuk'}:
        return 'ee'
    return identity


def _matching_baseline(operators: list[str], requested: str, aliases: list[str] | None = None) -> str:
    if requested in operators:
        return requested
    requested_identities = {_operator_identity(value) for value in [requested, *(aliases or [])] if str(value).strip()}
    matches = [operator for operator in operators if _operator_identity(operator) in requested_identities]
    return matches[0] if matches else requested


def _same_baseline_identity(operator: str, baseline: str, aliases: list[str] | None = None) -> bool:
    identities = {_operator_identity(value) for value in [baseline, *(aliases or [])] if str(value).strip()}
    return _operator_identity(operator) in identities


def _coverage_note(
    rows: list[dict[str, Any]], operators: list[str], environment: str,
    actual_environments: set[str],
) -> str:
    notes = []
    if environment == 'DriveCity' and 'DriveConnectionroad' not in actual_environments:
        notes.append('No DriveConnectionroad results are available for this aggregation context; Combined is not shown.')
    elif environment == 'DriveConnectionroad' and 'DriveCity' not in actual_environments:
        notes.append('No DriveCity results are available for this aggregation context; Combined is not shown.')
    weighted_rows = [row for row in rows if row.get('max_points') is None or (_number(row.get('max_points')) or 0.0) > 0]
    missing = sum(1 for row in weighted_rows
                  if any(not row['values'].get(operator, {}).get('complete', False) for operator in operators))
    if missing:
        notes.append(f'Incomplete KPI coverage: {missing} of {len(weighted_rows)} weighted KPI rows have at least one missing operator score.')
    return ' '.join(notes)


def _make_title(prefix: str, context: dict[str, Any]) -> str:
    labels = []
    for field in ('campaign', 'region', 'city', 'vendor', 'dataset_type', 'environment'):
        value = context.get(field)
        if value is not None and str(value).strip():
            labels.append(str(value))
    return f"{prefix} — {' · '.join(labels)}" if labels else prefix


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [record for record in value if isinstance(record, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return _clean_number(number) if math.isfinite(number) else None


def _integer(value: Any) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _clean_number(value: float) -> float:
    return 0.0 if value == 0 else value


def _hashable(value: Any) -> Any:
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _scope_sort_key(scope: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple('' if value is None else str(value).casefold() for value in scope)


def _environment_sort_key(environment: str) -> tuple[int, str]:
    try:
        return (_ENVIRONMENT_ORDER.index(environment), environment.casefold())
    except ValueError:
        return (len(_ENVIRONMENT_ORDER), environment.casefold())


def _fallback_kpi_label(code: str) -> str:
    return f'KPI {code}' if code else 'Unknown KPI'


def _slug(value: str) -> str:
    return re.sub(r'[^A-Z0-9]+', '-', value.upper()).strip('-') or 'UNKNOWN'
