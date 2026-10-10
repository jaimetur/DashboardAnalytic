"""The NQ Analysis Center catalog: sections, fields, root cause catalog and automatic status rules.

Every Non-Qualified Call is followed up with the fields of a workspace catalog, grouped in six
sections (General, RCA, Failure Event, Analysis, Implementation and Planning). A field gets its
value from one source:

- ``user``: entered by the analysts (lists, text, numbers, dates, Yes / No);
- ``tracking``: the follow-up of the call (status, team, assignee, last change, comments and the
  selected root category and cause);
- ``cdr``: an indexed call field or a CDR column (read only);
- ``rca``: the Root Cause Analysis script results imported by JOIN_ID (read only);
- ``derived``: a list value derived from call fields by keywords (for example the Session Type
  summary CALL / MULTI-RAB / WhatsApp).

The root cause catalog groups the Root Categories and the Root Causes of the analysts under the
technical Domains (RF, RAN, Core, IMS/E2E…): categories and causes are chosen independently, and
the domain of each one gives the colour, the grouping of the lists and the domain statistics.

The NQ Call Status follows ordered rules on the phase fields (Analysis, Implementation and
Planning status, or any other list or Yes / No field): the first rule whose conditions hold
gives the status, else the first status of the list. Rules name list values, so renaming a
value renames it in the rules and removing it removes it from them.

This module has no database access: it holds the defaults, validation and the Excel catalog
format shared by ``non_qualified_calls``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from io import BytesIO
from typing import Any

COLOR_PATTERN = re.compile(r'#[0-9a-fA-F]{6}')
_KEY = re.compile(r'[^a-z0-9]+')

# -- sections -----------------------------------------------------------------------------------
# The six sections of the Analysis Center, in the order of the call panel tabs. Implementation and Planning
# share one tab, in green (Planning darker); Failure Event is red. Their names and colours are editable; their keys are fixed.
SECTIONS = (
    ('general', 'General', '#0070C0'),
    ('rca', 'RCA', '#FFC000'),
    ('failure_event', 'Failure Details', '#FF0000'),
    ('analysis', 'Analysis', '#7030A0'),
    ('implementation', 'Implementation', '#00B050'),
    ('planning', 'Planning', '#00843D'),
)
# The colours of the first layout, replaced once while unchanged.
FIRST_SECTION_COLORS = {'failure_event': '#00B050', 'implementation': '#C55A11', 'planning': '#FF0000'}
# The section names of the first layout, renamed once while unchanged.
FIRST_SECTION_LABELS = {'failure_event': 'Failure Event'}
# The order of the Analysis fields in the first layout, replaced once while unchanged.
FIRST_ANALYSIS_ORDER = ('analysis_status', 'proposed_measure', 'tunnel_failure', 'failure_latitude', 'failure_longitude',
                        'problem_location', 'solution_location', 'needed_technology', 'findings')
SECTION_KEYS = tuple(key for key, _label, _color in SECTIONS)

# -- fields --------------------------------------------------------------------------------------
FIELD_TYPES = {
    'list': 'List', 'text': 'Text', 'long_text': 'Long text', 'number': 'Number', 'date': 'Date', 'yes_no': 'Yes / No',
}
FIELD_SOURCES = {
    'user': 'Entered by the analysts', 'tracking': 'Follow-up of the call', 'cdr': 'From the CDR',
    'rca': 'From the RCA script', 'derived': 'Derived from the call',
}
# Follow-up values a tracking field shows.
TRACKING_REFS = {
    'status': 'NQ Call Status', 'team': 'Team', 'assignee': 'Assignee', 'updated_at': 'Last modification',
    'comments': 'Comments', 'root_category': 'Root Category', 'root_cause': 'Root Cause',
}
# Values of the imported RCA script results; any other column of the file is kept as well.
RCA_REFS = {
    'auto_rca_category_a': 'Auto_RCA_Category_A', 'auto_rca_subcategory_a': 'Auto_RCA_Subcategory_A',
    'auto_rca_category_b': 'Auto_RCA_Category_B', 'auto_rca_subcategory_b': 'Auto_RCA_Subcategory_B',
    'rca_category': 'RCA Suggested Category', 'rca_cause': 'RCA Suggested Cause',
}
MAX_FIELDS = 120
MAX_FIELD_TEXT = 2000
MAX_LONG_TEXT = 20000
YES_NO = ('Yes', 'No')


def _clean(value: Any, limit: int = 80) -> str:
    return re.sub(r'\s+', ' ', str(value if value is not None else '')).strip()[:limit]


def field_key(label: str, taken: set[str]) -> str:
    """A stable key from a field name, unique among ``taken``."""
    base = _KEY.sub('_', label.casefold()).strip('_')[:40] or 'field'
    key, index = base, 2
    while key in taken:
        key, index = f'{base}_{index}', index + 1
    return key


def _option(name: str, color: str = '', keywords: tuple[str, ...] = ()) -> dict[str, Any]:
    return {'name': name, 'color': color, 'keywords': list(keywords)}


def _field(key: str, label: str, section: str, field_type: str, source: str = 'user', ref: str = '', *,
           options: tuple[dict[str, Any], ...] = (), in_table: bool = False, in_summary: bool = False,
           suggest_from: str = '', description: str = '') -> dict[str, Any]:
    return {
        'key': key, 'label': label, 'section': section, 'type': field_type, 'source': source, 'source_ref': ref,
        'options': [dict(option) for option in options], 'in_table': in_table, 'in_export': True, 'in_summary': in_summary,
        'required_to_close': False, 'suggest_from': suggest_from, 'description': description,
    }


_GREY, _AMBER, _GREEN, _RED, _BLUE, _SLATE = '#9aa5ad', '#e08a1e', '#2e8b57', '#b0234f', '#245a96', '#7b8790'
# The 37 fields of the meeting workbook, in its order (the order of the table and of the Excel export), with the
# Last Cell ID and Failure Comment of the CDR in Failure Details and the Analysis fields in the order of the call
# panel: the long texts (Proposed Measure, Findings) last.
DEFAULT_FIELDS = (
    _field('auto_rca_category_a', 'Auto_RCA_Category_A', 'rca', 'text', 'rca', 'auto_rca_category_a',
           description='Root cause category of the A side found by the RCA script (imported by JOIN_ID).'),
    _field('auto_rca_subcategory_a', 'Auto_RCA_Subcategory_A', 'rca', 'text', 'rca', 'auto_rca_subcategory_a',
           description='Root cause subcategory of the A side found by the RCA script.'),
    _field('auto_rca_category_b', 'Auto_RCA_Category_B', 'rca', 'text', 'rca', 'auto_rca_category_b',
           description='Root cause category of the B side found by the RCA script.'),
    _field('auto_rca_subcategory_b', 'Auto_RCA_Subcategory_B', 'rca', 'text', 'rca', 'auto_rca_subcategory_b',
           description='Root cause subcategory of the B side found by the RCA script.'),
    _field('rca_suggested_category', 'RCA Suggested Category', 'rca', 'text', 'rca', 'rca_category',
           description='Root category suggested by the RCA script.'),
    _field('rca_suggested_cause', 'RCA Suggested Cause', 'rca', 'text', 'rca', 'rca_cause', in_table=True,
           description='Root cause suggested by the RCA script.'),
    _field('netcheck_failure_classification', 'Netcheck Failure Classification', 'rca', 'text', 'cdr', 'failure_classification',
           description='Failure classification of the NetCheck RCA (CDR Failure_Classification).'),
    _field('netcheck_suggested_category', 'Netcheck Suggested Category', 'rca', 'text', 'cdr', 'failure_category',
           description='Category suggested by the NetCheck RCA (CDR Failure_Category).'),
    _field('netcheck_suggested_cause', 'Netcheck Suggested Cause', 'rca', 'text', 'cdr', 'failure_subcategory', in_table=True,
           description='Cause suggested by the NetCheck RCA (CDR Failure_Subcategory).'),
    _field('selected_root_category', 'Selected Root Category', 'rca', 'list', 'tracking', 'root_category', in_table=True,
           description='Final root category of the call, from the Root Categories of the root cause catalog.'),
    _field('selected_root_cause', 'Selected Root Cause', 'rca', 'list', 'tracking', 'root_cause', in_table=True,
           description='Final root cause of the call, from the Root Causes of the root cause catalog.'),
    _field('nq_call_status', 'NQ Call Status', 'general', 'list', 'tracking', 'status', in_table=True,
           description='Set by the status rules from the phase fields, or by hand.'),
    _field('team_responsible', 'Team Responsible', 'general', 'list', 'tracking', 'team', in_table=True),
    _field('assignee', 'Asignee', 'general', 'list', 'tracking', 'assignee', in_table=True,
           description='A member of the responsible team (any user of the workspace when the team has no members).'),
    _field('date_last_modification', 'Date last modification', 'general', 'date', 'tracking', 'updated_at',
           description='Set automatically each time the call is changed.'),
    _field('comments', 'Comments', 'general', 'long_text', 'tracking', 'comments', in_table=True,
           description='Every comment with its date, time and author (one per line in the Excel export).'),
    _field('session_type', 'Session Type', 'failure_event', 'list', 'derived', 'session_type,test_name', options=(
        _option('WhatsApp', '#25a35a', ('whatsapp',)), _option('MULTI-RAB', '#6a63c9', ('multirab', 'multi-rab', 'multi rab', 'mrab')),
        _option('CALL', _BLUE, ('call',)),
        _option('HTTP Transfer', '#0f6f7d', ('httptransfer', 'http transfer', 'fdfs')),
        _option('Browsing & Streaming', '#b85b20', ('httpbrowser', 'browser', 'videostreaming', 'video streaming', 'youtube')),
        _option('Interactivity & Ping', '#6941a4', ('interactivity', 'ping', 'icmp')),
    ), in_summary=True, description='CALL, MULTI-RAB or WhatsApp for Voice and Speech; three groups of tests for Data.'),
    _field('failed_party', 'Failed Party (MOC/MTC) (UE1/UE2)', 'failure_event', 'list', options=(
        _option('UE_A (MO)'), _option('UE_A (MT)'), _option('UE_B (MT)'), _option('UE_B (MO)'))),
    _field('host_network_when_failure', 'Host Network when Failure', 'failure_event', 'list', options=(
        _option('H3G'), _option('Vodafone'), _option('Telefónica')), suggest_from='operator'),
    _field('last_cell_id', 'Last Cell ID', 'failure_event', 'text', 'cdr', 'last_cell_id',
           description='The last cell of the Cell ID chain of the call in the CDR (the cell where it ended).'),
    _field('serving_cell_when_failure', 'Serving Cell when Failure', 'failure_event', 'text', suggest_from='last_cell_id'),
    _field('band_when_failure', 'Band when Failure', 'failure_event', 'list', options=tuple(_option(name) for name in (
        'LTE2100', 'LTE1400', 'LTE1800', 'LTE700', 'LTE800', 'LTE800-NBIoT', 'LTE900', 'LTE2300', 'LTE2600TDD', 'LTE2600',
        'LTE2100-NBIoT', 'NR3600', 'NR3400', 'NR2100', 'NR700', 'NR900', 'NR3700', 'GSM900', 'GSM1800'))),
    _field('vendor_when_failure', 'Vendor when Failure', 'failure_event', 'list', options=(
        _option('Ericsson'), _option('Huawei'), _option('NSN'), _option('Samsung')), suggest_from='vendor'),
    _field('failure_comment', 'Failure Comment', 'failure_event', 'long_text', 'cdr', 'failure_comment',
           description='The comment NetCheck writes on the failure in the CDR (Failure_Comment).'),
    _field('analysis_status', 'Analysis Status', 'analysis', 'list', options=(
        _option('Pending', _GREY), _option('Ongoing', _AMBER), _option('Finished', _GREEN),
        _option('Rejected', _RED), _option('Invalidated', _SLATE)), in_table=True, in_summary=True),
    _field('tunnel_failure', 'Tunnel Failure', 'analysis', 'yes_no'),
    _field('needed_technology', 'Needed Technology', 'analysis', 'text'),
    _field('failure_latitude', 'Failure Latitude', 'analysis', 'number', suggest_from='latitude'),
    _field('failure_longitude', 'Failure Longitude', 'analysis', 'number', suggest_from='longitude'),
    _field('problem_location', 'Problem Location', 'analysis', 'text'),
    _field('solution_location', 'Solution Location', 'analysis', 'text'),
    _field('proposed_measure', 'Proposed Measure', 'analysis', 'long_text'),
    _field('findings', 'Findings', 'analysis', 'long_text'),
    _field('implementation_status', 'Implementation Status', 'implementation', 'list', options=(
        _option('Not yet evaluated', _GREY), _option('Under evaluation', _AMBER), _option('Evaluated', _BLUE),
        _option('Implemented', _GREEN)), in_summary=True),
    _field('implementation_proposal', 'Implementation Proposal', 'implementation', 'list', options=tuple(_option(name) for name in (
        'New Site', 'NNS', 'Tilt', 'E2E Analysis', 'NR SA Layer Addition', 'NR Digital Tilt', 'RS Power', 'NR Power Boost'))),
    _field('implementation_site', 'Implementation Site', 'implementation', 'text'),
    _field('notice_to_vf3', 'Notice to VF3', 'implementation', 'yes_no'),
    _field('planned_status', 'Planned Status', 'planning', 'list', options=(
        _option('Not Planned', _GREY), _option('Planned', _GREEN)), in_summary=True),
    _field('planned_date', 'Planned Date', 'planning', 'date', description='Today by default; choose the date in the calendar.'),
)

# -- statuses, teams and status rules ---------------------------------------------------------
# (name, colour, closed)
DEFAULT_STATUSES = (
    ('Not Attended', '#9aa5ad', False),
    ('Open', '#d14a68', False),
    ('Under Analysis', '#7030A0', False),
    ('Under Implementation', '#C55A11', False),
    ('Under Planning', '#e0464e', False),
    ('Closed', '#2e8b57', True),
)
DEFAULT_TEAMS = (
    ('E2E stream', '#b85b20'), ('RAN Planning Coverage', '#0f6f7d'), ('RAN Planning Capacity', '#245a96'),
    ('RF OPT (Hot Spots) WP2a', '#c8102e'), ('Operations', '#5b6b2e'), ('Netcheck', '#6941a4'),
    ('Successful Call-Excluded', '#7b8790'), ('PCI Planning Team', '#e08a1e'),
)
# Conditions read list and Yes / No fields of the catalog, the team and assignee, and "@attended"
# (the call has been followed up or commented).
ATTENDED_FIELD = '@attended'
RULE_OPERATORS = {'in': 'is one of', 'not_in': 'is not one of', 'empty': 'is empty', 'not_empty': 'is not empty'}
DEFAULT_STATUS_RULES = (
    {'status': 'Closed', 'conditions': [{'field': 'analysis_status', 'op': 'in', 'values': ['Rejected', 'Invalidated']}]},
    {'status': 'Closed', 'conditions': [{'field': 'implementation_status', 'op': 'in', 'values': ['Implemented']}]},
    {'status': 'Under Planning', 'conditions': [{'field': 'planned_status', 'op': 'in', 'values': ['Planned']}]},
    {'status': 'Under Implementation', 'conditions': [
        {'field': 'implementation_status', 'op': 'in', 'values': ['Not yet evaluated', 'Under evaluation', 'Evaluated']}]},
    {'status': 'Closed', 'conditions': [{'field': 'analysis_status', 'op': 'in', 'values': ['Finished']}]},
    {'status': 'Under Analysis', 'conditions': [{'field': 'analysis_status', 'op': 'in', 'values': ['Ongoing']}]},
    {'status': 'Open', 'conditions': [{'field': ATTENDED_FIELD, 'op': 'in', 'values': ['Yes']}]},
)

# -- root cause catalog -----------------------------------------------------------------------
# Domains: (name, colour, keywords looked for in the CDR failure classification).
DEFAULT_DOMAINS = (
    ('RF', '#c8102e', ('rf',)),
    ('RAN', '#e08a1e', ('ran', 'paging')),
    ('Core 2G/4G/5G', '#6941a4', ('core', 'gsm')),
    ('Core EPSFB', '#245a96', ('epsfb', 'eps fallback')),
    ('IMS/E2E', '#b85b20', ('volte', 'ims')),
    ('AAA', '#2e8b57', ('aaa',)),
    ('Protocol', '#0f6f7d', ('protocol',)),
    ('Device', '#7b8790', ('device',)),
    ('Operational', '#5b6b2e', ()),
)
# Root Categories of the meeting workbook: (name, domain, keywords). "a+b" needs both words.
DEFAULT_CATEGORIES = (
    ('E2E', 'IMS/E2E', ('e2e',)),
    ('Poor Coverage LTE', 'RF', ('coverage+lte', 'coverage+4g')),
    ('DL Interference LTE', 'RF', ('dl interference+lte', 'dl interference+4g')),
    ('UL Interference LTE', 'RF', ('ul interference+lte', 'ul interference+4g')),
    ('Poor Coverage NR', 'RF', ('coverage+nr', 'coverage+5g')),
    ('DL Interference NR', 'RF', ('dl interference+nr', 'dl interference+5g')),
    ('UL Interference NR', 'RF', ('ul interference+nr', 'ul interference+5g')),
    ('Poor Coverage 2G/3G', 'RF', ('coverage+gsm', 'coverage+umts', 'coverage+2g', 'coverage+3g')),
    ('DL Interference 2G/3G', 'RF', ('dl interference+gsm', 'dl interference+umts', 'dl interference+2g', 'dl interference+3g')),
    ('UL Interference 2G/3G', 'RF', ('ul interference+gsm', 'ul interference+umts', 'ul interference+2g', 'ul interference+3g')),
    ('UE / Test Setup Issue', 'Device', ('test setup', 'modem')),
    ('Unclear', 'Operational', ()),
    ('Operational', 'Operational', ()),
    ('Invalidated', 'Operational', ()),
    ('Procedure Overlap', 'RAN', ('procedure overlap',)),
    ('Radio Configuration Inconsistency', 'RAN', ('configuration inconsistency',)),
    ('High PRB Utilization', 'RAN', ('prb', 'congestion')),
    ('Mobility LTE', 'RAN', ('handover+lte', 'mobility+lte', 'handover+4g')),
    ('Mobility NR', 'RAN', ('handover+nr', 'mobility+nr', 'handover+5g')),
    ('No Failure/ Drop', 'Operational', ()),
    ('IMSI Issue', 'Core 2G/4G/5G', ('imsi',)),
    ('VONR not Enabled in Source/Neighbor Site', 'IMS/E2E', ('vonr',)),
)
# Root Causes: those of the meeting workbook, then the causes of the first catalog, each in its domain.
DEFAULT_CAUSES = (
    ('NLOS due to clutter or terrain profile', 'RF', ('nlos', 'clutter', 'terrain')),
    ('LOS but weak signal', 'RF', ('weak signal',)),
    ('Large distance to the nearest site', 'RF', ('distance to',)),
    ('Road constrains', 'RF', ('road',)),
    ('Missing or late handover', 'RAN', ('late handover', 'missing handover', 'missing neighbour', 'missing neighbor')),
    ('Lack of dominant cell', 'RF', ('lack of dominant', 'pilot pollution')),
    ('Overshooting or excessive cell overlap', 'RF', ('overshoot', 'overshooting', 'cell overlap')),
    ('External UL interference', 'RF', ('external interference', 'external ul interference')),
    ('Internal UL interference', 'RF', ('internal interference', 'internal ul interference')),
    ('Antenna or site RF issue', 'RF', ('antenna', 'vswr')),
    ('Cell overload', 'RAN', ('overload',)),
    ('Incident', 'Operational', ('incident',)),
    ('Open alarms', 'Operational', ('alarm', 'alarms')),
    ('Performance ticket (KPI degradation)', 'Operational', ('kpi degradation',)),
    ('Potential E2E Issue', 'IMS/E2E', ('potential e2e',)),
    ('CRQ implementation on Site or Neighbour', 'Operational', ('crq',)),
    ('Cell/Site Outage', 'Operational', ('outage', 'site down', 'cell down')),
    ('MME/PCRF/IMS issue', 'Core 2G/4G/5G', ('mme', 'pcrf')),
    ('Tunnel Issue', 'Core 2G/4G/5G', ('tunnel',)),
    ('PCI Collision/PCI MOD 3 Collision', 'RAN', ('pci',)),
    ('Call not initiated', 'Device', ('not initiated',)),
    # The causes of the first catalog, with their keywords.
    ('DL interference', 'RF', ('dl interference', 'downlink interference')),
    ('UL interference', 'RF', ('ul interference', 'uplink interference')),
    ('Coverage', 'RF', ('coverage',)),
    ('BLER', 'RF', ('bler',)),
    ('Handover failure', 'RAN', ('handover',)),
    ('RRC layer', 'RAN', ('rrc',)),
    ('Inter-RAT transition', 'RAN', ('inter-rat',)),
    ('Low throughput', 'RAN', ('low throughput',)),
    ('Paging', 'RAN', ('paging',)),
    ('EPS bearer deactivation', 'Core 2G/4G/5G', ('bearer deactivation', 'eps mobility management')),
    ('TAU reject', 'Core 2G/4G/5G', ('tracking area update', 'tau')),
    ('NAS mobility management', 'Core 2G/4G/5G', ('nnas', 'nas')),
    ('WhatsApp session in GSM', 'Core 2G/4G/5G', ('session in gsm',)),
    ('EPS fallback failure', 'Core EPSFB', ('epsfb', 'eps fallback')),
    ('No QCI1 established', 'IMS/E2E', ('qci1', 'qci 1')),
    ('VoLTE core', 'IMS/E2E', ('volte core',)),
    ('E2E trace required', 'IMS/E2E', ('e2e',)),
    ('Authentication/Authorization', 'AAA', ('authentication', 'authorization')),
    ('Packet loss', 'Protocol', ('packet loss',)),
    ('TCP connection errors', 'Protocol', ('tcp',)),
    ('DNS', 'Protocol', ('dns',)),
    ('HTTP', 'Protocol', ('http',)),
    ('Data transfer timeout', 'Protocol', ('timeout',)),
    ('No DL packets', 'Protocol', ('no dl packets',)),
    ('Latency', 'Protocol', ('latency',)),
    ('Device or test setup', 'Device', ('device', 'modem')),
)
ROOT_KINDS = ('domain', 'category', 'cause')
ROOT_KIND_LABELS = {'domain': 'Domains', 'category': 'Root Categories', 'cause': 'Root Causes'}


def default_root_catalog() -> dict[str, list[dict[str, Any]]]:
    return {
        'domains': [{'name': name, 'color': color, 'keywords': list(keywords)} for name, color, keywords in DEFAULT_DOMAINS],
        'categories': [{'name': name, 'domain': domain, 'keywords': list(keywords)} for name, domain, keywords in DEFAULT_CATEGORIES],
        'causes': [{'name': name, 'domain': domain, 'keywords': list(keywords)} for name, domain, keywords in DEFAULT_CAUSES],
    }


def default_sections() -> list[dict[str, str]]:
    return [{'key': key, 'label': label, 'color': color} for key, label, color in SECTIONS]


def default_fields() -> list[dict[str, Any]]:
    return [{**field, 'options': [dict(option) for option in field['options']]} for field in DEFAULT_FIELDS]


def default_status_rules() -> list[dict[str, Any]]:
    return [{'status': rule['status'], 'conditions': [dict(condition, values=list(condition['values']))
                                                      for condition in rule['conditions']]} for rule in DEFAULT_STATUS_RULES]


# -- keywords -----------------------------------------------------------------------------------
def normalized_text(value: Any) -> str:
    """Lower-case text with underscores and non-breaking spaces as spaces, for keyword matching."""
    return _normalized(str(value or ''))


@lru_cache(maxsize=65536)
def _normalized(value: str) -> str:
    return re.sub(r'\s+', ' ', value.replace('_', ' ').replace('\xa0', ' ')).strip().casefold()


def keywords(values: Any) -> list[str]:
    """Clean keyword list (a string is split at commas, semicolons and new lines)."""
    if isinstance(values, str):
        values = re.split(r'[,;\n]', values)
    if not isinstance(values, (list, tuple)):
        return []
    cleaned = []
    for value in values:
        parts = [normalized_text(part) for part in str(value or '').split('+')]
        if all(parts):
            cleaned.append('+'.join(parts))
    return list(dict.fromkeys(cleaned))[:30]


@lru_cache(maxsize=4096)
def _word_pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(rf'(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])')


def _word(keyword: str, text: str, match: str) -> bool:
    # Most keywords are not in the text at all: only those that are need the whole-word check.
    if keyword not in text:
        return False
    return match == 'text' or _word_pattern(keyword).search(text) is not None


def keyword_found(values: list[str], text: str, match: str = 'words') -> bool:
    """Whether one keyword appears in the text: as whole words ("rf" in "RF Problems", not in "performance"),
    or anywhere with partial matching. A keyword "a+b" needs every part."""
    if not text:
        return False
    return any(all(_word(part, text, match) for part in keyword.split('+')) for keyword in values)


# -- validation ------------------------------------------------------------------------------
def normalize_sections(items: Any) -> list[dict[str, str]]:
    """The six sections with their names and colours (unknown keys are ignored, missing ones keep their defaults)."""
    given = {str(item.get('key')): item for item in items or [] if isinstance(item, dict)}
    sections = []
    for key, label, color in SECTIONS:
        item = given.get(key) or {}
        name = _clean(item.get('label'), 40) or label
        chosen = str(item.get('color') or '').strip()
        sections.append({'key': key, 'label': name, 'color': chosen if COLOR_PATTERN.fullmatch(chosen) else color})
    return sections


def normalize_options(items: Any, label: str, *, with_keywords: bool = False) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    names: set[str] = set()
    for option in items or []:
        if isinstance(option, str):
            option = {'name': option}
        if not isinstance(option, dict):
            raise ValueError(f'The values of "{label}" are invalid.')
        name = _clean(option.get('name'))
        if not name or name.casefold() in names:
            continue
        names.add(name.casefold())
        color = str(option.get('color') or '').strip()
        entry = {'name': name, 'color': color if COLOR_PATTERN.fullmatch(color) else '',
                 'previous': _clean(option.get('previous'))}
        if with_keywords:
            entry['keywords'] = keywords(option.get('keywords'))
        options.append(entry)
    return options


def normalize_fields(items: Any, existing: dict[str, dict[str, Any]], call_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """A valid field catalog: unique names and keys, known sections, types and sources.

    The fields bound to the follow-up keep their source and type; new fields get a key from their name.
    """
    if not isinstance(items, list):
        raise ValueError('The field list is invalid.')
    if len(items) > MAX_FIELDS:
        raise ValueError(f'Keep at most {MAX_FIELDS} fields.')
    normalized: list[dict[str, Any]] = []
    labels: set[str] = set()
    taken = set(existing)
    tracking_refs: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('The field list is invalid.')
        label = _clean(item.get('label'), 60)
        if not label:
            raise ValueError('Every field needs a name.')
        if label.casefold() in labels:
            raise ValueError(f'The field "{label}" is repeated.')
        labels.add(label.casefold())
        key = str(item.get('key') or '')
        if key in taken and key not in existing:
            key = ''
        if key not in existing and not re.fullmatch(r'[a-z0-9_]{1,40}', key):
            key = field_key(label, taken)
        taken.add(key)
        previous = existing.get(key) or {}
        source = str(item.get('source') or previous.get('source') or 'user')
        if source not in FIELD_SOURCES:
            raise ValueError(f'Choose where "{label}" takes its value from.')
        ref = str(item.get('source_ref') or previous.get('source_ref') or '').strip()[:200]
        field_type = str(item.get('type') or previous.get('type') or 'text')
        if field_type not in FIELD_TYPES:
            raise ValueError(f'Choose a type for "{label}".')
        if source == 'tracking':
            if ref not in TRACKING_REFS:
                raise ValueError(f'"{label}" shows an unknown follow-up value.')
            if ref in tracking_refs:
                raise ValueError(f'Two fields show the {TRACKING_REFS[ref]}.')
            tracking_refs.add(ref)
        elif source == 'rca' and not ref:
            raise ValueError(f'Choose the RCA script column of "{label}".')
        elif source == 'cdr':
            if not ref:
                raise ValueError(f'Choose the CDR value of "{label}".')
            if ref not in call_fields and not ref.startswith('column:'):
                ref = f'column:{ref}'
        elif source == 'derived':
            if not ref:
                raise ValueError(f'Choose the call values "{label}" is derived from.')
            field_type = 'list'
        options: list[dict[str, Any]] = []
        if field_type == 'list' and source in {'user', 'derived'}:
            options = normalize_options(item.get('options'), label, with_keywords=source == 'derived')
            if not options:
                raise ValueError(f'Add at least one value to the list "{label}".')
        section = str(item.get('section') or previous.get('section') or 'analysis')
        if section not in SECTION_KEYS:
            raise ValueError(f'Choose a section for "{label}".')
        editable = source == 'user'
        normalized.append({
            'key': key, 'label': label, 'section': section, 'type': field_type, 'source': source, 'source_ref': ref,
            'options': options, 'in_table': bool(item.get('in_table')), 'in_export': bool(item.get('in_export', True)),
            'in_summary': bool(item.get('in_summary')) and field_type in {'list', 'yes_no'},
            'required_to_close': bool(item.get('required_to_close')) and editable,
            'suggest_from': str(item.get('suggest_from') or '') if editable and str(item.get('suggest_from') or '') in call_fields else '',
            'description': str(item.get('description') or '').strip()[:300],
        })
    return normalized


def normalize_root_catalog(catalog: Any) -> dict[str, list[dict[str, Any]]]:
    """Valid domains (unique, coloured) and categories and causes (unique, each in a known domain or none)."""
    if not isinstance(catalog, dict):
        raise ValueError('The root cause catalog is invalid.')
    result: dict[str, list[dict[str, Any]]] = {'domains': [], 'categories': [], 'causes': []}
    seen: set[str] = set()
    for item in catalog.get('domains') or []:
        if not isinstance(item, dict):
            raise ValueError('The root cause catalog is invalid.')
        name = _clean(item.get('name'), 60)
        if not name:
            raise ValueError('Every domain needs a name.')
        if name.casefold() in seen:
            raise ValueError(f'The domain "{name}" is repeated.')
        seen.add(name.casefold())
        color = str(item.get('color') or '').strip()
        result['domains'].append({'name': name, 'color': color if COLOR_PATTERN.fullmatch(color) else '#7b8790',
                                  'keywords': keywords(item.get('keywords')), 'previous': _clean(item.get('previous'), 60)})
    domains = {domain['name'].casefold(): domain['name'] for domain in result['domains']}
    renamed = {domain['previous'].casefold(): domain['name'] for domain in result['domains'] if domain['previous']}
    for kind, plural, title in (('category', 'categories', 'Root Category'), ('cause', 'causes', 'Root Cause')):
        names: set[str] = set()
        for item in catalog.get(plural) or []:
            if not isinstance(item, dict):
                raise ValueError('The root cause catalog is invalid.')
            name = _clean(item.get('name'))
            if not name:
                raise ValueError(f'Every {title} needs a name.')
            if name.casefold() in names:
                raise ValueError(f'The {title} "{name}" is repeated.')
            names.add(name.casefold())
            domain = _clean(item.get('domain'), 60)
            domain = domains.get(domain.casefold()) or renamed.get(domain.casefold()) or ''
            result[plural].append({'name': name, 'domain': domain, 'keywords': keywords(item.get('keywords')),
                                   'previous': _clean(item.get('previous'))})
    return result


def normalize_status_rules(rules: Any, statuses: list[str], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rules naming known statuses and conditions on list and Yes / No fields, the team, the assignee or "attended"."""
    if not isinstance(rules, list):
        raise ValueError('The status rules are invalid.')
    names = {name.casefold(): name for name in statuses}
    known = condition_fields(fields)
    normalized = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError('The status rules are invalid.')
        status = names.get(_clean(rule.get('status'), 60).casefold())
        if not status:
            raise ValueError(f'"{rule.get("status")}" is not one of the statuses.')
        conditions = []
        for condition in rule.get('conditions') or []:
            if not isinstance(condition, dict):
                raise ValueError('The status rules are invalid.')
            field = str(condition.get('field') or '')
            if field not in known:
                raise ValueError(f'The status rule of {status} reads an unknown field.')
            op = str(condition.get('op') or 'in')
            if op not in RULE_OPERATORS:
                raise ValueError(f'The status rule of {status} has an unknown condition.')
            values = [_clean(value) for value in condition.get('values') or [] if _clean(value)]
            if op in {'in', 'not_in'} and not values:
                raise ValueError(f'Choose the values of every condition of the {status} rule.')
            conditions.append({'field': field, 'op': op, 'values': list(dict.fromkeys(values)) if op in {'in', 'not_in'} else []})
        if not conditions:
            raise ValueError(f'Give the {status} rule at least one condition.')
        normalized.append({'status': status, 'conditions': conditions})
    return normalized


