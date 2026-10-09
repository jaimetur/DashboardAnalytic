"""A workspace starts with the Operator Maps of its country, or without Operator Maps."""
import re

import src.DriveTestAnalyzer as core
from src.modules import workspace_countries


def _operators():
    return {group['canonical']: group for group in core.repository.list_operator_mapping_groups()}


def test_the_operators_of_the_50_main_countries_are_shipped():
    countries = workspace_countries.countries()
    assert len(countries) == 50 and {'GBR', 'DEU', 'USA', 'CHN', 'IND', 'ESP'} <= set(countries)
    names = [item['name'] for item in countries.values()]
    assert names == sorted(names)
    for code, item in countries.items():
        spellings = [value.casefold() for operator in item['operators'] for value in (operator['canonical'], *operator['aliases'])]
        assert len(spellings) == len(set(spellings)), code
        assert all(re.fullmatch(r'#[0-9A-F]{6}', operator['color']) for operator in item['operators']), code
    # The United Kingdom keeps the labels of the NetCheck UK CDRs.
    assert [operator['canonical'] for operator in countries['GBR']['operators']] == ['EE', '3', 'VF', 'VF SA', 'VF VoNR', 'O2', 'Lebara']


def test_a_workspace_created_for_a_country_starts_with_its_operators(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    assert client.post('/workspace/create', data={'name': 'DE', 'cdr_type': 'netcheck', 'country': 'DEU'},
                       follow_redirects=False).status_code == 303
    assert workspace_countries.workspace_country(core.repository) == 'DEU'
    operators = _operators()
    assert list(operators) == ['Telekom', 'Vodafone', 'O2', '1&1']
    assert operators['Telekom']['color'] == '#E20074'
    # As NetCheck writes the operators of Germany.
    assert 'O2 - de' in operators['O2']['aliases']
    assert core.repository.list_operator_mappings()['o2 - de'] == 'O2'


def test_a_workspace_without_a_country_has_no_operators_until_one_is_chosen(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    client.post('/workspace/create', data={'name': 'Somewhere', 'cdr_type': 'netcheck'}, follow_redirects=False)
    workspace = core.active_workspace
    assert workspace.name == 'Somewhere' and _operators() == {}
    # A label of the workspace is kept; the other operators of the country are added.
    core.repository.replace_operator_mapping_group(None, 'Movistar', ['Telefónica España'], '#123456')
    saved = client.post('/workspace/save', data={'workspace_id': workspace.id, 'name': workspace.name, 'country': 'ESP'},
                        headers={'X-Requested-With': 'XMLHttpRequest'})
    assert saved.status_code == 200 and '5 operators' in saved.json()['notice']
    operators = _operators()
    assert operators['Movistar']['color'] == '#123456'
    assert list(operators) == ['Movistar', 'Vodafone', 'Orange', 'Yoigo', 'MásMóvil', 'Digi']
    assert client.post('/workspace/create', data={'name': 'Nowhere', 'country': 'XXX'}, follow_redirects=False).status_code == 303
    assert core.active_workspace.name == 'Somewhere'
