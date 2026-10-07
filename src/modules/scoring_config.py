"""Workspace-scoped configuration and validation for NetCheck scoring."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from src.branding import canonical_format

CONFIGURATION_FORMAT = 'drivetest-analyzer-scoring-configuration'
CONFIGURATION_FORMAT_VERSION = 1
PROFILE_COLLECTION_VERSION = 3
MAX_SCORING_METRICS = 256
MAX_SCORING_PROFILES = 64
MAX_SCORING_ENVIRONMENTS = 32
SUPPORTED_MAPPING_METHODS = frozenset({'piecewise_linear', 'piecewise_quadratic', 'piecewise_smoothstep'})
_PROFILE_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}\Z')
DEFAULT_AGGREGATION_HIERARCHY = ['Operator', 'Vendor', 'Region', 'City', 'Campaign']
_AGGREGATION_FIELDS = frozenset(DEFAULT_AGGREGATION_HIERARCHY)
# Levels added after a hierarchy was saved; a saved hierarchy without them gets them in
# their default position.
OPTIONAL_AGGREGATION_LEVELS = {'Cluster': 'Region'}
# The aggregation hierarchy is an application setting shared by every workspace and
# methodology (it is not part of a methodology).
AGGREGATION_HIERARCHY_STATE_KEY = 'scoring_aggregation_hierarchy'


def validate_aggregation_hierarchy(hierarchy: object) -> list[str]:
    """The hierarchy when it lists every aggregation level exactly once (Cluster may be left out)."""
    if (not isinstance(hierarchy, list)
            or any(not isinstance(field, str) for field in hierarchy)
            or len(set(hierarchy)) != len(hierarchy)
            or not _AGGREGATION_FIELDS <= set(hierarchy) <= _AGGREGATION_FIELDS | set(OPTIONAL_AGGREGATION_LEVELS)):
        raise ValueError('The aggregation hierarchy must list Operator, Vendor, Region, City and Campaign exactly once, '
                         'optionally with Cluster.')
    return complete_aggregation_hierarchy(hierarchy)


def load_aggregation_hierarchy(repository: Any) -> list[str]:
    """The application's aggregation hierarchy, or the default one."""
    getter = getattr(repository, 'get_application_state', None)
    try:
        stored = json.loads(getter(AGGREGATION_HIERARCHY_STATE_KEY) or 'null') if callable(getter) else None
        return validate_aggregation_hierarchy(stored)
    except (TypeError, ValueError):
        return complete_aggregation_hierarchy()


def save_aggregation_hierarchy(repository: Any, hierarchy: object) -> list[str]:
    """Validate and save the application's aggregation hierarchy."""
    levels = validate_aggregation_hierarchy(hierarchy)
    repository.set_application_state(AGGREGATION_HIERARCHY_STATE_KEY, json.dumps(levels))
    return levels


def complete_aggregation_hierarchy(hierarchy: object = None) -> list[str]:
    """The aggregation hierarchy with every level: Cluster follows Region unless it was placed."""
    levels = [str(value).strip() for value in hierarchy if str(value).strip()] if isinstance(hierarchy, list) else []
    levels = levels or list(DEFAULT_AGGREGATION_HIERARCHY)
    for level, after in OPTIONAL_AGGREGATION_LEVELS.items():
        if level not in levels:
            levels.insert(levels.index(after) + 1 if after in levels else len(levels), level)
    return levels
