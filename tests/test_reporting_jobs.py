import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.DriveTestAnalyzer as core
from src.modules import report_tasks
from src.modules.report_tasks import (
    next_run_after, normalize_definition, normalize_schedule, recurrence_label, register_report_artifact_provider,
    safe_file_name,
)

TZ = timezone(timedelta(hours=2))


def login(client, username='super', password='super123'):
    client.cookies.clear()
    response = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert response.status_code == 303


def session(client, username, role):
    token = f'reporting-{username}-{role}'
    core.SESSIONS[token] = core.SessionUser(username=username, role=role)
    client.cookies.clear()
    client.cookies.set(core.SESSION_COOKIE, token)


def workspace_user(username, role):
    """A real account with access to the active workspace."""
    core.repository.create_user(username, f'{username}123', role)
    user_id = next(int(row['id']) for row in core.repository.list_users() if row['username'] == username)
    core.repository.set_user_workspace_access(user_id, [core.active_workspace.id])
    return user_id


def test_schedules_compute_the_next_execution():
    after = datetime(2026, 10, 5, 9, 30, tzinfo=TZ)  # A Monday.
    assert next_run_after(normalize_schedule({'mode': 'daily', 'time': '08:00'}), after) == datetime(2026, 10, 6, 8, 0, tzinfo=TZ)
    assert next_run_after(normalize_schedule({'mode': 'daily', 'time': '10:00'}), after) == datetime(2026, 10, 5, 10, 0, tzinfo=TZ)
    weekly = normalize_schedule({'mode': 'weekly', 'time': '08:00', 'weekdays': [0, 4]})
    assert next_run_after(weekly, after) == datetime(2026, 10, 9, 8, 0, tzinfo=TZ)
    # The last day of a shorter month replaces a missing day.
    monthly = normalize_schedule({'mode': 'monthly', 'time': '07:15', 'day_of_month': 31})
    assert next_run_after(monthly, datetime(2026, 11, 2, tzinfo=TZ)) == datetime(2026, 11, 30, 7, 15, tzinfo=TZ)
    once = normalize_schedule({'mode': 'once', 'date': '2026-10-05', 'time': '09:00'})
    assert next_run_after(once, after) is None
    assert next_run_after(normalize_schedule({'mode': 'manual'}), after) is None
    assert recurrence_label(weekly) == 'Weekly · Mon, Fri · 08:00'
    with pytest.raises(ValueError):
        normalize_schedule({'mode': 'weekly', 'time': '08:00', 'weekdays': []})
    with pytest.raises(ValueError):
        normalize_schedule({'mode': 'daily', 'time': '25:00'})


def test_definitions_keep_every_module_option_and_need_an_artifact():
    with pytest.raises(ValueError):
        normalize_definition({})
    definition = normalize_definition({
        'dashboards': [{'dashboard_id': 'd1', 'scope': 'multivendor', 'vendor_comparison': 'vendor_only',
                        'datasets': {'data': [3, '4']}, 'date_from': '2026-01-01',
                        'filters': {'Operator': ['EE', ''], 'RAT': []}}],
        'scoring': [{'nr_mode': 'sa', 'aggregation_levels': ['Campaign', 'Bogus'], 'context_filters': {'Vendor': ['Huawei']},
                     'main_cities': True}],
    })
    assert definition['dashboards'] == [{
        'dashboard_id': 'd1', 'label': '', 'scope': 'multivendor', 'vendor_comparison': 'vendor_only',
        'datasets': {'data': [3, 4]}, 'all_datasets': False, 'date_from': '2026-01-01', 'date_to': '', 'filters': {'Operator': ['EE']},
    }]
    scoring = definition['scoring'][0]
    assert (scoring['nr_mode'], scoring['aggregation_levels'], scoring['context_filters'], scoring['main_cities']) == (
        'SA', ['Operator', 'Campaign'], {'Vendor': ['Huawei']}, True)
    assert safe_file_name('Scoring: A/B ' + 'x' * 300 + '.pptx').endswith('.pptx')


