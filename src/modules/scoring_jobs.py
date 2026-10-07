"""Persistent background jobs and result caching for CDR scoring."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.modules.column_names import campaign_sort_key, column_identity, resolve_column_name
from src.modules.scoring_vendors import scoring_vendor_name, scoring_vendor_operators
from src.modules.nr_mode import NR_MODES, normalize_nr_mode
from src.modules.repository import Repository, local_now_iso
from src.modules.scoring_config import (
    DEFAULT_AGGREGATION_HIERARCHY,
    complete_aggregation_hierarchy,
    configuration_hash,
    load_aggregation_hierarchy,
    _is_legacy_two_environment_configuration,
    validate_scoring_configuration,
)


CDR_DATASET_KINDS = frozenset({'data', 'voice', 'speech'})
DEFAULT_BASELINE_OPERATOR = 'EE'
DEFAULT_LEVELS = ('Operator',)
INTERRUPTED_JOB_MESSAGE = 'Interrupted because the application restarted. Retry the job to run it again.'
AGGREGATION_CONTRACT_VERSION = 2
SCORING_CONTEXT_FILTER_FIELDS = ('Region', 'Cluster', 'City', 'Operator', 'Operator_Vendor', 'Vendor_Operator', 'Vendor', 'Campaign')
SCORING_CONTEXT_FILTER_COLUMNS = {
    'Region': ('Region', 'g_level_2'),
    'Cluster': ('Cluster',),
    'City': ('City', 'g_level_4'),
    'Operator': ('Operator',),
    'Operator_Vendor': ('Operator_Vendor',),
    # Vendor_Operator selections are translated to Operator_Vendor values (_expand_vendor_context_filters).
    'Vendor_Operator': ('Operator_Vendor',),
    'Vendor': ('Vendor',),
    'Campaign': ('Campaign',),
}
# Filters added after cached jobs existed only take part in a job's identity when used.
SCORING_OPTIONAL_CONTEXT_FILTERS = frozenset({'Cluster', 'Operator_Vendor', 'Vendor_Operator'})


def _scoring_engine():
    """Load the calculation engine only when a scoring job needs it."""
    return importlib.import_module('src.modules.scoring')


def _method_version(configuration: dict[str, Any]) -> str:
    engine = _scoring_engine()
    if configuration is None:
        raise ValueError('A scoring configuration is required. Import a Scoring Configuration before calculating scoring.')
    configured_version = getattr(engine, 'method_version_for_configuration', None)
    if callable(configured_version):
        return str(configured_version(configuration))
    snapshot = validate_scoring_configuration(configuration)
    base_version = str(getattr(engine, 'METHOD_VERSION', '1'))
    return f'{base_version}-config-{configuration_hash(snapshot)[:16]}'


def _workspace_scoring_configuration(repository: Repository) -> dict[str, Any]:
    getter = getattr(repository, 'get_scoring_configuration', None)
    if not callable(getter):
        raise ValueError('Scoring configuration storage is unavailable. Initialize the workspace database before calculating scoring.')
    payload = getter()
    if payload is None:
        raise ValueError('Import a Scoring Configuration before calculating scoring.')
    return validate_scoring_configuration(payload)


def _baseline_aliases(repository: Repository, baseline_operator: str) -> list[str]:
    aliases = [baseline_operator]
    getter = getattr(repository, 'list_operator_mapping_groups', None)
    groups = getter() if callable(getter) else []
    requested = baseline_operator.strip().casefold()
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        canonical = str(group.get('canonical') or '').strip()
        group_aliases = [str(value).strip() for value in group.get('aliases', []) if str(value).strip()]
        labels = [canonical, *group_aliases]
        if requested in {label.casefold() for label in labels if label}:
            aliases = [*labels, baseline_operator]
            break
    return list(dict.fromkeys(value for value in aliases if value))


def _decode_json(value: Any, default: Any) -> Any:
    try:
        decoded = json.loads(str(value or ''))
    except (TypeError, ValueError):
        return default
    return decoded


def _empty_context_filters() -> dict[str, list[str]]:
    return {field: [] for field in SCORING_CONTEXT_FILTER_FIELDS if field not in SCORING_OPTIONAL_CONTEXT_FILTERS}


def _normalize_context_filters(context_filters: dict[str, list[str]] | None) -> dict[str, list[str]]:
    """Normalize supported scoring filters while treating absent values as All."""
    normalized = _empty_context_filters()
    if context_filters is None:
        return normalized
    if not isinstance(context_filters, dict):
        raise ValueError('Scoring context filters must be an object keyed by Region, Cluster, City, Operator, Operator_Vendor, Vendor or Campaign.')

    fields_by_identity = {column_identity(field): field for field in SCORING_CONTEXT_FILTER_FIELDS}
    values_by_field: dict[str, dict[str, str]] = {field: {} for field in SCORING_CONTEXT_FILTER_FIELDS}
    for raw_field, raw_values in context_filters.items():
        field = fields_by_identity.get(column_identity(raw_field))
        if field is None:
            raise ValueError(f"Unsupported scoring context filter '{raw_field}'.")
        if raw_values is None:
            continue
        if isinstance(raw_values, str):
            values = [raw_values]
        elif isinstance(raw_values, (list, tuple, set)):
            values = list(raw_values)
        else:
            raise ValueError(f"Scoring context filter '{field}' must contain a list of values.")
        for raw_value in values:
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if value:
                values_by_field[field].setdefault(value.casefold(), value)

    for field, values in values_by_field.items():
        if values or field not in SCORING_OPTIONAL_CONTEXT_FILTERS:
            normalized[field] = sorted(values.values(), key=lambda value: (value.casefold(), value))
    return normalized


def _expand_operator_context_filter(
    repository: Repository, context_filters: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Include mapped Operator aliases so canonical selections match raw CDR rows."""
    expanded = {field: list(values) for field, values in context_filters.items()}
    selected = {value.casefold() for value in expanded.get('Operator', [])}
    getter = getattr(repository, 'list_operator_mapping_groups', None)
    groups = getter() if callable(getter) else []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        canonical = str(group.get('canonical') or '').strip()
        raw_aliases = group.get('aliases', [])
        aliases = [str(value).strip() for value in raw_aliases if str(value).strip()] if isinstance(raw_aliases, (list, tuple, set)) else []
        labels = [value for value in [canonical, *aliases] if value]
        if selected.intersection(value.casefold() for value in labels):
            for value in labels:
                selected.add(value.casefold())
                if not any(existing.casefold() == value.casefold() for existing in expanded['Operator']):
                    expanded['Operator'].append(value)
    expanded['Operator'].sort(key=lambda value: (value.casefold(), value))
    return expanded