_SCORE_ANCHORS = ('low_score', 'medium_score', 'high_score', 'ultra_score')
_SCOPE_ENVIRONMENTS = {
    'DriveCity': {'sheet': 'DriveCity', 'g_level_1': 'Drive', 'g_level_2': 'City'},
    'DriveConnectionroad': {
        'sheet': 'DriveConnectionroad', 'g_level_1': 'Drive', 'g_level_2': 'Connectionroad',
    },
    'Walk': {'sheet': 'Walk', 'g_level_1': 'Walk'},
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
_LEGACY_KPI_CODES = (
    'C5', 'C6', 'C7', 'C8', 'C9', 'C10', 'C11', 'C12', 'C13', 'C14', 'C15',
    'C17', 'C18', 'C19', 'C20', 'C21', 'C22', 'C23', 'C24', 'C25', 'C26',
    'C27', 'C28', 'C29', 'C30', 'C31', 'C32', 'C33', 'C34', 'C35', 'C36', 'C37',
)
_LEGACY_KPI_CODE_MAP = {code: f'K{index}' for index, code in enumerate(_LEGACY_KPI_CODES, start=1)}
# The Most Reliable Network scoring rates the KPIs whose KPI Type is Reliable with their
# own maximum points, stored per environment context; the Best Network scoring uses max_points.
MOST_RELIABLE_POINTS = 'most_reliable_points'
RELIABLE_KPI_TYPE = 'Reliable'
# Most Reliable points copied with two decimals can miss the environment total by a few
# hundredths (650.02 for 650): within this tolerance they are scaled to the Best Network total.
_RELIABLE_ROUNDING_TOLERANCE = .1
BEST_NETWORK_SCORING = 'best_network'
MOST_RELIABLE_SCORING = 'most_reliable'
SCORING_LABELS = {BEST_NETWORK_SCORING: 'Best Network', MOST_RELIABLE_SCORING: 'Most Reliable Network'}
_LEGACY_2026_PROFILE_ID = 'netcheck-2026'
_LEGACY_2026_VERSION = '2026Q2'
_LEGACY_2026_ENVIRONMENT = 'DriveConnectionroad'
_CURRENT_2026_ENVIRONMENT = 'Drive Connecting Roads'


def _is_legacy_two_environment_configuration(configuration: object) -> bool:
    """Identify saved snapshots that predate the zero-weight Walk context."""
    if not isinstance(configuration, dict):
        return False
    if configuration.get('next_kpi_number') is not None:
        return False
    scope = configuration.get('scope')
    environments = scope.get('environments') if isinstance(scope, dict) else None
    metrics = configuration.get('metrics')
    legacy_names = {'DriveCity', 'DriveConnectionroad'}
    if not isinstance(environments, dict) or set(environments) != legacy_names or not isinstance(metrics, list):
        return False
    if any(
            isinstance(metric, dict) and isinstance(metric.get('code'), str)
            and re.fullmatch(r'K\d+', metric['code'], flags=re.IGNORECASE)
            for metric in metrics):
        return False
    return all(
        isinstance(metric, dict) and isinstance(metric.get('contexts'), dict)
        and set(metric['contexts']) == legacy_names
        for metric in metrics
    )


def unwrap_scoring_configuration_payload(payload: object) -> dict[str, Any]:
    """Unwrap a supported import envelope or copy a bare legacy configuration."""
    if not isinstance(payload, dict):
        raise ValueError('Scoring configuration must be an object.')
    if 'format' in payload:
        if canonical_format(payload.get('format')) != CONFIGURATION_FORMAT:
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
    names = list(environments)
    totals = {
        name: sum(float(metric['contexts'][name]['max_points']) for metric in metrics)
        for name in names
    }
    for name, total_points in totals.items():
        contexts = [metric['contexts'][name] for metric in metrics]
        if total_points > 0:
            for context in contexts:
                context['weight_share'] = context['max_points'] / total_points
            continue
        shares = [float(context.get('weight_share', 0.0)) for context in contexts]
        share_total = sum(shares)
        if share_total <= 0 and name == 'Walk' and 'DriveCity' in environments:
            shares = [float(metric['contexts']['DriveCity'].get('weight_share', 0.0)) for metric in metrics]
            share_total = sum(shares)
        if share_total <= 0:
            shares = [1.0] * len(contexts)
            share_total = len(contexts)
        for context, share in zip(contexts, shares):
            context['weight_share'] = share / share_total
    grand_total = sum(totals.values())
    for name, total_points in totals.items():
        environments[name]['total_points'] = total_points
        environments[name]['weight_share'] = total_points / grand_total if grand_total else 0.0
    scope = configuration['scope']
    scope['total_max_points'] = grand_total


def _validate_scope(scope: Any) -> None:
    if not isinstance(scope, dict):
        raise ValueError('Scoring configuration scope is missing.')
    environments = scope.get('environments')
    if not isinstance(environments, dict) or not 1 <= len(environments) <= MAX_SCORING_ENVIRONMENTS:
        raise ValueError('Scoring scope must contain between 1 and 32 environments.')
    seen_names: set[str] = set()
    selectors: list[tuple[str, str | None, str]] = []
    for name, environment in environments.items():
        if (not isinstance(name, str) or not name or name != name.strip()
                or name.casefold() == 'combined'
                or len(name) > 80 or name.casefold() in seen_names):
            raise ValueError('Environment names must be unique trimmed text of at most 80 characters and cannot be Combined.')
        seen_names.add(name.casefold())
        if not isinstance(environment, dict):
            raise ValueError(f'Scoring scope {name} configuration is missing.')
        filters = environment.get('source_filters')
        if not isinstance(filters, dict) or not set(filters) <= {'G_Level_1', 'G_Level_2'}:
            raise ValueError(f'Scoring scope {name} source_filters must use G_Level_1 and optional G_Level_2.')
        g_level_1 = filters.get('G_Level_1')
        g_level_2 = filters.get('G_Level_2')
        if not isinstance(g_level_1, str) or not g_level_1.strip() or len(g_level_1) > 128:
            raise ValueError(f'Scoring scope {name} requires a non-empty source_filters.G_Level_1 value.')
        if 'G_Level_2' in filters and (
                not isinstance(g_level_2, str) or not g_level_2.strip() or len(g_level_2) > 128):
            raise ValueError(f'Scoring scope {name} source_filters.G_Level_2 must be non-empty text when provided.')
        if 'display_name' in environment and (
                not isinstance(environment['display_name'], str)
                or not environment['display_name'].strip()
                or environment['display_name'] != environment['display_name'].strip()
                or len(environment['display_name']) > 80):
            raise ValueError(f'Scoring scope {name} display_name must be trimmed text of at most 80 characters.')
        selector = (g_level_1.casefold(), g_level_2.casefold() if g_level_2 is not None else None, name)
        for previous_g1, previous_g2, previous_name in selectors:
            if (selector[0] == previous_g1
                    and (selector[1] is None or previous_g2 is None or selector[1] == previous_g2)):
                raise ValueError(
                    f'Scoring environments {previous_name} and {name} have overlapping source selectors.',
                )
        selectors.append(selector)


def _validate_interpolation(interpolation: Any) -> dict[str, Any]:
    if not isinstance(interpolation, dict):
        raise ValueError('Scoring interpolation settings are missing.')
    interpolation = {
        'score_range': [0.0, 1.0], 'method': 'piecewise_linear', 'clamp_to_range': True,
        'medium_score': .8, 'high_score_without_ultra': 1,
        'high_score_with_ultra': .95, 'ultra_score': 1, **interpolation,
    }
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
    return {'rule': rule}


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
    ratio = re.fullmatch(
        rf'(?:100 \* )?(SUM|COUNT)\((.+)\) / (SUM|COUNT)\(({_FORMULA_IDENTIFIER})\)', formula,
    )
    if ratio:
        _numerator_operation, numerator, _denominator_operation, denominator = ratio.groups()
        numerator = numerator.strip()
        if numerator not in _FORMULA_FIELDS_BY_KIND[kind]:
            _condition_fields(numerator, kind, label)
        if denominator not in _FORMULA_FIELDS_BY_KIND[kind]:
            raise ValueError(f'{label} formula references an unsupported {kind} denominator field.')
        return
    aggregate = re.fullmatch(r'(SUM|COUNT)\((.+)\)', formula)
    if aggregate:
        expression = aggregate.group(2).strip()
        if expression not in _FORMULA_FIELDS_BY_KIND[kind]:
            _condition_fields(expression, kind, label)
        return
    raise ValueError(f'{label} formula is unsupported.')


def _validate_calculation(metric: dict[str, Any]) -> dict[str, Any]:
    code = metric['code']
    kind = metric['source_kind']
    calculation = metric.get('calculation')
    label = f'KPI {code} calculation'
    if not isinstance(calculation, dict):
        raise ValueError(f'{label} is missing.')
    required = {'formula', 'filters'}
    if calculation.get('formula') == '100 * SUM(totalpacketlost) / SUM(Packets_Sent)':
        required.add('totalpacketlost')
        if calculation.get('totalpacketlost') != _TOTAL_PACKET_LOST_FORMULA:
            raise ValueError(f'{label} totalpacketlost expression is unsupported.')
    calculation = {key: value for key, value in calculation.items() if key not in {'source_kind', 'denominator'}}
    calculation.setdefault('filters', {})
    if set(calculation) != required:
        raise ValueError(f'{label} contains missing or unsupported calculation fields.')
    _validate_formula(calculation.get('formula'), kind, label)
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
    weight_share = None
    if 'weight_share' in context:
        weight_share = _finite_number(context['weight_share'], f'{label} weight_share', minimum=0, maximum=1)
    thresholds = context.get('thresholds')
    if isinstance(thresholds, dict):
        thresholds = {'ultra': None, **thresholds}
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
    validated = {
        **{key: copy.deepcopy(value) for key, value in context.items()
           if key not in {'threshold_reference', 'weight_reference', MOST_RELIABLE_POINTS}},
        'max_points': maximum,
        'thresholds': normalized_thresholds,
        'score_mapping': validated_mapping,
    }
    if weight_share is not None:
        validated['weight_share'] = weight_share
    # Zero Most Reliable points leave the KPI out of that scoring, like an absent value,
    # so a methodology without Most Reliable points keeps its identity.
    reliable_points = _finite_number(context.get(MOST_RELIABLE_POINTS, 0), f'{label} {MOST_RELIABLE_POINTS}', minimum=0)
    if reliable_points > 0:
        validated[MOST_RELIABLE_POINTS] = reliable_points
    return validated


def _add_legacy_walk_context(configuration: dict[str, Any]) -> dict[str, Any]:
    """Add a zero-weight Walk context when loading a two-environment configuration."""
    normalized = copy.deepcopy(configuration)
    scope = normalized.get('scope')
    environments = scope.get('environments') if isinstance(scope, dict) else None
    if not isinstance(environments, dict):
        return normalized
    supported_names = {'DriveCity', 'DriveConnectionroad', 'Walk'}
    if set(environments) not in (
        {'DriveCity', 'DriveConnectionroad'},
        supported_names,
    ):
        return normalized
    was_legacy = (
        'Walk' not in environments
        and set(environments) == {'DriveCity', 'DriveConnectionroad'}
        and not normalized.get('next_kpi_number')
        and not any(
            isinstance(metric, dict) and isinstance(metric.get('code'), str)
            and re.fullmatch(r'K\d+', metric['code'], flags=re.IGNORECASE)
            for metric in normalized.get('metrics', [])
        )
    )
    if was_legacy:
        environments['Walk'] = {
            **copy.deepcopy(_SCOPE_ENVIRONMENTS['Walk']),
            'total_points': 0.0,
            'weight_share': 0.0,
        }
    mapping = scope.get('environment_mapping')
    if was_legacy and isinstance(mapping, dict) and mapping == {
        'Drive + City': 'DriveCity',
        'Drive + Connectionroad': 'DriveConnectionroad',
    }:
        mapping['Walk'] = 'Walk'
    metrics = normalized.get('metrics')
    if not isinstance(metrics, list):
        return normalized
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        contexts = metric.get('contexts')
        if not isinstance(contexts, dict) or 'DriveCity' not in contexts:
            continue
        if was_legacy:
            walk_context = copy.deepcopy(contexts['DriveCity'])
            walk_context['max_points'] = 0.0
            walk_context.pop('weight_share', None)
            contexts['Walk'] = walk_context
    return normalized


def _remap_legacy_kpi_references(value: Any, code_map: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: code_map.get(item, item) if key == 'kpi_code' and isinstance(item, str)
            else _remap_legacy_kpi_references(item, code_map)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_remap_legacy_kpi_references(item, code_map) for item in value]
    return value


def _normalize_legacy_kpi_codes(configuration: dict[str, Any]) -> dict[str, Any]:
    """Replace source-workbook IDs for an unmigrated profile with stable sequential IDs."""
    has_sequential_codes = any(
        re.fullmatch(r'K\d+', metric['code'], flags=re.IGNORECASE)
        for metric in configuration['metrics']
    )
    if has_sequential_codes:
        return configuration
    code_map = {
        metric['code']: _LEGACY_KPI_CODE_MAP[metric['code']]
        for metric in configuration['metrics'] if metric['code'] in _LEGACY_KPI_CODE_MAP
    }
    if not code_map:
        return configuration
    for metric in configuration['metrics']:
        if metric['code'] in code_map:
            metric['code'] = code_map[metric['code']]
    configuration['gap_priority'] = [code_map.get(code, code) for code in configuration['gap_priority']]
    configuration = _remap_legacy_kpi_references(configuration, code_map)
    configuration['next_kpi_number'] = max(
        configuration.get('next_kpi_number', 1),
        max((int(match.group(1)) for code in code_map.values()
             if (match := re.fullmatch(r'K(\d+)', code))), default=0) + 1,
    )
    return validate_scoring_configuration(configuration)


def is_reliable_kpi(metric: object) -> bool:
    """Whether a KPI takes part in the Most Reliable Network scoring: its KPI Type is Reliable."""
    return (isinstance(metric, dict) and isinstance(metric.get('kpi_type'), str)
            and metric['kpi_type'].strip().casefold() == RELIABLE_KPI_TYPE.casefold())


def _normalize_reliable_points(metrics: list[dict[str, Any]], environments: list[str]) -> None:
    """Keep Most Reliable points only on Reliable KPIs and correct their rounding per environment."""
    for metric in metrics:
        if not is_reliable_kpi(metric):
            for context in metric['contexts'].values():
                context.pop(MOST_RELIABLE_POINTS, None)
    for name in environments:
        contexts = [metric['contexts'][name] for metric in metrics if MOST_RELIABLE_POINTS in metric['contexts'][name]]
        reliable_total = sum(context[MOST_RELIABLE_POINTS] for context in contexts)
        best_network_total = sum(metric['contexts'][name]['max_points'] for metric in metrics)
        # Already exact (within float noise): leave the points, so validation is idempotent.
        if reliable_total <= 0 or abs(reliable_total - best_network_total) < 1e-6:
            continue
        if abs(reliable_total - best_network_total) <= _RELIABLE_ROUNDING_TOLERANCE:
            factor = best_network_total / reliable_total
            for context in contexts:
                context[MOST_RELIABLE_POINTS] = round(context[MOST_RELIABLE_POINTS] * factor, 10)


def validate_scoring_configuration(payload: object) -> dict[str, Any]:
    """Validate a self-contained workspace configuration without reading seed files."""
    configuration = _add_legacy_walk_context(unwrap_scoring_configuration_payload(payload))
    for key in _PROVENANCE_KEYS - {'title'}:
        configuration.pop(key, None)
    title = configuration.get('title', '')
    if not isinstance(title, str) or len(title.strip()) > 256:
        raise ValueError('Scoring methodology title must be text of at most 256 characters.')
    configuration['title'] = title.strip()
    scope = configuration.get('scope')
    if isinstance(scope, dict):
        for key in ('environment_fields', 'environment_mapping', 'tableau_group_key',
                    'tableau_aggregate_group_by', 'campaign_in_tableau_group_key', 'allocation_note'):
            scope.pop(key, None)
        environments = scope.get('environments')
        for environment in environments.values() if isinstance(environments, dict) else ():
            if not isinstance(environment, dict):
                continue
            if 'source_filters' not in environment:
                environment['source_filters'] = {
                    field: environment[key] for key, field in
                    (('g_level_1', 'G_Level_1'), ('g_level_2', 'G_Level_2')) if key in environment
                }
            for key in ('g_level_1', 'g_level_2', 'sheet'):
                environment.pop(key, None)
    required = {'version', 'scope', 'metrics'}
    if not required <= set(configuration):
        raise ValueError('Scoring configuration must include version, scope and metrics.')
    version = configuration.get('version')
    if not isinstance(version, str) or not version.strip():
        raise ValueError('Scoring configuration version must be a non-empty string.')
    _validate_scope(configuration.get('scope'))
    interpolation = _validate_interpolation(configuration.get('interpolation', {
        'score_range': [0, 1], 'method': 'piecewise_linear', 'clamp_to_range': True,
        'medium_score': .8, 'high_score_without_ultra': 1,
        'high_score_with_ultra': .95, 'ultra_score': 1,
    }))
    interpolation.pop('source_note', None)
    context_names = list(configuration['scope']['environments'])
    supplied_metrics = configuration.get('metrics')
    if not isinstance(supplied_metrics, list) or not 1 <= len(supplied_metrics) <= MAX_SCORING_METRICS:
        raise ValueError(f'Scoring configuration must contain between 1 and {MAX_SCORING_METRICS} KPIs.')
    validated_metrics: list[dict[str, Any]] = []
    codes: list[str] = []
    for supplied in supplied_metrics:
        if not isinstance(supplied, dict):
            raise ValueError('Each KPI must be an object.')
        code = supplied.get('code')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', code):
            raise ValueError('KPI code must start with a letter and contain at most 32 letters, numbers, underscores or hyphens.')
        if code.casefold() in {existing.casefold() for existing in codes}:
            raise ValueError(f'KPI code {code} is duplicated.')
        codes.append(code)
        kind = supplied.get('source_kind')
        if not isinstance(kind, str) or kind not in _FORMULA_FIELDS_BY_KIND:
            raise ValueError(f'KPI {code} source_kind must be data, voice or speech.')
        direction = supplied.get('direction')
        if not isinstance(direction, str) or direction not in {'higher_is_better', 'lower_is_better'}:
            raise ValueError(f'KPI {code} direction must be higher_is_better or lower_is_better.')
        mapping_method = supplied.get('mapping_method', interpolation.get('method', 'piecewise_linear'))
        if not isinstance(mapping_method, str) or mapping_method not in SUPPORTED_MAPPING_METHODS:
            raise ValueError(f'KPI {code} mapping_method must be one of: {", ".join(sorted(SUPPORTED_MAPPING_METHODS))}.')
        for key in ('category', 'kpi'):
            value = supplied.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'KPI {code} {key} must be non-empty text.')
        kpi_type = supplied.get('kpi_type')
        if not isinstance(kpi_type, str) or not kpi_type.strip():
            raise ValueError(f'KPI {code} kpi_type must be non-empty text.')
        calculation = _validate_calculation(supplied)
        contexts = supplied.get('contexts')
        if not isinstance(contexts, dict) or set(contexts) != set(context_names):
            raise ValueError(f'KPI {code} must contain exactly one context per configured environment.')
        metric = copy.deepcopy(supplied)
        metric.pop('source', None)
        metric.update({
            'code': code,
            'source_kind': kind,
            'direction': direction,
            'mapping_method': mapping_method,
            'kpi_type': kpi_type.strip(),
            'calculation': calculation,
            'contexts': {
                name: _validate_metric_context({**supplied, 'contexts': contexts}, name, interpolation)
                for name in context_names
            },
        })
        validated_metrics.append(metric)
    priority = configuration.get('gap_priority', list(codes))
    if (not isinstance(priority, list) or any(not isinstance(code, str) for code in priority)
            or len(priority) != len(set(priority))):
        raise ValueError('GAP priority must list unique KPI codes from this configuration.')
    validated = copy.deepcopy(configuration)
    validated['interpolation'] = interpolation
    # The aggregation hierarchy is an application setting, not part of a methodology.
    validated.pop('aggregation_hierarchy', None)
    validated['metrics'] = validated_metrics
    highest_kpi_number = max(
        (int(match.group(1)) for code in codes
         if (match := re.fullmatch(r'K(\d+)', code, flags=re.IGNORECASE))),
        default=0,
    )
    requested_next_number = configuration.get('next_kpi_number', 1)
    if (isinstance(requested_next_number, bool) or not isinstance(requested_next_number, int)
            or requested_next_number < 1):
        raise ValueError('next_kpi_number must be a positive integer.')
    validated['next_kpi_number'] = max(highest_kpi_number + 1, requested_next_number)
    known_codes = set(codes)
    normalized_priority = [code for code in priority if code in known_codes]
    prioritized = set(normalized_priority)
    validated['gap_priority'] = [
        *normalized_priority, *(code for code in codes if code not in prioritized),
    ]
    _normalize_reliable_points(validated_metrics, context_names)
    _refresh_weight_totals(validated)
    if validated['scope']['total_max_points'] <= 0:
        raise ValueError('At least one KPI weight must be greater than zero.')
    return validated


