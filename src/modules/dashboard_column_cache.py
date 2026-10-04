"""Per-CDR column cache for Dashboard chart reads.

Each combined CDR table is cached per dataset and per SQL expression, in table
row order. Any Dashboard universe (CDRs, dates and filter values) and either
comparison mode can then be assembled in memory without querying SQLite.

Columns are stored compactly and reassembled with the same type inference as
``pandas.read_sql_query`` applies to the combined result rows, so an assembled
frame is identical to the frame SQLite would have returned for the same rows.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import re
import shutil
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from pandas._libs import lib
from pandas.core.internals.construction import convert_object_array

CACHE_FORMAT_VERSION = 1
ROWID = '__cache_rowid'
ORDER_DATE = '__cache_order_date'
# The expression of the combined tables' (dataset_id, event date) index.
ORDER_DATE_SQL = 'date(CAST("event_start_time" AS TEXT))'
# Expressions fetched by one SQLite query when a CDR segment is built.
BUILD_BATCH_SIZE = 24
ORDER_MODES = ('dataset_rowid', 'dataset_date_rowid', 'rowid')

_TOKEN_PATTERN = re.compile(r"'(?:[^']|'')*'|\"((?:[^\"]|\"\")*)\"")


def quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


@dataclass(frozen=True)
class CacheSource:
    """One physical combined CDR table, read directly or through a union branch.

    ``projection`` maps the branch aliases of an RF union to their physical SQL,
    so expressions over aliases are cached by their physical meaning and shared
    whatever other CDR types the union contains.
    """

    kind: str
    table: str
    projection: tuple[tuple[str, str], ...] = ()
    has_event_time: bool = True

    def physical(self, expression: str) -> str:
        """Rewrite an expression over branch aliases into physical table SQL."""
        if not self.projection:
            return expression
        aliases = dict(self.projection)

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name is None:
                return match.group(0)
            alias = name.replace('""', '"')
            return f'({aliases[alias]})' if alias in aliases else match.group(0)

        return _TOKEN_PATTERN.sub(replace, expression)


@dataclass(frozen=True)
class Segment:
    """The rows of one CDR inside one combined table, at one data revision."""

    source: CacheSource
    dataset_id: int
    version: str


@dataclass(frozen=True)
class SelectionTerms:
    """Row predicates of a Dashboard universe, evaluated on cached expressions.

    ``values`` holds ``(expression, allowed)`` pairs: the expression's text value
    must be one of ``allowed``; a ``None`` expression selects no row. ``date``
    holds ``(expression, low, high)`` ISO date bounds. ``excluded_sheets`` keeps
    rows whose sheet is NULL or not excluded.
    """

    values: tuple[tuple[str | None, frozenset[str]], ...] = ()
    date: tuple[str | None, str | None, str | None] | None = None
    excluded_sheets: tuple[str, frozenset[str]] | None = None

    def expressions(self) -> list[str]:
        result = [expression for expression, _allowed in self.values if expression]
        if self.date and self.date[0]:
            result.append(self.date[0])
        if self.excluded_sheets:
            result.append(self.excluded_sheets[0])
        return result


class StaleSegment(RuntimeError):
    """A cached segment no longer matches the rows SQLite returns."""


# ---------------------------------------------------------------------------
# Compact column parts
#
# A part is a tuple whose first item is its kind:
#   ('none', length)                  every value is NULL
#   ('float', float64)                REAL values or NULL (NaN marks NULL)
#   ('int', int64)                    INTEGER values, no NULL
#   ('intnull', int64, null_mask)     INTEGER values and NULL
#   ('str', int32 codes, categories)  TEXT values or NULL (code -1)
#   ('object', object array)          anything else, kept as returned
# ---------------------------------------------------------------------------

def encode_values(values: np.ndarray) -> tuple:
    """Encode one column of SQLite values without losing their Python types."""
    values = np.asarray(values, dtype=object)
    length = len(values)
    inferred = lib.infer_dtype(values, skipna=True)
    if inferred == 'empty':
        return ('none', length)
    if inferred == 'floating' and all(value is None or type(value) is float for value in values):
        return ('float', np.asarray(lib.maybe_convert_objects(values, try_float=True), dtype=np.float64))
    if inferred == 'integer' and all(value is None or type(value) is int for value in values):
        nulls = np.fromiter((value is None for value in values), dtype=bool, count=length)
        try:
            present = np.array(values[~nulls].tolist(), dtype=np.int64)
        except OverflowError:
            return ('object', values)
        if not nulls.any():
            return ('int', present)
        integers = np.zeros(length, dtype=np.int64)
        integers[~nulls] = present
        return ('intnull', integers, nulls)
    if inferred == 'string' and all(value is None or type(value) is str for value in values):
        codes, categories = pd.factorize(values)
        return ('str', codes.astype(np.int32), np.asarray(categories, dtype=object))
    return ('object', values)


def part_length(part: tuple) -> int:
    return int(part[1]) if part[0] == 'none' else len(part[1])


def part_nbytes(part: tuple) -> int:
    if part[0] == 'none':
        return 64
    if part[0] == 'object':
        return len(part[1]) * 64
    size = sum(item.nbytes for item in part[1:] if isinstance(item, np.ndarray) and item.dtype != object)
    if part[0] == 'str':
        size += sum(len(str(value)) + 56 for value in part[2])
    return size + 64


def _subset_kind(part: tuple, positions: np.ndarray) -> str | None:
    if not len(positions):
        return None
    kind = part[0]
    if kind == 'float':
        return 'none' if np.isnan(part[1][positions]).all() else 'float'
    if kind == 'intnull':
        nulls = part[2][positions]
        return 'none' if nulls.all() else ('intnull' if nulls.any() else 'int')
    if kind == 'str':
        return 'none' if (part[1][positions] < 0).all() else 'str'
    return kind


def decode_objects(part: tuple, positions: np.ndarray) -> np.ndarray:
    """Return the selected values as the Python objects SQLite returned."""
    kind = part[0]
    if kind == 'none':
        return np.full(len(positions), None, dtype=object)
    if kind == 'float':
        values = part[1][positions]
        result = values.astype(object)
        result[np.isnan(values)] = None
        return result
    if kind == 'int':
        return part[1][positions].astype(object)
    if kind == 'intnull':
        result = part[1][positions].astype(object)
        result[part[2][positions]] = None
        return result
    if kind == 'str':
        codes = part[1][positions]
        missing = codes < 0
        if not len(part[2]):
            return np.full(len(positions), None, dtype=object)
        result = part[2].take(np.where(missing, 0, codes)).astype(object)
        result[missing] = None
        return result
    return np.asarray(part[1], dtype=object)[positions]


def assemble_column(pieces: Sequence[tuple[tuple, np.ndarray]]) -> np.ndarray:
    """Concatenate selected values with ``read_sql_query``'s type inference."""
    pieces = [(part, positions) for part, positions in pieces if len(positions)]
    total = sum(len(positions) for _part, positions in pieces)
    kinds = {_subset_kind(part, positions) for part, positions in pieces}
    if kinds == {'none'}:
        return np.full(total, None, dtype=object)
    numeric = {'float', 'int', 'intnull'}
    if kinds == {'int'}:
        return np.concatenate([part[1][positions] for part, positions in pieces])
    if kinds and kinds <= numeric | {'none'}:
        arrays = []
        for part, positions in pieces:
            kind = part[0]
            if kind == 'float':
                arrays.append(part[1][positions])
            elif kind in {'int', 'intnull'}:
                values = part[1][positions].astype(np.float64)
                if kind == 'intnull':
                    values[part[2][positions]] = np.nan
                arrays.append(values)
            else:
                arrays.append(np.full(len(positions), np.nan))
        return np.concatenate(arrays)
    objects = np.concatenate([decode_objects(part, positions) for part, positions in pieces]) if pieces else np.empty(0, dtype=object)
    if kinds and kinds <= {'str', 'none'}:
        return objects
    return convert_object_array([objects], dtype=None, coerce_float=True, dtype_backend='numpy')[0]


