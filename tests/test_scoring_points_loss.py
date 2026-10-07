"""Where the scoring points are lost: points-lost maps per City, ITL3 area and custom Clusters."""
from __future__ import annotations

import json
import random
from io import BytesIO

import pandas as pd
import pytest
from pptx import Presentation

from src.modules import scoring_points_loss as points_loss
from src.modules.scoring import calculate_scoring
from src.modules.scoring_exports import export_scoring_powerpoint, export_scoring_report
from src.modules.scoring_reports import default_scenario
from src.modules.scoring_views import build_scoring_views
from tests.scoring_fixtures import scoring_configuration
from tests.test_scoring_api import scoring_api  # noqa: F401  (fixture)
from tests.test_scoring_exports import TEMPLATE

PLACES = {'Leeds': (53.80, -1.55), 'Manchester': (53.48, -2.24), 'London': (51.51, -0.13)}


def _result():
    """Three operators; Vodafone and Three fail calls mostly in Leeds and on a road towards it."""
    random.seed(7)
    rows = []
    for operator in ('EE', 'Vodafone UK', 'Three UK'):
        for city, (latitude, longitude) in PLACES.items():
            for index in range(40):
                failed = operator != 'EE' and ((city == 'Leeds' and index < 8) or (city == 'Manchester' and index < 2))
                rows.append({'Campaign': '2026-Q2', 'Operator': operator, 'G_Level_1': 'Drive', 'G_Level_2': 'City',
                             'City': city, 'Session_Type': 'CALL', 'Call_Status': 'Failed' if failed else 'Completed',
                             'Call_Start_Latitude_A': latitude + random.uniform(-.02, .02),
                             'Call_Start_Longitude_A': longitude + random.uniform(-.02, .02)})
        for index in range(30):
            rows.append({'Campaign': '2026-Q2', 'Operator': operator, 'G_Level_1': 'Drive', 'G_Level_2': 'Connectionroad',
                         'City': 'Sheffield to Leeds', 'Session_Type': 'CALL',
                         'Call_Status': 'Failed' if operator != 'EE' and index % 6 == 0 else 'Completed',
                         'Call_Start_Latitude_A': 53.38 + index * .014, 'Call_Start_Longitude_A': -1.47 - index * .003})
    result = calculate_scoring({'voice': pd.DataFrame(rows)}, ['Operator'], configuration=scoring_configuration())
    job = {'id': 1, 'levels': ['Operator'], 'baseline_operator': 'EE', 'configuration': result['configuration'],
           'campaigns': ['2026-Q2']}
    return job, result


def test_points_lost_are_spread_over_the_cities_routes_and_itl3_areas():
    job, result = _result()
    maps = build_scoring_views(job, result)['insights']['points_loss_maps']
    vodafone = {item['field']: item for item in maps if item['operator'] == 'Vodafone UK'}
    assert {'City', 'ITL3'} <= set(vodafone)
    cities = {area['name']: area for area in vodafone['City']['areas']}
    # Leeds loses most of the city points; the road is a route between cities.
    assert next(iter(cities)) in {'Leeds', 'Sheffield to Leeds'}
    assert cities['Leeds']['points'] > cities['Manchester']['points'] and 'London' not in cities
    assert cities['Sheffield to Leeds']['kind'] == 'route' and cities['Sheffield to Leeds']['route']
    # The ITL3 areas share the same total: the tests are placed in the polygon that contains them.
    areas = {area['name']: area['points'] for area in vodafone['ITL3']['areas']}
    assert vodafone['ITL3']['total'] == pytest.approx(vodafone['City']['total'])
    # Leeds also takes the end of the road that enters it.
    assert cities['Leeds']['points'] < areas['Leeds'] < cities['Leeds']['points'] + cities['Sheffield to Leeds']['points']
    # EE completes every call: it loses no points and gets no map.
    assert not any(item['operator'] == 'EE' for item in maps)


def test_bundled_itl3_boundaries_cover_the_uk():
    boundaries = points_loss.bundled_boundaries('ITL3')
    assert len(boundaries) == 182 and 'Leeds' in boundaries
    names = points_loss.boundary_names('ITL3', pd.Series([53.80, 51.51, 0.0]), pd.Series([-1.55, -0.13, 0.0]))
    assert names.iloc[0] == 'Leeds' and names.iloc[1] == 'Westminster and City of London' and pd.isna(names.iloc[2])


