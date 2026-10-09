"""Network Insights: radio quality, observed sites, spectrum and deployment.

The analysis reads the per-sample radio fields already present in the CDRs
(RSRP, SINR, serving cells, frequencies and coordinates) together with the
workspace's Operator mappings, the cell inventories uploaded as Vendor
mapping datasets and the licensed spectrum holdings configured in Workspace
Config. Every function below is free of web-framework dependencies so it can
be tested directly.
"""
# Postponed annotations are deliberately not enabled: FastAPI must resolve the
# request models and parameters declared inside install_network_insights_routes.
import csv
import io
import math
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from typing import Any, Callable, Iterable
from uuid import uuid4

import numpy as np
import pandas as pd

from src.modules.column_names import campaign_sort_key, column_identity, compact_campaign_value, operator_vendor_filter_values, vendor_filter_values
from src.modules.mapping_order import swap_operator_vendor, swap_vendor_operator
from src.modules.value_maps import ValueMapper, field_kind
from src.modules.mapping_order import dimension_order_key
from src.modules.output_layout import NETWORK_INSIGHTS_FOLDER, module_output_dir


NETWORK_INSIGHTS_KINDS = ('data', 'voice', 'speech')
# Bump when the normalised samples or the analysis payload change shape.
SAMPLES_CACHE_VERSION = 4
ANALYSIS_CACHE_VERSION = 6
INVENTORY_CACHE_VERSION = 4
OBSERVED_CACHE_VERSION = 8
# Columns of the Observed Sites/Cells (from CDRs) tables.
OBSERVED_COLUMNS = (
    'Operator', 'Vendor', 'Region', 'Cluster', 'City', 'Technology', 'Site_ID', 'Cell_ID', 'Band',
    'CDR_Types', 'Campaigns', 'Samples', 'Latitude', 'Longitude', 'RSRP_Mean', 'SINR_Mean',
)
SPECTRUM_HOLDINGS_STATE_KEY = 'network_spectrum_holdings'

# Each logical radio field lists, per CDR type, the source columns that carry
# it in priority order. Voice uses the measuring (A) side.
RF_FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    'latitude': {
        'data': ('Test_Start_Latitude',), 'voice': ('Call_Start_Latitude_A',), 'speech': ('Playing_Latitude', 'Recording_Latitude'),
    },
    'longitude': {
        'data': ('Test_Start_Longitude',), 'voice': ('Call_Start_Longitude_A',), 'speech': ('Playing_Longitude', 'Recording_Longitude'),
    },
    'lte_rsrp': {
        'data': ('LTE_PCell_RSRP_Avg',), 'voice': ('4G_RSRP_Avg_A',), 'speech': ('Playing_RSRP_Avg', 'Recording_RSRP_Avg'),
    },
    'nr_rsrp': {
        'data': ('NR_PCell_RSRP_Avg',), 'voice': ('NR_RSRP_Avg_A',), 'speech': ('Playing_RSRP_NR_Avg', 'Recording_RSRP_NR_Avg'),
    },
    'lte_sinr': {
        'data': ('LTE_PCell_SINR_Avg',), 'voice': ('4G_SINR_Avg_A',), 'speech': ('Playing_SINR_Avg', 'Recording_SINR_Avg'),
    },
    'nr_sinr': {
        'data': ('NR_PCell_SINR_Avg',), 'voice': ('NR_SINR_Avg_A',), 'speech': ('Playing_SINR_NR_Avg', 'Recording_SINR_NR_Avg'),
    },
    'cell_trace': {
        'data': ('LAC_CID_xARFCN',), 'voice': ('LAC_CID_xARFCN_A',), 'speech': (),
    },
    'cell_ids': {
        'data': ('Cell_ID',), 'voice': ('Cell_ID_A',), 'speech': ('Cell_IDs_A',),
    },
    'enodeb_id': {
        'data': (), 'voice': (), 'speech': ('Playing_eNodeBId', 'Recording_eNodeBId'),
    },
    'earfcn': {
        'data': ('LTE_PCC_EARFCN',), 'voice': ('E/U/ARFCN_A',), 'speech': ('ARFCN_A',),
    },
    'nr_band': {
        'data': ('NR_DL_PCell_Band',), 'voice': ('NR_BAND_A',), 'speech': (),
    },
    'lte_bandwidth': {
        'data': ('LTE_DL_PCell_Bandwidth',), 'voice': (), 'speech': (),
    },
    'nr_bandwidth': {
        'data': ('NR_DL_PCell_Bandwidth',), 'voice': (), 'speech': (),
    },
}
DIMENSION_ALIASES = {
    'operator': ('Operator',),
    'operator_vendor': ('Operator_Vendor',),
    'vendor': ('Vendor',),
    'campaign': ('Campaign', 'Period'),
    'region': ('Region', 'G_Level_2'),
    'cluster': ('Cluster',),
    'city': ('City', 'G_Level_4'),
    'source_sheet': ('source_sheet',),
}
GROUPINGS = {'operator': 'Operator', 'vendor': 'Vendor', 'region': 'Region', 'cluster': 'Cluster', 'city': 'City', 'kind': 'CDR type', 'technology': 'Technology', 'campaign': 'Campaign'}
TECHNOLOGIES = {'lte': 'LTE', 'nr': 'NR', 'lte_nr': 'LTE+NR'}

# Default classification bands. Thresholds are user-adjustable in the module;
# these defaults follow common drive-test reporting practice.
# LTE RSRP/SINR and NR SS-RSRP/SS-SINR use different reference signals, so
# each technology has its own thresholds.
DEFAULT_COVERAGE_THRESHOLD = -110.0
DEFAULT_INTERFERENCE_THRESHOLD = 0.0
DEFAULT_NR_COVERAGE_THRESHOLD = -115.0
DEFAULT_NR_INTERFERENCE_THRESHOLD = -3.0
RSRP_CLASSES = (
    ('Excellent', -80.0, '#2E8B57'),
    ('Good', -90.0, '#8BC34A'),
    ('Fair', -100.0, '#F2C230'),
    ('Poor', -110.0, '#F08A24'),
    ('Very poor', float('-inf'), '#D7263D'),
)
SINR_CLASSES = (
    ('Excellent', 20.0, '#2E8B57'),
    ('Good', 13.0, '#8BC34A'),
    ('Fair', 5.0, '#F2C230'),
    ('Poor', 0.0, '#F08A24'),
    ('Bad', float('-inf'), '#D7263D'),
)
OPERATOR_FALLBACK_COLOURS = ('#6D46A8', '#0B7A75', '#D9480F', '#1C7ED6', '#C2255C', '#5C940D', '#E67700', '#495057')
SERIES_DASHES = ([], [12, 8], [3, 6], [16, 6, 3, 6])

# 3GPP downlink EARFCN ranges (TS 36.101) and NR band centre frequencies used
# to classify the spectrum each sample was served on.
LTE_EARFCN_BANDS = (
    (1, 0, 599), (3, 1200, 1949), (7, 2750, 3449), (8, 3450, 3799), (20, 6150, 6449),
    (28, 9210, 9659), (32, 9920, 10359), (38, 37750, 38249), (40, 38650, 39649),
    (41, 39650, 41589), (42, 41590, 43589), (43, 43590, 45589),
)
BAND_CATALOGUE: dict[str, tuple[int, str]] = {
    'B1': (2100, 'FDD'), 'B3': (1800, 'FDD'), 'B7': (2600, 'FDD'), 'B8': (900, 'FDD'), 'B20': (800, 'FDD'),
    'B28': (700, 'FDD'), 'B32': (1500, 'SDL'), 'B38': (2600, 'TDD'), 'B40': (2300, 'TDD'), 'B41': (2500, 'TDD'),
    'B42': (3500, 'TDD'), 'B43': (3700, 'TDD'),
    'n1': (2100, 'FDD'), 'n3': (1800, 'FDD'), 'n7': (2600, 'FDD'), 'n8': (900, 'FDD'), 'n20': (800, 'FDD'),
    'n28': (700, 'FDD'), 'n38': (2600, 'TDD'), 'n40': (2300, 'TDD'), 'n41': (2500, 'TDD'), 'n77': (3700, 'TDD'),
    'n78': (3500, 'TDD'), 'n258': (26000, 'TDD'),
}
BAND_CLASSES = ('Low', 'Mid', 'High (TDD)')
SPECTRUM_DUPLEX_VALUES = ('FDD', 'TDD', 'SDL')

_TRACE_TOKEN = re.compile(r'\[\s*(LTE E-UTRA|NR|UMTS|GSM)[^,\]]*?\s(\d+)?\s*,\s*([^,\]]*)\s*,\s*([^,\]]*)\s*,\s*([^,\]]*)\]', re.I)
_NUMBER = re.compile(r'-?\d+(?:\.\d+)?')


def band_class(band: str) -> str:
    """Return Low, Mid or High (TDD) for an LTE (``B3``) or NR (``n78``) band."""
    details = BAND_CATALOGUE.get(str(band).strip())
    if not details:
        return ''
    frequency, duplex = details
    if frequency < 1000:
        return 'Low'
    if duplex == 'TDD':
        return 'High (TDD)'
    return 'Mid'


def lte_band_for_earfcn(value: object) -> str:
    """Map an LTE downlink EARFCN to its band label, for example ``B3``."""
    try:
        earfcn = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return ''
    for band, low, high in LTE_EARFCN_BANDS:
        if low <= earfcn <= high:
            return f'B{band}'
    return ''


