"""National & Area Summary: the National scoring next to the scoring of chosen cities and areas.

A scoring job of the whole country (no Region, Cluster or City filters) can ask for an area
summary. The same job, from the CDR rows it already loaded, then calculates up to three
scorings with different Split by levels:

* National: Operator, split by the summary's time split;
* the chosen cities (for example London), each scored with its own tests only;
* the breakdown: one scoring per Region, Cluster or City.

The time split of the summary aggregates every selected CDR into one value (All), splits by
Campaign, or splits by the Daily, Weekly, Monthly, Quarterly or Yearly period of the start time
of each test. Each area is scored with its own measurements: KPI values (rates, medians,
P90...) are not additive and the points come from non-linear thresholds, so they cannot be
derived from the National scoring. A calculation equal to the job's own reuses the job's result.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from src.modules.column_names import campaign_sort_key, column_identity, resolve_column_name
from src.modules.scoring import START_TIME_COLUMNS, normalize_time_split

AREA_SUMMARY_BREAKDOWNS = ('Region', 'Cluster', 'City')
GEOGRAPHIC_FILTER_FIELDS = ('Region', 'Cluster', 'City')
# All aggregates every selected CDR; Campaign splits by campaign; the periods split by the tests' start time.
AREA_SUMMARY_TIME_SPLITS = ('All', 'Campaign', 'Daily', 'Weekly', 'Monthly', 'Quarterly', 'Yearly')
NATIONAL = 'National'
_CITY_COLUMNS = ('City', 'G_Level_4')
# Saved per calculation: what the views of the summary read. The points-lost shares stay with the job's own result.
_PASS_RESULT_KEYS = ('scoring', 'totals', 'global_kpis', 'environment_scaling', 'aggregation_levels',
                     'aggregation_contract_version', 'campaigns', 'warnings', 'notices', 'baseline_aliases')


def normalize_area_summary_request(area_summary: Any, context_filters: dict[str, list[str]]) -> dict[str, Any] | None:
    """The breakdown level, the chosen cities and the time split of a job's area summary, or None
    without a breakdown or cities.

    The summary needs the whole country: a job with Region, Cluster or City filters cannot have one.
    """
    if not isinstance(area_summary, dict):
        return None
    requested = str(area_summary.get('breakdown') or '').strip().casefold()
    breakdown = next((name for name in AREA_SUMMARY_BREAKDOWNS if name.casefold() == requested), None)
    split = str(area_summary.get('time_split') or '').strip().casefold()
    time_split = next((name for name in AREA_SUMMARY_TIME_SPLITS if name.casefold() == split), 'Campaign')
    cities: dict[str, str] = {}
    for value in area_summary.get('cities') or []:
        text = str(value).strip()
        if text:
            cities.setdefault(text.casefold(), text)
    if breakdown is None and not cities:
        return None
    if any((context_filters or {}).get(field) for field in GEOGRAPHIC_FILTER_FIELDS):
        raise ValueError('The National & Area Summary needs the whole country: remove the Region, Cluster and City filters.')
    return {'breakdown': breakdown, 'cities': list(cities.values()), 'time_split': time_split}


def area_summary_levels(levels: list[str], area_summary: dict[str, Any] | None) -> list[str]:
    """The columns the job reads for its area summary, besides its own levels: the breakdown, City
    and, to split by period, the start time of the tests."""
    if not area_summary:
        return []
    extra = [area_summary['breakdown']] if area_summary.get('breakdown') else []
    if area_summary.get('cities') and 'City' not in extra:
        extra.append('City')
    if normalize_time_split(area_summary.get('time_split')):
        extra.extend(START_TIME_COLUMNS)
    identities = {column_identity(level) for level in levels}
    return [level for level in extra if column_identity(level) not in identities]


def _passes(levels: list[str], area_summary: dict[str, Any]) -> list[dict[str, Any]]:
    time_split = area_summary.get('time_split') or 'Campaign'
    base = ['Operator'] if time_split == 'All' else ['Operator', 'Campaign']
    breakdown = area_summary.get('breakdown')
    passes = [{'kind': NATIONAL, 'field': None, 'levels': base}]
    # A City breakdown already scores the chosen cities: they are listed first among its rows.
    if area_summary.get('cities') and breakdown != 'City':
        passes.append({'kind': 'City', 'field': 'city', 'levels': [*base, 'City'], 'cities': area_summary['cities']})
    if breakdown:
        passes.append({'kind': breakdown, 'field': breakdown.lower(), 'levels': [*base, breakdown]})
    identities = {column_identity(level) for level in levels}
    # A calculation split by period is never the job's own, which splits Campaign by campaign.
    for item in passes:
        item['reuses_job'] = (not normalize_time_split(time_split) and 'cities' not in item
                              and {column_identity(level) for level in item['levels']} == identities)
    return passes


def _city_frames(frames: dict[str, pd.DataFrame], cities: list[str]) -> dict[str, pd.DataFrame]:
    wanted = {city.casefold() for city in cities}
    selected = {}
    for kind, frame in frames.items():
        column = next((resolved for alias in _CITY_COLUMNS
                       if (resolved := resolve_column_name(frame.columns, alias)) is not None), None)
        if column is None:
            continue
        mask = frame[column].astype('string').str.strip().str.casefold().isin(wanted).fillna(False)
        if mask.any():
            selected[kind] = frame[mask.to_numpy(dtype=bool)].reset_index(drop=True)
    return selected


def calculate_area_summary(calculate: Callable[..., dict], frames: dict[str, pd.DataFrame], levels: list[str],
                           area_summary: dict[str, Any], call_kwargs: dict[str, Any],
                           progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    """Score the National, chosen-city and breakdown calculations of an area summary from the loaded rows."""
    passes = []
    warnings = []
    period = normalize_time_split(area_summary.get('time_split'))
    kwargs = {**call_kwargs, 'time_split': period} if period else call_kwargs
    for index, item in enumerate(_passes(levels, area_summary)):
        saved = {key: item[key] for key in ('kind', 'field', 'levels', 'reuses_job') if key in item}
        if 'cities' in item:
            saved['cities'] = item['cities']
        if not item['reuses_job']:
            if progress is not None:
                progress(88 + index * 2, f"Calculating the {item['kind']} scoring of the area summary")
            source = _city_frames(frames, item['cities']) if 'cities' in item else frames
            result = calculate(source, item['levels'], **kwargs) if source else {}
            rows = result.get('scoring') if isinstance(result, dict) else None
            if not rows or (item['field'] and not any(row.get(item['field']) not in (None, '') for row in rows)):
                what = ', '.join(item['cities']) if 'cities' in item else item['kind']
                warnings.append(f'National & Area Summary: the selected CDRs have no {what} measurements.')
                continue
            saved['result'] = {key: result[key] for key in _PASS_RESULT_KEYS if key in result}
        passes.append(saved)
    return {'breakdown': area_summary.get('breakdown'), 'cities': list(area_summary.get('cities') or []),
            'time_split': area_summary.get('time_split') or 'Campaign', 'passes': passes, 'warnings': warnings}


def most_reliable_area_summary(summary: Any, transform: Callable[[dict], dict | None]) -> Any:
    """The area summary of the Most Reliable scoring: each calculation transformed like the job's own result."""
    if not isinstance(summary, dict) or not isinstance(summary.get('passes'), list):
        return summary
    passes = []
    for item in summary['passes']:
        if isinstance(item, dict) and isinstance(item.get('result'), dict):
            reliable = transform(item['result'])
            if reliable is None:
                continue
            item = {**item, 'result': reliable}
        passes.append(item)
    return {**summary, 'passes': passes}


