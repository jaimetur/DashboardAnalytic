"""5G NR Mode (NSA/SA) classification for CDR datasets."""

from __future__ import annotations

import re
from pathlib import Path

NR_MODES = ('NSA', 'SA')
DEFAULT_NR_MODE = 'NSA'
NR_MODE_DATASET_KINDS = frozenset({'data', 'voice', 'speech'})

_NSA_TOKEN = re.compile(r'(?:5g|g)?nsa')
_SA_TOKEN = re.compile(r'(?:5g|g)?sa')


def normalize_nr_mode(value: object) -> str | None:
    """Return ``NSA`` or ``SA`` for a supported value, otherwise ``None``."""
    text = str(value or '').strip().upper()
    return text if text in NR_MODES else None


def infer_nr_mode(file_name: object) -> str:
    """Suggest the NR Mode of a CDR from its file name.

    ``SA`` is suggested only when the name explicitly identifies Standalone
    (for example ``UK_Q2_2026_SA_Data.csv``, ``5G SA`` or ``Standalone``).
    Names that mention NSA/Non-Standalone, or nothing at all, default to NSA.
    """
    stem = Path(str(file_name or '')).stem
    # Split camel-case words (``DataSA`` -> ``Data SA``) before lower-casing.
    spaced = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', stem)
    normalized = re.sub(r'[^a-z0-9]+', ' ', spaced.casefold())
    tokens = normalized.split()
    compact = ''.join(tokens)
    if 'nonstandalone' in compact or any(_NSA_TOKEN.fullmatch(token) for token in tokens):
        return 'NSA'
    if 'standalone' in compact or any(_SA_TOKEN.fullmatch(token) for token in tokens):
        return 'SA'
    return DEFAULT_NR_MODE


def dataset_nr_mode(dataset_kind: object, nr_mode: object, file_name: object = '') -> str | None:
    """Return the effective NR Mode of a dataset, or ``None`` for non-CDR files."""
    if str(dataset_kind or '').casefold() not in NR_MODE_DATASET_KINDS:
        return None
    return normalize_nr_mode(nr_mode) or infer_nr_mode(file_name)
