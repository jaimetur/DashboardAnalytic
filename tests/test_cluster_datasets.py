from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

import src.DriveTestAnalyzer as app_module
from src.modules.geospatial import validate_cluster_mapping, validate_region_mapping
from src.modules.repository import Repository


def _cluster_geojson(attribute='Cluster', value='North', geometry=None):
    return json.dumps({
        'type': 'FeatureCollection',
        'features': [{'type': 'Feature', 'properties': {attribute: value},
                      'geometry': geometry or {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}],
    }).encode()


def _upload_clusters(client, filename, content):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    response = client.post('/datasets-analysis/upload', data={'dataset_kinds': 'clusters'},
                           files={'dataset_files': (filename, io.BytesIO(content), 'application/octet-stream')},
                           follow_redirects=False)
    assert response.status_code == 303
    return next(dict(row) for row in app_module.repository.list_datasets() if row['file_name'] == filename)


@pytest.mark.parametrize('extension', ['.geojson', '.json', '.zip'])
def test_workspace_accepts_cluster_polygons_and_preserves_them_in_archives(client, tmp_path, extension):
    if extension == '.zip':
        shape_dir = tmp_path / 'shapes'
        shape_dir.mkdir()
        frame = gpd.GeoDataFrame({'Cluster': ['North']}, geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])], crs='EPSG:4326')
        frame.to_file(shape_dir / 'clusters.shp')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for path in shape_dir.iterdir():
                archive.writestr(f'polygons/{path.name}', path.read_bytes())
        content = buffer.getvalue()
    else:
        content = _cluster_geojson()
    dataset = _upload_clusters(client, f'clusters{extension}', content)
    assert dataset['dataset_kind'] == 'clusters' and dataset['status'] == 'ready'
    assert dataset['nr_mode'] is None
    assert Path(dataset['stored_path']).read_bytes() == content
    rows = app_module.repository.load_dataset_rows(dataset['id'], ['Cluster_Field'], {})
    assert rows.iloc[0]['Cluster_Field'] == 'Cluster'
    workspace_page = client.get('/workspace').text
    assert 'Clusters — Geospatial' in workspace_page
    assert client.get(f"/workspace/preview/{dataset['id']}").status_code == 200
    assert f"dataset_rows_{dataset['id']}" in app_module.repository.list_database_tables()
    insights = client.get('/network-insights').text
    assert 'Cluster Sites Density' in insights and 'Cluster polygons required.' in insights
    assert insights.index('network-insights:deployment') < insights.index('network-insights:sites')

    workspace = app_module.active_workspace
    package = tmp_path / 'cluster-workspace.zip'
    app_module.build_export_archive_file(f'workspace:{workspace.id}', package)
    stage = tmp_path / 'restore'
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        app_module._safe_extract_archive(archive, stage)
    restored = app_module.import_workspace_archive(stage / manifest['archive_path'], manifest['workspace'])
    restored_repo = Repository(restored.database_path, app_module.repository.global_db_path)
    recovered = next(dict(row) for row in restored_repo.list_datasets() if row['file_name'] == dataset['file_name'])
    assert recovered['dataset_kind'] == 'clusters' and recovered['status'] == 'ready'
    assert Path(recovered['stored_path']).read_bytes() == content
    assert validate_cluster_mapping(Path(recovered['stored_path'])) == 'Cluster'


@pytest.mark.parametrize('content, error', [
    (_cluster_geojson(attribute='Unknown'), 'must contain a Cluster'),
    (_cluster_geojson(value=''), 'blank values'),
    (_cluster_geojson(geometry={'type': 'Point', 'coordinates': [0, 0]}), 'only polygon geometries'),
])
def test_invalid_clusters_never_become_ready(client, content, error):
    dataset = _upload_clusters(client, 'bad-clusters.geojson', content)
    assert dataset['status'] == 'failed'
    assert error in dataset['last_error']


def test_cluster_validation_retains_region_mapping_behavior(tmp_path):
    region = tmp_path / 'regions.geojson'
    region.write_bytes(_cluster_geojson(attribute='Region'))
    assert validate_region_mapping(region) == 'Region'
    invalid_zip = tmp_path / 'clusters.zip'
    with zipfile.ZipFile(invalid_zip, 'w') as archive:
        archive.writestr('README.txt', 'No shapes')
    with pytest.raises(ValueError, match=r'Clusters ZIP must contain a .shp file'):
        validate_cluster_mapping(invalid_zip)
    unsupported = tmp_path / 'clusters.csv'
    unsupported.write_text('Cluster\nNorth\n')
    with pytest.raises(ValueError, match='Clusters require GeoJSON'):
        validate_cluster_mapping(unsupported)


def test_polygon_datasets_preview_their_polygons_on_a_map_without_cdr_actions(client):
    square = lambda west, south: {'type': 'Polygon', 'coordinates': [[[west, south], [west + .1, south], [west + .1, south + .1], [west, south + .1], [west, south]]]}
    content = json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'Cluster': name}, 'geometry': square(west, 51.5)}
        for name, west in (('London West', -0.3), ('London East', 0.0))
    ]}).encode()
    dataset = _upload_clusters(client, 'london_clusters.geojson', content)
    page = client.get(f"/workspace/preview/{dataset['id']}").text
    assert 'data-polygon-map' in page and 'Polygons Map' in page and 'dataset-preview-table' not in page
    assert 'Cluster polygons of the dataset (United Kingdom)' in page
    data = json.loads(page.split('data-polygon-map-data>', 1)[1].split('</script>', 1)[0])
    assert sorted(data['boundaries']) == ['London East', 'London West'] and data['background']
    # Reference datasets keep Preview, Reprocess and Delete only: they have no analysis or mappings to apply.
    workspace = client.get('/workspace').text
    card = workspace.split('data-dataset-card="geospatial"', 1)[1].split('</section>', 1)[0]
    assert 'Show the polygons on a map' in card and 'action-link-reprocess' in card and 'Delete dataset' in card
    assert 'Show Analysis' not in card and 'action-link-map-vendors' not in card and 'action-link-clear-vendors' not in card
