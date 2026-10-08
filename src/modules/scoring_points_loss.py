"""Where the scoring points are lost: KPI point losses attributed to the tests that cause them.

For every KPI of every scoring group, the tests that make the KPI lose points get a
weight: the tests that miss the KPI condition (a failed call, POLQA below 1.6, a
transfer below 2 Mbit/s...) weigh one each, and for averages, medians and P90 each test
weighs what it misses the KPI's High threshold by. The share of each area (City,
Region or Cluster of the CDR rows, and the ITL3 area (the UK NUTS3 level) containing the
test) is the sum of its tests' weights over the total, so the points an operator loses in
a KPI can be placed on a map with any scoring's points.

The ITL3 boundaries are the ONS "International Territorial Level 3 (January 2025)
Boundaries UK BUC" (Open Government Licence v3.0) in ``assets/geo``. Workspaces with a
Clusters or Region Mapping dataset also map the Cluster and Region losses on its polygons.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import PROJECT_ROOT

AREA_FIELDS = {'City': ('City', 'G_Level_4'), 'Region': ('Region',), 'Cluster': ('Cluster',)}
COORDINATE_SOURCES = {
    'data': (('Test_Start_Latitude', 'Test_Start_Longitude'),),
    'voice': (('Call_Start_Latitude_A', 'Call_Start_Longitude_A'),),
    'speech': (('Recording_Latitude', 'Recording_Longitude'), ('Playing_Latitude', 'Playing_Longitude')),
}
BOUNDARY_FIELDS = {'ITL3': ('uk-itl3-2025.geojson', 'ITL325NM')}
MAP_FIELDS = (*AREA_FIELDS, *BOUNDARY_FIELDS)
BOUNDARY_DIRECTORY = PROJECT_ROOT / 'assets' / 'geo'
NOT_SPECIFIED = 'Not specified'
AREA_COLUMN = '__area_{}'
LATITUDE, LONGITUDE, PLACE = '__latitude', '__longitude', '__place'
MAX_AREA_POINTS = 60
MAX_BACKGROUND_POINTS = 4000
_RATIO = re.compile(r'(100 \* )?(SUM|COUNT)\((.+)\) / (SUM|COUNT)\((\w+)\)')
_AGGREGATE = re.compile(r'(AVG|MEDIAN|PCT90)\((\w+)\)')


def source_columns(kind: str) -> list[str]:
    """CDR columns read for the points-lost map, in addition to the scoring columns."""
    columns = [name for aliases in AREA_FIELDS.values() for name in aliases]
    columns.extend(name for pair in COORDINATE_SOURCES.get(kind, ()) for name in pair)
    return columns


def attach_location(frame: pd.DataFrame, source: pd.DataFrame, kind: str, resolve) -> None:
    """Copy the area and coordinate columns of the source rows into the scoring frame."""
    for field, aliases in AREA_FIELDS.items():
        column = next((resolved for alias in aliases if (resolved := resolve(source.columns, alias)) is not None), None)
        if column is not None:
            frame[AREA_COLUMN.format(field)] = source[column].astype('string').str.strip()
    for latitude_name, longitude_name in COORDINATE_SOURCES.get(kind, ()):
        latitude, longitude = resolve(source.columns, latitude_name), resolve(source.columns, longitude_name)
        if latitude is not None and longitude is not None:
            frame[LATITUDE] = pd.to_numeric(source[latitude], errors='coerce')
            frame[LONGITUDE] = pd.to_numeric(source[longitude], errors='coerce')
            for field in BOUNDARY_FIELDS:
                frame[AREA_COLUMN.format(field)] = boundary_names(field, frame[LATITUDE], frame[LONGITUDE])
            break
    level_2 = resolve(source.columns, 'G_Level_2')
    # Drive City tests are places; other tests (Connecting Roads) follow a route.
    frame[PLACE] = (source[level_2].astype('string').str.casefold() == 'city') if level_2 is not None else True


@lru_cache(maxsize=4)
def _boundary_index(field: str):
    """Polygons, names and spatial index of a bundled boundary layer (None when missing)."""
    from shapely import STRtree
    from shapely.geometry import shape

    file_name, name_field = BOUNDARY_FIELDS[field]
    try:
        document = json.loads((BOUNDARY_DIRECTORY / file_name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    features = [feature for feature in document.get('features', []) if feature.get('geometry')]
    geometries = [shape(feature['geometry']) for feature in features]
    names = [str(feature['properties'][name_field]) for feature in features]
    return geometries, names, STRtree(geometries)


def boundary_names(field: str, latitude: pd.Series, longitude: pd.Series) -> pd.Series:
    """Name of the boundary polygon containing each coordinate (missing outside every polygon)."""
    import numpy as np
    from shapely import points

    names = pd.Series(pd.NA, index=latitude.index, dtype='string')
    index = _boundary_index(field)
    located = latitude.notna() & longitude.notna() & ~((latitude == 0) & (longitude == 0))
    if index is None or not located.any():
        return names
    _geometries, polygon_names, tree = index
    rows, polygons = tree.query(points(longitude[located].to_numpy(), latitude[located].to_numpy()),
                                predicate='intersects')
    if len(rows):
        first = pd.Series(polygons, index=rows).groupby(level=0).first()
        positions = np.flatnonzero(located.to_numpy())[first.index.to_numpy()]
        names.iloc[positions] = [polygon_names[polygon] for polygon in first.to_numpy()]
    return names


def _rings(geometry, precision: int) -> list[list[list[float]]]:
    polygons = geometry.geoms if geometry.geom_type == 'MultiPolygon' else [geometry]
    return [[[round(x, precision), round(y, precision)] for x, y in polygon.exterior.coords]
            for polygon in polygons if not polygon.is_empty]


def bundled_boundaries(field: str, precision: int = 3) -> dict[str, list[list[list[float]]]]:
    """Outer rings ([longitude, latitude]) of each polygon of a bundled boundary layer."""
    index = _boundary_index(field) if field in BOUNDARY_FIELDS else None
    if index is None:
        return {}
    geometries, names, _tree = index
    boundaries: dict[str, list] = {}
    for name, geometry in zip(names, geometries):
        boundaries.setdefault(name, []).extend(_rings(geometry, precision))
    return boundaries


def mapping_boundaries(path: Path, field: str, tolerance: float = .002) -> dict[str, list[list[list[float]]]]:
    """Simplified outer rings of a workspace Clusters or Region Mapping dataset, by its attribute."""
    from src.modules.geospatial import _cluster_field, _read_region_mapping, _region_field

    label = 'Clusters' if field == 'Cluster' else 'Region Mapping'
    polygons = _read_region_mapping(path, label)
    if polygons.empty or polygons.crs is None:
        return {}
    name_field = _cluster_field(polygons.columns) if field == 'Cluster' else _region_field(polygons.columns)
    polygons = polygons.to_crs('EPSG:4326')
    boundaries: dict[str, list] = {}
    for name, geometry in zip(polygons[name_field].astype(str).str.strip(), polygons.geometry):
        if geometry is None or geometry.is_empty or geometry.geom_type not in {'Polygon', 'MultiPolygon'}:
            continue
        boundaries.setdefault(name, []).extend(_rings(geometry.simplify(tolerance, preserve_topology=True), 4))
    return boundaries


def map_boundaries(result: dict[str, Any] | None, field: str) -> dict[str, list[list[list[float]]]]:
    """Polygons of a points-lost field: the bundled layer or the workspace mapping saved with the job."""
    if field in BOUNDARY_FIELDS:
        return bundled_boundaries(field)
    document = result.get('points_loss') if isinstance(result, dict) else None
    saved = (document or {}).get('boundaries') if isinstance(document, dict) else None
    return dict((saved or {}).get(field) or {})


def _numeric(frame: pd.DataFrame, field: str) -> pd.Series:
    return pd.to_numeric(frame[field], errors='coerce')


def test_weights(frame: pd.DataFrame, metric: dict[str, Any], thresholds: dict[str, Any],
                 condition, apply_filters) -> pd.Series:
    """Weight of each test in the points a KPI loses; tests outside the KPI weigh nothing."""
    selected = apply_filters(frame, metric['calculation']['filters'])
    formula = metric['calculation']['formula']
    higher_is_better = metric['direction'] == 'higher_is_better'
    weights = pd.Series(0.0, index=frame.index)
    if selected.empty:
        return weights
    if formula == '100 * SUM(totalpacketlost) / SUM(Packets_Sent)':
        lost = sum((_numeric(selected, field).fillna(0) if field in selected else 0)
                   for field in ('Packets_Lost', 'Packets_Discarded', 'Packets_Corrupted', 'Packets_Not_Sent'))
        weights.loc[selected.index] = pd.Series(lost, index=selected.index).clip(lower=0)
        return weights
    ratio = _RATIO.fullmatch(formula)
    if ratio:
        _multiplier, _operation, expression, _denominator_operation, denominator = ratio.groups()
        counted = selected[selected[denominator].notna()] if denominator in selected else selected
        expression = expression.strip()
        try:
            matches = condition(counted, expression).astype(bool)
        except (KeyError, ValueError):
            weights.loc[counted.index] = 1.0
            return weights
        # Higher-is-better ratios lose points on the tests that miss the condition, and
        # lower-is-better ratios (POLQA < 1.6, setup time > 10 s) on the tests that meet it.
        bad = ~matches if higher_is_better else matches
        weights.loc[counted.index] = bad.astype(float)
        return weights
    aggregate = _AGGREGATE.fullmatch(formula)
    if aggregate and aggregate.group(2) in selected:
        values = _numeric(selected, aggregate.group(2))
        target = thresholds.get('high')
        if isinstance(target, (int, float)):
            shortfall = (target - values) if higher_is_better else (values - target)
            weights.loc[selected.index] = shortfall.clip(lower=0).fillna(0)
            return weights
    weights.loc[selected.index] = 1.0
    return weights


def area_shares(frame: pd.DataFrame, weights: pd.Series) -> dict[str, dict[str, float]]:
    """Share of the KPI's weight in each area, for every area field of the rows."""
    total = float(weights.sum())
    if total <= 0:
        return {}
    shares: dict[str, dict[str, float]] = {}
    for field in MAP_FIELDS:
        column = AREA_COLUMN.format(field)
        if column not in frame:
            continue
        by_area = weights.groupby(frame[column].fillna(NOT_SPECIFIED).replace('', NOT_SPECIFIED)).sum()
        shares[field] = {str(area): round(float(value) / total, 6) for area, value in by_area.items() if value > 0}
    return shares


