"""E2E Dashboards and Reporting (old) are stored as PPT Dashboards and PPT Reporting (old)."""
import json
import sqlite3

from src.modules import ppt_naming


class _State:
    def __init__(self, values):
        self.values = values

    def get_application_state(self, key):
        return self.values.get(key)

    def set_application_state(self, key, value):
        self.values[key] = value


def test_features_activation_and_interface_settings_follow_the_new_module_names():
    rule = {'default': 'none', 'allow': {'roles': ['super-admin']}}
    labels = {
        'e2e-dashboards': {'title': 'E2E Dashboards', 'short_title': 'Dashboards', 'tab_icon': 'e2e-dashboards', 'position': 2},
        'reporting-old': {'title': 'My old reports', 'short_title': 'Reporting (old)', 'tab_icon': 'reporting-old', 'position': 3},
        'scoring': {'title': 'Scoring & GAP Analysis'},
    }
    state = _State({'features': json.dumps({'e2e-dashboards': rule, 'reporting-old': rule}), 'labels': json.dumps(labels)})
    ppt_naming.migrate_application_state(state, ('features', 'labels', 'missing'))
    assert json.loads(state.values['features']) == {'ppt-dashboards': rule, 'ppt-reporting-old': rule}
    migrated = json.loads(state.values['labels'])
    assert set(migrated) == {'ppt-dashboards', 'ppt-reporting-old', 'scoring'}
    assert migrated['ppt-dashboards'] == {'title': 'PPT Dashboards', 'short_title': 'Dashboards', 'tab_icon': 'ppt-dashboards', 'position': 2}
    # A title chosen in Interface Settings is kept.
    assert migrated['ppt-reporting-old']['title'] == 'My old reports'
    assert migrated['ppt-reporting-old']['short_title'] == 'PPT Reporting (old)'
    assert migrated['ppt-reporting-old']['tab_icon'] == 'ppt-reporting-old'
    # Settings already migrated are left as they are, except a former title of the module.
    state.values['labels'] = json.dumps({**migrated, 'ppt-reporting-old': {
        **migrated['ppt-reporting-old'], 'title': 'E2E Reporting', 'short_title': 'E2E Reporting'}})
    ppt_naming.migrate_application_state(state, ('labels',))
    assert {field: json.loads(state.values['labels'])['ppt-reporting-old'][field] for field in ('title', 'short_title')} == {
        'title': 'PPT Reporting (old)', 'short_title': 'PPT Reporting (old)'}
    before = dict(state.values)
    ppt_naming.migrate_application_state(state, ('features', 'labels'))
    assert state.values == before


def test_the_dashboards_of_a_workspace_keep_their_definitions(tmp_path):
    database = tmp_path / 'workspace.db'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE workspace_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        connection.executemany('INSERT INTO workspace_state VALUES (?, ?)', [
            ('e2e_dashboards_v2', '{"a": {"name": "NetCheck CDR Report"}}'),
            ('e2e_dashboard_default_filters_v6', '1'),
            ('campaign_map', '{}'),
        ])
    ppt_naming.migrate_workspace_database(database)
    with sqlite3.connect(database) as connection:
        stored = dict(connection.execute('SELECT key, value FROM workspace_state').fetchall())
    assert stored == {'ppt_dashboards_v2': '{"a": {"name": "NetCheck CDR Report"}}',
                      'ppt_dashboard_default_filters_v6': '1', 'campaign_map': '{}'}
    # A missing database, or one without the table, is left untouched.
    ppt_naming.migrate_workspace_database(tmp_path / 'missing.db')
    assert not (tmp_path / 'missing.db').exists()
