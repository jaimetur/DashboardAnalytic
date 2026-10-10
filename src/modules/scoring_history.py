"""Scoring History: the components of every scoring KPI of every CDR, per day and area.

Each ready Data, Voice and Speech CDR is read once (in the background, when the server is idle) and its tests are
grouped by day, campaign, operator, vendor, environment selectors, Region, Cluster and City. For every group and every
KPI of the workspace methodologies the history keeps what the KPI needs to be calculated again over any set of
groups: the sums and counts of its ratio terms and averages, and a mergeable sketch of the values of its medians and
90th percentiles (approximate, within 0.25 %). A scoring calculation over the indexed CDRs then adds the groups of its
period, areas and split instead of reading the CDR rows, and scores the KPI values with the thresholds of its
methodology, so any methodology, period (days, weeks, months, quarters, campaigns, years) and area can be scored
from the same history.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable

import pandas as pd

from src.modules.cdr_stage import dataset_cdr_stage
from src.modules.column_names import column_identity, resolve_column_name, vendor_match_values
from src.modules.scoring import (
    START_TIME_COLUMNS, _FIELDS, _LEVEL_SOURCE_ALIASES, _SHARED, _condition, _filter, _is_condition_expression,
    _key_name, _numeric, finish_scoring, normalize_time_split, period_labels, required_input_columns,
)
from src.modules.scoring_config import validate_scoring_configuration
from src.modules.scoring_vendors import scoring_vendor_group, scoring_vendor_name

HISTORY_TABLE = 'scoring_history'
HISTORY_SOURCES_TABLE = 'scoring_history_sources'
HISTORY_FILES_TABLE = 'scoring_history_files'
# Bumped when the components change: every CDR is indexed again.
HISTORY_VERSION = 1
CDR_KINDS = ('data', 'voice', 'speech')
# The dimensions of a history group, in their table order.
DIMENSIONS = ('day', 'campaign', 'operator', 'vendor', 'operator_vendor', 'g_level_1', 'g_level_2', 'region',
              'cluster', 'city')
# The source column of each dimension (the first one a CDR has).
DIMENSION_SOURCES = {
    'campaign': ('Campaign',), 'operator': ('Operator',), 'vendor': ('Vendor',), 'operator_vendor': ('Operator_Vendor',),
    'g_level_1': ('G_Level_1',), 'g_level_2': ('G_Level_2',), 'region': _LEVEL_SOURCE_ALIASES['Region'],
    'cluster': _LEVEL_SOURCE_ALIASES['Cluster'], 'city': _LEVEL_SOURCE_ALIASES['City'],
}
# The levels and context filters a calculation from the history supports, and the dimension of each.
LEVEL_DIMENSIONS = {'Operator': 'operator', 'Vendor': 'vendor', 'Region': 'region', 'Cluster': 'cluster',
                    'City': 'city', 'Campaign': 'campaign', 'Dataset Type': None}
FILTER_DIMENSIONS = {'Region': 'region', 'Cluster': 'cluster', 'City': 'city', 'Operator': 'operator',
                     'Operator_Vendor': 'operator_vendor', 'Vendor_Operator': 'operator_vendor', 'Vendor': 'vendor',
                     'Campaign': 'campaign'}
# The relative accuracy of the sketches of medians and percentiles.
SKETCH_ACCURACY = 0.0025
_GAMMA = (1 + SKETCH_ACCURACY) / (1 - SKETCH_ACCURACY)
_LOG_GAMMA = math.log(_GAMMA)
_PACKET_FORMULA = '100 * SUM(totalpacketlost) / SUM(Packets_Sent)'
_PACKET_FIELDS = ('Packets_Lost', 'Packets_Discarded', 'Packets_Corrupted', 'Packets_Not_Sent')

# A source of the history is a CDR file as processed: the SHA-256 of the whole file (whatever its name, ID or
# workspace) and the signature of its processing (normalization, Vendor, Region and Cluster mappings, rows and columns).
# The history of a deleted CDR is kept; a CDR processed again replaces the history of its former processing.
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {HISTORY_FILES_TABLE} (
    dataset_id INTEGER PRIMARY KEY,
    stored_path TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    file_mtime REAL NOT NULL DEFAULT 0,
    file_sha256 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS {HISTORY_SOURCES_TABLE} (
    source_key TEXT PRIMARY KEY,
    file_sha256 TEXT NOT NULL DEFAULT '',
    dataset_id INTEGER,
    kind TEXT NOT NULL,
    nr_mode TEXT NOT NULL DEFAULT '',
    cdr_stage TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    campaigns_json TEXT NOT NULL DEFAULT '[]',
    metrics_json TEXT NOT NULL DEFAULT '{{}}',
    columns_json TEXT NOT NULL DEFAULT '[]',
    row_count INTEGER NOT NULL DEFAULT 0,
    group_count INTEGER NOT NULL DEFAULT 0,
    first_day TEXT NOT NULL DEFAULT '',
    last_day TEXT NOT NULL DEFAULT '',
    indexed_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} (
    source_key TEXT NOT NULL,
    day TEXT,
    campaign TEXT,
    operator TEXT,
    vendor TEXT,
    operator_vendor TEXT,
    g_level_1 TEXT,
    g_level_2 TEXT,
    region TEXT,
    cluster TEXT,
    city TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    components_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_{HISTORY_TABLE}_source ON {HISTORY_TABLE}(source_key);
CREATE INDEX IF NOT EXISTS idx_{HISTORY_SOURCES_TABLE}_file ON {HISTORY_SOURCES_TABLE}(file_sha256);
CREATE INDEX IF NOT EXISTS idx_{HISTORY_TABLE}_day ON {HISTORY_TABLE}(day);
"""