def has_most_reliable_scoring(configuration: object) -> bool:
    """Whether a methodology gives Most Reliable points to at least one Reliable KPI."""
    metrics = configuration.get('metrics') if isinstance(configuration, dict) else None
    return any(
        isinstance(context, dict) and isinstance(context.get(MOST_RELIABLE_POINTS), (int, float))
        and not isinstance(context.get(MOST_RELIABLE_POINTS), bool) and context[MOST_RELIABLE_POINTS] > 0
        for metric in metrics or [] if is_reliable_kpi(metric)
        for context in (metric.get('contexts') or {}).values()
    )


def most_reliable_configuration(configuration: object) -> dict[str, Any] | None:
    """The methodology seen by the Most Reliable scoring, or None when it has no Most Reliable points.

    The KPIs whose KPI Type is Reliable take part with their Most Reliable points as
    maximum points; formulas, thresholds and score anchors stay the methodology's.
    """
    if not has_most_reliable_scoring(configuration):
        return None
    derived = validate_scoring_configuration(configuration)
    metrics = [metric for metric in derived['metrics'] if is_reliable_kpi(metric)]
    for metric in metrics:
        for context in metric['contexts'].values():
            context['max_points'] = context.pop(MOST_RELIABLE_POINTS, 0.0)
            context.pop('weight_share', None)
    codes = {metric['code'] for metric in metrics}
    derived['metrics'] = metrics
    derived['gap_priority'] = [code for code in derived['gap_priority'] if code in codes]
    derived['scoring'] = MOST_RELIABLE_SCORING
    return validate_scoring_configuration(derived)