class AreaGeometry:
    """Centroids, route points and a background sample of the test locations."""

    def __init__(self) -> None:
        self.areas: dict[str, dict[str, dict[str, Any]]] = {field: {} for field in AREA_FIELDS}
        self.background: list[list[float]] = []
        self._seen = 0

    def add(self, frame: pd.DataFrame) -> None:
        if LATITUDE not in frame or LONGITUDE not in frame:
            return
        located = frame[frame[LATITUDE].between(-90, 90) & frame[LONGITUDE].between(-180, 180)
                        & ~((frame[LATITUDE] == 0) & (frame[LONGITUDE] == 0))]
        if located.empty:
            return
        step = max(1, len(located) // 1500)
        for latitude, longitude in located[[LATITUDE, LONGITUDE]].iloc[::step].itertuples(index=False):
            self._seen += 1
            if len(self.background) < MAX_BACKGROUND_POINTS:
                self.background.append([round(float(latitude), 4), round(float(longitude), 4)])
        for field in AREA_FIELDS:
            column = AREA_COLUMN.format(field)
            if column not in located:
                continue
            for area, group in located.groupby(located[column].fillna(NOT_SPECIFIED)):
                entry = self.areas[field].setdefault(str(area), {
                    'latitude_sum': 0.0, 'longitude_sum': 0.0, 'tests': 0, 'places': 0, 'points': [], 'itl3': {}})
                # The ITL3 areas of the tests of each City or route, to show it alone on the ITL3 map.
                itl3 = AREA_COLUMN.format('ITL3')
                if field == 'City' and itl3 in group:
                    for name, count in group[itl3].dropna().value_counts().items():
                        entry['itl3'][str(name)] = entry['itl3'].get(str(name), 0) + int(count)
                entry['latitude_sum'] += float(group[LATITUDE].sum())
                entry['longitude_sum'] += float(group[LONGITUDE].sum())
                entry['tests'] += len(group)
                entry['places'] += int(group[PLACE].fillna(True).astype(bool).sum()) if PLACE in group else len(group)
                room = MAX_AREA_POINTS - len(entry['points'])
                if room > 0:
                    sample = group[[LATITUDE, LONGITUDE]].iloc[::max(1, len(group) // room)].head(room)
                    entry['points'].extend([round(float(lat), 4), round(float(lon), 4)]
                                           for lat, lon in sample.itertuples(index=False))

    def document(self) -> dict[str, Any]:
        areas = {}
        for field, entries in self.areas.items():
            if not entries:
                continue
            areas[field] = {
                area: {
                    'latitude': round(entry['latitude_sum'] / entry['tests'], 5),
                    'longitude': round(entry['longitude_sum'] / entry['tests'], 5),
                    'tests': entry['tests'],
                    # A City value of Connecting Roads tests is a route between cities.
                    'kind': 'place' if entry['places'] * 2 >= entry['tests'] else 'route',
                    'points': entry['points'] if entry['places'] * 2 < entry['tests'] else [],
                    **({'itl3': entry['itl3']} if entry['itl3'] else {}),
                }
                for area, entry in entries.items()
            }
        return {'areas': areas, 'background': self.background}


def row_area_links(areas: list[dict[str, Any]], field: str = 'ITL3') -> dict[str, list[str]]:
    """The boundary areas of each City or route, the one with most of its tests first.

    A City or route belongs to the areas holding its tests (``itl3``, at least 2% of them);
    results calculated before that was kept use the areas of its location or route points.
    """
    from shapely import points as shapely_points

    index = _boundary_index(field) if field in BOUNDARY_FIELDS else None
    links: dict[str, list[str]] = {}
    for area in areas:
        if area.get('name') == NOT_SPECIFIED:
            continue
        counts = dict(area.get('itl3') or {}) if field == 'ITL3' else {}
        if not counts and index is not None:
            spots = ([(lon, lat) for lat, lon in area['route']] if area.get('kind') == 'route' and area.get('route')
                     else [(area['longitude'], area['latitude'])] if area.get('latitude') is not None else [])
            if spots:
                _geometries, names, tree = index
                _rows, polygons = tree.query(shapely_points(spots), predicate='intersects')
                for polygon in polygons:
                    counts[names[polygon]] = counts.get(names[polygon], 0) + 1
        total = sum(counts.values())
        if total:
            ordered = sorted(counts, key=lambda name: -counts[name])
            links[area['name']] = [name for name in ordered if counts[name] / total >= .02] or ordered[:1]
    return links


def row_area_values(areas: list[dict[str, Any]], field: str = 'ITL3') -> dict[str, float]:
    """Each boundary area with the points of the City or route that loses most in it."""
    points = {area['name']: float(area['points']) for area in areas}
    values: dict[str, float] = {}
    for row, names in row_area_links(areas, field).items():
        for name in names:
            values[name] = max(values.get(name, 0.0), points[row])
    return values


def points_loss_maps(result: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
    """Points lost per area for each scoring series, all environments together and in each one.

    Each KPI loses its maximum points minus the points scored; the loss is spread over
    the areas by their shares. ``keys`` are the series fields other than the environment.
    The maps of all environments (``environment`` None) give each area the points it loses
    in each environment, most first (``environments``).
    """
    document = result.get('points_loss') if isinstance(result, dict) else None
    if not isinstance(document, dict) or not document.get('shares'):
        return []
    rows = {}
    for row in result.get('scoring') or []:
        rows[(tuple(row.get(key) for key in keys), row.get('environment'), row.get('kpi_code'))] = row
    series: dict[tuple, dict[str, dict[str, float]]] = {}
    by_environment: dict[tuple, dict[str, dict[str, dict[str, float]]]] = {}
    for entry in document['shares']:
        identity = tuple(entry.get(key) for key in keys)
        row = rows.get((identity, entry.get('environment'), entry.get('kpi_code')))
        if row is None:
            continue
        maximum = float(row.get('max_points') or 0)
        points = row.get('weighted_points')
        if maximum <= 0 or points is None:
            continue
        lost = max(0.0, maximum - float(points))
        if lost <= 0:
            continue
        environment = str(entry.get('environment') or '')
        for key in ((identity, None), (identity, environment)):
            target = series.setdefault(key, {})
            for field, shares in (entry.get('areas') or {}).items():
                areas = target.setdefault(field, {})
                for area, share in shares.items():
                    areas[area] = areas.get(area, 0.0) + lost * float(share)
                    if key[1] is None:
                        split = by_environment.setdefault(identity, {}).setdefault(field, {}).setdefault(area, {})
                        split[environment] = split.get(environment, 0.0) + lost * float(share)
    maps = []
    for (identity, environment), fields in series.items():
        context = dict(zip(keys, identity))
        for field, areas in fields.items():
            if not areas:
                continue
            item = {'context': context, 'field': field, 'areas': areas, 'total': sum(areas.values()),
                    'environment': environment}
            if environment is None:
                split = by_environment.get(identity, {}).get(field, {})
                item['environments'] = {area: [name for name, _points in sorted(
                    split.get(area, {}).items(), key=lambda pair: -pair[1]) if name] for area in areas}
            maps.append(item)
    return maps
