"""Vendor identities for scoring, leaving persisted CDR identities unchanged."""
from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from src.modules.column_names import column_identity, vendor_only_value


def scoring_vendor_name(value: object, operators: Iterable[object] = ()) -> str:
    """Remove known operator prefixes, including operator names with underscores."""
    text = '' if value is None else str(value).strip()
    names = sorted({str(operator).strip() for operator in operators if operator}, key=len, reverse=True)
    if text.casefold() in {name.casefold() for name in names}:
        return text
    for name in names:
        prefix = f'{name}_'
        if text.casefold().startswith(prefix.casefold()):
            return text[len(prefix):]
    for name in names:
        stripped = vendor_only_value(text, name)
        if stripped != text:
            return stripped
    return text


def scoring_vendor_group(value: object, operators: Iterable[object]) -> str:
    """Label operators without an assigned vendor as All in vendor aggregation."""
    operators = list(operators)
    name = scoring_vendor_name(value, operators)
    if not name or name.casefold() in {str(operator).strip().casefold() for operator in operators if operator}:
        return 'All'
    return name


def scoring_vendor_names(values: Iterable[object], operators: Iterable[object]) -> list[str]:
    """List actual vendors, excluding CDR operator-only fallback identities."""
    operators = list(operators)
    operator_identities = {str(name).strip().casefold() for name in operators if name}
    return sorted({
        name for value in values
        if (name := scoring_vendor_name(value, operators))
        and name.casefold() not in operator_identities
    }, key=str.casefold)


def scoring_vendor_operators(catalogues: dict, groups: list[dict] | None = None) -> list[str]:
    """Collect catalogue operators and configured aliases without reading CDR rows."""
    names = [name for catalogue in catalogues.values() for name in catalogue.get('operators', [])]
    for group in groups or []:
        names.extend([group.get('canonical', ''), *(group.get('aliases') or [])])
    return names


def normalize_scoring_vendor_result(result: dict[str, Any], groups: list[dict] | None = None) -> dict[str, Any]:
    """Copy saved result rows for consistent vendor labels in web and exports."""
    normalized = copy.deepcopy(result)
    operators = scoring_vendor_operators({}, groups)
    for rows in normalized.values():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    operators.extend(value for key, value in row.items() if column_identity(key) == 'operator' and value)
    for rows in normalized.values():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    for key, value in row.items():
                        if column_identity(key) == 'vendor' and value is not None:
                            row[key] = scoring_vendor_group(value, operators)
    return normalized
