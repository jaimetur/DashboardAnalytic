from __future__ import annotations

import re
from collections.abc import Iterable


COLUMN_IDENTITY_ALIASES = {
    'suscriber': 'subscriber',
    'suscribers': 'subscribers',
}

MAIN_CDR_FIELDS = (
    'Operator', 'Subscriber', 'Vendor', 'Vendor_Only',
    'Campaign', 'Benchmark', 'Campaign_Year', 'Campaign_Quarter', 'Period', 'Market',
    'Region', 'Zone', 'City',
    'Technology', 'RAT', 'RAT_A', 'L2_Call_Mode_A', 'Playing_Technology',
    'Session_Type', 'Type_Of_Test', 'Test_Name', 'Test_Result', 'Call_Status', 'Status',
    'Result', 'Event_Start_Time', 'Event_End_Time', 'Hour_Bucket', 'Day_Bucket',
)

PREVIEW_METADATA_FIELDS = ('Source_File', 'Source_Sheet', 'Dataset_Kind')

VENDOR_FIELD_IDENTITIES = frozenset({'vendor', 'vendoronly'})


def clean_column_name(value: object) -> str:
    """Return a persistent name without legacy SQLite ``__N`` suffixes."""
    name = str(value or '').strip() or 'Column'
    match = re.fullmatch(r'(.+?)__(\d+)', name)
    return f'{match.group(1)}_Duplicate_{match.group(2)}' if match else name


def vendor_only_value(vendor: object, operator: object = '') -> str:
    """Remove a recognized operator prefix from a mapped Vendor value."""
    text = '' if vendor is None else str(vendor).strip()
    if not text or '_' not in text:
        return text
    prefix, remainder = text.split('_', 1)
    normalized_prefix = re.sub(r'[^a-z0-9]+', '', prefix.casefold())
    normalized_operator = re.sub(r'[^a-z0-9]+', '', str(operator or '').casefold())
    groups = (
        {'vf', 'vodafone', 'vodafoneuk'},
        {'3', 'three', 'threeuk', 'h3g', 'h3guk'},
        {'o2', 'o2uk', 'telefonica'},
        {'ee', 'everythingeverywhere'},
    )
    if normalized_prefix == normalized_operator or any(
        normalized_prefix in group and normalized_operator in group for group in groups
    ):
        return remainder
    return text


def campaign_parts(value: object) -> tuple[str | None, str | None, str | None]:
    """Extract year, quarter and optional SA/NSA mode without changing source text."""
    text = '' if value is None else str(value).strip()
    if text.casefold() in {'<na>', 'nan', 'nat', 'none'}:
        text = ''
    year_match = re.search(r'(?<!\d)((?:19|20)\d{2})(?!\d)', text)
    quarter_match = re.search(r'(?:^|[^A-Z0-9])Q\s*[_\- ]?([1-4])(?=$|[^0-9])', text, flags=re.I)
    mode_match = re.search(r'(?:^|[_\- ])(NSA|SA)(?=$|[_\- ])', text, flags=re.I)
    return (
        year_match.group(1) if year_match else None,
        f'Q{quarter_match.group(1)}' if quarter_match else None,
        mode_match.group(1).upper() if mode_match else None,
    )


def compact_campaign_value(value: object) -> str:
    """Return a compact comparison/display value while preserving optional radio mode."""
    year, quarter, mode = campaign_parts(value)
    if not year or not quarter:
        text = '' if value is None else str(value).strip()
        return '' if text.casefold() in {'<na>', 'nan', 'nat', 'none'} else text
    return f'{year}-{quarter}{f"_{mode}" if mode else ""}'


def column_identity(value: object) -> str:
    """Return the shared identity used for CDR field-name matching."""
    identity = re.sub(r'[^a-z0-9]+', '', str(value or '').casefold())
    return COLUMN_IDENTITY_ALIASES.get(identity, identity)


def resolve_column_name(columns: Iterable[object], requested: object) -> str | None:
    """Resolve a field regardless of case, separators and supported spelling aliases."""
    available = [str(column) for column in columns]
    requested_text = str(requested or '').strip()
    if not requested_text:
        return None
    if requested_text in available:
        return requested_text
    requested_casefold = requested_text.casefold()
    case_match = next((column for column in available if column.strip().casefold() == requested_casefold), None)
    if case_match:
        return case_match
    requested_identity = column_identity(requested_text)
    return next((column for column in available if column_identity(column) == requested_identity), None)
