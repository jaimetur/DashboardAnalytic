import json

import pandas as pd
import pytest

import src.DashboardAnalytic as app_module
from src.modules.geospatial import assign_clusters, assign_regions


def _polygons(path, field, name):
    path.write_text(json.dumps({
        'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
        'features': [{'type': 'Feature', 'properties': {field: name},
                      'geometry': {'type': 'Polygon', 'coordinates': [[[-2, 53], [0, 53], [0, 55], [-2, 55], [-2, 53]]]}}],
    }), encoding='utf-8')
    return path


def test_cluster_mapping_fills_the_cluster_column_like_regions(tmp_path):
    pytest.importorskip('geopandas')
    frame = pd.DataFrame({'Test_Start_Longitude': [-1.0, 5.0, -1.0], 'Test_Start_Latitude': [54.0, 54.0, 54.0],
                          'Cluster': ['', '', 'Source Cluster']})
    mapped = assign_clusters(frame, 'data', _polygons(tmp_path / 'clusters.geojson', 'Cluster', 'Leeds Cluster'))
    assert mapped['Cluster'].tolist()[0] == 'Leeds Cluster'
    assert mapped['Cluster'].tolist()[2] == 'Source Cluster'
    assert pd.isna(mapped['Cluster'].tolist()[1]) or mapped['Cluster'].tolist()[1] == ''
    regions = assign_regions(frame.drop(columns='Cluster'), 'data', _polygons(tmp_path / 'regions.geojson', 'Region', 'North'))
    assert regions['Region'].tolist()[0] == 'North'


def test_mapping_again_overwrites_without_clearing_and_keeps_unselected_mappings(client, monkeypatch, tmp_path):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    repository = app_module.repository
    source = tmp_path / 'cdr.csv'
    source.write_text('x', encoding='utf-8')
    cdr_id, _ = repository.add_dataset('cdr.csv', str(source), 'admin')
    repository.replace_dataset_rows(cdr_id, pd.DataFrame({'Operator': ['EE']}))
    repository.update_dataset_profile(cdr_id, status='ready', progress=100, dataset_kind='data', nr_mode='NSA',
                                      region_mapping_applied=1, region_mapping_dataset_id=77,
                                      cluster_mapping_applied=1, cluster_mapping_dataset_id=88,
                                      normalization_version=app_module.DATASET_NORMALIZATION_VERSION)
    clusters_path = _polygons(tmp_path / 'clusters.geojson', 'Cluster', 'Leeds Cluster')
    clusters_id, _ = repository.add_dataset('clusters.geojson', str(clusters_path), 'admin')
    repository.update_dataset_profile(clusters_id, status='ready', progress=100, dataset_kind='clusters')
    calls = []
    monkeypatch.setattr(app_module, 'enqueue_dataset_processing', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(app_module, '_reporting_dataset', lambda dataset_id, kind, *_args: {'id': dataset_id})
    # A Region mapping alone keeps the previous Cluster mapping.
    response = client.post('/workspace/map-mappings', data={'cdr_dataset_ids': [cdr_id], 'region_mapping_dataset_id': 5},
                           follow_redirects=False)
    assert response.status_code == 303
    args, kwargs = calls[-1]
    assert args[6] == 5 and kwargs['cluster_mapping_dataset_id'] == 88
    # A new Cluster mapping replaces the previous one and keeps the Region mapping.
    client.post('/workspace/map-mappings', data={'cdr_dataset_ids': [cdr_id], 'cluster_mapping_dataset_id': clusters_id},
                follow_redirects=False)
    args, kwargs = calls[-1]
    assert args[6] == 77 and kwargs['cluster_mapping_dataset_id'] == clusters_id
    statuses = {row['id']: row for row in client.get('/api/datasets/status').json()['datasets']}
    assert statuses[cdr_id]['can_map_mappings'] and statuses[cdr_id]['can_clear_mappings']
    workspace = client.get('/workspace').text
    assert 'name="cluster_mapping_dataset_id"' in workspace and 'Cluster mapping rule' in workspace
    assert 'data-cluster-mapping-options=' in workspace