class HistoryUnavailable(Exception):
    """The history cannot answer a calculation: it reads the CDR rows instead."""


def ensure_history_tables(repository: Any) -> None:
    with repository.connection() as connection:
        connection.executescript(SCHEMA)


# ---------------------------------------------------------------------------------------------------------------------
# Metrics and their components

def metric_signature(metric: dict[str, Any]) -> str:
    """The identity of what a KPI measures: its source and calculation (not its thresholds or points)."""
    payload = json.dumps({'kind': metric['source_kind'], 'calculation': metric['calculation'], 'v': HISTORY_VERSION,
                          'sketch': SKETCH_ACCURACY}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]


def workspace_metrics(repository: Any) -> dict[str, dict[str, Any]]:
    """The KPIs of every methodology of the workspace, by signature."""
    metrics: dict[str, dict[str, Any]] = {}
    try:
        profiles = repository.get_scoring_profiles()['profiles']
    except (ValueError, KeyError, TypeError):
        return metrics
    for profile in profiles:
        try:
            configuration = validate_scoring_configuration(profile['configuration'])
        except (ValueError, KeyError, TypeError):
            continue
        for metric in configuration['metrics']:
            metrics.setdefault(metric_signature(metric), metric)
    return metrics


def _sketch_key(value: float) -> int:
    return math.ceil(math.log(value) / _LOG_GAMMA)


def _sketch_value(key: int) -> float:
    return 2 * _GAMMA ** key / (_GAMMA + 1)


def _sketch_keys(values: pd.Series) -> pd.Series:
    """The bucket of each value: positive ones by their logarithm, 'z' for zero and negative ones mirrored."""
    keys = pd.Series('z', index=values.index, dtype=object)
    positive = values > 0
    negative = values < 0
    if positive.any():
        keys[positive] = 'p' + (pd.Series(values[positive]).map(_sketch_key)).astype(str)
    if negative.any():
        keys[negative] = 'n' + (pd.Series(-values[negative]).map(_sketch_key)).astype(str)
    return keys


def _sketch_quantile(sketch: dict[str, int], quantile: float) -> float | None:
    """The value at ``quantile`` of a sketch, as pandas interpolates it (position quantile * (n - 1))."""
    count = sum(sketch.values())
    if not count:
        return None

    def order(key: str) -> tuple[int, float]:
        if key == 'z':
            return 1, 0.0
        if key.startswith('n'):
            return 0, -int(key[1:])
        return 2, int(key[1:])

    def value(key: str) -> float:
        if key == 'z':
            return 0.0
        return -_sketch_value(int(key[1:])) if key.startswith('n') else _sketch_value(int(key[1:]))

    position = quantile * (count - 1)
    lower, upper = math.floor(position), math.ceil(position)
    ordered = sorted(sketch.items(), key=lambda item: order(item[0]))
    found: dict[int, float] = {}
    seen = 0
    for key, amount in ordered:
        for rank in (lower, upper):
            if rank not in found and seen <= rank < seen + amount:
                found[rank] = value(key)
        seen += amount
    return found[lower] + (found[upper] - found[lower]) * (position - lower)


def _term_kind(operation: str, expression: str) -> str:
    if _is_condition_expression(expression.strip()):
        return 'condition'
    if operation == 'COUNT':
        return 'count'
    if operation in {'MEDIAN', 'PCT90'}:
        return 'sketch'
    return 'numeric'


def _parse_formula(formula: str) -> tuple[str, Any]:
    if formula == _PACKET_FORMULA:
        return 'packet', None
    ratio = re.fullmatch(r'(100 \* )?(SUM|COUNT)\((.+)\) / (SUM|COUNT)\((\w+)\)', formula)
    if ratio:
        return 'ratio', ratio.groups()
    aggregate = re.fullmatch(r'(AVG|MEDIAN|PCT90|SUM|COUNT)\((.+)\)', formula)
    if aggregate:
        return 'aggregate', aggregate.groups()
    raise ValueError(f'Unsupported scoring formula: {formula}')


def _term_frame(frame: pd.DataFrame, operation: str, expression: str, prefix: str) -> pd.DataFrame:
    """The per-row parts of a term, summed per group later: the sum and count, or the sketch bucket of each value."""
    expression = expression.strip()
    kind = _term_kind(operation, expression)
    if kind == 'condition':
        matches = _condition(frame, expression).astype(float)
        return pd.DataFrame({f'{prefix}s': matches, f'{prefix}c': matches})
    if kind == 'count':
        present = frame[expression].notna().astype(float)
        return pd.DataFrame({f'{prefix}s': present, f'{prefix}c': present})
    values = _numeric(frame, expression)
    if kind == 'sketch':
        return pd.DataFrame({f'{prefix}k': _sketch_keys(values).where(values.notna(), None),
                             f'{prefix}c': values.notna().astype(float)})
    return pd.DataFrame({f'{prefix}s': values, f'{prefix}c': values.notna().astype(float)})


def _metric_frame(frame: pd.DataFrame, metric: dict[str, Any]) -> pd.DataFrame:
    """The per-row components of a KPI over the rows its filters keep (the other rows are left out)."""
    calculation = metric['calculation']
    kept = _filter(frame, calculation['filters'])
    shape, parts = _parse_formula(calculation['formula'])
    if shape == 'packet':
        sent = _numeric(kept, 'Packets_Sent')
        lost = 0
        for field in _PACKET_FIELDS:
            values = _numeric(kept, field) if field in kept.columns else pd.Series(0.0, index=kept.index)
            values = values.fillna(0)
            lost = lost + (values.map(math.trunc) if field == 'Packets_Corrupted' else values)
        return pd.DataFrame({'ls': lost, 'ss': sent, 'sc': sent.notna().astype(float)}, index=kept.index)
    if shape == 'ratio':
        _multiplier, numerator_operation, expression, denominator_operation, denominator_field = parts
        return pd.concat([_term_frame(kept, numerator_operation, expression, 'n'),
                          _term_frame(kept, denominator_operation, denominator_field, 'd')], axis=1)
    operation, expression = parts
    return _term_frame(kept, operation, expression, 't')


