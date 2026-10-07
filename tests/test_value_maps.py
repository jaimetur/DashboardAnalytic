"""Mapped Operator, Vendor, Operator_Vendor and Vendor_Operator values shown and filtered everywhere."""
from src.modules.mapping_order import dimension_order_key, swap_operator_vendor, swap_vendor_operator
from src.modules.value_maps import ValueMapper, field_kind

OPERATORS = [
    {'canonical': 'VF', 'aliases': ['Vodafone UK', 'Vodafone', 'VF_SA'], 'position': 0},
    {'canonical': '3', 'aliases': ['Three UK'], 'position': 1},
    {'canonical': 'EE', 'aliases': [], 'position': 2},
]
VENDORS = [
    {'canonical': 'Ericsson', 'aliases': ['ERIC'], 'position': 0},
    {'canonical': 'Nokia', 'aliases': ['NSN'], 'position': 1},
]


def mapper():
    operator_mappings = {alias.casefold(): group['canonical'] for group in OPERATORS
                         for alias in [group['canonical'], *group['aliases']]}
    vendor_mappings = {alias.casefold(): group['canonical'] for group in VENDORS
                       for alias in [group['canonical'], *group['aliases']]}
    return ValueMapper(operator_mappings, vendor_mappings, OPERATORS, VENDORS)


def test_field_kinds_cover_every_operator_and_vendor_field():
    assert [field_kind(name) for name in ('Operator', 'operators', 'Vendor', 'operator_vendor', 'Vendor_Operator', 'City')] == [
        'operator', 'operator', 'vendor', 'operator_vendor', 'vendor_operator', None]


def test_values_are_mapped_and_follow_the_maps():
    values = mapper()
    assert values.values('operator', ['EE', 'Three UK', 'Vodafone UK', 'O2']) == ['VF', '3', 'EE', 'O2']
    # Operator_Vendor: by Operator, then Vendor; Operators without a Vendor after every Operator with Vendors.
    assert values.values('operator_vendor', ['EE - All', '3_NSN', 'Vodafone_ERIC', 'Vodafone_Nokia', '3_Ericsson']) == [
        'VF_Ericsson', 'VF_Nokia', '3_Ericsson', '3_Nokia', 'EE - All']


def test_mapped_selections_expand_to_every_source_spelling():
    values = mapper()
    assert values.expand('operator', ['VF'], ['Vodafone UK', 'EE', 'VF_SA']) == ['Vodafone UK', 'VF_SA', 'VF']
    assert set(values.sources('operator', ['VF'])) >= {'VF', 'vodafone uk', 'vf_sa'}
    assert 'vodafone_eric' in values.sources('operator_vendor', ['VF_Ericsson'])


def test_vendor_operator_is_operator_vendor_the_other_way_round():
    assert swap_operator_vendor('VF_SA_Ericsson_Mixed', OPERATORS) == 'Ericsson_Mixed_VF_SA'
    assert swap_vendor_operator('Ericsson_Mixed_VF_SA', OPERATORS) == 'VF_SA_Ericsson_Mixed'
    assert swap_operator_vendor('EE - All', OPERATORS) == 'EE - All'
    values = mapper()
    assert values.map('vendor_operator', 'ERIC_Vodafone UK') == 'Ericsson_VF'
    assert values.operator_vendors(['Ericsson_VF']) == ['VF_Ericsson']
    # By Vendor, then Operator; Operators without a Vendor last, in the same "<Operator> - All" form.
    vendor_operators = ['EE - All', 'Nokia_3', 'Ericsson_3', 'Nokia_VF', 'Ericsson_VF', 'VF - All']
    assert sorted(vendor_operators, key=lambda value: dimension_order_key('Vendor_Operator', value, OPERATORS, VENDORS)) == [
        'Ericsson_VF', 'Ericsson_3', 'Nokia_VF', 'Nokia_3', 'VF - All', 'EE - All']