def frame_from_columns(columns: Sequence[str], arrays: Sequence[np.ndarray], rows: int) -> pd.DataFrame:
    """Build the frame exactly like ``pandas.read_sql_query`` does."""
    if not rows:
        return pd.DataFrame(columns=list(columns))
    frame = pd.DataFrame(dict(zip(range(len(columns)), arrays)))
    frame.columns = list(columns)
    return frame


def match_values(part: tuple, allowed: frozenset[str]) -> np.ndarray:
    """Rows whose text value is one of ``allowed``; NULL never matches."""
    if part[0] == 'str':
        accepted = np.fromiter((value in allowed for value in part[2]), dtype=bool, count=len(part[2]))
        codes = part[1]
        return np.where(codes >= 0, accepted[np.maximum(codes, 0)] if len(accepted) else False, False)
    if part[0] == 'none':
        return np.zeros(part_length(part), dtype=bool)
    values = decode_objects(part, np.arange(part_length(part)))
    return np.fromiter((value is not None and str(value) in allowed for value in values), dtype=bool, count=len(values))


def match_range(part: tuple, low: str | None, high: str | None) -> np.ndarray:
    """Rows whose text value lies within inclusive bounds; NULL never matches."""
    def accepted(value) -> bool:
        if value is None:
            return False
        text = str(value)
        return (low is None or text >= low) and (high is None or text <= high)

    if part[0] == 'str':
        allowed = np.fromiter((accepted(value) for value in part[2]), dtype=bool, count=len(part[2]))
        codes = part[1]
        return np.where(codes >= 0, allowed[np.maximum(codes, 0)] if len(allowed) else False, False)
    if part[0] == 'none':
        return np.zeros(part_length(part), dtype=bool)
    values = decode_objects(part, np.arange(part_length(part)))
    return np.fromiter((accepted(value) for value in values), dtype=bool, count=len(values))