def _clean_key(key: Any) -> tuple:
    """A group key with its empty values as None (pandas gives NaN, which never equals itself)."""
    key = key if isinstance(key, tuple) else (key,)
    return tuple(None if (value is None or (isinstance(value, float) and math.isnan(value))) else value for value in key)


def _group_components(parts: pd.DataFrame, group_keys: pd.DataFrame) -> dict[tuple, dict[str, Any]]:
    """The components of a KPI for each group: sums and counts, and the sketches of the bucketed values."""
    if parts.empty:
        return {}
    keys = group_keys.loc[parts.index]
    key_columns = list(keys.columns)
    combined = pd.concat([keys, parts], axis=1)
    sums = [column for column in parts.columns if not column.endswith('k')]
    result: dict[tuple, dict[str, Any]] = {}
    grouped = combined.groupby(key_columns, dropna=False, sort=False)
    totals = grouped[sums].sum(min_count=1) if sums else None
    if totals is not None:
        for key, row in totals.iterrows():
            result[_clean_key(key)] = {column: (None if pd.isna(value) else float(value)) for column, value in row.items()}
    for column in (column for column in parts.columns if column.endswith('k')):
        buckets = combined[[*key_columns, column]].dropna(subset=[column])
        if buckets.empty:
            continue
        counts = buckets.groupby([*key_columns, column], dropna=False, sort=False).size()
        for index, amount in counts.items():
            key, bucket = _clean_key(tuple(index[:-1])), index[-1]
            result.setdefault(key, {}).setdefault(column, {})[str(bucket)] = int(amount)
    return result


