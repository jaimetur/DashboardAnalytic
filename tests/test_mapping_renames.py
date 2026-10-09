"""Renaming an Operator or a Vendor in the Maps renames it in the Reporting Jobs and the saved filters."""
import json

import src.DriveTestAnalyzer as core
from src.modules import report_tasks
from src.modules.mapping_renames import rename_in_document, rename_in_query, value_renamer
from src.modules.scoring_reports import default_report_configuration

SETTINGS = {
    'operator_mapping_groups': [{'canonical': name, 'aliases': []} for name in ('EE', '3', 'VF_UK', 'VF_SA', 'O2')],
    'vendor_mapping_groups': [{'canonical': name, 'aliases': []} for name in ('Ericsson', 'Ericsson (Mixed)', 'Samsung')],
}


def login(client, username='super', password='super123'):
    client.cookies.clear()
    response = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert response.status_code == 303


def test_operator_and_vendor_renames_change_only_the_renamed_label():
    operator = value_renamer('operator', 'VF_UK', 'VF', SETTINGS)
    assert operator('operator', 'VF_UK') == 'VF'
    assert operator('operator', 'VF_SA') == 'VF_SA'
    assert operator('operator_vendor', 'VF_UK_Ericsson') == 'VF_Ericsson'
    assert operator('operator_vendor', 'VF_SA_Ericsson') == 'VF_SA_Ericsson'
    assert operator('vendor_operator', 'Ericsson (Mixed)_VF_UK') == 'Ericsson (Mixed)_VF'
    assert operator('vendor_operator', 'Samsung_VF_SA') == 'Samsung_VF_SA'
    assert operator('vendor', 'VF_UK - All') == 'VF - All'
    vendor = value_renamer('vendor', 'Ericsson', 'ERI', SETTINGS)
    assert vendor('vendor', 'Ericsson') == 'ERI'
    assert vendor('vendor', 'Ericsson (Mixed)') == 'Ericsson (Mixed)'
    assert vendor('operator_vendor', 'VF_UK_Ericsson') == 'VF_UK_ERI'
    assert vendor('operator_vendor', 'VF_UK_Ericsson (Mixed)') == 'VF_UK_Ericsson (Mixed)'
    assert vendor('vendor_operator', 'Ericsson_3') == 'ERI_3'
    assert vendor('operator', 'Ericsson') == 'Ericsson'
    # Only the filter fields change; other settings that name a field keep their value.
    document = {'context_filters': {'Operator': ['EE', 'VF_UK'], 'Vendor_Operator': ['Ericsson_VF_UK'], 'City': ['VF_UK']},
                'baseline_operator': 'VF_UK', 'gap': {'operators': ['VF_UK']}, 'aggregation': 'operator', 'name': 'VF_UK'}
    assert rename_in_document(document, operator) == {
        'context_filters': {'Operator': ['EE', 'VF'], 'Vendor_Operator': ['Ericsson_VF'], 'City': ['VF_UK']},
        'baseline_operator': 'VF', 'gap': {'operators': ['VF']}, 'aggregation': 'operator', 'name': 'VF_UK'}
    assert rename_in_query('dataset_id=3&operator=VF_UK&operator=EE&city=VF_UK', operator) == \
        'dataset_id=3&operator=VF&operator=EE&city=VF_UK'


def test_renaming_an_operator_in_the_maps_renames_it_in_jobs_and_saved_filters(client):
    login(client)
    repository = core.repository
    report = default_report_configuration(context_filters={'Operator': ['EE', 'VF']})
    task = report_tasks.save_task(repository, None, {'name': 'Weekly', 'definition': {
        'scoring': [{'nr_mode': 'NSA', 'baseline_operator': 'VF', 'report': report}],
        'network_insights': [{'selection': {'operators': ['VF'], 'vendor_operators': ['Ericsson_VF']}}],
    }}, 'super', parse_recipients=lambda value: [], invalid_recipients=lambda value: [])
    repository.set_workspace_state('scoring_report_configurations', json.dumps(
        {'configurations': [{'name': 'National', 'configuration': report}], 'last': report}))
    repository.set_workspace_state('nq_calls_filters', json.dumps({'operator_vendor': ['VF_Ericsson'], 'city': ['VF']}))

    response = client.post('/workspace-config/operator-mappings/save', data={
        'original_canonical': 'VF', 'canonical_value': 'VF_UK', 'aliases': 'VF\nVodafone UK'}, follow_redirects=False)
    assert response.status_code == 303

    saved = report_tasks.get_task(repository, task['id'])
    scoring = saved['definition']['scoring'][0]
    assert scoring['baseline_operator'] == 'VF_UK'
    assert scoring['report']['scenarios'][0]['context_filters']['Operator'] == ['EE', 'VF_UK']
    selection = saved['definition']['network_insights'][0]['selection']
    assert (selection['operators'], selection['vendor_operators']) == (['VF_UK'], ['Ericsson_VF_UK'])
    # The job is saved again, so a Job Editor draft of its previous version is not restored.
    assert saved['updated_at'] != task['updated_at']
    configurations = json.loads(repository.get_workspace_state('scoring_report_configurations'))
    assert configurations['configurations'][0]['configuration']['scenarios'][0]['context_filters']['Operator'] == ['EE', 'VF_UK']
    assert configurations['last']['scenarios'][0]['context_filters']['Operator'] == ['EE', 'VF_UK']
    assert json.loads(repository.get_workspace_state('nq_calls_filters')) == {'operator_vendor': ['VF_UK_Ericsson'], 'city': ['VF']}


