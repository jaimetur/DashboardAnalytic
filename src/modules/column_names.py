from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from contextvars import ContextVar


COLUMN_IDENTITY_ALIASES = {
    'suscriber': 'subscriber',
    'suscribers': 'subscribers',
}

# Operator_Vendor is the operator-specific vendor (for example Vodafone_Ericsson)
# and Vendor the vendor alone (Ericsson); operators without a vendor store
# "<Operator> - All" in both.
OPERATOR_VENDOR_FIELD = 'Operator_Vendor'
VENDOR_FIELD = 'Vendor'
# <Vendor>_<Operator>: Operator_Vendor the other way round, derived when it is read (see mapping_order).
VENDOR_OPERATOR_FIELD = 'Vendor_Operator'

MAIN_CDR_FIELDS = (
    'Operator', 'Subscriber', OPERATOR_VENDOR_FIELD, VENDOR_FIELD,
    'Campaign', 'Benchmark', 'Campaign_Year', 'Campaign_Quarter', 'Period', 'Market',
    'Region', 'Zone', 'City',
    'Technology', 'RAT', 'RAT_A', 'L2_Call_Mode_A', 'Playing_Technology',
    'Session_Type', 'Type_Of_Test', 'Test_Name', 'Test_Result', 'Call_Status', 'Status',
    'Result', 'Event_Start_Time', 'Event_End_Time', 'Hour_Bucket', 'Day_Bucket',
)

PREVIEW_METADATA_FIELDS = ('Source_File', 'Source_Sheet', 'Dataset_Kind')

VENDOR_FIELD_IDENTITIES = frozenset({'vendor', 'operatorvendor'})
# Filter names that select the vendor alone; Vendor_Only and Vendor V3 are
# former names of the same field.
VENDOR_FILTER_IDENTITIES = frozenset({'vendor', 'vendoronly', 'vendorv3'})
OPERATOR_VENDOR_FILTER_IDENTITIES = frozenset({'operatorvendor', 'opvendor'})


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
    # An Operator whose name holds underscores (for example VF_SA) is removed whole.
    operator_text = str(operator or '').strip()
    if operator_text and text.casefold().startswith(operator_text.casefold() + '_'):
        return text[len(operator_text) + 1:]
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


# Campaign Maps (Workspace Config): how every chart, table, legend, filter and report
# shows campaigns. The label format uses markers filled from each campaign, so new
# campaigns follow it without editing the map: {year}, {yy}, {quarter}, {mode} (SA or
# NSA) and {market} (the country code such as UK). Characters inside the braces around
# a marker are written only when the campaign has that part: "{-mode}" writes "-SA" for
# an SA campaign and nothing otherwise. Campaigns are ordered by year and quarter, and
# the campaigns of one quarter by ``mode_order`` ("" is the campaign without a mode).
# Exceptions give their own label to campaigns that do not follow the pattern; they are
# ordered by the year and quarter of their label, or first (in their table order) when
# the label has none.
DEFAULT_CAMPAIGN_FORMAT = '{year}-Q{quarter}{-mode}'
DEFAULT_CAMPAIGN_MODE_ORDER = ('', 'NSA', 'SA')
DEFAULT_CAMPAIGN_MAP = {'format': DEFAULT_CAMPAIGN_FORMAT, 'mode_order': list(DEFAULT_CAMPAIGN_MODE_ORDER), 'exceptions': []}
CAMPAIGN_FORMAT_MARKER = re.compile(r'\{([^A-Za-z{}]*)(year|yy|quarter|mode|market)([^A-Za-z{}]*)\}')
_campaign_map_override: ContextVar[dict | None] = ContextVar('campaign_map_override', default=None)
_campaign_map_resolver: Callable[[], dict | None] | None = None


