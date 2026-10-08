"""Map Areas of a workspace: the administrative areas the Points Lost Map colours, per country.

The tests of the CDRs are placed in the administrative area of their country that contains them:
the bundled ITL3 areas for the United Kingdom, and for any other country a layer stored with the
workspace (for example municipalities in Spain or counties in the USA), downloaded from
geoBoundaries (https://www.geoboundaries.org) or imported from a GeoJSON or a zipped Shapefile.
The countries of the tests come from the bundled Natural Earth country polygons (public domain).
Layers travel with the Mappings & Reference Data in Import / Export, transfers and backups.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
import zlib
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

import pandas as pd

from src.config import PROJECT_ROOT

TABLE = 'map_area_layers'
TABLE_TITLE = 'Map Area Layers'
DOCUMENT_FORMAT = 'drivetest-analyzer-map-area-layers'
WORLD_FILE = PROJECT_ROOT / 'assets' / 'geo' / 'world-countries-50m.geojson'
ITL3_FILE = PROJECT_ROOT / 'assets' / 'geo' / 'uk-itl3-2025.geojson'
UK = 'GBR'
UK_LABEL = 'ITL3 area'
GEOBOUNDARIES_API = 'https://www.geoboundaries.org/api/current/gbOpen/{code}/ALL/'
GEOBOUNDARIES_ATTRIBUTION = 'geoBoundaries (William & Mary geoLab), www.geoboundaries.org'
# Layers finer than this would be too heavy to store and draw.
MAX_UNITS = 12000
# Tests a little off the coast still belong to the nearest country.
COAST_DEGREES = .3
SAMPLE_ROWS = 4000
NAME_FIELDS = ('shapeName', 'name', 'NAME', 'Name', 'NAME_EN', 'NAMEUNIT', 'NOMBRE', 'nombre', 'NAME_2', 'NAME_3', 'label')
_NON_COMMERCIAL = re.compile(r'non[- ]?commercial|\bnc\b|by-nc', re.IGNORECASE)
COORDINATE_COLUMNS = (
    ('Test_Start_Latitude', 'Test_Start_Longitude'),
    ('Call_Start_Latitude_A', 'Call_Start_Longitude_A'),
    ('Recording_Latitude', 'Recording_Longitude'),
    ('Playing_Latitude', 'Playing_Longitude'),
)
_index_cache: dict[str, tuple[str, Any]] = {}
_index_lock = Lock()


def ensure_table(repository: Any) -> None:
    with repository.connection() as connection:
        connection.execute(
            f'CREATE TABLE IF NOT EXISTS {TABLE} ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, country_code TEXT NOT NULL UNIQUE, country_name TEXT NOT NULL, '
            'level TEXT NOT NULL, level_label TEXT NOT NULL, origin TEXT NOT NULL, source TEXT NOT NULL, '
            'license TEXT NOT NULL, attribution TEXT NOT NULL, unit_count INTEGER NOT NULL, '
            'boundaries BLOB NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL)'
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- countries ------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _world():
    """Polygons, ISO 3166 alpha-3 codes, names and spatial index of the bundled countries."""
    from shapely import STRtree
    from shapely.geometry import shape

    try:
        features = json.loads(WORLD_FILE.read_text(encoding='utf-8')).get('features', [])
    except (OSError, ValueError):
        return None
    features = [feature for feature in features if feature.get('geometry') and feature['properties'].get('code')]
    geometries = [shape(feature['geometry']) for feature in features]
    codes = [str(feature['properties']['code']) for feature in features]
    names = [str(feature['properties']['name']) for feature in features]
    return geometries, codes, names, STRtree(geometries)


def country_name(code: str) -> str:
    world = _world()
    if world is None:
        return code
    _geometries, codes, names, _tree = world
    return names[codes.index(code)] if code in codes else code


def country_codes(latitude: pd.Series, longitude: pd.Series) -> pd.Series:
    """ISO alpha-3 code of the country of each coordinate (missing far from every country)."""
    import numpy as np
    from shapely import points

    codes = pd.Series(pd.NA, index=latitude.index, dtype='string')
    world = _world()
    located = latitude.notna() & longitude.notna() & ~((latitude == 0) & (longitude == 0))
    if world is None or not located.any():
        return codes
    _geometries, country_list, _names, tree = world
    spots = points(longitude[located].to_numpy(), latitude[located].to_numpy())
    nearest, distances = tree.query_nearest(spots, return_distance=True, all_matches=False)
    rows, polygons = nearest
    positions = np.flatnonzero(located.to_numpy())[rows]
    close = distances <= COAST_DEGREES
    codes.iloc[positions[close]] = [country_list[polygon] for polygon in polygons[close]]
    return codes


def country_outline(code: str, precision: int = 3) -> list[list[list[float]]]:
    """Outer rings of a country, drawn in grey under its areas."""
    world = _world()
    if world is None:
        return []
    geometries, codes, _names, _tree = world
    return [ring for geometry, item in zip(geometries, codes) if item == code for ring in _rings(geometry, precision)]


def detect_countries(repository: Any) -> list[dict[str, Any]]:
    """The countries of the tests of the ready CDRs, from a sample of each, most tests first."""
    from src.modules.column_names import resolve_column_name

    counts: dict[str, int] = {}
    total = 0
    for row in repository.list_datasets():
        if str(row['status'] or '') != 'ready' or str(row['dataset_kind'] or '') not in {'data', 'voice', 'speech'}:
            continue
        dataset_id = int(row['id'])
        try:
            columns = repository.list_dataset_row_columns(dataset_id)
        except Exception:  # noqa: BLE001 - a CDR without its rows table is skipped.
            continue
        pair = next(((latitude, longitude) for names in COORDINATE_COLUMNS
                     if (latitude := resolve_column_name(columns, names[0])) and (longitude := resolve_column_name(columns, names[1]))),
                    None)
        if pair is None:
            continue
        table = repository.dataset_rows_table_name(dataset_id)
        with repository.connection() as connection:
            rows = connection.execute(
                f'SELECT "{pair[0]}", "{pair[1]}" FROM "{table}" WHERE rowid % '
                f'(SELECT MAX(1, COUNT(*) / {SAMPLE_ROWS}) FROM "{table}") = 0 LIMIT {SAMPLE_ROWS}'
            ).fetchall()
        frame = pd.DataFrame([tuple(item) for item in rows], columns=['latitude', 'longitude'])
        if frame.empty:
            continue
        found = country_codes(pd.to_numeric(frame['latitude'], errors='coerce'),
                              pd.to_numeric(frame['longitude'], errors='coerce')).dropna()
        total += len(found)
        for code, count in found.value_counts().items():
            counts[str(code)] = counts.get(str(code), 0) + int(count)
    layers = {layer['country_code']: layer for layer in list_layers(repository)}
    return [{'code': code, 'name': country_name(code), 'tests': count, 'share': count / total if total else 0,
             'bundled': code == UK, 'layer': layers.get(code)}
            for code, count in sorted(counts.items(), key=lambda item: -item[1])]


# -- layers ---------------------------------------------------------------------------------------
def _rings(geometry, precision: int) -> list[list[list[float]]]:
    polygons = geometry.geoms if geometry.geom_type == 'MultiPolygon' else [geometry]
    return [[[round(x, precision), round(y, precision)] for x, y in polygon.exterior.coords]
            for polygon in polygons if not polygon.is_empty]


def _pack(boundaries: dict[str, list]) -> bytes:
    return zlib.compress(json.dumps(boundaries, separators=(',', ':'), ensure_ascii=False).encode('utf-8'), 6)


def _unpack(blob: bytes | None) -> dict[str, list]:
    return json.loads(zlib.decompress(blob).decode('utf-8')) if blob else {}


def list_layers(repository: Any) -> list[dict[str, Any]]:
    ensure_table(repository)
    with repository.connection() as connection:
        rows = connection.execute(
            f'SELECT id, country_code, country_name, level, level_label, origin, source, license, attribution, '
            f'unit_count, updated_by, updated_at FROM {TABLE} ORDER BY country_name').fetchall()
    return [dict(row) for row in rows]


def layer_boundaries(repository: Any, country_code: str) -> dict[str, list]:
    ensure_table(repository)
    with repository.connection() as connection:
        row = connection.execute(f'SELECT boundaries FROM {TABLE} WHERE country_code = ?', (country_code,)).fetchone()
    return _unpack(row['boundaries']) if row else {}


def delete_layer(repository: Any, layer_id: int) -> bool:
    ensure_table(repository)
    with repository.connection() as connection:
        deleted = connection.execute(f'DELETE FROM {TABLE} WHERE id = ?', (int(layer_id),)).rowcount
    _forget(repository)
    return bool(deleted)


def save_layer(repository: Any, *, country_code: str, level: str, level_label: str, origin: str, source: str,
               license_text: str, attribution: str, boundaries: dict[str, list], username: str) -> dict[str, Any]:
    """Save (or replace) the layer of a country."""
    code = str(country_code or '').strip().upper()
    if not re.fullmatch(r'[A-Z]{3}', code):
        raise ValueError('Choose the country of the map areas (ISO 3166 alpha-3 code, for example ESP).')
    if code == UK:
        raise ValueError('The United Kingdom uses the bundled ITL3 areas.')
    if not boundaries:
        raise ValueError('The map areas have no polygons.')
    ensure_table(repository)
    values = (code, country_name(code), level, level_label, origin, source, license_text, attribution,
              len(boundaries), _pack(boundaries), username, _now())
    with repository.connection() as connection:
        connection.execute(
            f'INSERT INTO {TABLE} (country_code, country_name, level, level_label, origin, source, license, attribution, '
            'unit_count, boundaries, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(country_code) DO UPDATE SET country_name = excluded.country_name, level = excluded.level, '
            'level_label = excluded.level_label, origin = excluded.origin, source = excluded.source, '
            'license = excluded.license, attribution = excluded.attribution, unit_count = excluded.unit_count, '
            'boundaries = excluded.boundaries, updated_by = excluded.updated_by, updated_at = excluded.updated_at',
            values,
        )
    _forget(repository)
    return next(layer for layer in list_layers(repository) if layer['country_code'] == code)


def _label(text: Any, level: str) -> str:
    """A readable singular label, such as municipality or county."""
    value = str(text or '').strip()
    if not value or value.casefold() in {'unknown', 'nan', 'gbopen'} or value.casefold().startswith('the '):
        return f'{level} area'
    value = value.lower()
    for plural, singular in (('ies', 'y'), ('s', '')):
        if value.endswith(plural) and len(value) > 4:
            return value[:-len(plural)] + singular
    return value


def _features_boundaries(features: Iterable[tuple[str, Any]], tolerance: float) -> dict[str, list]:
    """Simplified rings of each named polygon; repeated names get a number."""
    boundaries: dict[str, list] = {}
    seen: dict[str, int] = {}
    named = [(str(name).strip(), geometry) for name, geometry in features
             if str(name or '').strip() and geometry is not None and not geometry.is_empty
             and geometry.geom_type in {'Polygon', 'MultiPolygon'}]
    totals: dict[str, int] = {}
    for name, _geometry in named:
        totals[name] = totals.get(name, 0) + 1
    for name, geometry in named:
        if totals[name] > 1:
            seen[name] = seen.get(name, 0) + 1
            name = f'{name} ({seen[name]})'
        boundaries[name] = _rings(geometry.simplify(tolerance, preserve_topology=True), 4)
    return boundaries


def _tolerance(count: int) -> float:
    """Finer layers keep more detail: about 100 m for municipalities, 500 m for large areas."""
    return .001 if count > 1000 else .003 if count > 100 else .005


def _fetch(url: str, timeout: int = 120) -> bytes:
    import certifi

    request = urllib.request.Request(url, headers={'User-Agent': 'DriveTestAnalyzer'})
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 - fixed https sources
        return response.read()


def geoboundaries_levels(country_code: str) -> list[dict[str, Any]]:
    """The administrative levels geoBoundaries offers for a country, the suggested one marked."""
    code = str(country_code or '').strip().upper()
    if not re.fullmatch(r'[A-Z]{3}', code):
        raise ValueError('Unknown country code.')
    try:
        items = json.loads(_fetch(GEOBOUNDARIES_API.format(code=code), timeout=30))
    except Exception as exc:  # noqa: BLE001 - network errors are explained to the user
        raise ValueError(f'geoBoundaries could not be reached ({exc}). Import the areas from a file instead.') from exc
    levels = []
    for item in items if isinstance(items, list) else [items]:
        level = str(item.get('boundaryType') or '')
        if level in {'', 'ADM0'}:
            continue
        count = int(float(item.get('admUnitCount') or 0))
        license_text = str(item.get('boundaryLicense') or '').strip() or 'Unknown'
        levels.append({
            'level': level, 'label': _label(item.get('boundaryCanonical'), level), 'count': count,
            'mean_area_km2': round(float(item.get('meanAreaSqKM') or 0), 1),
            'license': license_text, 'source': str(item.get('boundarySource') or '').strip(),
            'year': str(item.get('boundaryYearRepresented') or ''),
            'commercial': not _NON_COMMERCIAL.search(license_text),
            'url': str(item.get('simplifiedGeometryGeoJSON') or item.get('gjDownloadURL') or ''),
            'too_large': count > MAX_UNITS,
        })
    levels.sort(key=lambda item: item['level'])
    # The finest level that is light enough and allows commercial use.
    usable = [item for item in levels if not item['too_large'] and item['commercial'] and item['url']]
    if usable:
        usable[-1]['suggested'] = True
    return levels


def download_geoboundaries(repository: Any, country_code: str, level: str, username: str) -> dict[str, Any]:
    from shapely.geometry import shape

    choice = next((item for item in geoboundaries_levels(country_code) if item['level'] == level), None)
    if choice is None or not choice['url']:
        raise ValueError(f'geoBoundaries has no {level} areas for this country.')
    if choice['too_large']:
        raise ValueError(f"The {choice['label']} level has {choice['count']} areas; choose a coarser level.")
    try:
        document = json.loads(_fetch(choice['url'], timeout=300))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f'The map areas could not be downloaded ({exc}).') from exc
    features = [(feature.get('properties', {}).get('shapeName'), shape(feature['geometry']))
                for feature in document.get('features', []) if feature.get('geometry')]
    boundaries = _features_boundaries(features, _tolerance(len(features)))
    return save_layer(
        repository, country_code=country_code, level=level, level_label=choice['label'], origin='geoBoundaries',
        source=choice['source'] or 'geoBoundaries', license_text=choice['license'],
        attribution=f"{choice['source'] or 'National source'} via {GEOBOUNDARIES_ATTRIBUTION}",
        boundaries=boundaries, username=username,
    )


def import_layer(repository: Any, filename: str, content: bytes, *, country_code: str, level_label: str,
                 name_field: str, username: str) -> dict[str, Any]:
    """A layer from a GeoJSON or a ZIP holding one Shapefile, named by one of its attributes."""
    import tempfile

    from src.modules.geospatial import _read_region_mapping

    suffix = Path(filename or '').suffix.casefold()
    if suffix not in {'.geojson', '.json', '.zip'}:
        raise ValueError('Import a GeoJSON, JSON or a ZIP holding a Shapefile.')
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f'areas{suffix}'
        path.write_bytes(content)
        frame = _read_region_mapping(path, 'Map Areas')
        if frame.empty:
            raise ValueError('The file has no polygons.')
        if frame.crs is not None:
            frame = frame.to_crs('EPSG:4326')
        field = (name_field or '').strip() or next((name for name in NAME_FIELDS if name in frame.columns), '')
        if field not in frame.columns:
            raise ValueError(f"Name the attribute that holds the area names (columns: {', '.join(map(str, frame.columns))}).")
        if len(frame) > MAX_UNITS:
            raise ValueError(f'The file has {len(frame)} areas; use a coarser level (up to {MAX_UNITS}).')
        boundaries = _features_boundaries(zip(frame[field].astype(str), frame.geometry), _tolerance(len(frame)))
    return save_layer(
        repository, country_code=country_code, level='Imported', level_label=(level_label or 'area').strip().lower(),
        origin='Imported', source=Path(filename).name, license_text='Provided by the workspace', attribution=Path(filename).name,
        boundaries=boundaries, username=username,
    )


# -- placing the tests -----------------------------------------------------------------------------
def _forget(repository: Any) -> None:
    with _index_lock:
        _index_cache.pop(str(getattr(repository, 'db_path', '')), None)


@lru_cache(maxsize=1)
def _uk_areas() -> list[tuple[str, Any]]:
    from shapely.geometry import shape

    try:
        features = json.loads(ITL3_FILE.read_text(encoding='utf-8')).get('features', [])
    except (OSError, ValueError):
        return []
    return [(str(feature['properties']['ITL325NM']), shape(feature['geometry']))
            for feature in features if feature.get('geometry')]


class AreaIndex:
    """The areas of every country of a workspace, to name the area of each test."""

    def __init__(self, layers: list[tuple[str, str, list[tuple[str, Any]]]]) -> None:
        from shapely import STRtree

        # (country code, area label, [(name, geometry)]); the UK uses the bundled ITL3 areas.
        self.layers = [(UK, UK_LABEL, _uk_areas()), *layers]
        self.names: list[str] = []
        self.countries: list[str] = []
        geometries = []
        for code, _label_text, areas in self.layers:
            for name, geometry in areas:
                self.names.append(name)
                self.countries.append(code)
                geometries.append(geometry)
        self.labels = {code: label for code, label, _areas in self.layers}
        self.tree = STRtree(geometries) if geometries else None
        self.geometries = geometries

    def names_of(self, latitude: pd.Series, longitude: pd.Series) -> pd.Series:
        """Name of the area containing each coordinate (missing outside every area)."""
        import numpy as np
        from shapely import points

        names = pd.Series(pd.NA, index=latitude.index, dtype='string')
        located = latitude.notna() & longitude.notna() & ~((latitude == 0) & (longitude == 0))
        if self.tree is None or not located.any():
            return names
        rows, polygons = self.tree.query(points(longitude[located].to_numpy(), latitude[located].to_numpy()),
                                         predicate='intersects')
        if len(rows):
            first = pd.Series(polygons, index=rows).groupby(level=0).first()
            positions = np.flatnonzero(located.to_numpy())[first.index.to_numpy()]
            names.iloc[positions] = [self.names[polygon] for polygon in first.to_numpy()]
        return names

    def document(self, used: Iterable[str], unplaced_countries: Iterable[str]) -> dict[str, Any]:
        """The polygons of the used areas of each country (the UK's are bundled) and the country outlines."""
        used = set(used)
        boundaries: dict[str, list] = {}
        countries = []
        for code, label, areas in self.layers:
            names = [name for name, _geometry in areas if name in used]
            if not names:
                continue
            countries.append({'code': code, 'name': country_name(code), 'label': label})
            if code != UK:
                for name, geometry in areas:
                    if name in used:
                        boundaries[name] = _rings(geometry, 4)
        background = [ring for item in countries if item['code'] != UK for ring in country_outline(item['code'])]
        return {'countries': countries, 'boundaries': boundaries, 'background': background,
                'unmapped_countries': [{'code': code, 'name': country_name(code)} for code in unplaced_countries]}


def area_index(repository: Any | None) -> AreaIndex:
    """The workspace's areas (cached until a layer changes); without a workspace, the UK's alone."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    if repository is None:
        return AreaIndex([])
    layers = list_layers(repository)
    signature = json.dumps([(layer['country_code'], layer['updated_at']) for layer in layers])
    key = str(getattr(repository, 'db_path', ''))
    with _index_lock:
        cached = _index_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
    built = []
    for layer in layers:
        areas = []
        for name, rings in layer_boundaries(repository, layer['country_code']).items():
            polygons = [Polygon(ring) for ring in rings if len(ring) > 3]
            if polygons:
                areas.append((name, polygons[0] if len(polygons) == 1 else unary_union(polygons)))
        built.append((layer['country_code'], layer['level_label'], areas))
    index = AreaIndex(built)
    with _index_lock:
        _index_cache[key] = (signature, index)
    return index


# -- transfers -------------------------------------------------------------------------------------
def layers_document(repository: Any) -> dict[str, Any]:
    """Every layer with its polygons, for Import / Export, transfers and backups."""
    return {'format': DOCUMENT_FORMAT, 'version': 1, 'layers': [
        {**{key: value for key, value in layer.items() if key not in {'id', 'country_name'}},
         'boundaries': layer_boundaries(repository, layer['country_code'])}
        for layer in list_layers(repository)]}


def import_layers_document(repository: Any, document: Any, username: str, *, replace: bool = True) -> int:
    if not isinstance(document, dict) or document.get('format') != DOCUMENT_FORMAT:
        raise ValueError('The file is not a DriveTest Analyzer Map Areas export.')
    if replace:
        ensure_table(repository)
        with repository.connection() as connection:
            connection.execute(f'DELETE FROM {TABLE}')
        _forget(repository)
    imported = 0
    for layer in document.get('layers') or []:
        if not isinstance(layer, dict):
            continue
        save_layer(repository, country_code=layer.get('country_code'), level=str(layer.get('level') or ''),
                   level_label=str(layer.get('level_label') or 'area'), origin=str(layer.get('origin') or 'Imported'),
                   source=str(layer.get('source') or ''), license_text=str(layer.get('license') or ''),
                   attribution=str(layer.get('attribution') or ''), boundaries=layer.get('boundaries') or {},
                   username=str(layer.get('updated_by') or username))
        imported += 1
    return imported