def test_custom_cluster_polygons_are_read_from_a_geojson(tmp_path):
    path = tmp_path / 'clusters.geojson'
    path.write_text(json.dumps({'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
                                'features': [{'type': 'Feature', 'properties': {'Cluster': 'North'},
                                              'geometry': {'type': 'Polygon', 'coordinates': [[[-2.5, 53], [-1, 53], [-1, 54.5], [-2.5, 54.5], [-2.5, 53]]]}}]}))
    boundaries = points_loss.mapping_boundaries(path, 'Cluster')
    assert list(boundaries) == ['North'] and boundaries['North'][0][0] == [-2.5, 53.0]
    assert points_loss.map_boundaries({'points_loss': {'boundaries': {'Cluster': boundaries}}}, 'Cluster') == boundaries


def _titles(content):
    return [slide.shapes.title.text_frame.text.split('\n')[0] for slide in Presentation(BytesIO(content)).slides
            if slide.shapes.title is not None]


def test_powerpoint_maps_the_points_lost_of_the_compared_operators():
    job, result = _result()
    content = export_scoring_powerpoint(job, result, TEMPLATE)
    titles = _titles(content)
    assert 'Points Lost per City — Vodafone UK' in titles and 'Points Lost per City — Three UK' in titles
    assert not any(title.startswith('Points Lost per City — EE') for title in titles)
    deck = Presentation(BytesIO(content))
    slide = next(slide for slide in deck.slides if slide.shapes.title is not None
                 and slide.shapes.title.text_frame.text.startswith('Points Lost per City — Vodafone UK'))
    names = {shape.name for shape in slide.shapes}
    assert {'Scoring Points Lost Map', 'Scoring Points Lost Bars', 'Scoring Points Lost Scale'} <= names
    scenario = default_scenario(operators=['Vodafone UK', 'Three UK'])
    for options in scenario['scorings'].values():
        options['gap']['points_loss_map'] = False
    without = export_scoring_report([{'job': job, 'result': result, 'scenario': scenario}], TEMPLATE)
    assert not any(title.startswith('Points Lost per') for title in _titles(without))


def test_job_api_serves_the_map_layers_without_the_raw_shares(scoring_api, monkeypatch):
    from types import ModuleType

    from src.modules import scoring_jobs

    client = scoring_api['client']
    repository = scoring_api['repository']
    repository.replace_scoring_configuration(scoring_configuration())
    _job, computed = _result()
    engine = ModuleType('src.modules.scoring')
    engine.METHOD_VERSION = 'points-loss-api-test'
    engine.required_input_columns = lambda kind, levels: [*levels, 'score']
    engine.calculate_scoring = lambda frames, levels, *, baseline_operator, configuration=None: computed
    monkeypatch.setattr(scoring_jobs, '_scoring_engine', lambda: engine)
    created = client.post('/api/scoring/jobs', json={
        'dataset_ids': scoring_api['complete_dataset_ids'], 'aggregation_levels': ['Operator'],
        'nr_mode': 'NSA', 'baseline_operator': 'EE',
    })
    assert created.status_code == 200, created.text
    job_id = created.json()['job']['id']
    assert scoring_jobs.run_scoring_job(repository, job_id)['status'] == 'completed'

    payload = client.get(f'/api/scoring/jobs/{job_id}').json()
    assert 'points_loss' not in payload
    assert any(item['field'] == 'ITL3' for item in payload['views']['insights']['points_loss_maps'])
    layer = client.get(f'/api/scoring/jobs/{job_id}/boundaries/ITL3').json()
    assert layer['field'] == 'ITL3' and len(layer['boundaries']) == 182
    # Without a Clusters dataset applied to the CDRs the Cluster layer has no polygons.
    assert client.get(f'/api/scoring/jobs/{job_id}/boundaries/Cluster').json()['boundaries'] == {}
    assert client.get(f'/api/scoring/jobs/{job_id}/boundaries/Unknown').status_code == 404
