import pandas as pd

from src.modules.analytics import _category_order_key, _chart_mapping_group
from src.modules.cdr_reporting import _vendor_display_sort_key, _vendor_only_display_sort_key
from src.modules.mapping_order import dimension_order_key, split_operator_vendor, vendor_order_key
from src.modules.scoring_views import _hierarchy_column_sort_key

OPERATORS = [{'canonical': name, 'aliases': [], 'position': index}
             for index, name in enumerate(['EE', '3', 'VF_UK', 'VF_SA', 'O2', 'Lebara'])]
VENDORS = [{'canonical': name, 'aliases': aliases, 'position': index} for index, (name, aliases) in enumerate([
    ('Ericsson', []), ('Huawei', []), ('Samsung', []), ('NSN', ['Nokia']), ('Ericsson_Mixed', ['Ericsson Mixed']),
    ('Non-Ericsson_Mixed', ['Mixed']), ('Other Vendor', ['Other']), ('(blank)', []),
])]


def frame_with_maps() -> pd.DataFrame:
    frame = pd.DataFrame()
    frame.attrs.update(operator_mapping_groups=OPERATORS, vendor_mapping_groups=VENDORS)
    return frame


def test_vendors_follow_the_vendor_map_and_operators_without_a_vendor_come_last():
    vendors = ['Samsung', 'Non-Ericsson_Mixed', 'Ericsson_Mixed', 'Huawei', 'Ericsson', '3 - All', 'Nokia', 'ZTE', 'EE - All']
    expected = ['Ericsson', 'Huawei', 'Samsung', 'Nokia', 'Ericsson_Mixed', 'Non-Ericsson_Mixed', 'ZTE', 'EE - All', '3 - All']
    assert sorted(vendors, key=lambda value: dimension_order_key('Vendor', value, OPERATORS, VENDORS)) == expected
    frame = frame_with_maps()
    assert sorted(vendors, key=lambda value: _vendor_only_display_sort_key(value, frame)) == expected
    assert sorted(vendors, key=lambda value: _category_order_key(frame, 'vendor', value)) == expected


def test_operator_vendor_values_follow_the_operator_map_then_the_vendor_map():
    values = ['VF_UK_Huawei', '3_Samsung', '3_Ericsson_Mixed', 'EE_Huawei', '3_Ericsson', 'VF_UK_Ericsson',
              '3 - All', 'EE - All', 'O2_Non-Ericsson_Mixed', 'EE_Ericsson']
    # Operators without a Vendor come after every Operator with Vendors, in Operator Map order.
    expected = ['EE_Ericsson', 'EE_Huawei', '3_Ericsson', '3_Samsung', '3_Ericsson_Mixed',
                'VF_UK_Ericsson', 'VF_UK_Huawei', 'O2_Non-Ericsson_Mixed', 'EE - All', '3 - All']
    assert sorted(values, key=lambda value: dimension_order_key('Operator_Vendor', value, OPERATORS, VENDORS)) == expected
    frame = frame_with_maps()
    assert sorted(values, key=lambda value: _vendor_display_sort_key(value, frame)) == expected
    assert sorted(values, key=lambda value: _category_order_key(frame, 'operator_vendor', value)) == expected


def test_vendor_names_containing_underscores_are_not_cut_at_their_last_underscore():
    assert split_operator_vendor('3_Ericsson_Mixed', OPERATORS) == ('3', 'Ericsson_Mixed')
    assert split_operator_vendor('VF_UK_Huawei', OPERATORS) == ('VF_UK', 'Huawei')
    frame = frame_with_maps()
    assert _chart_mapping_group(frame, 'vendor', 'Ericsson_Mixed')['canonical'] == 'Ericsson_Mixed'
    assert _chart_mapping_group(frame, 'operator_vendor', '3_Ericsson_Mixed')['canonical'] == 'Ericsson_Mixed'
    assert vendor_order_key('Ericsson_Mixed', VENDORS, OPERATORS) < vendor_order_key('Non-Ericsson_Mixed', VENDORS, OPERATORS)


def test_scoring_hierarchy_orders_the_vendor_level_by_the_vendor_map():
    columns = [
        {'path': [{'level': 'Operator', 'value': '3'}, {'level': 'Vendor', 'value': vendor}],
         'operator_position': 1, 'vendor_order': vendor_order_key(vendor, VENDORS, OPERATORS)}
        for vendor in ['Samsung', 'Non-Ericsson_Mixed', 'Ericsson', 'Ericsson_Mixed', 'Huawei']
    ]
    ordered = [column['path'][1]['value'] for column in sorted(columns, key=_hierarchy_column_sort_key)]
    assert ordered == ['Ericsson', 'Huawei', 'Samsung', 'Ericsson_Mixed', 'Non-Ericsson_Mixed']


def test_vendor_operator_orders_ericsson_mixed_with_ericsson_and_other_mixed_groups_last():
    values = ['Non-Ericsson_Mixed_3', 'Ericsson_Mixed_VF_UK', 'Huawei_3', 'Ericsson_VF_UK', 'Ericsson_Mixed_3',
              'Ericsson_3', 'NSN_VF_UK', 'EE - All']
    # Non-Ericsson_Mixed comes last of all, even after the Operators without a Vendor.
    expected = ['Ericsson_3', 'Ericsson_Mixed_3', 'Ericsson_VF_UK', 'Ericsson_Mixed_VF_UK', 'Huawei_3', 'NSN_VF_UK',
                'EE - All', 'Non-Ericsson_Mixed_3']
    assert sorted(values, key=lambda value: dimension_order_key('Vendor_Operator', value, OPERATORS, VENDORS)) == expected
