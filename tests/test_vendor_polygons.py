"""Vendors — Geospatial: Vendor polygons that assign each CDR sample the Vendor of its Operator."""

import io
import json

import pandas as pd

import src.DriveTestAnalyzer as core
from conftest import wait_for_background_dataset_work
from src.modules.cdr_reporting import assign_cdr_vendors, operator_key
from src.modules.geospatial import polygon_vendor_endpoints, validate_vendor_polygons
from src.modules.repository import local_now_iso


def square(west, south, size=.1):
    return {'type': 'Polygon', 'coordinates': [[[west, south], [west + size, south], [west + size, south + size], [west, south + size], [west, south]]]}


def polygons(features, operator=False):
    return json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'Vendor': vendor, **({'Operator': owner} if operator else {})}, 'geometry': square(west, 51.5)}
        for owner, vendor, west in features
    ]}).encode()


def login(client):
    client.cookies.clear()
    assert client.post('/login', data={'username': 'super', 'password': 'super123'}, follow_redirects=False).status_code == 303


def voice(rows):
    """Voice samples: Operator, start and end positions."""
    return pd.DataFrame([{
        'Operator': operator, 'Call_Start_Longitude_A': start, 'Call_Start_Latitude_A': 51.55 if start is not None else None,
        'Call_End_Longitude_A': end, 'Call_End_Latitude_A': 51.55 if end is not None else None, 'Session_ID_A': index,
    } for index, (operator, start, end) in enumerate(rows)])


def test_vendor_polygons_follow_the_cell_inventory_rule_at_both_ends(tmp_path):
    path = tmp_path / 'uk_vendors.geojson'
    # West: Ericsson for Vodafone and O2; east: Nokia for Vodafone only.
    path.write_bytes(polygons([('Vodafone', 'Ericsson', -0.3), ('O2', 'Ericsson', -0.3), ('Vodafone', 'Nokia', 0.0)], operator=True))
    assert validate_vendor_polygons(path) == ('Vendor', 'Operator')
    frame = voice([
        ('Vodafone', -0.25, -0.25),   # Ericsson at both ends
        ('VF SA', -0.25, 0.05),       # Ericsson then Nokia: same network as Vodafone
        ('Vodafone', 0.05, 0.05),     # Nokia at both ends
        ('O2', 0.05, 0.05),           # no O2 polygon there
        ('O2', -0.25, None),          # no end position: the start is also the end
        ('EE', -0.25, -0.25),         # no EE polygons
        ('Vodafone', None, None),     # no coordinates
    ])
    endpoints = polygon_vendor_endpoints(frame, 'voice', [(path, None)], frame['Operator'].tolist(), operator_key)
    mapped = assign_cdr_vendors(frame, polygon_vendors=endpoints)
    assert mapped['Operator_Vendor'].tolist() == [
        'Vodafone_Ericsson', 'VF SA_Ericsson (Mixed)', 'Vodafone_Nokia', 'O2_Unknown', 'O2_Ericsson', 'EE - All', 'Vodafone_Unknown',
    ]
    assert mapped['Vendor'].tolist() == ['Ericsson', 'Ericsson (Mixed)', 'Nokia', 'Unknown', 'Ericsson', 'EE - All', 'Unknown']


def test_vendor_polygons_without_an_operator_attribute_belong_to_the_chosen_operator(tmp_path):
    path = tmp_path / 'o2_vendor_polygons.geojson'
    path.write_bytes(polygons([('', 'Samsung', -0.3)]))
    frame = voice([('O2', -0.25, -0.25), ('Vodafone', -0.25, -0.25)])
    endpoints = polygon_vendor_endpoints(frame, 'voice', [(path, 'O2')], frame['Operator'].tolist(), operator_key)
    assert assign_cdr_vendors(frame, polygon_vendors=endpoints)['Operator_Vendor'].tolist() == ['O2_Samsung', 'Vodafone UK - All']


def test_vendor_polygons_upload_with_their_operator_and_map_cdrs(client, tmp_path):
    login(client)
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'vendors', 'dataset_operators': ''},
        files={'dataset_files': ('O2_Vendor_Polygons.geojson', io.BytesIO(polygons([('', 'Samsung', -0.3)])), 'application/geo+json')},
        follow_redirects=False,
    )
    assert response.status_code == 303
    wait_for_background_dataset_work()
    uploaded = next(row for row in core.repository.list_datasets() if row['file_name'] == 'O2_Vendor_Polygons.geojson')
    # Without an Operator attribute the Operator comes from the file name.
    assert uploaded['dataset_kind'] == 'vendors' and uploaded['status'] == 'ready' and uploaded['dataset_operator'] == 'O2'
    changed = client.post(f"/workspace/datasets/{uploaded['id']}/dataset-operator", json={'dataset_operator': 'O2'})
    assert changed.status_code == 200
    workspace = client.get('/workspace').text
    card = workspace.split('data-dataset-card="geospatial"', 1)[1].split('</section>', 1)[0]
    assert 'queue-geo-type-vendors">Vendors<' in card and 'data-dataset-dataset-operator-select' in card and '>Type<' in card
    assert 'name="vendor_polygon_dataset_ids"' in workspace and 'data-vendor-source-rule="polygons"' in workspace
    assert 'Polygons Map' in client.get(f"/workspace/preview/{uploaded['id']}").text

    source = tmp_path / 'UK_Voice.csv'
    source.write_text('x\n1\n', encoding='utf-8')
    cdr_id, _created = core.repository.add_dataset(source.name, str(source), 'super')
    rows = voice([('O2', -0.25, -0.25), ('O2', 0.5, 0.5), ('EE', -0.25, -0.25)])
    core.repository.replace_dataset_rows(cdr_id, rows)
    core.repository.update_dataset_profile(
        cdr_id, status='ready', progress=100, dataset_kind='voice', nr_mode='NSA', cdr_stage='final',
        row_count=len(rows), column_count=len(rows.columns), processed_at=local_now_iso(),
        normalization_version=core.DATASET_NORMALIZATION_VERSION, vendor_mapping_applied=1,
    )
    mapped = client.post('/workspace/map-mappings', data={
        'cdr_dataset_ids': str(cdr_id), 'vendor_source': 'polygons', 'vendor_polygon_dataset_ids': str(uploaded['id']),
    }, follow_redirects=False)
    assert mapped.status_code == 303
    wait_for_background_dataset_work()
    result = core.repository.load_dataset_rows(cdr_id, ['Operator_Vendor', 'Vendor'], {})
    assert result['Operator_Vendor'].tolist() == ['O2_Samsung', 'O2_Unknown', 'EE - All']
    options = json.loads(core.repository.get_dataset(cdr_id)['processing_options_json'])
    assert options['vendor_polygon_dataset_ids'] == [uploaded['id']] and options['vodafone_mapping_dataset_id'] is None


def test_a_chosen_operator_overrides_the_operator_attribute(tmp_path):
    path = tmp_path / 'vendors.geojson'
    path.write_bytes(polygons([('Vodafone', 'Ericsson', -0.3)], operator=True))
    frame = voice([('O2', -0.25, -0.25), ('Vodafone', -0.25, -0.25)])
    endpoints = polygon_vendor_endpoints(frame, 'voice', [(path, 'O2')], frame['Operator'].tolist(), operator_key)
    assert assign_cdr_vendors(frame, polygon_vendors=endpoints)['Operator_Vendor'].tolist() == ['O2_Ericsson', 'Vodafone UK - All']