def merge_components(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Add the components of a group to those of others: sums (None while none had a value), counts and sketches."""
    for name, value in source.items():
        if isinstance(value, dict):
            sketch = target.setdefault(name, {})
            for bucket, amount in value.items():
                sketch[bucket] = sketch.get(bucket, 0) + amount
        elif value is not None:
            current = target.get(name)
            target[name] = value if current is None else current + value
        else:
            target.setdefault(name, None)
    return target


def _term_value(components: dict[str, Any], operation: str, expression: str, prefix: str) -> tuple[float | None, int]:
    """A term's value and count, as the engine aggregates it (``scoring._aggregate_term``)."""
    kind = _term_kind(operation, expression)
    count = int(components.get(f'{prefix}c') or 0)
    if kind in {'condition', 'count'}:
        total = components.get(f'{prefix}s') or 0.0
        return float(total), int(total)
    if not count:
        return None, 0
    if kind == 'sketch':
        sketch = components.get(f'{prefix}k') or {}
        return _sketch_quantile(sketch, 0.5 if operation == 'MEDIAN' else 0.9), count
    total = components.get(f'{prefix}s')
    if total is None:
        return None, 0
    return (float(total) / count if operation == 'AVG' else float(total)), count


def metric_value(components: dict[str, Any] | None, metric: dict[str, Any]) -> tuple[float | None, int]:
    """A KPI's value and sample count from the components of its groups (``scoring._aggregate``)."""
    if not components:
        components = {}
    shape, parts = _parse_formula(metric['calculation']['formula'])
    if shape == 'packet':
        sent = components.get('ss')
        if sent is None or sent <= 0:
            return None, 0
        return float(100 * (components.get('ls') or 0.0) / sent), int(components.get('sc') or 0)
    if shape == 'ratio':
        multiplier, numerator_operation, expression, denominator_operation, denominator_field = parts
        numerator, _count = _term_value(components, numerator_operation, expression, 'n')
        denominator, count = _term_value(components, denominator_operation, denominator_field, 'd')
        if numerator is None or denominator is None or denominator == 0:
            return None, 0
        return float((100 if multiplier else 1) * numerator / denominator), count
    operation, expression = parts
    return _term_value(components, operation, expression, 't')


# ---------------------------------------------------------------------------------------------------------------------
# Indexing the CDRs

def file_sha256(repository: Any, row: Any) -> str:
    """The SHA-256 of the whole source file of a CDR (about half a second per GB), kept until the file changes."""
    dataset_id = int(row['id'])
    path = Path(str(row['stored_path'] or ''))
    try:
        stat = path.stat()
    except OSError:
        return ''
    with repository.connection() as connection:
        cached = connection.execute(f'SELECT * FROM {HISTORY_FILES_TABLE} WHERE dataset_id = ?', (dataset_id,)).fetchone()
    if (cached and cached['stored_path'] == str(path) and int(cached['file_size']) == stat.st_size
            and float(cached['file_mtime']) == stat.st_mtime and cached['file_sha256']):
        return str(cached['file_sha256'])
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    value = digest.hexdigest()
    with repository.connection() as connection:
        connection.execute(
            f'INSERT OR REPLACE INTO {HISTORY_FILES_TABLE} (dataset_id, stored_path, file_size, file_mtime, file_sha256) '
            'VALUES (?, ?, ?, ?, ?)', (dataset_id, str(path), stat.st_size, stat.st_mtime, value))
    return value


def source_key(repository: Any, row: Any, datasets: dict[int, Any] | None = None) -> tuple[str, str]:
    """The key of a CDR as processed (the SHA-256 of its file and the signature of its processing) and the file hash.

    Without its source file (an input removed to save space), the CDR is identified by its name and processing.
    """
    dataset_id = int(row['id'])
    sha = file_sha256(repository, row)
    datasets = datasets if datasets is not None else {int(item['id']): item for item in repository.list_datasets()}

    def mapping_file(field: str) -> str:
        mapping = datasets.get(int(row[field])) if row[field] else None
        return file_sha256(repository, mapping) if mapping is not None else ''

    signature = json.dumps({
        'v': HISTORY_VERSION, 'file': sha or str(row['file_name'] or ''), 'kind': str(row['dataset_kind'] or ''),
        'nr_mode': str(row['nr_mode'] or ''), 'processed_at': str(row['processed_at'] or ''),
        'updated_at': str(row['updated_at'] or ''), 'normalization_version': int(row['normalization_version'] or 1),
        'vendor_mapping_applied': int(row['vendor_mapping_applied'] or 0),
        'region_mapping': (int(row['region_mapping_applied'] or 0), mapping_file('region_mapping_dataset_id')),
        'cluster_mapping': (int(row['cluster_mapping_applied'] or 0), mapping_file('cluster_mapping_dataset_id')),
        'row_count': int(repository.dataset_row_count(dataset_id)),
        'columns': sorted(str(column) for column in repository.list_dataset_row_columns(dataset_id)),
    }, sort_keys=True, ensure_ascii=False)
    return f"{sha[:24] or 'nofile'}:{hashlib.sha1(signature.encode('utf-8')).hexdigest()[:16]}", sha


def _ready_cdrs(repository: Any) -> dict[int, Any]:
    return {
        int(row['id']): row for row in repository.list_datasets()
        if str(row['dataset_kind'] or '').casefold() in CDR_KINDS and str(row['status'] or '').casefold() == 'ready'
        and repository.dataset_rows_table_exists(int(row['id']))
    }


def history_changes(repository: Any) -> tuple[list[tuple[Any, str, str]], dict[str, dict[str, Any]]]:
    """The CDRs to index (new, changed, or without a KPI of the workspace) with their source key and file hash, and
    the KPIs of the workspace."""
    ensure_history_tables(repository)
    metrics = workspace_metrics(repository)
    all_datasets = {int(row['id']): row for row in repository.list_datasets()}
    with repository.connection() as connection:
        indexed = {str(row['source_key']): set(json.loads(row['metrics_json'] or '{}')) for row in connection.execute(
            f'SELECT source_key, metrics_json FROM {HISTORY_SOURCES_TABLE}').fetchall()}
    changed = []
    for row in _ready_cdrs(repository).values():
        key, sha = source_key(repository, row, all_datasets)
        kind = str(row['dataset_kind']).casefold()
        wanted = {signature for signature, metric in metrics.items() if metric['source_kind'] == kind}
        if key not in indexed or not wanted <= indexed[key]:
            changed.append((row, key, sha))
    return changed, metrics


def _dataset_frame(repository: Any, dataset_id: int, kind: str) -> tuple[pd.DataFrame, list[str]]:
    """The rows of a CDR with the scoring columns of its type under their canonical names, and the columns it has."""
    available = repository.list_dataset_row_columns(dataset_id)
    wanted = [*required_input_columns(kind), *(alias for aliases in DIMENSION_SOURCES.values() for alias in aliases),
              *START_TIME_COLUMNS]
    selected = list(dict.fromkeys(resolved for name in wanted if (resolved := resolve_column_name(available, name))))
    source = repository.load_dataset_rows(dataset_id, selected, {}) if selected else pd.DataFrame()
    frame = pd.DataFrame(index=source.index)
    present = []
    for field in required_input_columns(kind):
        if field in {'Operator', 'Campaign', 'G_Level_1', 'G_Level_2'}:
            continue
        column = resolve_column_name(source.columns, field)
        if column is not None:
            frame[field] = source[column]
            present.append(field)
        else:
            # A column the CDR lacks counts as empty, as in a calculation over several CDRs.
            frame[field] = pd.Series(float('nan'), index=source.index)
    for dimension, aliases in DIMENSION_SOURCES.items():
        column = next((resolved for alias in aliases if (resolved := resolve_column_name(source.columns, alias))), None)
        frame[dimension] = source[column] if column is not None else None
        if column is not None:
            present.append(dimension)
    start = next((column for name in START_TIME_COLUMNS if (column := resolve_column_name(source.columns, name))), None)
    if start is not None:
        frame['day'] = period_labels(source[start], 'Daily')
        present.append('day')
    else:
        frame['day'] = None
    return frame, present


def _missing_metric_columns(frame: pd.DataFrame, present: list[str], metric: dict[str, Any]) -> str | None:
    """The first column a KPI needs that the CDR lacks (its value is then missing, with a warning)."""
    calculation = metric['calculation']
    names = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', calculation['formula'])) | {
        str(field).removesuffix(' contains') for field in calculation['filters']}
    for name in sorted(names):
        if name in frame.columns and name not in present and name not in DIMENSIONS:
            return name
    return None


