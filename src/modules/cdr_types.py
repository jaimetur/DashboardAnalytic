"""The CDR file type a workspace handles.

Each workspace processes the CDRs of one provider. NetCheck CDR is supported;
Umlaut CDR files are similar but rename some columns and are listed as
upcoming until their column mapping is available.
"""
from __future__ import annotations

from typing import Any

CDR_TYPE_STATE_KEY = 'cdr_file_type'
DEFAULT_CDR_TYPE = 'netcheck'
CDR_TYPES: dict[str, dict[str, Any]] = {
    'netcheck': {'label': 'NetCheck CDR', 'supported': True},
    'umlaut': {'label': 'Umlaut CDR', 'supported': False},
}


def cdr_type_options() -> list[dict[str, Any]]:
    """The CDR types for selectors, the supported ones enabled."""
    return [{'value': key, **value} for key, value in CDR_TYPES.items()]


def normalize_cdr_type(value: object) -> str:
    """A supported CDR type; anything else is rejected."""
    key = str(value or DEFAULT_CDR_TYPE).strip().casefold()
    if key not in CDR_TYPES:
        raise ValueError('Choose one of the listed CDR types.')
    if not CDR_TYPES[key]['supported']:
        raise ValueError(f"{CDR_TYPES[key]['label']} files are not supported yet.")
    return key


def workspace_cdr_type(repository: Any) -> str:
    """The CDR type of a workspace; workspaces created before the setting handle NetCheck CDRs."""
    stored = str(repository.get_workspace_state(CDR_TYPE_STATE_KEY) or '').strip().casefold()
    return stored if stored in CDR_TYPES else DEFAULT_CDR_TYPE


def set_workspace_cdr_type(repository: Any, value: object) -> str:
    cdr_type = normalize_cdr_type(value)
    repository.set_workspace_state(CDR_TYPE_STATE_KEY, cdr_type)
    return cdr_type