def test_features_activation_controls_modules_by_role_group_and_user(client):
    analyst_id = workspace_user('analyst', 'user-viewer')
    login(client)
    # Defaults: Non-Qualified Calls hidden, Reporting (old) for its listed users, the rest for everyone.
    page = client.get('/workspace').text
    assert 'href="/reporting"' in page and 'href="/reporting-old"' in page
    assert 'href="/non-qualified-calls"' not in page
    order = [page.index(f'href="{path}"') for path in ('/datasets-analysis', '/network-insights', '/e2e-dashboards', '/scoring', '/reporting', '/reporting-old')]
    assert order == sorted(order)
    session(client, 'analyst', 'user-viewer')
    assert 'href="/reporting"' in client.get('/workspace').text
    assert client.get('/reporting').status_code == 200
    assert client.get('/scoring').status_code == 200
    # Rules saved with the former Reporting default (super-admins only) open Reporting to everyone once.
    core.repository.set_application_state(core.FEATURE_ACTIVATION_STATE_KEY, json.dumps({'reporting': core.LEGACY_REPORTING_RULE}))
    core._feature_activation_cache = None
    assert core.feature_activation_settings()['reporting']['default'] == 'all'
    # A user group activates Reporting for its members.
    login(client)
    assert client.post('/admin/user-groups', data={'name': 'Analysts', 'description': 'Team', 'member_ids': [analyst_id]},
                       follow_redirects=False).status_code == 303
    group_id = core.repository.list_user_groups()[0]['id']
    form = {f'default__{key}': 'all' for key in core.FEATURE_KEYS}
    form.update({'default__reporting': 'none', 'allow__reporting': [f'group:{group_id}'],
                 'default__scoring': 'none', 'allow__scoring': ['role:super-admin']})
    assert client.post('/admin/features', data=form, follow_redirects=False).status_code == 303
    session(client, 'analyst', 'user-viewer')
    assert client.get('/reporting').status_code == 200
    assert client.get('/scoring').status_code == 403
    # Forbidden wins over Allowed for an account in both lists.
    login(client)
    form['deny__reporting'] = [f'user:{analyst_id}']
    assert client.post('/admin/features', data=form, follow_redirects=False).status_code == 303
    session(client, 'analyst', 'user-viewer')
    assert client.get('/reporting').status_code == 403
    # Forbidden also restricts features active for all users.
    login(client)
    form.update({'deny__reporting': [], 'deny__workspace': ['role:user-viewer']})
    client.post('/admin/features', data=form)
    session(client, 'analyst', 'user-viewer')
    assert client.get('/workspace').status_code == 403
    assert client.get('/reporting').status_code == 200
    # Admins see Features Activation; viewers and editors do not.
    session(client, 'someone', 'admin')
    assert 'id="features-activation"' in client.get('/admin').text
    session(client, 'writer', 'user-editor')
    assert client.post('/admin/features', data=form).status_code == 403


def test_help_readme_and_changelog_are_public_except_reporting_old(client):
    client.cookies.clear()
    assert client.get('/documents/view/help').status_code == 200
    assert 'Sign in' in client.get('/documents/view/readme').text
    assert client.get('/api/documents/changelog').status_code == 200
    index = [item['relative_path'] for item in client.get('/api/documents/help-index').json()['documents']]
    assert 'reporting.md' in index and 'reporting-old.md' not in index
    assert client.get('/api/documents/help/reporting-old.md').status_code == 403
    assert 'reporting-old.md' not in client.get('/api/documents/help').json()['content']
    assert 'Email Delivery' in client.get('/api/documents/help/app-config.md').json()['content']
    login(client)
    index = [item['relative_path'] for item in client.get('/api/documents/help-index').json()['documents']]
    assert index.index('scoring-gap-analysis.md') < index.index('reporting.md') < index.index('reporting-old.md')
    assert client.get('/api/documents/help/reporting-old.md').status_code == 200


