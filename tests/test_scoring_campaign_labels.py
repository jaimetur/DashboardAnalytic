"""Campaign presentation preserves source identities across web and PowerPoint."""
import pytest

from src.modules.scoring_views import _hierarchy_display_value
from tests.test_scoring_results_controls import SCORING_SCRIPT, _function_source, _run_node_json


@pytest.mark.parametrize('raw, expected', [
    ('UK_Q1_2026', '2026-Q1'), ('UK_Q2_2026', '2026-Q2'),
    ('2026_Q3', '2026-Q3'), ('Germany q4 2025', '2025-Q4'),
    ('2026-Q1', '2026-Q1'), ('Special campaign', 'Special campaign'),
])
def test_campaign_display_matches_in_web_and_powerpoint(raw, expected):
    script = SCORING_SCRIPT.read_text()
    helpers = '\n'.join(_function_source(script, name) for name in (
        'hierarchyDisplayValue', 'hierarchyPathEntry', 'hierarchyPrefixKey',
    ))
    program = "const payload = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + helpers + r'''
const column = {path: [{level: 'Campaign', value: payload.raw}]};
process.stdout.write(JSON.stringify({
  campaign: hierarchyDisplayValue(column.path[0]),
  other: hierarchyDisplayValue({level: 'City', value: payload.raw}),
  entry: hierarchyPathEntry(column, 0, ['Campaign']),
  key: hierarchyPrefixKey(column, 0, ['Campaign']),
}));
'''
    actual = _run_node_json(program, {'raw': raw})
    assert actual['campaign'] == expected == _hierarchy_display_value({'level': 'Campaign', 'value': raw})
    assert actual['other'] == raw
    assert actual['entry']['rawValue'] == raw
    assert raw in actual['key']
