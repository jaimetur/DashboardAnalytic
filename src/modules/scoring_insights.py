"""NetCheck-style scoring insights derived from the saved scoring views.

Location cards, KPI GAP profiles, campaign trends and campaign comparisons are
built from the per-environment score tables, so the web page and the
PowerPoint/Word exports show the same numbers.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src.modules.column_names import campaign_sort_key as shared_campaign_sort_key, compact_campaign_value

LOCATION_LEVELS = ('City', 'Cluster', 'Region')
MAX_LOCATION_CARDS = 12
MIN_TREND_CAMPAIGNS = 5
MIN_COMPARISON_CAMPAIGNS = 2
_CONTEXT_FIELDS = ('vendor', 'region', 'cluster', 'city', 'campaign', 'dataset_type')
_LEVEL_FIELDS = {'Vendor': 'vendor', 'Region': 'region', 'Cluster': 'cluster', 'City': 'city', 'Campaign': 'campaign',
                 'Dataset Type': 'dataset_type'}
COMBINED = 'Combined'


def build_scoring_insights(score_tables: list[dict[str, Any]], configuration: dict[str, Any],
                           levels: list[str], result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Insights for every environment of the views; each item names its environment."""
    from src.modules.scoring_config import has_most_reliable_scoring, is_reliable_kpi
    environments = list(dict.fromkeys(str(table['context'].get('environment')) for table in score_tables))
    # Best Network marks the KPIs of the Most Reliable scoring when the methodology has one.
    reliable_codes = ({metric['code'] for metric in configuration.get('metrics', []) if is_reliable_kpi(metric)}
                      if has_most_reliable_scoring(configuration) else set())
    scopes = _scopes(score_tables)
    insights: dict[str, list[dict[str, Any]]] = {
        'location_cards': [], 'kpi_gap_profiles': [], 'campaign_trends': [], 'campaign_comparisons': [],
    }
    for environment in environments:
        summaries = {scope: _scope_summary(tables, environment) for scope, tables in scopes.items()}
        summaries = {scope: summary for scope, summary in summaries.items() if summary is not None}
        insights['location_cards'].extend(_location_cards(summaries, levels, environment))
        insights['campaign_trends'].extend(_campaign_trends(summaries, levels, environment))
        insights['campaign_comparisons'].extend(_campaign_comparisons(scopes, levels, environment))
        insights['kpi_gap_profiles'].extend(_kpi_gap_profiles(scopes, environment, reliable_codes))
    insights['points_loss_maps'], insights['points_loss_background'] = _points_loss_maps(result, score_tables)
    return insights


def _points_loss_maps(result: dict[str, Any] | None, score_tables: list[dict[str, Any]]) -> tuple[list, list]:
    """Points lost per area of each operator series, with the area locations to draw them."""
    from src.modules.scoring_points_loss import points_loss_maps
    document = (result or {}).get('points_loss')
    if not isinstance(document, dict) or not document.get('shares'):
        return [], []
    keys = [key for key in document['shares'][0] if key not in {'environment', 'kpi_code', 'areas'}]
    styles = next((table.get('operator_styles') for table in score_tables if table.get('operator_styles')), {}) or {}
    references = {table.get('baseline_operator') for table in score_tables}
    geometry = document.get('areas') or {}
    # What the map areas are, such as ITL3 areas or municipalities, and the countries without them.
    countries = (document.get('map_areas') or {}).get('countries') or []
    labels = list(dict.fromkeys(item.get('label') or 'area' for item in countries))
    area_label = labels[0] if len(labels) == 1 else 'map area'
    unmapped = (document.get('map_areas') or {}).get('unmapped_countries') or []
    maps = []
    for item in points_loss_maps(result, keys):
        context = item['context']
        operator = context.get('operator')
        style = styles.get(operator) or {}
        located = geometry.get(item['field']) or {}
        areas = []
        for name, points in sorted(item['areas'].items(), key=lambda entry: -entry[1]):
            place = located.get(name) or {}
            areas.append({'name': name, 'points': points, 'share': points / item['total'] if item['total'] else 0,
                          'latitude': place.get('latitude'), 'longitude': place.get('longitude'),
                          'kind': place.get('kind', 'place'), 'route': place.get('points') or [],
                          # The map areas holding its tests and how many, and the points it loses in each one:
                          # the City (or route) alone on the map.
                          'area_tests': place.get('area_tests') or {},
                          'area_losses': (item.get('area_losses') or {}).get(name) or {},
                          # All environments: the environments where the area loses points, most first.
                          'environments': (item.get('environments') or {}).get(name, [])})
        maps.append({
            'environment': item.get('environment') or COMBINED, 'operator': operator, 'label': style.get('label') or operator,
            'color': style.get('color'), 'is_reference': operator in references, 'field': item['field'],
            'context': {field: value for field, value in context.items()
                        if field != 'operator' and value not in (None, '')},
            'areas': areas, 'total': item['total'],
            **({'area_label': area_label, 'unmapped_countries': unmapped} if item['field'] == 'Area' else {}),
        })
    maps.sort(key=lambda item: ((styles.get(item['operator']) or {}).get('position', 99), str(item['operator']),
                                json.dumps(item['context'], sort_keys=True, default=str), item['field']))
    return maps, document.get('background') or []