def test_email_delivery_settings_keep_the_saved_password(client):
    login(client)
    saved = client.post('/application-config/email-delivery', data={
        'host': 'smtp.example.com', 'port': '587', 'security': 'starttls', 'username': 'bot', 'password': 'secret',
        'from_address': 'reports@example.com', 'from_name': 'Reports', 'max_attachments_mb': '10',
    }, follow_redirects=False)
    assert saved.status_code == 303
    client.post('/application-config/email-delivery', data={
        'host': 'smtp.example.com', 'port': '465', 'security': 'ssl', 'username': 'bot', 'password': '',
        'from_address': 'reports@example.com', 'from_name': 'Reports', 'max_attachments_mb': '10',
    })
    settings = core.email_delivery_settings(core.repository, include_password=True)
    assert (settings['port'], settings['security'], settings['password'], settings['configured']) == (465, 'ssl', 'secret', True)
    page = client.get('/application-config').text
    assert 'Email Delivery' in page and 'secret' not in page
    invalid = client.post('/application-config/email-delivery', data={
        'host': 'smtp.example.com', 'port': '587', 'security': 'starttls', 'from_address': 'not-an-address', 'max_attachments_mb': '10',
    }, follow_redirects=False)
    assert 'error=' in invalid.headers['location']


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        FakeSMTP.sent.append(message)