def keep_sheets(part: tuple, excluded: frozenset[str]) -> np.ndarray:
    """``sheet IS NULL OR normalized sheet NOT IN excluded``."""
    if part[0] == 'str':
        rejected = np.fromiter((value in excluded for value in part[2]), dtype=bool, count=len(part[2]))
        codes = part[1]
        return np.where(codes >= 0, ~rejected[np.maximum(codes, 0)] if len(rejected) else True, True)
    if part[0] == 'none':
        return np.ones(part_length(part), dtype=bool)
    values = decode_objects(part, np.arange(part_length(part)))
    return np.fromiter((value is None or str(value) not in excluded for value in values), dtype=bool, count=len(values))


def _date_ranks(part: tuple) -> np.ndarray:
    """Rank event dates in index order (NULL first, then ascending text)."""
    if part[0] == 'str':
        categories = part[2]
        order = np.argsort(np.asarray([str(value) for value in categories], dtype=object), kind='stable')
        ranks = np.empty(len(categories), dtype=np.int64)
        ranks[order] = np.arange(len(categories))
        codes = part[1]
        return np.where(codes >= 0, ranks[np.maximum(codes, 0)] if len(ranks) else -1, -1)
    if part[0] == 'none':
        return np.full(part_length(part), -1, dtype=np.int64)
    values = decode_objects(part, np.arange(part_length(part)))
    texts = sorted({str(value) for value in values if value is not None})
    lookup = {text: rank for rank, text in enumerate(texts)}
    return np.fromiter((-1 if value is None else lookup[str(value)] for value in values), dtype=np.int64, count=len(values))


# ---------------------------------------------------------------------------
# Cache storage
# ---------------------------------------------------------------------------

@dataclass
class _Memory:
    budget: int
    parts: OrderedDict = field(default_factory=OrderedDict)
    size: int = 0