def _scope_key(context: dict[str, Any]) -> tuple:
    return tuple((field, context.get(field)) for field in _CONTEXT_FIELDS)


def _scopes(score_tables: list[dict[str, Any]]) -> dict[tuple, dict[str, dict[str, Any]]]:
    scopes: dict[tuple, dict[str, dict[str, Any]]] = {}
    for table in score_tables:
        context = table.get('context') or {}
        scopes.setdefault(_scope_key(context), {})[str(context.get('environment'))] = table
    return scopes


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _service(row: dict[str, Any]) -> str:
    return 'Data' if str(row.get('source_kind') or '').casefold() == 'data' else 'Voice'


def _kpi_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in table.get('rows', []) if row.get('kpi_code')]


def _environment_points(table: dict[str, Any], operator: str) -> dict[str, Any]:
    """Voice and Data points of one operator in one environment table, with their maxima."""
    totals = {'Voice': 0.0, 'Data': 0.0, 'max_Voice': 0.0, 'max_Data': 0.0, 'measured': False, 'complete': True}
    for row in _kpi_rows(table):
        maximum = _number(row.get('max_points')) or 0.0
        if maximum <= 0:
            continue
        service = _service(row)
        totals[f'max_{service}'] += maximum
        value = (row.get('values') or {}).get(operator) or {}
        points = _number(value.get('points'))
        if points is None:
            totals['complete'] = False
            continue
        totals['measured'] = True
        totals[service] += points
        if value.get('complete') is False:
            totals['complete'] = False
    return totals


def _scope_summary(tables: dict[str, dict[str, Any]], environment: str) -> dict[str, Any] | None:
    """Points per operator of one scope, scaled to the full maximum of the environment.

    All Environments adds the environments measured for that scope and scales them to
    the full maximum, as NetCheck scales per-city rankings to 1,000 points.
    """
    if environment not in tables:
        return None
    table = tables[environment]
    if environment == COMBINED:
        sources = [source for name, source in tables.items()
                   if name != COMBINED and any((_number(row.get('max_points')) or 0) > 0 for row in _kpi_rows(source))]
    else:
        sources = [table]
    if not sources:
        return None
    maximum = sum(_number(row.get('max_points')) or 0.0 for source in sources for row in _kpi_rows(source))
    service_maximum = {service: sum(_number(row.get('max_points')) or 0.0 for source in sources
                                    for row in _kpi_rows(source) if _service(row) == service)
                       for service in ('Voice', 'Data')}
    operators = []
    scaled = False
    for operator in table.get('operators', []):
        parts = [_environment_points(source, operator) for source in sources]
        measured = [part for part in parts if part['measured']]
        if not measured:
            continue
        reached = sum(part['max_Voice'] + part['max_Data'] for part in measured)
        factor = maximum / reached if reached > 0 else 1.0
        scaled = scaled or abs(factor - 1) > 1e-9
        voice = sum(part['Voice'] for part in measured) * factor
        data = sum(part['Data'] for part in measured) * factor
        style = (table.get('operator_styles') or {}).get(operator) or {}
        operators.append({
            'operator': operator, 'label': style.get('label') or operator, 'color': style.get('color'),
            'voice': voice, 'data': data, 'total': voice + data,
            'complete': all(part['complete'] for part in measured) and len(measured) == len(parts),
            'is_reference': operator == table.get('baseline_operator'),
        })
    if not operators:
        return None
    return {'context': dict(table.get('context') or {}), 'maximum': maximum, 'scaled': scaled,
            'max_voice': service_maximum['Voice'], 'max_data': service_maximum['Data'],
            'operators': operators, 'baseline_operator': table.get('baseline_operator')}


