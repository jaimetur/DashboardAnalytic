"""Campaign Maps: the label format, mode order and exceptions every campaign label follows."""
import json

import pytest

import src.DriveTestAnalyzer as core
from src.modules.campaign_maps import load_campaign_map
from src.modules.column_names import (
    DEFAULT_CAMPAIGN_MAP, campaign_sort_key, compact_campaign_value, format_campaign, normalize_campaign_map,
    use_campaign_map,
)
from tests.test_non_qualified_calls import add_cdr, login, voice_rows

CAMPAIGNS = ['UK_Q2_SA_2026', 'UK_Q2_2026', 'UK_Q2_NSA_2026', 'UK_Q1_2026', '2025-Q4', 'Xmas drive', 'Special']


def _labels(config):
    return [format_campaign(value, config) for value in sorted(CAMPAIGNS, key=lambda value: campaign_sort_key(value, config))]


def test_default_map_reads_year_quarter_and_mode_in_order():
    config = normalize_campaign_map(DEFAULT_CAMPAIGN_MAP)
    assert _labels(config) == ['Special', 'Xmas drive', '2025-Q4', '2026-Q1', '2026-Q2', '2026-Q2-NSA', '2026-Q2-SA']
    # Any spelling of a campaign reads the same, so comparisons and filters keep matching.
    assert {compact_campaign_value(value) for value in ('UK_Q2_SA_2026', '2026-Q2_SA', '2026 Q2 SA', 'Q2_2026_SA')} == {'2026-Q2-SA'}


def test_custom_format_mode_order_and_exceptions_cover_new_campaigns():
    config = normalize_campaign_map({
        'format': 'Q{quarter}_{year}{_mode}{ (market)}', 'mode_order': ['SA', '', 'NSA'],
        'exceptions': [{'label': '2025-Q4 Xmas', 'sources': ['Xmas drive']}, {'label': 'Pilot', 'sources': 'Special'}],
    })
    assert _labels(config) == ['Pilot', 'Q4_2025', '2025-Q4 Xmas', 'Q1_2026 (UK)', 'Q2_2026_SA (UK)', 'Q2_2026 (UK)',
                               'Q2_2026_NSA (UK)']
    # A campaign uploaded later follows the format without editing the map.
    assert format_campaign('UK_Q1_2027_SA', config) == 'Q1_2027_SA (UK)'
    # Exception labels read as themselves, so a filter on the label matches.
    assert format_campaign('2025-Q4 Xmas', config) == '2025-Q4 Xmas'
    with use_campaign_map(config):
        assert compact_campaign_value('UK_Q3_2026') == 'Q3_2026 (UK)'
    assert compact_campaign_value('UK_Q3_2026') == '2026-Q3'


@pytest.mark.parametrize('config, message', [
    ({'format': '{year}-{week}'}, 'Unknown campaign label markers'),
    ({'format': 'Campaign'}, 'needs at least one marker'),
    ({'exceptions': [{'label': '', 'sources': ['A']}]}, 'needs a label'),
    ({'exceptions': [{'label': 'A', 'sources': []}]}, 'at least one source campaign'),
    ({'exceptions': [{'label': 'A', 'sources': ['X']}, {'label': 'B', 'sources': ['x']}]}, 'more than one exception'),
])
def test_invalid_maps_are_refused(config, message):
    with pytest.raises(ValueError, match=message):
        normalize_campaign_map(config)


def test_workspace_config_edits_previews_and_saves_the_map(client, tmp_path):
    voice = voice_rows()
    voice['Campaign'] = ['UK_Q2_SA_2026', 'UK_Q2_2026', 'UK_Q1_2026']
    add_cdr(tmp_path, 'NetCheck_UK_CDR_Voice_2026_Q1.xlsx', 'voice', voice)
    login(client)
    page = client.get('/workspace-config').text
    assert 'id="campaign-maps"' in page and 'campaign_maps.js' in page and 'id="campaign-map"' in page

    current = client.get('/api/workspace-config/campaign-map').json()
    assert current['campaign_map'] == normalize_campaign_map(DEFAULT_CAMPAIGN_MAP)
    edited = {'format': 'Q{quarter}_{year}{_mode}', 'mode_order': ['', 'NSA', 'SA'],
              'exceptions': [{'label': 'Q1 baseline', 'sources': ['UK_Q1_2026']}]}
    preview = client.post('/api/workspace-config/campaign-map/preview', json={'campaign_map': edited})
    assert preview.status_code == 200
    assert client.post('/api/workspace-config/campaign-map/preview', json={'campaign_map': {'format': '{week}'}}).status_code == 400

    saved = client.put('/api/workspace-config/campaign-map', json={'campaign_map': edited})
    assert saved.status_code == 200, saved.text
    assert load_campaign_map(core.repository)['format'] == 'Q{quarter}_{year}{_mode}'
    # Every label of the active workspace follows it, on the server and in the pages.
    assert compact_campaign_value('UK_Q2_SA_2026') == 'Q2_2026_SA'
    assert json.loads(client.get('/workspace-config').text.split('id="campaign-map" type="application/json">')[1]
                      .split('</script>')[0])['format'] == 'Q{quarter}_{year}{_mode}'
    # It travels with the Mappings & Reference Data.
    document = json.loads(core._mappings_reference_data_archive_payload(core.active_workspace))
    assert document['version'] == 1 and document['campaign_map']['exceptions'][0]['label'] == 'Q1 baseline'
    assert client.put('/api/workspace-config/campaign-map', json={'campaign_map': None}).json()['campaign_map'] == (
        normalize_campaign_map(DEFAULT_CAMPAIGN_MAP))
    core._restore_workspace_mappings_reference_data(core.active_workspace, json.dumps(document).encode())
    assert load_campaign_map(core.repository)['exceptions'][0]['sources'] == ['UK_Q1_2026']
    client.put('/api/workspace-config/campaign-map', json={'campaign_map': None})
    assert compact_campaign_value('UK_Q2_SA_2026') == '2026-Q2-SA'
