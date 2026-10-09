"""Values detected in the CDRs: their Operator, Vendor and Campaign labels and the warning while some are unassigned."""
import json

import pandas as pd
import pytest

import src.DriveTestAnalyzer as core
from src.modules.mapping_assignments import assignment_effects, assignment_rows, detected_values, unassigned_values
from src.modules.mapping_renames import count_saved_filters
from tests.test_non_qualified_calls import add_cdr, login, voice_rows, workspace_user


def test_detected_values_leave_operator_only_identities_out_of_the_vendors():
    catalogues = {
        1: {'operators': ['Vodafone SA', 'EE'], 'vendors_only': ['Ericsson', 'Vodafone SA - All', 'EE'], 'campaigns': ['UK_Q1_2026']},
        2: {'operators': ['vodafone sa'], 'vendors_only': ['Nokia'], 'campaigns': ['Xmas drive']},
    }
    detected = detected_values(catalogues, {1: 'CDR one.xlsx', 2: 'CDR two.xlsx'})
    assert detected['operator'] == {'Vodafone SA': ['CDR one.xlsx', 'CDR two.xlsx'], 'EE': ['CDR one.xlsx']}
    assert detected['vendor'] == {'Ericsson': ['CDR one.xlsx'], 'Nokia': ['CDR two.xlsx']}
    assert set(detected['campaign']) == {'UK_Q1_2026', 'Xmas drive'}


def test_rows_tell_unassigned_and_merged_values():
    detected = {'Vodafone SA': ['a'], 'Vodafone VoNR': ['a'], 'Vodafone UK': ['b'], 'Mystery': ['b']}
    mappings = {'vodafone sa': 'VF_SA', 'vodafone vonr': 'VF_SA', 'vodafone uk': 'VF', 'vf': 'VF', 'vf_sa': 'VF_SA'}
    rows = {row['value']: row for row in assignment_rows('operator', detected, mappings)}
    assert rows['Mystery'] == {'value': 'Mystery', 'cdrs': ['b'], 'label': 'Mystery', 'assigned': False,
                               'canonical': False, 'merged_with': []}
    assert rows['Vodafone SA']['merged_with'] == ['Vodafone VoNR'] and rows['Vodafone UK']['merged_with'] == []
    assert list(rows)[0] == 'Mystery'
    campaigns = assignment_rows('campaign', {'UK_Q2_2026': [], 'Xmas drive': [], 'Pilot run': []}, {},
                                {'format': '{year}-Q{quarter}', 'exceptions': [{'label': 'Pilot', 'sources': ['Pilot run']}]})
    assert unassigned_values({'operator': list(rows.values()), 'campaign': campaigns}) == {
        'operator': ['Mystery'], 'campaign': ['Xmas drive']}


def test_effects_list_merges_moved_values_and_labels_with_underscores():
    mappings = {'vodafone sa': 'VF_SA', 'vf_sa': 'VF_SA', 'vodafone vonr': 'VF_SA', 'vf': 'VF'}
    detected = ['Vodafone SA', 'Vodafone VoNR', 'Vodafone UK']
    effects = assignment_effects('operator', [('Vodafone VoNR', 'VF_VoNR'), ('Vodafone UK', 'vf_sa')], detected,
                                 mappings, ['VF_SA', 'VF'], saved_filters=lambda label: {'VF_SA': 2}.get(label, 0))
    assert effects['merges'] == [{'label': 'VF_SA', 'values': ['Vodafone SA', 'Vodafone UK']}]
    assert effects['moved'] == [{'value': 'Vodafone VoNR', 'from': 'VF_SA', 'to': 'VF_VoNR', 'filters': 2}]
    assert effects['underscores'] == ['VF_VoNR']
    # Renaming a group keeps its values: nothing merges or moves.
    renamed = assignment_effects('operator', [('VF-SA', 'VF-SA'), ('Vodafone SA', 'VF-SA'), ('Vodafone VoNR', 'VF-SA')],
                                 detected, mappings, ['VF_SA', 'VF'], rename=('VF_SA', 'VF-SA'))
    assert renamed == {'merges': [], 'moved': [], 'underscores': []}
    # Taking a source label out of a group leaves the value unassigned.
    removed = assignment_effects('operator', [('VF_SA', 'VF_SA'), ('Vodafone SA', 'VF_SA'), ('Vodafone VoNR', None)],
                                 detected, mappings, ['VF_SA', 'VF'])
    assert removed['moved'] == [{'value': 'Vodafone VoNR', 'from': 'VF_SA', 'to': None, 'filters': 0}]


def test_repository_assigns_values_to_existing_and_new_labels(client):
    repository = core.repository
    repository.replace_operator_mapping_group(None, 'VF_SA', ['Vodafone SA', 'Vodafone VoNR'])
    assert repository.assign_chart_mapping_sources('operator', [('Vodafone VoNR', 'VF_VoNR'), ('Mystery', 'ee'),
                                                                ('Vodafone SA', 'VF_SA')]) == 2
    mappings = repository.list_operator_mappings()
    assert mappings['vodafone vonr'] == 'VF_VoNR' and mappings['vf_vonr'] == 'VF_VoNR'
    assert mappings['mystery'] == 'EE' and mappings['vodafone sa'] == 'VF_SA'
    # A new label is a new group at the end of the table.
    assert repository.list_operator_mapping_groups()[-1]['canonical'] == 'VF_VoNR'
    with pytest.raises(ValueError, match='also one of the Operator labels'):
        repository.assign_chart_mapping_sources('operator', [('VF_SA', 'VF')])
    with pytest.raises(ValueError, match='name of the CDRs shown as VF'):
        repository.assign_chart_mapping_sources('operator', [('Vodafone SA', 'Vodafone UK')])
    # A refused assignment changes nothing.
    assert repository.list_operator_mappings()['vodafone sa'] == 'VF_SA'


