"""Map Areas of a workspace: the administrative areas of each country of the tests."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pandas as pd
import pytest

from src.modules import map_areas
from src.modules.scoring import calculate_scoring
from src.modules.scoring_points_loss import map_background, map_boundaries
from tests.scoring_fixtures import scoring_configuration

# Two square areas around Madrid and one around Barcelona, as a downloaded layer would hold them.
SPAIN = {
    'Madrid': [[[-3.9, 40.3], [-3.5, 40.3], [-3.5, 40.6], [-3.9, 40.6], [-3.9, 40.3]]],
    'Getafe': [[[-3.9, 40.0], [-3.5, 40.0], [-3.5, 40.3], [-3.9, 40.3], [-3.9, 40.0]]],
    'Barcelona': [[[2.0, 41.3], [2.3, 41.3], [2.3, 41.5], [2.0, 41.5], [2.0, 41.3]]],
}


class FakeRepository:
    """The workspace database calls Map Areas uses, on a SQLite file."""

    def __init__(self, path):
        self.db_path = path

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


@pytest.fixture()
def repository(tmp_path):
    return FakeRepository(tmp_path / 'workspace.db')


def _save_spain(repository):
    return map_areas.save_layer(repository, country_code='ESP', level='ADM3', level_label='municipality',
                                origin='geoBoundaries', source='IGN', license_text='CC BY 4.0',
                                attribution='IGN via geoBoundaries', boundaries=SPAIN, username='super')


def test_the_countries_of_the_tests_come_from_their_coordinates():
    codes = map_areas.country_codes(pd.Series([40.42, 51.51, 45.5, 0.0]), pd.Series([-3.70, -0.13, -73.57, 0.0]))
    assert codes.tolist()[:3] == ['ESP', 'GBR', 'CAN'] and pd.isna(codes.iloc[3])
    assert map_areas.country_name('ESP') == 'Spain'


def test_each_test_takes_the_area_of_its_country(repository):
    layer = _save_spain(repository)
    assert layer['country_name'] == 'Spain' and layer['unit_count'] == 3
    index = map_areas.area_index(repository)
    names = index.names_of(pd.Series([40.45, 40.1, 41.4, 51.51, 43.0]), pd.Series([-3.7, -3.7, 2.15, -0.13, -2.0]))
    # The UK keeps the ITL3 areas shipped with the application; a test in no area (Bilbao) is left without one.
    assert names.tolist()[:4] == ['Madrid', 'Getafe', 'Barcelona', 'Westminster and City of London'] and pd.isna(names.iloc[4])
    document = index.document({'Madrid', 'Westminster and City of London'})
    assert sorted((item['code'], item['bundled']) for item in document['countries']) == [('ESP', False), ('GBR', True)]
    # Only the used areas of other countries are kept with the job, over the outline of their country.
    assert list(document['boundaries']) == ['Madrid'] and document['background']
    assert document['unmapped_countries'] == []
    # A country without Map Areas is one area, the whole country, drawn from the application's country polygons.
    assert index.names_of(pd.Series([50.85]), pd.Series([4.35])).tolist() == ['Belgium']
    document = index.document({'Belgium'})
    assert document['countries'] == [{'code': 'BEL', 'name': 'Belgium', 'label': 'country', 'bundled': True}]
    assert document['unmapped_countries'] == [{'code': 'BEL', 'name': 'Belgium'}] and document['background'] == []
    assert list(map_areas.bundled_rings('BEL')) == ['Belgium']
    # Changing the layers rebuilds the index: without its own areas, Spain uses the provinces shipped with the application.
    map_areas.delete_layer(repository, layer['id'])
    index = map_areas.area_index(repository)
    assert index.names_of(pd.Series([40.45]), pd.Series([-3.7])).tolist() == ['Madrid']
    assert index.document({'Madrid'})['countries'] == [{'code': 'ESP', 'name': 'Spain', 'label': 'province', 'bundled': True}]


def test_scoring_places_the_tests_in_the_map_areas_and_keeps_the_losses_of_each_city(repository):
    _save_spain(repository)
    rows = []
    for operator in ('EE', 'Vodafone UK'):
        for city, (latitude, longitude) in {'Madrid': (40.45, -3.7), 'Getafe': (40.1, -3.7)}.items():
            for index in range(20):
                failed = operator != 'EE' and city == 'Madrid' and index < 5
                rows.append({'Campaign': '2026-Q2', 'Operator': operator, 'G_Level_1': 'Drive', 'G_Level_2': 'City',
                             'City': city, 'Session_Type': 'CALL', 'Call_Status': 'Failed' if failed else 'Completed',
                             'Call_Start_Latitude_A': latitude, 'Call_Start_Longitude_A': longitude})
        # A test in Bilbao, outside every saved area of Spain.
        rows.append({'Campaign': '2026-Q2', 'Operator': operator, 'G_Level_1': 'Drive', 'G_Level_2': 'City', 'City': 'Bilbao',
                     'Session_Type': 'CALL', 'Call_Status': 'Completed', 'Call_Start_Latitude_A': 43.26, 'Call_Start_Longitude_A': -2.93})
    result = calculate_scoring({'voice': pd.DataFrame(rows)}, ['Operator'], configuration=scoring_configuration(),
                               map_areas=map_areas.area_index(repository))
    document = result['points_loss']
    assert document['map_areas']['countries'] == [{'code': 'ESP', 'name': 'Spain', 'label': 'municipality', 'bundled': False}]
    assert set(document['map_areas']['boundaries']) == {'Madrid', 'Getafe'}
    assert map_boundaries(result, 'Area') == document['map_areas']['boundaries'] and map_background(result, 'Area')
    shares = [entry['areas'] for entry in document['shares'] if entry.get('operator') == 'Vodafone UK']
    assert shares and all(set(entry['City|Area']) == {'Madrid\x1fMadrid'} for entry in shares)


def test_geoboundaries_levels_suggest_the_finest_commercial_level_and_download_it(repository, monkeypatch):
    levels = [
        {'boundaryType': 'ADM0', 'admUnitCount': '1'},
        {'boundaryType': 'ADM1', 'admUnitCount': '19', 'boundaryCanonical': 'Unknown', 'boundaryLicense': 'CC BY 4.0',
         'boundarySource': 'IGN', 'simplifiedGeometryGeoJSON': 'https://example.test/adm1.geojson'},
        {'boundaryType': 'ADM2', 'admUnitCount': '52', 'boundaryCanonical': 'Province', 'boundaryLicense': 'CC BY 4.0',
         'boundarySource': 'INE', 'simplifiedGeometryGeoJSON': 'https://example.test/adm2.geojson'},
        {'boundaryType': 'ADM3', 'admUnitCount': '8205', 'boundaryCanonical': 'MUNICIPIOS',
         'boundaryLicense': 'CC BY-NC 4.0 (non-commercial)', 'boundarySource': 'IGN',
         'simplifiedGeometryGeoJSON': 'https://example.test/adm3.geojson'},
    ]
    features = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'shapeName': name}, 'geometry': {'type': 'Polygon', 'coordinates': rings}}
        for name, rings in [('Madrid', SPAIN['Madrid']), ('Toledo', SPAIN['Getafe']), ('Toledo', SPAIN['Barcelona'])]]}
    monkeypatch.setattr(map_areas, '_fetch', lambda url, timeout=0: json.dumps(levels if 'api' in url else features).encode())
    offered = map_areas.geoboundaries_levels('esp')
    assert [(item['level'], item['label'], item['commercial']) for item in offered] == [
        ('ADM1', 'ADM1 area', True), ('ADM2', 'province', True), ('ADM3', 'municipio', False)]
    assert [item['level'] for item in offered if item.get('suggested')] == ['ADM2']
    layer = map_areas.download_geoboundaries(repository, 'ESP', 'ADM2', 'super')
    assert layer['level_label'] == 'province' and layer['origin'] == 'geoBoundaries' and 'geoBoundaries' in layer['attribution']
    # Polygons with the same name in the same region are the parts of one area.
    assert {name: len(rings) for name, rings in map_areas.layer_boundaries(repository, 'ESP').items()} == {'Madrid': 1, 'Toledo': 2}
    # The UK can replace its ITL3 areas too.
    london = {'Greater London': [[[-0.6, 51.2], [0.4, 51.2], [0.4, 51.8], [-0.6, 51.8], [-0.6, 51.2]]]}
    map_areas.save_layer(repository, country_code='GBR', level='Imported', level_label='county', origin='Imported',
                         source='', license_text='', attribution='', boundaries=london, username='super')
    assert map_areas.area_index(repository).names_of(pd.Series([51.51]), pd.Series([-0.13])).tolist() == ['Greater London']


def test_map_areas_travel_with_their_polygons(repository, tmp_path):
    _save_spain(repository)
    document = json.loads(json.dumps(map_areas.layers_document(repository)))
    other = FakeRepository(tmp_path / 'other.db')
    assert map_areas.import_layers_document(other, document, 'super') == 1
    assert map_areas.layer_boundaries(other, 'ESP') == SPAIN
    assert map_areas.list_layers(other)[0]['updated_by'] == 'super'
    with pytest.raises(ValueError):
        map_areas.import_layers_document(other, {'format': 'other'}, 'super')


def test_the_countries_of_the_tests_are_found_from_a_sample_of_the_ready_cdrs(repository):
    with repository.connection() as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Call_Start_Latitude_A REAL, Call_Start_Longitude_A REAL)')
        connection.executemany('INSERT INTO dataset_rows_1 VALUES (?, ?)',
                               [(40.42, -3.70)] * 90 + [(51.51, -0.13)] * 10)
    repository.list_datasets = lambda: [{'id': 1, 'status': 'ready', 'dataset_kind': 'voice'},
                                        {'id': 2, 'status': 'processing', 'dataset_kind': 'voice'}]
    repository.list_dataset_row_columns = lambda dataset_id: ['Call_Start_Latitude_A', 'Call_Start_Longitude_A']
    repository.dataset_rows_table_name = lambda dataset_id: f'dataset_rows_{dataset_id}'
    _save_spain(repository)
    countries = map_areas.detect_countries(repository)
    # Spain has its own areas (over the provinces shipped with the application); the UK uses its ITL3 areas.
    assert [(item['code'], round(item['share'], 2), item['bundled']['level_label'], bool(item['layer'])) for item in countries] == [
        ('ESP', .9, 'province', True), ('GBR', .1, 'ITL3 area', False)]


def test_areas_whose_edges_cross_after_simplifying_still_place_the_tests(repository):
    # A ring crossing itself (as simplifying a jagged border can leave it) is repaired, not merged.
    crossed = {'Bayreuth': [[[11.4, 49.9], [11.6, 50.0], [11.6, 49.9], [11.4, 50.0], [11.4, 49.9]]],
               'Hof': [[[11.8, 50.2], [12.0, 50.2], [12.0, 50.4], [11.8, 50.4], [11.8, 50.2]]]}
    map_areas.save_layer(repository, country_code='DEU', level='ADM3', level_label='district', origin='geoBoundaries',
                         source='BKG', license_text='dl-de/by-2-0', attribution='BKG', boundaries=crossed, username='super')
    names = map_areas.area_index(repository).names_of(pd.Series([49.96, 49.99, 50.3]), pd.Series([11.45, 11.5, 11.9]))
    assert names.tolist()[0] == 'Bayreuth' and pd.isna(names.iloc[1]) and names.iloc[2] == 'Hof'
    assert map_areas.area_index(repository).document({'Bayreuth'})['boundaries']['Bayreuth'] == crossed['Bayreuth']


def test_a_name_found_in_several_regions_takes_the_name_of_each():
    from shapely.geometry import box
    features = [('Washington', box(0, 0, 1, 1)), ('Washington', box(5, 5, 6, 6)), ('Konstanz', box(10, 10, 11, 11)),
                ('Konstanz', box(11, 11, 12, 12)), ('Toledo', box(20, 20, 21, 21))]
    regions = lambda geometry: 'Ohio' if geometry.bounds[0] == 0 else 'Utah' if geometry.bounds[0] == 5 else 'Baden-Württemberg'
    boundaries = map_areas._features_boundaries(features, .001, regions)
    assert {name: len(rings) for name, rings in boundaries.items()} == {
        'Washington (Ohio)': 1, 'Washington (Utah)': 1, 'Konstanz': 2, 'Toledo': 1}


def test_the_application_ships_map_areas_for_its_main_markets():
    shipped = map_areas.bundled_layers()
    assert {'GBR', 'DEU', 'FRA', 'ITA', 'ESP', 'POL', 'ROU', 'NLD', 'CHE', 'USA', 'CAN', 'MEX', 'JPN', 'KOR', 'IND'} <= set(shipped)
    assert all(item['license'] and item['unit_count'] > 0 for item in shipped.values())
    index = map_areas.area_index(None)
    places = index.names_of(pd.Series([52.52, 48.85, 46.95, 40.71, 35.68, 37.57, 28.61]),
                            pd.Series([13.40, 2.35, 7.45, -74.0, 139.69, 126.98, 77.21]))
    assert places.notna().all() and places.iloc[2] == 'Bern'