class ColumnCache:
    """Disk and memory cache of per-CDR expression columns."""

    def __init__(self, root: Path, *, memory_bytes: int, disk_bytes: int):
        self.root = Path(root) / f'v{CACHE_FORMAT_VERSION}'
        self.disk_bytes = disk_bytes
        self._memory = _Memory(memory_bytes)
        self._lock = threading.RLock()
        self._segment_locks: dict[tuple, threading.Lock] = {}
        self._writes = 0

    # -- paths --------------------------------------------------------------
    def _dataset_dir(self, source: CacheSource, dataset_id: int) -> Path:
        return self.root / re.sub(r'[^A-Za-z0-9_.-]', '_', source.table) / str(int(dataset_id))

    def _segment_dir(self, segment: Segment) -> Path:
        version = hashlib.sha256(segment.version.encode()).hexdigest()[:24]
        return self._dataset_dir(segment.source, segment.dataset_id) / version

    @staticmethod
    def _part_name(expression: str) -> str:
        return hashlib.sha256(expression.encode()).hexdigest()[:32] + '.pkl'

    # -- memory -------------------------------------------------------------
    def _remember(self, key: str, part: tuple) -> None:
        with self._lock:
            memory = self._memory
            previous = memory.parts.pop(key, None)
            if previous is not None:
                memory.size -= part_nbytes(previous)
            memory.parts[key] = part
            memory.size += part_nbytes(part)
            while memory.size > memory.budget and len(memory.parts) > 1:
                _old_key, old_part = memory.parts.popitem(last=False)
                memory.size -= part_nbytes(old_part)

    def _recall(self, key: str) -> tuple | None:
        with self._lock:
            part = self._memory.parts.get(key)
            if part is not None:
                self._memory.parts.move_to_end(key)
            return part

    def forget(self) -> None:
        with self._lock:
            self._memory.parts.clear()
            self._memory.size = 0

    # -- disk ---------------------------------------------------------------
    def _read_part(self, path: Path, expression: str, *, remember: bool = True) -> tuple | None:
        key = str(path)
        part = self._recall(key)
        if part is not None:
            return part
        try:
            payload = pickle.loads(path.read_bytes())
            # Recently used CDRs are the last ones removed by the disk budget.
            os.utime(path)
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ValueError):
            return None
        if not isinstance(payload, tuple) or len(payload) != 3 or payload[0] != CACHE_FORMAT_VERSION or payload[1] != expression:
            return None
        part = payload[2]
        if remember:
            self._remember(key, part)
        return part

    def _write_part(self, path: Path, expression: str, part: tuple, *, remember: bool = True) -> None:
        if remember:
            self._remember(str(path), part)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f'{path.name}.{uuid4().hex}.tmp')
            temporary.write_bytes(pickle.dumps((CACHE_FORMAT_VERSION, expression, part), protocol=pickle.HIGHEST_PROTOCOL))
            temporary.replace(path)
        except OSError:
            return
        self._writes += 1
        if self._writes % 64 == 0:
            self.prune()

    def prune(self) -> None:
        """Keep the cache within its disk budget, removing the oldest CDRs first."""
        if not self.root.is_dir():
            return
        segments = []
        total = 0
        for directory in self.root.glob('*/*/*'):
            if not directory.is_dir():
                continue
            files = list(directory.glob('*.pkl'))
            size = sum(path.stat().st_size for path in files if path.exists())
            stamp = max((path.stat().st_mtime for path in files if path.exists()), default=0.0)
            segments.append((stamp, size, directory))
            total += size
        for _stamp, size, directory in sorted(segments, key=lambda item: item[0]):
            if total <= self.disk_bytes:
                break
            shutil.rmtree(directory, ignore_errors=True)
            total -= size

    def _discard_other_versions(self, segment: Segment) -> None:
        current = self._segment_dir(segment)
        parent = current.parent
        if not parent.is_dir():
            return
        for directory in parent.iterdir():
            if directory != current and directory.is_dir():
                shutil.rmtree(directory, ignore_errors=True)

    def invalidate(self, segment: Segment) -> None:
        directory = self._segment_dir(segment)
        prefix = str(directory)
        with self._lock:
            for key in [key for key in self._memory.parts if key.startswith(prefix)]:
                self._memory.size -= part_nbytes(self._memory.parts.pop(key))
        shutil.rmtree(directory, ignore_errors=True)

    # -- segments -----------------------------------------------------------
    def _segment_lock(self, segment: Segment) -> threading.Lock:
        key = (segment.source.table, segment.dataset_id, segment.version)
        with self._lock:
            return self._segment_locks.setdefault(key, threading.Lock())

    def segment_parts(
        self,
        connect: Callable[[], sqlite3.Connection],
        segment: Segment,
        expressions: Iterable[str],
        prefetch: Iterable[str] = (),
    ) -> dict[str, tuple]:
        """Return the parts of physical expressions for one CDR, building missing ones.

        ``prefetch`` expressions are built together with missing ones, so a later
        Dashboard filter change finds them without another SQLite read.
        """
        wanted = list(dict.fromkeys([ROWID, ORDER_DATE, *expressions]))
        directory = self._segment_dir(segment)
        with self._segment_lock(segment):
            parts: dict[str, tuple] = {}
            missing = []
            for expression in wanted:
                part = self._read_part(directory / self._part_name(expression), expression)
                if part is None:
                    missing.append(expression)
                else:
                    parts[expression] = part
            if missing:
                extra = [expression for expression in dict.fromkeys(prefetch)
                         if expression not in parts and expression not in missing
                         and not (directory / self._part_name(expression)).is_file()]
                if ROWID in missing:
                    self._discard_other_versions(segment)
                built = self._build(connect, segment, [*missing, *extra], parts.get(ROWID))
                for expression, part in built.items():
                    self._write_part(directory / self._part_name(expression), expression, part)
                parts.update({expression: built[expression] for expression in missing})
            lengths = {part_length(part) for part in parts.values()}
            if len(lengths) > 1:
                raise StaleSegment(f'Cached columns of dataset {segment.dataset_id} are misaligned.')
            return parts

    def ensure(
        self,
        connect: Callable[[], sqlite3.Connection],
        segment: Segment,
        expressions: Iterable[str],
        prefetch: Iterable[str] = (),
    ) -> bool:
        """Build a CDR's missing expressions on disk only; return whether any was built.

        Background warming uses it, so it never evicts the columns of the
        universes in use from memory.
        """
        directory = self._segment_dir(segment)
        wanted = list(dict.fromkeys([ROWID, ORDER_DATE, *expressions, *prefetch]))
        with self._segment_lock(segment):
            missing = [expression for expression in wanted if not (directory / self._part_name(expression)).is_file()]
            if not missing:
                return False
            rowids = None
            if ROWID not in missing:
                rowids = self._read_part(directory / self._part_name(ROWID), ROWID, remember=False)
            if rowids is None:
                self._discard_other_versions(segment)
                missing = list(dict.fromkeys([ROWID, *missing]))
            built = self._build(connect, segment, missing, rowids)
            for expression, part in built.items():
                self._write_part(directory / self._part_name(expression), expression, part, remember=False)
            return True

    def _build(
        self, connect: Callable[[], sqlite3.Connection], segment: Segment,
        expressions: list[str], rowids: tuple | None,
    ) -> dict[str, tuple]:
        source = segment.source
        table = quote_identifier(source.table)
        values = [expression for expression in expressions if expression not in {ROWID, ORDER_DATE}]
        include_order = ROWID in expressions or ORDER_DATE in expressions or rowids is None
        batches = [values[start:start + BUILD_BATCH_SIZE] for start in range(0, len(values), BUILD_BATCH_SIZE)] or [[]]
        built: dict[str, tuple] = {}
        connection = connect()
        try:
            for batch_index, batch in enumerate(batches):
                order_date = ORDER_DATE_SQL if source.has_event_time else 'NULL'
                select = ['rowid', order_date, *(source.physical(expression) for expression in batch)]
                rows = connection.execute(
                    f'SELECT {", ".join(select)} FROM {table} WHERE "dataset_id" = ? ORDER BY rowid',
                    (int(segment.dataset_id),),
                ).fetchall()
                content = lib.to_object_array_tuples(rows) if rows else np.empty((0, len(select)), dtype=object)
                fetched_rowids = encode_values(np.ascontiguousarray(content[:, 0]))
                reference = rowids or built.get(ROWID)
                if reference is not None and not _same_part(reference, fetched_rowids):
                    raise StaleSegment(f'The rows of dataset {segment.dataset_id} changed while caching.')
                if batch_index == 0 and include_order:
                    built[ROWID] = fetched_rowids
                    built[ORDER_DATE] = encode_values(np.ascontiguousarray(content[:, 1]))
                for offset, expression in enumerate(batch, start=2):
                    built[expression] = encode_values(np.ascontiguousarray(content[:, offset]))
        finally:
            connection.close()
        return built


