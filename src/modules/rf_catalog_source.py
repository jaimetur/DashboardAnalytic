"""Pool RF observations from selected Data, Voice and Speech CDRs."""
from __future__ import annotations

import pandas as pd

from src.modules.column_names import column_identity
from src.modules.network_insights import RF_FIELD_ALIASES

RF_CATALOG_FIELDS = {
    'Latitude': 'latitude', 'Longitude': 'longitude',
    'LTE_RSRP': 'lte_rsrp', 'NR_RSRP': 'nr_rsrp',
    'LTE_SINR': 'lte_sinr', 'NR_SINR': 'nr_sinr',
}
RF_CDR_KINDS = ('data', 'voice', 'speech')


def rf_source_columns(kind: str) -> set[str]:
    """Return the physical dependencies of the combined RF source."""
    return {column for logical in RF_CATALOG_FIELDS.values() for column in RF_FIELD_ALIASES[logical][kind]}


def pool_rf_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Keep every observation and normalize radio fields without averaging types."""
    normalized = []
    for kind, frame in frames.items():
        if frame.empty:
            continue
        source = frame.copy(deep=False)
        lookup = {column_identity(column): column for column in frame.columns}
        for target, logical in RF_CATALOG_FIELDS.items():
            values = pd.Series(float('nan'), index=frame.index)
            for candidate in RF_FIELD_ALIASES[logical][kind]:
                actual = lookup.get(column_identity(candidate))
                if actual:
                    values = values.fillna(pd.to_numeric(frame[actual], errors='coerce'))
            source[target] = values
        source['CDR_Type'] = kind.title()
        normalized.append(source)
    combined = pd.concat(normalized, ignore_index=True) if normalized else pd.DataFrame()
    if normalized:
        combined.attrs = normalized[0].attrs.copy()
    return combined


class RFUnionSource(str):
    """The UNION ALL source text, plus its per-type branches for efficient queries.

    A filtered query over the compound subquery cannot use the per-dataset
    index and computes every column; querying each branch separately can.
    """

    branches: tuple[str, ...] = ()
    # (kind, physical table, ((alias, physical SQL), ...)) for each branch.
    branch_projections: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = ()


def rf_union_source(repository, kinds: list[str]) -> tuple[str, list[str]]:
    """Build a read-only UNION ALL over materialized CDR tables, retaining raw samples."""
    schemas = {kind: repository.list_reporting_row_columns(kind) for kind in kinds}
    columns_by_identity = {}
    for columns in schemas.values():
        for column in columns:
            columns_by_identity.setdefault(column_identity(column), column)
    columns_by_identity.update({column_identity(column): column for column in (*RF_CATALOG_FIELDS, 'CDR_Type')})
    columns = list(columns_by_identity.values())
    quote = repository._quote_identifier
    queries = []
    projections = []
    for kind, schema in schemas.items():
        lookup = {column_identity(column): column for column in schema}
        expressions = []
        projection = []
        for target in columns:
            if target in RF_CATALOG_FIELDS:
                candidates = [lookup[column_identity(candidate)] for candidate in RF_FIELD_ALIASES[RF_CATALOG_FIELDS[target]][kind]
                              if column_identity(candidate) in lookup]
                terms = [f"NULLIF(TRIM(CAST({quote(column)} AS TEXT)), '')" for column in candidates]
                expression = f'COALESCE({", ".join(terms)})' if len(terms) > 1 else (terms[0] if terms else 'NULL')
            elif target == 'CDR_Type':
                expression = "'" + kind.title() + "'"
            else:
                actual = lookup.get(column_identity(target))
                expression = quote(actual) if actual else 'NULL'
            expressions.append(f'{expression} AS {quote(target)}')
            projection.append((target, expression))
        queries.append(f'SELECT {", ".join(expressions)} FROM {quote(repository.reporting_rows_table_name(kind))}')
        projections.append((kind, repository.reporting_rows_table_name(kind), tuple(projection)))
    source = RFUnionSource('(' + ' UNION ALL '.join(queries) + ')')
    source.branches = tuple(queries)
    source.branch_projections = tuple(projections)
    return source, columns
