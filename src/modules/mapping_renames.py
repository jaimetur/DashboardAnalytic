"""Renaming an Operator or a Vendor in the Operator Maps or Vendor Maps renames it in every saved filter.

Saved filters keep the mapped labels (see ``value_maps``), so a renamed label would no longer match
and the filters would silently drop it. Only values of Operator, Operator_Vendor, Vendor_Operator and
Vendor fields change, and only when they are the renamed label: ``<Operator>``, ``<Operator>_<Vendor>``,
``<Vendor>_<Operator>`` or ``<Operator> - All``. Campaign filters keep the full campaign value, which a
Campaign Map only shows differently, so they never need renaming.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode

# Filter keys and the kind of value they hold.
KEY_KINDS = {
    'operator': 'operator', 'operators': 'operator', 'baseline_operator': 'operator',
    'operator_vendor': 'operator_vendor', 'operator_vendors': 'operator_vendor',
    'vendor_operator': 'vendor_operator', 'vendor_operators': 'vendor_operator',
    'vendor': 'vendor', 'vendors': 'vendor', 'vendors_only': 'vendor',
}
# Workspace settings that keep filters: saved Scoring report configurations, the Scoring calculation,
# the Non-Qualified Calls filters and the Dashboards. CDR Analysis keeps the filters of each CDR as a query string.
FILTER_STATE_KEYS = (
    'scoring_report_configurations', 'scoring_calculation_selection_v1', 'nq_calls_filters',
    'ppt_dashboards_v2', 'ppt_dashboard_sets_v1',
)
CDR_ANALYSIS_STATE_KEY = 'datasets_analysis_selection_v1'
_ALL_SUFFIX = re.compile(r'^(?P<name>.+?)\s+- All(?: Vendors)?$', re.IGNORECASE)


def key_kind(key: Any) -> str | None:
    return KEY_KINDS.get(re.sub(r'[^a-z0-9]+', '_', str(key).casefold()).strip('_'))


def _labels(mapping_settings: dict[str, Any], mapping_type: str, extra: tuple[str, ...]) -> list[str]:
    labels = {str(label).strip() for group in mapping_settings.get(f'{mapping_type}_mapping_groups') or []
              for label in [group.get('canonical'), *(group.get('aliases') or [])] if str(label or '').strip()}
    labels.update(label for label in extra if label)
    # The longest first, so VF_SA_Ericsson is VF_SA's and not VF's.
    return sorted(labels, key=len, reverse=True)


def value_renamer(mapping_type: str, old_name: str, new_name: str,
                  mapping_settings: dict[str, Any]) -> Callable[[str, str], str]:
    """``rename(kind, value)``: the value with the renamed Operator or Vendor label."""
    old, new = str(old_name).strip(), str(new_name).strip()
    old_key = old.casefold()
    names = (old, new)
    operators = _labels(mapping_settings, 'operator', names if mapping_type == 'operator' else ())
    vendors = _labels(mapping_settings, 'vendor', names if mapping_type == 'vendor' else ())

    def rename(kind: str, value: str) -> str:
        text = value.strip()
        folded = text.casefold()
        if not old or not new or old == new or not text:
            return value
        operator_only = _ALL_SUFFIX.match(text)
        if operator_only:
            renamed = mapping_type == 'operator' and operator_only['name'].strip().casefold() == old_key
            return f'{new} - All' if renamed else value
        if kind == mapping_type:
            return new if folded == old_key else value
        if kind == 'operator_vendor':
            operator = next((label for label in operators if folded.startswith(f'{label.casefold()}_')), None)
            vendor = text[len(operator) + 1:] if operator else ''
        elif kind == 'vendor_operator':
            operator = next((label for label in operators if len(folded) > len(label) + 1
                             and folded.endswith(f'_{label.casefold()}')), None)
            vendor = text[:len(text) - len(operator) - 1] if operator else ''
        else:
            return value
        if not operator or not vendor:
            return value
        if mapping_type == 'operator' and operator.casefold() == old_key:
            operator = new
        elif mapping_type == 'vendor' and vendor.casefold() == old_key and any(
                label.casefold() == old_key for label in vendors):
            vendor = new
        else:
            return value
        return f'{operator}_{vendor}' if kind == 'operator_vendor' else f'{vendor}_{operator}'

    return rename


def rename_in_document(document: Any, rename: Callable[[str, str], str], kind: str | None = None) -> Any:
    """A copy of a JSON document with the values of its Operator and Vendor filters renamed."""
    if isinstance(document, dict):
        return {key: rename_in_document(item, rename, key_kind(key)) for key, item in document.items()}
    if isinstance(document, list):
        return [rename_in_document(item, rename, kind) for item in document]
    if isinstance(document, str) and kind:
        return rename(kind, document)
    return document


def rename_in_query(query: str, rename: Callable[[str, str], str]) -> str:
    """A CDR Analysis query string (``operator=VF&vendor=Ericsson``) with its filter values renamed."""
    pairs = parse_qsl(query, keep_blank_values=True)
    renamed = [(key, rename(kind, value) if (kind := key_kind(key)) else value) for key, value in pairs]
    return urlencode(renamed) if renamed != pairs else query


def rename_saved_filters(repository: Any, mapping_type: str, old_name: str, new_name: str,
                         mapping_settings: dict[str, Any], write: bool = True) -> int:
    """Rename an Operator or Vendor in the Reporting Jobs and workspace settings; returns how many changed.

    Without ``write`` nothing is saved: it counts the Reporting Jobs and saved filters that use the label.
    """
    from src.modules.report_tasks import rename_definition_values

    rename = value_renamer(mapping_type, old_name, new_name, mapping_settings)
    changed = rename_definition_values(repository, lambda definition: rename_in_document(definition, rename), write)
    for state_key in FILTER_STATE_KEYS:
        stored = repository.get_workspace_state(state_key)
        if not stored:
            continue
        try:
            document = json.loads(stored)
        except (TypeError, ValueError):
            continue
        renamed = rename_in_document(document, rename)
        if renamed != document:
            if write:
                repository.set_workspace_state(state_key, json.dumps(renamed, ensure_ascii=False))
            changed += 1
    try:
        selection = json.loads(repository.get_workspace_state(CDR_ANALYSIS_STATE_KEY) or '{}')
    except (TypeError, ValueError):
        selection = {}
    queries = selection.get('queries') if isinstance(selection, dict) else None
    if isinstance(queries, dict):
        renamed_queries = {key: rename_in_query(str(value), rename) for key, value in queries.items()}
        if renamed_queries != queries:
            if write:
                repository.set_workspace_state(CDR_ANALYSIS_STATE_KEY, json.dumps({**selection, 'queries': renamed_queries}))
            changed += 1
    return changed


def count_saved_filters(repository: Any, mapping_type: str, label: str, mapping_settings: dict[str, Any]) -> int:
    """How many Reporting Jobs and saved filters use an Operator or Vendor label (nothing is changed)."""
    return rename_saved_filters(repository, mapping_type, label, f'{label}\u0000', mapping_settings, write=False)
