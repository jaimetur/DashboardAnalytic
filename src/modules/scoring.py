"""Source-grounded NetCheck 2026Q2 KPI aggregation and ranking points."""
from __future__ import annotations

import math
import re
from typing import Iterable

import pandas as pd

from src.modules.column_names import column_identity, resolve_column_name
from src.modules.scoring_config import (
    configuration_hash,
    validate_scoring_configuration,
)

# Semantic engine version only. Configuration identity is added to job versions
# after the workspace snapshot has been supplied explicitly.
METHOD_VERSION = 'campaign-gap-v2'
_SHARED = ['Operator', 'Campaign', 'G_Level_1', 'G_Level_2']
_FIELDS = {
    'data': ['Test_Name', 'Test_Result', 'Mean_Data_Rate', 'Transfer_Duration', 'Type_of_Test',
             'http_Browser_Transferred_Bytes', 'http_Browser_1MB_Reached_Duration',
             'VideoStream_Time_to_First_Picture', 'Irritating_Video_Playout', 'Packets_Lost',
             'Packets_Discarded', 'Packets_Corrupted', 'Packets_Not_Sent', 'Packets_Sent',
             'Interactivity_RTT_Median'],
    'voice': ['Session_Type', 'Call_Status', 'Call_Setup_Time', 'Disturbed_and_Impaired_Call', 'Test_Status'],
    'speech': ['Session_Type', 'LQ'],
}


def required_input_columns(kind: str, levels: Iterable[str] = ()) -> list[str]:
    """Return projected source fields, using the application's shared aliases."""
    fields = _SHARED + _FIELDS.get(kind, [])
    for level in levels:
        identity = column_identity(level)
        field = 'Dataset_Kind' if identity in {'datasettype', 'datasetkind'} else ('Vendor' if identity == 'ranvendor' else level)
        if field not in fields:
            fields = fields + [field]
    return list(dict.fromkeys(fields))


def _required_configuration(configuration: dict | None) -> dict:
    if configuration is None:
        raise ValueError('A scoring configuration is required. Import a Scoring Configuration before calculating scoring.')
    return validate_scoring_configuration(configuration)


def method_version_for_configuration(configuration: dict) -> str:
    """Return a calculation version bound to every scoring setting."""
    snapshot = _required_configuration(configuration)
    return f"{snapshot['version']}-{METHOD_VERSION}-{configuration_hash(snapshot)[:16]}"


def interpolate_score(
    value: float, thresholds: dict, ultra: float | None = None,
    score_mapping: dict | None = None,
) -> float:
    """Apply configurable piecewise interpolation, clamped to the unit interval."""
    specification = thresholds.get('ultra')
    if isinstance(specification, dict) and specification.get('rule') == 'fixed':
        ultra = specification['value']
    elif isinstance(specification, (int, float)) and not isinstance(specification, bool):
        ultra = float(specification)
    has_ultra = specification is not None and ultra is not None
    mapping = score_mapping or {
        'low_score': 0.0, 'medium_score': 0.8,
        'high_score': 0.95 if has_ultra else 1.0, 'ultra_score': 1.0,
    }
    anchors = [(thresholds['low'], mapping['low_score']),
               (thresholds['medium'], mapping['medium_score']),
               (thresholds['high'], mapping['high_score'])]
    # A dynamic best value can be inside the fixed thresholds. Excel's nested
    # IF evaluates the Low/Medium/High branches before its final Ultra branch.
    sign = 1 if thresholds['high'] >= thresholds['low'] else -1
    normalized = [(sign * x, y) for x, y in anchors]
    x = sign * value
    if x <= normalized[0][0]:
        return float(mapping['low_score'])
    for (left, low_score), (right, high_score) in zip(normalized, normalized[1:]):
        if x <= right:
            if right == left:
                return float(high_score)
            return low_score + (x - left) / (right - left) * (high_score - low_score)
    if not has_ultra:
        return float(mapping['high_score'])
    high = normalized[-1][0]
    upper = sign * ultra
    if upper <= high or x >= upper:
        return float(mapping['ultra_score'])
    if upper == high:
        return float(mapping['ultra_score'])
    return mapping['high_score'] + (x - high) / (upper - high) * (mapping['ultra_score'] - mapping['high_score'])