def _single_value(rows: list[dict[str, Any]], field: str) -> Any:
    values = {row.get(field) for row in rows if row.get(field) not in (None, '')}
    return next(iter(values)) if len(values) == 1 else None


def build_area_summary(job: dict[str, Any], result: dict[str, Any], operator_mapping_groups: list[dict] | None = None,
                       *, vendor_mapping_groups: list[dict] | None = None,
                       include_operator: Callable[[str, str], bool] | None = None) -> list[dict[str, Any]]:
    """One summary per environment: the areas in order (National, chosen cities, breakdown) and,
    for each operator, its points in the latest campaign, the GAP to the reference and the change
    from the previous campaign, with its points in every campaign for the trend charts.
    """
    from src.modules.scoring_insights import _scopes
    from src.modules.scoring_views import build_scoring_views

    summary = result.get('area_summary') if isinstance(result, dict) else None
    if not isinstance(summary, dict) or not summary.get('passes'):
        return []
    configuration = job.get('configuration') or result.get('configuration')
    chosen = [city.casefold() for city in summary.get('cities') or []]
    areas: list[dict[str, Any]] = []
    for item in summary['passes']:
        if item.get('reuses_job'):
            source, source_job = result, job
        else:
            source = item.get('result')
            if not isinstance(source, dict):
                continue
            source_job = {'levels': list(item['levels']), 'aggregation_levels': list(item['levels']),
                          'aggregation_contract_version': job.get('aggregation_contract_version') or 2,
                          'baseline_operator': job.get('baseline_operator') or 'EE',
                          'baseline_aliases': job.get('baseline_aliases') or source.get('baseline_aliases'),
                          'configuration': configuration}
        views = build_scoring_views(source_job, {**source, 'configuration': configuration}, operator_mapping_groups,
                                    vendor_mapping_groups=vendor_mapping_groups)
        field = item.get('field')
        single = _single_value(source.get('scoring') or [], field) if field else None
        # An area measured in a single campaign has no campaign in its scope: it is that campaign.
        single_campaign = _single_value(source.get('scoring') or [], 'campaign') if 'Campaign' in item['levels'] else None
        by_label: dict[str, dict[str, Any]] = {}
        for scope, tables in _scopes(views.get('score_tables', [])).items():
            context = dict(scope)
            label = NATIONAL if field is None else context.get(field) or single
            if label in (None, ''):
                continue
            area = by_label.setdefault(str(label), {'label': str(label), 'kind': item['kind'], 'campaigns': {}})
            area['campaigns'][context.get('campaign') or single_campaign] = tables
        found = list(by_label.values())
        if item['kind'] == 'City' or (field == 'city' and chosen):
            # The chosen cities first, in the order they were chosen.
            order = {city: index for index, city in enumerate(chosen)}
            found.sort(key=lambda area: (order.get(area['label'].casefold(), len(order)), area['label'].casefold()))
        elif field is not None:
            found.sort(key=lambda area: area['label'].casefold())
        areas.extend(found)
    if not areas:
        return []
    environments = list(dict.fromkeys(
        environment for area in areas for tables in area['campaigns'].values() for environment in tables
    ))
    summaries = [summary_item for environment in environments
                 if (summary_item := _environment_summary(areas, environment, include_operator)) is not None]
    for summary_item in summaries:
        summary_item['time_split'] = summary.get('time_split') or 'Campaign'
    return summaries


