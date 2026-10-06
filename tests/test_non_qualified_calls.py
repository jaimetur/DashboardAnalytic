import io
import json
import time
import zipfile
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

import src.DriveTestAnalyzer as core
from src.modules import non_qualified_calls as nq
from src.modules.repository import local_now_iso


def login(client, username='super', password='super123'):
    client.cookies.clear()
    response = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert response.status_code == 303


def enable_module():
    settings = core.feature_activation_settings()
    settings['non-qualified-calls'] = {'default': 'all'}
    core.save_feature_activation_settings(settings)


def workspace_user(username, role):
    core.repository.create_user(username, f'{username}123', role)
    user_id = next(int(row['id']) for row in core.repository.list_users() if row['username'] == username)
    core.repository.set_user_workspace_access(user_id, [core.active_workspace.id])


def add_cdr(tmp_path: Path, name: str, kind: str, rows: pd.DataFrame) -> int:
    repository = core.repository
    source = tmp_path / name
    source.write_text('test source', encoding='utf-8')
    dataset_id, _created = repository.add_dataset(name, str(source), 'super')
    repository.replace_dataset_rows(dataset_id, rows)
    repository.update_dataset_profile(
        dataset_id, status='ready', progress=100, dataset_kind=kind, nr_mode='NSA',
        row_count=len(rows), column_count=len(rows.columns), processed_at=local_now_iso(),
    )
    return dataset_id


def voice_rows() -> pd.DataFrame:
    return pd.DataFrame({
        'Operator': ['EE', 'EE', 'Vodafone UK'],
        'Campaign': ['UK_Q1_2026'] * 3,
        'City': ['Leeds', 'York', 'Leeds'],
        'Session_ID_A': [1001, 1002, 1003],
        'Call_Status': ['Completed', 'Failed', 'Dropped'],
        'status': ['Completed', 'Failed', 'Dropped'],
        'event_start_time': ['2026-02-24 10:00:00', '2026-02-24 11:00:00', None],
        'Call_Start_Time': ['2026-02-24 10:00:00', '2026-02-24 11:00:00', '2026-02-24 12:00:00'],
        'Failure_Classification': ['', 'RF Problems', 'VoLTE Problems'],
        'Failure_Category': ['', 'Coverage problem', 'IMS'],
        'Call_Start_Latitude_A': [53.8, 53.9, 53.7],
        'Call_Start_Longitude_A': [-1.5, -1.0, -1.6],
    })


def data_rows() -> pd.DataFrame:
    return pd.DataFrame({
        'Operator': ['EE', 'Vodafone UK', 'Vodafone UK'],
        'Campaign': ['UK_Q1_2026'] * 3,
        'City': ['Leeds', 'Leeds', 'York'],
        'Test_ID': [5001, 5002, 5003],
        'Test_Name': ['HTTP DL', 'HTTP UL', 'Ping'],
        'Test_Result': ['Completed', 'Cutoff', 'Failed'],
        'status': ['Completed', 'Cutoff', 'Failed'],
        'event_start_time': ['2026-02-25 09:00:00', '2026-02-25 09:05:00', '2026-02-25 09:10:00'],
        'Failure_Classification': ['', 'RF Problems', ''],
        'Failure_Comment': ['', 'Interference on PCI 80', ''],
    })


