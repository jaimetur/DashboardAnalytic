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
        f'{export_time:%Y%m%d_%H%M%S} - {nr_mode_label} -  -  - {safe_scope}'.encode('utf-8')
    )
    zone_budget = max_stem_bytes - fixed_bytes - 4
    safe_zone = _filename_part(zone_label, zone_budget) if zone_label else ''
    suffix_parts = [part for part in (safe_scope, safe_zone) if part]
    name_budget = max(
        4,
        max_stem_bytes - len(
            f'{export_time:%Y%m%d_%H%M%S} - {nr_mode_label} -  - {" - ".join(suffix_parts)}'.encode('utf-8')
        ),
    )
    safe_name = _filename_part(dashboard_name, name_budget) or _filename_part('Dashboard', name_budget)
    timestamp = export_time.strftime('%Y%m%d_%H%M%S')
    return ' - '.join((timestamp, nr_mode_label, safe_name, *suffix_parts)) + safe_campaigns + '.pptx'


def build_scoring_report_filename(
    export_time: datetime,
    nr_mode_label: str,
    context_filters: dict[str, object] | None = None,
) -> str:
    """Build a timestamped scoring filename from its saved dimension selections."""
    filters = {
        str(key).strip().casefold(): value
        for key, value in (context_filters.items() if isinstance(context_filters, dict) else [])
    }

    def selection(field: str, all_label: str) -> str:
        value = filters.get(field.casefold(), [])
        if isinstance(value, (list, tuple, set)):
            selected = list(dict.fromkeys(
                str(item).strip() for item in value
                if item is not None and str(item).strip()
            ))
        elif value is None:
            selected = []
        else:
            rendered = str(value).strip()
            selected = [rendered] if rendered else []
        if not selected or (len(selected) == 1 and selected[0].casefold() in {'all', all_label.casefold()}):
            return all_label
        return ' + '.join(selected)

    values = [
        selection('region', 'All Regions'),
        selection('city', 'All Cities'),
        selection('operator', 'All Operators'),
        selection('vendor', 'All Vendors'),
        selection('campaign', 'All Campaigns'),
    ]
    timestamp = export_time.strftime('%Y%m%d_%H%M%S')
    safe_mode = _filename_part(nr_mode_label or 'NSA', 10) or 'NSA'
    fixed = [timestamp, 'Scoring & GAP Analysis', safe_mode]
    fixed_bytes = len(' - '.join(fixed).encode('utf-8')) + len('.pptx'.encode('utf-8'))
    separators_bytes = 3 * (len(values))
    available = max(5, 245 - fixed_bytes - separators_bytes)
    budgets = [len(_filename_part(value, 245).encode('utf-8')) for value in values]
    excess = sum(budgets) - available
    while excess > 0:
        largest = max(range(len(budgets)), key=budgets.__getitem__)
        reduction = min(excess, max(1, budgets[largest] - 5))
        budgets[largest] -= reduction
        excess -= reduction
    safe_values = [_filename_part(value, budget) for value, budget in zip(values, budgets)]
    return ' - '.join([*fixed, *safe_values]) + '.pptx'
