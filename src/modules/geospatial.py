"""Optional spatial Region enrichment for NetCheck CDR datasets."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable
import zipfile

import pandas as pd


REGION_FIELD_CANDIDATES = ('Region', 'WP', 'region', 'wp', 'Name', 'name')
COORDINATE_COLUMNS = {
    'data': (('Test_Start_Longitude', 'Test_Start_Latitude'),),
    'voice': (('Call_Start_Longitude_A', 'Call_Start_Latitude_A'),),
    'speech': (('Recording_Longitude', 'Recording_Latitude'),),
}


def _geopandas():
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - exercised by packaged installs.
        raise ValueError('Geospatial Region mapping requires the optional GeoPandas dependencies.') from exc
    return gpd


def _column(columns: Iterable[object], candidate: str) -> str | None:
    normalized = candidate.casefold().replace(' ', '_')
    for column in columns:
        if str(column).casefold().replace(' ', '_') == normalized:
            return str(column)
    return None


def _region_field(columns: Iterable[object]) -> str:
    for candidate in REGION_FIELD_CANDIDATES:
        found = _column(columns, candidate)
        if found:
            return found
    raise ValueError('The Region mapping must contain a Region or WP attribute column.')


def _read_region_mapping(path: Path):
    """Read GeoJSON directly or the first real shapefile stored in a ZIP."""
    gpd = _geopandas()
    if path.suffix.casefold() != '.zip':
        return gpd.read_file(path)
    try:
        with zipfile.ZipFile(path) as archive:
            shapefiles = sorted(
                name for name in archive.namelist()
                if name.casefold().endswith('.shp') and not name.startswith('__MACOSX/')
            )
    except zipfile.BadZipFile as exc:
        raise ValueError('The Region Mapping ZIP is invalid.') from exc
    if not shapefiles:
        raise ValueError('The Region Mapping ZIP must contain a .shp file.')
    if len(shapefiles) > 1:
        raise ValueError('The Region Mapping ZIP must contain exactly one .shp file.')
    return gpd.read_file(f'zip://{path}!{shapefiles[0]}')


def validate_region_mapping(path: Path) -> str:
    """Validate a GeoJSON or zipped shapefile and return its Region attribute."""
    regions = _read_region_mapping(path)
    if regions.empty:
        raise ValueError('The Region mapping has no geometries.')
    if regions.crs is None:
        raise ValueError('The Region mapping must declare a coordinate reference system.')
    if not regions.geometry.geom_type.isin({'Polygon', 'MultiPolygon'}).all():
        raise ValueError('The Region mapping must contain only polygon geometries.')
    field = _region_field(regions.columns)
    if regions[field].fillna('').astype(str).str.strip().eq('').any():
        raise ValueError(f'The Region mapping attribute {field} contains blank values.')
    return field


def assign_regions(dataset: pd.DataFrame, dataset_kind: str, mapping_path: Path) -> pd.DataFrame:
    """Fill blank Region values with the polygon attribute containing each CDR point."""
    coordinate_pairs = COORDINATE_COLUMNS.get(dataset_kind, ())
    longitude = latitude = None
    for longitude_name, latitude_name in coordinate_pairs:
        longitude = _column(dataset.columns, longitude_name)
        latitude = _column(dataset.columns, latitude_name)
        if longitude and latitude:
            break
    if not longitude or not latitude:
        raise ValueError(f'The {dataset_kind} CDR has no supported longitude/latitude columns for Region mapping.')

    gpd = _geopandas()
    regions = _read_region_mapping(mapping_path)
    field = _region_field(regions.columns)
    if regions.crs is None:
        raise ValueError('The Region mapping must declare a coordinate reference system.')
    result = dataset.copy()
    region_column = _column(result.columns, 'Region') or 'Region'
    if region_column not in result:
        result[region_column] = pd.NA
    blank = result[region_column].isna() | result[region_column].astype(str).str.strip().eq('')
    longitude_values = pd.to_numeric(result[longitude], errors='coerce')
    latitude_values = pd.to_numeric(result[latitude], errors='coerce')
    usable = blank & longitude_values.notna() & latitude_values.notna()
    if not usable.any():
        return result
    points = gpd.GeoDataFrame(
        result.loc[usable, []],
        geometry=gpd.points_from_xy(longitude_values[usable], latitude_values[usable]),
        crs='EPSG:4326',
    ).to_crs(regions.crs)
    matches = gpd.sjoin(points, regions[[field, 'geometry']], how='left', predicate='within')
    values = matches[field].groupby(level=0).first()
    result.loc[values.index, region_column] = values
    return result
