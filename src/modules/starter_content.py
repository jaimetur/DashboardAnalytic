"""Starter content of every workspace: what it needs to show charts as soon as it has CDRs.

New deployments and new workspaces, and existing workspaces once, receive the content shipped in
``assets`` that they do not have yet (matched by name, so nothing of theirs is replaced):

- ``assets/scoring-methodologies/*.json``: Scoring & GAP Analysis methodologies (portable format);
- ``assets/ppt-templates/<nsa|sa>/*.csv``: Report Templates, named after their file;
- ``assets/ppt-dashboards/*.json``: PPT Dashboards, which use those templates;
- ``assets/autocalculated-fields/default-autocalculated-fields.json``: the Auto-calculated Fields every new
  workspace starts with, which the templates use;
- ``assets/scoring-report-configurations/*.json``: saved Scoring report configurations (``name`` and
  ``configuration``);
- ``assets/query-builder-queries/*.json``: saved Query Builder queries (``name``, ``description`` and
  ``query_sql`` on the ``selected_data``, ``selected_voice`` and ``selected_speech`` views);
- ``assets/reporting-jobs/*.json``: Reporting Jobs, which name their Dashboards (``dashboard``: ``name`` and
  ``template_technology``) and their Scoring report configuration (``report_configuration``).

The Vendor Maps of a new workspace come from ``assets/labels-vendors/default-vendor-maps.json`` (see ``repository``);
the default Campaign Maps from ``assets/labels-campaigns/default-campaign-map.json`` (see ``column_names``).
The shipped content names no Operator or Vendor, so it fits any market.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.modules.column_names import column_identity

ASSETS = PROJECT_ROOT / 'assets'
STATE_KEY = 'starter_content_initialized_v2'
DASHBOARDS_STATE_KEY = 'ppt_dashboards_v2'
SCORING_STATE_KEY = 'scoring_configuration'


def _json_files(folder: Path) -> list[Path]:
    return sorted(folder.glob('*.json')) if folder.is_dir() else []


def _seed_methodologies(repository: Any) -> int:
    from src.modules.scoring_config import unwrap_scoring_profiles_payload, validate_scoring_profiles

    added = 0
    for path in _json_files(ASSETS / 'scoring-methodologies'):
        shipped = unwrap_scoring_profiles_payload(json.loads(path.read_text(encoding='utf-8')))
        if not shipped:
            continue
        raw = repository.get_workspace_state(SCORING_STATE_KEY)
        if raw is None or not raw.strip():
            repository.replace_scoring_profiles(shipped)
            added += len(shipped['profiles'])
            continue
        current = repository.get_scoring_profiles()
        known = {profile['id'] for profile in current['profiles']} | {profile['name'].casefold() for profile in current['profiles']}
        new = [profile for profile in shipped['profiles']
               if profile['id'] not in known and profile['name'].casefold() not in known]
        if new:
            repository.replace_scoring_profiles(validate_scoring_profiles({
                'active_profile_id': current['active_profile_id'], 'profiles': [*current['profiles'], *new]}))
            added += len(new)
    return added


def _seed_templates(repository: Any, username: str) -> int:
    added = 0
    for folder in sorted((ASSETS / 'ppt-templates').glob('*')) if (ASSETS / 'ppt-templates').is_dir() else []:
        technology = folder.name.casefold()
        if not folder.is_dir() or technology not in {'nsa', 'sa'}:
            continue
        existing = {str(row['name']).casefold() for row in repository.list_report_templates(technology)}
        for path in sorted(folder.glob('*.csv')):
            if path.stem.casefold() in existing:
                continue
            repository.add_report_template(technology, path.stem, path.read_bytes(), updated_by=username)
            added += 1
    return added


def _seed_dashboards(repository: Any) -> int:
    stored = repository.get_workspace_state(DASHBOARDS_STATE_KEY)
    dashboards = json.loads(stored) if stored else {}
    if not isinstance(dashboards, dict):
        return 0
    existing = {(str(item.get('name') or '').casefold(), str(item.get('template_technology') or item.get('technology') or ''))
                for item in dashboards.values() if isinstance(item, dict)}
    added = 0
    for path in _json_files(ASSETS / 'ppt-dashboards'):
        definition = json.loads(path.read_text(encoding='utf-8'))
        key = (str(definition.get('name') or '').casefold(), str(definition.get('template_technology') or definition.get('technology') or ''))
        if not key[0] or key in existing:
            continue
        dashboards[str(uuid.uuid4())] = definition
        existing.add(key)
        added += 1
    if added:
        repository.set_workspace_state(DASHBOARDS_STATE_KEY, json.dumps(dashboards))
    return added


def _seed_calculated_dimensions(repository: Any) -> int:
    """Add the shipped Auto-calculated Fields a workspace already set up does not have."""
    if repository.get_workspace_state('calculated_dimensions_initialized') != '1':
        # Not set up yet: it starts from the shipped definitions when it is first used.
        return 0
    path = ASSETS / 'autocalculated-fields' / 'default-autocalculated-fields.json'
    shipped = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    current = repository.list_calculated_dimensions()
    known = {column_identity(item.get('name', '')) for item in current}
    missing = [item for item in shipped if column_identity(item.get('name', '')) not in known]
    if not missing:
        return 0
    from src.modules.cdr_reporting import calculated_dimensions_json, parse_calculated_dimensions
    # The CDRs get the new fields when the workspace materializes them in the background.
    repository.replace_calculated_dimensions(calculated_dimensions_json(parse_calculated_dimensions([*current, *missing])))
    return len(missing)


def _shipped_report_configurations() -> dict[str, dict[str, Any]]:
    configurations = {}
    for path in _json_files(ASSETS / 'scoring-report-configurations'):
        item = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(item, dict) and str(item.get('name') or '').strip():
            configurations[str(item['name']).strip()] = item['configuration']
    return configurations


def _seed_report_configurations(repository: Any) -> int:
    from src.modules.scoring_reports import load_report_state, save_named_configuration

    existing = {item['name'].casefold() for item in load_report_state(repository)['configurations']}
    added = 0
    for name, configuration in _shipped_report_configurations().items():
        if name.casefold() not in existing:
            save_named_configuration(repository, name, configuration)
            added += 1
    return added


def _seed_queries(repository: Any, username: str) -> int:
    existing = {str(row['name']).casefold() for row in repository.list_query_builder_queries()}
    added = 0
    for path in _json_files(ASSETS / 'query-builder-queries'):
        item = json.loads(path.read_text(encoding='utf-8'))
        name = str(item.get('name') or '').strip()
        if not name or name.casefold() in existing or not str(item.get('query_sql') or '').strip():
            continue
        # No CDRs are chosen: the query runs on the CDRs chosen in Query Builder.
        repository.save_query_builder_query(name, str(item.get('description') or ''), str(item['query_sql']), [], username)
        added += 1
    return added


def _seed_reporting_jobs(repository: Any, username: str) -> int:
    from src.modules import report_tasks

    stored = repository.get_workspace_state(DASHBOARDS_STATE_KEY)
    dashboards = json.loads(stored) if stored else {}
    dashboard_ids = {(str(item.get('name') or '').casefold(), str(item.get('template_technology') or '')): key
                     for key, item in (dashboards.items() if isinstance(dashboards, dict) else []) if isinstance(item, dict)}
    configurations = {name.casefold(): configuration for name, configuration in _shipped_report_configurations().items()}
    existing = {task['name'].casefold() for task in report_tasks.list_tasks(repository)}
    added = 0
    for path in _json_files(ASSETS / 'reporting-jobs'):
        item = json.loads(path.read_text(encoding='utf-8'))
        name = str(item.get('name') or '').strip()
        if not name or name.casefold() in existing:
            continue
        definition = dict(item.get('definition') or {})
        entries = []
        for entry in definition.get('dashboards') or []:
            target = entry.get('dashboard') or {}
            dashboard_id = dashboard_ids.get((str(target.get('name') or '').casefold(), str(target.get('template_technology') or '')))
            if dashboard_id:
                entries.append({**{key: value for key, value in entry.items() if key != 'dashboard'}, 'dashboard_id': dashboard_id})
        definition['dashboards'] = entries
        scoring = []
        for entry in definition.get('scoring') or []:
            configuration = configurations.get(str(entry.get('report_configuration') or '').casefold())
            if configuration:
                scoring.append({**{key: value for key, value in entry.items() if key != 'report_configuration'},
                                'report': {**configuration, 'name': entry['report_configuration']}})
        definition['scoring'] = scoring
        if not (entries or scoring):
            continue
        report_tasks.save_task(repository, None, {**item, 'definition': definition}, username,
                               parse_recipients=lambda value: [str(address) for address in value or []],
                               invalid_recipients=lambda _addresses: [])
        added += 1
    return added


def seed_starter_content(repository: Any, username: str = 'system') -> dict[str, int] | None:
    """Add the shipped starter content once per workspace; returns what was added, or None when done before."""
    if repository.get_workspace_state(STATE_KEY) == '1':
        return None
    added = {
        'methodologies': _seed_methodologies(repository),
        'report_templates': _seed_templates(repository, username),
        'dashboards': _seed_dashboards(repository),
        'auto_calculated_fields': _seed_calculated_dimensions(repository),
        'scoring_report_configurations': _seed_report_configurations(repository),
        'query_builder_queries': _seed_queries(repository, username),
    }
    # After the Dashboards and the report configurations, which the Reporting Jobs name.
    added['reporting_jobs'] = _seed_reporting_jobs(repository, username)
    repository.set_workspace_state(STATE_KEY, '1')
    if any(added.values()) and hasattr(repository, 'try_add_log'):
        repository.try_add_log(username, 'starter_content_added', json.dumps(added))
    return added