def _environment_summary(areas: list[dict[str, Any]], environment: str,
                         include_operator: Callable[[str, str], bool] | None) -> dict[str, Any] | None:
    from src.modules.scoring_insights import _scope_summary

    campaigns = sorted({campaign for area in areas for campaign in area['campaigns'] if campaign not in (None, '')},
                       key=campaign_sort_key)
    latest = campaigns[-1] if campaigns else None
    previous = campaigns[-2] if len(campaigns) > 1 else None
    styles: dict[str, dict[str, Any]] = {}
    rows_by_area = []
    maximum = None
    scaled = False
    for area in areas:
        points: dict[Any, dict[str, dict[str, Any]]] = {}
        for campaign, tables in area['campaigns'].items():
            summary = _scope_summary(tables, environment)
            if summary is None:
                continue
            maximum = summary['maximum'] if maximum is None else max(maximum, summary['maximum'])
            scaled = scaled or summary['scaled']
            points[campaign] = {item['operator']: item for item in summary['operators']}
        current = points.get(latest) if latest is not None else points.get(None)
        # An area without measurements in the latest campaign (one still being measured, for example) keeps its
        # operators and trend, without a score: those of the latest campaign it was measured in.
        measured = bool(current)
        if not measured:
            current = next((points[campaign] for campaign in reversed(campaigns) if points.get(campaign)), None)
            if not current:
                continue
        before = points.get(previous) if previous is not None and measured else None
        reference = next((item for item in current.values() if item['is_reference']), None)
        rows = []
        for operator, item in current.items():
            if include_operator is not None and not item['is_reference'] and not include_operator(operator, item['label']):
                continue
            styles.setdefault(operator, {'label': item['label'], 'color': item['color'],
                                         'is_reference': item['is_reference']})
            prior = (before or {}).get(operator)
            rows.append({
                'operator': operator, 'label': item['label'], 'color': item['color'],
                'is_reference': item['is_reference'], 'points': item['total'] if measured else None,
                'complete': item['complete'] or not measured, 'order': item['total'],
                'gap': None if reference is None or item['is_reference'] or not measured else item['total'] - reference['total'],
                'delta': None if prior is None else item['total'] - prior['total'],
                'trend': [((points.get(campaign) or {}).get(operator) or {}).get('total') for campaign in campaigns],
            })
        if not rows:
            continue
        # The reference first, then the operators from the highest score.
        rows.sort(key=lambda row: (not row['is_reference'], -row.pop('order')))
        rows_by_area.append({'label': area['label'], 'kind': area['kind'], 'measured': measured, 'rows': rows})
    # National alone summarises nothing.
    if len(rows_by_area) < 2:
        return None
    reference = next((style['label'] for style in styles.values() if style['is_reference']), None)
    return {
        'environment': environment, 'maximum': maximum, 'scaled': scaled,
        'campaigns': campaigns, 'latest_campaign': latest, 'previous_campaign': previous,
        'reference_label': reference, 'operators': styles, 'areas': rows_by_area,
    }
