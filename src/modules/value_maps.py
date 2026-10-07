"""Operator, Vendor and Operator_Vendor values as the workspace maps show them.

Every filter, table, chart and report shows the canonical labels of the Operator Maps
and Vendor Maps (Campaigns follow the Campaign Maps, see ``column_names``). Modules
whose data keep the source spellings show the mapped values and, to filter, expand a
mapped selection to the source values it stands for. Only Preview Dataset shows the
source values as they are.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from src.modules.cdr_reporting import _normalise_operator_label, _normalise_vendor
from src.modules.mapping_order import dimension_order_key, split_vendor_operator, swap_operator_vendor, swap_vendor_operator

# The kind of value each filter field holds.
FIELD_KINDS = {
    'operator': 'operator', 'operators': 'operator',
    'vendor': 'vendor', 'vendors_only': 'vendor',
    'operator_vendor': 'operator_vendor', 'operator_vendors': 'operator_vendor',
    'vendor_operator': 'vendor_operator', 'vendor_operators': 'vendor_operator',
}


def field_kind(field: str) -> str | None:
    """'operator', 'vendor' or 'operator_vendor' for a filter field, or None when it is not mapped."""
    key = ''.join(character for character in str(field or '').casefold() if character.isalnum() or character == '_')
    return FIELD_KINDS.get(key)


class ValueMapper:
    """Maps source Operator, Vendor and Operator_Vendor values to their canonical labels."""

    def __init__(self, operator_mappings: dict[str, str] | None = None, vendor_mappings: dict[str, str] | None = None,
                 operator_groups: list[dict[str, Any]] | None = None, vendor_groups: list[dict[str, Any]] | None = None) -> None:
        self.operator_mappings = {str(key).strip().casefold(): str(value) for key, value in (operator_mappings or {}).items()}
        self.vendor_mappings = {str(key).strip().casefold(): str(value) for key, value in (vendor_mappings or {}).items()}
        self.operator_groups = list(operator_groups or [])
        self.vendor_groups = list(vendor_groups or [])

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> 'ValueMapper':
        return cls(settings.get('operator_mappings'), settings.get('vendor_mappings'),
                   settings.get('operator_mapping_groups'), settings.get('vendor_mapping_groups'))

    @classmethod
    def from_repository(cls, repository: Any) -> 'ValueMapper':
        return cls.from_settings(repository.chart_mapping_settings())

    def map(self, kind: str | None, value: Any) -> Any:
        """The canonical label of one value; blanks and unmapped kinds stay as they are."""
        if value is None or not str(value).strip() or kind is None:
            return value
        if kind == 'operator':
            return _normalise_operator_label(value, self.operator_mappings)
        if kind == 'vendor_operator':
            vendor, operator = split_vendor_operator(value, self.operator_groups)
            operator = _normalise_operator_label(operator, self.operator_mappings)
            if not vendor:
                return f'{operator} - All'
            # The whole Vendor is one label: Ericsson_Mixed is not an Operator_Vendor value.
            return f'{_normalise_operator_label(vendor, self.vendor_mappings)}_{operator}'
        return _normalise_vendor(value, self.operator_mappings, self.vendor_mappings)

    def vendor_operators(self, operator_vendors: Iterable[Any]) -> list[str]:
        """The Vendor_Operator values of some Operator_Vendor values (the same identities the other way round)."""
        return [swap_operator_vendor(value, self.operator_groups) for value in operator_vendors
                if value is not None and str(value).strip()]

    def operator_vendors(self, vendor_operators: Iterable[Any]) -> list[str]:
        """The Operator_Vendor values a Vendor_Operator selection stands for."""
        return [swap_vendor_operator(value, self.operator_groups) for value in vendor_operators
                if value is not None and str(value).strip()]

    def values(self, kind: str | None, values: Iterable[Any]) -> list[Any]:
        """The distinct mapped values in the order of the Operator and Vendor Maps (see ``mapping_order``)."""
        mapped = list(dict.fromkeys(self.map(kind, value) for value in values if value is not None and str(value).strip()))
        if kind is None:
            return mapped
        return sorted(mapped, key=lambda value: dimension_order_key(kind, value, self.operator_groups, self.vendor_groups))

    def expand(self, kind: str | None, selected: Iterable[Any], source_values: Iterable[Any]) -> list[Any]:
        """The source values a mapped selection stands for (the selection itself is kept too)."""
        wanted = {str(value).strip().casefold() for value in selected if value is not None and str(value).strip()}
        if kind is None or not wanted:
            return list(selected)
        expanded = [value for value in source_values
                    if str(value).strip().casefold() in wanted or str(self.map(kind, value)).strip().casefold() in wanted]
        return list(dict.fromkeys([*expanded, *selected]))

    def _aliases(self, mappings: dict[str, str]) -> dict[str, list[str]]:
        aliases: dict[str, list[str]] = {}
        for alias, canonical in mappings.items():
            aliases.setdefault(canonical.casefold(), [canonical]).append(alias)
        return aliases

    def sources(self, kind: str | None, selected: Iterable[Any]) -> list[str]:
        """Every spelling a mapped selection stands for, from the maps alone (no data is read).

        Operator_Vendor combines the spellings of its Operator and of its Vendor, and
        "<Operator> - All" those of its Operator.
        """
        selected = [str(value).strip() for value in selected if value is not None and str(value).strip()]
        if kind is None:
            return selected
        operators = self._aliases(self.operator_mappings)
        vendors = self._aliases(self.vendor_mappings)
        result = list(selected)
        for value in selected:
            if kind == 'operator':
                result.extend(operators.get(value.casefold(), []))
                continue
            all_vendors = re.match(r'^(.*?)\s+- All(?: Vendors)?$', value, flags=re.IGNORECASE)
            if all_vendors:
                result.extend(f'{alias} - All' for alias in operators.get(all_vendors.group(1).casefold(), []))
                continue
            if kind == 'vendor':
                result.extend(vendors.get(value.casefold(), []))
                continue
            for index, character in enumerate(value):
                operator, vendor = value[:index], value[index + 1:]
                if character == '_' and operator.casefold() in operators and vendor:
                    result.extend(f'{operator_alias}_{vendor_alias}' for operator_alias in operators[operator.casefold()]
                                  for vendor_alias in vendors.get(vendor.casefold(), [vendor]))
        return list(dict.fromkeys(result))