def sequence_values(value: object) -> list[str]:
    """Split ``[a]->[b]`` or ``a->b`` sequences into their values."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    text = str(value).strip()
    if not text or text.casefold() in {'nan', 'none', '<na>'}:
        return []
    return [part.strip(' []') for part in text.split('->') if part.strip(' []')]


def lte_enodeb_from_eci(value: object) -> int | None:
    """Return the physical eNodeB of an LTE E-UTRAN Cell Identity (ECI // 256)."""
    try:
        eci = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    # Smaller identities are 2G/3G cell IDs, which carry no eNodeB.
    return eci // 256 if eci > 65535 else None


def parse_cell_trace(value: object) -> list[dict[str, Any]]:
    """Parse ``[LTE E-UTRA 7, TAC, ECI, EARFCN]->[...]`` serving-cell traces."""
    cells = []
    for match in _TRACE_TOKEN.finditer(str(value or '')):
        technology, band_number, _area, cell, channel = match.groups()
        technology = technology.upper()
        band = ''
        if technology.startswith('LTE'):
            band = f'B{band_number}' if band_number else lte_band_for_earfcn(channel)
        cells.append({'technology': 'LTE' if technology.startswith('LTE') else technology, 'band': band,
                      'cell': str(cell).strip(), 'channel': str(channel).strip()})
    return cells


def nr_band_label(value: object) -> str:
    """Return ``n78`` for ``NR BAND 78`` (first band of a sequence)."""
    for item in sequence_values(value):
        number = re.search(r'(\d+)', item)
        if number:
            return f'n{number.group(1)}'
    return ''


def enodeb_label(value: object) -> str:
    """Normalise Speech eNodeB identifiers such as ``L 601983``."""
    for item in sequence_values(value):
        number = re.search(r'(\d+)', item)
        if number:
            return number.group(1)
    return ''


def classify(value: float, classes: tuple[tuple[str, float, str], ...]) -> tuple[str, str]:
    """Return the (label, colour) of the first class whose lower bound is reached."""
    for label, lower, colour in classes:
        if value >= lower:
            return label, colour
    return classes[-1][0], classes[-1][2]


def resolve_source_columns(available: Iterable[str], kind: str) -> dict[str, str]:
    """Pick, for one CDR type, the source column carrying each logical field."""
    lookup = {column_identity(column): str(column) for column in available}
    resolved: dict[str, str] = {}
    for field, aliases in DIMENSION_ALIASES.items():
        column = next((lookup[column_identity(alias)] for alias in aliases if column_identity(alias) in lookup), None)
        if column:
            resolved[field] = column
    for field, by_kind in RF_FIELD_ALIASES.items():
        column = next((lookup[column_identity(alias)] for alias in by_kind.get(kind, ()) if column_identity(alias) in lookup), None)
        if column:
            resolved[field] = column
    return resolved


def normalise_samples(frame: pd.DataFrame, kind: str, columns: dict[str, str]) -> pd.DataFrame:
    """Return one tidy row per CDR sample with the logical radio fields."""
    result = pd.DataFrame(index=frame.index)
    result['kind'] = kind.title()
    for field in ('operator', 'operator_vendor', 'vendor', 'campaign', 'region', 'cluster', 'city'):
        source = columns.get(field)
        values = frame[source] if source in frame.columns else pd.Series('', index=frame.index)
        result[field] = values.fillna('').astype(str).str.strip()
    campaigns = {value: compact_campaign_value(value) or value for value in pd.unique(result['campaign'])}
    result['campaign'] = result['campaign'].map(campaigns)
    groups = [{'canonical': name} for name in pd.unique(result['operator']) if name]
    swapped = {value: swap_operator_vendor(value, groups) for value in pd.unique(result['operator_vendor'])}
    result['vendor_operator'] = result['operator_vendor'].map(swapped)
    for field in ('latitude', 'longitude', 'lte_rsrp', 'nr_rsrp', 'lte_sinr', 'nr_sinr', 'lte_bandwidth', 'nr_bandwidth'):
        source = columns.get(field)
        result[field] = pd.to_numeric(frame[source], errors='coerce') if source in frame.columns else math.nan
    # Values outside physical ranges are measurement placeholders.
    for field, low, high in (('lte_rsrp', -160, -20), ('nr_rsrp', -160, -20), ('lte_sinr', -30, 50), ('nr_sinr', -30, 50)):
        result.loc[(result[field] < low) | (result[field] > high), field] = math.nan
    result.loc[(result['latitude'].abs() > 90) | (result['latitude'] == 0), 'latitude'] = math.nan
    result.loc[(result['longitude'].abs() > 180) | (result['longitude'] == 0), 'longitude'] = math.nan

    # Traces repeat heavily across samples: parse each distinct value once.
    def parsed_column(field: str, parser) -> pd.Series:
        source = columns.get(field)
        if source not in frame.columns:
            return pd.Series([None] * len(frame), index=frame.index, dtype=object)
        values = frame[source].astype(object).where(frame[source].notna(), '')
        cache = {value: parser(value) for value in pd.unique(values)}
        return values.map(cache)

    def trace_cells(value: object) -> tuple[tuple[str, ...], tuple[str, ...], str]:
        cells, enodebs, band = [], [], ''
        for cell in parse_cell_trace(value):
            if cell['technology'] != 'LTE':
                continue
            band = band or cell['band']
            cells.append(cell['cell'])
            enodeb = lte_enodeb_from_eci(cell['cell'])
            if enodeb is not None:
                enodebs.append(str(enodeb))
        return tuple(dict.fromkeys(cells)), tuple(dict.fromkeys(enodebs)), band

    def id_cells(value: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
        cells = tuple(dict.fromkeys(sequence_values(value)))
        enodebs = tuple(dict.fromkeys(str(item) for item in map(lte_enodeb_from_eci, cells) if item is not None))
        return cells, enodebs

    traces = parsed_column('cell_trace', trace_cells)
    ids = parsed_column('cell_ids', id_cells)
    speech_enodebs = parsed_column('enodeb_id', enodeb_label)
    earfcn_bands = parsed_column('earfcn', lambda value: lte_band_for_earfcn((sequence_values(value) or [''])[0]))
    cells_column, enodebs_column, bands_column = [], [], []
    for trace, identified, speech_enodeb, earfcn_band in zip(traces, ids, speech_enodebs, earfcn_bands, strict=True):
        cells, enodebs, band = trace if trace else ((), (), '')
        if not cells and identified:
            cells, enodebs = identified
        if speech_enodeb:
            enodebs = (speech_enodeb,)
        # Tuples are shared with the parse cache, keeping memory flat.
        cells_column.append(cells)
        enodebs_column.append(enodebs)
        bands_column.append(band or earfcn_band or '')
    result['cells'] = cells_column
    result['enodebs'] = enodebs_column
    result['lte_band'] = bands_column
    nr_source = columns.get('nr_band')
    result['nr_band'] = frame[nr_source].map(nr_band_label) if nr_source in frame.columns else ''
    return result.reset_index(drop=True)


def _quantile(values: pd.Series, q: float) -> float | None:
    return round(float(values.quantile(q)), 2) if len(values) else None


def _share(mask: pd.Series) -> float | None:
    return round(float(mask.mean()) * 100, 1) if len(mask) else None


def rf_summary(
    samples: pd.DataFrame, technology: str, group: str | None,
    coverage_threshold: float, interference_threshold: float,
) -> list[dict[str, Any]]:
    """Summarise RSRP/SINR and observed sites per Operator (and group)."""
    rsrp, sinr = f'{technology}_rsrp', f'{technology}_sinr'
    keys = ['operator', *([group] if group else [])]
    rows = []
    for key, part in samples.groupby(keys, sort=False, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        rsrp_values = part[rsrp].dropna()
        sinr_values = part[sinr].dropna()
        enodebs = set(chain.from_iterable(part['enodebs']))
        cells = set(chain.from_iterable(part['cells']))
        rows.append({
            'operator': key[0], 'group': key[1] if group else '',
            'samples': int(len(part)),
            'rsrp_samples': int(len(rsrp_values)),
            'rsrp_mean': round(float(rsrp_values.mean()), 2) if len(rsrp_values) else None,
            'rsrp_median': _quantile(rsrp_values, .5), 'rsrp_p10': _quantile(rsrp_values, .1),
            'low_coverage_share': _share(rsrp_values < coverage_threshold),
            'rsrp_classes': class_distribution(rsrp_values, RSRP_CLASSES),
            'sinr_samples': int(len(sinr_values)),
            'sinr_mean': round(float(sinr_values.mean()), 2) if len(sinr_values) else None,
            'sinr_median': _quantile(sinr_values, .5), 'sinr_p10': _quantile(sinr_values, .1),
            'high_interference_share': _share(sinr_values < interference_threshold),
            'sinr_classes': class_distribution(sinr_values, SINR_CLASSES),
            'observed_enodebs': len(enodebs), 'observed_cells': len(cells),
        })
    return rows


def class_distribution(values: pd.Series, classes: tuple[tuple[str, float, str], ...]) -> list[dict[str, Any]]:
    """Return the share of samples in each quality class, best first."""
    if not len(values):
        return []
    numbers = values.to_numpy(dtype=float)
    # Each value belongs to the first class whose lower bound it reaches.
    remaining = np.ones(len(numbers), dtype=bool)
    shares = []
    for label, lower, colour in classes:
        reached = remaining & (numbers >= lower) if not math.isinf(lower) else remaining
        shares.append({'label': label, 'colour': colour, 'share': round(int(reached.sum()) / len(numbers) * 100, 1)})
        remaining &= ~reached
    return shares


def operator_colours(operators: Iterable[str], mapping_groups: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Use the workspace Operator Map colours, with a stable fallback palette."""
    configured = {
        str(group.get('canonical') or '').strip().casefold(): str(group.get('color') or '').strip()
        for group in mapping_groups or []
    }
    colours = {}
    for index, operator in enumerate(dict.fromkeys(operators)):
        colour = configured.get(str(operator).casefold())
        colours[operator] = colour if re.fullmatch(r'#[0-9a-fA-F]{6}', colour or '') else OPERATOR_FALLBACK_COLOURS[index % len(OPERATOR_FALLBACK_COLOURS)]
    return colours


def cdf_payload(
    samples: pd.DataFrame, value_column: str, group: str | None, title: str, metric_label: str,
    colours: dict[str, str], *, points: int = 120, dash_groups: dict[str, str] | None = None,
    widths: dict[str, int] | None = None, order_key: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Build a Canvas CDF model (one curve per Operator and group).

    ``dash_groups`` maps each Operator label to its secondary grouping value,
    so curves sharing an Operator colour use a different line style per value.
    ``widths`` maps each label to its line width (newer campaigns are thicker).
    ``order_key`` orders the curves by their Operator label (see ``mapping_order``).
    """
    dash_values = sorted(set(dash_groups.values()), key=str.casefold) if dash_groups else []
    series = []
    legend = []
    keys = ['operator', *([group] if group else [])]
    lows, highs = [], []
    group_values = list(dict.fromkeys(samples[group])) if group else []
    grouped = [(key if isinstance(key, tuple) else (key,), part) for key, part in samples.groupby(keys, sort=False, dropna=False)]
    if order_key:
        grouped.sort(key=lambda item: order_key(str(item[0][0])))
    for key, part in grouped:
        values = part[value_column].dropna().sort_values()
        if values.empty:
            continue
        quantiles = [index / (points - 1) for index in range(points)]
        x = [round(float(value), 2) for value in np.quantile(values.to_numpy(dtype=float), quantiles)]
        lows.append(x[0]); highs.append(x[-1])
        name = ' · '.join(str(item) for item in key if str(item))
        if group:
            dash = SERIES_DASHES[group_values.index(key[1]) % len(SERIES_DASHES)]
        elif dash_groups and key[0] in dash_groups:
            dash = SERIES_DASHES[dash_values.index(dash_groups[key[0]]) % len(SERIES_DASHES)]
        else:
            dash = []
        colour = colours.get(key[0], OPERATOR_FALLBACK_COLOURS[0])
        width = (widths or {}).get(key[0], 3)
        series.append({'name': name, 'colour': colour, 'width': width, 'dash': dash, 'x': x, 'y': quantiles})
        legend.append({'label': name, 'colour': colour, 'width': width, 'dash': dash})
    domain_x = [min(lows), max(highs)] if lows else [0, 1]
    if domain_x[0] == domain_x[1]:
        domain_x = [domain_x[0] - 1, domain_x[1] + 1]
    return {
        'renderer': 'catalog-v2', 'width': 1600, 'height': 900, 'type': 'cdf' if series else 'empty',
        'title': title, 'metric': metric_label,
        'message': 'No samples are available for this selection.',
        'legend': {'position': 'right', 'line_markers': True, 'items': legend},
        'label_position': '', 'label_format': {}, 'legend_format': {},
        'axis_ranges': {'x': [None, None], 'y': [None, None]},
        'domain': {'x': domain_x, 'y': [0, 1]},
        'series': series,
    }


def campaign_line_widths(campaigns: dict[str, str], families: dict[str, str]) -> dict[str, int]:
    """Line width per label: the latest campaign of each Operator/Vendor is the thickest.

    Like the PPT Dashboard CDFs, two campaigns use widths 1 and 4 and longer
    histories thin out by one per older campaign.
    """
    from src.modules.cdr_reporting import _campaign_sort_key

    by_family: dict[str, set[str]] = {}
    for label, campaign in campaigns.items():
        if campaign:
            by_family.setdefault(families.get(label, ''), set()).add(campaign)
    ranks: dict[str, dict[str, int]] = {}
    for family, values in by_family.items():
        ordered = sorted(values, key=_campaign_sort_key)
        if len(ordered) == 2:
            ranks[family] = {ordered[0]: 1, ordered[1]: 4}
        else:
            ranks[family] = {campaign: max(1, 4 - index) for index, campaign in enumerate(reversed(ordered))}
    return {label: ranks.get(families.get(label, ''), {}).get(campaign, 3) for label, campaign in campaigns.items()}


def grid_cells(
    samples: pd.DataFrame, value_column: str, threshold: float, grid_metres: float, min_samples: int,
) -> tuple[pd.DataFrame, float]:
    """Aggregate samples into square grid cells; coarsen very dense grids."""
    located = samples.dropna(subset=['latitude', 'longitude', value_column])
    if located.empty:
        return pd.DataFrame(), grid_metres
    effective = max(25.0, float(grid_metres))
    reference_latitude = math.radians(float(located['latitude'].median()))
    while True:
        latitude_step = effective / 111_320
        longitude_step = effective / (111_320 * max(math.cos(reference_latitude), 0.2))
        frame = located.assign(
            row=(located['latitude'] / latitude_step).round().astype('int64'),
            column=(located['longitude'] / longitude_step).round().astype('int64'),
            bad=located[value_column] < threshold,
        )
        cells = frame.groupby(['row', 'column'], sort=False).agg(
            samples=(value_column, 'size'), mean=(value_column, 'mean'), bad_share=('bad', 'mean'),
        ).reset_index()
        cells = cells.loc[cells['samples'] >= max(1, int(min_samples))]
        # The most frequent City and Region of each grid cell.
        for field in ('city', 'region'):
            counts = frame.groupby(['row', 'column', field], sort=False).size().reset_index(name='count')
            counts = counts.sort_values('count', ascending=False, kind='stable').drop_duplicates(['row', 'column'])
            cells = cells.merge(counts[['row', 'column', field]], on=['row', 'column'], how='left')
            cells[field] = cells[field].fillna('')
        cells = cells.loc[cells['samples'] >= max(1, int(min_samples))]
        if len(cells) <= 12_000 or effective >= 5_000:
            break
        effective *= 2
    cells['latitude'] = cells['row'] * latitude_step
    cells['longitude'] = cells['column'] * longitude_step
    cells['bad_share'] = (cells['bad_share'] * 100).round(1)
    cells['mean'] = cells['mean'].round(2)
    return cells.reset_index(drop=True), effective


def hotspots(cells: pd.DataFrame, limit: int = 25) -> list[dict[str, Any]]:
    """Rank grid cells by how many samples fall below the threshold."""
    if cells.empty:
        return []
    ranked = cells.assign(weight=cells['samples'] * cells['bad_share']).loc[cells['bad_share'] >= 50]
    ranked = ranked.sort_values(['weight', 'bad_share'], ascending=False).head(limit)
    return [
        {
            'latitude': round(float(row.latitude), 6), 'longitude': round(float(row.longitude), 6),
            'samples': int(row.samples), 'mean': float(row.mean), 'bad_share': float(row.bad_share),
            'city': str(row.city), 'region': str(row.region),
        }
        for row in ranked.itertuples()
    ]


def map_payload(
    cells: pd.DataFrame, classes: tuple[tuple[str, float, str], ...], title: str, unit: str,
    geometry: Any,
) -> dict[str, Any]:
    """Build a Canvas map model with one coloured series per quality class."""
    if cells.empty:
        return {'renderer': 'catalog-v2', 'width': 1600, 'height': 900, 'type': 'empty', 'title': title,
                'message': 'No located samples are available for this selection.'}
    series = []
    for index, (label, lower, colour) in enumerate(classes):
        upper = classes[index - 1][1] if index else None
        if math.isinf(lower):
            name = f'{label} (< {upper:g} {unit})'
        elif upper is None:
            name = f'{label} (≥ {lower:g} {unit})'
        else:
            name = f'{label} ({lower:g} to {upper:g} {unit})'
        mask = cells['mean'] >= lower
        if upper is not None:
            mask &= cells['mean'] < upper
        part = cells.loc[mask]
        series.append({'name': name, 'colour': colour, 'points': [
            [round(float(longitude), 6), round(float(latitude), 6)]
            for longitude, latitude in zip(part['longitude'], part['latitude'], strict=True)
        ]})
    lon_low, lon_high = float(cells['longitude'].min()), float(cells['longitude'].max())
    lat_low, lat_high = float(cells['latitude'].min()), float(cells['latitude'].max())
    lon_padding = max((lon_high - lon_low) * .06, .004)
    lat_padding = max((lat_high - lat_low) * .06, .004)
    zoom, tile_left, tile_top, tile_right, tile_bottom, top_left, bottom_right = geometry(
        lon_low - lon_padding, lon_high + lon_padding, lat_low - lat_padding, lat_high + lat_padding,
    )
    return {
        'renderer': 'catalog-v2', 'width': 1600, 'height': 900, 'type': 'map', 'title': title,
        'legend': {'position': 'right', 'line_markers': False, 'items': [
            {'label': item['name'], 'colour': item['colour']} for item in series
        ]},
        'label_position': 'None', 'label_format': {}, 'legend_format': {},
        'axis_ranges': {'x': [None, None], 'y': [None, None]},
        'x_label': 'Longitude', 'y_label': 'Latitude', 'point_radius': 6,
        'domain': {'x': [lon_low, lon_high], 'y': [lat_low, lat_high]},
        'basemap': {
            'provider': 'OpenStreetMap', 'url_template': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            'attribution': '© OpenStreetMap contributors', 'zoom': zoom,
            'tile_range': [tile_left, tile_top, tile_right, tile_bottom],
            'world_bounds': [*top_left, *bottom_right], 'tile_size': 256,
        },
        'series': series,
    }


def observed_spectrum(samples: pd.DataFrame) -> list[dict[str, Any]]:
    """Share of samples served on each band, with the typical DL bandwidth."""
    rows = []
    for technology, band_column, bandwidth_column in (('LTE', 'lte_band', 'lte_bandwidth'), ('NR', 'nr_band', 'nr_bandwidth')):
        located = samples.loc[samples[band_column].astype(str) != '']
        for operator, part in located.groupby('operator', sort=False):
            total = len(part)
            for band, band_part in part.groupby(band_column, sort=False):
                bandwidths = band_part[bandwidth_column].dropna()
                rows.append({
                    'operator': operator, 'technology': technology, 'band': band,
                    'band_class': band_class(band),
                    'frequency_mhz': BAND_CATALOGUE.get(band, (None, ''))[0],
                    'duplex': BAND_CATALOGUE.get(band, (None, ''))[1],
                    'share': round(len(band_part) / total * 100, 1),
                    'samples': int(len(band_part)),
                    'typical_bandwidth_mhz': float(bandwidths.mode().iloc[0]) if len(bandwidths) else None,
                })
    order = {name: index for index, name in enumerate(BAND_CATALOGUE)}
    return sorted(rows, key=lambda row: (row['operator'], row['technology'], order.get(row['band'], 999)))


def normalise_spectrum_holdings(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Validate licensed spectrum rows (Operator, band, duplex, class, MHz)."""
    result = []
    for index, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            raise ValueError(f'Spectrum holding {index} is invalid.')
        operator = str(row.get('operator') or '').strip()
        band = str(row.get('band') or '').strip()
        if not operator or not band:
            raise ValueError(f'Spectrum holding {index} needs an Operator and a band.')
        duplex = str(row.get('duplex') or BAND_CATALOGUE.get(band, (0, 'FDD'))[1] or 'FDD').strip().upper()
        if duplex not in SPECTRUM_DUPLEX_VALUES:
            raise ValueError(f'Spectrum holding {index} has an unsupported duplex mode "{duplex}".')
        klass = str(row.get('band_class') or band_class(band) or '').strip()
        klass = next((item for item in BAND_CLASSES if item.casefold() == klass.casefold()), '')
        if not klass:
            raise ValueError(f'Spectrum holding {index} needs a band class: Low, Mid or High (TDD).')
        try:
            bandwidth = float(str(row.get('bandwidth_mhz')).strip())
        except (TypeError, ValueError):
            raise ValueError(f'Spectrum holding {index} needs a bandwidth in MHz.') from None
        if not math.isfinite(bandwidth) or bandwidth <= 0:
            raise ValueError(f'Spectrum holding {index} needs a positive bandwidth in MHz.')
        result.append({
            'operator': operator, 'band': band, 'duplex': duplex, 'band_class': klass,
            'bandwidth_mhz': round(bandwidth, 3), 'notes': str(row.get('notes') or '').strip(),
        })
    return result


SPECTRUM_CSV_HEADER = ('Operator', 'Band', 'Duplex', 'Band Class', 'Bandwidth MHz', 'Notes')


def parse_spectrum_csv(text: str) -> list[dict[str, Any]]:
    """Read ``Operator,Band,Duplex,Band Class,Bandwidth MHz,Notes`` rows.

    Comma, semicolon and tab separators are accepted, so rows pasted from a
    spreadsheet work as well.
    """
    import csv
    from io import StringIO

    text = str(text or '').strip()
    if not text:
        return []
    header = text.splitlines()[0]
    delimiter = '\t' if '\t' in header else ';' if header.count(';') > header.count(',') else ','
    reader = csv.DictReader(StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError('Paste a CSV with an Operator,Band,Duplex,Band Class,Bandwidth MHz,Notes header.')
    columns = {column_identity(name): name for name in reader.fieldnames}

    def value(row: dict[str, Any], *names: str) -> str:
        return next((str(row.get(columns[column_identity(name)]) or '') for name in names if column_identity(name) in columns), '')

    return normalise_spectrum_holdings([
        {
            'operator': value(row, 'Operator'), 'band': value(row, 'Band'), 'duplex': value(row, 'Duplex'),
            'band_class': value(row, 'Band Class', 'Class'),
            'bandwidth_mhz': value(row, 'Bandwidth MHz', 'Bandwidth', 'MHz'), 'notes': value(row, 'Notes'),
        }
        for row in reader if any(str(item or '').strip() for item in row.values())
    ])


def spectrum_holdings_csv(holdings: list[dict[str, Any]]) -> str:
    """Write holdings with the header accepted by :func:`parse_spectrum_csv`."""
    import csv
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(SPECTRUM_CSV_HEADER)
    for row in holdings:
        writer.writerow([row['operator'], row['band'], row['duplex'], row['band_class'], f"{row['bandwidth_mhz']:g}", row.get('notes', '')])
    return buffer.getvalue()


def licensed_spectrum_summary(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate licensed MHz per Operator and band class."""
    totals: dict[str, dict[str, float]] = {}
    for row in holdings:
        operator_totals = totals.setdefault(row['operator'], dict.fromkeys(BAND_CLASSES, 0.0))
        operator_totals[row['band_class']] = operator_totals.get(row['band_class'], 0.0) + float(row['bandwidth_mhz'])
    return [
        {'operator': operator, **{klass: round(values.get(klass, 0.0), 3) for klass in BAND_CLASSES},
         'total': round(sum(values.values()), 3)}
        for operator, values in totals.items()
    ]


# Cell inventories arrive as Vendor mapping datasets; their columns differ by
# operator and sheet, so each logical field lists the accepted headers.
INVENTORY_FIELDS = {
    'site': ('Site_ID', 'Site ID', 'eNBId', 'eNodeB ID', 'MBNL_ID'),
    'cell': ('CId___ECI', 'CELL_NAME', 'Cell Name', 'cellId', 'Cell ID', 'Cid__ECI', 'GCID', 'ECI', 'Cell_ID', 'Global CI'),
    'scenario': ('eMOCNScenario',),
    'network': ('Network',),
    'host_network': ('Host Network',),
    'vendor': ('OP_Vendor', 'OP/ Vendor', 'Vendor'),
    'region': ('Region', 'UK "Regional"'),
    'subregion': ('Subregion',),
    'cluster': ('Cluster', 'Cluster Name', 'Engineering Polygon', 'Regional Optimisation Polygon'),
    'site_type': ('Site_Type', 'Site Type'),
    'band': ('Band', 'Frequency Band'),
}
DEPLOYMENT_GROUPINGS = {
    'scenario': 'eMOCN Scenario', 'host_network': 'Host Network', 'network': 'Network', 'vendor': 'RAN Vendor',
    'region': 'Region', 'subregion': 'Subregion', 'cluster': 'Cluster', 'site_type': 'Site Type', 'band': 'Band',
}


# ---------------------------------------------------------------------------
# Inventory (Vendor mapping datasets)
# ---------------------------------------------------------------------------
INVENTORY_DATASET_KINDS = {'mapping_vodafone': 'Vodafone', 'mapping_three': 'Three'}


INVENTORY_KEY_COLUMNS = ('Operator', 'Operator_Vendor', 'Vendor', 'Region', 'Cluster', 'City', 'Technology')
# Source vendor of an inventory, and the vendor alone stored by earlier versions.
INVENTORY_DETAIL_ALIASES = {
    'Operator': ('Operator',),
    'Source_Vendor': ('Vendor', 'OP_Vendor', 'OP/ Vendor'),
    'Vendor_Only': ('Vendor_Only',),
    'Region': ('Region', 'UK "Regional"'),
    'City': ('City', 'Beacon2Town', 'Town', 'Major Town and Cities v3/BUA'),
    'Technology': ('Technology', 'RAT', 'Source_Sheet'),
    'Cluster': ('Cluster', 'Cluster Name', 'Engineering Polygon', 'Regional Optimisation Polygon'),
}


INVENTORY_COORDINATES = {
    'longitude': ('Longitude', 'Long', 'Lon', 'Site Longitude', 'Site_Longitude'),
    'latitude': ('Latitude', 'Lat', 'Site Latitude', 'Site_Latitude'),
    'easting': ('Easting', 'Site Easting', 'Site_Easting'),
    'northing': ('Northing', 'Site Northing', 'Site_Northing'),
}


def inventory_polygon_sources(repository) -> tuple:
    """Identify ready boundary inputs and their revisions for spatial cache invalidation."""
    sources = []
    for row in repository.list_datasets():
        if row['status'] == 'ready' and row['dataset_kind'] in {'regions', 'clusters'}:
            path = Path(str(row['stored_path']))
            sources.append((row['dataset_kind'], int(row['id']), str(row['updated_at'] or ''),
                            str(path), path.stat().st_mtime_ns))
    return tuple(sorted(sources, key=lambda item: item[1], reverse=True))


@lru_cache(maxsize=4)
def inventory_polygon_lookup(sources: tuple):
    """Index imported polygons in WGS84; newest uploads take precedence on overlaps."""
    from src.modules.geospatial import _column, _read_region_mapping, _region_field
    from shapely import STRtree

    lookups = {}
    for dimension, kind in [('Region', 'regions'), ('Cluster', 'clusters')]:
        geometries, names = [], []
        for source_kind, _identifier, _revision, path, _mtime in sources:
            if source_kind != kind:
                continue
            boundaries = _read_region_mapping(Path(path), dimension).to_crs('EPSG:4326')
            field = _region_field(boundaries.columns) if dimension == 'Region' else next(
                found for candidate in ('Cluster', 'Cluster_ID', 'Cluster_Name', 'ClusterName', 'Name')
                if (found := _column(boundaries.columns, candidate)))
            for geometry, name in zip(boundaries.geometry, boundaries[field]):
                if geometry is not None and not geometry.is_empty:
                    geometries.append(geometry)
                    names.append(str(name).strip())
        if geometries:
            lookups[dimension] = (STRtree(geometries), names)
    return lookups


def register_inventory_polygon_mapping(repository, connection) -> None:
    """Resolve inventory coordinates to imported boundary names without changing source rows."""
    sources = inventory_polygon_sources(repository)
    lookups = inventory_polygon_lookup(sources) if sources else {}
    projected_to_wgs84 = None

    @lru_cache(maxsize=65536)
    def mapped_name(dimension, longitude, latitude, easting, northing, original):
        nonlocal projected_to_wgs84
        if dimension not in lookups:
            return original

        def numeric(value):
            try:
                result = float(str(value).strip().replace(',', '.'))
                return result if math.isfinite(result) else None
            except (TypeError, ValueError):
                return None

        lon, lat = numeric(longitude), numeric(latitude)
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            east, north = numeric(easting), numeric(northing)
            if east is None or north is None:
                return ''
            if projected_to_wgs84 is None:
                from pyproj import Transformer
                projected_to_wgs84 = Transformer.from_crs('EPSG:27700', 'EPSG:4326', always_xy=True)
            lon, lat = projected_to_wgs84.transform(east, north)
        from shapely.geometry import Point
        tree, names = lookups[dimension]
        matches = tree.query(Point(lon, lat), predicate='intersects')
        return names[min(matches)] if len(matches) else ''

    connection.create_function('inventory_polygon_name', 6, mapped_name, deterministic=True)


def inventory_coordinate_expressions(columns, quote) -> list[str]:
    lookup = {column_identity(column): column for column in columns}
    values = []
    for aliases in INVENTORY_COORDINATES.values():
        fields = list(dict.fromkeys(lookup[column_identity(alias)] for alias in aliases if column_identity(alias) in lookup))
        parts = [f"NULLIF(TRIM(CAST({quote(field)} AS TEXT)), '')" for field in fields]
        values.append(f"COALESCE({', '.join(parts)}, '')" if parts else "''")
    return values


OPERATOR_FAMILIES = (
    {'vf', 'vodafone', 'vodafoneuk'}, {'3', 'three', 'threeuk', 'h3g', 'h3guk'},
    {'o2', 'o2uk', 'telefonica'}, {'ee', 'everythingeverywhere'},
)


def operator_family(name: object) -> str:
    """One identity for every spelling of the same operator (Vodafone, VF, Vodafone UK...)."""
    identity = re.sub(r'[^a-z0-9]+', '', str(name or '').casefold())
    return next((f'family{index}' for index, family in enumerate(OPERATOR_FAMILIES) if identity in family), identity)


SAMPLE_FILTERS = (
    ('operator', 'operators'), ('operator_vendor', 'operator_vendors'), ('vendor_operator', 'vendor_operators'),
    ('vendor', 'vendors'), ('region', 'regions'),
    ('cluster', 'clusters'), ('city', 'cities'), ('campaign', 'campaigns'),
)


def filter_samples(samples: pd.DataFrame, request: Any) -> pd.DataFrame:
    """Samples matching the Common Selection filters."""
    filtered = samples
    operators = samples['operator'].dropna().unique() if 'operator' in samples else []
    for field, key in SAMPLE_FILTERS:
        values = list(getattr(request, key, None) or [])
        if field == 'vendor':
            values = vendor_filter_values(values, operators)
        elif field in {'operator_vendor', 'vendor_operator'}:
            values = operator_vendor_filter_values(values, operators)
        wanted = {str(value).casefold() for value in values if str(value).strip()}
        if wanted and field in filtered:
            filtered = filtered.loc[filtered[field].str.casefold().isin(wanted)]
    return filtered


def inventory_filter_normalizer(repository):
    """Comparable form of an inventory filter value: mapped Operator and Vendor, casefolded."""
    from src.modules.column_names import vendor_filter_value

    mappings = repository.chart_mapping_settings()
    operator_maps = {str(key).casefold(): str(value) for key, value in mappings.get('operator_mappings', {}).items()}
    vendor_maps = {str(key).casefold(): str(value) for key, value in mappings.get('vendor_mappings', {}).items()}
    operator_names = [*operator_maps, *operator_maps.values(), 'Vodafone', 'Vodafone UK', 'VFUK', 'VF', 'Three', '3UK', '3']

    @lru_cache(maxsize=4096)
    def filter_value(value, field):
        text = str(value or '').strip()
        if field == 'Operator':
            text = operator_maps.get(text.casefold(), text)
        elif field == 'Vendor':
            text = vendor_filter_value(text, operator_names)
            text = vendor_maps.get(text.casefold(), text)
        elif field == 'Operator_Vendor':
            # CDRs write Vodafone_Ericsson and inventories Vodafone UK_Ericsson:
            # compare the operator family and the mapped vendor.
            all_vendors = re.search(r'\s+- All(?: Vendors)?$', text, flags=re.IGNORECASE)
            base = re.sub(r'\s+- All(?: Vendors)?$', '', text, flags=re.IGNORECASE)
            prefix, _separator, vendor = base.partition('_')
            vendor = '' if all_vendors else vendor_maps.get(vendor.strip().casefold(), vendor.strip())
            return f"{operator_family(operator_maps.get(prefix.strip().casefold(), prefix))}|{vendor.casefold()}"
        return text.casefold()

    return filter_value


def prepare_inventory_query(repository, connection, datasets: list[dict[str, Any]], selection: dict[str, Any],
                            apply_filters: bool = True):
    """Align complete inventories without changing stored source fields or row multiplicity.

    Without ``apply_filters`` the query returns every row of every inventory.
    """
    from functools import lru_cache
    from src.modules.column_names import vendor_filter_value

    quote = repository._quote_identifier
    mappings = repository.chart_mapping_settings()
    operator_maps = {str(key).casefold(): str(value) for key, value in mappings.get('operator_mappings', {}).items()}
    vendor_maps = {str(key).casefold(): str(value) for key, value in mappings.get('vendor_mappings', {}).items()}
    operator_names = [*operator_maps, *operator_maps.values(), 'Vodafone', 'Vodafone UK', 'VFUK', 'VF', 'Three', '3UK', '3']

    @lru_cache(maxsize=1024)
    def operator_value(value, fallback):
        text = str(value or fallback).strip()
        return operator_maps.get(text.casefold(), text)

    @lru_cache(maxsize=1024)
    def vendor_value(raw, only, operator):
        text = str(raw or '').strip()
        vendor = vendor_filter_value(text, operator_names) or str(only or '').strip()
        if not vendor:
            return ''
        return f'{operator}_{vendor}'

    @lru_cache(maxsize=1024)
    def vendor_only_value(raw, only):
        return str(only or '').strip() or vendor_filter_value(raw, operator_names)

    @lru_cache(maxsize=1024)
    def technology_value(value):
        text = str(value or '').strip()
        return {'4g': 'LTE', 'lte': 'LTE', '5g': 'NR', 'nr': 'NR'}.get(text.casefold(), text)

    filter_value = inventory_filter_normalizer(repository)

    @lru_cache(maxsize=4096)
    def cell_value(value):
        text = str(value or '').strip()
        if re.fullmatch(r'\d+(?:\.0+)?', text):
            return str(int(text.split('.')[0]))
        if re.fullmatch(r'0x[0-9a-f]+', text, re.I):
            return str(int(text, 16))
        return text

    connection.create_function('inventory_cell', 1, cell_value, deterministic=True)
    connection.create_function('inventory_operator', 2, operator_value, deterministic=True)
    connection.create_function('inventory_vendor', 3, vendor_value, deterministic=True)
    connection.create_function('inventory_vendor_only', 2, vendor_only_value, deterministic=True)
    connection.create_function('inventory_technology', 1, technology_value, deterministic=True)
    connection.create_function('inventory_filter', 2, filter_value, deterministic=True)
    register_inventory_polygon_mapping(repository, connection)
    schemas = {row['id']: repository.list_dataset_row_columns(row['id']) for row in datasets}
    source_columns = list(dict.fromkeys(column for row in datasets for column in schemas[row['id']]))
    columns = [*INVENTORY_KEY_COLUMNS, 'Source_Dataset_ID', 'Source_Dataset_Name']
    source_names = {}
    used = {column.casefold() for column in columns} | {'__inventory_cell_id', '__inventory_source_row'}
    for source in source_columns:
        name = f'Source_{source}' if column_identity(source) in {column_identity(key) for key in INVENTORY_KEY_COLUMNS} else source
        while name.casefold() in used:
            name = f'Source_{name}'
        source_names[source] = name
        used.add(name.casefold())
        columns.append(name)

    selects = []
    for dataset in datasets:
        available = schemas[dataset['id']]
        lookup = {column_identity(column): column for column in available}

        def expression(aliases):
            fields = list(dict.fromkeys(lookup[column_identity(alias)] for alias in aliases if column_identity(alias) in lookup))
            if not fields:
                return "''"
            parts = [f"NULLIF(TRIM(CAST({quote(field)} AS TEXT)), '')" for field in fields]
            return f"COALESCE({', '.join(parts)}, '')"

        fallback = str(dataset['operator']).replace("'", "''")
        operator = f"inventory_operator({expression(INVENTORY_DETAIL_ALIASES['Operator'])}, '{fallback}')"
        raw_vendor = expression(INVENTORY_DETAIL_ALIASES['Source_Vendor'])
        only = expression(INVENTORY_DETAIL_ALIASES['Vendor_Only'])
        normalized = {
            'Operator': operator,
            'Operator_Vendor': f'inventory_vendor({raw_vendor}, {only}, {operator})',
            'Vendor': f'inventory_vendor_only({raw_vendor}, {only})',
            'Region': expression(INVENTORY_DETAIL_ALIASES['Region']),
            'City': expression(INVENTORY_DETAIL_ALIASES['City']),
            'Technology': f"COALESCE(NULLIF(inventory_technology({expression(('Technology', 'RAT'))}), ''), CASE LOWER({expression(('Source_Sheet',))}) WHEN '4g' THEN 'LTE' WHEN '5g' THEN 'NR' ELSE '' END)",
            'Cluster': expression(INVENTORY_DETAIL_ALIASES['Cluster']),
        }
        coordinates = ', '.join(inventory_coordinate_expressions(available, quote))
        for dimension in ('Region', 'Cluster'):
            normalized[dimension] = f"inventory_polygon_name('{dimension}', {coordinates}, {normalized[dimension]})"
        # Three's ECI mapping format identifies LTE cells even without a Technology header.
        if dataset['kind'] == 'mapping_three' and any(column_identity(col) in {'cideci', 'eci'} for col in available):
            normalized['Technology'] = f"COALESCE(NULLIF({normalized['Technology']}, ''), 'LTE')"
        cell = expression(('GCID', 'CId___ECI', 'Cid__ECI', 'ECI', 'Cell_ID', 'Global CI'))
        if cell == "''":
            local = expression(('Local Cell ID',))
            enodeb = expression(('eNodeB ID', 'eNBId'))
            gnodeb = expression(('gNodeB ID',))
            cell = f"CASE WHEN {local} = '' THEN NULL WHEN {normalized['Technology']} = 'NR' AND {gnodeb} != '' THEN CAST({gnodeb} AS INTEGER) * 4096 + CAST({local} AS INTEGER) WHEN {normalized['Technology']} = 'LTE' AND {enodeb} != '' THEN CAST({enodeb} AS INTEGER) * 256 + CAST({local} AS INTEGER) END"
        values = [f'{value} AS {quote(field)}' for field, value in normalized.items()]
        values.extend([f'inventory_cell({cell}) AS __Inventory_Cell_ID', 'rowid AS __Inventory_Source_Row'])
        filename = str(dataset['file_name']).replace("'", "''")
        values.extend([f"{int(dataset['id'])} AS Source_Dataset_ID", f"'{filename}' AS Source_Dataset_Name"])
        values.extend(f"{quote(source) if source in available else 'NULL'} AS {quote(source_names[source])}" for source in source_columns)
        selects.append(f"SELECT {', '.join(values)} FROM {quote(repository.dataset_rows_table_name(dataset['id']))}")
    if not selects:
        return '', [], columns
    if not apply_filters:
        return 'SELECT * FROM (' + ' UNION ALL '.join(selects) + ')', [], columns
    predicates, parameters = [], []
    for field, key in [('Operator', 'operators'), ('Operator_Vendor', 'operator_vendors'), ('Vendor', 'vendors'),
                       ('Region', 'regions'), ('Cluster', 'clusters'), ('City', 'cities')]:
        values = list(dict.fromkeys(filter_value(value, field) for value in selection.get(key, []) if str(value).strip()))
        if values:
            predicates.append(f"inventory_filter({quote(field)}, '{field}') IN ({', '.join('?' for _ in values)})")
            parameters.extend(values)
    technology = selection.get('technology', 'lte')
    technologies = ['LTE', 'NR'] if technology == 'lte_nr' else ['NR'] if technology == 'nr' else ['LTE']
    predicates.append(f"Technology IN ({', '.join('?' for _ in technologies)})")
    parameters.extend(technologies)
    query = 'SELECT * FROM (' + ' UNION ALL '.join(selects) + ')'
    if predicates:
        query += ' WHERE ' + ' AND '.join(predicates)
    return query, parameters, columns


def inventory_expression(columns: Iterable[str], field: str, quote) -> str | None:
    """SQL expression returning the first non-empty inventory column value."""
    lookup = {column_identity(column): column for column in columns}
    present = [lookup[column_identity(alias)] for alias in INVENTORY_FIELDS[field] if column_identity(alias) in lookup]
    if not present:
        return None
    parts = [f"NULLIF(TRIM(CAST({quote(column)} AS TEXT)), '')" for column in dict.fromkeys(present)]
    return parts[0] if len(parts) == 1 else f"COALESCE({', '.join(parts)})"


def inventory_projection(task_repository: Any, dataset: dict[str, Any]) -> pd.DataFrame:
    """Read only distinct identifiers and grouping fields from an inventory."""
    dataset_id = int(dataset['id'])
    columns = task_repository.list_dataset_row_columns(dataset_id)
    quote = task_repository._quote_identifier
    expressions = {field: inventory_expression(columns, field, quote) for field in INVENTORY_FIELDS}
    if not expressions['site']:
        return pd.DataFrame()
    coordinates = ', '.join(inventory_coordinate_expressions(columns, quote))
    polygon_kinds = {source[0] for source in inventory_polygon_sources(task_repository)}
    for field, dimension in [('region', 'Region'), ('cluster', 'Cluster')]:
        if not expressions[field] and ('regions' if field == 'region' else 'clusters') not in polygon_kinds:
            continue
        original = expressions[field] or "''"
        expressions[field] = f"inventory_polygon_name('{dimension}', {coordinates}, {original})"
    selected = ', '.join(f'{expression} AS {quote(field)}'
                         for field, expression in expressions.items() if expression)
    table = quote(task_repository.dataset_rows_table_name(dataset_id))
    with task_repository.connection() as connection:
        register_inventory_polygon_mapping(task_repository, connection)
        return pd.read_sql_query(
            f"SELECT DISTINCT {selected} FROM {table} WHERE {expressions['site']} IS NOT NULL", connection)


def inventory_summary(task_repository: Any, dataset: dict[str, Any], group: str | None,
                      *, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """Count distinct sites and cells using a reusable narrow inventory frame."""
    if frame is None:
        frame = inventory_projection(task_repository, dataset)
    if 'site' not in frame.columns:
        return {'available_groups': [], 'rows': [], 'totals': None}
    available_groups = [key for key in DEPLOYMENT_GROUPINGS if key in frame.columns]
    grouped = frame.assign(_group=frame[group].replace('', pd.NA).fillna('Not set') if group in available_groups else 'All')
    counts = grouped.groupby('_group', sort=False)['site'].nunique().rename('sites').to_frame()
    counts['cells'] = grouped.groupby('_group', sort=False)['cell'].nunique() if 'cell' in frame.columns else 0
    counts = counts.reset_index().sort_values(['sites', '_group'], ascending=[False, True])
    return {
        'available_groups': available_groups,
        'rows': [{'group': str(row['_group']), 'sites': int(row['sites']), 'cells': int(row['cells'])}
                 for row in counts.to_dict('records')],
        'totals': {'sites': int(frame['site'].nunique()),
                   'cells': int(frame['cell'].nunique()) if 'cell' in frame.columns else 0},
    }


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------
def install_network_insights_routes(core: Any) -> None:
    """Register the Network Insights page and its JSON API."""
    import hashlib
    import json
    from collections import OrderedDict
    from pathlib import Path
    from threading import Lock

    from urllib.parse import urlencode

    from fastapi import Depends, Form, HTTPException, Query, Request
    from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
    from pydantic import BaseModel, Field

    from src.modules.cdr_reporting import _osm_map_tile_geometry

    app = core.app
    sample_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
    sample_cache_lock = Lock()
    analysis_cache: OrderedDict[str, bytes] = OrderedDict()
    analysis_cache_lock = Lock()
    inventory_cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
    inventory_cache_lock = Lock()

    class AnalysisRequest(BaseModel):
        nr_mode: str = 'NSA'
        datasets: dict[str, list[int]] = Field(default_factory=dict)
        technology: str = 'lte'
        group: list[str] | str = Field(default_factory=lambda: ['operator', 'campaign'])
        operators: list[str] = Field(default_factory=list)
        operator_vendors: list[str] = Field(default_factory=list)
        vendor_operators: list[str] = Field(default_factory=list)
        vendors: list[str] = Field(default_factory=list)
        campaigns: list[str] = Field(default_factory=list)
        regions: list[str] = Field(default_factory=list)
        clusters: list[str] = Field(default_factory=list)
        cities: list[str] = Field(default_factory=list)
        # LTE thresholds; NR SS-RSRP/SS-SINR have their own.
        coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD
        interference_threshold: float = DEFAULT_INTERFERENCE_THRESHOLD
        nr_coverage_threshold: float = DEFAULT_NR_COVERAGE_THRESHOLD
        nr_interference_threshold: float = DEFAULT_NR_INTERFERENCE_THRESHOLD
        grid_metres: float = 250
        min_samples: int = 3
        map_operator: str = ''
        # Summaries draw the maps of every group, not only the one shown on the page.
        map_all_groups: bool = False

    class SpectrumRequest(BaseModel):
        holdings: list[dict[str, Any]] = Field(default_factory=list)

    def insights_user(user=Depends(core.current_user)):
        if not core.active_workspace:
            raise HTTPException(400, 'Open a workspace before using Network Insights.')
        if user.role != 'super-admin' and not core.repository.user_has_workspace_access(user.username, core.active_workspace.id):
            raise HTTPException(403, 'You do not have access to the active workspace.')
        return user

    def editor_user(user=Depends(insights_user)):
        if user.role not in {'user-editor', 'admin', 'super-admin'}:
            raise HTTPException(403, 'Editor access required.')
        return user

    def bound_repository():
        return core.Repository(Path(core.repository.db_path), core.repository.global_db_path)

    def ready_cdrs(task_repository) -> list[dict[str, Any]]:
        rows = []
        for row in task_repository.list_datasets():
            if row['status'] != 'ready' or row['dataset_kind'] not in NETWORK_INSIGHTS_KINDS:
                continue
            item = dict(row)
            rows.append({
                'id': int(item['id']), 'kind': item['dataset_kind'], 'file_name': str(item['file_name']),
                'nr_mode': core.dataset_nr_mode(item['dataset_kind'], item.get('nr_mode'), item['file_name']),
                'cdr_stage': core.dataset_cdr_stage(item['dataset_kind'], item.get('cdr_stage'), item['file_name']),
                'row_count': int(item.get('row_count') or 0),
                'updated_at': str(item.get('updated_at') or item.get('processed_at') or ''),
            })
        return sorted(rows, key=lambda row: row['id'], reverse=True)

    def inventory_datasets(task_repository) -> list[dict[str, Any]]:
        return [
            {'id': int(row['id']), 'kind': row['dataset_kind'], 'operator': INVENTORY_DATASET_KINDS[row['dataset_kind']],
             'file_name': str(row['file_name']), 'updated_at': str(row['updated_at'] or '')}
            for row in task_repository.list_datasets()
            if row['status'] == 'ready' and row['dataset_kind'] in INVENTORY_DATASET_KINDS
        ]

    def cluster_datasets_ready(task_repository) -> bool:
        return any(row['status'] == 'ready' and row['dataset_kind'] == 'clusters'
                   for row in task_repository.list_datasets())

    def cluster_grouping_available(task_repository) -> bool:
        if cluster_datasets_ready(task_repository):
            return True
        return any(inventory_expression(task_repository.list_dataset_row_columns(dataset['id']), 'cluster',
                                        task_repository._quote_identifier)
                   for dataset in inventory_datasets(task_repository))

    def require_cluster_dataset(group: str, task_repository) -> None:
        if group == 'cluster' and not cluster_grouping_available(task_repository):
            raise HTTPException(400, 'Import Clusters polygons or an inventory with a Cluster field to group deployment by Cluster.')

    def cache_directory(task_repository) -> Path:
        """Workspace folder for Network Insights caches that survive restarts."""
        folder = Path(task_repository.db_path).resolve().parent / '.network-insights-cache'
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_cache_file(folder: Path, name: str, payload: bytes, keep: int, pattern: str) -> None:
        """Write atomically and keep only the newest files of one kind."""
        temporary = folder / f'.{name}.{uuid4().hex}.tmp'
        temporary.write_bytes(payload)
        temporary.replace(folder / name)
        for stale in sorted(folder.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)[keep:]:
            stale.unlink(missing_ok=True)

    def samples_key(task_repository, datasets: dict[str, list[int]]) -> tuple[str, dict[str, list[int]]]:
        """Identity of the normalised samples: CDR revisions and Operator mappings."""
        available = {row['id']: row for row in ready_cdrs(task_repository)}
        selected = {
            kind: [int(dataset_id) for dataset_id in datasets.get(kind, []) if int(dataset_id) in available and available[int(dataset_id)]['kind'] == kind]
            for kind in NETWORK_INSIGHTS_KINDS
        }
        if not any(selected.values()):
            raise HTTPException(400, 'Select at least one ready CDR.')
        fingerprint = json.dumps({
            'version': SAMPLES_CACHE_VERSION,
            'database': str(Path(task_repository.db_path).resolve()),
            'datasets': {kind: [(dataset_id, available[dataset_id]['updated_at']) for dataset_id in ids] for kind, ids in selected.items()},
            'mappings': {key: value for key, value in task_repository.chart_mapping_settings().items()
                         if key in {'operator_mappings', 'vendor_mappings'}},
        }, sort_keys=True, default=str)
        return hashlib.sha256(fingerprint.encode()).hexdigest(), selected

    def load_samples(task_repository, datasets: dict[str, list[int]]) -> pd.DataFrame:
        key, selected = samples_key(task_repository, datasets)
        with sample_cache_lock:
            cached = sample_cache.get(key)
            if cached is not None:
                sample_cache.move_to_end(key)
                return cached
        # Each CDR's samples are stored on their own, so adding or removing a
        # CDR from the selection only reads the CDRs not analysed before.
        revisions = {row['id']: row['updated_at'] for row in ready_cdrs(task_repository)}
        # The samples hold mapped Operators and Vendors: a change of either map reads them again.
        settings = task_repository.chart_mapping_settings()
        mappings = {'operator': settings.get('operator_mappings'), 'vendor': settings.get('vendor_mappings')}
        pairs = [(kind, dataset_id) for kind, ids in selected.items() for dataset_id in ids]
        # CDRs not read before are read in parallel; SQLite reads release the GIL.
        with ThreadPoolExecutor(max_workers=max(1, min(4, len(pairs)))) as executor:
            frames = list(executor.map(
                lambda pair: dataset_samples(task_repository, pair[0], pair[1], revisions.get(pair[1]), mappings), pairs))
        frames = [frame for frame in frames if not frame.empty]
        samples = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        with sample_cache_lock:
            sample_cache[key] = samples
            while len(sample_cache) > 3:
                sample_cache.popitem(last=False)
        return samples

    dataset_sample_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()

    def dataset_samples(task_repository, kind: str, dataset_id: int, revision: Any, mappings: Any) -> pd.DataFrame:
        """Normalised samples of one CDR, kept in memory and on disk until it or the Operator mappings change."""
        key = hashlib.sha256(json.dumps({
            'version': SAMPLES_CACHE_VERSION, 'database': str(Path(task_repository.db_path).resolve()),
            'dataset': dataset_id, 'kind': kind, 'revision': revision, 'mappings': mappings,
        }, sort_keys=True, default=str).encode()).hexdigest()
        with sample_cache_lock:
            cached = dataset_sample_cache.get(key)
            if cached is not None:
                dataset_sample_cache.move_to_end(key)
                return cached
        folder = cache_directory(task_repository)
        stored = folder / f'samples-cdr-{key}.pkl'
        samples = None
        if stored.is_file():
            try:
                samples = pd.read_pickle(stored)
                stored.touch()
            except Exception:
                stored.unlink(missing_ok=True)
        if samples is None:
            samples = read_samples(task_repository, {kind: [dataset_id]})
            buffer = io.BytesIO()
            samples.to_pickle(buffer, protocol=5)
            write_cache_file(folder, stored.name, buffer.getvalue(), keep=24, pattern='samples-cdr-*.pkl')
            # Samples of whole selections were stored before samples per CDR.
            for legacy in folder.glob('samples-*.pkl'):
                if not legacy.name.startswith('samples-cdr-'):
                    legacy.unlink(missing_ok=True)
        with sample_cache_lock:
            dataset_sample_cache[key] = samples
            while len(dataset_sample_cache) > 12:
                dataset_sample_cache.popitem(last=False)
        return samples

    def read_samples(task_repository, selected: dict[str, list[int]]) -> pd.DataFrame:
        frames = []
        mapping_settings = task_repository.chart_mapping_settings()
        for kind, ids in selected.items():
            if not ids:
                continue
            source_columns: set[str] = set()
            for dataset_id in ids:
                source_columns.update(task_repository.list_dataset_row_columns(dataset_id))
            columns = resolve_source_columns(source_columns, kind)
            requested = list(dict.fromkeys(columns.values()))
            for dataset_id in ids:
                task_repository.copy_dataset_rows_to_reporting(dataset_id, kind, requested)
            frame = task_repository.load_reporting_rows(kind, ids, requested)
            if frame.empty:
                continue
            if 'source_sheet' in columns and columns['source_sheet'] in frame.columns:
                sheets = frame[columns['source_sheet']].fillna('').astype(str).str.strip().str.casefold()
                frame = frame.loc[~sheets.isin(core.CDR_IGNORED_SHEET_KEYS)].copy()
            frame = core.apply_operator_mappings(frame, mapping_settings.get('operator_mappings') or {})
            frame.attrs.update(mapping_settings)
            frame = core.normalise_operator_aliases(frame)
            frames.append(normalise_samples(frame, kind, columns))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    @app.get('/network-insights', response_class=HTMLResponse)
    def network_insights_page(request: Request, user=Depends(insights_user)):
        task_repository = bound_repository()
        holdings = load_spectrum_holdings(task_repository)
        return core.render_template(request, 'network_insights.html', {
            'user': user,
            'network_insights_config': {
                'selection_storage_key': f'network-insights:selection:{core.active_workspace.id}:{user.username}',
                'datasets': ready_cdrs(task_repository),
                'inventories': inventory_datasets(task_repository),
                'deployment_groups': DEPLOYMENT_GROUPINGS,
                'clusters_available': cluster_grouping_available(task_repository),
                'groupings': GROUPINGS,
                'main_cities': task_repository.list_main_cities(),
                'technologies': TECHNOLOGIES,
                'coverage_threshold': DEFAULT_COVERAGE_THRESHOLD,
                'interference_threshold': DEFAULT_INTERFERENCE_THRESHOLD,
                'nr_coverage_threshold': DEFAULT_NR_COVERAGE_THRESHOLD,
                'nr_interference_threshold': DEFAULT_NR_INTERFERENCE_THRESHOLD,
                'rsrp_classes': [{'label': label, 'lower': None if math.isinf(lower) else lower, 'colour': colour} for label, lower, colour in RSRP_CLASSES],
                'sinr_classes': [{'label': label, 'lower': None if math.isinf(lower) else lower, 'colour': colour} for label, lower, colour in SINR_CLASSES],
                'spectrum_holdings': holdings,
                'spectrum_summary': licensed_spectrum_summary(holdings),
                'band_classes': BAND_CLASSES,
                'can_edit': user.role in {'user-editor', 'admin', 'super-admin'},
            },
        })

    @app.post('/api/network-insights/filter-options')
    def network_insights_filter_options(request: AnalysisRequest, vendor_only: bool = False, user=Depends(insights_user)):
        """Filter values of the selected CDRs from their catalogues; vendor_only returns the vendor fields."""
        task_repository = bound_repository()
        available = {row['id']: row for row in ready_cdrs(task_repository)}
        fields = ('operator_vendor', 'vendor_operator', 'vendor') if vendor_only else ('operator', 'region', 'cluster', 'city', 'campaign')
        values = {field: set() for field in fields}
        mappings = task_repository.chart_mapping_settings()
        selected = {dataset_id: kind for kind in NETWORK_INSIGHTS_KINDS
                    for dataset_id in request.datasets.get(kind, [])
                    if dataset_id in available and available[dataset_id]['kind'] == kind}
        if vendor_only:
            # One-time backfill for existing CDRs; future ingestion stores both formats.
            for dataset_id in task_repository.missing_cdr_vendor_only_ids(selected):
                columns = resolve_source_columns(task_repository.list_dataset_row_columns(dataset_id), selected[dataset_id])
                column = columns.get('vendor')
                vendor_values = task_repository.list_distinct_dataset_row_values(dataset_id, column, limit=None) if column else []
                task_repository.set_cdr_catalogue_vendor_only(dataset_id, vendor_values)
        else:
            for dataset_id in task_repository.missing_cdr_cluster_ids(selected):
                columns = resolve_source_columns(task_repository.list_dataset_row_columns(dataset_id), selected[dataset_id])
                column = columns.get('cluster')
                cluster_values = task_repository.list_distinct_dataset_row_values(dataset_id, column, limit=None) if column else []
                task_repository.set_cdr_catalogue_clusters(dataset_id, cluster_values)
        catalogue_keys = {'operator_vendor': 'vendors', 'vendor_operator': 'vendor_operators', 'vendor': 'vendors_only', 'city': 'cities'}
        catalogues = task_repository.cdr_catalogues_by_dataset(selected)
        for catalogue in catalogues.values():
            for field in values:
                values[field].update(catalogue.get(catalogue_keys.get(field, field + 's'), []))
        # Operators and Vendors with their Operator and Vendor Maps labels, as in the samples.
        mapper = ValueMapper.from_settings(mappings)
        for field in ('operator', 'operator_vendor', 'vendor_operator', 'vendor'):
            if values.get(field):
                values[field] = mapper.values(field_kind(field), values[field])
        if 'campaign' in values:
            values['campaign'] = {compact_campaign_value(value) or value for value in values['campaign']}
        return {'options': {field + 's' if field != 'city' else 'cities': (
            list if field in {'operator', 'operator_vendor', 'vendor_operator', 'vendor'} else lambda items: sorted(items, key=str.casefold)
        )([value for value in items if str(value).strip()]) for field, items in values.items()}}

    def analysis_key(task_repository, request: AnalysisRequest) -> str:
        """Identity of an analysis: its request and every input it reads."""
        samples, _selected = samples_key(task_repository, request.datasets)
        inputs = {
            'version': ANALYSIS_CACHE_VERSION, 'samples': samples, 'request': request.model_dump(),
            'mapping_groups': task_repository.list_operator_mapping_groups(),
            'holdings': load_spectrum_holdings(task_repository),
            'inventories': [(row['id'], row['updated_at']) for row in inventory_datasets(task_repository)],
        }
        return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()

    @app.post('/api/network-insights/analysis')
    def network_insights_analysis(request: AnalysisRequest, cached_only: bool = Query(False), user=Depends(insights_user)):
        # Repeating an analysis with the same CDRs and filters returns the
        # stored result instead of recalculating it, also after a restart.
        # ``cached_only`` answers 204 instead of calculating a missing result.
        task_repository = bound_repository()
        key = analysis_key(task_repository, request)
        with analysis_cache_lock:
            cached = analysis_cache.get(key)
            if cached is not None:
                analysis_cache.move_to_end(key)
        folder = cache_directory(task_repository)
        stored = folder / f'analysis-{key}.json'
        if cached is None and stored.is_file():
            cached = stored.read_bytes()
            stored.touch()
        if cached is None and cached_only:
            return Response(status_code=204)
        if cached is None:
            cached = json.dumps(run_analysis(request), ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            write_cache_file(folder, stored.name, cached, keep=40, pattern='analysis-*.json')
        with analysis_cache_lock:
            analysis_cache[key] = cached
            while len(analysis_cache) > 12:
                analysis_cache.popitem(last=False)
        return Response(cached, media_type='application/json')

    def technology_thresholds(request: AnalysisRequest, radio: str) -> tuple[float, float]:
        if radio == 'nr':
            return request.nr_coverage_threshold, request.nr_interference_threshold
        return request.coverage_threshold, request.interference_threshold

    def run_analysis(request: AnalysisRequest) -> dict[str, Any]:
        technology = request.technology if request.technology in TECHNOLOGIES else 'lte'
        requested_groups = [request.group] if isinstance(request.group, str) else request.group
        # Operator can only be left out when Vendor groups the samples instead.
        if 'vendor' not in requested_groups:
            requested_groups = ['operator', *requested_groups]
        # LTE+NR never pools the technologies: LTE RSRP/SINR and NR SS-RSRP/SS-SINR
        # use different reference signals, so each one gets its own section.
        groups = [field for field in GROUPINGS if field != 'technology' and field in requested_groups]
        group_label = ' → '.join(GROUPINGS[field] for field in groups) or 'All samples'
        task_repository = bound_repository()
        samples = load_samples(task_repository, request.datasets)
        if samples.empty:
            raise HTTPException(400, 'The selected CDRs have no samples.')
        options = {
            'operators': [value for value in dict.fromkeys(samples['operator']) if value],
            'operator_vendors': sorted({value for value in samples['operator_vendor'] if value}, key=str.casefold),
            'vendor_operators': sorted({value for value in samples['vendor_operator'] if value}, key=str.casefold),
            'vendors': sorted({value for value in samples['vendor'] if value}, key=str.casefold),
            'regions': sorted({value for value in samples['region'] if value}, key=str.casefold),
            'clusters': sorted({value for value in samples['cluster'] if value}, key=str.casefold),
            'cities': sorted({value for value in samples['city'] if value}, key=str.casefold),
            'campaigns': sorted({value for value in samples['campaign'] if value}, key=campaign_sort_key),
        }
        filtered = filter_samples(samples, request)
        if filtered.empty:
            raise HTTPException(400, 'No samples match the selected filters.')
        filtered = filtered.copy()
        original_operators = filtered['operator'].copy()
        operator_mappings = {str(key).casefold(): str(value)
                             for key, value in task_repository.list_operator_mappings().items()}
        inventoried_operators = {operator_mappings.get(dataset['operator'].casefold(), dataset['operator'])
                                for dataset in inventory_datasets(task_repository)}
        missing_inventory_operators = sorted(
            {str(operator) for operator in original_operators if str(operator).strip()} - inventoried_operators,
            key=str.casefold,
        )
        # Site/cell identifiers remain scoped by their source operator when
        # operators are pooled; each group already has one operator otherwise.
        if 'operator' not in groups:
            for field in ('enodebs', 'cells'):
                filtered[field] = [tuple(f'{operator}:{value}' for value in values)
                                   for operator, values in zip(original_operators, filtered[field], strict=True)]
        if groups:
            grouping_values = filtered[groups].fillna('').astype(str)
            labels = grouping_values[groups[0]].replace('', '(Empty)')
            for field in groups[1:]:
                labels = labels.str.cat(grouping_values[field].replace('', '(Empty)'), sep=' · ')
        else:
            labels = pd.Series('All samples', index=filtered.index)
        filtered['operator'] = labels
        # Curves share their Operator/Vendor colour. Campaigns differ by line
        # width (the latest is the thickest) and other groups by line style.
        family_field = groups[0] if groups and groups[0] in {'operator', 'vendor'} else None
        secondary = [field for field in groups if field not in {family_field, 'campaign'}]
        dash_groups = None
        if family_field and secondary:
            secondary_values = filtered[secondary].fillna('').astype(str)
            secondary_labels = secondary_values[secondary[0]]
            for field in secondary[1:]:
                secondary_labels = secondary_labels.str.cat(secondary_values[field], sep=' · ')
            dash_groups = dict(zip(labels, secondary_labels, strict=True))
        widths = None
        if 'campaign' in groups:
            family_values = original_operators if family_field == 'operator' else filtered[family_field] if family_field else None
            families = dict(zip(labels, family_values.fillna('').astype(str), strict=True)) if family_values is not None else {}
            widths = campaign_line_widths(dict(zip(labels, filtered['campaign'].fillna('').astype(str), strict=True)), families)
        mapping_groups = task_repository.list_operator_mapping_groups()
        vendor_mapping_groups = task_repository.list_vendor_mapping_groups()

        def group_order(label: str) -> tuple[Any, ...]:
            """Groups in Operator Map and Vendor Map order, one grouping field after another."""
            parts = str(label).split(' · ')
            return tuple(
                dimension_order_key(field, part, mapping_groups, vendor_mapping_groups) or (0, 0, part.casefold())
                for field, part in zip(groups, parts)
            ) if groups and len(parts) == len(groups) else ((1, 0, str(label).casefold()),)

        if 'operator' in groups:
            source_colours = operator_colours(original_operators, mapping_groups)
            colours = {label: source_colours[operator]
                       for label, operator in zip(labels, original_operators, strict=True)}
        else:
            colours = operator_colours(filtered['operator'], [])
        campaigns = [value for value in options['campaigns'] if value in set(filtered['campaign'])]
        radios = ('lte', 'nr') if technology == 'lte_nr' else (technology,)
        warnings = []

        def technology_section(radio: str) -> dict[str, Any]:
            label = TECHNOLOGIES[radio]
            coverage_threshold, interference_threshold = technology_thresholds(request, radio)
            rsrp, sinr = f'{radio}_rsrp', f'{radio}_sinr'
            frame = filtered
            if technology == 'lte_nr':
                frame = filtered.loc[filtered[[rsrp, sinr]].notna().any(axis=1)]
            if not frame[rsrp].notna().any():
                warnings.append(f'The selected CDRs carry no {label} RSRP samples.')
            overview = rf_summary(frame, radio, None, coverage_threshold, interference_threshold)
            overview.sort(key=lambda row: group_order(row['operator']))
            comparison = None
            if len(campaigns) >= 2 and 'campaign' not in groups:
                previous, latest = campaigns[-2], campaigns[-1]
                by_campaign = {
                    (row['operator'], row['group']): row
                    for row in rf_summary(frame.loc[frame['campaign'].isin([previous, latest])], radio, 'campaign',
                                          coverage_threshold, interference_threshold)
                }
                for row in overview:
                    before, after = by_campaign.get((row['operator'], previous)), by_campaign.get((row['operator'], latest))
                    row['deltas'] = {
                        metric: (round(after[metric] - before[metric], 2) if before and after and after[metric] is not None and before[metric] is not None else None)
                        for metric in ('rsrp_median', 'low_coverage_share', 'sinr_median', 'high_interference_share')
                    }
                comparison = {'previous': previous, 'latest': latest}
            for row in overview:
                row['technology'] = label
            map_operators = [row['operator'] for row in overview]
            map_operator = request.map_operator if request.map_operator in map_operators else (map_operators[0] if map_operators else '')
            def group_maps(operator: str) -> dict[str, Any]:
                operator_samples = frame.loc[frame['operator'] == operator]
                coverage_cells, coverage_grid = grid_cells(operator_samples, rsrp, coverage_threshold, request.grid_metres, request.min_samples)
                interference_cells, interference_grid = grid_cells(operator_samples, sinr, interference_threshold, request.grid_metres, request.min_samples)
                return {
                    'operator': operator,
                    'coverage': map_payload(coverage_cells, RSRP_CLASSES, f'{operator} · Mean {label} RSRP per {coverage_grid:g} m grid', 'dBm', _osm_map_tile_geometry),
                    'coverage_hotspots': hotspots(coverage_cells), 'coverage_grid_metres': coverage_grid,
                    'interference': map_payload(interference_cells, SINR_CLASSES, f'{operator} · Mean {label} SINR per {interference_grid:g} m grid', 'dB', _osm_map_tile_geometry),
                    'interference_hotspots': hotspots(interference_cells), 'interference_grid_metres': interference_grid,
                }

            selected_maps = group_maps(map_operator)
            return {
                'technology': radio, 'technology_label': label,
                'coverage_threshold': coverage_threshold, 'interference_threshold': interference_threshold,
                'overview': overview, 'rf_rows': overview, 'comparison': comparison,
                'charts': {
                    'rsrp_cdf': cdf_payload(frame, rsrp, None, f'{label} RSRP', 'RSRP (dBm)', colours, dash_groups=dash_groups, widths=widths, order_key=group_order),
                    'sinr_cdf': cdf_payload(frame, sinr, None, f'{label} SINR', 'SINR (dB)', colours, dash_groups=dash_groups, widths=widths, order_key=group_order),
                },
                'maps': {
                    **selected_maps, 'operators': map_operators,
                    **({'groups': [selected_maps if operator == map_operator else group_maps(operator) for operator in map_operators]}
                       if request.map_all_groups else {}),
                },
            }

        sections = [technology_section(radio) for radio in radios]
        if filtered[['latitude', 'longitude']].dropna().empty:
            warnings.append('The selected CDRs carry no sample coordinates, so maps are unavailable.')
        holdings = load_spectrum_holdings(task_repository)
        rows = [row for section in sections for row in section['overview']]
        first = sections[0]
        return {
            'technology': technology, 'technology_label': TECHNOLOGIES[technology],
            'group': groups, 'group_label': group_label,
            'options': options, 'comparison': first['comparison'],
            # Every technology section in order; LTE+NR has one for LTE and one for NR.
            'sections': sections,
            'overview': rows,
            'rf_rows': rows,
            'missing_inventory_operators': missing_inventory_operators,
            'charts': first['charts'],
            'maps': first['maps'],
            'spectrum': {
                'observed': observed_spectrum(filtered),
                'licensed': licensed_spectrum_summary(holdings),
            },
            'colours': colours,
            'warnings': warnings,
        }

    # ------------------------------------------------------------------
    # Sites/Cells tables: complete inventories or cells observed in CDRs
    # ------------------------------------------------------------------
    class SitesRequest(AnalysisRequest):
        source: str = 'inventory'
        operator: str = ''
        page: int = 0
        column: str = ''
        search: str = ''
        # Excel-style column filters: column -> accepted values ('' is blank).
        filters: dict[str, list[str]] = Field(default_factory=dict)

    site_tables_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
    site_tables_lock = Lock()

    def remember(key: str, build) -> dict[str, Any]:
        with site_tables_lock:
            cached = site_tables_cache.get(key)
            if cached is not None:
                site_tables_cache.move_to_end(key)
                return cached
        value = build()
        with site_tables_lock:
            site_tables_cache[key] = value
            while len(site_tables_cache) > 8:
                site_tables_cache.popitem(last=False)
        return value

    def operator_labels(task_repository) -> dict[str, str]:
        """Mapped operator -> inventory label (Vodafone, Three) of the uploaded inventories."""
        mappings = {str(key).casefold(): str(value) for key, value in task_repository.list_operator_mappings().items()}
        return {mappings.get(row['operator'].casefold(), row['operator']): row['operator']
                for row in inventory_datasets(task_repository)}

    def inventory_index(task_repository) -> dict[str, Any]:
        """Normalised key fields of every inventory row, built once per inventory revision.

        Pages, filters and value lists read this index; only the visible rows
        are read back from the stored inventories.
        """
        datasets = inventory_datasets(task_repository)
        signature = json.dumps([INVENTORY_CACHE_VERSION, str(Path(task_repository.db_path).resolve()),
                                [(row['id'], inventory_revision(task_repository, row)) for row in datasets],
                                task_repository.chart_mapping_settings(), inventory_polygon_sources(task_repository)],
                               sort_keys=True, default=str)
        digest = hashlib.sha256(signature.encode()).hexdigest()

        def build() -> dict[str, Any]:
            folder = cache_directory(task_repository)
            stored = folder / f'inventory-index-{digest}.pkl'
            if stored.is_file():
                try:
                    stored.touch()
                    return pd.read_pickle(stored)
                except Exception:
                    stored.unlink(missing_ok=True)
            with task_repository.connection() as connection:
                query, parameters, columns = prepare_inventory_query(task_repository, connection, datasets, {}, apply_filters=False)
                quote = task_repository._quote_identifier
                keys = [*INVENTORY_KEY_COLUMNS, 'Source_Dataset_ID', '__Inventory_Source_Row']
                frame = pd.read_sql_query(
                    f"SELECT {', '.join(quote(column) for column in keys)} FROM ({query})", connection, params=parameters,
                ) if query else pd.DataFrame(columns=keys)
            for column in INVENTORY_KEY_COLUMNS:
                frame[column] = frame[column].fillna('').astype(str)
            frame = frame.sort_values(['Source_Dataset_ID', '__Inventory_Source_Row'], kind='stable').reset_index(drop=True)
            index = {'frame': frame, 'columns': columns,
                     'names': {int(row['id']): str(row['file_name']) for row in datasets},
                     'sources': source_column_map(task_repository, datasets)}
            buffer = io.BytesIO()
            pd.to_pickle(index, buffer, protocol=5)
            write_cache_file(folder, stored.name, buffer.getvalue(), keep=3, pattern='inventory-index-*.pkl')
            return index

        return remember(f'inventory-index:{digest}', build)

    def source_column_map(task_repository, datasets) -> dict[str, dict[int, str]]:
        """Displayed column -> stored column per inventory, as in the combined query."""
        schemas = {int(row['id']): task_repository.list_dataset_row_columns(row['id']) for row in datasets}
        source_columns = list(dict.fromkeys(column for columns in schemas.values() for column in columns))
        used = {column.casefold() for column in [*INVENTORY_KEY_COLUMNS, 'Source_Dataset_ID', 'Source_Dataset_Name']}
        used |= {'__inventory_cell_id', '__inventory_source_row'}
        mapping: dict[str, dict[int, str]] = {}
        for source in source_columns:
            name = f'Source_{source}' if column_identity(source) in {column_identity(key) for key in INVENTORY_KEY_COLUMNS} else source
            while name.casefold() in used:
                name = f'Source_{name}'
            used.add(name.casefold())
            mapping[name] = {dataset_id: source for dataset_id, columns in schemas.items() if source in columns}
        return mapping

    def selected_inventory(task_repository, request: SitesRequest) -> tuple[dict[str, Any], pd.DataFrame]:
        """Inventory index rows matching the Analysis Selection (Operator, Vendor, Region, City, Technology)."""
        index = inventory_index(task_repository)
        frame = index['frame']
        normalise = inventory_filter_normalizer(task_repository)
        mask = pd.Series(True, index=frame.index)
        operator_groups = [{'canonical': name} for name in pd.unique(frame['Operator']) if name] if 'Operator' in frame else []
        operator_vendors = [*request.operator_vendors,
                            *(swap_vendor_operator(value, operator_groups) for value in request.vendor_operators)]
        for field, values in (('Operator', request.operators), ('Operator_Vendor', operator_vendors),
                              ('Vendor', request.vendors), ('Region', request.regions),
                              ('Cluster', request.clusters), ('City', request.cities)):
            wanted = {normalise(value, field) for value in values if str(value).strip()}
            if wanted:
                keys = {value: normalise(value, field) for value in pd.unique(frame[field])}
                mask &= frame[field].map(keys).isin(wanted)
        technologies = ['LTE', 'NR'] if request.technology == 'lte_nr' else ['NR'] if request.technology == 'nr' else ['LTE']
        mask &= frame['Technology'].isin(technologies)
        return index, frame.loc[mask]

    def observed_cells(task_repository, request: SitesRequest) -> dict[str, Any]:
        """One row per LTE cell (or site without cell identity) observed in the selected CDRs."""
        samples_identity, _selected = samples_key(task_repository, request.datasets)
        selection = {key: value for key, value in request.model_dump().items()
                     if key in {'operators', 'operator_vendors', 'vendor_operators', 'vendors', 'campaigns', 'regions', 'clusters', 'cities', 'technology'}}
        digest = hashlib.sha256(json.dumps([OBSERVED_CACHE_VERSION, samples_identity, selection,
                                            inventory_polygon_sources(task_repository)], sort_keys=True, default=str).encode()).hexdigest()

        def build() -> dict[str, Any]:
            samples = load_samples(task_repository, request.datasets)
            filtered = filter_samples(samples, request)
            columns = list(OBSERVED_COLUMNS)
            if request.technology == 'nr' or filtered.empty:
                # Cell traces identify LTE cells only.
                return {'frame': pd.DataFrame(columns=columns), 'columns': columns}
            fields = ['operator', 'vendor', 'region', 'city', 'campaign', 'kind', 'lte_band', 'latitude', 'longitude', 'lte_rsrp', 'lte_sinr']
            with_cells = filtered.loc[filtered['cells'].map(len) > 0, [*fields, 'cells']].explode('cells').rename(columns={'cells': 'cell'})
            sites_only = filtered.loc[(filtered['cells'].map(len) == 0) & (filtered['enodebs'].map(len) > 0), [*fields, 'enodebs']]
            sites_only = sites_only.explode('enodebs').rename(columns={'enodebs': 'site'})
            sites_only['cell'] = ''
            sites = {value: (str(enodeb) if (enodeb := lte_enodeb_from_eci(value)) is not None else '') for value in pd.unique(with_cells['cell'])}
            with_cells['site'] = with_cells['cell'].map(sites)
            rows = pd.concat([with_cells, sites_only], ignore_index=True)
            rows = rows.loc[(rows['cell'] != '') | (rows['site'] != '')]
            if rows.empty:
                return {'frame': pd.DataFrame(columns=columns), 'columns': columns}
            keys = ['operator', 'site', 'cell']
            # Vectorised per-cell aggregation: blanks become missing so 'first'
            # takes the first non-empty value of each cell.
            for field in ('vendor', 'region', 'city', 'lte_band'):
                rows[field] = rows[field].replace('', pd.NA)
            grouped = rows.groupby(keys, sort=True, dropna=False).agg(
                Vendor=('vendor', 'first'), Region=('region', 'first'), City=('city', 'first'), Band=('lte_band', 'first'),
                Samples=('kind', 'size'), Latitude=('latitude', 'mean'), Longitude=('longitude', 'mean'),
                RSRP_Mean=('lte_rsrp', 'mean'), SINR_Mean=('lte_sinr', 'mean'),
            )
            codes = {key: position for position, key in enumerate(grouped.index)}
            for name, field in (('CDR_Types', 'kind'), ('Campaigns', 'campaign')):
                # One linear pass instead of a Python call per cell.
                distinct = rows.loc[rows[field] != '', [*keys, field]].drop_duplicates().sort_values(field)
                values: list[list[str]] = [[] for _ in range(len(grouped))]
                for key, value in zip(zip(*(distinct[column] for column in keys)), distinct[field]):
                    values[codes[key]].append(str(value))
                grouped[name] = [', '.join(items) for items in values]
            grouped = grouped.reset_index().rename(columns={'operator': 'Operator', 'site': 'Site_ID', 'cell': 'Cell_ID'})
            for field in ('Vendor', 'Region', 'City', 'Band'):
                grouped[field] = grouped[field].astype(object).where(grouped[field].notna(), '')
            grouped['Technology'] = 'LTE'
            for column in ('Latitude', 'Longitude'):
                grouped[column] = grouped[column].round(6)
            for column in ('RSRP_Mean', 'SINR_Mean'):
                grouped[column] = grouped[column].round(2)
            grouped['Cluster'] = observed_clusters(task_repository, grouped)
            return {'frame': grouped[columns].reset_index(drop=True), 'columns': columns}

        def stored_build() -> dict[str, Any]:
            folder = cache_directory(task_repository)
            stored = folder / f'observed-{digest}.pkl'
            if stored.is_file():
                try:
                    stored.touch()
                    return pd.read_pickle(stored)
                except Exception:
                    stored.unlink(missing_ok=True)
            result = build()
            buffer = io.BytesIO()
            pd.to_pickle(result, buffer, protocol=5)
            write_cache_file(folder, stored.name, buffer.getvalue(), keep=12, pattern='observed-*.pkl')
            return result

        return remember(f'observed:{digest}', stored_build)

    def observed_clusters(task_repository, frame: pd.DataFrame) -> pd.Series:
        """Cluster of each observed cell's mean position, when Clusters polygons are imported."""
        sources = inventory_polygon_sources(task_repository)
        lookups = inventory_polygon_lookup(sources) if sources else {}
        if 'Cluster' not in lookups or frame.empty:
            return pd.Series('', index=frame.index)
        import shapely

        tree, names = lookups['Cluster']
        located = frame['Longitude'].notna() & frame['Latitude'].notna()
        result = pd.Series('', index=frame.index, dtype=object)
        if not located.any():
            return result
        # One bulk spatial query; the first matching polygon names each cell.
        points = shapely.points(frame.loc[located, 'Longitude'].to_numpy(), frame.loc[located, 'Latitude'].to_numpy())
        inputs, matches = tree.query(points, predicate='intersects')
        first: dict[int, int] = {}
        for position, match in zip(inputs.tolist(), matches.tolist()):
            first.setdefault(position, match)
        positions = frame.index[located]
        result.loc[positions] = [names[first[position]] if position in first else '' for position in range(len(positions))]
        return result

    def table_operators(task_repository, request: SitesRequest, frame: pd.DataFrame) -> dict[str, str]:
        """Operators with a table: those of the uploaded inventories, otherwise the CDR operators."""
        labels = operator_labels(task_repository)
        if not labels and request.source == 'observed':
            labels = {value: value for value in pd.unique(frame['Operator']) if str(value).strip()}
        mappings = {str(key).casefold(): str(value) for key, value in task_repository.list_operator_mappings().items()}
        wanted = {mappings.get(value.casefold(), value) for value in request.operators if str(value).strip()}
        return {operator: label for operator, label in labels.items() if not wanted or operator in wanted}

    def text_values(series: pd.Series) -> pd.Series:
        """Values as filters compare them: text, with blanks as ''."""
        values = series.astype(object).where(series.notna(), '')
        return values.map(lambda value: '' if value is None else (str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)).strip())

    def source_rowids(task_repository, index, column: str, values: list[str]) -> dict[int, set[int]]:
        """Inventory rows whose stored column holds one of the values, per inventory."""
        quote = task_repository._quote_identifier
        wanted = [str(value) for value in values]
        rowids: dict[int, set[int]] = {}
        with task_repository.connection() as connection:
            for dataset_id in index['names']:
                stored = index['sources'].get(column, {}).get(dataset_id)
                table = quote(task_repository.dataset_rows_table_name(dataset_id))
                if stored is None:
                    # An inventory without the column has it blank in every row.
                    rowids[dataset_id] = ({int(row[0]) for row in connection.execute(f'SELECT rowid FROM {table}')}
                                          if '' in wanted else set())
                    continue
                text = f"TRIM(COALESCE(CAST({quote(stored)} AS TEXT), ''))"
                placeholders = ', '.join('?' for _ in wanted)
                rows = connection.execute(f'SELECT rowid FROM {table} WHERE {text} IN ({placeholders})', wanted).fetchall()
                rowids[dataset_id] = {int(row[0]) for row in rows}
        return rowids

    def apply_column_filters(task_repository, request: SitesRequest, index, frame: pd.DataFrame, skip: str = '') -> pd.DataFrame:
        for column, values in request.filters.items():
            if column == skip or values is None:
                continue
            accepted = {str(value) for value in values}
            if column in frame.columns and not column.startswith('__'):
                frame = frame.loc[text_values(frame[column]).isin(accepted)]
            elif request.source == 'inventory' and column == 'Source_Dataset_Name':
                names = {dataset_id for dataset_id, name in index['names'].items() if name in accepted}
                frame = frame.loc[frame['Source_Dataset_ID'].isin(names)]
            elif request.source == 'inventory' and column in index['sources']:
                rowids = source_rowids(task_repository, index, column, sorted(accepted))
                keys = set((dataset_id, rowid) for dataset_id, ids in rowids.items() for rowid in ids)
                pairs = pd.Series(list(zip(frame['Source_Dataset_ID'].astype(int), frame['__Inventory_Source_Row'].astype(int))), index=frame.index)
                frame = frame.loc[pairs.isin(keys)]
        return frame

    def table_frame(task_repository, request: SitesRequest, skip_filter: str = '') -> tuple[dict[str, Any], pd.DataFrame, list[str]]:
        """Rows of one Sites/Cells table after the Analysis Selection and column filters."""
        if request.source == 'observed':
            observed = observed_cells(task_repository, request)
            index, frame, columns = observed, observed['frame'], observed['columns']
        else:
            index, frame = selected_inventory(task_repository, request)
            columns = index['columns']
        if request.operator:
            frame = frame.loc[frame['Operator'] == request.operator]
        return index, apply_column_filters(task_repository, request, index, frame, skip_filter), columns

    def inventory_rows(task_repository, index, frame: pd.DataFrame, columns: list[str]) -> list[list[Any]]:
        """Complete rows of the given index entries, in index order."""
        quote = task_repository._quote_identifier
        stored: dict[tuple[int, int], dict[str, Any]] = {}
        with task_repository.connection() as connection:
            for dataset_id, part in frame.groupby('Source_Dataset_ID', sort=False):
                dataset_id = int(dataset_id)
                table = quote(task_repository.dataset_rows_table_name(dataset_id))
                fields = {name: sources[dataset_id] for name, sources in index['sources'].items() if dataset_id in sources}
                rowids = [int(value) for value in part['__Inventory_Source_Row']]
                for start in range(0, len(rowids), 500):
                    chunk = rowids[start:start + 500]
                    select = ', '.join(['rowid', *(quote(source) for source in fields.values())])
                    for row in connection.execute(f"SELECT {select} FROM {table} WHERE rowid IN ({', '.join('?' for _ in chunk)})", chunk):
                        stored[(dataset_id, int(row[0]))] = dict(zip(fields, row[1:]))
        rows = []
        for record in frame.to_dict('records'):
            dataset_id, rowid = int(record['Source_Dataset_ID']), int(record['__Inventory_Source_Row'])
            values = stored.get((dataset_id, rowid), {})
            row = []
            for column in columns:
                if column == 'Source_Dataset_Name':
                    row.append(index['names'].get(dataset_id, ''))
                elif column in record and not column.startswith('__'):
                    row.append(record[column])
                else:
                    row.append(values.get(column))
            rows.append(row)
        return rows

    def table_page(task_repository, request: SitesRequest, label: str = '') -> dict[str, Any]:
        index, frame, columns = table_frame(task_repository, request)
        total = len(frame)
        page = min(max(request.page, 0), max(0, (total - 1) // 50))
        visible = frame.iloc[page * 50:(page + 1) * 50]
        if request.source == 'inventory':
            rows = inventory_rows(task_repository, index, visible, columns)
            key_columns = list(INVENTORY_KEY_COLUMNS)
        else:
            rows = visible.astype(object).where(visible.notna(), None).values.tolist()
            key_columns = ['Operator', 'Site_ID', 'Cell_ID']
        return {'operator': request.operator, 'operator_label': label or request.operator, 'source': request.source,
                'columns': columns, 'key_columns': key_columns, 'rows': rows, 'total_rows': total, 'page': page,
                'page_size': 50, 'filters': {column: values for column, values in request.filters.items() if values is not None}}

    def table_suffix(labels: list[str]) -> str:
        """CSV suffix: _VF for Vodafone, _3 for Three and _VF_3 for both."""
        codes = []
        for label in labels:
            text = str(label).strip()
            code = {'vodafone': 'VF', 'vf': 'VF', 'vf_uk': 'VF', 'three': '3', '3': '3', '3uk': '3'}.get(text.casefold())
            codes.append(code or re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_'))
        ordered = sorted(dict.fromkeys(code for code in codes if code), key=lambda code: (code != 'VF', code != '3', code))
        return ('_' + '_'.join(ordered)) if ordered else ''

    @app.post('/api/network-insights/sites/tables')
    def network_insights_site_tables(request: SitesRequest, user=Depends(insights_user)):
        task_repository = bound_repository()
        _index, frame, _columns = table_frame(task_repository, SitesRequest(**{**request.model_dump(), 'operator': '', 'filters': {}}))
        labels = table_operators(task_repository, request, frame)
        tables = [table_page(task_repository, SitesRequest(**{**request.model_dump(), 'operator': operator, 'page': 0, 'filters': {}}), label)
                  for operator, label in labels.items()]
        return {'source': request.source, 'tables': tables}

    @app.post('/api/network-insights/sites/page')
    def network_insights_site_page(request: SitesRequest, user=Depends(insights_user)):
        task_repository = bound_repository()
        labels = operator_labels(task_repository)
        return table_page(task_repository, request, labels.get(request.operator, request.operator))

    @app.post('/api/network-insights/sites/values')
    def network_insights_site_values(request: SitesRequest, user=Depends(insights_user)):
        """Values of one column under every other filter, for its Excel-style filter."""
        task_repository = bound_repository()
        index, frame, columns = table_frame(task_repository, request, skip_filter=request.column)
        if request.column not in columns:
            raise HTTPException(400, 'Choose a column of the table.')
        if request.source == 'inventory' and request.column not in frame.columns and request.column != 'Source_Dataset_Name':
            counts = Counter()
            quote = task_repository._quote_identifier
            with task_repository.connection() as connection:
                for dataset_id, part in frame.groupby('Source_Dataset_ID', sort=False):
                    stored = index['sources'].get(request.column, {}).get(int(dataset_id))
                    if stored is None:
                        counts[''] += len(part)
                        continue
                    table = quote(task_repository.dataset_rows_table_name(int(dataset_id)))
                    rowids = json.dumps([int(value) for value in part['__Inventory_Source_Row']])
                    text = f"TRIM(COALESCE(CAST({quote(stored)} AS TEXT), ''))"
                    for value, count in connection.execute(
                        f'SELECT {text}, COUNT(*) FROM {table} WHERE rowid IN (SELECT value FROM json_each(?)) GROUP BY 1', [rowids],
                    ):
                        counts[str(value)] += int(count)
        elif request.column == 'Source_Dataset_Name':
            counts = Counter({index['names'].get(int(key), ''): int(value) for key, value in frame['Source_Dataset_ID'].value_counts().items()})
        else:
            counts = Counter(text_values(frame[request.column]).value_counts().to_dict())
        search = request.search.strip().casefold()
        values = sorted((value for value in counts if not search or search in value.casefold()), key=lambda value: (value == '', value.casefold()))
        return {'column': request.column, 'values': [{'value': value, 'count': counts[value]} for value in values[:2000]],
                'truncated': len(values) > 2000, 'selected': request.filters.get(request.column)}

    @app.post('/api/network-insights/sites/export')
    def network_insights_site_export(request: SitesRequest, user=Depends(insights_user)):
        from tempfile import NamedTemporaryFile

        from fastapi.responses import FileResponse
        from starlette.background import BackgroundTask

        task_repository = bound_repository()
        index, frame, columns = table_frame(task_repository, request)
        labels = operator_labels(task_repository) or {value: value for value in pd.unique(frame['Operator'])}
        included = [request.operator] if request.operator else list(dict.fromkeys(str(value) for value in frame['Operator']))
        suffix = table_suffix([labels.get(operator, operator) for operator in included] or list(labels.values()))
        name = ('cdr-observed-sites-cells' if request.source == 'observed' else 'site-cell-inventory') + f'{suffix}.csv'
        with NamedTemporaryFile(mode='w', newline='', encoding='utf-8', suffix='.csv', delete=False) as output:
            destination = Path(output.name)
            try:
                writer = csv.writer(output)
                writer.writerow(columns)
                for start in range(0, len(frame), 5000):
                    chunk = frame.iloc[start:start + 5000]
                    rows = (inventory_rows(task_repository, index, chunk, columns) if request.source == 'inventory'
                            else chunk.astype(object).where(chunk.notna(), None).values.tolist())
                    writer.writerows(['' if value is None else value for value in row] for row in rows)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
        return FileResponse(destination, media_type='text/csv', filename=name,
                            background=BackgroundTask(destination.unlink, missing_ok=True))

    # Earlier routes of the complete inventory tables answer through the same tables.
    @app.post('/api/network-insights/inventory/tables')
    def network_insights_inventory_tables(request: AnalysisRequest, user=Depends(insights_user)):
        tables = network_insights_site_tables(SitesRequest(**request.model_dump(), source='inventory'), user)['tables']
        return {'inventories': tables}

    @app.post('/api/network-insights/inventory')
    def network_insights_combined_inventory(request: AnalysisRequest, page: int = Query(0, ge=0),
                                          operator: str = '', user=Depends(insights_user)):
        return network_insights_site_page(SitesRequest(**request.model_dump(), source='inventory', page=page, operator=operator), user)

    @app.post('/api/network-insights/inventory/export')
    def network_insights_combined_inventory_export(request: AnalysisRequest, operator: str = '', user=Depends(insights_user)):
        return network_insights_site_export(SitesRequest(**request.model_dump(), source='inventory', operator=operator), user)

    def inventory_records(task_repository, dataset: dict[str, Any], page: int = 0) -> dict[str, Any]:
        """Read a bounded page without discarding inventory columns or unmatched rows."""
        columns = task_repository.list_dataset_row_columns(dataset['id'])
        total = task_repository.dataset_row_count(dataset['id'])
        page = min(page, max(0, (total - 1) // 50))
        frame, total, _values = task_repository.load_dataset_preview_page(
            dataset['id'], columns, {}, page, 50,
        )
        return {**dataset, 'columns': columns, 'rows': json.loads(frame.to_json(orient='values', double_precision=15)),
                'total_rows': total, 'page': page, 'page_size': 50}

    @app.get('/api/network-insights/inventory/{dataset_id}')
    def network_insights_inventory(dataset_id: int, page: int = Query(0, ge=0),
                                   download: bool = False, user=Depends(insights_user)):
        task_repository = bound_repository()
        dataset = next((row for row in inventory_datasets(task_repository) if row['id'] == dataset_id), None)
        if dataset is None:
            raise HTTPException(404, 'Ready Vodafone or Three inventory not found in the active workspace.')
        if download:
            columns = task_repository.list_dataset_row_columns(dataset_id)
            return StreamingResponse(
                task_repository.stream_dataset_preview_csv(dataset_id, columns, {}),
                media_type='text/csv',
                headers={'Content-Disposition': f'attachment; filename="site-inventory{table_suffix([dataset["operator"]])}.csv"'},
            )
        return inventory_records(task_repository, dataset, page)

    @app.get('/api/network-insights/deployment/{dataset_id}/export')
    def network_insights_deployment_export(dataset_id: int, group: str = 'scenario', user=Depends(insights_user)):
        if group not in DEPLOYMENT_GROUPINGS:
            raise HTTPException(400, 'Choose a supported network deployment grouping.')
        task_repository = bound_repository()
        require_cluster_dataset(group, task_repository)
        dataset = next((row for row in inventory_datasets(task_repository) if row['id'] == dataset_id), None)
        if dataset is None:
            raise HTTPException(404, 'Ready Vodafone or Three inventory not found in the active workspace.')
        summary = inventory_summary(task_repository, dataset, group)
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow([DEPLOYMENT_GROUPINGS[group] if group in summary['available_groups'] else 'Inventory',
                         'Sites', 'Cells'])
        writer.writerows((row['group'], row['sites'], row['cells']) for row in summary['rows'])
        return StreamingResponse(
            iter([output.getvalue()]), media_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename="network-deployment-{group}{table_suffix([dataset["operator"]])}.csv"'},
        )

    @app.get('/api/network-insights/deployment/export-all')
    def network_insights_deployment_export_all(group: str = 'scenario', user=Depends(insights_user)):
        if group not in DEPLOYMENT_GROUPINGS:
            raise HTTPException(400, 'Choose a supported network deployment grouping.')
        deployment = deployment_summary(group)
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Operator', 'Source_Dataset_ID', 'Source_Dataset_Name', DEPLOYMENT_GROUPINGS[group], 'Sites', 'Cells'])
        for inventory in deployment['inventories']:
            writer.writerows((inventory['operator'], inventory['id'], inventory['file_name'],
                              row['group'], row['sites'], row['cells']) for row in inventory['rows'])
        suffix = table_suffix([inventory['operator'] for inventory in deployment['inventories']])
        return StreamingResponse(iter([output.getvalue()]), media_type='text/csv',
                                 headers={'Content-Disposition': f'attachment; filename="network-deployment-{group}{suffix}.csv"'})

    @app.get('/api/network-insights/deployment')
    def network_insights_deployment(group: str = 'scenario', user=Depends(insights_user)):
        return deployment_summary(group)

    def inventory_revision(task_repository, dataset: dict[str, Any]) -> tuple:
        """Profile revision plus row count and last row, so any row change refreshes caches."""
        table = task_repository._quote_identifier(task_repository.dataset_rows_table_name(dataset['id']))
        try:
            with task_repository.connection() as connection:
                count, last = connection.execute(f'SELECT COUNT(*), MAX(rowid) FROM {table}').fetchone()
        except sqlite3.OperationalError:
            count, last = 0, 0
        columns = tuple(task_repository.list_dataset_row_columns(dataset['id']))
        return dataset['updated_at'], int(count or 0), int(last or 0), columns

    def cached_inventory_projection(task_repository, dataset: dict[str, Any]) -> dict[str, Any]:
        """An inventory's identifiers and grouping fields, kept in memory and on disk."""
        key = (str(Path(task_repository.db_path).resolve()), dataset['id'],
               dataset['file_name'], inventory_revision(task_repository, dataset), inventory_polygon_sources(task_repository))
        with inventory_cache_lock:
            cached = inventory_cache.get(key)
            if cached is not None:
                inventory_cache.move_to_end(key)
                return cached
        folder = cache_directory(task_repository)
        digest = hashlib.sha256(json.dumps([INVENTORY_CACHE_VERSION, *key], default=str).encode()).hexdigest()
        stored = folder / f'inventory-{digest}.pkl'
        frame = None
        if stored.is_file():
            try:
                frame = pd.read_pickle(stored)
                stored.touch()
            except Exception:
                stored.unlink(missing_ok=True)
        if frame is None:
            frame = inventory_projection(task_repository, dataset)
            buffer = io.BytesIO()
            frame.to_pickle(buffer, protocol=5)
            write_cache_file(folder, stored.name, buffer.getvalue(), keep=8, pattern='inventory-*.pkl')
        with inventory_cache_lock:
            cached = inventory_cache.setdefault(key, {'frame': frame, 'summaries': {}})
            inventory_cache.move_to_end(key)
            while len(inventory_cache) > 6:
                inventory_cache.popitem(last=False)
        return cached

    def deployment_summary(group: str = 'scenario') -> dict[str, Any]:
        task_repository = bound_repository()
        require_cluster_dataset(group, task_repository)
        results = []
        for dataset in inventory_datasets(task_repository):
            if group == 'inventory':
                results.append(inventory_records(task_repository, dataset))
                continue
            cached = cached_inventory_projection(task_repository, dataset)
            with inventory_cache_lock:
                grouping = group if group in DEPLOYMENT_GROUPINGS else None
                if grouping not in cached['summaries']:
                    cached['summaries'][grouping] = inventory_summary(
                        task_repository, dataset, grouping, frame=cached['frame'])
                summary = cached['summaries'][grouping]
            results.append({**dataset, **summary})
        return {'group': group, 'group_label': DEPLOYMENT_GROUPINGS.get(group, 'All'), 'inventories': results}

    def cluster_inventory_summary() -> dict[str, Any]:
        """Count inventory identifiers per operator, deduplicating overlapping uploads."""
        task_repository = bound_repository()
        frames: dict[str, list[pd.DataFrame]] = {}
        for dataset in inventory_datasets(task_repository):
            frames.setdefault(dataset['operator'], []).append(cached_inventory_projection(task_repository, dataset)['frame'])
        rows = []
        for operator, sources in sorted(frames.items()):
            frame = pd.concat(sources, ignore_index=True)
            totals = inventory_summary(task_repository, {}, None, frame=frame)['totals']
            if totals:
                rows.append({'operator': operator, **totals})
        return {'rows': rows}

    @app.get('/api/network-insights/cluster-inventories')
    def network_insights_cluster_inventories(user=Depends(insights_user)):
        return cluster_inventory_summary()

    def write_summary(selection: dict[str, Any], export_kind: str, destination: Path) -> dict[str, Any]:
        """Write the Summary Network Insights (PowerPoint or Word) for a saved or current selection.

        An empty dataset selection analyses every ready Data, Voice and Speech CDR.
        Returns the selection description used in the document.
        """
        from src.modules.cdr_reporting import _render_dashboard_payload
        from src.modules.network_insights_export import export_network_insights_powerpoint, export_network_insights_word

        task_repository = bound_repository()
        available = ready_cdrs(task_repository)
        request = AnalysisRequest.model_validate(selection or {})
        if not any(request.datasets.get(kind) for kind in NETWORK_INSIGHTS_KINDS):
            # Like the page, an analysis covers the CDRs of one NR Mode.
            nr_mode = str((selection or {}).get('nr_mode') or 'NSA').upper()
            request.datasets = {kind: [row['id'] for row in available if row['kind'] == kind and str(row['nr_mode']).upper() == nr_mode]
                                for kind in NETWORK_INSIGHTS_KINDS}
        request.map_all_groups = True
        analysis = run_analysis(request)
        names = {row['id']: row['file_name'] for row in available}
        description = {
            **request.model_dump(), 'technology_label': analysis['technology_label'], 'group_label': analysis['group_label'],
            'nr_mode': str((selection or {}).get('nr_mode') or '').upper(),
            'dataset_names': [names[dataset_id] for kind in NETWORK_INSIGHTS_KINDS for dataset_id in request.datasets.get(kind, []) if dataset_id in names],
        }
        deployment = {'groupings': [deployment_summary(group) for group in DEPLOYMENT_GROUPINGS
                                    if group != 'cluster' or cluster_grouping_available(task_repository)],
                      'cluster_inventories': cluster_inventory_summary()}
        render = lambda payload, width, height: _render_dashboard_payload(payload, width=width, height=height)[0]
        writer = export_network_insights_word if export_kind == 'word' else export_network_insights_powerpoint
        writer(destination, analysis, deployment, description, render)
        return description

    core.write_network_insights_summary = write_summary

    @app.post('/api/network-insights/export/{export_kind}')
    def network_insights_export(export_kind: str, request: AnalysisRequest, user=Depends(insights_user)):
        from datetime import datetime

        from fastapi.responses import FileResponse

        if export_kind not in {'word', 'powerpoint'}:
            raise HTTPException(404, 'Unsupported export type.')
        suffix = 'docx' if export_kind == 'word' else 'pptx'
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        destination = core.safe_join(module_output_dir(core.settings.output_dir, NETWORK_INSIGHTS_FOLDER, create=True),
                                     f'{stamp}_summary_network_insights.{suffix}')
        try:
            write_summary(request.model_dump(), export_kind, destination)
        except HTTPException:
            raise
        except Exception as exc:
            # The reason reaches the page's error dialog and the server console.
            import traceback
            traceback.print_exc()
            raise HTTPException(500, f'The {export_kind} export failed: {exc}') from exc
        core.repository.try_add_log(user.username, f'export_network_insights_{export_kind}', json.dumps({'file': destination.name}))
        media_type = ('application/vnd.openxmlformats-officedocument.wordprocessingml.document' if export_kind == 'word'
                      else 'application/vnd.openxmlformats-officedocument.presentationml.presentation')
        return FileResponse(destination, filename=f'{stamp} - Network Insights - Summary.{suffix}', media_type=media_type)

    @app.get('/api/network-insights/spectrum')
    def network_insights_spectrum(user=Depends(insights_user)):
        holdings = load_spectrum_holdings(bound_repository())
        return {'holdings': holdings, 'summary': licensed_spectrum_summary(holdings)}

    @app.put('/api/network-insights/spectrum')
    def network_insights_spectrum_save(request: SpectrumRequest, user=Depends(editor_user)):
        try:
            holdings = normalise_spectrum_holdings(request.holdings)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        task_repository = bound_repository()
        save_spectrum_holdings(task_repository, holdings)
        task_repository.try_add_log(user.username, 'network_spectrum_holdings_saved', json.dumps({'rows': len(holdings)}))
        return {'holdings': holdings, 'summary': licensed_spectrum_summary(holdings)}

    @app.post('/workspace-config/spectrum-holdings/save')
    def workspace_spectrum_holdings_save(holdings_csv: str = Form(''), user=Depends(core.config_editor_user)):
        def redirect(key: str, message: str) -> RedirectResponse:
            return RedirectResponse(f'/workspace-config?{urlencode({key: message})}#spectrum-holdings', status_code=303)

        if not core.active_workspace:
            return redirect('spectrum_holdings_error', 'Open a workspace before editing Spectrum Holdings.')
        try:
            holdings = parse_spectrum_csv(holdings_csv)
        except ValueError as exc:
            return redirect('spectrum_holdings_error', str(exc))
        task_repository = bound_repository()
        save_spectrum_holdings(task_repository, holdings)
        task_repository.try_add_log(user.username, 'network_spectrum_holdings_saved', json.dumps({'rows': len(holdings)}))
        return redirect('spectrum_holdings_notice', f'Spectrum Holdings saved ({len(holdings)} rows).')


def load_spectrum_holdings(task_repository: Any) -> list[dict[str, Any]]:
    """Return the validated licensed spectrum holdings of a workspace."""
    import json

    try:
        rows = json.loads(task_repository.get_workspace_state(SPECTRUM_HOLDINGS_STATE_KEY) or '[]')
        return normalise_spectrum_holdings(rows if isinstance(rows, list) else [])
    except (TypeError, ValueError):
        return []


def save_spectrum_holdings(task_repository: Any, holdings: list[dict[str, Any]]) -> None:
    import json

    task_repository.set_workspace_state(SPECTRUM_HOLDINGS_STATE_KEY, json.dumps(normalise_spectrum_holdings(holdings), ensure_ascii=False))
