import json
import time
from io import BytesIO
from pathlib import Path
from threading import Event

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
    assert page.text.index('<th>Status</th>') < page.text.index('<th>Actions</th>')
    assert 'colspan="5" class="form-note">Loading Dashboards' in page.text
    assert 'id="ds-library"' not in page.text
    assert 'id="ds-save"' in page.text
    assert '>Save Filters<' in page.text
    assert page.text.index('id="ds-unsaved-filters-badge"') < page.text.index('id="ds-dashboard-name"')
    assert 'id="confirm-secondary"' in page.text
    assert '>Apply Filters<' in page.text
    assert page.text.index('>Apply Filters<') < page.text.index('>Save Filters<')
    assert 'id="ds-apply-filters" title="Apply current filters without saving them" disabled' in page.text
    assert 'id="ds-refresh"' not in page.text
    assert '>Import Dashboard<' in page.text
    assert 'Total Dashboards: 0' in page.text
    assert '>Dashboard Data & Filters<' in page.text
    assert '>Default Filters<' in page.text
    assert '>Additional Filters<' in page.text
    assert '>Clear Filters<' in page.text
    assert '>Reload Saved Filters<' in page.text
    assert 'id="ds-dashboard-name">Dashboard: —' in page.text
    assert 'title="Save and apply the current Dashboard filters"' in page.text
    assert 'title="Remove all filter restrictions and dates"' in page.text
    assert 'title="Restore CDR sources, scope, filters, additional fields and dates from the last saved Dashboard"' in page.text
    assert 'id="ds-preparing-rows"' in page.text
    assert 'class="form-note ds-filter-help"' in page.text
    assert 'id="ds-default-facets"' in page.text
    assert 'id="ds-additional-facets"' in page.text
    assert 'Select field to add new filter' in page.text
    assert 'id="ds-custom-field" multiple size="1" data-multiselect-single="true"' in page.text
    assert 'hidden_filters' in DashboardDefinition.model_fields
    assert 'slide_comments' in DashboardDefinition.model_fields
    assert 'id="ds-view" class="ds-view-dashboard-action" title="Open the Dashboard viewer" disabled' in page.text
    assert 'id="ds-preparing"' in page.text
    assert 'id="ds-preparing-title"' in page.text
    assert '>Preparing Dashboard data<' in page.text
    assert 'id="ds-viewer-preparing"' in page.text
    assert '>Auto-Calculated Fields<' in page.text
    assert 'class="ds-viewer-icon-action ds-viewer-refresh-action"' in page.text
    assert 'id="ds-chart-expanded-overlay"' in page.text
    assert 'id="ds-chart-expanded-canvas"' in page.text
    assert 'id="ds-chart-expanded-data"' in page.text
    assert 'id="ds-chart-expanded-zoom"' in page.text
    assert 'id="ds-chart-expanded-filters"' in page.text
    assert 'id="ds-chart-expanded-edit"' in page.text
    assert 'id="ds-chart-expanded-first"' in page.text
    assert 'id="ds-chart-expanded-last"' in page.text
    assert 'id="ds-chart-expanded-canvas-shell"' in page.text
    assert 'id="ds-chart-expanded-position"' in page.text
    assert 'class="ds-chart-expanded-footer"' in page.text
    assert 'id="ds-chart-expanded-controls"' in page.text
    assert 'id="ds-chart-expanded-controls"><button type="button" id="ds-chart-expanded-data"' in page.text
    assert 'ds-viewer-refresh-action' in page.text
    dashboard_script = (Path(__file__).parents[1] / 'src/web_interface/static/js/e2e_dashboards.js').read_text(encoding='utf-8')
    assert "controls.append(data, expand, zoom)" in dashboard_script
    assert "savedDefinition = definitionFingerprint(definition); dirty = false;" in dashboard_script
    assert "await warmDashboardModels();" not in dashboard_script
    assert "Rendering Dashboard Charts" in dashboard_script
    assert "overlay('ds-viewer', true); renderSlide();" in dashboard_script
    app_script = (Path(__file__).parents[1] / 'src/web_interface/static/js/app.js').read_text(encoding='utf-8')
    task_panel_start = app_script.index("const root = document.getElementById('background-task-panels');")
    task_listener = app_script.index("window.addEventListener('dashboard-analytic:background-task'")
    assert task_listener > task_panel_start
    assert "This Auto-calculated Field has unsaved changes. Close without saving them?" in app_script
    assert "overlay.addEventListener('click', (event) => { if (event.target === overlay) void requestFinish(); });" in app_script
    assert "window.parent.postMessage({type: 'dashboard-analytic:template-saved'}, window.location.origin);" in app_script
    assert "openTemplateEditor(expandedChart?.focus_row)" in dashboard_script
    assert "card.ondblclick = safe(async event =>" in dashboard_script
    assert "const syncExpandedChartNavigation" in dashboard_script
    assert "navigateExpandedChart(expandedCharts().length - 1)" in dashboard_script
    assert "expandedCanvasShell.classList.add('ds-hover')" in dashboard_script
    assert "`Chart ${index + 1} / ${charts.length}`" in dashboard_script
    assert "if (event.target === event.currentTarget) expandedChartOverlay(false);" in dashboard_script
    assert 'const closeOnOutsidePointer = (id, close) =>' in dashboard_script
    assert "closeOnOutsidePointer('ds-filter-overlay', closeFilters);" in dashboard_script
    assert "closeOnOutsidePointer('ds-editor-overlay', closeTemplateEditor);" in dashboard_script
    assert "const updateUnsavedFiltersBadge = () => { $('ds-unsaved-filters-badge').hidden = !hasUnsavedFilterChanges(); };" in dashboard_script
    assert "if (!$('ds-filter-overlay').hidden) await closeFilters();" in dashboard_script
    assert "This Dashboard has unsaved changes. Close Adaptative Filters without saving them?" not in dashboard_script
    assert "This Report Template has unsaved changes. Close the editor without saving them?" in dashboard_script
    assert 'const templateChanged = templateEditorSaved;' in dashboard_script
    assert 'if (templateChanged) await prepare();' in dashboard_script
    assert "event.data?.type === 'dashboard-analytic:template-saved'" in dashboard_script
    chart_script = (Path(__file__).parents[1] / 'src/web_interface/static/js/dashboard_charts.js').read_text(encoding='utf-8')
    assert 'function selectionStartAllowed(canvas, event)' in chart_script
    assert 'return logicalY >= 90;' in chart_script
    assert "canvas.classList.toggle('ds-chart-selection-blocked', !selectionStartAllowed(canvas, event));" in chart_script
    assert 'function applyDateBounds(bounds)' in dashboard_script
    assert "button.disabled = Boolean((minimum && value < minimum) || (maximum && value > maximum));" in dashboard_script
    assert 'applyDateBounds(payload.date_bounds)' in dashboard_script
    assert 'function datePicker(key, label)' in dashboard_script
    assert "previous.addEventListener('click', () => { month.setMonth(month.getMonth() - 1); render(); });" in dashboard_script
    assert "button.addEventListener('click', () => { input.value = iso; definition[key] = iso; wrapper.classList.toggle('ds-date-picker-unsaved', hasUnsavedDate(key)); menu.hidden = true; filterChanged(); });" in dashboard_script
    assert 'const current = (selected || available).filter(Boolean);' in dashboard_script
    assert "const hasUnsavedFilter = field => !sameFilterValues(definition?.filters?.[field], savedDashboardDefinition().filters?.[field]);" in dashboard_script
    assert "const hasUnsavedSource = kind => !sameFilterValues(definition?.datasets?.[kind], savedDashboardDefinition().datasets?.[kind]);" in dashboard_script
    assert "const hasUnsavedScope = () => String(definition?.scope || '') !== String(savedDashboardDefinition().scope || '');" in dashboard_script
    assert "const host = node('label', label, 'ds-source-filter')" in dashboard_script
    assert "facet.classList.toggle('ds-filter-unsaved', hasUnsavedFilter(field));" in dashboard_script
    assert "wrapper.classList.toggle('ds-date-picker-unsaved', hasUnsavedDate(key));" in dashboard_script
    assert 'savedDefinition = definitionFingerprint(definition); updateDirtyState(); sources(); facets(); library();' in dashboard_script
    assert 'await prepare();' in dashboard_script
    assert 'if (next.length === current.length && next.every(value => current.includes(value))) return;' in dashboard_script
    assert 'function filterChanged() {' in dashboard_script
    assert "status('Filter changes are ready to apply.');" in dashboard_script
    assert 'const cached = preparedPayloads.get(preparedPayloadKey(activeId, definitionFingerprint(definition)));' in dashboard_script
    assert 'if (preparing && cached && currentFilterState !== preparingFilterState)' in dashboard_script
    assert "status('Restored the previously prepared filters.');" in dashboard_script
    assert 'const preparedPayloadKey = (id, fingerprint) =>' in dashboard_script
    assert 'entries.push({fingerprint, token: payload.token});' in dashboard_script
    assert 'const selectionStateFingerprint = value =>' in dashboard_script
    assert 'appliedSelectionState = selectionStateFingerprint(definition);' in dashboard_script
    assert 'const needsDataPreparation = selectionStateFingerprint(definition) !== appliedSelectionState;' in dashboard_script
    assert "params.set('rendering_only', '1');" in dashboard_script
    assert "params.set('preparation_id', preparationToken);" in dashboard_script
    assert "dashboard_name: definition?.name || 'Dashboard'," in dashboard_script
    assert "let preparationToken = '';" in dashboard_script
    assert "window.dispatchEvent(new Event('dashboard-analytic:refresh-background-tasks'));" in dashboard_script
    dashboard_module = (Path(__file__).parents[1] / 'src/modules/e2e_dashboards.py').read_text(encoding='utf-8')
    assert "'dashboard_name': task['name']," in dashboard_module
    assert "'label': 'Rendering Dashboard Charts' if task.get('rendering_only') else 'Preparing Dashboard data'," in dashboard_module
    assert 'direct_preparation_tasks: dict[str, dict] = {}' in dashboard_module
    assert "preparation_id: str | None = None," in dashboard_module
    assert "'label': 'Rendering Dashboard Charts' if job['total'] else 'Preparing Dashboard data'," in dashboard_module
    assert "phase === 'rendering' ? 'Rendering Dashboard Charts' : 'Preparing Dashboard data'" in dashboard_script
    assert "if (preparingFilterState === requestedFilterState) return preparing;" in dashboard_script
    assert "if (backgroundPreparationToken === preparationToken) dismissPreparationStatus();" in dashboard_script
    assert "bind('ds-apply-filters', async () => {" in dashboard_script
    assert "if (!definition || filterStateFingerprint(definition) === appliedFilterState) return;" in dashboard_script
    assert "api(`/prepare${params.size ? `?${params}` : ''}`,'POST',definition,controller.signal)" in dashboard_script
    assert "window.dispatchEvent(new Event('dashboard-analytic:refresh-background-tasks'));" in dashboard_script
    assert "title: 'Unsaved Dashboard filters'" in dashboard_script
    assert "confirmLabel: 'Save Filters'" in dashboard_script
    assert "secondaryLabel: 'Discard'" in dashboard_script
    assert "window.location.assign(target.href);" in dashboard_script
    assert "$('ds-apply-filters').disabled = !definition || filterStateFingerprint(definition) === appliedFilterState || filterActionBusy;" in dashboard_script
    assert "const dashboardStatuses = new Map();" in dashboard_script
    assert "window.setInterval(refreshDashboardStatuses, 2000);" in dashboard_script
    assert "let previousDashboardName = '';" in app_script
    assert 'if (dashboardName && dashboardName !== previousDashboardName)' in app_script
    assert 'completedByWorkspace.forEach((entries) =>' in app_script
    assert 'entry.group.tasks.splice(Math.min(entry.position + offset, entry.group.tasks.length), 0, entry.task);' in app_script
    selection_key_source = dashboard_module[dashboard_module.index('def persistent_selection_key'):dashboard_module.index('def selected_date_bounds')]
    assert "'scope': definition.scope," not in selection_key_source
    assert "'schema': 4," in selection_key_source
    assert '{snapshot.selection_key}:{snapshot.definition.scope}:{entry_key}' in dashboard_module
    assert '{selection_key}:{candidate.scope}:{entry_key}' in dashboard_module
    assert "'rendering_only': rendering_only," in dashboard_module
    assert 'def materialize_selection(definition, task_repository, dimensions, selected_by_kind, fields, *, use_profile_options=False):' in dashboard_module
    assert 'use_profile_options=use_profile_options,' in dashboard_module
    dashboard_css = (Path(__file__).parents[1] / 'src/web_interface/static/css/e2e_dashboards.css').read_text(encoding='utf-8')
    assert '.e2e-dashboards .ds-unsaved-filters-badge' in dashboard_css
    assert '.e2e-dashboards .ds-dashboard-close::after' in dashboard_css
    assert '.e2e-dashboards .ds-dashboard-close{background:linear-gradient(135deg,#e5989b,#f2b8b9)' in dashboard_css
    assert '.e2e-dashboards .ds-dashboard-view{background:linear-gradient(145deg,#167957,#29ae7d)' in dashboard_css
    assert '.ds-dashboard-status-loading-data{border-color:#d3aa45;background:#fff1c9;color:#77570a}' in dashboard_css
    assert '.ds-dashboard-status-data-queued{border-color:#aaa3b2;background:#f0edf2;color:#655e6c}' in dashboard_css
    assert "d='M12 2v10'" in dashboard_css
    assert "bind('ds-viewer-refresh',prepare);" in dashboard_script
    assert 'async function restorePrepared(id) {' in dashboard_script
    assert 'const preparedPayloads = new Map();' in dashboard_script
    assert 'const inMemory = preparedPayloads.get(preparedPayloadKey(id, fingerprint));' in dashboard_script
    assert 'if (inMemory?.fingerprint === fingerprint) { applyPreparedPayload(inMemory.payload); return true; }' in dashboard_script
    assert "api(`/prefetched/${encodeURIComponent(id)}`)" in dashboard_script
    assert "api(`/prepared/${encodeURIComponent(cachedEntry.token)}`)" in dashboard_script
    assert 'if (!await restorePrepared(id)) await prepare();' in dashboard_script
    assert 'savedDefinition = definitionFingerprint(definition); updateDirtyState();\n    // Date defaults may be derived' in dashboard_script
    assert 'with the disabled Apply and Save buttons.\n    sources(); facets();' in dashboard_script
    assert "setPreparationState('preparing');" in dashboard_script
    assert "bind('ds-refresh',prepare);" not in dashboard_script
    assert 'const setPreparationRows = payload =>' in dashboard_script
    assert 'setPreparationRows(payload);' in dashboard_script
    assert 'setPreparationRows(prepared);' in dashboard_script
    assert "$('ds-preparing-rows').hidden = !$('ds-preparing-rows').textContent;" in dashboard_script
    assert "bind('ds-clear-filters', () => { definition.filters = {}; definition.date_from = definition.date_to = null; sources(); facets(); filterChanged(); });" in dashboard_script
    assert "bind('ds-last-saved-filters', () => {" in dashboard_script
    assert "definition.datasets = structuredClone(saved.datasets || {});" in dashboard_script
    assert "definition.scope = saved.scope || 'single';" in dashboard_script
    assert "definition.filters = structuredClone(saved.filters || {});" in dashboard_script
    assert "definition.custom_fields = structuredClone(saved.custom_fields || []);" in dashboard_script
    assert "definition.hidden_filters = structuredClone(saved.hidden_filters || []);" in dashboard_script
    dashboard_css = (Path(__file__).parents[1] / 'src/web_interface/static/css/e2e_dashboards.css').read_text(encoding='utf-8')
    assert '.ds-dashboard-status-ready{' in dashboard_css
    assert '.ds-dashboard-status-rendering{' in dashboard_css
    assert '.ds-chart-controls button:not(:disabled){cursor:pointer!important}' in dashboard_css
    assert '.ds-source-filter.ds-filter-unsaved select,.ds-source-filter.ds-filter-unsaved .multiselect-trigger' in dashboard_css
    assert '.ds-date-picker.ds-date-picker-unsaved>input,.ds-facet.ds-filter-unsaved .multiselect-trigger' in dashboard_css
    assert '.e2e-dashboards .ds-view-dashboard-action{margin-left:auto;' in dashboard_css
    assert '#ds-filter-float .ds-filter-help{margin:26px 0 5px}' in dashboard_css
    assert '#ds-filter-float .ds-data-panel>summary{pointer-events:none;cursor:default}' in dashboard_css
    assert "panel.querySelector('summary').tabIndex = -1;" in dashboard_script
    assert '.ds-chart-expanded-canvas.ds-hover .ds-chart-controls,.ds-chart-expanded-canvas:focus-within .ds-chart-controls{opacity:1;visibility:visible;transform:translateY(0);transition-delay:0s;pointer-events:auto}' in dashboard_css
    saved = client.put('/api/e2e-dashboards/test', json=payload)
    assert saved.status_code == 200
    assert saved.json()['definition']['hidden_filters'] == []
    assert saved.json()['definition']['slide_comments'] == {}
    listed = client.get('/api/e2e-dashboards')
    assert listed.json()['test']['name'] == 'Comparison'
    assert listed.headers['cache-control'] == 'no-store, max-age=0, must-revalidate'
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
    assert preview['date_bounds'] == {'min': '2026-09-01', 'max': '2026-09-03'}
    assert len(preview['slides']) == 2
    assert len(preview['slides'][0]['charts']) == 2
    assert preview['slides'][0]['charts'][0]['focus_row'] == 0
    assert preview['slides'][0]['charts'][1]['focus_row'] == 1
    assert preview['slides'][0]['charts'][0]['position'][0] < preview['slides'][0]['charts'][1]['position'][0]
    token = preview['token']
    restored = client.get(f'/api/e2e-dashboards/prepared/{token}')
    assert restored.status_code == 200
    assert restored.json() == preview
    image = client.get(f'/api/e2e-dashboards/preview/{token}/0.png')
    assert image.status_code == 200, image.text if image.status_code != 200 else ''
    assert image.content.startswith(b'\x89PNG')
    interactive = client.get(f'/api/e2e-dashboards/chart/{token}/0')
    assert interactive.status_code == 200, interactive.text
    assert interactive.json()['type'] == 'cdf'
    assert interactive.json()['renderer'] == 'catalog-v2'
    assert interactive.json()['series']
    assert list((Path(core.repository.db_path).parent / '.dashboard-data-cache' / 'charts-pil').glob('*.png'))
    entry = core.load_template_catalogue(next(row['content'] for row in core.repository.list_report_templates('nsa') if row['name'] == 'Dashboard test'), 'nsa')[0]
    assert not core.is_empty_catalog_chart(image.content, entry)
    data = client.get(f'/api/e2e-dashboards/data/{token}/0').json()
    assert data['total'] == 3
    assert client.get(f'/api/e2e-dashboards/data/{token}/0?download=true').headers['content-type'].startswith('text/csv')
    assert client.delete('/api/e2e-dashboards/test').status_code == 200
    assert client.get('/api/e2e-dashboards').json() == {}


