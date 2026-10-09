"""Scoring report configurations: scenarios with their filters, aggregation and content options.

A report has one or more scenarios (for example National, London, Main Cities and
per Vendor). Each scenario uses the job's CDRs, NR Mode, methodology and GAP reference
with its own filters and aggregation levels, and chooses the slides of each scoring.
A scenario of the whole country (no Region, Cluster or City filters) can also include the
National & area summary: the National scoring next to the scoring of chosen cities and of
each Region, Cluster or City, with its own time split (all CDRs, per campaign or per period).
Saved configurations and the last one used are kept in the workspace and travel with
the Scoring & GAP Analysis Configuration.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

REPORT_CONFIGURATIONS_STATE_KEY = 'scoring_report_configurations'
REPORT_CONFIGURATIONS_FORMAT = 'drivetest-analyzer-scoring-report-configurations'
REPORT_CONFIGURATIONS_VERSION = 1
SCORING_KINDS = ('best_network', 'most_reliable')
REPORT_LEVELS = ('Operator', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign')
REPORT_FILTER_FIELDS = ('Operator', 'Operator_Vendor', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign')
# Filters that leave out part of the country: with any of them there is no National scoring.
GEOGRAPHIC_FILTER_FIELDS = ('Region', 'Cluster', 'City')
AREA_SUMMARY_BREAKDOWNS = ('None', 'Region', 'Cluster', 'City')
DEFAULT_AREA_SUMMARY = {'enabled': True, 'time_split': 'Campaign', 'breakdown': 'Region', 'cities': ['London'],
                        'main_cities': False}
# The time split of the area summary: every selected CDR in one value, per campaign or per period of the tests' start time.
AREA_SUMMARY_TIME_SPLITS = ('All', 'Campaign', 'Daily', 'Weekly', 'Monthly', 'Quarterly', 'Yearly')
MAX_SCENARIOS = 20
MAX_SAVED_CONFIGURATIONS = 50
_OPTION_DEFAULTS = {
    'enabled': True,
    # 'all' shows only All Environments; 'split' adds a block per environment.
    'environments': 'all',
    'charts': {'service': True, 'category': True, 'breakdown': True, 'location_cards': True, 'trend': True},
    'tables': {'summary': True, 'breakdown': True, 'kpi_values': False, 'gap_values': False,
               'campaign_comparison': True},
    # An empty operator list compares every operator with the reference.
    'gap': {'operators': [], 'all_operators': True, 'individual': True, 'profile': True, 'points_loss_map': True},
}
_DEFAULT_COMPARED_OPERATORS = re.compile(r'^(vf|vodafone|3|three|h3g)(?![a-z0-9])', re.IGNORECASE)


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    return list(dict.fromkeys(str(value).strip()[:160] for value in values if str(value).strip()))


def default_compared_operators(operators: list[str]) -> list[str]:
    """Vodafone and Three by default; every operator when neither is available."""
    return [operator for operator in operators if _DEFAULT_COMPARED_OPERATORS.match(str(operator).strip())]


def default_scoring_options(*, operators: list[str] | None = None) -> dict[str, Any]:
    options = copy.deepcopy(_OPTION_DEFAULTS)
    options['gap']['operators'] = default_compared_operators(operators or [])
    return options


def _normalize_options(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    options = copy.deepcopy(_OPTION_DEFAULTS)
    options['enabled'] = bool(raw.get('enabled', True))
    options['environments'] = 'split' if raw.get('environments') == 'split' else 'all'
    for group in ('charts', 'tables', 'gap'):
        supplied = raw.get(group) if isinstance(raw.get(group), dict) else {}
        for key, default in _OPTION_DEFAULTS[group].items():
            if key == 'operators':
                options[group][key] = _strings(supplied.get(key))
            elif key in supplied:
                options[group][key] = bool(supplied[key])
            else:
                options[group][key] = default
    return options


def _normalize_area_summary(raw: Any, whole_country: bool) -> dict[str, Any]:
    """Whether the scenario has the National & area summary and its rows besides National:
    the chosen cities, then each Region, Cluster or City. By default only scenarios of the whole country have it.
    """
    if not isinstance(raw, dict):
        return {**copy.deepcopy(DEFAULT_AREA_SUMMARY), 'enabled': whole_country}
    breakdown = str(raw.get('breakdown') or '').strip().casefold()
    time_split = str(raw.get('time_split') or '').strip().casefold()
    return {
        'enabled': bool(raw['enabled']) if 'enabled' in raw else whole_country,
        'time_split': next((name for name in AREA_SUMMARY_TIME_SPLITS if name.casefold() == time_split), 'Campaign'),
        'breakdown': next((name for name in AREA_SUMMARY_BREAKDOWNS if name.casefold() == breakdown), 'None'),
        'cities': _strings(raw.get('cities')),
        'main_cities': bool(raw.get('main_cities')),
    }


def has_geographic_filters(scenario: dict[str, Any]) -> bool:
    """Whether the scenario leaves out part of the country: Region, Cluster, City or Main Cities filters."""
    filters = scenario.get('context_filters') or {}
    return bool(scenario.get('main_cities')) or any(filters.get(field) for field in GEOGRAPHIC_FILTER_FIELDS)


def default_scenario(*, name: str = 'National', context_filters: dict[str, Any] | None = None,
                     aggregation_levels: list[str] | None = None, main_cities: bool = False,
                     operators: list[str] | None = None) -> dict[str, Any]:
    # Campaign is always included: a scenario with a single campaign leaves the level out.
    return normalize_scenario({
        'name': name, 'context_filters': context_filters or {},
        'aggregation_levels': [*(aggregation_levels or ['Operator']), 'Campaign'],
        'main_cities': main_cities,
        'scorings': {kind: default_scoring_options(operators=operators) for kind in SCORING_KINDS},
    })


def normalize_scenario(raw: Any, index: int = 0) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    name = str(raw.get('name') or '').strip()[:80] or f'Scenario {index + 1}'
    filters = raw.get('context_filters') if isinstance(raw.get('context_filters'), dict) else {}
    levels = [level for level in _strings(raw.get('aggregation_levels')) if level in REPORT_LEVELS]
    scorings = raw.get('scorings') if isinstance(raw.get('scorings'), dict) else {}
    scenario = {
        'name': name,
        'context_filters': {field: _strings(filters.get(field)) for field in REPORT_FILTER_FIELDS
                            if _strings(filters.get(field))},
        'main_cities': bool(raw.get('main_cities')),
        'aggregation_levels': ['Operator', *[level for level in REPORT_LEVELS if level in levels and level != 'Operator']],
        'scorings': {kind: _normalize_options(scorings.get(kind)) for kind in SCORING_KINDS},
    }
    scenario['area_summary'] = _normalize_area_summary(raw.get('area_summary'), not has_geographic_filters(scenario))
    return scenario


def normalize_report_configuration(raw: Any) -> dict[str, Any]:
    """A report configuration: one to twenty scenarios, in order."""
    raw = raw if isinstance(raw, dict) else {}
    scenarios = raw.get('scenarios') if isinstance(raw.get('scenarios'), list) else []
    if not scenarios:
        raise ValueError('A scoring report needs at least one scenario.')
    if len(scenarios) > MAX_SCENARIOS:
        raise ValueError(f'A scoring report can contain up to {MAX_SCENARIOS} scenarios.')
    normalized = [normalize_scenario(item, index) for index, item in enumerate(scenarios)]
    if not any(any(options['enabled'] for options in scenario['scorings'].values()) for scenario in normalized):
        raise ValueError('Include the Best Network or the Most Reliable Network scoring in at least one scenario.')
    configuration: dict[str, Any] = {'scenarios': normalized}
    # The saved configuration (or Default) it was chosen from, shown again in the editor's selector.
    name = str(raw.get('name') or '').strip()[:80]
    if name:
        configuration['name'] = name
    return configuration


def default_report_configuration(*, context_filters: dict[str, Any] | None = None,
                                 aggregation_levels: list[str] | None = None, main_cities: bool = False,
                                 operators: list[str] | None = None) -> dict[str, Any]:
    """One scenario with the calculation's filters and aggregation and the default content."""
    return {'scenarios': [default_scenario(context_filters=context_filters, aggregation_levels=aggregation_levels,
                                           main_cities=main_cities, operators=operators)]}


