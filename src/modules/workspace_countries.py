"""The country of a workspace and the Operator Maps it starts with.

``assets/labels-operators/operators-by-country.json`` lists, for the 50 main countries (ISO 3166
alpha-3 codes), their mobile operators: the label of each one, its corporate colour and the ways the
CDRs write it (also with the country, such as ``o2 - de``). A workspace created for a country starts
with those Operator Maps; one created without a country starts without Operator Maps.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.config import PROJECT_ROOT

COUNTRY_STATE_KEY = 'workspace_country'
OPERATORS_FILE = PROJECT_ROOT / 'assets' / 'labels-operators' / 'operators-by-country.json'


@lru_cache(maxsize=1)
def countries() -> dict[str, dict[str, Any]]:
    """The countries with their operators, by ISO 3166 alpha-3 code, in alphabetical order of their names."""
    try:
        document = json.loads(OPERATORS_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return dict(sorted(((str(code).upper(), item) for code, item in document.items() if isinstance(item, dict)),
                       key=lambda entry: str(entry[1].get('name') or entry[0])))


def country_options() -> list[dict[str, str]]:
    return [{'value': code, 'label': str(item.get('name') or code)} for code, item in countries().items()]


def normalize_country(value: object) -> str:
    """The country code chosen for a workspace, or '' for none."""
    code = str(value or '').strip().upper()
    if not code:
        return ''
    if code not in countries():
        raise ValueError('Choose one of the listed countries, or none.')
    return code


def workspace_country(repository: Any) -> str:
    code = str(repository.get_workspace_state(COUNTRY_STATE_KEY) or '').strip().upper()
    return code if code in countries() else ''


def add_country_operators(repository: Any, code: str) -> int:
    """Add the operators of a country that the workspace's Operator Maps do not have yet."""
    item = countries().get(code)
    if not item:
        return 0
    groups = repository.list_operator_mapping_groups()
    labels = {str(group['canonical']).casefold() for group in groups}
    mapped = labels | {str(alias).casefold() for group in groups for alias in group['aliases']}
    added = 0
    for operator in item.get('operators') or []:
        label = str(operator.get('canonical') or '').strip()
        if not label or label.casefold() in mapped:
            continue
        aliases = [alias for alias in operator.get('aliases') or [] if str(alias).casefold() not in mapped]
        try:
            repository.replace_operator_mapping_group(None, label, aliases, operator.get('color'))
        except ValueError:
            # A spelling the workspace already gives to another label keeps it.
            continue
        mapped |= {label.casefold(), *(str(alias).casefold() for alias in aliases)}
        added += 1
    return added


def set_workspace_country(repository: Any, value: object) -> tuple[str, int]:
    """Save the country of a workspace and add its operators; returns the code and the operators added."""
    code = normalize_country(value)
    repository.set_workspace_state(COUNTRY_STATE_KEY, code)
    return code, add_country_operators(repository, code) if code else 0