def query(client, **payload):
    response = client.post('/api/non-qualified-calls/calls', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_module_is_hidden_until_activated_and_marks_tabs_in_development(client):
    login(client)
    assert client.get('/api/non-qualified-calls/state').status_code == 403
    page = client.get('/workspace').text
    assert 'href="/non-qualified-calls"' not in page
    # Each module tab shows its stage: ALPHA, BETA, NEW or STABLE.
    assert '<span class="module-tab-label-mobile">Network</span><svg class="module-tab-new module-tab-new-alpha"' in page
    assert '<span class="module-tab-label-mobile">Scoring</span><svg class="module-tab-new module-tab-new-beta"' in page
    assert '<span>Workspace</span><svg class="module-tab-new module-tab-new-stable"' in page
    assert '<span class="module-tab-label-mobile">Analysis</span><svg class="module-tab-new module-tab-new-stable"' in page
    assert '>STABLE</text>' in page and '>ALPHA</text>' in page and '>BETA</text>' in page and '>NEW</text>' in page
    enable_module()
    page = client.get('/non-qualified-calls')
    assert page.status_code == 200
    assert 'module-tab-non-qualified-calls active' in page.text
    assert '<span class="module-tab-label-mobile">NQ Calls</span><svg class="module-tab-new module-tab-new-alpha"' in page.text
    assert 'id="nq-table"' in page.text and 'non_qualified_calls.js' in page.text


def test_nq_calls_are_indexed_tracked_and_commented(client, tmp_path):
    enable_module()
    workspace_user('editor', 'user-editor')
    workspace_user('viewer', 'user-viewer')
    voice_id = add_cdr(tmp_path, 'NetCheck_UK_CDR_Voice_2026_Q1.xlsx', 'voice', voice_rows())
    add_cdr(tmp_path, 'NetCheck_UK_CDR_Data_2026_Q1.xlsx', 'data', data_rows())
    login(client)

    state = client.get('/api/non-qualified-calls/state').json()
    assert state['sync']['calls'] == 4 and state['sync']['datasets'] == 2
    assert [item['name'] for item in state['options']['statuses']][:2] == ['Open', 'Under Investigation']
    assert state['filter_options']['result'] == ['Cutoff', 'Dropped', 'Failed']
    assert {'super', 'editor', 'viewer'} <= set(state['users'])

    result = query(client)
    assert result['total'] == 4 and result['summary'] == {
        'total': 4, 'closed': 0, 'commented': 0, 'with_team': 0, 'assigned': 0, 'open': 4,
    }
    by_service = next(item for item in result['breakdowns'] if item['field'] == 'service')['items']
    assert {item['value']: item['count'] for item in by_service} == {'voice': 2, 'data': 2}
    dropped = next(call for call in result['calls'] if call['result'] == 'Dropped')
    # Empty values fall back to the next CDR column with a value.
    assert dropped['start_time'] == '2026-02-24 12:00:00' and dropped['status'] == 'Open'
    assert dropped['latitude'] == 53.7 and dropped['failure_classification'] == 'VoLTE Problems'
    assert query(client, filters={'service': ['voice']})['total'] == 2
    assert query(client, filters={'search': 'pci 80'})['total'] == 1

    key = dropped['call_key']
    url = f'/api/non-qualified-calls/calls/{key}'
    changed = client.patch(url, json={'changes': {'status': 'Under Investigation', 'team': 'Core Network'}, 'version': 0})
    assert changed.status_code == 200, changed.text
    detail = changed.json()
    assert detail['call']['status'] == 'Under Investigation' and detail['call']['version'] == 1
    assert {(entry['field'], entry['new_value']) for entry in detail['history']} == {
        ('status', 'Under Investigation'), ('team', 'Core Network')}
    assert ['Call_Status', 'Dropped'] in detail['fields'] and detail['call']['dataset_name'].endswith('Voice_2026_Q1.xlsx')
    # A stale version means another user changed the call first.
    assert client.patch(url, json={'changes': {'status': 'Resolved'}, 'version': 0}).status_code == 409
    assert client.patch(url, json={'changes': {'status': 'Unknown'}}).status_code == 400
    assert client.patch(url, json={'changes': {'assignee': 'nobody'}}).status_code == 400

    comment = client.post(f'{url}/comments', json={'body': 'Waiting for E2E traces from the vendor.'}).json()['comment']
    assert client.post(f'{url}/comments', json={'body': '   '}).status_code == 400
    listed = query(client, filters={'search': 'e2e traces'})
    assert listed['total'] == 1 and listed['calls'][0]['comment_count'] == 1
    assert listed['calls'][0]['last_comment']['created_by'] == 'super'
    assert query(client, filters={'without_comments': True})['total'] == 3
    assert query(client, filters={'team': [nq.UNASSIGNED]})['total'] == 3

    login(client, 'editor', 'editor123')
    assert client.patch(f"/api/non-qualified-calls/comments/{comment['id']}", json={'body': 'Changed'}).status_code == 403
    own = client.post(f'{url}/comments', json={'body': 'Traces requested.'}).json()['comment']
    edited = client.patch(f"/api/non-qualified-calls/comments/{own['id']}", json={'body': 'Traces requested twice.'})
    assert edited.status_code == 200 and edited.json()['comment']['edited_by'] == 'editor'
    bulk = client.post('/api/non-qualified-calls/calls/bulk', json={
        'call_keys': [call['call_key'] for call in result['calls']], 'changes': {'assignee': 'editor'}})
    assert bulk.json() == {'changed': 4}
    assert query(client, filters={'mine': True})['total'] == 4

    login(client, 'viewer', 'viewer123')
    assert query(client)['total'] == 4
    assert client.patch(url, json={'changes': {'status': 'Resolved'}}).status_code == 403
    assert client.post(f'{url}/comments', json={'body': 'Hi'}).status_code == 403

    login(client)  # A super-admin moderates any comment; deleted comments keep their history.
    deleted = client.delete(f"/api/non-qualified-calls/comments/{own['id']}").json()['comment']
    assert deleted['body'] == '' and deleted['deleted_by'] == 'super'
    detail = client.get(url).json()
    assert [entry['field'] for entry in detail['history']][-3:] == ['comment_edit', 'assignee', 'comment_delete']
    assert detail['history'][-1]['old_value'] == 'Traces requested twice.'

    # Processing the same CDR again keeps the follow-up of its calls.
    core.repository.replace_dataset_rows(voice_id, voice_rows())
    core.repository.update_dataset_profile(voice_id, processed_at=local_now_iso(), updated_at=local_now_iso())
    again = query(client, filters={'service': ['voice'], 'status': ['Under Investigation']})
    assert again['sync']['reindexed'] == 1 and again['total'] == 1 and again['calls'][0]['call_key'] == key
    assert query(client, filters={'open_only': True})['total'] == 4
    client.patch(url, json={'changes': {'status': 'Resolved'}})
    assert query(client, filters={'open_only': True})['total'] == 3
    assert query(client)['summary']['closed'] == 1


def test_statuses_and_teams_can_be_renamed_but_not_removed_while_in_use(client, tmp_path):
    enable_module()
    add_cdr(tmp_path, 'NetCheck_UK_CDR_Voice_2026_Q1.xlsx', 'voice', voice_rows())
    login(client)
    key = query(client)['calls'][0]['call_key']
    client.patch(f'/api/non-qualified-calls/calls/{key}', json={'changes': {'team': 'Transport'}})
    options = client.get('/api/non-qualified-calls/state').json()['options']
    teams = [{'name': 'Backhaul' if team['name'] == 'Transport' else team['name'], 'color': team['color'],
              'previous': team['name']} for team in options['teams']]
    saved = client.put('/api/non-qualified-calls/options', json={'statuses': options['statuses'], 'teams': teams})
    assert saved.status_code == 200, saved.text
    assert client.get(f'/api/non-qualified-calls/calls/{key}').json()['call']['team'] == 'Backhaul'
    removed = client.put('/api/non-qualified-calls/options', json={
        'statuses': options['statuses'], 'teams': [team for team in teams if team['name'] != 'Backhaul']})
    assert removed.status_code == 400 and 'in use' in removed.json()['detail']
    assert client.put('/api/non-qualified-calls/options', json={'statuses': [], 'teams': teams}).status_code == 400
    repeated = [{'name': 'Open'}, {'name': 'open'}]
    assert client.put('/api/non-qualified-calls/options', json={'statuses': repeated, 'teams': teams}).status_code == 400


def test_excel_export_lists_calls_comments_and_history(client, tmp_path):
    enable_module()
    add_cdr(tmp_path, 'NetCheck_UK_CDR_Data_2026_Q1.xlsx', 'data', data_rows())
    login(client)
    key = query(client, filters={'result': ['Cutoff']})['calls'][0]['call_key']
    client.patch(f'/api/non-qualified-calls/calls/{key}', json={'changes': {'status': 'Pending Information'}})
    client.post(f'/api/non-qualified-calls/calls/{key}/comments', json={'body': 'Check the interference.'})
    response = client.post('/api/non-qualified-calls/export', json={'filters': {'result': ['Cutoff']}})
    assert response.status_code == 200
    assert response.headers['content-disposition'].endswith('.xlsx"')
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ['NQ Calls', 'Comments', 'History']
    calls = list(workbook['NQ Calls'].values)
    header = calls[0]
    assert len(calls) == 2
    row = dict(zip(header, calls[1]))
    assert (row['Result'], row['Status'], row['Comments'], row['Last Comment']) == (
        'Cutoff', 'Pending Information', 1, 'Check the interference.')
    assert list(workbook['Comments'].values)[1][4] == 'Check the interference.'
    assert list(workbook['History'].values)[1][4:7] == ('Status', 'Open', 'Pending Information')


def test_tracking_travels_with_workspace_packages_and_imports_once(client, tmp_path):
    enable_module()
    add_cdr(tmp_path, 'NetCheck_UK_CDR_Voice_2026_Q1.xlsx', 'voice', voice_rows())
    login(client)
    key = query(client)['calls'][0]['call_key']
    client.patch(f'/api/non-qualified-calls/calls/{key}', json={'changes': {'status': 'Resolved'}})
    client.post(f'/api/non-qualified-calls/calls/{key}/comments', json={'body': 'Fixed by the RAN team.'})
    payload = core._nq_call_tracking_payload(core.active_workspace)
    document = json.loads(payload)
    assert document['format'] == 'nq-call-tracking' and len(document['comments']) == 1
    assert 'nq_call_tracking' in core.full_workspace_archive_components()
    assert core.archive_workspace_components_for_target('nq-call-tracking') == ['nq_call_tracking']

    with core.repository.connection() as connection:
        for table in (nq.NQ_CALL_TRACKING_TABLE, nq.NQ_CALL_COMMENTS_TABLE, nq.NQ_CALL_HISTORY_TABLE):
            connection.execute(f'DELETE FROM {table}')
    assert core._restore_workspace_nq_call_tracking(core.active_workspace, payload) == 1
    detail = client.get(f'/api/non-qualified-calls/calls/{key}').json()
    assert detail['call']['status'] == 'Resolved' and detail['comments'][0]['body'] == 'Fixed by the RAN team.'
    assert len(detail['history']) == 1
    # Importing the same follow-up again changes nothing.
    assert core._restore_workspace_nq_call_tracking(core.active_workspace, payload) == 0
    assert len(client.get(f'/api/non-qualified-calls/calls/{key}').json()['comments']) == 1

    # Admin → Import/Export: the NQ Call Tracking package imports into a workspace.
    exported = client.get('/admin/import-export/export?export_target=nq-call-tracking')
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert json.loads(archive.read(manifest['archive_path']))['format'] == 'nq-call-tracking'
    assert manifest['kind'] == 'nq-call-tracking' and core.archive_workspace_components(manifest) == ['nq_call_tracking']
    with core.repository.connection() as connection:
        connection.execute(f'DELETE FROM {nq.NQ_CALL_COMMENTS_TABLE}')
    inspection = client.post('/admin/import-export/inspect',
                             files={'package': ('nq.zip', io.BytesIO(exported.content), 'application/zip')})
    assert inspection.status_code == 200, inspection.text
    job = client.post('/admin/import-export/import/jobs', data={
        'upload_id': inspection.headers['X-Import-Upload-Id'], 'confirmed_import': 'true', 'workspace_ids': 'default'})
    assert job.status_code == 200, job.text
    for _attempt in range(200):
        status = client.get(job.json()['status_url']).json()
        if status['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert status['status'] == 'ready', status
    assert len(client.get(f'/api/non-qualified-calls/calls/{key}').json()['comments']) == 1


def test_nq_tables_appear_in_database_management(client, tmp_path):
    enable_module()
    login(client)
    client.get('/api/non-qualified-calls/state')
    page = client.get('/admin').text
    for title in ('NQ Calls', 'NQ Call Tracking', 'NQ Call Comments', 'NQ Call History', 'NQ Call Options', 'NQ Call Sources'):
        assert f'>{title}<' in page or f'"{title}"' in page, title


def test_teams_members_progress_shared_filters_and_reporting_artifact(client, tmp_path):
    enable_module()
    workspace_user('editor', 'user-editor')
    workspace_user('viewer', 'user-viewer')
    voice_id = add_cdr(tmp_path, 'NetCheck_UK_CDR_Voice_2026_Q1.xlsx', 'voice', voice_rows())
    add_cdr(tmp_path, 'NetCheck_UK_CDR_Data_2026_Q1.xlsx', 'data', data_rows())
    login(client)

    # Teams are edited from Workspace Config with their members; a user can be in several teams.
    teams = client.get('/api/non-qualified-calls/teams').json()
    assert teams['can_edit'] and {'editor', 'viewer'} <= set(teams['users'])
    payload = [{**team, 'previous': team['name'], 'members': ['editor'] if team['name'] == 'Core Network' else []}
               for team in teams['teams']]
    payload.append({'name': 'Field Ops', 'color': '#336699', 'previous': '', 'members': ['editor', 'viewer']})
    saved = client.put('/api/non-qualified-calls/teams', json={'teams': payload})
    assert saved.status_code == 200, saved.text
    members = {team['name']: team['members'] for team in saved.json()['teams']}
    assert members['Core Network'] == ['editor'] and members['Field Ops'] == ['editor', 'viewer']
    assert client.put('/api/non-qualified-calls/teams', json={'teams': [{'name': 'Ghosts', 'members': ['nobody']}]}).status_code == 400
    assert 'Non-Qualified Calls Teams' in client.get('/workspace-config').text

    # A call of a team with members only accepts its members as assignee.
    call = next(item for item in query(client)['calls'] if item['result'] == 'Dropped')
    url = f"/api/non-qualified-calls/calls/{call['call_key']}"
    assert client.patch(url, json={'changes': {'team': 'Core Network', 'assignee': 'viewer'}}).status_code == 400
    assigned = client.patch(url, json={'changes': {'team': 'Field Ops', 'assignee': 'viewer'}}).json()['call']
    assert assigned['assignee'] == 'viewer'
    # Moving it to a team the assignee does not belong to clears the assignee.
    moved = client.patch(url, json={'changes': {'team': 'Core Network'}}).json()['call']
    assert moved['team'] == 'Core Network' and moved['assignee'] == ''
    assert client.post(f'{url}/comments', json={'body': 'Checked the drive test.'}).status_code == 200

    # Summary breakdowns include the CDR names.
    result = query(client)
    by_cdr = next(item for item in result['breakdowns'] if item['field'] == 'dataset_id')
    assert by_cdr['label'] == 'By CDR' and {item['label'] for item in by_cdr['items']} == {
        'NetCheck_UK_CDR_Voice_2026_Q1.xlsx', 'NetCheck_UK_CDR_Data_2026_Q1.xlsx'}
    assert [item['field'] for item in result['breakdowns']][-5:] == ['vendor', 'region', 'cluster', 'city', 'dataset_id']

    # Progress View: distributions, attended calls and periods.
    progress = client.post('/api/non-qualified-calls/progress', json={'filters': {}, 'granularity': 'week'})
    assert progress.status_code == 200, progress.text
    progress = progress.json()
    assert progress['summary']['total'] == 4 and progress['summary']['attended'] == 1
    assert {item['field'] for item in progress['distributions']} >= {'status', 'team', 'assignee'}
    assert progress['periods'] and sum(period['detected'] for period in progress['periods']) == 4

    # The Filters panel is shared by every user and session of the workspace.
    filters = {'service': ['voice'], 'city': ['Leeds'], 'open_only': True, 'search': 'drop', 'unknown': ['x']}
    assert client.put('/api/non-qualified-calls/filters', json={'filters': filters}).status_code == 200
    login(client, 'viewer', 'viewer123')
    assert client.get('/api/non-qualified-calls/state').json()['saved_filters'] == {
        'city': ['Leeds'], 'open_only': True, 'search': 'drop', 'service': ['voice']}

    # Reporting Jobs: the Executive Summary and Progress Status artifact with its filters.
    from src.modules.report_tasks import ARTIFACT_PROVIDERS

    login(client)
    provider = ARTIFACT_PROVIDERS['non_qualified_calls']
    user = core.SessionUser(username='super', role='super-admin')
    artifacts = provider['generate'](
        {'formats': ['powerpoint', 'word', 'excel'], 'options': {'filters': {'datasets': [str(voice_id)]}, 'granularity': 'month'}},
        tmp_path, '20261006_120000', user)
    assert [item['file_name'] for item in artifacts] == [
        '20261006_120000 - Non-Qualified Calls - Executive Summary and Progress Status.pptx',
        '20261006_120000 - Non-Qualified Calls - Executive Summary and Progress Status.docx',
        '20261006_120000 - Non-Qualified Calls - Executive Summary and Progress Status.xlsx',
    ]
    assert all((tmp_path / item['file_name']).stat().st_size > 0 for item in artifacts)
    assert '2 Non-Qualified Calls' in artifacts[0]['details'][-1]


def test_page_exports_the_executive_summary_to_powerpoint_and_word(client, tmp_path):
    from docx import Document
    from pptx import Presentation

    enable_module()
    add_cdr(tmp_path, 'NetCheck_UK_CDR_Data_2026_Q1.xlsx', 'data', data_rows())
    login(client)
    page = client.get('/non-qualified-calls').text
    assert 'data-nq-document-export="powerpoint"' in page and 'data-nq-document-export="word"' in page
    body = {'filters': {'result': ['Cutoff']}, 'granularity': 'month'}
    deck = client.post('/api/non-qualified-calls/export/powerpoint', json=body)
    assert deck.status_code == 200 and deck.headers['content-disposition'].endswith('.pptx"')
    assert len(Presentation(io.BytesIO(deck.content)).slides) > 1
    document = client.post('/api/non-qualified-calls/export/word', json=body)
    assert document.status_code == 200 and document.headers['content-disposition'].endswith('.docx"')
    assert Document(io.BytesIO(document.content)).paragraphs
    assert client.post('/api/non-qualified-calls/export/pdf', json=body).status_code == 404