def normalize_campaign_map(config: object) -> dict:
    """A valid Campaign Map: label format, order of the radio modes and exceptions."""
    config = config if isinstance(config, dict) else {}
    label_format = str(config.get('format') or '').strip() or DEFAULT_CAMPAIGN_FORMAT
    if len(label_format) > 80:
        raise ValueError('The campaign label format is limited to 80 characters.')
    unknown = [name for name in re.findall(r'\{[^A-Za-z{}]*([A-Za-z_]+)[^A-Za-z{}]*\}', label_format)
               if name not in {'year', 'yy', 'quarter', 'mode', 'market'}]
    if unknown:
        raise ValueError(f'Unknown campaign label markers: {", ".join(sorted(set(unknown)))}. '
                         'Use {year}, {yy}, {quarter}, {mode} and {market}.')
    if not CAMPAIGN_FORMAT_MARKER.search(label_format):
        raise ValueError('The campaign label format needs at least one marker such as {year} or {quarter}.')
    modes = [str(value or '').strip().upper() for value in config.get('mode_order') or []]
    modes = [mode for mode in dict.fromkeys(modes) if mode in DEFAULT_CAMPAIGN_MODE_ORDER]
    modes += [mode for mode in DEFAULT_CAMPAIGN_MODE_ORDER if mode not in modes]
    exceptions, seen_sources, seen_labels = [], set(), set()
    for item in config.get('exceptions') or []:
        if not isinstance(item, dict):
            raise ValueError('The campaign exceptions are invalid.')
        label = re.sub(r'\s+', ' ', str(item.get('label') or '')).strip()[:80]
        raw_sources = item.get('sources')
        if isinstance(raw_sources, str):
            raw_sources = raw_sources.splitlines()
        sources = list(dict.fromkeys(source for value in raw_sources or [] if (source := str(value).strip())))
        if not label and not sources:
            continue
        if not label:
            raise ValueError('Every campaign exception needs a label.')
        if not sources:
            raise ValueError(f'The campaign exception "{label}" needs at least one source campaign.')
        if label.casefold() in seen_labels:
            raise ValueError(f'The campaign label "{label}" is repeated.')
        repeated = [source for source in sources if source.casefold() in seen_sources]
        if repeated:
            raise ValueError(f'These campaigns belong to more than one exception: {", ".join(repeated)}.')
        seen_labels.add(label.casefold())
        seen_sources.update(source.casefold() for source in sources)
        exceptions.append({'label': label, 'sources': sources})
    return {'format': label_format, 'mode_order': modes, 'exceptions': exceptions}


def set_campaign_map_resolver(resolver: Callable[[], dict | None] | None) -> None:
    """Install the function returning the Campaign Map of the active workspace."""
    global _campaign_map_resolver
    _campaign_map_resolver = resolver


@contextmanager
def use_campaign_map(config: dict | None):
    """Use a workspace's Campaign Map in this context (jobs of a workspace that is not active)."""
    token = _campaign_map_override.set(normalize_campaign_map(config) if config is not None else None)
    try:
        yield
    finally:
        _campaign_map_override.reset(token)


def current_campaign_map() -> dict:
    override = _campaign_map_override.get()
    if override is not None:
        return override
    if _campaign_map_resolver is not None:
        try:
            resolved = _campaign_map_resolver()
        except Exception:  # noqa: BLE001 - labels fall back to the default map when the workspace cannot be read.
            resolved = None
        if resolved is not None:
            return resolved
    return DEFAULT_CAMPAIGN_MAP


def _campaign_text(value: object) -> str:
    text = '' if value is None else str(value).strip()
    return '' if text.casefold() in {'<na>', 'nan', 'nat', 'none'} else text


def campaign_market(value: object) -> str:
    """The country code that starts or ends a campaign (UK in UK_Q2_2026), if any."""
    for token in re.split(r'[^A-Za-z0-9]+', _campaign_text(value)):
        if re.fullmatch(r'[A-Z]{2,3}', token) and token not in {'SA', 'NSA'}:
            return token
    return ''


def _exception_for(text: str, config: dict) -> tuple[int, dict] | None:
    key = text.casefold()
    for index, item in enumerate(config.get('exceptions') or []):
        if key == item['label'].casefold() or any(key == source.casefold() for source in item['sources']):
            return index, item
    return None


