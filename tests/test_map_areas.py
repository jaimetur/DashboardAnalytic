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
    # The UK keeps the bundled ITL3 areas; a test in no area (Bilbao) is left without one.
    assert names.tolist()[:4] == ['Madrid', 'Getafe', 'Barcelona', 'Westminster and City of London'] and pd.isna(names.iloc[4])
    document = index.document({'Madrid', 'Westminster and City of London'}, ['FRA'])
    assert [item['code'] for item in document['countries']] == ['GBR', 'ESP']
    # Only the used areas of other countries are kept with the job, over the outline of their country.
    assert list(document['boundaries']) == ['Madrid'] and document['background']
    assert document['unmapped_countries'] == [{'code': 'FRA', 'name': 'France'}]
    # Changing the layers rebuilds the index.
    map_areas.delete_layer(repository, layer['id'])
    assert map_areas.area_index(repository).names_of(pd.Series([40.45]), pd.Series([-3.7])).isna().all()


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
    assert document['map_areas']['countries'] == [{'code': 'ESP', 'name': 'Spain', 'label': 'municipality'}]
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
    # Repeated names stay separate areas.
    assert set(map_areas.layer_boundaries(repository, 'ESP')) == {'Madrid', 'Toledo (1)', 'Toledo (2)'}
    with pytest.raises(ValueError, match='bundled ITL3'):
        map_areas.save_layer(repository, country_code='GBR', level='ADM2', level_label='county', origin='Imported',
                             source='', license_text='', attribution='', boundaries=SPAIN, username='super')


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
    assert [(item['code'], round(item['share'], 2), item['bundled'], bool(item['layer'])) for item in countries] == [
        ('ESP', .9, False, True), ('GBR', .1, True, False)]
