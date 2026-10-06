"""Order of Operator, Vendor and Operator_Vendor values in every aggregation.

Operators follow the Operator Maps table of Workspace Config and Vendors the
Vendor Maps table. ``Operator_Vendor`` values are ordered by their Operator and,
within one Operator, by their Vendor. Labels missing from the maps follow the
mapped ones (pure Vendors before mixed, other and all-vendor groups), and
Operators without a Vendor come last, in Operator Map order.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from src.modules.column_names import column_identity, vendor_filter_rank

_ALL_SUFFIX = re.compile(r'\s+- All(?: Vendors)?$', re.IGNORECASE)
_SEPARATOR = re.compile(r'^\s*[_·|/]\s*')
UNMAPPED = 1_000_000


def _labels(group: dict[str, Any]) -> set[str]:
    return {str(label or '').strip().casefold() for label in [group.get('canonical'), *(group.get('aliases') or [])] if label}


def mapping_group(value: object, groups: Iterable[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The map group whose canonical label or alias is exactly ``value``."""
    key = _ALL_SUFFIX.sub('', str(value or '').strip()).casefold()
    return next((group for group in groups or [] if key in _labels(group)), None)


def _position(group: dict[str, Any] | None) -> int:
    try:
        return int(group.get('position', 0)) if group else UNMAPPED
    except (TypeError, ValueError):
        return UNMAPPED


def operator_order_key(value: object, operator_groups: Iterable[dict[str, Any]] | None) -> tuple[Any, ...]:
    group = mapping_group(value, operator_groups)
    return (0 if group else 1), _position(group), str(value or '').strip().casefold()


def vendor_order_key(
    value: object, vendor_groups: Iterable[dict[str, Any]] | None,
    operator_groups: Iterable[dict[str, Any]] | None = None,
) -> tuple[Any, ...]:
    text = _ALL_SUFFIX.sub('', str(value or '').strip())
    group = mapping_group(text, vendor_groups)
    if group:
        return 0, _position(group), text.casefold()
    operator = mapping_group(text, operator_groups)
    if operator or not text or vendor_filter_rank(value) == 2:
        return 2, _position(operator), text.casefold()
    return 1, vendor_filter_rank(value), text.casefold()


def split_operator_vendor(value: object, operator_groups: Iterable[dict[str, Any]] | None) -> tuple[str, str]:
    """Split ``<Operator>_<Vendor>`` at the longest Operator label it starts with."""
    text = _ALL_SUFFIX.sub('', str(value or '').strip())
    best = ''
    for group in operator_groups or []:
        for label in [group.get('canonical'), *(group.get('aliases') or [])]:
            candidate = str(label or '').strip()
            if (candidate and len(candidate) > len(best) and text.casefold().startswith(candidate.casefold())
                    and (len(text) == len(candidate) or _SEPARATOR.match(text[len(candidate):]))):
                best = candidate
    if not best:
        operator, separator, vendor = text.partition('_')
        return (operator, vendor) if separator else (text, '')
    return text[:len(best)], _SEPARATOR.sub('', text[len(best):], count=1)


def operator_vendor_order_key(
    value: object, operator_groups: Iterable[dict[str, Any]] | None, vendor_groups: Iterable[dict[str, Any]] | None,
) -> tuple[Any, ...]:
    operator, vendor = split_operator_vendor(value, operator_groups)
    # An Operator without a Vendor (``<Operator> - All``) comes after that Operator's Vendors.
    vendor_key = vendor_order_key(vendor, vendor_groups, operator_groups) if vendor else (3, UNMAPPED, '')
    return (*operator_order_key(operator, operator_groups), *vendor_key)


def dimension_order_key(
    dimension: object, value: object,
    operator_groups: Iterable[dict[str, Any]] | None, vendor_groups: Iterable[dict[str, Any]] | None,
) -> tuple[Any, ...] | None:
    """The map order of a value of an Operator, Vendor or Operator_Vendor dimension; ``None`` for other dimensions."""
    identity = column_identity(dimension)
    if identity in {'operator', 'subscriber'}:
        return operator_order_key(value, operator_groups)
    if identity in {'vendor', 'vendoronly', 'ranvendor'}:
        return vendor_order_key(value, vendor_groups, operator_groups)
    if identity == 'operatorvendor':
        return operator_vendor_order_key(value, operator_groups, vendor_groups)
    return None