def _display(level: str, value: Any) -> str:
    return compact_campaign_value(value) if level == 'Campaign' else str(value)


def campaign_sort_key(value: Any) -> tuple:
    """Chronological campaign order shared by every module (plain, NSA, then SA in a quarter)."""
    return shared_campaign_sort_key(value)


def _group_label(context: dict[str, Any], levels: list[str], excluded: set[str]) -> str:
    parts = [f'{level}: {_display(level, context.get(field))}' for level, field in _LEVEL_FIELDS.items()
             if level in levels and level not in excluded and context.get(field) not in (None, '')]
    return ' · '.join(parts)


def _location_cards(summaries: dict[tuple, dict[str, Any]], levels: list[str], environment: str) -> list[dict[str, Any]]:
    selected = [level for level in LOCATION_LEVELS if level in levels]
    for level in selected:
        field = _LEVEL_FIELDS[level]
        groups: dict[tuple, list[dict[str, Any]]] = {}
        for summary in summaries.values():
            context = summary['context']
            if context.get(field) in (None, ''):
                continue
            key = tuple((name, context.get(name)) for name in _CONTEXT_FIELDS if name != field)
            groups.setdefault(key, []).append(summary)
        usable = [cards for cards in groups.values() if 2 <= len(cards) <= MAX_LOCATION_CARDS]
        if not usable:
            continue
        return [{
            'environment': environment, 'level': level,
            'title': _group_label(cards[0]['context'], levels, {level}),
            'maximum': cards[0]['maximum'], 'scaled': any(card['scaled'] for card in cards),
            'max_voice': cards[0]['max_voice'], 'max_data': cards[0]['max_data'],
            'campaign': cards[0]['context'].get('campaign') if level != 'Campaign' else None,
            'cards': [{'label': _display(level, card['context'].get(field)), 'operators': card['operators']}
                      for card in sorted(cards, key=lambda item: str(item['context'].get(field)).casefold())],
        } for cards in usable]
    return []