def condition_fields(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The fields a status rule can read, with the values it can choose."""
    known: dict[str, dict[str, Any]] = {ATTENDED_FIELD: {'label': 'Attended (followed up or commented)', 'values': list(YES_NO)}}
    for field in fields:
        if field['source'] == 'tracking' and field['source_ref'] in {'team', 'assignee', 'root_category', 'root_cause'}:
            known[f"@{field['source_ref']}"] = {'label': field['label'], 'values': []}
        elif field['source'] in {'user', 'derived'} and field['type'] in {'list', 'yes_no'}:
            values = [option['name'] for option in field['options']] if field['type'] == 'list' else list(YES_NO)
            known[field['key']] = {'label': field['label'], 'values': values}
    return known


def rules_after_field_changes(rules: list[dict[str, Any]], before: list[dict[str, Any]],
                              after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rules with renamed list values renamed, removed values and fields dropped, and empty rules removed."""
    del before
    new = {field['key']: field for field in after}
    kept: list[dict[str, Any]] = []
    for rule in rules:
        conditions = []
        for condition in rule['conditions']:
            field = condition['field']
            if field.startswith('@'):
                conditions.append(condition)
                continue
            target = new.get(field)
            if target is None or target['type'] not in {'list', 'yes_no'}:
                continue
            if target['type'] == 'list':
                renamed = {option.get('previous', '').casefold(): option['name'] for option in target['options'] if option.get('previous')}
                names = {option['name'].casefold(): option['name'] for option in target['options']}
                values = []
                for value in condition['values']:
                    value = renamed.get(value.casefold(), value) if value.casefold() not in names else names[value.casefold()]
                    if value.casefold() in names:
                        values.append(names[value.casefold()])
                if condition['op'] in {'in', 'not_in'} and not values:
                    continue
                condition = {**condition, 'values': list(dict.fromkeys(values))}
            conditions.append(condition)
        if conditions:
            kept.append({**rule, 'conditions': conditions})
    return kept


def rules_after_status_changes(rules: list[dict[str, Any]], renamed: dict[str, str], statuses: list[str]) -> list[dict[str, Any]]:
    names = {name.casefold() for name in statuses}
    result = []
    for rule in rules:
        status = renamed.get(rule['status'].casefold(), rule['status'])
        if status.casefold() in names:
            result.append({**rule, 'status': status})
    return result


def evaluate_status(rules: list[dict[str, Any]], values: dict[str, str], fallback: str) -> str:
    """The status of the first rule whose conditions all hold for ``values`` (field key → value), else ``fallback``."""
    for rule in rules:
        if all(_condition_holds(condition, values) for condition in rule['conditions']):
            return rule['status']
    return fallback


def _condition_holds(condition: dict[str, Any], values: dict[str, str]) -> bool:
    value = str(values.get(condition['field']) or '').strip()
    wanted = {item.casefold() for item in condition['values']}
    if condition['op'] == 'empty':
        return not value
    if condition['op'] == 'not_empty':
        return bool(value)
    if condition['op'] == 'not_in':
        return value.casefold() not in wanted
    return value.casefold() in wanted


# -- Excel catalog --------------------------------------------------------------------------
CATALOG_FORMAT = 'NQ Analysis Center catalog'
_YES = {'yes', 'y', 'true', '1', 'x', 'si', 'sí'}


def _flag(value: Any) -> bool:
    return str(value if value is not None else '').strip().casefold() in _YES


def catalog_workbook(sections: list[dict[str, str]], fields: list[dict[str, Any]], statuses: list[dict[str, Any]],
                     teams: list[dict[str, Any]], root: dict[str, list[dict[str, Any]]], rules: list[dict[str, Any]]) -> bytes:
    """The catalog as an Excel workbook: About, Sections, Fields, Lists, Root Catalog and Status Rules sheets.

    Every sheet is a plain table, so the catalog can be edited in Excel and imported again.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    header_font = Font(bold=True, color='FFFFFF')
    by_section = {section['key']: section for section in sections}

    def sheet(title: str, headers: list[str], rows: list[list[Any]], widths: list[int], fill: str = '7D1238',
              colors: list[str] | None = None):
        target = workbook.create_sheet(title)
        target.append(headers)
        for cell in target[1]:
            cell.font, cell.fill = header_font, PatternFill('solid', fgColor=fill)
        for index, row in enumerate(rows):
            target.append(row)
            if colors and colors[index]:
                target.cell(index + 2, 1).fill = PatternFill('solid', fgColor=colors[index].lstrip('#'))
                target.cell(index + 2, 1).font = Font(bold=True, color=contrast_color(colors[index]))
        target.freeze_panes = 'A2'
        for index, width in enumerate(widths, start=1):
            target.column_dimensions[get_column_letter(index)].width = width
        for row in target.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        return target

    about = workbook.active
    about.title = 'About'
    for line in (
        [CATALOG_FORMAT],
        ['Edit the sheets and import the workbook again in Non-Qualified Calls → Analysis Center → Fields & Sections → Import Catalog.'],
        ['Sections: the name and colour of the six sections (their keys are fixed).'],
        ['Fields: one row per field, in the order of the table and of the Excel export. Source is user, tracking, cdr, rca or derived.'],
        ['Lists: the values of every list field (List = field key), with their colour and, for derived lists, their keywords.'],
        ['Root Catalog: Domains, Root Categories and Root Causes; categories and causes name their domain. Keywords suggest them.'],
        ['Statuses and Teams: the NQ Call Status values (Closed = Yes ends the follow-up) and the responsible teams.'],
        ['Status Rules: the first rule whose conditions all hold sets the status; Field "@attended" is Yes once the call is followed up.'],
    ):
        about.append(line)
    about['A1'].font = Font(bold=True, size=14, color='7D1238')
    about.column_dimensions['A'].width = 120
    sheet('Sections', ['Key', 'Section', 'Colour'], [[section['key'], section['label'], section['color']] for section in sections],
          [18, 26, 12], colors=[section['color'] for section in sections])
    sheet('Fields', ['Order', 'Section', 'Field', 'Key', 'Type', 'Source', 'Source Reference', 'In Table', 'In Excel', 'In Summary',
                     'Required to Close', 'Suggest From', 'Description'],
          [[index + 1, by_section.get(field['section'], {}).get('label', field['section']), field['label'], field['key'],
            field['type'], field['source'], field['source_ref'], 'Yes' if field['in_table'] else 'No',
            'Yes' if field.get('in_export', True) else 'No', 'Yes' if field['in_summary'] else 'No',
            'Yes' if field['required_to_close'] else 'No', field.get('suggest_from', ''), field.get('description', '')]
           for index, field in enumerate(fields)],
          [7, 16, 34, 30, 11, 10, 26, 9, 9, 11, 10, 14, 60],
          colors=[by_section.get(field['section'], {}).get('color', '') for field in fields])
    list_rows = [[field['key'], option['name'], option.get('color', ''), ', '.join(option.get('keywords') or [])]
                 for field in fields if field['type'] == 'list' and field['source'] in {'user', 'derived'}
                 for option in field['options']]
    sheet('Lists', ['List', 'Value', 'Colour', 'Keywords'], list_rows, [30, 40, 12, 60])
    root_rows = [['Domain', item['name'], '', item.get('color', ''), ', '.join(item.get('keywords') or [])] for item in root['domains']]
    root_rows += [['Root Category', item['name'], item.get('domain', ''), '', ', '.join(item.get('keywords') or [])]
                  for item in root['categories']]
    root_rows += [['Root Cause', item['name'], item.get('domain', ''), '', ', '.join(item.get('keywords') or [])] for item in root['causes']]
    sheet('Root Catalog', ['Kind', 'Name', 'Domain', 'Colour', 'Keywords'], root_rows, [16, 44, 18, 12, 60])
    option_rows = [['Status', item['name'], item['color'], 'Yes' if item.get('closed') else 'No', ''] for item in statuses]
    option_rows += [['Team', item['name'], item['color'], '', ', '.join(item.get('members') or [])] for item in teams]
    sheet('Statuses and Teams', ['Kind', 'Name', 'Colour', 'Closed', 'Members'], option_rows, [10, 34, 12, 9, 50])
    rule_rows = [[index + 1, rule['status'], condition['field'], condition['op'], ', '.join(condition['values'])]
                 for index, rule in enumerate(rules) for condition in rule['conditions']]
    sheet('Status Rules', ['Rule', 'Status', 'Field', 'Condition', 'Values'], rule_rows, [7, 24, 28, 12, 60])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def contrast_color(hex_color: str) -> str:
    match = COLOR_PATTERN.fullmatch(hex_color or '')
    if not match:
        return 'FFFFFF'
    value = int(hex_color[1:], 16)
    red, green, blue = (value >> 16) & 255, (value >> 8) & 255, value & 255
    return '2A1A20' if (0.299 * red + 0.587 * green + 0.114 * blue) > 160 else 'FFFFFF'


def _rows(sheet) -> list[dict[str, Any]]:
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [normalized_text(value) for value in rows[0]]
    return [{header: value for header, value in zip(headers, row) if header} for row in rows[1:]
            if any(value not in (None, '') for value in row)]


def _split(value: Any) -> list[str]:
    return [part.strip() for part in re.split(r'[,;\n]', str(value or '')) if part.strip()]


def read_catalog_workbook(content: bytes) -> dict[str, Any]:
    """The catalog of a workbook: the format written by ``catalog_workbook`` or the meeting layout
    (sections in the first row, field names in the second and value lists below)."""
    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    names = {sheet.title.casefold(): sheet for sheet in workbook.worksheets}
    if 'fields' not in names:
        return _read_meeting_layout(workbook.worksheets[0])
    catalog: dict[str, Any] = {'format': 'catalog'}
    if 'sections' in names:
        catalog['sections'] = [{'key': str(row.get('key') or '').strip(), 'label': row.get('section'), 'color': row.get('colour') or row.get('color')}
                               for row in _rows(names['sections'])]
    section_keys = {normalized_text(section['label']): section['key'] for section in catalog.get('sections') or default_sections()}
    section_keys.update({key: key for key in SECTION_KEYS})
    section_keys.update({normalized_text(label): key for key, label, _color in SECTIONS})
    lists: dict[str, list[dict[str, Any]]] = {}
    if 'lists' in names:
        for row in _rows(names['lists']):
            lists.setdefault(str(row.get('list') or '').strip(), []).append(
                {'name': row.get('value'), 'color': row.get('colour') or row.get('color') or '', 'keywords': _split(row.get('keywords'))})
    fields = []
    for row in sorted(_rows(names['fields']), key=lambda row: float(row.get('order') or 0) if str(row.get('order') or '').replace('.', '', 1).isdigit() else 0):
        label = str(row.get('field') or '').strip()
        if not label:
            continue
        key = str(row.get('key') or '').strip()
        fields.append({
            'key': key, 'label': label, 'section': section_keys.get(normalized_text(row.get('section')), 'analysis'),
            'type': str(row.get('type') or 'text').strip(), 'source': str(row.get('source') or 'user').strip(),
            'source_ref': str(row.get('source reference') or '').strip(), 'options': lists.get(key) or lists.get(label) or [],
            'in_table': _flag(row.get('in table')), 'in_export': _flag(row.get('in excel')) if row.get('in excel') is not None else True,
            'in_summary': _flag(row.get('in summary')), 'required_to_close': _flag(row.get('required to close')),
            'suggest_from': str(row.get('suggest from') or '').strip(), 'description': str(row.get('description') or '').strip(),
        })
    catalog['fields'] = fields
    if 'root catalog' in names:
        root: dict[str, list[dict[str, Any]]] = {'domains': [], 'categories': [], 'causes': []}
        plural = {'domain': 'domains', 'root category': 'categories', 'category': 'categories', 'root cause': 'causes', 'cause': 'causes'}
        for row in _rows(names['root catalog']):
            target = plural.get(normalized_text(row.get('kind')))
            if not target:
                continue
            item = {'name': row.get('name'), 'keywords': _split(row.get('keywords'))}
            if target == 'domains':
                item['color'] = row.get('colour') or row.get('color') or ''
            else:
                item['domain'] = row.get('domain') or ''
            root[target].append(item)
        catalog['root'] = root
    if 'statuses and teams' in names:
        statuses, teams = [], []
        for row in _rows(names['statuses and teams']):
            kind = normalized_text(row.get('kind'))
            if kind == 'status':
                statuses.append({'name': row.get('name'), 'color': row.get('colour') or '', 'closed': _flag(row.get('closed'))})
            elif kind == 'team':
                teams.append({'name': row.get('name'), 'color': row.get('colour') or '', 'members': _split(row.get('members'))})
        catalog['statuses'], catalog['teams'] = statuses, teams
    if 'status rules' in names:
        rules: dict[int, dict[str, Any]] = {}
        for row in _rows(names['status rules']):
            number = int(float(row.get('rule') or 0)) if str(row.get('rule') or '').replace('.', '', 1).isdigit() else len(rules) + 1
            rule = rules.setdefault(number, {'status': str(row.get('status') or '').strip(), 'conditions': []})
            rule['conditions'].append({'field': str(row.get('field') or '').strip(), 'op': str(row.get('condition') or 'in').strip(),
                                       'values': _split(row.get('values'))})
        catalog['rules'] = [rules[number] for number in sorted(rules)]
    return catalog


# The meeting layout: section titles in the first row, field names in the second, then a status
# row, the value kind, notes and the example values below.
_SECTION_TITLES = {'rca': 'rca', 'general': 'general', 'failure event': 'failure_event', 'analysis': 'analysis',
                   'implementation': 'implementation', 'planning': 'planning'}


def _read_meeting_layout(sheet) -> dict[str, Any]:
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    if len(rows) < 2:
        raise ValueError('The workbook has no fields.')
    defaults = {normalized_text(field['label']): field for field in DEFAULT_FIELDS}
    defaults.update({normalized_text(field['key']): field for field in DEFAULT_FIELDS})
    fields = []
    section = 'general'
    labels: set[str] = set()
    for index, title in enumerate(rows[1]):
        heading = normalized_text(rows[0][index] if index < len(rows[0]) else '')
        for word, key in _SECTION_TITLES.items():
            if heading.startswith(word):
                section = key
        label = re.sub(r'\s+', ' ', str(title or '')).strip()[:60]
        if not label or label.casefold() in labels:
            continue
        labels.add(label.casefold())
        known = defaults.get(normalized_text(label))
        values = []
        for row in rows[5:]:
            text = re.sub(r'\s+', ' ', str(row[index] if index < len(row) and row[index] is not None else '')).strip()
            if text and text.casefold() not in {value.casefold() for value in values}:
                values.append(text)
        if known is not None:
            field = {**known, 'section': section, 'options': [dict(option) for option in known['options']]}
            if field['source'] == 'user' and field['type'] == 'list':
                names = {option['name'].casefold() for option in field['options']}
                field['options'] += [{'name': value, 'color': '', 'keywords': []} for value in values
                                     if value.casefold() not in names and value.casefold() != 'user define']
            fields.append(field)
            continue
        kind = normalized_text(rows[3][index] if len(rows) > 3 and index < len(rows[3]) else '')
        lowered = [value.casefold() for value in values]
        if 'boole' in kind or (lowered and set(lowered) <= {'yes', 'no'}):
            field_type, options = 'yes_no', []
        elif 'fecha' in kind or 'date' in kind:
            field_type, options = 'date', []
        elif 'decimal' in kind or 'number' in kind:
            field_type, options = 'number', []
        elif 'lista' in kind or 'list' in kind:
            field_type, options = 'list', [{'name': value, 'color': '', 'keywords': []} for value in values if value.casefold() != 'user define']
        else:
            field_type, options = ('long_text' if 'ilimitado' in kind or 'unlimited' in kind else 'text'), []
        if field_type == 'list' and not options:
            field_type = 'text'
        fields.append(_field('', label, section, field_type, options=tuple(options)))
    return {'format': 'meeting', 'fields': fields}