def _same_part(left: tuple, right: tuple) -> bool:
    if part_length(left) != part_length(right):
        return False
    if left[0] != right[0]:
        return False
    if left[0] == 'none':
        return True
    return np.array_equal(left[1], right[1])


# ---------------------------------------------------------------------------
# Frame assembly
# ---------------------------------------------------------------------------

def read_frame(
    cache: ColumnCache,
    connect: Callable[[], sqlite3.Connection],
    segments: Sequence[Segment],
    columns: Sequence[tuple[str, str]],
    terms: SelectionTerms,
    order: str,
    prefetch: Callable[[CacheSource], Iterable[str]] | None = None,
) -> pd.DataFrame:
    """Assemble the frame SQLite would return for the selection, in ``order``.

    ``columns`` holds ``(output name, expression)`` pairs over each source's
    column namespace. ``order`` is ``dataset_rowid`` (CDRs ascending, then table
    order), ``dataset_date_rowid`` (CDRs, event date, table order) or ``rowid``
    (table order across the CDRs of each source). Sources keep their given order.
    """
    if order not in ORDER_MODES:
        raise ValueError(f'Unsupported row order: {order}')
    names = [name for name, _expression in columns]
    per_column: list[list[tuple[tuple, np.ndarray]]] = [[] for _ in columns]
    groups: list[list[tuple[np.ndarray, np.ndarray]]] = []
    current_table = None
    for segment in segments:
        source = segment.source
        physical_columns = [source.physical(expression) for _name, expression in columns]
        physical_terms = [source.physical(expression) for expression in terms.expressions()]
        extra = [source.physical(expression) for expression in (prefetch(source) if prefetch else ())]
        parts = cache.segment_parts(connect, segment, [*physical_columns, *physical_terms], extra)
        mask = np.ones(part_length(parts[ROWID]), dtype=bool)
        for expression, allowed in terms.values:
            if expression is None:
                mask[:] = False
            else:
                mask &= match_values(parts[source.physical(expression)], allowed)
        if terms.date:
            expression, low, high = terms.date
            if expression is None:
                mask[:] = False
            else:
                mask &= match_range(parts[source.physical(expression)], low, high)
        if terms.excluded_sheets:
            expression, excluded = terms.excluded_sheets
            mask &= keep_sheets(parts[source.physical(expression)], excluded)
        positions = np.flatnonzero(mask)
        if order == 'dataset_date_rowid' and len(positions):
            ranks = _date_ranks(parts[ORDER_DATE])[positions]
            positions = positions[np.argsort(ranks, kind='stable')]
        for index, expression in enumerate(physical_columns):
            per_column[index].append((parts[expression], positions))
        rowids = parts[ROWID][1][positions] if parts[ROWID][0] in {'int', 'intnull'} else np.asarray(
            [int(value) for value in decode_objects(parts[ROWID], positions)], dtype=np.int64,
        )
        if source.table != current_table:
            groups.append([])
            current_table = source.table
        groups[-1].append((positions, rowids))
    total = sum(len(positions) for group in groups for positions, _rowids in group)
    arrays = [assemble_column(pieces) for pieces in per_column] if total else []
    if total and order == 'rowid':
        permutation = []
        offset = 0
        for group in groups:
            rowids = np.concatenate([item[1] for item in group]) if group else np.empty(0, dtype=np.int64)
            permutation.append(offset + np.argsort(rowids, kind='stable'))
            offset += len(rowids)
        permutation = np.concatenate(permutation)
        arrays = [array[permutation] for array in arrays]
    return frame_from_columns(names, arrays, total)


def default_memory_bytes() -> int:
    return int(os.environ.get('DASHBOARD_ANALYTIC_COLUMN_CACHE_MEMORY_MB') or 1024) * 1024 ** 2


def default_disk_bytes() -> int:
    return int(os.environ.get('DASHBOARD_ANALYTIC_COLUMN_CACHE_DISK_MB') or 8192) * 1024 ** 2
