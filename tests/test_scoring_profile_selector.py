from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import src.DriveTestAnalyzer as app_module
from src.modules.repository import Repository
from tests.scoring_fixtures import scoring_configuration


class _ScoringProfileSelectParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_profile_select = False
        self.profiles: list[dict[str, object]] = []
        self.current: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == 'select' and 'data-scoring-profile' in attributes:
            self.in_profile_select = True
        elif tag == 'option' and self.in_profile_select:
            self.current = {
                'id': attributes.get('value'),
                'selected': 'selected' in attributes,
                'name': '',
            }

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current['name'] = str(self.current['name']) + data

    def handle_endtag(self, tag: str) -> None:
        if tag == 'option' and self.current is not None:
            self.profiles.append(self.current)
            self.current = None
        elif tag == 'select' and self.in_profile_select:
            self.in_profile_select = False


def test_scoring_calculation_selector_lists_profiles_and_defaults_to_active(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    workspace = app_module.active_workspace
    repository = Repository(
        workspace.database_path,
        global_db_path=app_module.repository.db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    repository.initialize()
    repository.replace_scoring_configuration(scoring_configuration())

    profiles = repository.get_scoring_profiles()
    active_id = profiles['active_profile_id']
    alternate = deepcopy(profiles['profiles'][0])
    alternate.update({'id': 'netcheck-alt', 'name': 'Alternative methodology'})
    profiles['profiles'].append(alternate)
    repository.replace_scoring_profiles(profiles)

    page = client.get('/scoring')
    assert page.status_code == 200
    assert '<label class="scoring-profile-choice">Scoring Methodology' in page.text
    parser = _ScoringProfileSelectParser()
    parser.feed(page.text)
    assert [profile['id'] for profile in parser.profiles] == [active_id, 'netcheck-alt']
    assert [profile['selected'] for profile in parser.profiles] == [True, False]

    config_match = re.search(
        r'<script type="application/json" data-scoring-config>(.*?)</script>', page.text, re.DOTALL,
    )
    assert config_match
    page_config = json.loads(config_match.group(1))
    alternate_page_profile = next(
        profile for profile in page_config['scoring_profiles'] if profile['id'] == 'netcheck-alt'
    )
    # The aggregation hierarchy is an application setting, not part of a methodology.
    assert alternate_page_profile == {'id': 'netcheck-alt', 'name': 'Alternative methodology'}
    assert page_config['active_profile_id'] == active_id

    script = (Path(__file__).parents[1] / 'src/web_interface/static/js/scoring.js').read_text(encoding='utf-8')
    assert 'scoring_profile_id: scoringProfileSelect?.value || undefined' in script