def _campaign_groups(summaries: dict[tuple, dict[str, Any]]) -> dict[tuple, list[dict[str, Any]]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for summary in summaries.values():
        context = summary['context']
        if context.get('campaign') in (None, ''):
            continue
        key = tuple((name, context.get(name)) for name in _CONTEXT_FIELDS if name != 'campaign')
        groups.setdefault(key, []).append(summary)
    return groups


def _campaign_trends(summaries: dict[tuple, dict[str, Any]], levels: list[str], environment: str) -> list[dict[str, Any]]:
    if 'Campaign' not in levels:
        return []
    trends = []
    for members in _campaign_groups(summaries).values():
        members = sorted(members, key=lambda item: campaign_sort_key(item['context'].get('campaign')))
        if len(members) < MIN_TREND_CAMPAIGNS:
            continue
        operators: dict[str, dict[str, Any]] = {}
        for index, member in enumerate(members):
            for item in member['operators']:
                series = operators.setdefault(item['operator'], {
                    'operator': item['operator'], 'label': item['label'], 'color': item['color'],
                    'is_reference': item['is_reference'], 'points': [None] * len(members),
                })
                series['points'][index] = item['total']
        trends.append({
            'environment': environment, 'title': _group_label(members[0]['context'], levels, {'Campaign'}),
            'maximum': members[0]['maximum'],
            'campaigns': [_display('Campaign', member['context'].get('campaign')) for member in members],
            'series': list(operators.values()),
        })
    return trends


def _campaign_comparisons(scopes: dict[tuple, dict[str, dict[str, Any]]], levels: list[str],
                          environment: str) -> list[dict[str, Any]]:
    """Each operator's KPI points in the two latest campaigns of every group, latest minus previous."""
    if 'Campaign' not in levels:
        return []
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for tables in scopes.values():
        table = tables.get(environment)
        if table is None or table['context'].get('campaign') in (None, ''):
            continue
        key = tuple((name, table['context'].get(name)) for name in _CONTEXT_FIELDS if name != 'campaign')
        groups.setdefault(key, []).append(table)
    comparisons = []
    for tables in groups.values():
        tables = sorted(tables, key=lambda table: campaign_sort_key(table['context'].get('campaign')))
        if len(tables) < MIN_COMPARISON_CAMPAIGNS:
            continue
        previous, latest = tables[-2], tables[-1]
        previous_rows = {row['kpi_code']: row for row in _kpi_rows(previous)}
        for operator in latest.get('operators', []):
            rows = []
            for row in _kpi_rows(latest):
                if (_number(row.get('max_points')) or 0) <= 0:
                    continue
                before = ((previous_rows.get(row['kpi_code']) or {}).get('values') or {}).get(operator) or {}
                after = (row.get('values') or {}).get(operator) or {}
                before_points, after_points = _number(before.get('points')), _number(after.get('points'))
                rows.append({
                    'kpi_code': row['kpi_code'], 'kpi': row.get('kpi'), 'category': row.get('category'),
                    'service': _service(row), 'previous_value': _number(before.get('value')),
                    'previous_points': before_points, 'latest_value': _number(after.get('value')),
                    'latest_points': after_points,
                    'delta': after_points - before_points if None not in (after_points, before_points) else None,
                })
            if not any(row['delta'] is not None for row in rows):
                continue
            rows.sort(key=lambda item: (item['delta'] is None, item['delta'] if item['delta'] is not None else 0))
            style = (latest.get('operator_styles') or {}).get(operator) or {}
            comparisons.append({
                'environment': environment, 'operator': operator, 'label': style.get('label') or operator,
                'title': _group_label(latest['context'], levels, {'Campaign'}),
                'previous_campaign': _display('Campaign', previous['context'].get('campaign')),
                'latest_campaign': _display('Campaign', latest['context'].get('campaign')),
                'rows': rows, 'total_delta': sum(row['delta'] for row in rows if row['delta'] is not None),
            })
    return comparisons


def _kpi_gap_profiles(scopes: dict[tuple, dict[str, dict[str, Any]]], environment: str,
                      reliable_codes: set[str]) -> list[dict[str, Any]]:
    """Per compared operator: the points lost against the maximum and the GAP to the reference, per KPI."""
    profiles = []
    for tables in scopes.values():
        table = tables.get(environment)
        if table is None:
            continue
        if environment == COMBINED:
            columns = [name for name, source in tables.items() if name != COMBINED
                       and any((_number(row.get('max_points')) or 0) > 0 for row in _kpi_rows(source))]
        else:
            columns = [environment]
        if not columns:
            continue
        reference = table.get('baseline_operator')
        for operator in table.get('operators', []):
            rows = []
            for row in _kpi_rows(table):
                to_maximum: dict[str, float | None] = {}
                to_reference: dict[str, float | None] = {}
                for name in columns:
                    source = next((item for item in _kpi_rows(tables[name]) if item['kpi_code'] == row['kpi_code']), None)
                    maximum = _number((source or {}).get('max_points')) or 0.0
                    points = _number((((source or {}).get('values') or {}).get(operator) or {}).get('points'))
                    to_maximum[name] = maximum - points if points is not None and maximum > 0 else None
                    gap = ((source or {}).get('gaps') or {}).get(operator)
                    to_reference[name] = _number(gap) if operator != reference else None
                if all(value is None for value in to_maximum.values()):
                    continue
                rows.append({
                    'kpi_code': row['kpi_code'], 'kpi': row.get('kpi'), 'category': row.get('category'),
                    'service': _service(row), 'most_reliable': row['kpi_code'] in reliable_codes,
                    'gap_to_maximum': to_maximum,
                    'total_gap_to_maximum': sum(value for value in to_maximum.values() if value is not None),
                    'gap_to_reference': to_reference,
                    'total_gap_to_reference': (sum(value for value in to_reference.values() if value is not None)
                                               if any(value is not None for value in to_reference.values()) else None),
                })
            if not rows:
                continue
            style = (table.get('operator_styles') or {}).get(operator) or {}
            profiles.append({
                'environment': environment, 'operator': operator, 'label': style.get('label') or operator,
                'color': style.get('color'), 'reference': reference, 'reference_label': ((table.get('operator_styles') or {}).get(reference) or {}).get('label') or reference,
                'context': {field: table['context'].get(field) for field in _CONTEXT_FIELDS if table['context'].get(field) not in (None, '')},
                'columns': columns,
                'to_maximum': sorted(rows, key=lambda item: -item['total_gap_to_maximum']),
                'to_reference': sorted(
                    (item for item in rows if item['total_gap_to_reference'] is not None),
                    key=lambda item: item['total_gap_to_reference']),
                'underline_most_reliable': bool(reliable_codes),
            })
    return profiles