def index_dataset(repository: Any, row: Any, metrics: dict[str, dict[str, Any]], key: str = '',
                  sha: str = '') -> dict[str, Any]:
    """Read a CDR once and store the components of every KPI of its type for each of its day and area groups."""
    dataset_id = int(row['id'])
    if not key:
        key, sha = source_key(repository, row)
    kind = str(row['dataset_kind']).casefold()
    frame, present = _dataset_frame(repository, dataset_id, kind)
    for dimension in DIMENSIONS:
        frame[dimension] = frame[dimension].map(lambda value: None if pd.isna(value) else str(value))
    group_keys = frame[list(DIMENSIONS)]
    groups: dict[tuple, dict[str, Any]] = {}
    row_counts = group_keys.groupby(list(DIMENSIONS), dropna=False, sort=False).size()
    for group_key, amount in row_counts.items():
        groups[_clean_key(group_key)] = {'rows': int(amount), 'metrics': {}}
    indexed_metrics: dict[str, str] = {}
    for signature, metric in metrics.items():
        if metric['source_kind'] != kind:
            continue
        # A column the CDR lacks is empty in its rows (as when several CDRs are scored together); the KPI is
        # missing, with a warning, only when every CDR of a calculation lacks it.
        indexed_metrics[signature] = _missing_metric_columns(frame, present, metric) or ''
        try:
            parts = _metric_frame(frame, metric)
        except KeyError as error:
            indexed_metrics[signature] = str(error.args[0])
            continue
        for group_key, components in _group_components(parts, group_keys).items():
            groups[group_key]['metrics'][signature] = components
    row_count = repository.dataset_row_count(dataset_id)
    days = sorted(group_key[0] for group_key in groups if group_key[0])
    campaigns = sorted({group_key[1] for group_key in groups if group_key[1]})
    stage = dataset_cdr_stage(kind, row['cdr_stage'] if 'cdr_stage' in row.keys() else None, row['file_name']) or ''
    with repository.connection() as connection:
        # The CDR processed again replaces the history of its former processing of the same file (the history of
        # another file, even of a deleted CDR whose ID was given to this one, is kept).
        stale = [str(item[0]) for item in connection.execute(
            f'SELECT source_key FROM {HISTORY_SOURCES_TABLE} WHERE source_key = ? OR (dataset_id = ? AND file_sha256 = ?)',
            (key, dataset_id, sha)).fetchall()]
        for stale_key in stale:
            connection.execute(f'DELETE FROM {HISTORY_TABLE} WHERE source_key = ?', (stale_key,))
            connection.execute(f'DELETE FROM {HISTORY_SOURCES_TABLE} WHERE source_key = ?', (stale_key,))
        connection.executemany(
            f"INSERT INTO {HISTORY_TABLE} (source_key, {', '.join(DIMENSIONS)}, row_count, components_json) "
            f"VALUES (?, {', '.join('?' for _ in DIMENSIONS)}, ?, ?)",
            [(key, *group_key, group['rows'], json.dumps(group['metrics'], separators=(',', ':')))
             for group_key, group in groups.items()],
        )
        connection.execute(
            f'INSERT INTO {HISTORY_SOURCES_TABLE} (source_key, file_sha256, dataset_id, kind, nr_mode, cdr_stage, name, '
            'campaigns_json, metrics_json, columns_json, row_count, group_count, first_day, last_day, indexed_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (key, sha, dataset_id, kind, str(row['nr_mode'] or ''), stage, str(row['file_name'] or ''),
             json.dumps(campaigns, ensure_ascii=False), json.dumps(indexed_metrics), json.dumps(present), row_count,
             len(groups), days[0] if days else '', days[-1] if days else '',
             pd.Timestamp.now().isoformat(timespec='seconds')),
        )
    return {'dataset_id': dataset_id, 'source_key': key, 'groups': len(groups), 'rows': row_count}


def sync_history(repository: Any, progress: Callable[[int, int, str], None] | None = None) -> dict[str, Any]:
    """Index the new or changed CDRs (the history of the deleted ones is kept)."""
    changed, metrics = history_changes(repository)
    for index, (row, key, sha) in enumerate(changed):
        if progress:
            progress(index, len(changed), str(row['file_name'] or ''))
        index_dataset(repository, row, metrics, key, sha)
    return {'indexed': len(changed)}


def history_status(repository: Any) -> dict[str, Any]:
    changed, _metrics = history_changes(repository)
    with repository.connection() as connection:
        indexed, groups, last = connection.execute(
            f'SELECT COUNT(*), COALESCE(SUM(group_count), 0), MAX(indexed_at) FROM {HISTORY_SOURCES_TABLE}').fetchone()
    return {'indexed': int(indexed or 0), 'groups': int(groups or 0), 'indexed_at': last or '',
            'pending': len(changed)}


# ---------------------------------------------------------------------------------------------------------------------
# Scoring from the history

def history_covers(repository: Any, dataset_ids: Iterable[int], levels: Iterable[str],
                   configuration: dict[str, Any], context_filters: dict[str, list[str]] | None = None) -> bool:
    """Whether every CDR is indexed at its current revision with every KPI of the methodology, and the split and
    filters are dimensions of the history."""
    try:
        _dimensions(levels)
    except HistoryUnavailable:
        return False
    if any(values and field not in FILTER_DIMENSIONS for field, values in (context_filters or {}).items()):
        return False
    try:
        ensure_history_tables(repository)
        _sources(repository, list(dataset_ids), validate_scoring_configuration(configuration))
    except HistoryUnavailable:
        return False
    return True


def _dimensions(levels: Iterable[str]) -> list[str]:
    dimensions = []
    for level in levels:
        identity = column_identity(level)
        canonical = {'operator': 'Operator', 'region': 'Region', 'cluster': 'Cluster', 'city': 'City', 'vendor': 'Vendor',
                     'ranvendor': 'Vendor', 'campaign': 'Campaign', 'datasettype': 'Dataset Type',
                     'datasetkind': 'Dataset Type'}.get(identity)
        if canonical is None:
            raise HistoryUnavailable(f'Unsupported scoring level: {level}')
        if canonical not in dimensions:
            dimensions.append(canonical)
    if 'Operator' not in dimensions:
        dimensions.append('Operator')
    return dimensions


