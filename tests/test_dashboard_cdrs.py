"""The CDRs chosen in a Dashboard always belong to its workspace."""
from src.modules.ppt_dashboards import existing_dataset_selection


class _Datasets:
    def __init__(self, rows):
        self.rows = rows

    def list_datasets(self):
        return self.rows


def test_a_dashboard_forgets_the_cdrs_its_workspace_does_not_have():
    kinds = {4: 'data', 5: 'speech', 6: 'voice'}
    # CDRs of another workspace (or deleted ones), and a Speech CDR chosen as Voice, are left out.
    assert existing_dataset_selection({'name': 'A', 'datasets': {'data': [4, 9], 'voice': [5], 'speech': [5]}}, kinds) == {
        'name': 'A', 'datasets': {'data': [4], 'voice': [], 'speech': [5]}}
    # Without any of its CDRs it uses the latest CDRs again, like a Dashboard without CDRs.
    assert existing_dataset_selection({'name': 'B', 'datasets': {'data': [9, 3], 'voice': [11, 5], 'speech': [10, 4]}}, kinds) == {
        'name': 'B'}
    # A Dashboard whose CDRs are all here, or that has none, is not changed.
    unchanged = {'name': 'C', 'datasets': {'data': [4], 'voice': [], 'speech': []}}
    assert existing_dataset_selection(unchanged, kinds) is unchanged
    assert existing_dataset_selection({'name': 'D'}, kinds) == {'name': 'D'}


def test_imported_dashboards_choose_the_cdrs_of_the_destination_with_the_same_name():
    import src.DriveTestAnalyzer as app_module

    destination = _Datasets([
        {'id': 4, 'file_name': 'DE_Q3_Data.xlsm', 'dataset_kind': 'data'},
        {'id': 6, 'file_name': 'DE_Q3_Voice.xlsm', 'dataset_kind': 'voice'},
        {'id': 9, 'file_name': 'Other.xlsm', 'dataset_kind': 'data'},
    ])
    source_cdrs = [
        {'id': 9, 'name': 'de_q3_data.xlsm', 'kind': 'data'},
        {'id': 11, 'name': 'DE_Q3_Voice.xlsm', 'kind': 'voice'},
        {'id': 10, 'name': 'UK_Q3_Speech.xlsm', 'kind': 'speech'},
        {'id': 3, 'name': 'UK_Q3_Data.xlsm', 'kind': 'data'},
    ]
    dashboards = {
        'report': {'name': 'NetCheck CDR Report', 'datasets': {'data': [9], 'voice': [11], 'speech': [10]}},
        'uk-only': {'name': 'UK only', 'datasets': {'data': [3], 'voice': [], 'speech': [10]}},
        'latest': {'name': 'Latest CDRs'},
    }
    imported = app_module._dashboards_on_destination_cdrs(dashboards, source_cdrs, destination)
    # Id 9 is another CDR in the destination: the CDR with the same name and type is chosen instead.
    assert imported['report']['datasets'] == {'data': [4], 'voice': [6], 'speech': []}
    assert imported['uk-only'] == {'name': 'UK only'}
    assert imported['latest'] == {'name': 'Latest CDRs'}
    # A package without the names of its CDRs keeps only the CDRs the destination has with their type.
    assert app_module._dashboards_on_destination_cdrs(
        {'report': {'datasets': {'data': [9, 3], 'voice': [6]}}}, None, destination,
    ) == {'report': {'datasets': {'data': [9], 'voice': [6]}}}


def test_the_vendor_sources_cover_the_operators_of_their_datasets(client, tmp_path):
    import json

    import src.DriveTestAnalyzer as app_module

    polygons = tmp_path / 'vendors.geojson'
    polygons.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'Operator': operator, 'Vendor': 'Ericsson'},
         'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
        for operator in ('VF', 'Three UK')]}), encoding='utf-8')
    covered = app_module.vendor_source_operators(
        [{'id': 1}], [{'id': 2}],
        [{'dataset_operator': 'O2', 'can_map_vendors_from': True}, {'dataset_operator': 'EE', 'can_map_vendors_from': False}],
        [{'dataset_operator': '', 'stored_path': str(polygons)}, {'dataset_operator': 'O2 UK', 'stored_path': ''}],
    )
    # VFUK covers Vodafone, 3UK covers 3 and each Network Inventory that can map Vendors its Operator.
    assert covered['inventory'] == ['3', 'o2', 'vodafone uk']
    # Multi-operator polygons cover the Operators of their Operator attribute.
    assert covered['polygons'] == ['3', 'o2', 'vodafone uk']
    assert covered['mapping_vodafone'] == 'vodafone uk' and covered['identities']['VF'] == 'vodafone uk'
