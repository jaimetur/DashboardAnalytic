"""Workspace-wide persistence for the Scoring calculation controls."""

from __future__ import annotations

import json
from typing import Any

from src.branding import canonical_format
from src.modules.column_names import column_identity
from src.modules.cdr_stage import combined_dataset_ids
from src.modules.nr_mode import normalize_nr_mode
from src.modules.repository import Repository
from src.modules.scoring_vendors import scoring_vendor_name, scoring_vendor_operators
from src.modules.scoring_config import load_aggregation_hierarchy


SCORING_SELECTION_STATE_KEY = 'scoring_calculation_selection_v1'
SCORING_SELECTION_FORMAT = 'drivetest-analyzer-scoring-selection'
SCORING_SELECTION_VERSION = 1
SCORING_CONTEXT_FILTER_FIELDS = ('Region', 'Cluster', 'City', 'Operator', 'Operator_Vendor', 'Vendor', 'Campaign')
# Filters that are not aggregation levels: saved selections only list them when used.
SCORING_OPTIONAL_CONTEXT_FILTERS = frozenset({'Cluster', 'Operator_Vendor'})
MAX_TRACKED_CLIENTS = 64


def _profile_context(repository: Repository) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        profile_state = repository.get_scoring_profiles()
    except ValueError:
        return {}, ''
    profiles = {
        str(profile['id']): profile
        for profile in profile_state['profiles']
        if isinstance(profile, dict) and str(profile.get('id') or '').strip()
    }
    active_id = str(profile_state.get('active_profile_id') or '')
    return profiles, active_id


def _operator_options(repository: Repository) -> list[str]:
    options: list[str] = []
    seen: set[str] = set()
    for group in repository.list_operator_mapping_groups():
        canonical = str(group.get('canonical') or '').strip()
        identity = canonical.casefold()
        if canonical and identity not in seen:
            options.append(canonical)
            seen.add(identity)
    return options or ['EE']


def _available_cdr_rows(repository: Repository) -> list[dict[str, Any]]:
    # The CDRs of the combined tables: Final CDRs, and Daily CDRs until a Final CDR replaces them.
    included = combined_dataset_ids(repository)
    available: list[dict[str, Any]] = []
    for raw_row in repository.list_datasets():
        row = dict(raw_row)
        kind = str(row.get('dataset_kind') or '').strip().casefold()
        if str(row.get('status') or '').strip().casefold() != 'ready' or kind not in {'data', 'voice', 'speech'}:
            continue
        if int(row['id']) not in included:
            continue
        mode = normalize_nr_mode(row.get('nr_mode'))
        if mode not in {'NSA', 'SA'}:
            continue
        available.append({**row, 'id': int(row['id']), 'dataset_kind': kind, 'nr_mode': mode})
    return available


def _available_cdr_ids(
    repository: Repository,
    rows: list[dict[str, Any]],
    selected_ids: list[int] | None = None,
) -> set[int]:
    selected = set(selected_ids) if selected_ids is not None else None
    return {
        int(row['id']) for row in rows
        if (selected is None or int(row['id']) in selected)
        and repository.dataset_rows_table_exists(int(row['id']))
    }


def _default_nr_mode(rows: list[dict[str, Any]]) -> str:
    modes = {str(row['nr_mode']) for row in rows}
    return 'NSA' if 'NSA' in modes else ('SA' if 'SA' in modes else 'NSA')


def _default_selection(repository: Repository) -> dict[str, Any]:
    rows = _available_cdr_rows(repository)
    nr_mode = _default_nr_mode(rows)
    defaults = _fallback_selection(repository, rows=rows, nr_mode=nr_mode)
    # Repository catalogue order is newest first, matching the scoring page's default.
    for kind in ('data', 'voice', 'speech'):
        latest = next((row for row in rows
                       if row['nr_mode'] == nr_mode
                       and row['dataset_kind'] == kind
                       and repository.dataset_rows_table_exists(int(row['id']))), None)
        if latest is not None:
            defaults['dataset_ids'].append(int(latest['id']))
    return defaults


def _fallback_selection(
    repository: Repository,
    *,
    rows: list[dict[str, Any]] | None = None,
    nr_mode: str | None = None,
) -> dict[str, Any]:
    rows = rows if rows is not None else _available_cdr_rows(repository)
    selected_mode = nr_mode or _default_nr_mode(rows)
    profiles, active_profile_id = _profile_context(repository)
    operator_options = _operator_options(repository)
    baseline = next((value for value in operator_options if value.casefold() == 'ee'), operator_options[0])
    return {
        'dataset_ids': [],
        'aggregation_levels': ['Operator'],
        'nr_mode': selected_mode,
        'baseline_operator': baseline,
        'scoring_profile_id': active_profile_id if profiles else '',
        'context_filters': {field: [] for field in SCORING_CONTEXT_FILTER_FIELDS if field not in SCORING_OPTIONAL_CONTEXT_FILTERS},
    }


