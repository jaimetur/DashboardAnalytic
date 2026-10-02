from pathlib import Path

from tests.test_scoring_results_controls import _function_source, _run_node_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_TEMPLATE = PROJECT_ROOT / 'src/web_interface/templates/scoring.html'
SCORING_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring.js'


def test_scoring_selection_loads_from_server_before_enabling_controls():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert "root.dataset.selectionUrl || '/api/scoring/selection'" in script
    assert 'data-selection-url="/api/scoring/selection"' in template
    assert "const body = await requestJson(selectionUrl);" in script
    assert 'applySavedCalculationSelection(body.selection);' in script
    assert 'selectionPersisted = body.persisted !== false;' in script
    assert 'if (!selectionPersisted) {' in script
    assert 'await persistCalculationSelection({force: true});' in script
    assert "calculationPanel.inert = true;" in script
    assert "calculationPanel.inert = false;" in script
    assert 'loadCalculationSelection();' in script
    assert 'localStorage' not in script


def test_scoring_selection_roundtrips_explicit_empty_filters_and_methodology():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert "const selectionFieldOrder = ['Region', 'City', 'Operator', 'Vendor', 'Campaign'];" in script
    assert "context_filters: Object.fromEntries(selectionFieldOrder.map(key => [key, filters[key] || []]))" in script
    assert "scoring_profile_id: String(scoringProfileSelect?.value || activeProfileId)" in script
    assert "const requested = filters[key] ?? filters[key.toLowerCase()] ?? [];" in script
    assert "option.selected = !option.disabled && selected.has(option.value.toLocaleLowerCase())" in script
    assert '.scoring-note[data-kind="warning"]' in template


def test_scoring_selection_saves_are_debounced_serialized_and_flushed_on_navigation():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert 'function scheduleSelectionSave()' in script
    assert '}, 250);' in script
    assert 'selectionSaveChain = selectionSaveChain.catch(() => null).then(async () =>' in script
    assert 'if (!force && key === lastQueuedSelectionKey) return selectionSaveChain;' in script
    assert 'if (key === lastSavedSelectionKey || key === lastQueuedSelectionKey)' not in script
    assert 'client_id: selectionClientId, client_revision: clientRevision' in script
    assert "window.addEventListener('pagehide', flushSelectionSaveOnPageHide);" in script
    assert 'keepalive: true,' in script
    assert 'if (selectionPersisted && key === lastSavedSelectionKey && key === lastQueuedSelectionKey) return;' in script
    assert 'if (!selectionLoaded || restoringSelection || !selectionDirty) return;' in script


def test_job_selection_restoration_maps_job_fields_and_schedules_persistence():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    functions = '\n'.join(_function_source(script, name) for name in (
        'restoreCalculationSelectionFromJob', 'scheduleSelectionSave',
    ))
    program = r'''
let applied, persisted = false, timeoutDelay, timeoutCallback;
let restoringSelection = false, selectionLoaded = true, selectionDirty = false;
let selectionSaveTimer = null;
const applySavedCalculationSelection = selection => {applied = selection;};
const persistCalculationSelection = () => {persisted = true;};
const window = {
  clearTimeout: () => {},
  setTimeout: (callback, delay) => {timeoutCallback = callback; timeoutDelay = delay; return 42;},
};
''' + functions + r'''
restoreCalculationSelectionFromJob({
  dataset_ids: [12, '13'], aggregation_levels: ['City', 'Vendor'], levels: ['Legacy'],
  nr_mode: 'NR', baseline_operator: 'EE', scoring_profile_id: 'profile-7',
  context_filters: {Region: ['North'], City: [], Operator: ['EE'], Vendor: [], Campaign: ['Spring']},
});
const queued = {applied, selectionDirty, selectionSaveTimer, timeoutDelay};
timeoutCallback();
process.stdout.write(JSON.stringify({queued, persisted}));
'''
    result = _run_node_json(program, {})
    assert result['queued']['applied'] == {
        'dataset_ids': [12, '13'], 'aggregation_levels': ['City', 'Vendor'],
        'nr_mode': 'NR', 'baseline_operator': 'EE', 'scoring_profile_id': 'profile-7',
        'context_filters': {
            'Region': ['North'], 'City': [], 'Operator': ['EE'], 'Vendor': [], 'Campaign': ['Spring'],
        },
    }
    assert result['queued']['selectionDirty'] is True
    assert result['queued']['selectionSaveTimer'] == 42
    assert result['queued']['timeoutDelay'] == 250
    assert result['persisted'] is True


