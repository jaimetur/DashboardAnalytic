from io import BytesIO

import pandas as pd

import src.DashboardAnalytic as core
from src.modules.e2e_dashboards import DashboardDefinition, filter_frame


def definition(**changes):
    return DashboardDefinition(name='Comparison', template='Dashboard test', datasets={'data': [1]}, **changes)


def setup_dashboard(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    response = client.post('/datasets-analysis/upload', data={'dataset_kinds': 'data'}, files={
        'dataset_files': ('sample.csv', BytesIO(b'Operator,City,Mean_Data_Rate,Test_Name,Test_Start_Time\nA,London,10,HTTP DL,2026-09-01\nB,Leeds,20,HTTP DL,2026-09-02\nA,London,30,HTTP DL,2026-09-03\n'), 'text/csv'),
    })
    assert response.status_code == 200
    core.repository.add_report_template('nsa', 'Dashboard test', (
        'Slide,Slide tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Filters,Rows Aggregation,Column Aggregation,Legend,Legend Position\n'
        '1,Comparison,,Title and 2 columns + Comments,Rate,CDR-Data,Mean_Data_Rate,CDF Line,,Operator,,,Top\n'
        '1,Comparison,,Title and 2 columns + Comments,Rate again,CDR-Data,Mean_Data_Rate,CDF Line,,Operator,,,Top\n'
        '2,Next,,Title and 1 column + Comments,Rate next,CDR-Data,Mean_Data_Rate,CDF Line,,Operator,,,Top\n'
    ).encode(), is_default=False)
    return definition().model_dump(mode='json')


def test_filter_empty_missing_and_inclusive_dates():
    frame = pd.DataFrame({'City': ['London', 'Leeds'], 'Test_Start_Time': ['2026-09-01 23:59', '2026-09-02']})
    assert filter_frame(frame, definition(filters={'City': []})).empty
    assert filter_frame(frame, definition(filters={'Missing': ['Yes']})).empty
    assert len(filter_frame(frame, definition(date_from='2026-09-01', date_to='2026-09-01'))) == 1
    assert len(filter_frame(frame, definition(filters={'city': ['London']}))) == 1
    radio = pd.DataFrame({'RAT_A': ['LTE', 'NR'], 'technology_primary': ['4G', '5G']})
    assert len(filter_frame(radio, definition(filters={'RAT': ['NR'], 'Technology': ['5G']}))) == 1


def test_dashboard_sets_lifecycle_and_layout(client):
    payload = setup_dashboard(client)
    page = client.get('/e2e-dashboards')
    assert page.status_code == 200
    assert page.text.index('>Datasets Analysis<') < page.text.index('>E2E Dashboards<') < page.text.index('>E2E Reporting<')
    assert 'id="ds-nr-mode"' in page.text
    assert 'id="ds-sets-body"' in page.text
    assert 'id="ds-library"' not in page.text
    assert 'id="ds-save"' in page.text
    assert '>Import Dashboard Set<' in page.text
    assert client.put('/api/e2e-dashboards/test', json=payload).status_code == 200
    assert client.get('/api/e2e-dashboards').json()['test']['name'] == 'Comparison'
    result = client.post('/api/e2e-dashboards/prepare', json=payload)
    assert result.status_code == 200, result.text
    preview = result.json()
    assert preview['filter_fields'] == ['Market', 'Operator', 'Vendor', 'Region', 'City', 'Session Type', 'Technology', 'RAT']
    assert preview['options']['Operator'] == ['A', 'B']
    assert preview['options']['City'] == ['Leeds', 'London']
    assert len(preview['slides']) == 2
    assert len(preview['slides'][0]['charts']) == 2
    assert preview['slides'][0]['charts'][0]['position'][0] < preview['slides'][0]['charts'][1]['position'][0]
    token = preview['token']
    image = client.get(f'/api/e2e-dashboards/preview/{token}/0.png')
    assert image.status_code == 200, image.text if image.status_code != 200 else ''
    assert image.content.startswith(b'\x89PNG')
    entry = core.load_template_catalogue(next(row['content'] for row in core.repository.list_report_templates('nsa') if row['name'] == 'Dashboard test'), 'nsa')[0]
    assert not core.is_empty_catalog_chart(image.content, entry)
    data = client.get(f'/api/e2e-dashboards/data/{token}/0').json()
    assert data['total'] == 3
    assert client.get(f'/api/e2e-dashboards/data/{token}/0?download=true').headers['content-type'].startswith('text/csv')
    assert client.delete('/api/e2e-dashboards/test').status_code == 200
    assert client.get('/api/e2e-dashboards').json() == {}


def test_dashboard_custom_fields_and_snapshot_filters(client):
    payload = setup_dashboard(client)
    core.write_workspace_calculated_dimensions([{'name': '7-cities', 'sources': ['cdr-data'], 'rules': [{'when': 'City IN (London)', 'value': 'Yes'}], 'default': 'No'}])
    payload['custom_fields'] = ['7-cities']
    preview = client.post('/api/e2e-dashboards/prepare', json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()['options']['7-cities'] == ['No', 'Yes']
    original = preview.json()['token']
    payload['filters'] = {'7-cities': ['Yes']}
    preview = client.post('/api/e2e-dashboards/prepare', json=payload).json()
    assert preview['rows']['data'] == 2
    assert preview['options']['7-cities'] == ['No', 'Yes']
    for index in (0, 1, 2):
        assert client.get(f"/api/e2e-dashboards/data/{preview['token']}/{index}").json()['total'] == 2
    assert client.get(f'/api/e2e-dashboards/data/{original}/0').json()['total'] == 3
    payload['filters'] = {'7-cities': []}
    assert client.post('/api/e2e-dashboards/prepare', json=payload).json()['rows']['data'] == 0


def test_dashboard_validates_template_dates_and_sources(client):
    payload = setup_dashboard(client)
    payload['date_from'], payload['date_to'] = '2026-09-03', '2026-09-01'
    assert client.post('/api/e2e-dashboards/prepare', json=payload).status_code == 400
    payload['date_from'] = payload['date_to'] = None
    payload['datasets'] = {}
    assert client.post('/api/e2e-dashboards/prepare', json=payload).status_code == 400
    payload['template'] = 'Unknown'
    assert client.put('/api/e2e-dashboards/test', json=payload).status_code == 400
    assert client.get('/api/e2e-dashboards/data/missing/0').status_code == 410


def test_dashboard_snapshot_access_and_legacy_redirect(client):
    payload = setup_dashboard(client)
    response = client.get('/dashboard?dataset_id=1', follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == '/datasets-analysis?dataset_id=1'
    assert client.get(response.headers['location']).status_code == 200
    preview = client.post('/api/e2e-dashboards/prepare', json=payload).json()
    client.get('/logout')
    client.post('/login', data={'username': 'demo', 'password': 'demo123'})
    assert client.get(f"/api/e2e-dashboards/data/{preview['token']}/0").status_code == 403
    assert client.get(f"/api/e2e-dashboards/preview/{preview['token']}/0.png").status_code == 403


def test_dashboard_reuses_sources_and_invalidates_database_edits(client, monkeypatch):
    payload = setup_dashboard(client)
    from src.modules.repository import Repository
    loads = []
    original = Repository.load_reporting_rows

    def tracked(self, *args, **kwargs):
        loads.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Repository, 'load_reporting_rows', tracked)
    first = client.post('/api/e2e-dashboards/prepare', json=payload)
    assert first.status_code == 200
    payload['filters'] = {'City': ['London']}
    assert client.post('/api/e2e-dashboards/prepare', json=payload).json()['rows']['data'] == 2
    assert len(loads) == 1
    core.repository.set_workspace_state('dashboard_cache_test', 'updated')
    assert client.post('/api/e2e-dashboards/prepare', json=payload).status_code == 200
    assert len(loads) == 2


def test_dashboard_is_restricted_to_super_admins_and_ejaitur(client):
    setup_dashboard(client)
    assert 'href="/e2e-dashboards"' in client.get('/datasets-analysis').text
    client.get('/logout')
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert client.get('/api/e2e-dashboards').status_code == 403
    assert client.put('/api/e2e-dashboards/test', json=definition().model_dump(mode='json')).status_code == 403
    assert 'href="/e2e-dashboards"' not in client.get('/datasets-analysis').text
    core.repository.create_user('EJAITUR', 'ejaitur123', 'admin')
    core.repository.set_workspace_user_access(core.active_workspace.id, ['super', 'admin', 'demo', 'EJAITUR'])
    client.get('/logout')
    client.post('/login', data={'username': 'EJAITUR', 'password': 'ejaitur123'})
    assert client.get('/e2e-dashboards').status_code == 200
    assert 'href="/e2e-dashboards"' in client.get('/datasets-analysis').text