def _numeric(frame: pd.DataFrame, field: str) -> pd.Series:
    return pd.to_numeric(frame[field], errors='coerce').replace([float('inf'), -float('inf')], float('nan'))


def _filter(frame: pd.DataFrame, filters: dict) -> pd.DataFrame:
    for field, rule in filters.items():
        if field.endswith(' contains'):
            field = field.removesuffix(' contains')
            if isinstance(rule, list):
                for fragment in rule:
                    frame = frame[frame[field].astype('string').str.contains(fragment, regex=False, na=False)]
            elif isinstance(rule, str):
                contains = re.fullmatch(r'contains ([^\r\n]{1,256})', rule)
                if not contains:
                    raise ValueError(f'Unsupported scoring filter: {field} contains {rule}')
                frame = frame[frame[field].astype('string').str.contains(contains.group(1), regex=False, na=False)]
            else:
                raise ValueError(f'Unsupported scoring filter: {field} contains {rule}')
        elif isinstance(rule, list):
            frame = frame[frame[field].isin(rule)]
        elif isinstance(rule, str):
            contains = re.fullmatch(r'contains ([^\r\n]{1,256})', rule)
            numeric_threshold = re.fullmatch(
                r'>= ([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)', rule,
            )
            if contains:
                frame = frame[frame[field].astype('string').str.contains(contains.group(1), regex=False, na=False)]
            elif numeric_threshold and math.isfinite(float(numeric_threshold.group(1))):
                frame = frame[_numeric(frame, field) >= float(numeric_threshold.group(1))]
            else:
                raise ValueError(f'Unsupported scoring filter: {field} {rule}')
        else:
            raise ValueError(f'Unsupported scoring filter: {field} {rule}')
    return frame


def _condition(frame: pd.DataFrame, expression: str) -> pd.Series:
    if ' AND ' in expression:
        left, right = expression.split(' AND ', 1)
        return _condition(frame, left) & _condition(frame, right)
    contains = re.fullmatch(r'CONTAINS\((\w+), "([^"]+)"\)', expression)
    if contains:
        return frame[contains[1]].astype('string').str.contains(contains[2], regex=False, na=False)
    if expression.endswith(' IS NOT NULL'):
        return frame[expression.removesuffix(' IS NOT NULL')].notna()
    comparison = re.fullmatch(r'(\w+) (==|<=|>=|>) (.+)', expression)
    if not comparison:
        raise ValueError(f'Unsupported scoring condition: {expression}')
    field, operator, literal = comparison.groups()
    series = frame[field] if literal.startswith('"') else _numeric(frame, field)
    value = literal.strip('"') if literal.startswith('"') else float(literal)
    return {'==': series.eq, '<=': series.le, '>=': series.ge, '>': series.gt}[operator](value).fillna(False)


