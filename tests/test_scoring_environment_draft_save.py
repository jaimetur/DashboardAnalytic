"""Regression checks for environment drafts across independent section saves."""
import json
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('persist_changes', [True, False])
def test_environment_drafts_and_save_verification(persist_changes):
    script = Path('src/web_interface/static/js/scoring_config.js').read_text()
    start = script.index('  const environmentSaveSignature =')
    end = script.index('  const appendCell =', start)
    functions = script[start:end]
    program = '''
const clone = value => JSON.parse(JSON.stringify(value));
let activeProfileId = 'test', kpiDirty = true, saveQueue = Promise.resolve(), profileCollection = null;
const methodologyTitleInput = {value: 'Custom scoring methodology'};
let lastEnvironment = 'Drive - City';
const environmentSelect = {value: 'Drive - City'};
const syncEnvironmentSourceFields = () => {};
const renderEnvironmentOptions = () => {environmentSelect.value = Object.keys(configuration.scope.environments)[0];};
let configuration = {title: 'Custom scoring methodology', scope: {environments: {'Drive - City': {}, 'Walk - Train': {}}}};
const old = {active_profile_id: 'test', profiles: [{id: 'test', configuration: {title: 'Custom scoring methodology', scope: {environments: {DriveCity: {}}}}}]};
let stored = clone(old), persistChanges = PERSIST_CHANGES;
const normalizeProfileCollection = value => value;
const loadProfiles = async () => clone(stored);
const requestJson = async (_, options) => {
  const saved = JSON.parse(options.body);
  if (persistChanges) stored = clone(saved);
  return saved;
};
const profilesEndpoint = '/profiles';
const setProfileCollection = saved => { profileCollection = saved; configuration = saved.profiles[0].configuration; };
''' + functions + '''
(async () => {
  await saveConfiguration(latest => ({...latest, gap_priority: ['K1']}), 'test', true);
  const draft = clone(configuration);
  let verified = false, error = '';
  try {
    await saveConfiguration(latest => ({...latest, scope: clone(draft.scope)}), 'test', false, true);
    verified = true;
  } catch (failure) { error = failure.message; }
  console.log(JSON.stringify({configuration, verified, error, selected: environmentSelect.value}));
})();
'''
    program = program.replace('PERSIST_CHANGES', 'true' if persist_changes else 'false')
    output = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    saved = json.loads(output.stdout)
    assert set(saved['configuration']['scope']['environments']) == {'Drive - City', 'Walk - Train'}
    assert saved['configuration']['title'] == 'Custom scoring methodology'
    assert saved['configuration']['gap_priority'] == ['K1']
    assert saved['selected'] == 'Drive - City'
    assert saved['verified'] is persist_changes
    if not persist_changes:
        assert 'could not be verified' in saved['error']


def test_capture_selected_context_builds_and_saves_score_mapping():
    script = Path('src/web_interface/static/js/scoring_config.js').read_text()
    start = script.index('  const captureSelectedContext =')
    end = script.index('  const hydrateSelectedContext =', start)
    capture = script[start:end]
    program = '''
const anchors = [['low_score'], ['medium_score'], ['high_score'], ['ultra_score']];
const environmentSelect = {value: 'DriveCity'};
const pointInputValue = input => Number(input.value);
const contextDraftsForRow = row => row._contextDrafts || (row._contextDrafts = {});
''' + capture + '''
const values = {
  '[data-threshold="low"]': {value: '10'},
  '[data-threshold="medium"]': {value: '50'},
  '[data-threshold="high"]': {value: '90'},
  '[data-score-anchor="low_score"]': {value: '0'},
  '[data-score-anchor="medium_score"]': {value: '80'},
  '[data-score-anchor="high_score"]': {value: '95'},
  '[data-score-anchor="ultra_score"]': {value: '100'},
  '[data-max-points]': {value: '25'},
  '[data-ultra-mode]': {value: 'best_max'},
  '[data-ultra-value]': {value: ''},
};
const row = {querySelector: selector => values[selector] || null};
captureSelectedContext(row);
process.stdout.write(JSON.stringify(row._contextDrafts.DriveCity));
'''
    output = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    captured = json.loads(output.stdout)

    assert captured['max_points'] == '25'
    assert captured['thresholds'] == {'low': '10', 'medium': '50', 'high': '90'}
    assert captured['score_mapping'] == {
        'low_score': '0', 'medium_score': '80', 'high_score': '95', 'ultra_score': '100',
    }
