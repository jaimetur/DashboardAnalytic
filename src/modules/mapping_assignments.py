"""Operator, Vendor and Campaign values found in the CDRs and the label the workspace maps give them.

The Operator Maps and Vendor Maps start from the values of the ready CDRs of the workspace: each
detected value is assigned to one label, and a label that stands for several detected values merges
them in every filter, table, chart and report. A value no map assigns keeps its own name and is
reported as unassigned until it is assigned. Campaigns follow the Campaign Maps pattern: a campaign
without a year and quarter and without an exception is unassigned.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from src.modules.column_names import campaign_parts, format_campaign

KINDS = ('operator', 'vendor', 'campaign')
KIND_TITLES = {'operator': 'Operators', 'vendor': 'Vendors', 'campaign': 'Campaigns'}
# The cached CDR catalogue field holding each kind of value.
CATALOGUE_FIELDS = {'operator': 'operators', 'vendor': 'vendors_only', 'campaign': 'campaigns'}
_ALL_SUFFIX = re.compile(r'\s+- All(?: Vendors)?$', re.IGNORECASE)


def detected_values(catalogues: dict[int, dict[str, list[str]]], dataset_names: dict[int, str],
                    operator_mappings: dict[str, str] | None = None) -> dict[str, dict[str, list[str]]]:
    """``{kind: {value: [CDR names]}}`` for the Operators, Vendors and Campaigns of the CDRs.

    Values differing only in case are one value. Vendors leave out the operator-only identities
    (``<Operator> - All`` and Operator names), which are not Vendors.
    """
    found: dict[str, dict[str, tuple[str, list[str]]]] = {kind: {} for kind in KINDS}
    for dataset_id, catalogue in catalogues.items():
        name = dataset_names.get(dataset_id) or f'CDR {dataset_id}'
        for kind, field in CATALOGUE_FIELDS.items():
            for value in catalogue.get(field) or []:
                text = str(value).strip()
                if not text:
                    continue
                entry = found[kind].setdefault(text.casefold(), (text, []))
                if name not in entry[1]:
                    entry[1].append(name)
    operators = {*found['operator'], *(str(key).casefold() for key in (operator_mappings or {})),
                 *(str(value).casefold() for value in (operator_mappings or {}).values())}
    found['vendor'] = {key: entry for key, entry in found['vendor'].items()
                       if key not in operators and not _ALL_SUFFIX.search(entry[0])}
    return {kind: {value: sorted(names, key=str.casefold) for value, names in entries.values()}
            for kind, entries in found.items()}


def campaign_assignment(value: str, campaign_map: dict) -> tuple[str, bool]:
    """The label of a campaign and whether the Campaign Map assigns it (an exception or a year and quarter)."""
    label = format_campaign(value, campaign_map)
    if any(value.casefold() in {source.casefold() for source in item['sources']}
           or value.casefold() == item['label'].casefold() for item in campaign_map.get('exceptions') or []):
        return label, True
    year, quarter, _mode = campaign_parts(value)
    return label, bool(year and quarter)


def assignment_rows(kind: str, detected: dict[str, list[str]], mappings: dict[str, str],
                    campaign_map: dict | None = None) -> list[dict[str, Any]]:
    """One row per detected value: its CDRs, label, whether it is assigned and the values merged with it.

    Unassigned values come first, then by label and value.
    """
    rows = []
    for value, cdrs in detected.items():
        if kind == 'campaign':
            label, assigned = campaign_assignment(value, campaign_map or {})
        else:
            mapped = mappings.get(value.casefold())
            label, assigned = (mapped, True) if mapped else (value, False)
        rows.append({'value': value, 'cdrs': cdrs, 'label': label, 'assigned': assigned,
                     # The canonical label of its own group: renaming the group changes it.
                     'canonical': assigned and kind != 'campaign' and label.casefold() == value.casefold()})
    members: dict[str, list[str]] = {}
    for row in rows:
        if row['assigned']:
            members.setdefault(row['label'].casefold(), []).append(row['value'])
    for row in rows:
        group = members.get(row['label'].casefold(), []) if row['assigned'] else []
        row['merged_with'] = sorted((value for value in group if value != row['value']), key=str.casefold)
    return sorted(rows, key=lambda row: (row['assigned'], row['label'].casefold(), row['value'].casefold()))


def unassigned_values(rows_by_kind: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    """The unassigned values of each kind (only the kinds that have some)."""
    result = {kind: sorted((row['value'] for row in rows if not row['assigned']), key=str.casefold)
              for kind, rows in rows_by_kind.items()}
    return {kind: values for kind, values in result.items() if values}


def assignment_effects(
    kind: str, assignments: Iterable[tuple[str, str | None]], detected: Iterable[str], mappings: dict[str, str],
    canonical_labels: Iterable[str], rename: tuple[str, str] | None = None,
    saved_filters: Callable[[str], int] | None = None,
) -> dict[str, list[Any]]:
    """What saving some assignments does, to confirm it first.

    ``assignments`` are ``(source value, label)`` pairs; a ``None`` label leaves the value unassigned.
    ``rename`` is the ``(old, new)`` canonical label of a group saved under another name. The result lists:

    - ``merges``: labels that would stand for two or more detected values, other than they already do;
    - ``moved``: values leaving their label, with how many saved filters use that label (and so stop
      including the value);
    - ``underscores``: new Operator or Vendor labels with ``_``, the Operator_Vendor separator.
    """
    detected = list(detected)
    canonical_labels = [str(label) for label in canonical_labels]
    current = {str(source).casefold(): str(label) for source, label in mappings.items()}
    old_name, new_name = rename or ('', '')

    def renamed(label: str | None) -> str | None:
        return new_name if label and old_name and label.casefold() == old_name.casefold() else label

    before = {source: renamed(label) for source, label in current.items()}
    after = dict(before)
    existing = {label.casefold(): label for label in canonical_labels}
    if rename:
        existing.pop(old_name.casefold(), None)
        existing[new_name.casefold()] = new_name
    changes: list[tuple[str, str | None]] = []
    for source, label in assignments:
        source = str(source).strip()
        label = str(label).strip() if label is not None else None
        if not source:
            continue
        label = existing.get(label.casefold(), label) if label else None
        changes.append((source, label))
        if label:
            after[source.casefold()] = label
        else:
            after.pop(source.casefold(), None)

    def members(mapping: dict[str, str | None], label: str) -> list[str]:
        return sorted((value for value in detected if (mapping.get(value.casefold()) or '').casefold() == label.casefold()),
                      key=str.casefold)

    merges, seen = [], set()
    for _source, label in changes:
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        values = members(after, label)
        if len(values) >= 2 and values != members(before, label):
            merges.append({'label': label, 'values': values})
    moved = []
    for source, label in changes:
        previous = current.get(source.casefold())
        if not previous or previous.casefold() == source.casefold():
            continue
        if label and (renamed(previous) or '').casefold() == label.casefold():
            continue
        moved.append({'value': source, 'from': previous, 'to': label,
                      'filters': saved_filters(previous) if saved_filters else 0})
    underscores = []
    if kind in {'operator', 'vendor'}:
        underscores = sorted({label for _source, label in changes
                              if label and '_' in label and label.casefold() not in {
                                  value.casefold() for value in canonical_labels}}, key=str.casefold)
    return {'merges': merges, 'moved': moved, 'underscores': underscores}