def _empty_state() -> dict[str, Any]:
    return {'configurations': [], 'last': None}


def _normalize_state(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    configurations = []
    seen: set[str] = set()
    for item in raw.get('configurations') or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()[:80]
        if not name or name.casefold() in seen:
            continue
        try:
            configuration = normalize_report_configuration(item.get('configuration'))
        except ValueError:
            continue
        seen.add(name.casefold())
        configurations.append({'name': name, 'configuration': configuration,
                               'updated_at': str(item.get('updated_at') or '')[:40]})
    last = None
    if raw.get('last') is not None:
        try:
            last = normalize_report_configuration(raw.get('last'))
        except ValueError:
            last = None
    return {'configurations': configurations[:MAX_SAVED_CONFIGURATIONS], 'last': last}


def load_report_state(repository) -> dict[str, Any]:
    raw = repository.get_workspace_state(REPORT_CONFIGURATIONS_STATE_KEY)
    if not raw:
        return _empty_state()
    try:
        return _normalize_state(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _empty_state()


def _store(repository, state: dict[str, Any]) -> dict[str, Any]:
    state = _normalize_state(state)
    repository.set_workspace_state(REPORT_CONFIGURATIONS_STATE_KEY,
                                   json.dumps(state, ensure_ascii=False, separators=(',', ':')))
    return state


def remember_last_configuration(repository, configuration: dict[str, Any]) -> None:
    state = load_report_state(repository)
    state['last'] = normalize_report_configuration(configuration)
    _store(repository, state)


def save_named_configuration(repository, name: str, configuration: dict[str, Any], updated_at: str = '') -> dict[str, Any]:
    name = str(name or '').strip()[:80]
    if not name:
        raise ValueError('Enter a name for the report configuration.')
    state = load_report_state(repository)
    configurations = [item for item in state['configurations'] if item['name'].casefold() != name.casefold()]
    if len(configurations) >= MAX_SAVED_CONFIGURATIONS:
        raise ValueError(f'A workspace can keep up to {MAX_SAVED_CONFIGURATIONS} report configurations.')
    configurations.append({'name': name, 'configuration': normalize_report_configuration(configuration),
                           'updated_at': updated_at})
    state['configurations'] = sorted(configurations, key=lambda item: item['name'].casefold())
    return _store(repository, state)


def delete_named_configuration(repository, name: str) -> dict[str, Any]:
    state = load_report_state(repository)
    state['configurations'] = [item for item in state['configurations']
                               if item['name'].casefold() != str(name or '').strip().casefold()]
    return _store(repository, state)


def report_configurations_document(state: dict[str, Any]) -> dict[str, Any]:
    """Portable document of the saved report configurations (and the last one used)."""
    state = _normalize_state(state)
    return {'format': REPORT_CONFIGURATIONS_FORMAT, 'version': REPORT_CONFIGURATIONS_VERSION, **state}


def unwrap_report_configurations_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get('format') != REPORT_CONFIGURATIONS_FORMAT:
        raise ValueError('This file is not a Scoring report configurations document.')
    if document.get('version') != REPORT_CONFIGURATIONS_VERSION:
        raise ValueError('Unsupported Scoring report configurations version.')
    return _normalize_state(document)


def import_report_configurations(repository, document: Any, *, replace: bool = False) -> dict[str, Any]:
    """Add the configurations of a document, replacing those with the same name (or all of them)."""
    incoming = unwrap_report_configurations_document(document)
    state = load_report_state(repository)
    if replace:
        state = {'configurations': incoming['configurations'], 'last': incoming['last'] or state['last']}
    else:
        names = {item['name'].casefold() for item in incoming['configurations']}
        state['configurations'] = [item for item in state['configurations'] if item['name'].casefold() not in names]
        state['configurations'].extend(incoming['configurations'])
    return _store(repository, state)