def _expand_vendor_context_filters(
    repository: Repository, context_filters: dict[str, list[str]], catalogues: dict[int, dict[str, list[str]]],
) -> dict[str, list[str]]:
    """Include the source spellings of mapped Vendor and Operator_Vendor selections, as for Operators."""
    from src.modules.value_maps import ValueMapper

    settings_getter = getattr(repository, 'chart_mapping_settings', None)
    if not callable(settings_getter) or not any(context_filters.get(field) for field in ('Vendor', 'Operator_Vendor', 'Vendor_Operator')):
        return context_filters
    mapper = ValueMapper.from_settings(settings_getter())
    expanded = {field: list(values) for field, values in context_filters.items()}
    # Vendor_Operator is Operator_Vendor the other way round: it selects those values (both: their intersection).
    if expanded.get('Vendor_Operator'):
        wanted = mapper.operator_vendors(expanded['Vendor_Operator'])
        if expanded.get('Operator_Vendor'):
            chosen = {value.casefold() for value in expanded['Operator_Vendor']}
            wanted = [value for value in wanted if value.casefold() in chosen] or ['\u0000']
        expanded['Operator_Vendor'] = wanted
        expanded['Vendor_Operator'] = []
    for field, kind, key in (('Vendor', 'vendor', 'vendors_only'), ('Operator_Vendor', 'operator_vendor', 'vendors')):
        if expanded.get(field):
            sources = [value for catalogue in catalogues.values() for value in catalogue.get(key) or []]
            expanded[field] = sorted(mapper.expand(kind, expanded[field], sources), key=lambda value: (value.casefold(), value))
    return expanded


