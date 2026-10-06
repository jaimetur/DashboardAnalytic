"""Shared filename formatting for CDR-related PowerPoint exports."""
from __future__ import annotations

from datetime import datetime
import re


def _filename_part(value: str, max_bytes: int) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(value)).strip(' .')
    if len(safe.encode('utf-8')) <= max_bytes:
        return safe
    clipped = safe.encode('utf-8')[:max_bytes - 3].decode('utf-8', errors='ignore').rstrip(' .,_-&')
    return f'{clipped}…' if clipped else '…'


def build_cdr_report_filename(
    export_time: datetime,
    nr_mode_label: str,
    dashboard_name: str,
    scope_label: str,
    zone_label: str = '',
    campaign_suffix: str = '',
) -> str:
    """Build the standard timestamped filename for a CDR PowerPoint export."""
    safe_campaigns = f' - {_filename_part(campaign_suffix, 60)}' if campaign_suffix else ''
    max_stem_bytes = 240 - len(safe_campaigns.encode('utf-8'))
    safe_scope = _filename_part(scope_label, 40)
    fixed_bytes = len(
        f'{export_time:%Y%m%d_%H%M%S} - E2E Dashboards - {nr_mode_label} -  -  - {safe_scope}'.encode('utf-8')
    )
    zone_budget = max_stem_bytes - fixed_bytes - 4
    safe_zone = _filename_part(zone_label, zone_budget) if zone_label else ''
    suffix_parts = [part for part in (safe_scope, safe_zone) if part]
    name_budget = max(
        4,
        max_stem_bytes - len(
            f'{export_time:%Y%m%d_%H%M%S} - E2E Dashboards - {nr_mode_label} -  - {" - ".join(suffix_parts)}'.encode('utf-8')
        ),
    )
    safe_name = _filename_part(dashboard_name, name_budget) or _filename_part('Dashboard', name_budget)
    timestamp = export_time.strftime('%Y%m%d_%H%M%S')
    # Every document starts with its time stamp and module.
    return ' - '.join((timestamp, 'E2E Dashboards', nr_mode_label, safe_name, *suffix_parts)) + safe_campaigns + '.pptx'


SCORING_LIST_MAX_CHARACTERS = 110

_SCORING_FIELDS = {
    'region': 'All Regions', 'cluster': 'All Clusters', 'city': 'All Cities', 'operator': 'All Operators',
    'vendor': 'All Vendors', 'campaign': 'All Campaigns',
}


def scoring_display_selections(context_filters, *, max_characters: int = SCORING_LIST_MAX_CHARACTERS,
                               campaign_values=None, aggregation_values=None,
                               nr_mode_label: str = 'NSA') -> dict:
    """Retain complete values within the presentation list limit."""
    filters = context_filters if isinstance(context_filters, dict) else {}
    if isinstance(context_filters, list):
        filters = {}
        for item in context_filters:
            if isinstance(item, dict):
                key = str(item.get('column') or item.get('field') or '').casefold()
                value = item.get('value', item.get('values', []))
                filters.setdefault(key, []).extend(value if isinstance(value, (list, tuple, set)) else [value])
    filters = {str(key).strip().casefold(): value for key, value in filters.items()}

    def values(value, fallback):
        if not isinstance(value, (list, tuple, set)):
            value = [value]
        if isinstance(value, set):
            value = sorted(value, key=str)
        selected = list(dict.fromkeys(re.sub(r'\s+', ' ', str(item)).strip()
                                      for item in value if item is not None and str(item).strip()))
        return [fallback] if not selected or (len(selected) == 1 and selected[0].casefold() in {'all', fallback.casefold()}) else selected

    original = {key: values(filters.get(key, []), fallback) for key, fallback in _SCORING_FIELDS.items()}
    if campaign_values is not None:
        original['campaign'] = values(campaign_values, 'All Campaigns')
    original['aggregation'] = values(aggregation_values or ['Operator'], 'Operator')
    retained = {key: list(value) for key, value in original.items()}
    def fit_line(key, selected):
        while selected and len(', '.join(selected)) > max_characters:
            selected.pop()

    for key, selected in retained.items():
        fit_line(key, selected)

    return {'values': retained, 'omitted': {key: len(retained[key]) < len(value) for key, value in original.items()}}


def _scoring_filename(export_time: datetime, nr_mode_label: str, selections: dict[str, list[str]]) -> str:
    safe_mode = re.sub(r'[^A-Za-z0-9_-]', '', str(nr_mode_label or 'NSA'))[:10] or 'NSA'
    fixed = [f'{export_time:%Y%m%d_%H%M%S}', 'Scoring & GAP Analysis', safe_mode]
    parts = [re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', ' + '.join(selections[key])).strip(' .')
             for key in _SCORING_FIELDS]
    return ' - '.join([*fixed, *parts]) + '.pptx'


def build_scoring_report_filename(export_time: datetime, nr_mode_label: str,
                                  context_filters: dict[str, object] | None = None,
                                  *, display_selections: dict | None = None) -> str:
    """Build a bounded filename using complete values retained on intro slides."""
    plan = display_selections or scoring_display_selections(context_filters, nr_mode_label=nr_mode_label)
    selected = {key: list(plan['values'][key]) for key in _SCORING_FIELDS}
    while len(_scoring_filename(export_time, nr_mode_label, selected).encode('utf-8')) > 245:
        candidates = [key for key in _SCORING_FIELDS if selected[key] and selected[key] != [_SCORING_FIELDS[key]]]
        if not candidates:
            break
        key = max(candidates, key=lambda field: len(' + '.join(selected[field]).encode('utf-8')))
        selected[key].pop()
    return _scoring_filename(export_time, nr_mode_label, selected)