def _aggregate(frame: pd.DataFrame, metric: dict) -> tuple[float | None, int]:
    calculation = metric['calculation']
    frame = _filter(frame, calculation['filters'])
    formula = calculation['formula']
    aggregate = re.fullmatch(r'(AVG|MEDIAN|PCT90)\((\w+)\)', formula)
    if aggregate:
        operation, field = aggregate.groups()
        values = _numeric(frame, field).dropna()
        if values.empty:
            return None, 0
        value = values.mean() if operation == 'AVG' else (values.median() if operation == 'MEDIAN' else values.quantile(.9, interpolation='linear'))
        return float(value), len(values)
    if formula == '100 * SUM(totalpacketlost) / SUM(Packets_Sent)':
        sent = _numeric(frame, 'Packets_Sent')
        denominator = sent.sum(min_count=1)
        lost = sum(_numeric(frame, field).fillna(0).map(math.trunc) if field == 'Packets_Corrupted' else _numeric(frame, field).fillna(0)
                   for field in ['Packets_Lost', 'Packets_Discarded', 'Packets_Corrupted', 'Packets_Not_Sent'])
        return (float(100 * lost.sum() / denominator), int(sent.notna().sum())) if denominator > 0 else (None, 0)
    ratio = re.fullmatch(r'100 \* (?:SUM|COUNT)\((.+)\) / COUNT\((\w+)\)', formula)
    if not ratio:
        raise ValueError(f'Unsupported scoring formula: {formula}')
    expression, denominator_field = ratio.groups()
    count = int(frame[denominator_field].notna().sum())
    if not count:
        return None, 0
    return float(100 * _condition(frame, expression).sum() / count), count


def _key_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', value.casefold()).strip('_')


def _operator_identity(value: str) -> str:
    identity = column_identity(value)
    if identity.endswith('uk'):
        identity = identity[:-2]
    return 'ee' if identity in {'ee', 'everythingeverywhere'} else identity


def _is_baseline(value: str, baseline_operator: str, baseline_aliases: Iterable[str]) -> bool:
    aliases = {str(baseline_operator), *(str(alias) for alias in baseline_aliases)}
    identities = {_operator_identity(alias) for alias in aliases if alias.strip()}
    return _operator_identity(str(value)) in identities