def _normalize_context_filters(
    raw_filters: object,
    hierarchy: list[str],
    warnings: list[str],
) -> dict[str, list[str]]:
    normalized = {field: [] for field in SCORING_CONTEXT_FILTER_FIELDS if field not in SCORING_OPTIONAL_CONTEXT_FILTERS}
    if raw_filters is None:
        return normalized
    if not isinstance(raw_filters, dict):
        warnings.append('Saved context filters were invalid and have been cleared.')
        return normalized
    supported = {column_identity(field): field for field in SCORING_CONTEXT_FILTER_FIELDS}
    # Cluster and Operator_Vendor filter the samples without being aggregation levels.
    allowed_fields = {column_identity(field) for field in hierarchy} | {'cluster', 'operatorvendor'}
    values_by_field: dict[str, dict[str, str]] = {field: {} for field in SCORING_CONTEXT_FILTER_FIELDS}
    stale_fields = False
    for raw_field, raw_values in raw_filters.items():
        canonical = supported.get(column_identity(raw_field))
        if canonical is None or column_identity(canonical) not in allowed_fields:
            stale_fields = True
            continue
        if raw_values is None:
            continue
        values = [raw_values] if isinstance(raw_values, str) else raw_values
        if not isinstance(values, (list, tuple, set)):
            stale_fields = True
            continue
        for raw_value in values:
            value = str(raw_value).strip() if raw_value is not None else ''
            if value:
                values_by_field[canonical].setdefault(value.casefold(), value)
    for field, values in values_by_field.items():
        if values or field not in SCORING_OPTIONAL_CONTEXT_FILTERS:
            normalized[field] = sorted(values.values(), key=lambda value: (value.casefold(), value))
    if stale_fields:
        warnings.append('Context filters from the previous selection were no longer supported and have been cleared.')
    return normalized


