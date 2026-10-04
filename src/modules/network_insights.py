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
import math
import re
from collections import Counter
from typing import Any, Iterable

import pandas as pd

from src.modules.column_names import column_identity, compact_campaign_value, vendor_filter_values


NETWORK_INSIGHTS_KINDS = ('data', 'voice', 'speech')
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
    'vendor': ('Vendor_Only',),
    'campaign': ('Campaign', 'Period'),
    'region': ('Region', 'G_Level_2'),
    'city': ('City', 'G_Level_4'),
    'source_sheet': ('source_sheet',),
}
GROUPINGS = {'operator': 'Operator', 'vendor': 'Vendor', 'region': 'Region', 'city': 'City', 'kind': 'CDR type', 'technology': 'Technology', 'campaign': 'Campaign'}
TECHNOLOGIES = {'lte': 'LTE', 'nr': 'NR', 'lte_nr': 'LTE+NR'}

# Default classification bands. Thresholds are user-adjustable in the module;
# these defaults follow common drive-test reporting practice.
DEFAULT_COVERAGE_THRESHOLD = -110.0
DEFAULT_INTERFERENCE_THRESHOLD = 0.0
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
    for field in ('operator', 'vendor', 'campaign', 'region', 'city'):
        source = columns.get(field)
        values = frame[source] if source in frame.columns else pd.Series('', index=frame.index)
        result[field] = values.fillna('').astype(str).str.strip()
    result['campaign'] = result['campaign'].map(lambda value: compact_campaign_value(value) or value)
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
        enodebs = {item for values in part['enodebs'] for item in values}
        cells = {item for values in part['cells'] for item in values}
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
    labels = Counter(classify(float(value), classes)[0] for value in values)
    return [
        {'label': label, 'colour': colour, 'share': round(labels.get(label, 0) / len(values) * 100, 1)}
        for label, _lower, colour in classes
    ]


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
) -> dict[str, Any]:
    """Build a Canvas CDF model (one curve per Operator and group).

    ``dash_groups`` maps each Operator label to its secondary grouping value,
    so curves sharing an Operator colour use a different line style per value.
    """
    dash_values = sorted(set(dash_groups.values()), key=str.casefold) if dash_groups else []
    series = []
    legend = []
    keys = ['operator', *([group] if group else [])]
    lows, highs = [], []
    group_values = list(dict.fromkeys(samples[group])) if group else []
    for key, part in samples.groupby(keys, sort=False, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        values = part[value_column].dropna().sort_values()
        if values.empty:
            continue
        quantiles = [index / (points - 1) for index in range(points)]
        x = [round(float(values.quantile(q)), 2) for q in quantiles]
        lows.append(x[0]); highs.append(x[-1])
        name = ' · '.join(str(item) for item in key if str(item))
        if group:
            dash = SERIES_DASHES[group_values.index(key[1]) % len(SERIES_DASHES)]
        elif dash_groups and key[0] in dash_groups:
            dash = SERIES_DASHES[dash_values.index(dash_groups[key[0]]) % len(SERIES_DASHES)]
        else:
            dash = []
        colour = colours.get(key[0], OPERATOR_FALLBACK_COLOURS[0])
        series.append({'name': name, 'colour': colour, 'width': 3, 'dash': dash, 'x': x, 'y': quantiles})
        legend.append({'label': name, 'colour': colour, 'width': 3, 'dash': dash})
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
            city=('city', lambda values: Counter(values).most_common(1)[0][0] if len(values) else ''),
            region=('region', lambda values: Counter(values).most_common(1)[0][0] if len(values) else ''),
        ).reset_index()
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
    'cell': ('CId___ECI', 'CELL_NAME', 'Cell Name', 'cellId', 'Cell ID'),
    'scenario': ('eMOCNScenario',),
    'network': ('Network',),
    'host_network': ('Host Network',),
    'vendor': ('OP_Vendor', 'OP/ Vendor', 'Vendor'),
    'region': ('Region',),
    'subregion': ('Subregion',),
    'site_type': ('Site_Type', 'Site Type'),
    'band': ('Band', 'Frequency Band'),
}
DEPLOYMENT_GROUPINGS = {
    'scenario': 'eMOCN Scenario', 'host_network': 'Host Network', 'network': 'Network', 'vendor': 'RAN Vendor',
    'region': 'Region', 'subregion': 'Subregion', 'site_type': 'Site Type', 'band': 'Band',
}