def test_job_editor_drafts_of_a_changed_job_are_discarded_and_close_is_labelled():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = (root / 'src/web_interface/static/js/report_jobs.js').read_text(encoding='utf-8')
    # The draft keeps the version of the job it was made from; a newer saved job is opened instead.
    assert 'editingUpdatedAt = task?.updated_at' in script
    assert 'if (task && draft.editingUpdatedAt !== task.updated_at) {' in script
    template = (root / 'src/web_interface/templates/report_jobs.html').read_text(encoding='utf-8')
    assert 'id="rj-editor-close"' in template and '<span>Close</span></button>' in template


def test_mixed_vendor_groups_are_stored_with_their_interface_labels(tmp_path):
    import sqlite3

    from src.modules.repository import SCHEMA, Repository

    database_path = tmp_path / 'workspace.db'
    repository = Repository(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        connection.execute('CREATE TABLE dataset_rows_1 (Operator TEXT, Operator_Vendor TEXT, Vendor TEXT, Vendor_Operator TEXT, Note TEXT)')
        connection.execute("INSERT INTO dataset_rows_1 VALUES ('3', '3_Ericsson_Mixed', 'Ericsson_Mixed', 'Ericsson_Mixed_3', 'Ericsson_Mixed')")
        connection.execute("INSERT INTO dataset_rows_1 VALUES ('VF', 'VF_Non-Ericsson_Mixed', 'Non-Ericsson_Mixed', 'Non-Ericsson_Mixed_VF', '')")
        connection.executemany('INSERT INTO vendor_mappings (source_value, canonical_value) VALUES (?, ?)', [
            ('Ericsson_Mixed', 'Ericsson_Mixed'), ('Non-Ericsson_Mixed', 'Non-Ericsson_Mixed'), ('Mixed', 'Non-Ericsson_Mixed'),
        ])
        connection.execute("INSERT INTO chart_mapping_groups (mapping_type, canonical_value, position, color) VALUES ('vendor', 'Non-Ericsson_Mixed', 5, '#B9770E')")
        template = b'Vendor,Filter\nVendor,Vendor NOT IN (Non-Ericsson_Mixed, Ericsson_Mixed)\n'
        connection.execute("INSERT INTO report_templates (technology, name, content, is_default) VALUES ('sa', 'Template', ?, 1)", (template,))
        connection.execute(
            "INSERT INTO workspace_state (key, value) VALUES ('nq_calls_filters', ?)",
            (json.dumps({'vendor': ['Ericsson_Mixed', 'Non-Ericsson_Mixed']}),),
        )

        repository._rename_mixed_vendor_labels(connection)

        rows = [tuple(row) for row in connection.execute('SELECT Operator_Vendor, Vendor, Vendor_Operator, Note FROM dataset_rows_1')]
        # CDR rows change in their vendor fields only.
        assert rows == [('3_Ericsson (Mixed)', 'Ericsson (Mixed)', 'Ericsson (Mixed)_3', 'Ericsson_Mixed'),
                        ('VF_Mixed (non-Ericsson)', 'Mixed (non-Ericsson)', 'Mixed (non-Ericsson)_VF', '')]
        assert dict(connection.execute('SELECT source_value, canonical_value FROM vendor_mappings').fetchall()) == {
            'Ericsson (Mixed)': 'Ericsson (Mixed)', 'Mixed (non-Ericsson)': 'Mixed (non-Ericsson)', 'Mixed': 'Mixed (non-Ericsson)'}
        assert [tuple(row) for row in connection.execute('SELECT canonical_value, position FROM chart_mapping_groups')] == [
            ('Mixed (non-Ericsson)', 5)]
        stored = connection.execute('SELECT content FROM report_templates').fetchone()[0]
        assert isinstance(stored, bytes) and stored == b'Vendor,Filter\nVendor,Vendor NOT IN (Mixed (non-Ericsson), Ericsson (Mixed))\n'
        assert json.loads(connection.execute("SELECT value FROM workspace_state WHERE key = 'nq_calls_filters'").fetchone()[0]) == {
            'vendor': ['Ericsson (Mixed)', 'Mixed (non-Ericsson)']}
        # Once per workspace.
        assert connection.execute("SELECT value FROM workspace_state WHERE key = 'vendor_mixed_labels_v3'").fetchone()[0] == '1'