def wait_for_run(client, run_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = next(item for item in client.get('/api/reporting/state').json()['runs'] if item['id'] == run_id)
        if run['status'] not in {'queued', 'running'}:
            return run
        time.sleep(0.1)
    raise AssertionError('The Reporting run did not finish.')


def test_reporting_job_runs_emails_and_travels_with_exports(client, monkeypatch, tmp_path):
    import smtplib

    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    FakeSMTP.sent = []

    def generate(config, folder, stamp, user):
        path = folder / f'{stamp} - Fake report.pptx'
        path.write_bytes(b'fake')
        return [{'module': 'fake', 'title': 'Fake report', 'file_name': path.name, 'size': 4, 'status': 'ready',
                 'details': ['Filter: everything']}]

    register_report_artifact_provider('fake', 'Fake module', 'datasets-analysis', generate)
    try:
        login(client)
        core.save_email_delivery_settings(core.repository, {
            'host': 'smtp.example.com', 'port': 587, 'security': 'starttls', 'from_address': 'reports@example.com',
            'max_attachments_mb': 10,
        }, keep_password=False)
        options = client.get('/api/reporting/options').json()
        assert any(provider['key'] == 'fake' for provider in options['providers'])
        payload = {
            'name': 'Weekly check', 'definition': {'modules': {'fake': {'enabled': True}}},
            'send_email': True, 'recipients': 'a@example.com; b@example.com',
            'schedule': {'mode': 'weekly', 'time': '08:00', 'weekdays': [0]}, 'enabled': True,
        }
        created = client.post('/api/reporting/tasks', json=payload)
        assert created.status_code == 200, created.text
        task = created.json()['task']
        assert task['recipients'] == ['a@example.com', 'b@example.com'] and task['next_run_at']
        assert client.post('/api/reporting/tasks', json={**payload, 'recipients': 'bad'}).status_code == 400
        run_id = client.post(f"/api/reporting/tasks/{task['id']}/run").json()['run_id']
        run = wait_for_run(client, run_id)
        assert run['status'] == 'sent', run
        message = FakeSMTP.sent[-1]
        assert message['To'] == 'a@example.com, b@example.com'
        body = message.get_body(('plain',)).get_content()
        assert 'Fake report' in body and 'Filter: everything' in body
        assert [part.get_filename() for part in message.iter_attachments()] == [run['artifacts'][0]['file_name']]
        assert client.get(f'/api/reporting/runs/{run_id}/download').status_code == 200
        state = client.get('/api/reporting/state').json()
        assert state['tasks'][0]['last_run']['id'] == run_id
        # Duplicates are disabled copies.
        copy = client.post(f"/api/reporting/tasks/{task['id']}/duplicate").json()['task']
        assert copy['name'] == 'Weekly check (copy)' and not copy['enabled'] and copy['next_run_at'] is None
        # Due jobs run once per schedule check.
        with core.repository.connection() as connection:
            connection.execute("UPDATE report_tasks SET next_run_at = ? WHERE id = ?",
                               ((datetime.now().astimezone() - timedelta(minutes=1)).isoformat(), task['id']))
        due = core.run_due_report_tasks()
        assert len(due) == 1 and core.run_due_report_tasks() == []
        wait_for_run(client, due[0])
        # Reporting Jobs travel with workspace packages.
        document = json.loads(report_tasks.export_tasks_document(core.repository))
        assert {item['name'] for item in document['reporting_jobs']} == {'Weekly check', 'Weekly check (copy)'}
        assert core._restore_workspace_reporting_jobs(core.active_workspace, json.dumps(document).encode()) == 2
        assert len(client.get('/api/reporting/state').json()['tasks']) == 2
        assert client.delete(f"/api/reporting/tasks/{copy['id']}").status_code == 200
    finally:
        report_tasks.ARTIFACT_PROVIDERS.pop('fake', None)


def test_reporting_jobs_only_include_modules_of_their_author(client):
    workspace_user('editor', 'user-editor')
    login(client, 'editor', 'editor123')
    core.save_feature_activation_settings({
        **{key: {'default': 'all'} for key in core.FEATURE_KEYS},
        'scoring': {'default': 'none', 'allow': {'roles': ['super-admin']}},
    })
    try:
        payload = {'name': 'Scoring only', 'definition': {'scoring': [{'nr_mode': 'NSA'}]}, 'schedule': {'mode': 'manual'}}
        response = client.post('/api/reporting/tasks', json=payload)
        assert response.status_code == 403
        assert 'Scoring' in response.json()['detail']
        assert client.get('/api/reporting/options').json()['allowed_modules']['scoring'] is False
    finally:
        core.save_feature_activation_settings({key: {'default': 'all'} for key in core.FEATURE_KEYS})


def test_feature_rules_saved_before_forbidden_lists_keep_their_meaning():
    rule = core.normalized_feature_rule({'mode': 'selected', 'roles': ['admin'], 'users': ['7']})
    assert rule == {'default': 'none', 'allow': {'roles': ['admin'], 'groups': [], 'users': [7]},
                    'deny': {'roles': [], 'groups': [], 'users': []}}
    assert core.normalized_feature_rule({'mode': 'all'})['default'] == 'all'
    defaults = core.normalized_feature_rule(None, core.FEATURE_DEFAULTS['reporting-old'])
    assert defaults['default'] == 'none' and defaults['allow_usernames'] == ['ejaitur']


def test_network_insights_entries_keep_their_own_selection_and_read_single_selections():
    definition = normalize_definition({'network_insights': [
        {'label': 'NSA LTE', 'formats': ['word'], 'selection': {'nr_mode': 'NSA', 'technology': 'lte', 'operators': ['EE']}},
        {'formats': ['powerpoint'], 'selection': {'nr_mode': 'sa', 'technology': 'nr', 'nr_coverage_threshold': -118}},
    ]})
    first, second = definition['network_insights']
    assert (first['label'], first['formats'], first['selection']['operators']) == ('NSA LTE', ['word'], ['EE'])
    assert (second['selection']['nr_mode'], second['selection']['technology'], second['selection']['nr_coverage_threshold']) == ('SA', 'nr', -118)
    assert report_tasks.network_entry_name(second) == 'SA NR'
    labels = report_tasks.artifact_labels(definition)
    assert 'Network Insights · NSA LTE (Word)' in labels and 'Network Insights · SA NR (PPT)' in labels
    # Jobs saved with one Network Insights selection keep it as one entry.
    legacy = normalize_definition({'network_insights': {'enabled': True, 'formats': ['word'], 'selection': {
        'technology': 'nr', 'coverage_threshold': -112, 'datasets': {'data': [5]}}}})
    assert len(legacy['network_insights']) == 1
    assert legacy['network_insights'][0]['selection']['nr_coverage_threshold'] == -112
    assert report_tasks._remap_dataset_ids(legacy, {5: 9})['network_insights'][0]['selection']['datasets'] == {'data': [9]}
    with pytest.raises(ValueError):
        normalize_definition({'network_insights': {'enabled': False, 'selection': {}}})


def test_dashboard_entries_can_use_every_ready_cdr_of_their_nr_mode():
    definition = normalize_definition({'dashboards': [{'dashboard_id': 'd1', 'all_datasets': True}]})
    assert definition['dashboards'][0]['all_datasets'] is True and definition['dashboards'][0]['datasets'] == {}


def test_reporting_runs_appear_in_background_tasks(client):
    login(client)
    task = client.post('/api/reporting/tasks', json={
        'name': 'Background check', 'definition': {'scoring': [{'nr_mode': 'NSA'}]}, 'schedule': {'mode': 'manual'},
    }).json()['task']
    report_tasks.create_run(core.repository, report_tasks.get_task(core.repository, task['id']), 'manual', 'super')
    groups = client.get('/api/background-tasks').json()
    labels = [item['label'] for group in (groups.get('workspaces') or groups.get('groups') or []) for item in group['tasks']] \
        if isinstance(groups, dict) else []
    assert any(label == 'Reporting Job: Background check' for label in labels) or 'Reporting Job: Background check' in json.dumps(groups)


def test_workspace_access_by_role_group_and_user(client):
    login(client)
    workspace_id = core.active_workspace.id
    core.repository.create_user('field', 'field123', 'user-viewer')
    field_id = next(int(row['id']) for row in core.repository.list_users() if row['username'] == 'field')
    assert not core.repository.user_has_workspace_access('field', workspace_id)
    # A role opens the workspace to every account with that role.
    assert client.post('/admin/workspace-access', data={f'access__{workspace_id}': ['role:user-viewer']},
                       follow_redirects=False).status_code == 303
    assert core.repository.user_has_workspace_access('field', workspace_id)
    assert 'id="workspace-access"' in client.get('/admin').text
    # A user group opens it to its members only.
    assert client.post('/admin/user-groups', data={'name': 'Field', 'description': '', 'member_ids': [field_id]},
                       follow_redirects=False).status_code == 303
    group_id = core.repository.list_user_groups()[0]['id']
    client.post('/admin/workspace-access', data={f'access__{workspace_id}': [f'group:{group_id}']}, follow_redirects=False)
    assert core.repository.workspace_access_rules()[workspace_id] == {'roles': [], 'groups': [group_id]}
    assert core.repository.user_has_workspace_access('field', workspace_id)
    # Users are the same direct grants as the Workspace Access picker of Workspace Management.
    client.post('/admin/workspace-access', data={f'access__{workspace_id}': [f'user:{field_id}']}, follow_redirects=False)
    assert workspace_id not in core.repository.workspace_access_rules()
    assert workspace_id in core.repository.list_user_workspace_ids(field_id)
    client.post('/admin/workspace-access', data={}, follow_redirects=False)
    assert not core.repository.user_has_workspace_access('field', workspace_id)
    # Workspace Management saves roles and groups with the workspace.
    name = core.active_workspace.name
    assert client.post('/workspace/save', data={'workspace_id': workspace_id, 'name': name, 'access_roles': ['user-viewer'],
                                                'access_groups': [group_id]}, follow_redirects=False).status_code == 303
    assert core.repository.workspace_access_rules()[workspace_id] == {'roles': ['user-viewer'], 'groups': [group_id]}


def test_users_table_assigns_groups_and_lists_workspaces_granted_by_groups(client):
    login(client)
    workspace = core.active_workspace
    core.repository.create_user('analyst', 'analyst123', 'user-viewer')
    analyst_id = next(int(row['id']) for row in core.repository.list_users() if row['username'] == 'analyst')
    group_id = core.repository.save_user_group(None, 'Analysts', '', [])
    core.repository.set_workspace_access_rule(workspace.id, [], [group_id])
    response = client.post(f'/admin/users/{analyst_id}/update', data={
        'username': 'analyst', 'role': 'user-viewer', 'active': '1', 'group_ids': [group_id], 'groups_submitted': '1',
    }, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 200, response.text
    assert response.json()['user']['group_ids'] == [group_id]
    assert core.repository.user_has_workspace_access('analyst', workspace.id)
    page = client.get('/admin').text
    assert '<th>Groups</th><th>Workspaces</th>' in page
    assert f'<span>{workspace.name} <small>· Analysts</small></span>' in page
    # A form without the group selector keeps the memberships.
    client.post(f'/admin/users/{analyst_id}/update', data={'username': 'analyst', 'role': 'user-viewer', 'active': '1'},
                headers={'X-Requested-With': 'XMLHttpRequest'})
    assert core.repository.list_user_groups()[0]['member_ids'] == [analyst_id]


def test_cdr_analysis_artifact_keeps_metrics_filters_and_single_choices():
    definition = report_tasks.normalize_definition({'dataset_analysis': {
        'enabled': True, 'formats': ['powerpoint'], 'metrics': {'data': ['Mean_Data_Rate'], 'voice': [], 'other': ['x']},
        'filters': {'operators': ['EE'], 'clusters': [], 'unknown': ['x']},
        'aggregation': 'vendor', 'cdf_grouping': 'nonsense',
    }})['dataset_analysis']
    assert definition['metrics'] == {'data': ['Mean_Data_Rate']} and definition['filters'] == {'operators': ['EE']}
    assert definition['aggregation'] == 'vendor' and definition['cdf_grouping'] == 'operator'


def test_reporting_options_list_cdr_analysis_metrics_per_cdr_type(client):
    login(client)
    options = client.get('/api/reporting/options').json()
    assert set(options['cdr_metrics']) == {'data', 'voice', 'speech'}
    assert options['cdr_kinds'] == {'data': 'CDR Data', 'voice': 'CDR Voice', 'speech': 'CDR Speech'}
    assert options['cdr_aggregations']['all'] == 'Auto' and options['cdr_cdf_groupings']['all'] == 'Single CDF'


def test_network_insights_grouping_keeps_operator_unless_vendor():
    entries = lambda group: report_tasks.normalize_definition(
        {'network_insights': [{'enabled': True, 'formats': ['powerpoint'], 'selection': {'group': group}}]})['network_insights']
    assert entries(['campaign'])[0]['selection']['group'] == ['operator', 'campaign']
    assert entries(['vendor', 'campaign'])[0]['selection']['group'] == ['vendor', 'campaign']


def test_reporting_options_list_filter_values_per_cdr(client):
    login(client)
    options = client.get('/api/reporting/options').json()
    assert isinstance(options['values_by_dataset'], dict)
    for values in options['values_by_dataset'].values():
        assert set(values) == {'Operator', 'Operator_Vendor', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign'}


def test_reporting_state_names_its_workspace_for_editor_drafts(client):
    login(client)
    assert client.get('/api/reporting/state').json()['workspace_id'] == core.active_workspace.id


def test_module_artifacts_always_include_a_document_with_their_excel():
    from src.modules import report_tasks

    register_report_artifact_provider('document_and_excel_test', 'Document Test', 'reporting', lambda *_args: [],
                                      formats=('powerpoint', 'word', 'excel'))
    try:
        only_excel = normalize_definition({'modules': {'document_and_excel_test': {'enabled': True, 'formats': ['excel']}}})
        assert only_excel['modules']['document_and_excel_test']['formats'] == ['powerpoint', 'excel']
        word_and_excel = normalize_definition({'modules': {'document_and_excel_test': {'enabled': True, 'formats': ['word', 'excel']}}})
        assert word_and_excel['modules']['document_and_excel_test']['formats'] == ['word', 'excel']
    finally:
        report_tasks.ARTIFACT_PROVIDERS.pop('document_and_excel_test', None)


def test_job_artifacts_are_grouped_by_module_with_their_entries():
    from src.modules import report_tasks

    groups = report_tasks.artifact_groups({
        'dataset_analysis': {'enabled': True, 'formats': ['powerpoint', 'word']},
        'network_insights': [{'nr_mode': 'NSA', 'technology': 'lte', 'formats': ['powerpoint']},
                             {'nr_mode': 'SA', 'technology': 'lte_nr', 'formats': ['word']}],
        'dashboards': [{'dashboard_id': 'd1', 'label': 'Main Cities'}],
        'scoring': [], 'modules': {},
    })
    assert [group['module'] for group in groups] == ['CDR Analysis', 'Network Insights', 'E2E Dashboards']
    assert groups[0]['items'] == ['(PPT/Word)']
    assert len(groups[1]['items']) == 2 and groups[1]['items'][1].endswith('(Word)')
    assert groups[2]['items'] == ['Main Cities (PPT)']
