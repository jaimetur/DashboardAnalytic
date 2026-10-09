"""Dataset uploads continue after leaving the page, also in another workspace."""
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
    # The session is gone once the files are in the workspace.
    assert client.get(url).status_code == 404


def test_an_upload_can_be_cancelled_and_checks_its_files(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    workspace = core.active_workspace
    refused = client.post('/api/uploads', json={'workspace_id': workspace.id, 'files': [{'name': 'notes.exe', 'size': 3}], 'form': {}})
    assert refused.status_code == 400 and 'Unsupported file type' in refused.json()['detail']
    upload = client.post('/api/uploads', json={'workspace_id': workspace.id, 'files': [{'name': 'a.csv', 'size': 3}], 'form': {}}).json()
    url = f"/api/uploads/{workspace.id}/{upload['upload_id']}"
    assert client.post(f'{url}/complete').status_code == 409
    assert client.delete(url).json() == {'ok': True}
    assert client.get(url).status_code == 404
