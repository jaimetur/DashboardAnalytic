"""Reset Application: super-admins delete every database, workspace and the config and data folders."""

import src.DriveTestAnalyzer as app_module
from src.config import settings


def login(client, username='super', password='super123'):
    client.cookies.clear()
    response = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert response.status_code == 303


def test_only_super_admins_see_and_use_reset_application(client):
    login(client, 'admin', 'admin123')
    assert 'data-app-reset-open' not in client.get('/admin').text
    response = client.post('/admin/reset-application', data={'confirmation': 'RESET APPLICATION'}, follow_redirects=False)
    assert response.status_code == 403

    login(client)
    page = client.get('/admin').text
    assert 'data-app-reset-open' in page and 'data-app-reset-dialog' in page
    assert str(app_module.application_data_dir.resolve()) in page
    # Without the exact confirmation phrase nothing is deleted.
    marker = app_module.application_config_dir / 'marker.txt'
    marker.write_text('kept', encoding='utf-8')
    assert client.post('/admin/reset-application', data={'confirmation': 'reset'}, follow_redirects=False).status_code == 400
    assert marker.exists()


def test_reset_application_starts_as_a_new_deployment(client):
    login(client)
    config_dir, data_dir = app_module.application_config_dir, app_module.application_data_dir
    assert client.post('/admin/users', data={
        'username': 'analyst', 'password': 'analyst123', 'role': 'user-editor', 'workspace_ids': 'default',
    }).status_code in {200, 303}
    (config_dir / 'marker.txt').write_text('gone', encoding='utf-8')
    (data_dir / 'scheduled-backups').mkdir(exist_ok=True)
    (data_dir / 'scheduled-backups' / 'drivetest-analyzer-backup-20260101-000000.zip').write_bytes(b'zip')
    (app_module.active_workspace.input_dir / 'UK_Voice.csv').write_text('x\n1\n', encoding='utf-8')
    templates = settings.ppt_templates_dir / 'Template_CDR_analysis.pptx'

    response = client.post('/admin/reset-application', data={'confirmation': 'RESET APPLICATION'}, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/login?reset=1'

    assert not (config_dir / 'marker.txt').exists() and not (data_dir / 'scheduled-backups').exists()
    assert not (app_module.active_workspace.input_dir / 'UK_Voice.csv').exists()
    # The shipped PowerPoint templates are never deleted.
    assert templates.exists()
    assert [workspace.name for workspace in app_module.workspace_registry.list()] == ['Default']
    assert sorted(row['username'] for row in app_module.repository.list_users()) == ['admin', 'demo', 'super']
    assert app_module.SESSIONS == {}
    assert 'The application was reset' in client.get('/login?reset=1').text
    login(client)
    assert client.get('/admin').status_code == 200
