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
let lastEnvironment = 'Drive - City';
const environmentSelect = {value: 'Drive - City'};
const syncEnvironmentSourceFields = () => {};
const renderEnvironmentOptions = () => {environmentSelect.value = Object.keys(configuration.scope.environments)[0];};
let configuration = {scope: {environments: {'Drive - City': {}, 'Walk - Train': {}}}};
const old = {active_profile_id: 'test', profiles: [{id: 'test', configuration: {scope: {environments: {DriveCity: {}}}}}]};
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
    assert saved['configuration']['gap_priority'] == ['K1']
    assert saved['selected'] == 'Drive - City'
    assert saved['verified'] is persist_changes
    if not persist_changes:
        assert 'could not be verified' in saved['error']