def test_prefetched_dashboard_reuses_completed_server_snapshot(client):
    payload = setup_dashboard(client)
    dashboard_id = 'warmed-dashboard'
    saved = client.put(f'/api/e2e-dashboards/{dashboard_id}', json=payload)
    assert saved.status_code == 200

    deadline = time.monotonic() + 10
    response = client.get(f'/api/e2e-dashboards/prefetched/{dashboard_id}')
    while response.status_code == 409 and time.monotonic() < deadline:
        time.sleep(0.05)
        response = client.get(f'/api/e2e-dashboards/prefetched/{dashboard_id}')

    assert response.status_code == 200, response.text
    assert response.json()['slides']
    while time.monotonic() < deadline:
        groups = client.get('/api/background-tasks').json()['groups']
        if not any(
            task['id'] == f'dashboard-prefetch:{dashboard_id}'
            for group in groups for task in group['tasks']
        ):
            break
        time.sleep(0.05)
    manifests = list(
        (Path(core.repository.db_path).parent / '.dashboard-data-cache' / 'dashboard-previews').glob('*.json')
    )
    assert manifests


def test_applying_filters_queues_all_chart_models_and_reuses_previous_cache(client, monkeypatch):
    payload = setup_dashboard(client)
    import src.modules.e2e_dashboards as dashboards_module

    core.repository.set_workspace_state('e2e_dashboards_v2', json.dumps({'filtered-dashboard': payload}))
    uncached = client.get('/api/e2e-dashboards/statuses')
    assert uncached.status_code == 200
    assert uncached.json()['filtered-dashboard'] == {'state': 'not-cached', 'label': 'Not cached'}

    started = Event()
    release = Event()
    calls = []
    original = dashboards_module.catalog_chart_payload

    def tracked(*args, **kwargs):
        calls.append(1)
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(dashboards_module, 'catalog_chart_payload', tracked)
    response = client.post('/api/e2e-dashboards/prepare?dashboard_id=filtered-dashboard', json=payload)
    assert response.status_code == 200, response.text
    assert started.wait(5)
    try:
        groups = client.get('/api/background-tasks').json()['groups']
        tasks = [task for group in groups for task in group['tasks']]
        assert any(
            task['id'].startswith('dashboard-prefetch:filtered-dashboard:')
            and task['dashboard_name'] == 'Comparison'
            and task['label'] == 'Rendering Dashboard Charts'
            for task in tasks
        )
        assert client.get('/api/e2e-dashboards/statuses').json()['filtered-dashboard']['label'] == 'Rendering'
    finally:
        release.set()

    cache_dir = Path(core.repository.db_path).parent / '.dashboard-data-cache' / 'charts-canvas'
    deadline = time.monotonic() + 10
    while len(list(cache_dir.glob('*.json'))) < 3 and time.monotonic() < deadline:
        time.sleep(0.05)
    first_models = {path.name for path in cache_dir.glob('*.json')}
    assert len(first_models) == 3
    assert client.get('/api/e2e-dashboards/statuses').json()['filtered-dashboard'] == {
        'state': 'ready', 'label': 'Ready',
    }

    payload['filters'] = {'City': ['London']}
    filtered = client.post('/api/e2e-dashboards/prepare?dashboard_id=filtered-dashboard', json=payload)
    assert filtered.status_code == 200, filtered.text
    deadline = time.monotonic() + 10
    while len(list(cache_dir.glob('*.json'))) < 6 and time.monotonic() < deadline:
        time.sleep(0.05)
    filtered_models = {path.name for path in cache_dir.glob('*.json')}
    assert first_models < filtered_models

    payload['filters'] = {}
    calls_before_restore = len(calls)
    restored = client.post('/api/e2e-dashboards/prepare?dashboard_id=filtered-dashboard', json=payload)
    assert restored.status_code == 200, restored.text
    time.sleep(0.1)
    assert len(calls) == calls_before_restore
    assert {path.name for path in cache_dir.glob('*.json')} == filtered_models

    core.repository.update_dataset_profile(1, progress=100)
    assert client.get('/api/e2e-dashboards/statuses').json()['filtered-dashboard'] == {
        'state': 'data-needed', 'label': 'Data needed',
    }
    calls_before_revision = len(calls)
    refreshed = client.post('/api/e2e-dashboards/prepare?dashboard_id=filtered-dashboard', json=payload)
    assert refreshed.status_code == 200, refreshed.text
    deadline = time.monotonic() + 10
    while len(list(cache_dir.glob('*.json'))) < 9 and time.monotonic() < deadline:
        time.sleep(0.05)
    refreshed_models = {path.name for path in cache_dir.glob('*.json')}
    assert filtered_models < refreshed_models
    assert len(calls) == calls_before_revision + 3

    (cache_dir / next(iter(refreshed_models - filtered_models))).unlink()
    assert client.get('/api/e2e-dashboards/statuses').json()['filtered-dashboard'] == {
        'state': 'charts-needed', 'label': 'Charts needed',
    }