def _cdr_with_unassigned_values(tmp_path):
    rows = voice_rows()
    rows['Operator'] = ['Vodafone SA', 'Vodafone VoNR', 'EE']
    rows['Vendor'] = ['Ericsson', 'Nokia', 'Ericsson']
    rows['Campaign'] = ['UK_Q1_2026', 'Xmas drive', 'UK_Q1_2026']
    dataset_id = add_cdr(tmp_path, 'NetCheck_UK_CDR_Voice_2026_Q1.xlsx', 'voice', rows)
    core.cache_cdr_catalogue(dataset_id, rows)
    return dataset_id


def test_unassigned_values_show_a_card_until_they_are_assigned(client, tmp_path):
    _cdr_with_unassigned_values(tmp_path)
    login(client)
    page = client.get('/workspace-config').text
    assert 'data-unassigned-values-card data-can-edit="1"' in page
    unassigned = json.loads(page.split('id="unassigned-mapping-values" type="application/json">')[1].split('</script>')[0])
    assert unassigned == {'operator': ['Vodafone SA', 'Vodafone VoNR'], 'vendor': ['Nokia'], 'campaign': ['Xmas drive']}
    assert 'id="operator-assignments"' in page and 'id="vendor-assignments"' in page
    assert client.get('/api/mapping-assignments/unassigned').json() == {'unassigned': unassigned, 'can_edit': True}

    preview = client.post('/api/workspace-config/operator-mappings/preview', json={'assignments': [
        {'value': 'Vodafone SA', 'label': 'VF_SA'}, {'value': 'Vodafone VoNR', 'label': 'VF_SA'}]}).json()
    assert preview['merges'] == [{'label': 'VF_SA', 'values': ['Vodafone SA', 'Vodafone VoNR']}]
    assert preview['underscores'] == ['VF_SA']

    response = client.post('/workspace-config/operator-mappings/assign', data={
        'source': ['Vodafone SA', 'Vodafone VoNR', 'EE'], 'label': ['VF_SA', 'VF_VoNR', 'EE']}, follow_redirects=False)
    assert response.status_code == 303 and '2+names+assigned' in response.headers['location']
    client.post('/workspace-config/vendor-mappings/assign', data={'source': ['Nokia'], 'label': ['Nokia']})
    client.put('/api/workspace-config/campaign-map', json={'campaign_map': {
        'format': '{year}-Q{quarter}{-mode}', 'exceptions': [{'label': 'Xmas', 'sources': ['Xmas drive']}]}})
    assert client.get('/api/mapping-assignments/unassigned').json()['unassigned'] == {}
    page = client.get('/workspace-config').text
    assert 'data-unassigned-values-card data-can-edit="1" role="alert" aria-label="Unassigned values in the CDRs" hidden' in page
    # The names of the CDRs stay listed with their label, chosen in a list of the labels.
    assert 'id="operator-assignments"' in page and 'Choose a label…' not in page
    assert '<option value="VF_VoNR" selected>VF_VoNR</option>' in page
    assert '"EE": ["NetCheck_UK_CDR_Voice_2026_Q1.xlsx"]' in page
    # Every module shows the values with their labels: the two Vodafone Operators stay apart.
    settings = core.repository.chart_mapping_settings()
    assert settings['operator_mappings']['vodafone sa'] == 'VF_SA' and settings['operator_mappings']['vodafone vonr'] == 'VF_VoNR'


def test_viewers_see_the_card_without_the_assignment_links(client, tmp_path):
    _cdr_with_unassigned_values(tmp_path)
    workspace_user('viewer', 'user-viewer')
    login(client, 'viewer', 'viewer123')
    page = client.get('/workspace').text
    assert 'data-unassigned-values-card data-can-edit="0"' in page
    assert client.get('/api/mapping-assignments/unassigned').json()['can_edit'] is False
    assert client.post('/workspace-config/operator-mappings/assign',
                       data={'source': ['Vodafone SA'], 'label': ['VF_SA']}).status_code == 403
    assert client.post('/api/workspace-config/operator-mappings/preview', json={'assignments': []}).status_code == 403


def test_moving_a_value_counts_the_saved_filters_of_its_label_without_changing_them(client, tmp_path):
    _cdr_with_unassigned_values(tmp_path)
    core.repository.replace_operator_mapping_group(None, 'VF_SA', ['Vodafone SA', 'Vodafone VoNR'])
    stored = json.dumps({'operator': ['VF_SA']})
    core.repository.set_workspace_state('nq_calls_filters', stored)
    assert count_saved_filters(core.repository, 'operator', 'VF_SA', core.repository.chart_mapping_settings()) == 1
    login(client)
    preview = client.post('/api/workspace-config/operator-mappings/preview', json={'assignments': [
        {'value': 'Vodafone VoNR', 'label': 'VF_VoNR'}]}).json()
    assert preview['moved'] == [{'value': 'Vodafone VoNR', 'from': 'VF_SA', 'to': 'VF_VoNR', 'filters': 1}]
    assert core.repository.get_workspace_state('nq_calls_filters') == stored
    # The campaign preview tells the unassigned campaigns.
    campaigns = client.post('/api/workspace-config/campaign-map/preview', json={'campaign_map': None}).json()['preview']
    assert {item['campaign']: item['assigned'] for item in campaigns} == {'UK_Q1_2026': True, 'Xmas drive': False}
