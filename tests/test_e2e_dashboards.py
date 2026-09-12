import json
from io import BytesIO
from pathlib import Path

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


def test_dashboards_lifecycle_and_layout(client):
    payload = setup_dashboard(client)
    page = client.get('/e2e-dashboards')
    assert page.status_code == 200
    assert page.text.index('>Datasets Analysis<') < page.text.index('>E2E Dashboards<') < page.text.index('>E2E Reporting<')
    assert client.get('/e2e-reporting').status_code == 200
    legacy_reporting = client.get('/reporting', follow_redirects=False)
    assert legacy_reporting.status_code == 307
    assert legacy_reporting.headers['location'] == '/e2e-reporting'
    assert 'id="ds-nr-mode"' in page.text
    assert 'id="ds-dashboards-body"' in page.text
    assert 'id="ds-library"' not in page.text
    assert 'id="ds-save"' in page.text
    assert '>Import Dashboard<' in page.text
    assert 'Total Dashboards: 0' in page.text
    assert '>Dashboard Data & Filters<' in page.text
    assert '>Default Filters<' in page.text
    assert '>Additional Filters<' in page.text
    assert 'id="ds-default-facets"' in page.text
    assert 'id="ds-additional-facets"' in page.text
    assert 'Select field to add new filter' in page.text
    assert 'id="ds-custom-field" multiple size="1" data-multiselect-single="true"' in page.text
    assert 'hidden_filters' in DashboardDefinition.model_fields
    assert 'slide_comments' in DashboardDefinition.model_fields
    assert 'id="ds-view" disabled' in page.text
    assert 'id="ds-preparing"' in page.text
    assert 'id="ds-preparing-title"' in page.text
    assert 'id="ds-viewer-preparing"' in page.text
    assert '>Auto-Calculated Fields<' in page.text
    assert 'class="ds-viewer-icon-action ds-viewer-refresh-action"' in page.text
    assert client.put('/api/e2e-dashboards/test', json=payload).status_code == 200
    assert client.get('/api/e2e-dashboards').json()['test']['name'] == 'Comparison'
    renamed = client.patch('/api/e2e-dashboards/test/name', json={'name': 'Renamed comparison'})
    assert renamed.status_code == 200
    assert renamed.json()['name'] == 'Renamed comparison'
    assert client.get('/api/e2e-dashboards').json()['test']['name'] == 'Renamed comparison'
    comments = client.patch('/api/e2e-dashboards/test/comments', json={'slide_comments': {'1': ['Review city outliers']}})
    assert comments.status_code == 200
    assert comments.json()['slide_comments'] == {'1': ['Review city outliers']}
    assert client.get('/api/e2e-dashboards').json()['test']['slide_comments'] == {'1': ['Review city outliers']}
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
    interactive = client.get(f'/api/e2e-dashboards/chart/{token}/0')
    assert interactive.status_code == 200, interactive.text
    assert interactive.json()['type'] == 'cdf'
    assert interactive.json()['renderer'] == 'catalog-v2'
    assert interactive.json()['series']
    assert list((Path(core.repository.db_path).parent / '.dashboard-chart-cache').glob('*.png'))
    entry = core.load_template_catalogue(next(row['content'] for row in core.repository.list_report_templates('nsa') if row['name'] == 'Dashboard test'), 'nsa')[0]
    assert not core.is_empty_catalog_chart(image.content, entry)
    data = client.get(f'/api/e2e-dashboards/data/{token}/0').json()
    assert data['total'] == 3
    assert client.get(f'/api/e2e-dashboards/data/{token}/0?download=true').headers['content-type'].startswith('text/csv')
    assert client.delete('/api/e2e-dashboards/test').status_code == 200
    assert client.get('/api/e2e-dashboards').json() == {}


def test_dashboard_preview_identifies_title_and_transition_slides(client):
    payload = setup_dashboard(client)
    core.repository.add_report_template('nsa', 'Structural dashboard', (
        'Slide,Slide tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Filters,Rows Aggregation,Column Aggregation,Legend,Legend Position\n'
        '1,Quarterly review,Network results,Title Page,,,,Title Slide,,,,,Top\n'
        '2,Voice performance,,Title Only,,,,Transition Slide,,,,,Top\n'
    ).encode(), is_default=False)
    payload['template'] = 'Structural dashboard'

    preview = client.post('/api/e2e-dashboards/prepare', json=payload)

    assert preview.status_code == 200, preview.text
    slides = preview.json()['slides']
    assert [(slide['title'], slide['structural_type'], slide['charts']) for slide in slides] == [
        ('Quarterly review', 'title slide', []),
        ('Voice performance', 'transition slide', []),
    ]


def test_dashboard_state_migrates_from_legacy_storage(client):
    payload = setup_dashboard(client)
    core.repository.set_workspace_state('e2e_dashboard_sets_v1', '{"legacy": ' + json.dumps(payload) + '}')
    result = client.get('/api/e2e-dashboards')
    assert result.status_code == 200
    assert result.json()['legacy']['name'] == 'Comparison'
    assert json.loads(core.repository.get_workspace_state('e2e_dashboards_v2')) == result.json()


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
    payload['filters'] = {'Test_Name': ['HTTP DL']}
    payload['custom_fields'] = ['Test_Name']
    preview = client.post('/api/e2e-dashboards/prepare', json=payload).json()
    assert 'Test_Name' in preview['available_fields']
    assert preview['options']['Test_Name'] == ['HTTP DL']
    payload['hidden_filters'] = ['Market']
    preview = client.post('/api/e2e-dashboards/prepare', json=payload).json()
    assert 'Market' not in preview['options']


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