def test_dashboard_api_session_expires_on_application_process_restart(client):
    setup_dashboard(client)
    import src.DashboardAnalytic as app_module

    app_module.SESSIONS.clear()

    response = client.get('/api/e2e-dashboards', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/login'


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
    assert client.get(f"/api/e2e-dashboards/data/{preview['token']}/0").status_code == 410
    assert client.get(f"/api/e2e-dashboards/preview/{preview['token']}/0.png").status_code == 410
    assert client.get(f"/api/e2e-dashboards/chart/{preview['token']}/0").status_code == 410
    assert client.get(f"/api/e2e-dashboards/prepared/{preview['token']}").status_code == 410


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
    monkeypatch.setattr(dashboards_module, 'DASHBOARD_PROFILE_SELECTION_THRESHOLD', 1)
    payload['filters'] = {'City': ['London']}
    preview = client.post('/api/e2e-dashboards/prepare', json=payload)
    assert preview.status_code == 200
    assert preview.json()['rows']['data'] == 2
    assert preview.json()['rows_exact'] is True
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
    assert data.json()['total'] == 2


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


def test_dashboard_is_available_to_workspace_users(client):
    setup_dashboard(client)
    client.get('/logout')
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert client.get('/e2e-dashboards').status_code == 200
    assert client.get('/api/e2e-dashboards').status_code == 200
    assert client.put('/api/e2e-dashboards/test', json=definition().model_dump(mode='json')).status_code == 200
    assert 'href="/e2e-dashboards"' in client.get('/datasets-analysis').text
    client.get('/logout')
    client.post('/login', data={'username': 'demo', 'password': 'demo123'})
    assert client.get('/e2e-dashboards').status_code == 200
    assert 'href="/e2e-dashboards"' in client.get('/datasets-analysis').text