def calculate_scoring(
    frames: dict[str, pd.DataFrame], levels: Iterable[str] = ('Operator',),
    baseline_operator: str = 'EE', configuration: dict | None = None,
    baseline_aliases: Iterable[str] = (),
) -> dict:
    """Calculate campaign-separated scores without reallocating missing weights."""
    config = _required_configuration(configuration)
    metrics = config['metrics']
    metric_by_code = {metric['code']: metric for metric in metrics}
    method_version = method_version_for_configuration(config)
    baseline_aliases = list(dict.fromkeys(
        [str(baseline_operator), *(str(alias).strip() for alias in baseline_aliases if str(alias).strip())]
    ))
    dimensions = []
    for level in levels:
        identity = column_identity(level)
        canonical = {'operator': 'Operator', 'region': 'Region', 'city': 'City', 'vendor': 'Vendor',
                     'ranvendor': 'Vendor', 'datasettype': 'Dataset Type', 'datasetkind': 'Dataset Type'}.get(identity)
        if canonical is None:
            raise ValueError(f'Unsupported scoring level: {level}')
        if canonical not in dimensions:
            dimensions.append(canonical)
    if 'Operator' not in dimensions:
        dimensions.append('Operator')
    group_fields = ['Campaign'] + dimensions + ['environment']
    keys = [_key_name(field) for field in group_fields]
    rows, warnings = [], ['Campaigns are scored separately; the supplied Tableau Prep flow pools campaigns.']
    for missing_kind in _FIELDS.keys() - frames.keys():
        warnings.append(f'{missing_kind.title()} source is missing; full benchmark coverage is unavailable.')
    for kind, source in frames.items():
        if kind not in _FIELDS or source.empty:
            continue
        frame = pd.DataFrame(index=source.index)
        for field in required_input_columns(kind, dimensions):
            resolved = resolve_column_name(source.columns, field)
            if resolved:
                frame[field] = source[resolved]
        if 'Dataset Type' in dimensions:
            frame['Dataset Type'] = kind.title()
        missing_group = [field for field in _SHARED + [d for d in dimensions if d != 'Dataset Type'] if field not in frame]
        if missing_group:
            warnings.append(f'{kind.title()}: missing grouping columns: {", ".join(missing_group)}; no scores calculated.')
            continue
        frame['environment'] = None
        for environment, context in config['scope']['environments'].items():
            mask = (frame['G_Level_1'] == context['g_level_1']) & (frame['G_Level_2'] == context['g_level_2'])
            frame.loc[mask, 'environment'] = environment
        valid = frame['environment'].notna() & frame['Operator'].notna() & frame['Campaign'].notna()
        if (~valid).any():
            warnings.append(f'{kind.title()}: {int((~valid).sum())} rows have unsupported or missing environment, operator or campaign and were excluded.')
        for values, group in frame[valid].groupby(group_fields, dropna=False, sort=False):
            metadata = dict(zip(keys, values))
            metadata = {key: (None if pd.isna(value) else value) for key, value in metadata.items()}
            for metric in (m for m in metrics if m['source_kind'] == kind):
                try:
                    value, count = _aggregate(group, metric)
                except KeyError as error:
                    value, count = None, 0
                    warnings.append(f'{kind.title()}: {metric["code"]} requires missing column {error.args[0]}.')
                context = metric['contexts'][metadata['environment']]
                rows.append({**metadata, 'kpi_code': metric['code'], 'kpi': metric['kpi'], 'category': metric['category'],
                             'dataset_type': kind.title(), 'kpi_type': metric.get('kpi_type'),
                             'unit': metric.get('unit'), 'value': value, 'sample_count': count, 'score': None,
                             'weighted_points': None, 'max_points': context['max_points']})
    for row in rows:
        if row['value'] is None:
            continue
        metric = metric_by_code[row['kpi_code']]
        metric_context = metric['contexts'][row['environment']]
        thresholds = metric_context['thresholds']
        ultra = thresholds.get('ultra')
        if isinstance(ultra, dict) and ultra['rule'] in {'best_min', 'best_max'}:
            peers = [r['value'] for r in rows if r['kpi_code'] == row['kpi_code'] and r['value'] is not None
                     and all(r.get(key) == row.get(key) for key in keys if key != 'operator')]
            ultra_value = min(peers) if ultra['rule'] == 'best_min' else max(peers)
        else:
            ultra_value = None
        row['score'] = interpolate_score(row['value'], thresholds, ultra_value, metric_context['score_mapping'])
        row['weighted_points'] = row['score'] * row['max_points']
    totals = _totals(rows, keys, config)
    if any(not row['complete_coverage'] for row in totals):
        warnings.append('Incomplete KPI or environment coverage: partial points are shown without renormalizing weights; a complete benchmark score is unavailable.')
    gap = []
    for row in rows:
        if _is_baseline(str(row['operator']), baseline_operator, baseline_aliases):
            continue
        baseline = next((other for other in rows if _is_baseline(str(other['operator']), baseline_operator, baseline_aliases)
                         and other['kpi_code'] == row['kpi_code'] and all(other.get(key) == row.get(key) for key in keys if key != 'operator')), None)
        if baseline is None:
            warnings.append(f'Baseline {baseline_operator} is unavailable for one or more comparison groups.')
        elif baseline['weighted_points'] is not None and row['weighted_points'] is not None:
            gap.append({**{key: row.get(key) for key in keys}, 'dataset_type': row['dataset_type'], 'kpi': row['kpi'],
                        'kpi_code': row['kpi_code'], 'category': row['category'], 'kpi_type': row['kpi_type'],
                        'baseline_operator': baseline_operator,
                        'baseline_actual_operator': baseline['operator'], 'baseline_points': baseline['weighted_points'], 'operator_points': row['weighted_points'],
                        'gap_points': row['weighted_points'] - baseline['weighted_points']})
    gap_totals = []
    for row in totals:
        if _is_baseline(str(row['operator']), baseline_operator, baseline_aliases):
            continue
        baseline = next((other for other in totals if _is_baseline(str(other['operator']), baseline_operator, baseline_aliases)
                         and other['category'] == row['category']
                         and all(other.get(key) == row.get(key) for key in keys if key != 'operator')), None)
        if baseline is not None:
            complete = baseline['complete_coverage'] and row['complete_coverage']
            gap_totals.append({**{key: row.get(key) for key in keys}, 'category': row['category'],
                               'baseline_operator': baseline_operator, 'baseline_actual_operator': baseline['operator'],
                               'baseline_points': baseline['weighted_points'], 'operator_points': row['weighted_points'],
                               'gap_points': row['weighted_points'] - baseline['weighted_points'] if complete else None,
                               'complete_coverage': complete})
    return {'scoring': rows, 'totals': totals, 'charts': [dict(row) for row in totals], 'gap': gap,
            'gap_totals': gap_totals, 'warnings': list(dict.fromkeys(warnings)),
            'method_version': method_version, 'configuration': config,
            'configuration_hash': configuration_hash(config), 'gap_direction': 'operator_minus_reference',
            'baseline_aliases': baseline_aliases}