def test_job_selection_restoration_uses_legacy_levels_field():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    restore = _function_source(script, 'restoreCalculationSelectionFromJob')
    program = r'''
let applied;
const applySavedCalculationSelection = selection => {applied = selection;};
const scheduleSelectionSave = () => {};
''' + restore + r'''
restoreCalculationSelectionFromJob({dataset_ids: [5], levels: ['Operator', 'City']});
process.stdout.write(JSON.stringify(applied));
'''
    result = _run_node_json(program, {})
    assert result['aggregation_levels'] == ['Operator', 'City']
    assert result['dataset_ids'] == [5]
    assert result['context_filters'] == {}


def test_job_selection_restoration_clears_filters_on_actual_controls():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    apply_saved = _function_source(script, 'applySavedCalculationSelection')
    restore = _function_source(script, 'restoreCalculationSelectionFromJob')
    program = r'''
let restoringSelection = false, message = '';
const selectionFieldOrder = ['Region', 'City'];
const nrFilter = {value: 'NSA', options: [{value: 'NSA'}, {value: 'NR'}]};
const datasetInput = {value: '8', checked: true, closest: () => ({hidden: false})};
const datasetInputs = [datasetInput];
const aggregationInputs = [
  {value: 'Operator', checked: true}, {value: 'City', checked: true}, {value: 'Region', checked: true},
];
const baselineInput = {value: 'EE', options: [{value: 'EE'}]};
const scoringProfileSelect = {value: 'profile-1'};
const activeProfileId = 'profile-1';
const scoringProfileById = new Map();
const applyNrFilter = () => {};
const updateSelection = () => {};
const applyProfileHierarchy = () => {};
const uniqueCatalogueValues = values => [...new Set(values.map(String))];
const filterSelect = values => ({
  options: values.map(value => ({value, disabled: false, selected: true})),
  dispatchEvent: () => {},
});
const contextFilterSelects = new Map([
  ['Region', filterSelect(['North'])], ['City', filterSelect(['Paris'])],
]);
const Event = class {constructor(type, options) {this.type = type; this.options = options;}};
const setMessage = text => {message = text;};
const scheduleSelectionSave = () => {};
''' + apply_saved + restore + r'''
restoreCalculationSelectionFromJob({dataset_ids: [], aggregation_levels: ['Operator'], context_filters: {}});
process.stdout.write(JSON.stringify({
  datasetChecked: datasetInput.checked,
  aggregationChecked: aggregationInputs.map(input => input.checked),
  filters: [...contextFilterSelects].map(([key, select]) => [key, select.options.map(option => option.selected)]),
  message,
}));
'''
    result = _run_node_json(program, {})
    assert result['datasetChecked'] is False
    assert result['aggregationChecked'] == [True, False, False]
    assert result['filters'] == [['Region', [False]], ['City', [False]]]
    assert result['message'] == ''


def test_only_explicit_job_list_selection_restores_saved_calculation_selection():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    handler_start = script.index("  for (const list of jobLists) list.addEventListener('click', async event => {")
    handler_end = script.index("\n  root.addEventListener('click',", handler_start)
    job_list_handler = script[handler_start:handler_end]
    load_job = _function_source(script, 'loadJob')

    assert job_list_handler.count('restoreCalculationSelectionFromJob(job);') == 1
    assert 'await loadJob(job, true);' in job_list_handler
    assert 'restoreCalculationSelectionFromJob' not in load_job