def test_dashboard_sql_selection_preserves_voice_nr_mode_semantics(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    response = client.post('/datasets-analysis/upload', data={'dataset_kinds': 'voice'}, files={
        'dataset_files': ('voice.csv', BytesIO(
            b'Operator,Mean_Call_Setup_Time,RAT_A,Session_Type,L1_Call_Mode_A\n'
            b'A,1.0,EN-DC,WhatsApp Voice,\n'
            b'A,2.0,NR,WhatsApp Voice,\n'
            b'A,3.0,LTE,Native Voice,VoLTE\n'
            b'A,4.0,NR,Native Voice,VoNR\n'
        ), 'text/csv'),
    })
    assert response.status_code == 200
    core.repository.add_report_template('nsa', 'Voice Dashboard', (
        'Slide,Slide tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Filters,Rows Aggregation,Column Aggregation,Legend,Legend Position\n'
        '1,Voice,,Title and 1 column + Comments,Calls,CDR-Voice,Mean_Call_Setup_Time,CDF Line,,Operator,,,Top\n'
    ).encode(), is_default=False)
    payload = DashboardDefinition(
        name='Voice', template='Voice Dashboard', datasets={'voice': [1]}, technology='nsa',
    ).model_dump(mode='json')
    assert client.post('/api/e2e-dashboards/prepare', json=payload).json()['rows']['voice'] == 2
    payload['technology'] = 'sa'
    assert client.post('/api/e2e-dashboards/prepare', json=payload).json()['rows']['voice'] == 2


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
    assert client.get(f"/api/e2e-dashboards/chart/{preview['token']}/0").status_code == 403


def test_dashboard_reuses_persistent_sql_selection_and_invalidates_dataset_versions(client):
    payload = setup_dashboard(client)
    first = client.post('/api/e2e-dashboards/prepare', json=payload)
    assert first.status_code == 200
    with core.repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) AS count FROM dashboard_filter_selections').fetchone()['count'] == 1
    repeated = client.post('/api/e2e-dashboards/prepare', json=payload)
    assert repeated.status_code == 200
    assert repeated.json()['token'] != first.json()['token']
    with core.repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) AS count FROM dashboard_filter_selections').fetchone()['count'] == 1
    payload['name'] = 'Renamed comparison'
    assert client.post('/api/e2e-dashboards/prepare', json=payload).status_code == 200
    with core.repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) AS count FROM dashboard_filter_selections').fetchone()['count'] == 1
    payload['filters'] = {'City': ['London']}
    assert client.post('/api/e2e-dashboards/prepare', json=payload).json()['rows']['data'] == 2
    with core.repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) AS count FROM dashboard_filter_selections').fetchone()['count'] == 2
    core.repository.set_workspace_state('dashboard_cache_test', 'updated')
    assert client.post('/api/e2e-dashboards/prepare', json=payload).status_code == 200
    with core.repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) AS count FROM dashboard_filter_selections').fetchone()['count'] == 2
    core.repository.update_dataset_profile(1, progress=100)
    assert client.post('/api/e2e-dashboards/prepare', json=payload).status_code == 200
    with core.repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) AS count FROM dashboard_filter_selections').fetchone()['count'] == 3


def test_dashboard_large_selection_uses_direct_sql_predicate(client, monkeypatch):
    payload = setup_dashboard(client)
    import src.modules.e2e_dashboards as dashboards_module

    monkeypatch.setattr(dashboards_module, 'DASHBOARD_SELECTION_ROW_LIMIT', 1)
    preview = client.post('/api/e2e-dashboards/prepare', json=payload)
    assert preview.status_code == 200
    with core.repository.connection() as connection:
        selection = connection.execute(
            'SELECT id, materialized FROM dashboard_filter_selections ORDER BY id DESC LIMIT 1'
        ).fetchone()
        assert selection['materialized'] == 0
        assert connection.execute(
            'SELECT COUNT(*) AS count FROM dashboard_filter_selection_rows WHERE selection_id = ?',
            (selection['id'],),
        ).fetchone()['count'] == 0
    data = client.get(f"/api/e2e-dashboards/data/{preview.json()['token']}/0")
    assert data.status_code == 200
    assert data.json()['total'] == 3


def test_dashboard_reuses_normalized_snapshot_for_every_chart(client, monkeypatch):
    payload = setup_dashboard(client)
    import src.modules.e2e_dashboards as dashboards_module

    calls = []
    original = dashboards_module.normalise_report_operator_aliases

    def tracked(frame):
        calls.append(len(frame))
        return original(frame)

    monkeypatch.setattr(dashboards_module, 'normalise_report_operator_aliases', tracked)
    preview = client.post('/api/e2e-dashboards/prepare', json=payload).json()
    for index in (0, 1, 2):
        assert client.get(f"/api/e2e-dashboards/preview/{preview['token']}/{index}.png").status_code == 200
    assert calls == [3]
    assert client.get(f"/api/e2e-dashboards/preview/{preview['token']}/0.png").status_code == 200
    assert calls == [3]


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