def _normalize_selection(
    repository: Repository,
    raw_selection: object,
    defaults: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not isinstance(raw_selection, dict):
        return defaults, ['Saved scoring selection was invalid and has been reset.']

    profiles, active_profile_id = _profile_context(repository)
    selected_profile_id = str(raw_selection.get('scoring_profile_id') or '').strip()
    if profiles and selected_profile_id not in profiles:
        if selected_profile_id:
            warnings.append('The saved scoring methodology is no longer available; the active methodology was selected.')
        selected_profile_id = active_profile_id
    elif not profiles:
        if selected_profile_id:
            warnings.append('The saved scoring methodology is unavailable; import a scoring configuration before calculating.')
        selected_profile_id = ''
    elif not selected_profile_id:
        selected_profile_id = active_profile_id
    hierarchy = load_aggregation_hierarchy(repository)
    hierarchy_by_identity = {column_identity(level): level for level in hierarchy}

    raw_mode = normalize_nr_mode(raw_selection.get('nr_mode'))
    rows = _available_cdr_rows(repository)
    if raw_mode not in {'NSA', 'SA'}:
        raw_mode = defaults['nr_mode']
        warnings.append('The saved NR Mode was invalid; the default mode was selected.')
    if not any(row['nr_mode'] == raw_mode for row in rows):
        available_mode = _default_nr_mode(rows)
        if available_mode != raw_mode:
            raw_mode = available_mode
            warnings.append('The saved NR Mode is no longer available; the available mode was selected.')

    raw_ids = raw_selection.get('dataset_ids', [])
    if not isinstance(raw_ids, (list, tuple, set)):
        raw_ids = []
        warnings.append('The saved CDR selection was invalid and has been cleared.')
    parsed_ids: list[int] = []
    invalid_ids = False
    for value in raw_ids:
        if isinstance(value, bool):
            invalid_ids = True
            continue
        try:
            dataset_id = int(value)
        except (TypeError, ValueError, OverflowError):
            invalid_ids = True
            continue
        if dataset_id <= 0:
            invalid_ids = True
            continue
        if dataset_id not in parsed_ids:
            parsed_ids.append(dataset_id)
    rows_by_id = {int(row['id']): row for row in rows}
    table_ids = _available_cdr_ids(repository, rows, parsed_ids) if parsed_ids else set()
    dataset_ids = [
        dataset_id for dataset_id in parsed_ids
        if dataset_id in rows_by_id
        and rows_by_id[dataset_id]['nr_mode'] == raw_mode
        and dataset_id in table_ids
    ]
    if invalid_ids or len(dataset_ids) != len(parsed_ids):
        warnings.append('One or more saved CDR datasets are no longer available and were removed.')

    raw_levels = raw_selection.get('aggregation_levels', defaults['aggregation_levels'])
    if not isinstance(raw_levels, (list, tuple, set)):
        raw_levels = []
        warnings.append('Saved Split by levels were invalid and have been reset.')
    selected_level_ids = {column_identity(value) for value in raw_levels if str(value).strip()}
    aggregation_levels = [
        level for level in hierarchy
        if column_identity(level) == column_identity('Operator') or column_identity(level) in selected_level_ids
    ]
    if any(identity not in hierarchy_by_identity for identity in selected_level_ids):
        warnings.append('Split by levels from the previous methodology were removed.')
    if not aggregation_levels:
        aggregation_levels = ['Operator']

    operator_options = _operator_options(repository)
    raw_baseline = str(raw_selection.get('baseline_operator') or '').strip()
    baseline = next((value for value in operator_options if value.casefold() == raw_baseline.casefold()), None)
    if baseline is None:
        baseline = next((value for value in operator_options if value.casefold() == 'ee'), operator_options[0])
        if raw_baseline and raw_baseline.casefold() != baseline.casefold():
            warnings.append('The saved GAP reference operator is no longer available; a default operator was selected.')

    context_filters = _normalize_context_filters(raw_selection.get('context_filters'), hierarchy, warnings)
    vendor_operators = scoring_vendor_operators(
        repository.cdr_catalogues_by_dataset(dataset_ids), repository.list_operator_mapping_groups(),
    )
    context_filters['Vendor'] = sorted({
        scoring_vendor_name(value, vendor_operators) for value in context_filters['Vendor']
    }, key=str.casefold)
    return {
        'dataset_ids': dataset_ids,
        'aggregation_levels': aggregation_levels,
        'nr_mode': raw_mode,
        'baseline_operator': baseline,
        'scoring_profile_id': selected_profile_id,
        'context_filters': context_filters,
    }, list(dict.fromkeys(warnings))


def load_scoring_selection(repository: Repository) -> tuple[dict[str, Any], list[str]]:
    """Return the normalized workspace selection without reading CDR rows."""
    raw = repository.get_workspace_state(SCORING_SELECTION_STATE_KEY)
    if raw is None:
        return _default_selection(repository), []
    try:
        document = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return _default_selection(repository), ['Saved scoring selection could not be read and has been reset.']
    if not isinstance(document, dict):
        return _default_selection(repository), ['Saved scoring selection could not be read and has been reset.']
    if canonical_format(document.get('format')) == SCORING_SELECTION_FORMAT and document.get('version') == SCORING_SELECTION_VERSION:
        selection = document.get('selection')
    else:
        # Accept a flat selection document to ease recovery from early versions.
        selection = document
    defaults = _fallback_selection(repository)
    return normalize_scoring_selection(repository, selection, defaults=defaults)


def normalize_scoring_selection(
    repository: Repository,
    selection: object,
    *,
    defaults: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate a client selection against current workspace metadata."""
    return _normalize_selection(repository, selection, defaults or _fallback_selection(repository))


def save_scoring_selection(
    repository: Repository,
    selection: dict[str, Any],
    *,
    client_id: str | None = None,
    client_revision: int | None = None,
) -> bool:
    """Atomically store a selection and reject delayed writes from the same tab."""
    with repository.connection() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute(
            'SELECT value FROM workspace_state WHERE key = ?', (SCORING_SELECTION_STATE_KEY,),
        ).fetchone()
        try:
            existing = json.loads(str(row['value'])) if row else {}
        except (TypeError, json.JSONDecodeError):
            existing = {}
        revisions: dict[str, int] = {}
        if isinstance(existing, dict) and canonical_format(existing.get('format')) == SCORING_SELECTION_FORMAT:
            raw_revisions = existing.get('client_revisions')
            if isinstance(raw_revisions, dict):
                for existing_client, existing_revision in raw_revisions.items():
                    try:
                        normalized_revision = int(existing_revision)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if str(existing_client).strip() and normalized_revision > 0:
                        revisions[str(existing_client)] = normalized_revision

        if client_id and client_revision is not None:
            if client_revision <= revisions.get(client_id, 0):
                return False
            revisions[client_id] = client_revision
            while len(revisions) > MAX_TRACKED_CLIENTS:
                revisions.pop(next(iter(revisions)))

        document = serialize_scoring_selection(selection, revisions)
        connection.execute(
            'INSERT INTO workspace_state (key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (SCORING_SELECTION_STATE_KEY, document),
        )
    return True


def serialize_scoring_selection(
    selection: dict[str, Any],
    client_revisions: dict[str, int] | None = None,
) -> str:
    """Serialize the stable versioned workspace selection document."""
    return json.dumps({
        'format': SCORING_SELECTION_FORMAT,
        'version': SCORING_SELECTION_VERSION,
        'selection': selection,
        'client_revisions': client_revisions or {},
    }, ensure_ascii=False, separators=(',', ':'))
