"""Workspace-scoped configuration and validation for NetCheck scoring."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


CONFIGURATION_FORMAT = 'dashboard-analytic-scoring-configuration'
CONFIGURATION_FORMAT_VERSION = 1
_SCORE_ANCHORS = ('low_score', 'medium_score', 'high_score', 'ultra_score')
_CONTEXT_NAMES = ('DriveCity', 'DriveConnectionroad')
_METRIC_CODES = (
    'C5', 'C6', 'C7', 'C8', 'C9', 'C10', 'C11', 'C12', 'C13', 'C14', 'C15',
    'C17', 'C18', 'C19', 'C20', 'C21', 'C22', 'C23', 'C24', 'C25', 'C26',
    'C27', 'C28', 'C29', 'C30', 'C31', 'C32', 'C33', 'C34', 'C35', 'C36', 'C37',
)
_VOICE_CODES = frozenset({'C5', 'C6', 'C7', 'C10', 'C11', 'C14', 'C15'})
_SPEECH_CODES = frozenset({'C8', 'C9', 'C12', 'C13'})
_LOWER_IS_BETTER_CODES = frozenset({
    'C6', 'C7', 'C8', 'C10', 'C12', 'C14', 'C18', 'C20', 'C31', 'C34', 'C35', 'C36', 'C37',
})
_SOURCE_KIND_BY_CODE = {
    code: ('voice' if code in _VOICE_CODES else 'speech' if code in _SPEECH_CODES else 'data')
    for code in _METRIC_CODES
}
_DIRECTION_BY_CODE = {
    code: ('lower_is_better' if code in _LOWER_IS_BETTER_CODES else 'higher_is_better')
    for code in _METRIC_CODES
}
_SCOPE_ENVIRONMENTS = {
    'DriveCity': {'sheet': 'DriveCity', 'g_level_1': 'Drive', 'g_level_2': 'City'},
    'DriveConnectionroad': {
        'sheet': 'DriveConnectionroad', 'g_level_1': 'Drive', 'g_level_2': 'Connectionroad',
    },
}
_SCOPE_IDENTITIES = {
    'environment_fields': ['G_Level_1', 'G_Level_2'],
    'environment_mapping': {
        'Drive + City': 'DriveCity',
        'Drive + Connectionroad': 'DriveConnectionroad',
    },
    'tableau_group_key': '[Operator] + "_" + [G_Level_1] + "_" + [G_Level_2]',
    'tableau_aggregate_group_by': ['dataset'],
    'campaign_in_tableau_group_key': False,
}
_FORMULA_FIELDS_BY_KIND = {
    'data': frozenset({
        'Test_Name', 'Test_Result', 'Mean_Data_Rate', 'Transfer_Duration', 'Type_of_Test',
        'http_Browser_Transferred_Bytes', 'http_Browser_1MB_Reached_Duration',
        'VideoStream_Time_to_First_Picture', 'Irritating_Video_Playout', 'Packets_Lost',
        'Packets_Discarded', 'Packets_Corrupted', 'Packets_Not_Sent', 'Packets_Sent',
        'Interactivity_RTT_Median',
    }),
    'voice': frozenset({
        'Session_Type', 'Call_Status', 'Call_Setup_Time', 'Disturbed_and_Impaired_Call', 'Test_Status',
    }),
    'speech': frozenset({'Session_Type', 'LQ'}),
}
_PROVENANCE_KEYS = frozenset({'title', 'sources', 'gap_example', 'validation_examples', 'discrepancies'})
_DERIVED_SCOPE_FIELDS = frozenset({'total_max_points', 'allocation_note'})
_DERIVED_ENVIRONMENT_FIELDS = frozenset({'total_points', 'weight_share'})
_FORMULA_IDENTIFIER = r'[A-Za-z_]\w*'
_NUMBER_LITERAL = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
_TOTAL_PACKET_LOST_FORMULA = (
    'IFNULL(Packets_Lost,0) + IFNULL(Packets_Discarded,0) + '
    'IFNULL(INT(Packets_Corrupted),0) + IFNULL(Packets_Not_Sent,0)'
)


def unwrap_scoring_configuration_payload(payload: object) -> dict[str, Any]:
    """Unwrap a supported import envelope or copy a bare legacy configuration."""
    if not isinstance(payload, dict):
        raise ValueError('Scoring configuration must be an object.')
    if 'format' in payload:
        if payload.get('format') != CONFIGURATION_FORMAT:
            raise ValueError('Unsupported scoring configuration file format.')
        version = payload.get('version')
        if (not isinstance(version, int) or isinstance(version, bool)
                or version != CONFIGURATION_FORMAT_VERSION):
            raise ValueError('Unsupported scoring configuration file version.')
        payload = payload.get('configuration')
        if not isinstance(payload, dict):
            raise ValueError('This file does not contain a scoring configuration to import.')
    return copy.deepcopy(payload)


def _finite_number(value: Any, label: str, *, minimum: float | None = None,
                   maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f'{label} must be a finite number.')
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f'{label} must be at least {minimum:g}.')
    if maximum is not None and number > maximum:
        raise ValueError(f'{label} must be at most {maximum:g}.')
    return number


def _refresh_weight_totals(configuration: dict[str, Any]) -> None:
    metrics = configuration['metrics']
    environments = configuration['scope']['environments']
    totals = {
        name: sum(float(metric['contexts'][name]['max_points']) for metric in metrics)
        for name in _CONTEXT_NAMES
    }
    grand_total = sum(totals.values())
    for name, total_points in totals.items():
        environments[name]['total_points'] = total_points
        environments[name]['weight_share'] = total_points / grand_total if grand_total else 0.0
    scope = configuration['scope']
    scope['total_max_points'] = grand_total
    scope['allocation_note'] = 'Maximum points and weight shares derive from configured KPI weights.'


def _validate_scope(scope: Any) -> None:
    if not isinstance(scope, dict):
        raise ValueError('Scoring configuration scope is missing.')
    for key, expected in _SCOPE_IDENTITIES.items():
        if scope.get(key) != expected:
            raise ValueError(f'Scoring scope field {key} is unsupported.')
    environments = scope.get('environments')
    if not isinstance(environments, dict) or set(environments) != set(_CONTEXT_NAMES):
        raise ValueError('Scoring scope must contain exactly the supported environments.')
    for name, identity in _SCOPE_ENVIRONMENTS.items():
        environment = environments.get(name)
        if not isinstance(environment, dict):
            raise ValueError(f'Scoring scope {name} configuration is missing.')
        for key, expected in identity.items():
            if environment.get(key) != expected:
                raise ValueError(f'Scoring scope {name} field {key} is unsupported.')


def _validate_interpolation(interpolation: Any) -> dict[str, Any]:
    if not isinstance(interpolation, dict):
        raise ValueError('Scoring interpolation settings are missing.')
    expected = {
        'score_range': [0.0, 1.0],
        'method': 'piecewise_linear',
        'clamp_to_range': True,
    }
    score_range = interpolation.get('score_range')
    if not isinstance(score_range, list) or len(score_range) != 2:
        raise ValueError('Scoring interpolation score_range must contain two supported anchors.')
    normalized_range = [
        _finite_number(value, f'interpolation score_range[{index}]')
        for index, value in enumerate(score_range)
    ]
    if normalized_range != expected['score_range']:
        raise ValueError('Scoring interpolation field score_range is source-defined and cannot be changed.')
    for key in ('medium_score', 'high_score_without_ultra', 'high_score_with_ultra', 'ultra_score'):
        _finite_number(interpolation.get(key), f'interpolation {key}', minimum=0, maximum=1)
    if not (interpolation['medium_score'] <= interpolation['high_score_with_ultra'] <= interpolation['ultra_score']
            and interpolation['medium_score'] <= interpolation['high_score_without_ultra'] <= interpolation['ultra_score']):
        raise ValueError('Scoring interpolation anchors must increase in score quality order.')
    for key in ('method', 'clamp_to_range'):
        supplied = interpolation.get(key)
        matches = supplied == expected[key] and (key != 'clamp_to_range' or isinstance(supplied, bool))
        if not matches:
            raise ValueError(f'Scoring interpolation field {key} is source-defined and cannot be changed.')
    return copy.deepcopy(interpolation)


def _validate_ultra(value: Any, direction: str, label: str) -> float | dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _finite_number(value, label)
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a number, null or a best-value mapping.')
    rule = value.get('rule')
    if rule == 'fixed':
        if set(value) != {'rule', 'value'}:
            raise ValueError(f'{label} fixed mapping must contain only rule and value.')
        return _finite_number(value.get('value'), f'{label}.value')
    expected_rule = 'best_max' if direction == 'higher_is_better' else 'best_min'
    if rule != expected_rule:
        raise ValueError(f'{label} must use {expected_rule} for this KPI direction.')
    if set(value) - {'rule', 'source_formula'}:
        raise ValueError(f'{label} contains unsupported best-value settings.')
    formula = value.get('source_formula')
    if formula is not None and (not isinstance(formula, str) or not formula.strip()):
        raise ValueError(f'{label}.source_formula must be a non-empty string when provided.')
    return copy.deepcopy(value)


def _condition_fields(expression: str, kind: str, label: str) -> set[str]:
    if len(expression) > 1024:
        raise ValueError(f'{label} condition is too long.')
    if ' AND ' in expression:
        pieces = expression.split(' AND ')
        if len(pieces) > 5 or any(not piece for piece in pieces):
            raise ValueError(f'{label} contains an unsupported condition.')
        fields: set[str] = set()
        for piece in pieces:
            fields.update(_condition_fields(piece, kind, label))
        return fields
    contains = re.fullmatch(rf'CONTAINS\(({_FORMULA_IDENTIFIER}), "([^"\\]+)"\)', expression)
    if contains:
        fields = {contains.group(1)}
    else:
        not_null = re.fullmatch(rf'({_FORMULA_IDENTIFIER}) IS NOT NULL', expression)
        comparison = re.fullmatch(
            rf'({_FORMULA_IDENTIFIER}) (==|<=|>=|>) ("[^"\\]+"|{_NUMBER_LITERAL})', expression,
        )
        if not_null:
            fields = {not_null.group(1)}
        elif comparison:
            if comparison.group(2) != '==' and comparison.group(3).startswith('"'):
                raise ValueError(f'{label} only supports string equality comparisons.')
            fields = {comparison.group(1)}
        else:
            raise ValueError(f'{label} contains an unsupported condition.')
    if not fields <= _FORMULA_FIELDS_BY_KIND[kind]:
        raise ValueError(f'{label} references an unsupported {kind} field.')
    return fields


def _validate_formula(formula: Any, kind: str, label: str) -> None:
    if not isinstance(formula, str) or not formula.strip() or len(formula) > 1024:
        raise ValueError(f'{label} formula must be a supported expression.')
    aggregate = re.fullmatch(rf'(AVG|MEDIAN|PCT90)\(({_FORMULA_IDENTIFIER})\)', formula)
    if aggregate:
        if aggregate.group(2) not in _FORMULA_FIELDS_BY_KIND[kind]:
            raise ValueError(f'{label} formula references an unsupported {kind} field.')
        return
    if formula == '100 * SUM(totalpacketlost) / SUM(Packets_Sent)' and kind == 'data':
        return
    ratio = re.fullmatch(rf'100 \* (SUM|COUNT)\((.+)\) / COUNT\(({_FORMULA_IDENTIFIER})\)', formula)
    if not ratio:
        raise ValueError(f'{label} formula is unsupported.')
    numerator = ratio.group(2).strip()
    numerator_fields = _condition_fields(numerator, kind, label)
    denominator = ratio.group(3)
    if denominator not in _FORMULA_FIELDS_BY_KIND[kind]:
        raise ValueError(f'{label} formula references an unsupported {kind} denominator field.')
    if not numerator_fields:
        raise ValueError(f'{label} formula must reference a source field.')


def _validate_calculation(metric: dict[str, Any]) -> dict[str, Any]:
    code = metric['code']
    kind = _SOURCE_KIND_BY_CODE[code]
    calculation = metric.get('calculation')
    label = f'KPI {code} calculation'
    if not isinstance(calculation, dict):
        raise ValueError(f'{label} is missing.')
    required = {'source_kind', 'formula', 'filters', 'denominator'}
    if calculation.get('formula') == '100 * SUM(totalpacketlost) / SUM(Packets_Sent)':
        required.add('totalpacketlost')
        if calculation.get('totalpacketlost') != _TOTAL_PACKET_LOST_FORMULA:
            raise ValueError(f'{label} totalpacketlost expression is unsupported.')
    if set(calculation) != required:
        raise ValueError(f'{label} contains missing or unsupported calculation fields.')
    if calculation.get('source_kind') != kind:
        raise ValueError(f'{label} source_kind does not match the supported KPI identity.')
    _validate_formula(calculation.get('formula'), kind, label)
    denominator = calculation.get('denominator')
    if not isinstance(denominator, str) or not denominator.strip() or len(denominator) > 256:
        raise ValueError(f'{label} denominator must be a short description.')
    filters = calculation.get('filters')
    if not isinstance(filters, dict):
        raise ValueError(f'{label} filters must be an object.')
    allowed_fields = _FORMULA_FIELDS_BY_KIND[kind]
    for raw_field, rule in filters.items():
        if not isinstance(raw_field, str):
            raise ValueError(f'{label} filter field must be text.')
        field = raw_field.removesuffix(' contains') if raw_field.endswith(' contains') else raw_field
        if field not in allowed_fields:
            raise ValueError(f'{label} filter references an unsupported {kind} field.')
        if raw_field.endswith(' contains') and not isinstance(rule, list):
            raise ValueError(f'{label} contains filters must use a list of text fragments.')
        if isinstance(rule, list):
            if not rule or any(not isinstance(item, str) or not item.strip() or len(item) > 256 for item in rule):
                raise ValueError(f'{label} list filters must contain non-empty text values.')
        elif isinstance(rule, str):
            if re.fullmatch(r'contains [^\r\n]{1,256}', rule):
                continue
            numeric_filter = re.fullmatch(rf'>= ({_NUMBER_LITERAL})', rule)
            if numeric_filter and math.isfinite(float(numeric_filter.group(1))):
                continue
            raise ValueError(f'{label} contains an unsupported filter rule.')
        else:
            raise ValueError(f'{label} contains an unsupported filter rule.')
    return copy.deepcopy(calculation)


def _score_mapping_from_interpolation(interpolation: dict[str, Any], context: dict[str, Any]) -> dict[str, float]:
    score_range = interpolation['score_range']
    has_ultra = context.get('thresholds', {}).get('ultra') is not None
    return {
        'low_score': float(score_range[0]),
        'medium_score': float(interpolation['medium_score']),
        'high_score': float(interpolation['high_score_with_ultra' if has_ultra else 'high_score_without_ultra']),
        'ultra_score': float(interpolation['ultra_score']),
    }


def _validate_metric_context(metric: dict[str, Any], name: str, interpolation: dict[str, Any]) -> dict[str, Any]:
    label = f"{metric['code']} {name}"
    context = metric['contexts'].get(name)
    if not isinstance(context, dict):
        raise ValueError(f'{label} configuration is missing.')
    maximum = _finite_number(context.get('max_points'), f'{label} max_points', minimum=0)
    thresholds = context.get('thresholds')
    if not isinstance(thresholds, dict) or set(thresholds) != {'low', 'medium', 'high', 'ultra'}:
        raise ValueError(f'{label} thresholds must contain low, medium, high and ultra.')
    low = _finite_number(thresholds['low'], f'{label} low threshold')
    medium = _finite_number(thresholds['medium'], f'{label} medium threshold')
    high = _finite_number(thresholds['high'], f'{label} high threshold')
    direction = metric['direction']
    ultra = _validate_ultra(thresholds['ultra'], direction, f'{label} ultra threshold')
    if direction == 'higher_is_better':
        monotonic = low <= medium <= high
        ultra_valid = not isinstance(ultra, (int, float)) or ultra >= high
    else:
        monotonic = low >= medium >= high
        ultra_valid = not isinstance(ultra, (int, float)) or ultra <= high
    if not monotonic or not ultra_valid:
        raise ValueError(f'{label} thresholds must increase in KPI quality order.')
    normalized_thresholds = {'low': low, 'medium': medium, 'high': high, 'ultra': ultra}
    mapping = context.get('score_mapping')
    if mapping is None:
        mapping = _score_mapping_from_interpolation(
            interpolation, {**context, 'thresholds': normalized_thresholds},
        )
    if not isinstance(mapping, dict) or set(mapping) != set(_SCORE_ANCHORS):
        raise ValueError(f'{label} score_mapping must contain the four score anchors.')
    validated_mapping = {
        anchor: _finite_number(mapping[anchor], f'{label} {anchor}', minimum=0, maximum=1)
        for anchor in _SCORE_ANCHORS
    }
    if list(validated_mapping.values()) != sorted(validated_mapping.values()):
        raise ValueError(f'{label} score anchors must be monotonic.')
    return {
        **copy.deepcopy(context),
        'max_points': maximum,
        'thresholds': normalized_thresholds,
        'score_mapping': validated_mapping,
    }


def validate_scoring_configuration(payload: object) -> dict[str, Any]:
    """Validate a self-contained workspace configuration without reading seed files."""
    configuration = unwrap_scoring_configuration_payload(payload)
    required = {'version', 'scope', 'interpolation', 'metrics'}
    if not required <= set(configuration):
        raise ValueError('Scoring configuration must include version, scope, interpolation and metrics.')
    version = configuration.get('version')
    if not isinstance(version, str) or not version.strip():
        raise ValueError('Scoring configuration version must be a non-empty string.')
    _validate_scope(configuration.get('scope'))
    interpolation = _validate_interpolation(configuration.get('interpolation'))
    supplied_metrics = configuration.get('metrics')
    if not isinstance(supplied_metrics, list) or len(supplied_metrics) != len(_METRIC_CODES):
        raise ValueError(f'Scoring configuration must contain all {len(_METRIC_CODES)} supported KPIs.')
    validated_metrics: list[dict[str, Any]] = []
    for code, supplied in zip(_METRIC_CODES, supplied_metrics):
        if not isinstance(supplied, dict) or supplied.get('code') != code:
            raise ValueError('KPI codes and their supported source order cannot be changed.')
        kind = _SOURCE_KIND_BY_CODE[code]
        direction = _DIRECTION_BY_CODE[code]
        if supplied.get('source_kind') != kind or supplied.get('direction') != direction:
            raise ValueError(f'KPI {code} source_kind or direction does not match its supported identity.')
        for key in ('category', 'kpi'):
            value = supplied.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'KPI {code} {key} must be non-empty text.')
        kpi_type = supplied.get('kpi_type')
        if not isinstance(kpi_type, str) or not kpi_type.strip():
            raise ValueError(f'KPI {code} kpi_type must be non-empty text.')
        calculation = _validate_calculation(supplied)
        contexts = supplied.get('contexts')
        if not isinstance(contexts, dict) or set(contexts) != set(_CONTEXT_NAMES):
            raise ValueError(f'KPI {code} must contain both supported scoring environments.')
        metric = copy.deepcopy(supplied)
        metric.update({
            'code': code,
            'source_kind': kind,
            'direction': direction,
            'kpi_type': kpi_type.strip(),
            'calculation': calculation,
            'contexts': {
                name: _validate_metric_context({**supplied, 'contexts': contexts}, name, interpolation)
                for name in _CONTEXT_NAMES
            },
        })
        validated_metrics.append(metric)
    priority = configuration.get('gap_priority', list(_METRIC_CODES))
    if (not isinstance(priority, list) or any(not isinstance(code, str) for code in priority)
            or len(priority) != len(_METRIC_CODES) or len(set(priority)) != len(priority)
            or set(priority) != set(_METRIC_CODES)):
        raise ValueError('GAP priority must list every supported KPI code exactly once.')
    validated = copy.deepcopy(configuration)
    validated['metrics'] = validated_metrics
    validated['gap_priority'] = list(priority)
    _refresh_weight_totals(validated)
    if validated['scope']['total_max_points'] <= 0:
        raise ValueError('At least one KPI weight must be greater than zero.')
    if any(validated['scope']['environments'][name]['total_points'] <= 0 for name in _CONTEXT_NAMES):
        raise ValueError('Each scoring environment must have positive maximum points.')
    return validated


def _normalize_initial_configuration(payload: dict[str, Any]) -> dict[str, Any]:
    configuration = copy.deepcopy(payload)
    metrics = configuration.get('metrics')
    interpolation = configuration.get('interpolation')
    if not isinstance(metrics, list) or not isinstance(interpolation, dict):
        raise ValueError('Scoring seed must contain metrics and interpolation settings.')
    interpolation = _validate_interpolation(interpolation)
    configuration.setdefault('gap_priority', [str(metric.get('code', '')) for metric in metrics])
    for metric in metrics:
        contexts = metric.get('contexts') if isinstance(metric, dict) else None
        if not isinstance(contexts, dict):
            continue
        for context in contexts.values():
            if not isinstance(context, dict):
                continue
            thresholds = context.get('thresholds')
            if isinstance(thresholds, dict) and isinstance(thresholds.get('ultra'), dict):
                ultra = thresholds['ultra']
                if ultra.get('rule') == 'fixed' and 'value' in ultra:
                    thresholds['ultra'] = ultra['value']
            if 'score_mapping' not in context:
                context['score_mapping'] = _score_mapping_from_interpolation(interpolation, context)
    return validate_scoring_configuration(configuration)


def load_initial_scoring_configuration(path: Path | str) -> dict[str, Any]:
    """Explicitly read and normalize a user-selected scoring seed/import file."""
    if path is None or not str(path).strip():
        raise ValueError('An explicit scoring configuration file path is required.')
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f'Unable to read scoring configuration file: {error}') from error
    configuration = unwrap_scoring_configuration_payload(raw)
    return _normalize_initial_configuration(configuration)


def default_scoring_configuration(path: Path | str) -> dict[str, Any]:
    """Deprecated explicit-path alias for tests or first-time seed import only."""
    return load_initial_scoring_configuration(path)


def _hash_projection(configuration: dict[str, Any]) -> dict[str, Any]:
    projection = copy.deepcopy(configuration)
    for key in _PROVENANCE_KEYS:
        projection.pop(key, None)
    interpolation = projection.get('interpolation')
    if isinstance(interpolation, dict):
        interpolation.pop('source_note', None)
    scope = projection.get('scope')
    if isinstance(scope, dict):
        for key in _DERIVED_SCOPE_FIELDS:
            scope.pop(key, None)
        for environment in scope.get('environments', {}).values():
            if isinstance(environment, dict):
                for key in _DERIVED_ENVIRONMENT_FIELDS:
                    environment.pop(key, None)
    for metric in projection.get('metrics', []):
        if not isinstance(metric, dict):
            continue
        metric.pop('source', None)
        for context in metric.get('contexts', {}).values():
            if isinstance(context, dict):
                context.pop('threshold_reference', None)
                context.pop('weight_reference', None)
    return projection


def configuration_hash(configuration: dict[str, Any]) -> str:
    """Return a stable digest of scoring settings, excluding descriptive provenance."""
    projection = _hash_projection(configuration)
    payload = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