# ---------------------------------------------------------------------------
# Inventory (Vendor mapping datasets)
# ---------------------------------------------------------------------------
INVENTORY_DATASET_KINDS = {'mapping_vodafone': 'Vodafone', 'mapping_three': 'Three'}


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
    selected = ', '.join(f'{expression} AS {quote(field)}'
                         for field, expression in expressions.items() if expression)
    table = quote(task_repository.dataset_rows_table_name(dataset_id))
    with task_repository.connection() as connection:
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
    grouped = frame.assign(_group=frame[group].fillna('Not set') if group in available_groups else 'All')
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

    from fastapi import Depends, Form, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from pydantic import BaseModel, Field

    from src.modules.cdr_reporting import _osm_map_tile_geometry

    app = core.app
    sample_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
    sample_cache_lock = Lock()
    inventory_cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
    inventory_cache_lock = Lock()

    class AnalysisRequest(BaseModel):
        datasets: dict[str, list[int]] = Field(default_factory=dict)
        technology: str = 'lte'
        group: list[str] | str = Field(default_factory=lambda: ['operator', 'campaign'])
        operators: list[str] = Field(default_factory=list)
        vendors: list[str] = Field(default_factory=list)
        campaigns: list[str] = Field(default_factory=list)
        regions: list[str] = Field(default_factory=list)
        cities: list[str] = Field(default_factory=list)
        coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD
        interference_threshold: float = DEFAULT_INTERFERENCE_THRESHOLD
        grid_metres: float = 250
        min_samples: int = 3
        map_operator: str = ''

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

    def load_samples(task_repository, datasets: dict[str, list[int]]) -> pd.DataFrame:
        available = {row['id']: row for row in ready_cdrs(task_repository)}
        selected = {
            kind: [int(dataset_id) for dataset_id in datasets.get(kind, []) if int(dataset_id) in available and available[int(dataset_id)]['kind'] == kind]
            for kind in NETWORK_INSIGHTS_KINDS
        }
        if not any(selected.values()):
            raise HTTPException(400, 'Select at least one ready CDR.')
        fingerprint = json.dumps({
            'database': str(Path(task_repository.db_path).resolve()),
            'datasets': {kind: [(dataset_id, available[dataset_id]['updated_at']) for dataset_id in ids] for kind, ids in selected.items()},
            'mappings': task_repository.chart_mapping_settings().get('operator_mappings'),
        }, sort_keys=True, default=str)
        key = hashlib.sha256(fingerprint.encode()).hexdigest()
        with sample_cache_lock:
            cached = sample_cache.get(key)
            if cached is not None:
                sample_cache.move_to_end(key)
                return cached
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
        samples = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        with sample_cache_lock:
            sample_cache[key] = samples
            while len(sample_cache) > 3:
                sample_cache.popitem(last=False)
        return samples

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
                'groupings': GROUPINGS,
                'main_cities': task_repository.list_main_cities(),
                'technologies': TECHNOLOGIES,
                'coverage_threshold': DEFAULT_COVERAGE_THRESHOLD,
                'interference_threshold': DEFAULT_INTERFERENCE_THRESHOLD,
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
        task_repository = bound_repository()
        available = {row['id']: row for row in ready_cdrs(task_repository)}
        fields = ('vendor',) if vendor_only else ('operator', 'region', 'city', 'campaign')
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
        catalogues = task_repository.cdr_catalogues_by_dataset(selected)
        for catalogue in catalogues.values():
            for field in values:
                catalogue_key = 'vendors_only' if field == 'vendor' else 'cities' if field == 'city' else field + 's'
                values[field].update(catalogue.get(catalogue_key, []))
        if values.get('operator'):
            frame = pd.DataFrame({'Operator': sorted(values['operator'])})
            frame = core.apply_operator_mappings(frame, mappings.get('operator_mappings') or {})
            frame.attrs.update(mappings)
            frame = core.normalise_operator_aliases(frame)
            values['operator'] = set(frame['Operator'].dropna().astype(str))
        if 'campaign' in values:
            values['campaign'] = {compact_campaign_value(value) or value for value in values['campaign']}
        return {'options': {field + 's' if field != 'city' else 'cities': sorted(
            (value for value in items if str(value).strip()), key=str.casefold,
        ) for field, items in values.items()}}

    @app.post('/api/network-insights/analysis')
    def network_insights_analysis(request: AnalysisRequest, user=Depends(insights_user)):
        technology = request.technology if request.technology in TECHNOLOGIES else 'lte'
        requested_groups = [request.group] if isinstance(request.group, str) else request.group
        # LTE+NR always separates the technologies: LTE RSRP/SINR and NR
        # SS-RSRP/SS-SINR use different reference signals and are never pooled.
        # Operator can only be left out when Vendor groups the samples instead.
        if 'vendor' not in requested_groups:
            requested_groups = ['operator', *requested_groups]
        groups = [field for field in GROUPINGS
                  if (field == 'technology' and technology == 'lte_nr')
                  or (field != 'technology' and field in requested_groups)]
        group_label = ' → '.join(GROUPINGS[field] for field in groups) or 'All samples'
        task_repository = bound_repository()
        samples = load_samples(task_repository, request.datasets)
        if samples.empty:
            raise HTTPException(400, 'The selected CDRs have no samples.')
        options = {
            'operators': [value for value in dict.fromkeys(samples['operator']) if value],
            'vendors': sorted({value for value in samples['vendor'] if value}, key=str.casefold),
            'regions': sorted({value for value in samples['region'] if value}, key=str.casefold),
            'cities': sorted({value for value in samples['city'] if value}, key=str.casefold),
            'campaigns': sorted({value for value in samples['campaign'] if value}, key=str.casefold),
        }
        filtered = samples
        for field, values in (('operator', request.operators), ('vendor', request.vendors), ('region', request.regions), ('city', request.cities), ('campaign', request.campaigns)):
            if field == 'vendor':
                values = vendor_filter_values(values, samples['operator'].dropna().unique())
            wanted = {str(value).casefold() for value in values if str(value).strip()}
            if wanted:
                filtered = filtered.loc[filtered[field].str.casefold().isin(wanted)]
        if filtered.empty:
            raise HTTPException(400, 'No samples match the selected filters.')
        filtered = filtered.copy()
        if 'technology' in groups:
            technology_frames = []
            for radio in ('lte', 'nr'):
                part = filtered.loc[filtered[[f'{radio}_rsrp', f'{radio}_sinr']].notna().any(axis=1)].copy()
                part['technology'] = TECHNOLOGIES[radio]
                other = 'nr' if radio == 'lte' else 'lte'
                for metric in ('rsrp', 'sinr', 'bandwidth'):
                    part[f'{other}_{metric}'] = math.nan
                part[f'{other}_band'] = ''
                technology_frames.append(part)
            filtered = pd.concat(technology_frames, ignore_index=True)
            if filtered.empty:
                raise HTTPException(400, 'No LTE or NR radio measurements match the selected filters.')
            # Each row now carries one technology, so its values form one column.
            for metric in ('rsrp', 'sinr'):
                filtered[f'lte_nr_{metric}'] = filtered[f'lte_{metric}'].fillna(filtered[f'nr_{metric}'])
        original_operators = filtered['operator'].copy()
        # Operator is a grouping dimension only when explicitly selected.
        # Site/cell identifiers remain scoped by their source operator when pooled.
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
        group_column = None
        # Curves sharing an Operator colour differ by line style per secondary group.
        secondary = [field for field in groups if field != 'operator']
        dash_groups = None
        if 'operator' in groups and secondary:
            secondary_labels = filtered[secondary].fillna('').astype(str).agg(' · '.join, axis=1)
            dash_groups = dict(zip(labels, secondary_labels, strict=True))
        rsrp, sinr = f'{technology}_rsrp', f'{technology}_sinr'
        mapping_groups = task_repository.list_operator_mapping_groups()
        if 'operator' in groups:
            source_colours = operator_colours(original_operators, mapping_groups)
            colours = {label: source_colours[operator]
                       for label, operator in zip(labels, original_operators, strict=True)}
        else:
            colours = operator_colours(filtered['operator'], [])
        overview = rf_summary(filtered, technology, None, request.coverage_threshold, request.interference_threshold)
        overview.sort(key=lambda row: str(row['operator']).casefold())
        campaigns = [value for value in options['campaigns'] if value in set(filtered['campaign'])]
        comparison = None
        if len(campaigns) >= 2 and 'campaign' not in groups:
            previous, latest = campaigns[-2], campaigns[-1]
            by_campaign = {
                (row['operator'], row['group']): row
                for row in rf_summary(filtered.loc[filtered['campaign'].isin([previous, latest])], technology, 'campaign',
                                      request.coverage_threshold, request.interference_threshold)
            }
            for row in overview:
                before, after = by_campaign.get((row['operator'], previous)), by_campaign.get((row['operator'], latest))
                row['deltas'] = {
                    metric: (round(after[metric] - before[metric], 2) if before and after and after[metric] is not None and before[metric] is not None else None)
                    for metric in ('rsrp_median', 'low_coverage_share', 'sinr_median', 'high_interference_share')
                }
            comparison = {'previous': previous, 'latest': latest}
        map_operators = [row['operator'] for row in overview]
        map_operator = request.map_operator if request.map_operator in map_operators else (map_operators[0] if map_operators else '')
        operator_samples = filtered.loc[filtered['operator'] == map_operator]
        coverage_cells, coverage_grid = grid_cells(operator_samples, rsrp, request.coverage_threshold, request.grid_metres, request.min_samples)
        interference_cells, interference_grid = grid_cells(operator_samples, sinr, request.interference_threshold, request.grid_metres, request.min_samples)
        technology_label = TECHNOLOGIES[technology]
        holdings = load_spectrum_holdings(task_repository)
        warnings = []
        rsrp_available = filtered[['lte_rsrp', 'nr_rsrp']].notna().any().any() if technology == 'lte_nr' else filtered[rsrp].notna().any()
        if not rsrp_available:
            warnings.append(f'The selected CDRs carry no {technology_label} RSRP samples.')
        if filtered[['latitude', 'longitude']].dropna().empty:
            warnings.append('The selected CDRs carry no sample coordinates, so maps are unavailable.')
        return {
            'technology': technology, 'technology_label': technology_label,
            'group': groups, 'group_label': group_label,
            'options': options, 'comparison': comparison,
            'overview': overview,
            'rf_rows': overview,
            'charts': {
                'rsrp_cdf': cdf_payload(filtered, rsrp, group_column, f'{technology_label} RSRP', 'RSRP (dBm)', colours, dash_groups=dash_groups),
                'sinr_cdf': cdf_payload(filtered, sinr, group_column, f'{technology_label} SINR', 'SINR (dB)', colours, dash_groups=dash_groups),
            },
            'maps': {
                'operator': map_operator, 'operators': map_operators,
                'coverage': map_payload(coverage_cells, RSRP_CLASSES, f'{map_operator} · Mean {technology_label} RSRP per {coverage_grid:g} m grid', 'dBm', _osm_map_tile_geometry),
                'coverage_hotspots': hotspots(coverage_cells), 'coverage_grid_metres': coverage_grid,
                'interference': map_payload(interference_cells, SINR_CLASSES, f'{map_operator} · Mean {technology_label} SINR per {interference_grid:g} m grid', 'dB', _osm_map_tile_geometry),
                'interference_hotspots': hotspots(interference_cells), 'interference_grid_metres': interference_grid,
            },
            'spectrum': {
                'observed': observed_spectrum(filtered),
                'licensed': licensed_spectrum_summary(holdings),
            },
            'colours': colours,
            'warnings': warnings,
        }

    @app.get('/api/network-insights/deployment')
    def network_insights_deployment(group: str = 'scenario', user=Depends(insights_user)):
        task_repository = bound_repository()
        results = []
        for dataset in inventory_datasets(task_repository):
            # Profile revisions change after processing and supported table edits.
            key = (str(Path(task_repository.db_path).resolve()), dataset['id'],
                   dataset['file_name'], dataset['updated_at'])
            with inventory_cache_lock:
                cached = inventory_cache.get(key)
                if cached is None:
                    cached = {'frame': inventory_projection(task_repository, dataset), 'summaries': {}}
                    inventory_cache[key] = cached
                inventory_cache.move_to_end(key)
                while len(inventory_cache) > 4:
                    inventory_cache.popitem(last=False)
                grouping = group if group in DEPLOYMENT_GROUPINGS else None
                if grouping not in cached['summaries']:
                    cached['summaries'][grouping] = inventory_summary(
                        task_repository, dataset, grouping, frame=cached['frame'])
                summary = cached['summaries'][grouping]
            results.append({**dataset, **summary})
        return {'group': group, 'group_label': DEPLOYMENT_GROUPINGS.get(group, 'All'), 'inventories': results}

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