def default_scoring_profile(configuration: object) -> dict[str, Any]:
    """Create a stable, named profile when reading a legacy single configuration."""
    validated = _normalize_legacy_kpi_codes(validate_scoring_configuration(configuration))
    year_match = re.search(r'20\d{2}', validated['version'])
    year = year_match.group(0) if year_match else None
    identifier = f'netcheck-{year}' if year else 'netcheck-default'
    name = f'NetCheck {year}' if year else 'NetCheck Configuration'
    return {'id': identifier, 'name': name, 'configuration': validated}


def validate_scoring_profiles(payload: object) -> dict[str, Any]:
    """Validate a complete workspace collection of named scoring profiles."""
    if not isinstance(payload, dict):
        raise ValueError('Scoring methodologies must be an object.')
    active_profile_id = payload.get('active_profile_id')
    profiles = payload.get('profiles')
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= MAX_SCORING_PROFILES:
        raise ValueError(f'Scoring methodologies must contain between 1 and {MAX_SCORING_PROFILES} methodologies.')
    normalized_profiles: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != {'id', 'name', 'configuration'}:
            raise ValueError('Each scoring methodology must contain only id, name and configuration.')
        profile_id = profile.get('id')
        if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
            raise ValueError('Scoring methodology id must be a lowercase identifier of up to 64 characters.')
        if profile_id in seen_ids:
            raise ValueError(f'Scoring methodology id {profile_id} is duplicated.')
        seen_ids.add(profile_id)
        name = profile.get('name')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError('Scoring methodology name must contain between 1 and 80 characters.')
        normalized_name = name.strip()
        if normalized_name.casefold() in seen_names:
            raise ValueError(f'Scoring methodology name {normalized_name} is duplicated.')
        seen_names.add(normalized_name.casefold())
        configuration = _normalize_legacy_kpi_codes(
            validate_scoring_configuration(profile.get('configuration')),
        )
        normalized_profiles.append({
            'id': profile_id,
            'name': normalized_name,
            'configuration': configuration,
        })
    if not isinstance(active_profile_id, str) or active_profile_id not in seen_ids:
        raise ValueError('The active scoring methodology must reference an existing methodology.')
    return {'active_profile_id': active_profile_id, 'profiles': normalized_profiles}


