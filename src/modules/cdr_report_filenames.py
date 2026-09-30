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