def format_campaign(value: object, config: dict | None = None) -> str:
    """The label of a campaign with a Campaign Map (the workspace's one by default)."""
    config = config or current_campaign_map()
    text = _campaign_text(value)
    if not text:
        return ''
    exception = _exception_for(text, config)
    if exception:
        return exception[1]['label']
    year, quarter, mode = campaign_parts(text)
    if not year or not quarter:
        return text
    parts = {'year': year, 'yy': year[-2:], 'quarter': quarter[1:], 'mode': mode or '', 'market': campaign_market(text)}

    def marker(match: re.Match) -> str:
        filled = parts[match.group(2)]
        return f'{match.group(1)}{filled}{match.group(3)}' if filled else ''

    return CAMPAIGN_FORMAT_MARKER.sub(marker, config.get('format') or DEFAULT_CAMPAIGN_FORMAT)


def compact_campaign_value(value: object) -> str:
    """The campaign as every chart, table, legend, filter and report shows it (see Campaign Maps).

    With the default map UK_Q2_2026 reads 2026-Q2, UK_Q2_NSA_2026 reads 2026-Q2-NSA and
    UK_Q2_SA_2026 (or 2026-Q2_SA) reads 2026-Q2-SA; values without a year and quarter are
    kept. Comparisons normalise both sides with it, so any spelling matches the same campaign.
    """
    return format_campaign(value)


def campaign_sort_key(value: object, config: dict | None = None) -> tuple[int, int, int, int, str]:
    """Campaign order with a Campaign Map: year, quarter, then the order of the radio modes.

    Campaigns and exception labels without a year and quarter come first, exceptions in
    their table order.
    """
    config = config or current_campaign_map()
    text = _campaign_text(value)
    exception = _exception_for(text, config)
    label = exception[1]['label'] if exception else text
    year, quarter, mode = campaign_parts(label if exception else text)
    if not year or not quarter:
        return (-1, -1, exception[0] if exception else len(config.get('exceptions') or []), 0, label.casefold())
    modes = config.get('mode_order') or list(DEFAULT_CAMPAIGN_MODE_ORDER)
    rank = modes.index(mode or '') if (mode or '') in modes else len(modes)
    return (int(year), int(quarter[1]), rank, exception[0] + 1 if exception else 0, label.casefold())


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


def vendor_filter_column(column: object) -> str:
    """Route every vendor filter name to its field: Vendor or Operator_Vendor."""
    identity = column_identity(column)
    if identity in VENDOR_FILTER_IDENTITIES:
        return VENDOR_FIELD
    if identity in OPERATOR_VENDOR_FILTER_IDENTITIES:
        return OPERATOR_VENDOR_FIELD
    return str(column)


def is_vendor_filter(column: object) -> bool:
    """Whether a filter name selects the vendor alone."""
    return column_identity(column) in VENDOR_FILTER_IDENTITIES


def is_operator_vendor_filter(column: object) -> bool:
    """Whether a filter name selects the operator-specific vendor."""
    return column_identity(column) in OPERATOR_VENDOR_FILTER_IDENTITIES


def vendor_filter_value(value: object, operators=()) -> str:
    """Normalize legacy composite filter values using configured operator aliases."""
    text = re.sub(r'\s+- All(?: Vendors)?$', '', str(value or '').strip(), flags=re.IGNORECASE)
    names = sorted({str(item).strip() for item in operators if item}, key=len, reverse=True)
    if text.casefold() in {name.casefold() for name in names}:
        return text
    for operator in names:
        if text.casefold().startswith(operator.casefold() + '_'):
            return text[len(operator) + 1:]
    for operator in names:
        stripped = vendor_only_value(text, operator)
        if stripped != text:
            return stripped
    return text


def mapped_vendor_only_value(vendor: object, operator: object = '') -> str:
    """Persist the operator-only identity with an explicit All suffix."""
    operator_text = '' if operator is None else str(operator).strip()
    text = '' if vendor is None else str(vendor).strip()
    if re.search(r'\s+- All(?: Vendors)?$', text, flags=re.IGNORECASE):
        return re.sub(r'\s+- All(?: Vendors)?$', ' - All', text, flags=re.IGNORECASE)
    if operator_text and (not text or column_identity(text) == column_identity(operator_text)):
        return f'{operator_text} - All'
    return vendor_only_value(text, operator_text)