def _context_filter_cache_values(context_filters: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return the case-insensitive SQL semantics used to identify filter scopes."""
    values = {
        field: sorted({str(value).strip().casefold() for value in context_filters.get(field, []) if str(value).strip()})
        for field in SCORING_CONTEXT_FILTER_FIELDS
    }
    return {field: items for field, items in values.items() if items or field not in SCORING_OPTIONAL_CONTEXT_FILTERS}


def _serialize_result_value(value: Any) -> Any:
    """Convert pandas and NumPy scalars into strict JSON values."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_result_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_result_value(child) for child in value]
    item = getattr(value, 'item', None)
    if callable(item):
        try:
            return _serialize_result_value(item())
        except (TypeError, ValueError):
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _read_campaigns(repository: Repository, dataset_ids: list[int]) -> dict[int, list[str]]:
    if not dataset_ids:
        return {}
    with repository.connection() as connection:
        rows = connection.execute(
            f"SELECT dataset_id, campaigns_json FROM cdr_catalogues "
            f"WHERE dataset_id IN ({','.join('?' for _ in dataset_ids)})",
            dataset_ids,
        ).fetchall()
    campaigns: dict[int, list[str]] = {}
    for row in rows:
        values = _decode_json(row['campaigns_json'], [])
        if isinstance(values, list):
            campaigns[int(row['dataset_id'])] = [str(item).strip() for item in values if str(item).strip()]
    for dataset_id in dataset_ids:
        if not campaigns.get(int(dataset_id)):
            campaigns[int(dataset_id)] = repository.list_distinct_dataset_row_values(
                int(dataset_id), 'Campaign', limit=1000,
            )
    return campaigns


def _source_snapshot(
    repository: Repository,
    dataset_ids: list[int],
    *,
    expected_nr_mode: str | None = None,
) -> tuple[list[dict[str, Any]], dict[int, list[str]], str]:
    requested_ids = list(dict.fromkeys(int(dataset_id) for dataset_id in dataset_ids))
    if not requested_ids:
        raise ValueError('Select at least one processed CDR dataset.')
    requested_id_set = set(requested_ids)
    datasets_by_id = {
        int(row['id']): row for row in repository.list_datasets()
        if int(row['id']) in requested_id_set
    }
    missing = [dataset_id for dataset_id in requested_ids if dataset_id not in datasets_by_id]
    if missing:
        raise ValueError(f"Selected CDR dataset(s) no longer exist: {', '.join(map(str, missing))}.")

    expected_mode = normalize_nr_mode(expected_nr_mode) if expected_nr_mode else None
    if expected_nr_mode and expected_mode is None:
        raise ValueError('NR Mode must be NSA or SA.')
    campaigns_by_id = _read_campaigns(repository, requested_ids)
    sources: list[dict[str, Any]] = []
    for dataset_id in sorted(requested_ids):
        row = datasets_by_id[dataset_id]
        kind = str(row['dataset_kind'] or '').strip().casefold()
        if kind not in CDR_DATASET_KINDS:
            raise ValueError(f"Dataset '{row['file_name']}' is not a CDR Data, Voice or Speech dataset.")
        if str(row['status'] or '').casefold() != 'ready':
            raise ValueError(f"Dataset '{row['file_name']}' must finish processing before scoring.")
        nr_mode = normalize_nr_mode(row['nr_mode'])
        if nr_mode is None:
            raise ValueError(f"Dataset '{row['file_name']}' has no valid NR Mode.")
        if expected_mode and nr_mode != expected_mode:
            raise ValueError(f"Dataset '{row['file_name']}' does not match the selected {expected_mode} NR Mode.")
        table_name = repository.dataset_rows_table_name(dataset_id)
        if not repository.dataset_rows_table_exists(dataset_id):
            raise ValueError(f"Dataset '{row['file_name']}' has no processed row table.")
        columns = repository.list_dataset_row_columns(dataset_id)
        row_count = repository.dataset_row_count(dataset_id)
        if row_count < 1:
            raise ValueError(f"Dataset '{row['file_name']}' has no processed rows to score.")
        campaigns = campaigns_by_id.get(dataset_id, [])
        metadata = {
            'dataset_id': dataset_id,
            'name': str(row['file_name'] or ''),
            'kind': kind,
            'nr_mode': nr_mode,
            'campaigns': campaigns,
            'row_count': row_count,
        }
        # Scores are based on the persisted materialization. Keep the cache
        # stable when a workspace is copied or restored and its file paths or
        # dataset IDs change, while profile timestamps capture supported row
        # replacements and Database Management edits.
        signature = {
            'name': metadata['name'],
            'kind': kind,
            'nr_mode': nr_mode,
            'processed_at': str(row['processed_at'] or ''),
            'profile_updated_at': str(row['updated_at'] or ''),
            'normalization_version': int(row['normalization_version'] or 1),
            'vendor_mapping_applied': int(row['vendor_mapping_applied'] or 0),
            'region_mapping_applied': int(row['region_mapping_applied'] or 0),
            'row_count': row_count,
            'columns': columns,
            'campaigns': campaigns,
        }
        sources.append({'metadata': metadata, 'signature': signature, 'columns': columns, 'table_name': table_name})

    modes = {str(source['metadata']['nr_mode']) for source in sources}
    if len(modes) != 1:
        raise ValueError('Select CDR datasets with the same NR Mode.')
    if expected_mode and modes != {expected_mode}:
        raise ValueError(f'Selected CDR datasets do not all match {expected_mode}.')
    source_fingerprint_payload = sorted(
        (source['signature'] for source in sources),
        key=lambda signature: json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
    )
    source_fingerprint = hashlib.sha256(
        json.dumps(source_fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    return sources, campaigns_by_id, source_fingerprint


def validate_complete_scoring_cdr_selection(
    repository: Repository,
    dataset_ids: list[int],
    nr_mode: str | None,
    context_filters: dict[str, list[str]] | None = None,
) -> list[int]:
    """Validate that a requested run has complete Data, Voice and Speech coverage."""
    normalized_ids = list(dict.fromkeys(int(dataset_id) for dataset_id in dataset_ids))
    normalized_filters = _normalize_context_filters(context_filters)
    sources, _campaigns, _fingerprint = _source_snapshot(
        repository, normalized_ids, expected_nr_mode=nr_mode,
    )
    kinds = {str(source['metadata']['kind']) for source in sources}
    missing_kinds = [kind for kind in ('data', 'voice', 'speech') if kind not in kinds]
    if missing_kinds:
        labels = {'data': 'Data', 'voice': 'Voice', 'speech': 'Speech'}
        missing_label = ', '.join(labels[kind] for kind in missing_kinds)
        raise ValueError(
            'Scoring requires at least one processed Data, Voice and Speech CDR dataset. '
            f'Missing: {missing_label}.'
        )

    campaigns_by_kind: dict[str, set[str]] = {kind: set() for kind in CDR_DATASET_KINDS}
    labels = {'data': 'Data', 'voice': 'Voice', 'speech': 'Speech'}
    for source in sources:
        metadata = source['metadata']
        campaigns_by_kind[str(metadata['kind'])].update(
            str(campaign).strip() for campaign in metadata.get('campaigns', []) if str(campaign).strip()
        )
    selected_campaigns = normalized_filters['Campaign']
    if selected_campaigns:
        campaigns_to_check = selected_campaigns
    else:
        campaigns_to_check = sorted(
            set().union(*campaigns_by_kind.values()), key=lambda value: (value.casefold(), value),
        )
    kind_order = ('data', 'voice', 'speech')
    uncovered = []
    for campaign in campaigns_to_check:
        campaign_key = campaign.casefold()
        missing = [
            labels[kind] for kind in kind_order
            if not any(value.casefold() == campaign_key for value in campaigns_by_kind[kind])
        ]
        if missing:
            uncovered.append(f"{campaign} ({', '.join(missing)})")
    if uncovered:
        raise ValueError(
            'Selected CDR datasets must cover each campaign with Data, Voice and Speech. '
            f'Missing campaign coverage: {"; ".join(uncovered)}.'
        )
    return normalized_ids


def select_all_complete_cdrs(repository: Repository, nr_mode: str) -> list[int]:
    """Every ready CDR of the NR Mode whose campaigns all have Data, Voice and Speech CDRs."""
    mode = normalize_nr_mode(nr_mode)
    candidates = [
        row for row in repository.list_datasets()
        if str(row['status'] or '').casefold() == 'ready'
        and str(row['dataset_kind'] or '').strip().casefold() in CDR_DATASET_KINDS
        and normalize_nr_mode(row['nr_mode']) == mode
        and repository.dataset_rows_table_exists(int(row['id']))
        and repository.dataset_row_count(int(row['id'])) > 0
    ]
    campaign_index = _read_campaigns(repository, [int(row['id']) for row in candidates])
    # CDRs without a Campaign form their own set, complete when every type has one.
    campaigns_of = {
        int(row['id']): {str(campaign).strip().casefold() for campaign in campaign_index.get(int(row['id']), [])
                         if str(campaign).strip()} or {''}
        for row in candidates
    }
    by_kind: dict[str, set[str]] = {kind: set() for kind in ('data', 'voice', 'speech')}
    for row in candidates:
        by_kind[str(row['dataset_kind']).strip().casefold()].update(campaigns_of[int(row['id'])])
    complete = by_kind['data'] & by_kind['voice'] & by_kind['speech']
    selected = sorted(int(row['id']) for row in candidates if campaigns_of[int(row['id'])] <= complete)
    if not selected:
        raise ValueError(f'There is no complete set of Data, Voice and Speech CDRs in {mode} NR Mode.')
    return validate_complete_scoring_cdr_selection(repository, selected, mode)


def select_latest_companion_cdrs(repository: Repository, dataset_id: int) -> list[int]:
    """Pair a newly processed CDR with the newest compatible CDRs for every type."""
    anchor_id = int(dataset_id)
    anchor_sources, _anchor_campaigns, _fingerprint = _source_snapshot(repository, [anchor_id])
    anchor = anchor_sources[0]['metadata']
    anchor_kind = str(anchor['kind'])
    anchor_mode = str(anchor['nr_mode'])
    target_campaigns = {
        str(campaign).strip() for campaign in anchor.get('campaigns', []) if str(campaign).strip()
    }

    candidates = [
        row for row in repository.list_datasets()
        if str(row['status'] or '').casefold() == 'ready'
        and str(row['dataset_kind'] or '').strip().casefold() in CDR_DATASET_KINDS
        and normalize_nr_mode(row['nr_mode']) == anchor_mode
        and repository.dataset_rows_table_exists(int(row['id']))
        and repository.dataset_row_count(int(row['id'])) > 0
    ]
    campaign_index = _read_campaigns(repository, [int(row['id']) for row in candidates])
    candidates.sort(key=lambda row: (str(row['uploaded_at'] or ''), int(row['id'])), reverse=True)
    selected_ids = [anchor_id]

    labels = {'data': 'Data', 'voice': 'Voice', 'speech': 'Speech'}
    for kind in ('data', 'voice', 'speech'):
        if kind == anchor_kind:
            continue
        compatible: list[Any] = []
        for row in candidates:
            if str(row['dataset_kind'] or '').strip().casefold() != kind:
                continue
            campaigns = set(campaign_index.get(int(row['id']), []))
            if (target_campaigns and campaigns <= target_campaigns) or (not target_campaigns and not campaigns):
                compatible.append(row)

        if target_campaigns:
            for campaign in sorted(target_campaigns, key=str.casefold):
                match = next((
                    row for row in compatible
                    if campaign in campaign_index.get(int(row['id']), [])
                ), None)
                if match is None:
                    raise ValueError(
                        f"No processed {labels[kind]} CDR in {anchor_mode} NR Mode covers campaign '{campaign}'."
                    )
                selected_id = int(match['id'])
                if selected_id not in selected_ids:
                    selected_ids.append(selected_id)
        elif compatible:
            selected_ids.append(int(compatible[0]['id']))
        else:
            raise ValueError(
                f'No processed {labels[kind]} CDR in {anchor_mode} NR Mode has matching campaign coverage.'
            )

    return validate_complete_scoring_cdr_selection(repository, selected_ids, anchor_mode)


def _normalize_levels(
    levels: Iterable[object], sources: list[dict[str, Any]],
    aggregation_hierarchy: Iterable[object] = DEFAULT_AGGREGATION_HIERARCHY,
) -> list[str]:
    raw_levels = [str(level).strip() for level in levels if str(level).strip()]
    if not any(column_identity(level) == 'operator' for level in raw_levels):
        raw_levels.append('Operator')
    available_columns = list(dict.fromkeys(
        str(column) for source in sources for column in source['columns']
    ))
    resolved_levels: list[str] = []
    seen: set[str] = set()
    for requested in raw_levels:
        requested_identity = column_identity(requested)
        if requested_identity == 'operator':
            resolved = 'Operator'
        elif requested_identity in {'datasettype', 'datasetkind'}:
            resolved = 'Dataset Type' if resolve_column_name(available_columns, 'Dataset_Kind') else None
        elif requested_identity in {'ranvendor', 'vendor'}:
            resolved = 'Vendor' if resolve_column_name(available_columns, 'Vendor') else None
        elif requested_identity in {'region', 'city'}:
            canonical = 'Region' if requested_identity == 'region' else 'City'
            aliases = ('Region', 'g_level_2') if canonical == 'Region' else ('City', 'g_level_4')
            resolved = canonical if any(resolve_column_name(available_columns, alias) for alias in aliases) else None
        elif requested_identity == 'cluster':
            resolved = 'Cluster' if resolve_column_name(available_columns, 'Cluster') else None
        elif requested_identity == 'campaign':
            resolved = resolve_column_name(available_columns, 'Campaign')
        else:
            resolved = None
        if not resolved:
            raise ValueError(f"Aggregation level '{requested}' is not available in the selected CDR datasets.")
        resolved_identity = column_identity(resolved)
        if resolved_identity not in seen:
            resolved_levels.append(resolved)
            seen.add(resolved_identity)
    hierarchy_order = {
        column_identity(field): index
        for index, field in enumerate(complete_aggregation_hierarchy(list(aggregation_hierarchy)))
    }
    resolved_levels.sort(key=lambda value: (
        hierarchy_order.get(column_identity(value), len(hierarchy_order)), value.casefold(),
    ))
    operator_sources = [source for source in sources if resolve_column_name(source['columns'], 'Operator') is None]
    if operator_sources:
        names = ', '.join(str(source['metadata']['name']) for source in operator_sources)
        raise ValueError(f'Operator is required for scoring and is missing from: {names}.')
    return resolved_levels


def _job_payload(
    levels: list[str], nr_mode: str, baseline_operator: str,
    method_version: str, source_fingerprint: str, config_hash: str = '',
    baseline_aliases: list[str] | None = None,
    context_filters: dict[str, list[str]] | None = None,
    resolved_context_filters: dict[str, list[str]] | None = None,
    operator_mappings: dict[str, str] | None = None,
    scoring_profile_id: str = '',
    scoring_profile_name: str = '',
) -> tuple[str, str]:
    key_payload = {
        'method_version': method_version,
        'configuration_hash': config_hash,
        'baseline_aliases': sorted(set(baseline_aliases or [baseline_operator]), key=str.casefold),
        'source_fingerprint': source_fingerprint,
        'levels': levels,
        'nr_mode': nr_mode,
        'baseline_operator': baseline_operator,
        'aggregation_contract_version': AGGREGATION_CONTRACT_VERSION,
        'operator_mappings': {
            str(alias).strip().casefold(): str(canonical).strip()
            for alias, canonical in sorted((operator_mappings or {}).items(), key=lambda item: str(item[0]).casefold())
            if str(alias).strip() and str(canonical).strip()
        },
    }
    if scoring_profile_id:
        key_payload['scoring_profile_id'] = scoring_profile_id
    if scoring_profile_name:
        key_payload['scoring_profile_name'] = scoring_profile_name
    normalized_filters = _normalize_context_filters(context_filters)
    resolved_filters = _normalize_context_filters(resolved_context_filters or context_filters)
    if any(normalized_filters.values()):
        key_payload['context_filters'] = _context_filter_cache_values(normalized_filters)
        key_payload['resolved_context_filters'] = _context_filter_cache_values(resolved_filters)
    canonical = json.dumps(key_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest(), canonical


def _row_to_job(
    row: Any, *, include_result: bool = False, include_snapshot: bool = True,
    include_internal_snapshot: bool = False,
) -> dict[str, Any]:
    if row is None:
        raise ValueError('Scoring job was not found.')
    source_metadata_payload = _decode_json(row['source_metadata_json'], [])
    dataset_ids = _decode_json(row['dataset_ids_json'], [])
    levels = _decode_json(row['levels_json'], [])
    result = _decode_json(row['result_json'], None) if include_result else None
    if isinstance(source_metadata_payload, dict):
        metadata_list = source_metadata_payload.get('sources', [])
        configuration_payload = source_metadata_payload.get('configuration')
        scoring_profile_id = str(source_metadata_payload.get('scoring_profile_id') or '')
        scoring_profile_name = str(source_metadata_payload.get('scoring_profile_name') or '')
        baseline_aliases = source_metadata_payload.get('baseline_aliases', [])
        context_filters = source_metadata_payload.get('context_filters', {})
        resolved_context_filters = source_metadata_payload.get('resolved_context_filters', context_filters)
        aggregation_hierarchy = source_metadata_payload.get('aggregation_hierarchy', [])
        aggregation_contract_version = source_metadata_payload.get('aggregation_contract_version', 1)
        operator_mappings = source_metadata_payload.get('operator_mappings', {})
    else:
        metadata_list = source_metadata_payload if isinstance(source_metadata_payload, list) else []
        configuration_payload = None
        scoring_profile_id = ''
        scoring_profile_name = ''
        baseline_aliases = []
        context_filters = {}
        resolved_context_filters = {}
        aggregation_hierarchy = []
        aggregation_contract_version = 1
        operator_mappings = {}
    if not isinstance(context_filters, dict):
        context_filters = {}
    if not isinstance(resolved_context_filters, dict):
        resolved_context_filters = context_filters
    if not isinstance(aggregation_hierarchy, list):
        aggregation_hierarchy = []
    if not isinstance(operator_mappings, dict):
        operator_mappings = {}
    try:
        aggregation_contract_version = max(1, int(aggregation_contract_version))
    except (TypeError, ValueError):
        aggregation_contract_version = 1
    if not isinstance(metadata_list, list):
        metadata_list = []
    if include_snapshot:
        if configuration_payload is None and isinstance(result, dict):
            configuration_payload = result.get('configuration')
        if _is_legacy_two_environment_configuration(configuration_payload):
            configuration = configuration_payload
        else:
            configuration = validate_scoring_configuration(configuration_payload) if configuration_payload is not None else None
    else:
        configuration = None
    if isinstance(result, dict):
        if configuration is not None:
            result.setdefault('configuration', configuration)
    baseline = str(row['baseline_operator'] or DEFAULT_BASELINE_OPERATOR)
    baseline_aliases = list(dict.fromkeys(
        [baseline, *(str(alias).strip() for alias in baseline_aliases if str(alias).strip())]
    )) if include_snapshot else []
    job = {
        'id': int(row['id']),
        'cache_key': str(row['cache_key'] or ''),
        'method_version': str(row['method_version'] or ''),
        'source_fingerprint': str(row['source_fingerprint'] or ''),
        'dataset_ids': [int(value) for value in dataset_ids if str(value).strip().lstrip('-').isdigit()],
        'source_metadata': metadata_list,
        'context_filters': {
            str(field): [str(value) for value in values if str(value).strip()]
            for field, values in context_filters.items()
            if isinstance(values, (list, tuple, set))
        },
        'aggregation_hierarchy': [str(value) for value in aggregation_hierarchy if str(value).strip()],
        'aggregation_contract_version': aggregation_contract_version,
        'dataset_names': [str(item.get('name') or '') for item in metadata_list if isinstance(item, dict)],
        'campaigns': sorted({
            str(campaign).strip()
            for item in metadata_list if isinstance(item, dict)
            for campaign in item.get('campaigns', []) if str(campaign).strip()
        }, key=campaign_sort_key),
        'nr_mode': str(row['nr_mode'] or ''),
        'levels': [str(value) for value in levels if str(value).strip()],
        'aggregation_levels': [str(value) for value in levels if str(value).strip()],
        'baseline_operator': str(row['baseline_operator'] or DEFAULT_BASELINE_OPERATOR),
        'scoring_profile_id': scoring_profile_id,
        'scoring_profile_name': scoring_profile_name,
        'status': str(row['status'] or 'queued'),
        'progress': max(0, min(100, int(row['progress'] or 0))),
        'message': str(row['message'] or ''),
        'error': str(row['last_error'] or ''),
        'created_by': str(row['created_by'] or 'system'),
        'created_at': str(row['created_at'] or ''),
        'started_at': str(row['started_at'] or ''),
        'updated_at': str(row['updated_at'] or ''),
        'finished_at': str(row['finished_at'] or ''),
        'result': result,
    }
    if include_snapshot:
        job['configuration'] = configuration
        job['baseline_aliases'] = baseline_aliases
    if include_internal_snapshot:
        job['resolved_context_filters'] = {
            str(field): [str(value) for value in values if str(value).strip()]
            for field, values in resolved_context_filters.items()
            if isinstance(values, (list, tuple, set))
        }
        job['operator_mappings'] = {
            str(alias).strip().casefold(): str(canonical).strip()
            for alias, canonical in operator_mappings.items()
            if str(alias).strip() and str(canonical).strip()
        }
    return job


def _prepare_scoring_job(
    repository: Repository,
    dataset_ids: list[int],
    levels: list[str],
    nr_mode: str | None,
    *,
    baseline_operator: str = DEFAULT_BASELINE_OPERATOR,
    context_filters: dict[str, list[str]] | None = None,
    scoring_profile_id: str | None = None,
) -> tuple[str, str, str, list[int], dict[str, Any], str, list[str], str]:
    """Prepare the canonical identity and snapshot shared by matching and submission."""
    normalized_ids = list(dict.fromkeys(int(dataset_id) for dataset_id in dataset_ids))
    normalized_context_filters = _normalize_context_filters(context_filters)
    vendor_catalogues = repository.cdr_catalogues_by_dataset(normalized_ids)
    vendor_operators = scoring_vendor_operators(vendor_catalogues, repository.list_operator_mapping_groups())
    normalized_context_filters['Vendor'] = sorted({
        scoring_vendor_name(value, vendor_operators) for value in normalized_context_filters['Vendor']
    }, key=str.casefold)
    resolved_context_filters = _expand_operator_context_filter(repository, normalized_context_filters)
    resolved_context_filters = _expand_vendor_context_filters(repository, resolved_context_filters, vendor_catalogues)
    profile_getter = getattr(repository, 'get_scoring_profile', None)
    if callable(profile_getter):
        if scoring_profile_id is None or (
            isinstance(scoring_profile_id, str) and not scoring_profile_id.strip()
        ):
            scoring_profile = profile_getter()
        else:
            if not isinstance(scoring_profile_id, str):
                raise ValueError('Scoring methodology ID must be a non-empty identifier.')
            scoring_profile = profile_getter(scoring_profile_id.strip())
        configuration = validate_scoring_configuration(scoring_profile['configuration'])
    else:
        if scoring_profile_id is not None:
            raise ValueError('This workspace does not support selecting scoring methodologies for a job.')
        configuration = _workspace_scoring_configuration(repository)
        scoring_profile = {'id': '', 'name': ''}
    sources, _campaigns, source_fingerprint = _source_snapshot(
        repository, normalized_ids, expected_nr_mode=nr_mode,
    )
    aggregation_hierarchy = load_aggregation_hierarchy(repository)
    normalized_levels = _normalize_levels(levels, sources, aggregation_hierarchy)
    selected_mode = normalize_nr_mode(nr_mode) if nr_mode else str(sources[0]['metadata']['nr_mode'])
    if selected_mode not in NR_MODES:
        raise ValueError('NR Mode must be NSA or SA.')
    baseline = str(baseline_operator or '').strip()
    if not baseline:
        raise ValueError('Select a comparison baseline operator.')
    baseline_aliases = _baseline_aliases(repository, baseline)
    mapping_getter = getattr(repository, 'list_operator_mappings', None)
    raw_operator_mappings = mapping_getter() if callable(mapping_getter) else {}
    operator_mappings = {
        str(alias).strip().casefold(): str(canonical).strip()
        for alias, canonical in raw_operator_mappings.items()
        if str(alias).strip() and str(canonical).strip()
    } if isinstance(raw_operator_mappings, dict) else {}
    config_hash = configuration_hash(configuration)
    version = _method_version(configuration)
    cache_key, _canonical = _job_payload(
        normalized_levels, selected_mode, baseline, version, source_fingerprint, config_hash, baseline_aliases,
        normalized_context_filters, resolved_context_filters, operator_mappings,
        str(scoring_profile.get('id') or ''), str(scoring_profile.get('name') or ''),
    )
    source_metadata = [source['metadata'] for source in sources]
    source_snapshot = {
        'sources': source_metadata,
        'configuration': configuration,
        'scoring_profile_id': str(scoring_profile.get('id') or ''),
        'scoring_profile_name': str(scoring_profile.get('name') or ''),
        'baseline_aliases': baseline_aliases,
        'context_filters': normalized_context_filters,
        'resolved_context_filters': resolved_context_filters,
        'aggregation_hierarchy': list(aggregation_hierarchy),
        'aggregation_contract_version': AGGREGATION_CONTRACT_VERSION,
        'operator_mappings': operator_mappings,
    }
    return (cache_key, version, source_fingerprint, normalized_ids, source_snapshot,
            selected_mode, normalized_levels, baseline)


def _matching_saved_job(connection: Any, cache_key: str, version: str,
                        dataset_ids: list[int], source_fingerprint: str) -> Any:
    """Match saved inputs even when an engine upgrade changed their cache digest."""
    rows = connection.execute(
        "SELECT * FROM scoring_jobs WHERE cache_key = ? OR source_fingerprint = ? "
        "ORDER BY status IN ('queued', 'processing') DESC, id DESC",
        (cache_key, source_fingerprint),
    ).fetchall()
    for row in rows:
        if row['cache_key'] == cache_key:
            return row
        try:
            job = _row_to_job(row, include_internal_snapshot=True)
            if sorted(job['dataset_ids']) != sorted(dataset_ids) or not job.get('configuration'):
                continue
            saved_key, _ = _job_payload(
                job['levels'], job['nr_mode'], job['baseline_operator'], version,
                job['source_fingerprint'], configuration_hash(job['configuration']),
                job['baseline_aliases'], job['context_filters'], job['resolved_context_filters'],
                job['operator_mappings'], job['scoring_profile_id'], job['scoring_profile_name'],
            )
        except (ValueError, TypeError, KeyError):
            continue
        if saved_key == cache_key:
            return row
    return None


def find_matching_scoring_job(
    repository: Repository, dataset_ids: list[int], levels: list[str], nr_mode: str | None,
    *, baseline_operator: str = DEFAULT_BASELINE_OPERATOR,
    context_filters: dict[str, list[str]] | None = None,
    scoring_profile_id: str | None = None,
) -> dict[str, Any] | None:
    """Find a saved calculation using the same identity as job submission."""
    cache_key, version, source_fingerprint, normalized_ids, *_ = _prepare_scoring_job(
        repository, dataset_ids, levels, nr_mode, baseline_operator=baseline_operator,
        context_filters=context_filters, scoring_profile_id=scoring_profile_id,
    )
    with repository.connection() as connection:
        row = _matching_saved_job(connection, cache_key, version, normalized_ids, source_fingerprint)
    return _row_to_job(row, include_snapshot=False) if row else None


def create_scoring_job(
    repository: Repository,
    dataset_ids: list[int],
    levels: list[str],
    nr_mode: str | None,
    *,
    baseline_operator: str = DEFAULT_BASELINE_OPERATOR,
    force: bool = False,
    username: str = 'system',
    context_filters: dict[str, list[str]] | None = None,
    scoring_profile_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Reuse a matching result, requeue the existing job, or create a new calculation."""
    (cache_key, version, source_fingerprint, normalized_ids, source_snapshot,
     selected_mode, normalized_levels, baseline) = _prepare_scoring_job(
        repository, dataset_ids, levels, nr_mode, baseline_operator=baseline_operator,
        context_filters=context_filters, scoring_profile_id=scoring_profile_id,
    )
    now = local_now_iso()
    with repository.connection() as connection:
        connection.execute('BEGIN IMMEDIATE')
        if not force:
            cached_row = connection.execute(
                "SELECT * FROM scoring_jobs WHERE cache_key = ? AND status = 'completed' "
                'AND result_json IS NOT NULL ORDER BY id DESC LIMIT 1',
                (cache_key,),
            ).fetchone()
            if cached_row:
                return _row_to_job(cached_row, include_result=True), True
        active_row = connection.execute(
            "SELECT * FROM scoring_jobs WHERE cache_key = ? AND status IN ('queued', 'processing') "
            'ORDER BY id DESC LIMIT 1',
            (cache_key,),
        ).fetchone()
        if active_row:
            return _row_to_job(active_row), True
        previous_row = _matching_saved_job(connection, cache_key, version, normalized_ids, source_fingerprint)
        if previous_row and previous_row['status'] in ('queued', 'processing'):
            return _row_to_job(previous_row), True
        if previous_row:
            connection.execute(
                """UPDATE scoring_jobs SET status = 'queued', progress = 0,
                   message = 'Waiting to calculate scoring', result_json = NULL,
                   last_error = NULL, started_at = NULL, finished_at = NULL,
                   created_at = ?, updated_at = ?, created_by = ?, source_metadata_json = ?,
                   cache_key = ?, method_version = ?
                   WHERE id = ?""",
                (now, now, str(username or 'system'),
                 json.dumps(source_snapshot, ensure_ascii=False, separators=(',', ':')),
                 cache_key, version, previous_row['id']),
            )
            job = connection.execute('SELECT * FROM scoring_jobs WHERE id = ?', (previous_row['id'],)).fetchone()
            return _row_to_job(job), False
        cursor = connection.execute(
            """
            INSERT INTO scoring_jobs (
                cache_key, method_version, source_fingerprint, dataset_ids_json,
                source_metadata_json, nr_mode, levels_json, baseline_operator,
                status, progress, message, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, 'Waiting to calculate scoring', ?, ?, ?)
            """,
            (
                cache_key, version, source_fingerprint, json.dumps(normalized_ids),
                json.dumps(source_snapshot, ensure_ascii=False, separators=(',', ':')), selected_mode,
                json.dumps(normalized_levels, ensure_ascii=False), baseline,
                str(username or 'system'), now, now,
            ),
        )
        job_id = int(cursor.lastrowid)
        job = connection.execute('SELECT * FROM scoring_jobs WHERE id = ?', (job_id,)).fetchone()
    return _row_to_job(job), False


def list_scoring_jobs(repository: Repository) -> list[dict[str, Any]]:
    """Return all scoring job summaries without loading result payloads."""
    with repository.connection() as connection:
        rows = connection.execute(
            'SELECT id, cache_key, method_version, source_fingerprint, dataset_ids_json, '
            'source_metadata_json, nr_mode, levels_json, baseline_operator, status, progress, '
            'message, last_error, created_by, created_at, started_at, updated_at, finished_at '
            'FROM scoring_jobs ORDER BY julianday(created_at) DESC, id DESC'
        ).fetchall()
    return [_row_to_job(row, include_snapshot=False) for row in rows]


def recover_interrupted_scoring_jobs(repository: Repository) -> list[int]:
    """Fail persisted scoring work when its workspace is first opened after restart."""
    now = local_now_iso()
    with repository.connection() as connection:
        rows = connection.execute(
            "SELECT id FROM scoring_jobs WHERE status IN ('queued', 'processing') ORDER BY id",
        ).fetchall()
        job_ids = [int(row['id']) for row in rows]
        if job_ids:
            placeholders = ','.join('?' for _ in job_ids)
            connection.execute(
                f"UPDATE scoring_jobs SET status = 'failed', last_error = ?, message = ?, updated_at = ?, finished_at = ? "
                f"WHERE id IN ({placeholders}) AND status IN ('queued', 'processing')",
                (INTERRUPTED_JOB_MESSAGE, INTERRUPTED_JOB_MESSAGE, now, now, *job_ids),
            )
    return job_ids


def get_scoring_job(
    repository: Repository, job_id: int, include_result: bool = False,
    include_internal_snapshot: bool = False,
) -> dict[str, Any] | None:
    """Return a job and optionally decode its persisted scoring tables."""
    with repository.connection() as connection:
        row = connection.execute('SELECT * FROM scoring_jobs WHERE id = ?', (int(job_id),)).fetchone()
    if row is None:
        return None
    job = _row_to_job(
        row, include_result=include_result, include_internal_snapshot=include_internal_snapshot,
    )
    if include_result and not include_internal_snapshot:
        _apply_current_environment_labels(repository, job)
        # Results saved before environment scaling existed are scaled when they are opened.
        from src.modules.scoring import apply_environment_scaling
        apply_environment_scaling(job.get('result'), str(job.get('baseline_operator') or 'EE'))
    return job


def _apply_current_environment_labels(repository: Repository, job: dict[str, Any]) -> None:
    """Project current profile labels without changing stored rules or environment keys."""
    try:
        profile = repository.get_scoring_profile(job.get('scoring_profile_id') or None)
    except ValueError:
        return
    current = profile['configuration'].get('scope', {}).get('environments', {})

    def source_identity(scope: dict[str, Any]) -> tuple[str, str]:
        filters = scope.get('source_filters') or {}
        first = str(filters.get('G_Level_1') or scope.get('g_level_1') or '').strip().casefold()
        second = str(filters.get('G_Level_2') or scope.get('g_level_2') or '').strip().casefold()
        if second in {'connectionroad', 'connectingroads', 'connecting roads'}:
            second = 'connecting roads'
        return first, second

    labels = {source_identity(scope): str(scope.get('display_name') or name)
              for name, scope in current.items()}
    for configuration in (job.get('configuration'), (job.get('result') or {}).get('configuration')):
        if not isinstance(configuration, dict):
            continue
        for name, scope in configuration.get('scope', {}).get('environments', {}).items():
            identity = source_identity(scope)
            label = labels.get(identity) if identity[0] else None
            if label and label != str(scope.get('display_name') or name):
                scope['display_name'] = label


def delete_scoring_job(repository: Repository, job_id: int) -> bool:
    """Remove a saved job and its result without modifying source CDRs."""
    with repository.connection() as connection:
        cursor = connection.execute('DELETE FROM scoring_jobs WHERE id = ?', (int(job_id),))
        return cursor.rowcount > 0


class _ScoringJobDeleted(Exception):
    """Stop further processing at a checkpoint after a job is removed."""


def _update_scoring_job(repository: Repository, job_id: int, **fields: Any) -> None:
    allowed_fields = {
        'status', 'progress', 'message', 'result_json', 'last_error', 'started_at', 'finished_at',
    }
    updates = {key: value for key, value in fields.items() if key in allowed_fields}
    if not updates:
        return
    updates['updated_at'] = local_now_iso()
    assignments = ', '.join(f'"{column}" = ?' for column in updates)
    values = [updates[column] for column in updates]
    with repository.connection() as connection:
        connection.execute(
            f"UPDATE scoring_jobs SET {assignments} WHERE id = ? AND status <> 'stopped'",
            (*values, int(job_id)),
        )


def _load_source_frames(
    repository: Repository, sources: list[dict[str, Any]], progress_callback, required_columns,
    context_filters: dict[str, list[str]] | None = None,
) -> dict[str, pd.DataFrame]:
    frames_by_kind: dict[str, list[pd.DataFrame]] = {}
    normalized_filters = _normalize_context_filters(context_filters)
    active_filters = {field: values for field, values in normalized_filters.items() if values}
    catalogues = repository.cdr_catalogues_by_dataset([int(source['metadata']['dataset_id']) for source in sources])
    vendor_operators = scoring_vendor_operators(catalogues, repository.list_operator_mapping_groups())
    total = max(1, len(sources))
    for index, source in enumerate(sources, start=1):
        dataset_id = int(source['metadata']['dataset_id'])
        if active_filters.get('Vendor'):
            repository.ensure_vendor_column(dataset_id)
        columns = repository.list_dataset_row_columns(dataset_id)
        requested = required_columns(str(source['metadata']['kind']), source['levels'])
        if any(column_identity(level) == 'datasettype' for level in source['levels']):
            requested = [*requested, 'Dataset_Kind']
        requested = [
            'Dataset_Kind' if column_identity(name) == 'datasettype' else name
            for name in requested
        ]
        selected_columns = [
            resolved for name in requested
            if (resolved := resolve_column_name(columns, name)) is not None
        ]
        dataset_filters: dict[str, list[str]] = {}
        missing_filter_fields = []
        for field, values in active_filters.items():
            resolved_filter_column = next((
                resolved for candidate in SCORING_CONTEXT_FILTER_COLUMNS[field]
                if (resolved := resolve_column_name(columns, candidate)) is not None
            ), None)
            if resolved_filter_column is None:
                missing_filter_fields.append(field)
            else:
                if field == 'Vendor':
                    values = [scoring_vendor_name(value, vendor_operators) for value in values]
                dataset_filters[resolved_filter_column] = values
        if missing_filter_fields:
            frame = pd.DataFrame()
        else:
            frame = repository.load_dataset_rows(
                dataset_id, list(dict.fromkeys(selected_columns)), dataset_filters,
            )
        if frame.empty:
            if not active_filters:
                raise ValueError(f"Dataset '{source['metadata']['name']}' has no rows available for scoring.")
            progress_callback(10 + round(index * 45 / total), f"Skipped {source['metadata']['name']} with no matching rows")
            continue
        kind = str(source['metadata']['kind'])
        frames_by_kind.setdefault(kind, []).append(frame)
        progress_callback(10 + round(index * 45 / total), f"Loaded {source['metadata']['name']}")

    if active_filters:
        labels = {'data': 'Data', 'voice': 'Voice', 'speech': 'Speech'}
        missing_kinds = [kind for kind in ('data', 'voice', 'speech') if not frames_by_kind.get(kind)]
        if missing_kinds:
            missing_labels = ', '.join(labels[kind] for kind in missing_kinds)
            raise ValueError(
                'Scoring context filters leave no matching processed rows for every required CDR type. '
                f'Missing: {missing_labels}.'
            )
    return {
        kind: pd.concat(frames, ignore_index=True, sort=False)
        for kind, frames in frames_by_kind.items()
    }


def _attach_mapping_boundaries(repository: Repository, dataset_ids: list[int], result: dict[str, Any]) -> None:
    """Save the Clusters and Region Mapping polygons applied to the CDRs for the points-lost maps."""
    document = result.get('points_loss')
    if not isinstance(document, dict):
        return
    from src.modules.scoring_points_loss import mapping_boundaries

    rows = {int(row['id']): row for row in repository.list_datasets()}
    boundaries = {}
    for field, applied, mapping in (('Cluster', 'cluster_mapping_applied', 'cluster_mapping_dataset_id'),
                                    ('Region', 'region_mapping_applied', 'region_mapping_dataset_id')):
        mapping_ids = [rows[dataset_id][mapping] for dataset_id in dataset_ids
                       if dataset_id in rows and rows[dataset_id][applied] and rows[dataset_id][mapping]]
        mapping_row = rows.get(int(mapping_ids[-1])) if mapping_ids else None
        if mapping_row is None or not mapping_row['stored_path']:
            continue
        try:
            polygons = mapping_boundaries(Path(str(mapping_row['stored_path'])), field)
        except Exception:  # The map is optional; a missing or unreadable mapping file only drops its polygons.
            continue
        if polygons:
            boundaries[field] = polygons
    if boundaries:
        document['boundaries'] = boundaries


def run_scoring_job(repository: Repository, job_id: int) -> dict[str, Any] | None:
    """Calculate one queued job, persist its result, and retain failures for review."""
    job = get_scoring_job(repository, job_id, include_internal_snapshot=True)
    if job is None:
        return None
    if job['status'] == 'completed':
        return get_scoring_job(repository, job_id, include_result=True)
    if job['status'] == 'stopped':
        return job
    if job['status'] == 'processing':
        return job
    now = local_now_iso()
    _update_scoring_job(
        repository, job_id, status='processing', progress=2,
        message='Checking selected CDR datasets', last_error='', started_at=now,
    )

    def update_progress(progress: int, message: str) -> None:
        if get_scoring_job(repository, job_id) is None:
            raise _ScoringJobDeleted()
        _update_scoring_job(
            repository, job_id, progress=max(2, min(95, int(progress))), message=message,
        )

    try:
        configuration = job.get('configuration')
        if configuration is None:
            raise ValueError(
                'This scoring job has no saved configuration snapshot. Import a Scoring Configuration and create a new scoring job.'
            )
        current_version = _method_version(configuration)
        if current_version != job['method_version']:
            raise ValueError('The scoring methodology changed after this job was queued. Create a new scoring job.')
        configuration = validate_scoring_configuration(configuration)
        dataset_ids = [int(value) for value in job['dataset_ids']]
        sources, _campaigns, current_fingerprint = _source_snapshot(
            repository, dataset_ids, expected_nr_mode=job['nr_mode'],
        )
        if current_fingerprint != job['source_fingerprint']:
            raise ValueError('A selected CDR changed after this job was queued. Create a new scoring job.')
        update_progress(6, 'Reading processed CDR rows')
        engine = _scoring_engine()
        # The points-lost map also reads the area and coordinate columns.
        required_columns = getattr(engine, 'load_input_columns', None) or getattr(engine, 'required_input_columns')
        for source in sources:
            source['levels'] = job['levels']
        frames = _load_source_frames(
            repository, sources, update_progress, required_columns,
            job.get('resolved_context_filters', job.get('context_filters', {})),
        )
        _current_sources, _campaigns, post_load_fingerprint = _source_snapshot(
            repository, dataset_ids, expected_nr_mode=job['nr_mode'],
        )
        if post_load_fingerprint != job['source_fingerprint']:
            raise ValueError('A selected CDR changed while its scoring rows were being loaded.')
        update_progress(62, 'Calculating KPIs and interpolated scores')
        calculate = engine.calculate_scoring
        parameters = inspect.signature(calculate).parameters
        call_kwargs = {
            'baseline_operator': job['baseline_operator'],
            'configuration': configuration,
        }
        if 'operator_mappings' in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
            call_kwargs['operator_mappings'] = job.get('operator_mappings', {})
        if 'baseline_aliases' in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
            call_kwargs['baseline_aliases'] = job.get('baseline_aliases', [])
        result = calculate(frames, job['levels'], **call_kwargs)
        if not isinstance(result, dict):
            raise TypeError('The scoring engine must return a result object.')
        _attach_mapping_boundaries(repository, dataset_ids, result)
        result.setdefault('configuration', configuration)
        result.setdefault('configuration_hash', configuration_hash(configuration))
        result.setdefault('gap_direction', 'operator_minus_reference')
        result.setdefault('baseline_aliases', job.get('baseline_aliases', []))
        result.setdefault('aggregation_levels', job['levels'])
        result.setdefault('aggregation_contract_version', job['aggregation_contract_version'])
        result.setdefault('campaigns', job['campaigns'])
        _latest_sources, _latest_campaigns, final_fingerprint = _source_snapshot(
            repository, dataset_ids, expected_nr_mode=job['nr_mode'],
        )
        if final_fingerprint != job['source_fingerprint']:
            raise ValueError('A selected CDR changed while its scoring calculation was running.')
        result_payload = {
            'scoring': result.get('scoring', []),
            'gap': result.get('gap', []),
            'charts': result.get('charts', []),
            'warnings': result.get('warnings', []),
            **{key: value for key, value in result.items() if key not in {'scoring', 'gap', 'charts', 'warnings'}},
        }
        encoded_result = json.dumps(
            _serialize_result_value(result_payload), ensure_ascii=False, separators=(',', ':'), allow_nan=False,
        )
        _update_scoring_job(
            repository, job_id, status='completed', progress=100,
            message='Scoring tables and GAP analysis are ready', result_json=encoded_result,
            last_error='', finished_at=local_now_iso(),
        )
    except _ScoringJobDeleted:
        return None
    except Exception as exc:
        _update_scoring_job(
            repository, job_id, status='failed', progress=100,
            message='Scoring calculation failed', last_error=str(exc), finished_at=local_now_iso(),
        )
    return get_scoring_job(repository, job_id, include_result=True)
