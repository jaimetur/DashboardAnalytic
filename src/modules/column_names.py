from __future__ import annotations

import re
from collections.abc import Iterable


COLUMN_IDENTITY_ALIASES = {
    'suscriber': 'subscriber',
    'suscribers': 'subscribers',
}


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