def _totals(rows: list[dict], keys: list[str], configuration: dict) -> list[dict]:
    config = _required_configuration(configuration)
    metrics = config['metrics']
    environments = config['scope']['environments']
    grouped = {}
    for row in rows:
        grouped.setdefault(tuple(row.get(key) for key in keys), []).append(row)
    totals = []
    categories = list(dict.fromkeys(metric['category'] for metric in metrics)) + ['Overall']
    for group, members in grouped.items():
        metadata = dict(zip(keys, group))
        for category in categories:
            expected = [m for m in metrics
                        if ('dataset_type' not in keys or m['source_kind'].title() == metadata['dataset_type'])
                        and (category == 'Overall' or m['category'] == category)
                        and m['contexts'][metadata['environment']]['max_points'] > 0]
            if not expected:
                zero_weight_metrics = [m for m in metrics
                                       if ('dataset_type' not in keys or m['source_kind'].title() == metadata['dataset_type'])
                                       and (category == 'Overall' or m['category'] == category)]
                if not zero_weight_metrics:
                    continue
            selected = [row for row in members if category == 'Overall' or row['category'] == category]
            active_codes = {metric['code'] for metric in expected}
            selected_active = [row for row in selected if row['kpi_code'] in active_codes]
            maximum = sum(m['contexts'][metadata['environment']]['max_points'] for m in expected)
            totals.append(_summary({**metadata, 'category': category}, selected, maximum,
                                   len(selected_active) == len(expected) and all(row['score'] is not None for row in selected_active)))
    combined = {}
    base_keys = [key for key in keys if key != 'environment'] + ['category']
    for row in totals:
        combined.setdefault(tuple(row.get(key) for key in base_keys), []).append(row)
    for group, members in combined.items():
        metadata = dict(zip(base_keys, group))
        expected = [m for m in metrics
                    if ('dataset_type' not in keys or m['source_kind'].title() == metadata['dataset_type'])
                    and (metadata['category'] == 'Overall' or m['category'] == metadata['category'])
                    and sum(m['contexts'][name]['max_points'] for name in environments if name in m['contexts']) > 0]
        maximum = sum(sum(m['contexts'][name]['max_points'] for name in environments if name in m['contexts'])
                      for m in expected)
        totals.append(_summary({**metadata, 'environment': 'Combined'}, members, maximum,
                               len(members) == 2 and all(row['complete_coverage'] for row in members), summary=True))
    return totals


def _summary(metadata: dict, members: list[dict], maximum: float, complete: bool, summary: bool = False) -> dict:
    points = sum(row['weighted_points'] or 0 for row in members)
    available = sum(row['available_points'] if summary else (row['max_points'] if row['score'] is not None else 0)
                    for row in members)
    return {**metadata, 'weighted_points': points, 'total_points': points, 'max_points': maximum,
            'available_points': available, 'score': points / maximum if complete and maximum > 0 else None,
            'complete_coverage': complete, 'sample_count': sum(row['sample_count'] for row in members)}
