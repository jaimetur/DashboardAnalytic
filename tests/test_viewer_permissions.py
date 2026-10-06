import io

import pandas as pd
import pytest

import src.DriveTestAnalyzer as core


def _viewer(client, username='viewer', role='user-viewer'):
    core.repository.create_user(username, f'{username}123', role)
    user_id = next(int(row['id']) for row in core.repository.list_users() if row['username'] == username)
    core.repository.set_user_workspace_access(user_id, [core.active_workspace.id])
    client.cookies.clear()
    response = client.post('/login', data={'username': username, 'password': f'{username}123'}, follow_redirects=False)
    assert response.status_code == 303


def _ready_cdr(tmp_path):
    source = tmp_path / 'cdr.csv'
    source.write_text('Operator\nEE\n', encoding='utf-8')
    dataset_id, _ = core.repository.add_dataset('cdr.csv', str(source), 'admin')
    core.repository.replace_dataset_rows(dataset_id, pd.DataFrame({'Operator': ['EE']}))
    core.repository.update_dataset_profile(dataset_id, status='ready', progress=100, dataset_kind='data', nr_mode='NSA')
    return dataset_id


@pytest.mark.parametrize('method, path, kwargs', [
    ('post', '/datasets-analysis/upload', {'files': {'dataset_files': ('x.csv', io.BytesIO(b'a\n1\n'), 'text/csv')}}),
    ('post', '/datasets-analysis/delete/{id}', {}),
    ('post', '/datasets-analysis/retry/{id}', {}),
    ('post', '/dashboard/retry/{id}', {}),
    ('post', '/datasets-analysis/stop/{id}', {}),
    ('post', '/workspace/delete-datasets', {}),
    ('post', '/workspace/reprocess-datasets', {'data': {'dataset_ids': '{id}'}}),
    ('post', '/workspace/stop-datasets', {}),
    ('post', '/workspace/map-mappings', {'data': {'cdr_dataset_ids': '{id}', 'region_mapping_dataset_id': '1'}}),
    ('post', '/workspace/map-vendors', {'data': {'cdr_dataset_id': '{id}', 'three_mapping_dataset_id': '1'}}),
    ('post', '/workspace/map-regions', {'data': {'cdr_dataset_ids': '{id}', 'region_mapping_dataset_id': '1'}}),
    ('post', '/workspace/clear-mappings', {'data': {'cdr_dataset_ids': '{id}'}}),
    ('post', '/workspace/clear-regions', {'data': {'cdr_dataset_ids': '{id}'}}),
    ('post', '/workspace/clear-vendors', {'data': {'cdr_dataset_ids': '{id}'}}),
    ('post', '/workspace/datasets/{id}/nr-mode', {'json': {'nr_mode': 'SA'}}),
    ('post', '/workspace/combined/data/recreate', {}),
    ('post', '/api/workspace/auto-calculated-fields/rematerialize', {}),
    ('put', '/api/workspace/calculated-dimensions', {'json': {'dimensions': []}}),
    ('post', '/api/query-builder/save', {'json': {'name': 'q', 'query': 'SELECT 1'}}),
    ('delete', '/api/query-builder/saved/1', {}),
    ('delete', '/api/scoring/jobs/1', {}),
    ('put', '/api/e2e-dashboards/d1', {'json': {'name': 'D'}}),
    ('delete', '/api/e2e-dashboards/d1', {}),
    ('patch', '/api/e2e-dashboards/d1/name', {'json': {'name': 'D'}}),
    ('patch', '/api/e2e-dashboards/d1/comments', {'json': {'slide_comments': {}}}),
])
def test_user_viewer_cannot_change_the_workspace(client, tmp_path, method, path, kwargs):
    dataset_id = _ready_cdr(tmp_path)
    _viewer(client)
    path = path.replace('{id}', str(dataset_id))
    kwargs = {key: ({name: str(value).replace('{id}', str(dataset_id)) for name, value in item.items()} if key == 'data' else item)
              for key, item in kwargs.items()}
    response = getattr(client, method)(path, follow_redirects=False, **kwargs)
    assert response.status_code == 403, (path, response.status_code, response.text[:200])
    assert core.repository.get_dataset(dataset_id) is not None


def test_user_viewer_still_explores_and_generates_jobs(client, tmp_path):
    _ready_cdr(tmp_path)
    _viewer(client)
    assert client.get('/workspace').status_code == 200
    page = client.get('/e2e-dashboards')
    assert page.status_code == 200 and 'data-ds-manage-only' in page.text
    assert 'data-authenticated-role="user-viewer"' in page.text
    assert client.post('/api/scoring/jobs/match', json={}).status_code != 403
    # Editors keep changing the workspace.
    _viewer(client, 'editor', 'user-editor')
    assert client.post('/workspace/stop-datasets', follow_redirects=False).status_code != 403


def _features_form(rules):
    form = {}
    for key, rule in rules.items():
        form[f'default__{key}'] = rule.get('default', 'all')
        form[f'allow__{key}'] = rule.get('allow', [])
        form[f'deny__{key}'] = rule.get('deny', [])
    return form


def test_admins_grant_but_never_remove_features_of_super_admins(client):
    _viewer(client, 'boss', 'super-admin')
    boss_id = next(int(row['id']) for row in core.repository.list_users() if row['username'] == 'boss')
    _viewer(client, 'plainadmin', 'admin')
    assert 'Features Activation' in client.get('/admin').text
    base = {key: {'default': 'all'} for key in core.FEATURE_KEYS}
    base['reporting'] = {'default': 'none', 'allow': ['role:super-admin']}
    try:
        # Granting is allowed.
        response = client.post('/admin/features', data=_features_form({**base, 'reporting': {'default': 'none', 'allow': ['role:super-admin', 'role:admin']}}), follow_redirects=False)
        assert response.status_code == 303
        # Removing it from the super-admin role, a super-admin account or through "Nobody" is not.
        for change in ({'default': 'none'}, {'default': 'all', 'deny': ['role:super-admin']},
                       {'default': 'all', 'deny': [f'user:{boss_id}']}):
            response = client.post('/admin/features', data=_features_form({**base, 'reporting': change}), follow_redirects=False)
            assert response.status_code == 403 and 'cannot remove' in response.text
        assert core.user_has_feature(core.SessionUser(username='boss', role='super-admin'), 'reporting')
        # Admins still restrict their own and lower roles.
        response = client.post('/admin/features', data=_features_form({**base, 'builders': {'default': 'all', 'deny': ['role:user-viewer']}}), follow_redirects=False)
        assert response.status_code == 303
    finally:
        core.save_feature_activation_settings({key: {'default': 'all'} for key in core.FEATURE_KEYS})