def operator_vendor_value(vendor: object, operator: object = '') -> str:
    """The operator-specific vendor: <Operator>_<Vendor>, or "<Operator> - All" without a vendor."""
    operator_text = '' if operator is None else str(operator).strip()
    text = '' if vendor is None or str(vendor).strip().casefold() in {'nan', '<na>', 'none'} else str(vendor).strip()
    if re.search(r'\s+- All(?: Vendors)?$', text, flags=re.IGNORECASE):
        return re.sub(r'\s+- All(?: Vendors)?$', ' - All', text, flags=re.IGNORECASE)
    if not operator_text:
        return text
    if not text or column_identity(text) == column_identity(operator_text):
        return f'{operator_text} - All'
    if vendor_only_value(text, operator_text) != text:
        return text
    return f'{operator_text}_{text}'


def operator_vendor_filter_values(values, operators=()) -> list[str]:
    """Match Operator_Vendor values, including an Operator name saved before "<Operator> - All"."""
    mappings = {str(alias).strip().casefold(): str(canonical).strip() for alias, canonical in operators.items()} if isinstance(operators, dict) else {}
    names = {str(name).strip().casefold() for name in [*mappings.keys(), *mappings.values(), *([] if mappings else operators)] if name}
    result = []
    for value in values:
        text = str(value or '').strip()
        result.append(text)
        if text.casefold() in names:
            canonical = mappings.get(text.casefold(), text)
            result.extend((f'{canonical} - All', f'{text} - All'))
        elif re.search(r'\s+- All(?: Vendors)?$', text, flags=re.IGNORECASE):
            result.append(re.sub(r'\s+- All(?: Vendors)?$', ' - All', text, flags=re.IGNORECASE))
    return list(dict.fromkeys(result))


def vendor_filter_values(values, operators=()) -> list[str]:
    """Match current and legacy operator-only values during cache transitions."""
    mappings = {str(alias).strip().casefold(): str(canonical).strip() for alias, canonical in operators.items()} if isinstance(operators, dict) else {}
    operators = [*mappings.keys(), *mappings.values()] if mappings else list(operators)
    names = {str(operator).strip().casefold() for operator in operators if operator}
    result = []
    for value in values:
        text = vendor_filter_value(value, operators)
        result.append(text)
        if text.casefold() in names or re.search(r'\s+- All(?: Vendors)?$', str(value), flags=re.IGNORECASE):
            canonical = mappings.get(text.casefold(), text)
            result.extend((canonical, f'{canonical} - All', f'{canonical} - All Vendors', f'{text} - All', f'{text} - All Vendors'))
    return list(dict.fromkeys(result))


def vendor_match_values(field: object, values, operators=()) -> list[str]:
    """Filter values to match on a field, accepting former Vendor and Operator_Vendor spellings."""
    column = vendor_filter_column(field)
    if column == VENDOR_FIELD:
        return vendor_filter_values(values, operators)
    if column == OPERATOR_VENDOR_FIELD:
        return operator_vendor_filter_values(values, operators)
    return [str(value) for value in values]


def vendor_filter_rank(value: object) -> int:
    """0 for vendors, 1 for mixed, other and all-vendor groups, 2 for operators without a vendor."""
    text = str(value or '').strip()
    if re.search(r'\s-\sAll(?: Vendors)?$', text, flags=re.IGNORECASE):
        return 2
    key = re.sub(r'[^a-z0-9]', '', text.casefold())
    return 1 if any(part in key for part in ('mixed', 'othervendor', 'allvendor')) else 0


def sort_vendor_values(values: Iterable[object]) -> list:
    """Vendor filter values in the order used everywhere: vendors, then mixed groups, then
    operators without a vendor, each block alphabetically."""
    return sorted(values, key=lambda value: (vendor_filter_rank(value), str(value or '').strip().casefold()))
