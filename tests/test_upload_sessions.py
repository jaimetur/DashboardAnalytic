"""Dataset uploads continue after leaving the page, also in another workspace."""
import json

import src.DriveTestAnalyzer as core
from src.modules.repository import Repository
from tests.conftest import wait_for_background_dataset_work

CSV = (b'Operator,City,Mean_Data_Rate,Test_Name,Test_Start_Time\n'
       b'A,London,10,HTTP DL,2026-09-01\nB,Leeds,20,HTTP DL,2026-09-02\nA,London,30,HTTP DL,2026-09-03\n')


def test_an_upload_is_sent_in_chunks_and_ends_in_the_workspace_it_started_in(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    source = core.active_workspace
    started = client.post('/api/uploads', json={
        'workspace_id': source.id, 'files': [{'name': 'sample data.csv', 'size': len(CSV)}],
        'form': {'dataset_kinds': ['data'], 'nr_modes': ['NSA'], 'cdr_stages': ['final']},
    })
    assert started.status_code == 200, started.text
    upload = started.json()
    assert upload['received'] == [0] and not upload['complete']
    url = f"/api/uploads/{source.id}/{upload['upload_id']}"
    # The user opens another workspace while the upload goes on.
    client.post('/workspace/create', data={'name': 'Elsewhere'}, follow_redirects=False)
    assert core.active_workspace.id != source.id
    assert client.put(f'{url}/files/0?offset=0', content=CSV[:40]).json() == {'received': 40}
    # A chunk ahead of the bytes received is refused with the offset to resume from.
    ahead = client.put(f'{url}/files/0?offset=60', content=CSV[60:])
    assert ahead.status_code == 409 and ahead.json()['received'] == 40
    # A chunk sent again after an interruption only adds what is missing.
    assert client.put(f'{url}/files/0?offset=20', content=CSV[20:]).json() == {'received': len(CSV)}
    assert client.get(url).json()['complete'] is True
    completed = client.post(f'{url}/complete')
    assert completed.status_code == 202, completed.text
    assert completed.json()['workspace_id'] == source.id
    wait_for_background_dataset_work()
    source_repository = Repository(source.database_path, global_db_path=core.repository.global_db_path)
    dataset = source_repository.get_dataset(completed.json()['dataset_ids'][0])
    assert dataset['file_name'] == 'sample data.csv' and dataset['dataset_kind'] == 'data'
    assert (source.input_dir / 'sample data.csv').read_bytes() == CSV
    assert core.repository.list_datasets() == []
    # A page resuming the upload learns that it ended.
    assert client.get(url).json()['done'] is True


def test_an_upload_can_be_cancelled_and_checks_its_files(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    workspace = core.active_workspace
    refused = client.post('/api/uploads', json={'workspace_id': workspace.id, 'files': [{'name': 'notes.exe', 'size': 3}], 'form': {}})
    assert refused.status_code == 400 and 'Unsupported file type' in refused.json()['detail']
    upload = client.post('/api/uploads', json={'workspace_id': workspace.id, 'files': [{'name': 'a.csv', 'size': 3}], 'form': {}}).json()
    url = f"/api/uploads/{workspace.id}/{upload['upload_id']}"
    # Nothing is registered before its bytes arrive.
    assert client.post(f'{url}/files/0/complete').status_code == 409
    assert client.post(f'{url}/complete').json()['done'] is False
    assert client.delete(url).json() == {'ok': True}
    assert client.get(url).status_code == 404


def test_each_file_is_processed_as_soon_as_it_is_uploaded(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    workspace = core.active_workspace
    regions = (b'{"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": ['
               b'{"type": "Feature", "properties": {"Region": "London"}, "geometry": {"type": "Polygon", '
               b'"coordinates": [[[-1, 51], [1, 51], [1, 52], [-1, 52], [-1, 51]]]}}]}')
    upload = client.post('/api/uploads', json={
        'workspace_id': workspace.id,
        'files': [{'name': 'Regions.geojson', 'size': len(regions)}, {'name': 'sample data.csv', 'size': len(CSV)}],
        'form': {'dataset_kinds': ['regions', 'data'], 'region_mapping_dataset_ids': ['', 'upload:0']},
    }).json()
    url = f"/api/uploads/{workspace.id}/{upload['upload_id']}"
    # The Regions file is registered and queued while the CDR still uploads.
    client.put(f'{url}/files/0?offset=0', content=regions)
    first = client.post(f'{url}/files/0/complete').json()
    assert first['done'] is False and len(first['dataset_ids']) == 1
    regions_id = first['dataset_ids'][0]
    assert core.repository.get_dataset(regions_id)['dataset_kind'] == 'regions'
    assert client.get(url).json()['registered'] == [True, False]
    client.put(f'{url}/files/1?offset=0', content=CSV)
    second = client.post(f'{url}/files/1/complete').json()
    assert second['done'] is True
    wait_for_background_dataset_work()
    cdr = core.repository.get_dataset(second['dataset_ids'][0])
    # The CDR of the batch used the Regions file uploaded with it.
    # The CDR of the batch was processed with the Regions file uploaded with it.
    assert cdr['status'] == 'ready' and json.loads(cdr['processing_options_json'])['region_mapping_dataset_id'] == regions_id


def test_parallel_workspace_work_runs_side_by_side_but_never_beside_exclusive_work():
    import threading

    from src.modules.background_scheduler import BackgroundTaskScheduler

    scheduler = BackgroundTaskScheduler(max_workers=2)
    running, peak, lock = set(), [], threading.Lock()
    gates = {name: threading.Event() for name in ('a', 'b', 'combined')}

    def task(name):
        with lock:
            running.add(name)
            peak.append(set(running))
        gates[name].wait(timeout=5)
        with lock:
            running.discard(name)

    try:
        first = scheduler.submit_ordered(task, 'a', workspace_key='w', priority=(1, 1), parallel=True)
        second = scheduler.submit_ordered(task, 'b', workspace_key='w', priority=(1, 2), parallel=True)
        combined = scheduler.submit_ordered(task, 'combined', workspace_key='w', priority=(2, 0))
        for _ in range(100):
            if {'a', 'b'} <= running:
                break
            threading.Event().wait(0.02)
        # Two datasets of one Workspace process together; its combined table waits for both.
        assert {'a', 'b'} <= running and 'combined' not in running
        gates['a'].set()
        first.result(timeout=5)
        assert 'combined' not in running
        gates['b'].set()
        second.result(timeout=5)
        gates['combined'].set()
        combined.result(timeout=5)
        assert all(snapshot == {'combined'} for snapshot in peak if 'combined' in snapshot)
    finally:
        for gate in gates.values():
            gate.set()
        scheduler.shutdown()
