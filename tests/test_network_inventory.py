"""Network Inventories of any Operator: uploaded with their Operator and, with cells and Vendors, used to map Vendors."""

import io
import json

import pandas as pd

import src.DriveTestAnalyzer as core
from conftest import wait_for_background_dataset_work
from src.modules.cdr_reporting import assign_cdr_vendors, build_inventory_vendor_lookup, inventory_vendor_columns, operator_key
from src.modules.repository import local_now_iso


def login(client):
    client.cookies.clear()
    assert client.post('/login', data={'username': 'super', 'password': 'super123'}, follow_redirects=False).status_code == 303


def test_network_inventory_columns_and_cells():
    assert inventory_vendor_columns(['Site', 'ECI', 'OEM']) == {'vendor': 'OEM', 'cell': 'ECI'}
    assert inventory_vendor_columns(['eNB ID', 'Local Cell ID', 'Vendor']) == {'vendor': 'Vendor', 'enodeb': 'eNB ID', 'local_cell': 'Local Cell ID'}
    assert inventory_vendor_columns(['Site', 'Latitude', 'Longitude']) is None
    assert build_inventory_vendor_lookup(pd.DataFrame({'ECI': [1001.0, 1002], 'Vendor': ['Nokia', 'Ericsson']})) == {'1001': 'Nokia', '1002': 'Ericsson'}
    assert build_inventory_vendor_lookup(pd.DataFrame({'eNodeB ID': [10], 'Local Cell ID': [3], 'Vendor': ['Samsung']})) == {str(10 * 256 + 3): 'Samsung'}


def test_network_inventories_map_the_vendor_of_their_operator():
    frame = pd.DataFrame({
        'Operator': ['O2', 'O2', 'O2', 'EE', 'Vodafone'],
        'Cell_ID_A': ['1001 -> 1001', '1001 -> 1002', '9', '1001', '1001'],
    })
    lookups = {operator_key('O2'): {'1001': 'Ericsson', '1002': 'Nokia'}}
    mapped = assign_cdr_vendors(frame, inventory_lookups=lookups)
    assert mapped['Operator_Vendor'].tolist() == ['O2_Ericsson', 'O2_Ericsson_Mixed', 'O2_Non-Ericsson_Mixed', 'EE - All', 'Vodafone UK - All']
    assert mapped['Vendor'].tolist() == ['Ericsson', 'Ericsson_Mixed', 'Non-Ericsson_Mixed', 'EE - All', 'Vodafone UK - All']


def test_network_inventory_upload_with_its_operator_and_map_cdrs(client, tmp_path):
    login(client)
    inventory = 'Site,ECI,Vendor\nS1,1001,Ericsson\nS2,1002,Nokia\n'
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'network_inventory', 'dataset_operators': ''},
        files={'dataset_files': ('O2_Network_Inventory.csv', io.BytesIO(inventory.encode()), 'text/csv')},
        follow_redirects=False,
    )
    assert response.status_code == 303
    wait_for_background_dataset_work()
    uploaded = next(row for row in core.repository.list_datasets() if row['file_name'] == 'O2_Network_Inventory.csv')
    # The Operator comes from the file name; the Network Inventory card lets it be changed.
    assert uploaded['dataset_kind'] == 'network_inventory' and uploaded['status'] == 'ready' and uploaded['dataset_operator'] == 'O2'
    assert client.post(f"/workspace/datasets/{uploaded['id']}/dataset-operator", json={'dataset_operator': 'O2'}).status_code == 200
    workspace = client.get('/workspace').text
    card = workspace.split('data-dataset-card="network-inventory"', 1)[1].split('</section>', 1)[0]
    assert 'O2_Network_Inventory.csv' in card and 'data-dataset-operator-select' in card
    assert f'name="network_inventory_dataset_ids" value="{uploaded["id"]}" checked' in workspace

    source = tmp_path / 'UK_Voice.csv'
    source.write_text('x\n1\n', encoding='utf-8')
    cdr_id, _created = core.repository.add_dataset(source.name, str(source), 'super')
    rows = pd.DataFrame({'Operator': ['O2', 'O2', 'EE'], 'Cell_ID_A': ['1001', '1001 -> 1002', '1001'], 'Session_ID_A': [1, 2, 3]})
    core.repository.replace_dataset_rows(cdr_id, rows)
    core.repository.update_dataset_profile(
        cdr_id, status='ready', progress=100, dataset_kind='voice', nr_mode='NSA', cdr_stage='final',
        row_count=len(rows), column_count=len(rows.columns), processed_at=local_now_iso(),
        normalization_version=core.DATASET_NORMALIZATION_VERSION, vendor_mapping_applied=1,
    )
    mapped = client.post('/workspace/map-mappings', data={
        'cdr_dataset_ids': str(cdr_id), 'vendor_source': 'inventory', 'network_inventory_dataset_ids': str(uploaded['id']),
    }, follow_redirects=False)
    assert mapped.status_code == 303
    wait_for_background_dataset_work()
    result = core.repository.load_dataset_rows(cdr_id, ['Operator_Vendor'], {})
    assert result['Operator_Vendor'].tolist() == ['O2_Ericsson', 'O2_Ericsson_Mixed', 'EE - All']
    options = json.loads(core.repository.get_dataset(cdr_id)['processing_options_json'])
    assert options['network_inventory_dataset_ids'] == [uploaded['id']]
