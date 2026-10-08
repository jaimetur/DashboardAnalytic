"""Optional spatial Region enrichment for NetCheck CDR datasets."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable
import zipfile

import pandas as pd


REGION_FIELD_CANDIDATES = ('Region', 'WP', 'region', 'wp', 'Name', 'name')
COORDINATE_COLUMNS = {
    'data': (('Test_Start_Longitude', 'Test_Start_Latitude'),),
    'voice': (('Call_Start_Longitude_A', 'Call_Start_Latitude_A'),),
    'speech': (('Recording_Longitude', 'Recording_Latitude'),),
}
# Where a sample ends, when the CDR records it: Vendor polygons compare its start and end like the
# first and last cells of the Network Inventory rule.
END_COORDINATE_COLUMNS = {
    'voice': (('Call_End_Longitude_A', 'Call_End_Latitude_A'),),
}
VENDOR_FIELD_CANDIDATES = ('Vendor', 'OP_Vendor', 'OP/ Vendor', 'Name')
OPERATOR_FIELD_CANDIDATES = ('Operator', 'MNO', 'Network')


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


def _read_region_mapping(path: Path, label: str = 'Region Mapping'):
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
        raise ValueError(f'The {label} ZIP is invalid.') from exc
    if not shapefiles:
        raise ValueError(f'The {label} ZIP must contain a .shp file.')
    if len(shapefiles) > 1:
        raise ValueError(f'The {label} ZIP must contain exactly one .shp file.')
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


def _cluster_field(columns: Iterable[object]) -> str:
    field = next((found for candidate in ('Cluster', 'Cluster_ID', 'Cluster_Name', 'ClusterName', 'Name')
                  if (found := _column(columns, candidate))), None)
    if not field:
        raise ValueError('The Clusters dataset must contain a Cluster, Cluster_ID, Cluster_Name or Name attribute.')
    return field


def validate_cluster_mapping(path: Path) -> str:
    """Validate cluster polygons using the same GeoJSON/zipped-shapefile reader as regions."""
    if path.suffix.casefold() not in {'.geojson', '.json', '.zip'}:
        raise ValueError('Clusters require GeoJSON, JSON or a ZIP containing a shapefile.')
    clusters = _read_region_mapping(path, 'Clusters')
    if clusters.empty:
        raise ValueError('The Clusters dataset has no geometries.')
    if clusters.crs is None:
        raise ValueError('The Clusters dataset must declare a coordinate reference system.')
    if not clusters.geometry.geom_type.isin({'Polygon', 'MultiPolygon'}).all():
        raise ValueError('The Clusters dataset must contain only polygon geometries.')
    if not clusters.geometry.is_valid.all() or clusters.geometry.is_empty.any():
        raise ValueError('The Clusters dataset contains invalid or empty polygons.')
    field = _cluster_field(clusters.columns)
    if clusters[field].fillna('').astype(str).str.strip().eq('').any():
        raise ValueError(f'The Clusters attribute {field} contains blank values.')
    return field


def _vendor_field(columns: Iterable[object]) -> str:
    field = next((found for candidate in VENDOR_FIELD_CANDIDATES if (found := _column(columns, candidate))), None)
    if not field:
        raise ValueError('The Vendor polygons must contain a Vendor, OP_Vendor or Name attribute.')
    return field


def _operator_field(columns: Iterable[object]) -> str | None:
    return next((found for candidate in OPERATOR_FIELD_CANDIDATES if (found := _column(columns, candidate))), None)


def validate_vendor_polygons(path: Path) -> tuple[str, str | None]:
    """Validate Vendor polygons and return their Vendor attribute and their Operator attribute, if any."""
    if path.suffix.casefold() not in {'.geojson', '.json', '.zip'}:
        raise ValueError('Vendor polygons require GeoJSON, JSON or a ZIP containing a shapefile.')
    polygons = _read_region_mapping(path, 'Vendor polygons')
    if polygons.empty:
        raise ValueError('The Vendor polygons have no geometries.')
    if polygons.crs is None:
        raise ValueError('The Vendor polygons must declare a coordinate reference system.')
    if not polygons.geometry.geom_type.isin({'Polygon', 'MultiPolygon'}).all():
        raise ValueError('The Vendor polygons must contain only polygon geometries.')
    field = _vendor_field(polygons.columns)
    if polygons[field].fillna('').astype(str).str.strip().eq('').any():
        raise ValueError(f'The Vendor polygons attribute {field} contains blank values.')
    return field, _operator_field(polygons.columns)


def vendor_polygon_operators(path: Path) -> list[str]:
    """The values of the Operator attribute of Vendor polygons (none without that attribute)."""
    polygons = _read_region_mapping(path, 'Vendor polygons')
    field = _operator_field(polygons.columns)
    if not field:
        return []
    return sorted({str(value).strip() for value in polygons[field].dropna() if str(value).strip()})


def _endpoint_columns(dataset: pd.DataFrame, pairs: Iterable[tuple[str, str]]) -> tuple[str, str] | None:
    for longitude_name, latitude_name in pairs:
        longitude, latitude = _column(dataset.columns, longitude_name), _column(dataset.columns, latitude_name)
        if longitude and latitude:
            return longitude, latitude
    return None


def polygon_vendor_endpoints(
    dataset: pd.DataFrame,
    dataset_kind: str,
    polygon_sets: Iterable[tuple[Path, str | None]],
    operators: Iterable[object],
    operator_key: Callable[[object], str],
) -> tuple[list[str | None], list[str | None], list[bool]]:
    """The Vendor polygon at the start and at the end of each CDR sample, in row order.

    ``polygon_sets`` lists each Vendor polygons file with the Operator it belongs to; without one (a
    Multi-operator file) each polygon belongs to the Operator of its Operator attribute. A sample only takes the
    polygons of its Operator (``operator_key`` gives the shared identity of two spellings); the third
    list tells which samples have polygons for their Operator. Without an end position the end is the start.
    """
    gpd = _geopandas()
    start_columns = _endpoint_columns(dataset, COORDINATE_COLUMNS.get(dataset_kind, ()))
    if not start_columns:
        raise ValueError(f'The {dataset_kind} CDR has no supported longitude/latitude columns for Vendor polygons.')
    frames = []
    for path, operator in polygon_sets:
        polygons = _read_region_mapping(Path(path), 'Vendor polygons')
        if polygons.crs is None:
            raise ValueError('The Vendor polygons must declare a coordinate reference system.')
        vendor_field, operator_field = _vendor_field(polygons.columns), _operator_field(polygons.columns)
        if not operator_field and not operator:
            raise ValueError(f'Choose the Operator of the Vendor polygons {Path(path).name}.')
        polygons = polygons.to_crs('EPSG:4326')
        frames.append(gpd.GeoDataFrame({
            'polygon_vendor': polygons[vendor_field].astype(str).str.strip(),
            'polygon_operator': (pd.Series(operator, index=polygons.index) if operator else polygons[operator_field]).map(operator_key),
        }, geometry=polygons.geometry, crs='EPSG:4326'))
    polygons = pd.concat(frames, ignore_index=True) if frames else gpd.GeoDataFrame(
        {'polygon_vendor': [], 'polygon_operator': []}, geometry=[], crs='EPSG:4326')
    polygons = gpd.GeoDataFrame(polygons, geometry='geometry', crs='EPSG:4326')
    frame = dataset.reset_index(drop=True)
    sample_keys = pd.Series([operator_key(value) for value in operators], index=frame.index)
    covered = sample_keys.isin(set(polygons['polygon_operator']))

    def vendors_at(columns: tuple[str, str]) -> pd.Series:
        longitude = pd.to_numeric(frame[columns[0]], errors='coerce')
        latitude = pd.to_numeric(frame[columns[1]], errors='coerce')
        usable = covered & longitude.notna() & latitude.notna()
        result = pd.Series(pd.NA, index=frame.index, dtype='object')
        if not usable.any():
            return result
        points = gpd.GeoDataFrame(
            {'sample_operator': sample_keys[usable]},
            geometry=gpd.points_from_xy(longitude[usable], latitude[usable]), crs='EPSG:4326',
        )
        matches = gpd.sjoin(points, polygons, how='inner', predicate='within')
        matches = matches[matches['sample_operator'] == matches['polygon_operator']]
        found = matches['polygon_vendor'].groupby(level=0).first()
        result.loc[found.index] = found
        return result

    start = vendors_at(start_columns)
    end_columns = _endpoint_columns(dataset, END_COORDINATE_COLUMNS.get(dataset_kind, ()))
    if end_columns:
        end = vendors_at(end_columns)
        no_end = pd.to_numeric(frame[end_columns[0]], errors='coerce').isna() | pd.to_numeric(frame[end_columns[1]], errors='coerce').isna()
        end = end.where(~no_end, start)
    else:
        end = start
    clean = lambda series: [None if pd.isna(value) else str(value) for value in series]
    return clean(start), clean(end), covered.tolist()


def assign_regions(dataset: pd.DataFrame, dataset_kind: str, mapping_path: Path) -> pd.DataFrame:
    """Fill blank Region values with the polygon attribute containing each CDR point."""
    return _assign_polygons(dataset, dataset_kind, mapping_path, 'Region')


def assign_clusters(dataset: pd.DataFrame, dataset_kind: str, mapping_path: Path) -> pd.DataFrame:
    """Fill blank Cluster values with the Clusters polygon containing each CDR point."""
    return _assign_polygons(dataset, dataset_kind, mapping_path, 'Cluster')


def _assign_polygons(dataset: pd.DataFrame, dataset_kind: str, mapping_path: Path, target: str) -> pd.DataFrame:
    coordinate_pairs = COORDINATE_COLUMNS.get(dataset_kind, ())
    longitude = latitude = None
    for longitude_name, latitude_name in coordinate_pairs:
        longitude = _column(dataset.columns, longitude_name)
        latitude = _column(dataset.columns, latitude_name)
        if longitude and latitude:
            break
    if not longitude or not latitude:
        raise ValueError(f'The {dataset_kind} CDR has no supported longitude/latitude columns for {target} mapping.')

    gpd = _geopandas()
    label = 'Region Mapping' if target == 'Region' else 'Clusters'
    polygons = _read_region_mapping(mapping_path, label)
    field = _region_field(polygons.columns) if target == 'Region' else _cluster_field(polygons.columns)
    if polygons.crs is None:
        raise ValueError(f'The {label} must declare a coordinate reference system.')
    result = dataset.copy()
    target_column = _column(result.columns, target) or target
    if target_column not in result:
        result[target_column] = pd.NA
    blank = result[target_column].isna() | result[target_column].astype(str).str.strip().eq('')
    longitude_values = pd.to_numeric(result[longitude], errors='coerce')
    latitude_values = pd.to_numeric(result[latitude], errors='coerce')
    usable = blank & longitude_values.notna() & latitude_values.notna()
    if not usable.any():
        return result
    points = gpd.GeoDataFrame(
        result.loc[usable, []],
        geometry=gpd.points_from_xy(longitude_values[usable], latitude_values[usable]),
        crs='EPSG:4326',
    ).to_crs(polygons.crs)
    matches = gpd.sjoin(points, polygons[[field, 'geometry']], how='left', predicate='within')
    values = matches[field].groupby(level=0).first()
    result.loc[values.index, target_column] = values
    return result