def migrate_known_legacy_2026_profiles(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the known 2026 workspace profile without rewriting historical configs."""
    if not isinstance(payload.get('profiles'), list):
        return payload  # The caller validates the profile collection before invoking this helper.
    profile_indexes: list[int] = []
    for index, profile in enumerate(payload['profiles']):
        if not isinstance(profile, dict) or profile.get('id') != _LEGACY_2026_PROFILE_ID:
            continue
        configuration = profile.get('configuration')
        if not isinstance(configuration, dict) or configuration.get('version') != _LEGACY_2026_VERSION:
            continue
        scope = configuration.get('scope')
        environments = scope.get('environments') if isinstance(scope, dict) else None
        if not isinstance(environments, dict):
            continue
        legacy_environment = environments.get(_LEGACY_2026_ENVIRONMENT)
        if legacy_environment is None or _CURRENT_2026_ENVIRONMENT in environments:
            continue
        if (not isinstance(legacy_environment, dict) or legacy_environment.get('source_filters', {}).get('G_Level_1') != 'Drive'
                or legacy_environment.get('source_filters', {}).get('G_Level_2') not in {'Connectionroad', 'Connecting Roads'}
                or legacy_environment.get('display_name')):
            continue
        profile_indexes.append(index)
    if not profile_indexes:
        return payload

    migrated = copy.deepcopy(payload)
    for index in profile_indexes:
        profile = migrated['profiles'][index]
        configuration = profile.get('configuration')
        scope = configuration.get('scope')
        environments = scope['environments']
        environments = {
            (_CURRENT_2026_ENVIRONMENT if key == _LEGACY_2026_ENVIRONMENT else key): value
            for key, value in environments.items()
        }
        scope['environments'] = environments
        for metric in configuration.get('metrics', []):
            contexts = metric.get('contexts') if isinstance(metric, dict) else None
            if not isinstance(contexts, dict) or _LEGACY_2026_ENVIRONMENT not in contexts:
                continue
            metric['contexts'] = {
                (_CURRENT_2026_ENVIRONMENT if key == _LEGACY_2026_ENVIRONMENT else key): value
                for key, value in contexts.items()
            }
        environment = environments[_CURRENT_2026_ENVIRONMENT]
        environment['source_filters']['G_Level_2'] = 'Connecting Roads'
        environment['display_name'] = _CURRENT_2026_ENVIRONMENT
    return validate_scoring_profiles(migrated)


def scoring_profiles_document(profiles: dict[str, Any] | None) -> dict[str, Any]:
    """Build the portable configuration format without derived totals or provenance."""
    document = {'format': CONFIGURATION_FORMAT, 'version': PROFILE_COLLECTION_VERSION,
                'active_profile_id': None, 'profiles': None}
    if profiles is None:
        return document
    normalized = validate_scoring_profiles(profiles)
    for profile in normalized['profiles']:
        configuration = profile['configuration']
        scope = configuration['scope']
        scope.pop('total_max_points', None)
        for environment in scope['environments'].values():
            environment.pop('total_points', None)
            environment.pop('weight_share', None)
        for metric in configuration['metrics']:
            for name, context in metric['contexts'].items():
                if sum(item['contexts'][name]['max_points'] for item in configuration['metrics']) > 0:
                    context.pop('weight_share', None)
    document.update(normalized)
    return document


def unwrap_scoring_profiles_payload(payload: object) -> dict[str, Any] | None:
    """Unwrap current profile collections and migrate supported legacy single-profile files."""
    if not isinstance(payload, dict):
        raise ValueError('Scoring configuration must be an object.')
    if canonical_format(payload.get('format')) == CONFIGURATION_FORMAT:
        version = payload.get('version')
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError('Unsupported scoring configuration file version.')
        if version == CONFIGURATION_FORMAT_VERSION:
            if 'configuration' not in payload:
                raise ValueError('This file does not contain a scoring configuration to import.')
            if payload.get('configuration') is None:
                return None
            profile = default_scoring_profile(unwrap_scoring_configuration_payload(payload))
            return validate_scoring_profiles({'active_profile_id': profile['id'], 'profiles': [profile]})
        if version != PROFILE_COLLECTION_VERSION:
            raise ValueError('Unsupported scoring configuration file version.')
        if 'profiles' not in payload:
            raise ValueError('This file does not contain a scoring methodology collection.')
        if payload.get('profiles') is None:
            if payload.get('active_profile_id') is not None:
                raise ValueError('An empty scoring methodology collection cannot have an active methodology.')
            return None
        return validate_scoring_profiles({
            'active_profile_id': payload.get('active_profile_id'),
            'profiles': payload.get('profiles'),
        })
    if 'profiles' in payload or 'active_profile_id' in payload:
        return validate_scoring_profiles(payload)
    profile = default_scoring_profile(payload)
    return validate_scoring_profiles({
        'active_profile_id': profile['id'],
        'profiles': [profile],
    })


def _normalize_initial_configuration(payload: dict[str, Any]) -> dict[str, Any]:
    configuration = copy.deepcopy(payload)
    metrics = configuration.get('metrics')
    interpolation = configuration.get('interpolation', {})
    if not isinstance(metrics, list) or not isinstance(interpolation, dict):
        raise ValueError('Scoring seed must contain metrics and valid optional interpolation settings.')
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
    projection.pop('next_kpi_number', None)
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
        # An explicit historical default has the same scoring identity as an
        # older profile that derives it from the interpolation configuration.
        if metric.get('mapping_method') == 'piecewise_linear':
            metric.pop('mapping_method')
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