def _sources(repository: Any, dataset_ids: list[int], config: dict[str, Any]) -> dict[int, Any]:
    """The history source of each selected CDR, at its current file and processing, with every KPI of the methodology."""
    datasets = _ready_cdrs(repository)
    all_datasets = {int(row['id']): row for row in repository.list_datasets()}
    keys = {}
    for dataset_id in dataset_ids:
        row = datasets.get(int(dataset_id))
        if row is None:
            raise HistoryUnavailable(f'CDR {dataset_id} is not ready.')
        keys[int(dataset_id)] = source_key(repository, row, all_datasets)[0]
    with repository.connection() as connection:
        indexed = {str(row['source_key']): row for row in connection.execute(
            f'SELECT * FROM {HISTORY_SOURCES_TABLE} WHERE source_key IN ({", ".join("?" for _ in keys) or "NULL"})',
            list(keys.values())).fetchall()}
    sources = {}
    for dataset_id, key in keys.items():
        source = indexed.get(key)
        if source is None:
            raise HistoryUnavailable(f'CDR {dataset_id} is not in the Scoring History at its current processing.')
        kind_signatures = {metric_signature(metric) for metric in config['metrics'] if metric['source_kind'] == source['kind']}
        if not kind_signatures <= set(json.loads(source['metrics_json'] or '{}')):
            raise HistoryUnavailable(f'CDR {dataset_id} has no history of every KPI of the methodology.')
        sources[dataset_id] = source
    return sources


_PERIODS: dict[tuple[str, str], str | None] = {}


def _period(day: str, time_split: str) -> str | None:
    """The period of a day, as the engine labels the start times (2026-W07, 2026-07, 2026-Q3...)."""
    key = (day, time_split)
    if key not in _PERIODS:
        _PERIODS[key] = period_labels(pd.Series([day]), time_split).iloc[0]
    return _PERIODS[key]


def _matcher(values: Iterable[str]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def calculate_scoring_from_history(
    repository: Any, dataset_ids: Iterable[int], levels: Iterable[str] = ('Operator',), *,
    baseline_operator: str = 'EE', configuration: dict | None = None, baseline_aliases: Iterable[str] = (),
    operator_mappings: dict[str, str] | None = None, context_filters: dict[str, list[str]] | None = None,
    time_split: str | None = None, cities: Iterable[str] | None = None, vendor_operators: Iterable[str] = (),
) -> dict[str, Any]:
    """The scoring of the CDRs at the split and filters, as ``scoring.calculate_scoring`` calculates it from their rows,
    from the Scoring History (without the points-lost map, which needs the rows of the tests).

    ``cities`` keeps the tests of those cities (the separate cities of a National & area summary); ``vendor_operators``
    are the operator names the Vendor filter removes from vendor names, as when the CDR rows are loaded.
    """
    config = validate_scoring_configuration(configuration)
    dataset_ids = [int(value) for value in dataset_ids]
    dimensions = _dimensions(levels)
    sources = _sources(repository, dataset_ids, config)
    metrics = config['metrics']
    signatures = {metric['code']: metric_signature(metric) for metric in metrics}
    baseline_aliases = list(dict.fromkeys(
        [str(baseline_operator), *(str(alias).strip() for alias in baseline_aliases if str(alias).strip())]))
    campaign_selected = 'Campaign' in dimensions
    time_split = normalize_time_split(time_split) if campaign_selected else None
    group_fields = list(dict.fromkeys(['Campaign', *dimensions, 'environment']))
    keys = [_key_name(field) for field in group_fields]
    normalized_operator_mappings = {
        str(alias).strip().casefold(): str(canonical).strip()
        for alias, canonical in (operator_mappings or {}).items() if str(alias).strip() and str(canonical).strip()
    }
    environments = config['scope']['environments']
    # The context filters, matched as the CDR rows are loaded: trimmed and whatever their case.
    filters: dict[str, set[str]] = {}
    mapping_names = repository.list_operator_mappings() if hasattr(repository, 'list_operator_mappings') else []
    for field, values in (context_filters or {}).items():
        values = [str(value) for value in values or [] if str(value).strip()]
        if not values:
            continue
        if field == 'Vendor':
            values = [scoring_vendor_name(value, vendor_operators) for value in values]
        if field in {'Vendor', 'Operator_Vendor', 'Vendor_Operator'}:
            values = vendor_match_values(field, values, mapping_names)
        filters[FILTER_DIMENSIONS[field]] = _matcher(values)
    city_filter = _matcher(cities) if cities is not None else None

    # The groups of the selected CDRs, by type, that the filters keep.
    rows_by_kind: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    present_by_kind: dict[str, set[str]] = {}
    missing_by_kind: dict[str, dict[str, set[str]]] = {}
    campaign_values: dict[str, str] = {}
    warnings: list[str] = []
    for dataset_id in dataset_ids:
        source = sources[dataset_id]
        kind = str(source['kind'])
        present = set(json.loads(source['columns_json'] or '[]'))
        if any(dimension not in present for dimension in filters):
            if {'vendor', 'operator_vendor'} & (set(filters) - present):
                # Loading the rows adds the Vendor column a vendor filter needs: they are read instead.
                raise HistoryUnavailable(f'CDR {dataset_id} has no Vendor column in the Scoring History.')
            continue
        indexed_metrics = json.loads(source['metrics_json'] or '{}')
        missing_by_kind.setdefault(kind, {})
        for signature, missing in indexed_metrics.items():
            missing_by_kind[kind].setdefault(signature, set()).add(missing)
        with repository.connection() as connection:
            records = connection.execute(
                f"SELECT {', '.join(DIMENSIONS)}, row_count, components_json FROM {HISTORY_TABLE} WHERE source_key = ?",
                (source['source_key'],)).fetchall()
        kept = []
        for record in records:
            values = {dimension: record[dimension] for dimension in DIMENSIONS}
            if any((values[dimension] or '').strip().lower() not in allowed for dimension, allowed in filters.items()):
                continue
            if city_filter is not None and (values['city'] or '').strip().lower() not in city_filter:
                continue
            kept.append((values, {'rows': int(record['row_count']), 'metrics': json.loads(record['components_json'])}))
        if not kept:
            continue
        rows_by_kind.setdefault(kind, []).extend(kept)
        present_by_kind.setdefault(kind, set()).update(present)
        for values, _group in kept:
            if values['campaign'] and values['campaign'].strip():
                campaign_values.setdefault(values['campaign'].strip().casefold(), values['campaign'].strip())
    if filters:
        labels = {'data': 'Data', 'voice': 'Voice', 'speech': 'Speech'}
        missing_kinds = [kind for kind in CDR_KINDS if not rows_by_kind.get(kind)]
        if missing_kinds:
            raise ValueError('Scoring context filters leave no matching processed rows for every required CDR type. '
                             f"Missing: {', '.join(labels[kind] for kind in missing_kinds)}.")
    for missing_kind in set(_FIELDS) - set(rows_by_kind):
        warnings.append(f'{missing_kind.title()} source is missing; full benchmark coverage is unavailable.')

    rows: list[dict[str, Any]] = []
    global_kpis: list[dict[str, Any]] = []
    for kind, kind_rows in rows_by_kind.items():
        present = present_by_kind[kind]
        needed = {'Operator': 'operator', 'Campaign': 'campaign', 'G_Level_1': 'g_level_1', 'G_Level_2': 'g_level_2',
                  **{level: LEVEL_DIMENSIONS[level] for level in dimensions if level != 'Dataset Type'}}
        missing_group = [field for field, dimension in needed.items() if dimension not in present]
        if missing_group:
            warnings.append(f'{kind.title()}: missing grouping columns: {", ".join(missing_group)}; no scores calculated.')
            continue
        kind_metrics = [metric for metric in metrics if metric['source_kind'] == kind]
        # The operators named in the Vendor values (and the mapped ones) are removed from them, as in the engine.
        vendor_names = [*normalized_operator_mappings, *normalized_operator_mappings.values(),
                        *{values['operator'] for values, _group in kind_rows if values['operator'] is not None}]
        vendor_labels: dict[str | None, str] = {}
        grouped: dict[tuple, dict[str, dict[str, Any]]] = {}
        global_grouped: dict[tuple, dict[str, Any]] = {}
        invalid = 0
        for values, group in kind_rows:
            operator = values['operator']
            if operator is not None and normalized_operator_mappings:
                operator = normalized_operator_mappings.get(operator.strip().casefold(), operator.strip())
            if not campaign_selected:
                campaign = None
            elif time_split:
                campaign = _period(values['day'], time_split) if values['day'] else None
            else:
                campaign = values['campaign']
            matched = [name for name, context in environments.items()
                       if values['g_level_1'] == context['source_filters']['G_Level_1']
                       and ('G_Level_2' not in context['source_filters']
                            or values['g_level_2'] == context['source_filters']['G_Level_2'])]
            environment = matched[-1] if matched else None
            dimension_values = {'Campaign': campaign, 'Operator': operator, 'Dataset Type': kind.title()}
            for level in dimensions:
                if level == 'Vendor':
                    raw = values['vendor']
                    if raw not in vendor_labels:
                        vendor_labels[raw] = 'All' if raw is None else scoring_vendor_group(raw, vendor_names)
                    dimension_values['Vendor'] = vendor_labels[raw]
                elif level in {'Region', 'Cluster', 'City'}:
                    dimension_values[level] = values[LEVEL_DIMENSIONS[level]]
            valid = environment is not None and operator is not None and (campaign is not None or not campaign_selected)
            if not valid:
                invalid += group['rows']
            base = tuple(dimension_values.get(field) for field in group_fields if field != 'environment')
            if valid:
                target = grouped.setdefault((*base, environment), {})
                for signature, components in group['metrics'].items():
                    merge_components(target.setdefault(signature, {}), components)
            if matched and operator is not None and (campaign is not None or not campaign_selected):
                entry = global_grouped.setdefault(base, {'all': {}, 'environments': {}})
                for signature, components in group['metrics'].items():
                    merge_components(entry['all'].setdefault(signature, {}), components)
                    for name in matched:
                        merge_components(entry['environments'].setdefault(name, {}).setdefault(signature, {}), components)
        if invalid:
            context = 'environment, operator or campaign' if campaign_selected else 'environment or operator'
            warnings.append(f'{kind.title()}: {invalid} rows have unsupported or missing {context} and were excluded.')

        def value_of(components: dict[str, Any], metric: dict[str, Any]) -> tuple[float | None, int]:
            missing = missing_by_kind.get(kind, {}).get(signatures[metric['code']], set())
            if missing and all(missing):
                warnings.append(f'{kind.title()}: {metric["code"]} requires missing column {sorted(missing)[0]}.')
                return None, 0
            return metric_value(components.get(signatures[metric['code']]), metric)

        for group_key, components in grouped.items():
            metadata = dict(zip(keys, group_key))
            for metric in kind_metrics:
                value, count = value_of(components, metric)
                context = metric['contexts'][metadata['environment']]
                rows.append({**metadata, 'kpi_code': metric['code'], 'kpi': metric['kpi'], 'category': metric['category'],
                             'dataset_type': kind.title(), 'kpi_type': metric.get('kpi_type'),
                             'unit': metric.get('unit'), 'value': value, 'sample_count': count, 'score': None,
                             'weighted_points': None, 'max_points': context['max_points']})
        global_keys = [_key_name(field) for field in group_fields if field != 'environment']
        for base, entry in global_grouped.items():
            metadata = dict(zip(global_keys, base))
            for metric in kind_metrics:
                value, count = value_of(entry['all'], metric)
                expected = [name for name in environments if name in metric['contexts']]
                covered = [name for name in expected
                           if value_of(entry['environments'].get(name, {}), metric)[0] is not None]
                missing_environments = [name for name in expected if name not in covered]
                global_kpis.append({**metadata, 'environment': 'All Environments', 'kpi_code': metric['code'],
                                    'kpi': metric['kpi'], 'category': metric['category'], 'dataset_type': kind.title(),
                                    'kpi_type': metric.get('kpi_type'), 'unit': metric.get('unit'), 'value': value,
                                    'sample_count': count,
                                    'complete_coverage': value is not None and not missing_environments,
                                    'missing_environments': missing_environments})
    result = finish_scoring(
        rows, global_kpis, keys=keys, dimensions=dimensions, config=config, baseline_operator=baseline_operator,
        baseline_aliases=baseline_aliases, warnings=warnings, campaigns=campaign_values.values(),
        points_loss_document=None,
    )
    result['source'] = 'history'
    return result


# ---------------------------------------------------------------------------------------------------------------------
# Indexing in the background: the new, changed or removed CDRs of the active workspace are indexed once the server has
# been idle for a while, never while a page waits.
HISTORY_IDLE_SECONDS = 2 * 60
_history_jobs: dict[str, dict[str, Any]] = {}
_history_jobs_guard = Lock()


def _workspace_key(path: Any) -> str:
    return str(Path(str(path)).resolve())


def history_job(database_path: Any) -> dict[str, Any] | None:
    with _history_jobs_guard:
        job = _history_jobs.get(_workspace_key(database_path))
        return dict(job) if job else None


def start_history_sync(repository: Any, submit: Callable[..., Any]) -> dict[str, Any]:
    """Queue the indexing of the workspace's new or changed CDRs, unless it is already queued or running."""
    key = _workspace_key(repository.db_path)
    with _history_jobs_guard:
        current = _history_jobs.get(key)
        if current and current['status'] in {'queued', 'processing'}:
            return dict(current)
        job = {'status': 'queued', 'queued_at': time.time(), 'started_at': None, 'finished_at': None, 'error': '',
               'done': 0, 'total': 0, 'current': '', 'result': None}
        _history_jobs[key] = job

    def progress(done: int, total: int, name: str) -> None:
        with _history_jobs_guard:
            job.update(done=done, total=total, current=name)

    def run() -> None:
        with _history_jobs_guard:
            job.update(status='processing', started_at=time.time())
        try:
            result = sync_history(repository, progress)
        except Exception as exc:  # The next idle period tries again.
            with _history_jobs_guard:
                job.update(status='failed', error=str(exc), finished_at=time.time())
            return
        with _history_jobs_guard:
            job.update(status='ready', result=result, done=job['total'], finished_at=time.time())

    submit(run)
    with _history_jobs_guard:
        return dict(job)


def install_scoring_history(core: Any) -> None:
    """Index the Scoring History when the server is idle, show it among the background tasks, and report its state."""
    from fastapi import Depends
    from fastapi.responses import JSONResponse

    def active_repository() -> Any | None:
        workspace = core.active_workspace
        if not workspace:
            return None
        return core.Repository(workspace.database_path, global_db_path=core.repository.global_db_path,
                               workspace_registry_db_path=core.workspace_registry.registry_path)

    def index_when_idle() -> None:
        repository = active_repository()
        if repository is None:
            return
        job = history_job(repository.db_path)
        if job and job['status'] in {'queued', 'processing'}:
            return
        changed, metrics = history_changes(repository)
        if metrics and changed:
            start_history_sync(repository, core.submit_background_task)

    def history_tasks(workspace: Any) -> list[dict[str, Any]]:
        job = history_job(workspace.database_path)
        if not job or (job['status'] in {'ready', 'failed'} and time.time() - (job['finished_at'] or 0) > 5):
            return []
        detail = job['error'] or (f"Indexing {job['current']} ({job['done'] + 1} of {job['total']})" if job['current']
                                  else 'Indexing the KPIs of new or changed CDRs')
        return [{
            'id': f'scoring-history:{workspace.id}', 'label': 'Scoring History indexing', 'detail': detail,
            'status': job['status'],
            'progress': round(100 * job['done'] / job['total']) if job['total'] else None,
            'queued_at': job['queued_at'], 'started_at': job['started_at'], 'completed_at': job['finished_at'],
        }]

    @core.app.get('/api/scoring/history')
    def scoring_history_state(user=Depends(core.current_user)) -> JSONResponse:
        """How many CDRs the Scoring History holds, when it was last indexed and how many wait to be indexed."""
        repository = active_repository()
        if repository is None:
            return JSONResponse({'indexed': 0, 'groups': 0, 'indexed_at': '', 'pending': 0, 'indexing': False})
        job = history_job(repository.db_path)
        return JSONResponse({**history_status(repository),
                             'indexing': bool(job and job['status'] in {'queued', 'processing'})})

    core.register_idle_task(index_when_idle, HISTORY_IDLE_SECONDS)
    core.BACKGROUND_TASK_PROVIDERS.append(history_tasks)
