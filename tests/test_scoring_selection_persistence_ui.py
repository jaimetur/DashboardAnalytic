from pathlib import Path
from html.parser import HTMLParser

from tests.test_scoring_results_controls import _function_source, _run_node_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_TEMPLATE = PROJECT_ROOT / 'src/web_interface/templates/scoring.html'
SCORING_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring.js'


class _ScoringMarkupParser(HTMLParser):
    _VOID_ELEMENTS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.elements = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.elements.append((tag, attributes, tuple(self.stack)))
        if tag not in self._VOID_ELEMENTS:
            self.stack.append((tag, attributes))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


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


def test_scoring_calculation_picker_orders_cdr_aggregation_and_gap_reference_controls():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    parser = _ScoringMarkupParser()
    parser.feed(template)
    elements = parser.elements

    assert 'Select CDRs, filters, Split by &amp; GAP reference' in template
    assert template.index('<label>NR Mode') < template.index('<strong>CDR datasets</strong>')
    assert template.index('<strong>CDR datasets</strong>') < template.index('<strong>Split by</strong>')
    assert template.index('<strong>Split by</strong>') < template.index('id="scoring-gap-reference-title"')

    buttons = [
        (attrs, ancestors) for tag, attrs, ancestors in elements
        if tag == 'button' and attrs.get('data-scoring-select-datasets')
    ]
    assert [attrs['data-scoring-select-datasets'] for attrs, _ancestors in buttons] == ['all', 'latest', 'latest-two']
    for _attrs, ancestors in buttons:
        assert any(
            ancestor_attrs.get('class') == 'scoring-dataset-actions'
            for _tag, ancestor_attrs in ancestors
        )
        assert any(
            ancestor_attrs.get('class') == 'scoring-picker'
            for _tag, ancestor_attrs in ancestors
        )

    gap_select = next(
        (attrs, ancestors) for tag, attrs, ancestors in elements
        if tag == 'select' and 'data-baseline-operator' in attrs
    )
    assert any(
        ancestor_attrs.get('aria-labelledby') == 'scoring-gap-reference-title'
        for _tag, ancestor_attrs in gap_select[1]
    )


def test_cdr_shortcuts_select_latest_two_or_all_visible_and_keep_gap_reference_in_selection():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    handler_start = script.index("  root.querySelectorAll('[data-scoring-select-datasets]').forEach(button => {")
    handler_end = script.index("\n\n  datasetInputs.forEach(input => input.addEventListener", handler_start)
    functions = '\n'.join(_function_source(script, name) for name in (
        'datasetNameDate', 'selectLatestDatasetForEachKind', 'calculationSelectionFromControls',
    ))
    handlers = script[handler_start:handler_end]
    program = r'''
const selectedAreaSummary = () => ({enabled: false});
const selectedIds = [];
const datasetInputs = [];
const datasetOptions = [];
const datasetKindOrder = ['data', 'voice', 'speech'];
const selectedButtons = new Map();
let updateCount = 0, saveCount = 0;
const root = {querySelectorAll: () => buttons};
const buttons = ['all', 'latest', 'latest-two'].map(choice => ({
  dataset: {scoringSelectDatasets: choice},
  addEventListener: (_name, handler) => selectedButtons.set(choice, handler),
}));
const updateSelection = () => {updateCount += 1;};
const scheduleSelectionSave = () => {saveCount += 1;};
const selectedDatasetIds = () => datasetInputs
  .filter(input => input.checked && !input.option.hidden).map(input => input.value);
const selectedLevels = () => ['Operator', 'Region'];
const selectedContextFilters = () => ({Region: [], City: [], Operator: [], Vendor: [], Campaign: []});
const selectionFieldOrder = ['Region', 'City', 'Operator', 'Vendor', 'Campaign'];
const nrFilter = {value: 'NSA'};
const baselineInput = {value: 'GAP reference O2'};
const scoringProfileSelect = {value: 'methodology-1'};
const activeProfileId = 'methodology-1';
function addDataset(kind, id, date, nrMode = 'NSA') {
  const input = {value: String(id), checked: true};
  const option = {hidden: nrMode !== 'NSA', dataset: {datasetKind: kind, uploadedAt: date, nrMode},
    querySelector: () => input};
  input.option = option;
  datasetInputs.push(input); datasetOptions.push(option);
  return input;
}
addDataset('data', 1, '2026-08-01T00:00:00Z');
addDataset('data', 2, '2026-08-01T00:00:00Z');
addDataset('data', 3, '2026-07-31T00:00:00Z');
addDataset('data', 99, '2026-09-01T00:00:00Z', 'SA');
addDataset('voice', 10, '');
addDataset('voice', 11, '');
addDataset('speech', 14, '');
''' + functions + '\n' + handlers + r'''
async function main() {
  selectedButtons.get('latest-two')();
  const latestTwo = [...selectedDatasetIds()].map(Number).sort((a, b) => a - b);
  const savedCalculation = calculationSelectionFromControls();
  selectedButtons.get('latest')();
  const latestOne = [...selectedDatasetIds()].map(Number).sort((a, b) => a - b);
  selectedButtons.get('all')();
  const allVisible = [...selectedDatasetIds()].map(Number).sort((a, b) => a - b);
  process.stdout.write(JSON.stringify({latestTwo, latestOne, allVisible, savedCalculation, updateCount, saveCount}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = _run_node_json(program, {})
    assert result['latestTwo'] == [1, 2, 10, 11, 14]
    assert result['latestOne'] == [2, 11, 14]
    assert result['allVisible'] == [1, 2, 3, 10, 11, 14]
    assert result['savedCalculation'] == {
        'dataset_ids': [1, 2, 10, 11, 14], 'aggregation_levels': ['Operator', 'Region'],
        'nr_mode': 'NSA', 'baseline_operator': 'GAP reference O2',
        'scoring_profile_id': 'methodology-1',
        'context_filters': {'Region': [], 'City': [], 'Operator': [], 'Vendor': [], 'Campaign': []},
        'area_summary': {'enabled': False},
    }
    assert result['updateCount'] == 3
    assert result['saveCount'] == 3


def test_dataset_name_date_parses_supported_dates_and_rejects_invalid_calendar_values():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    parser = _function_source(script, 'datasetNameDate')
    program = parser + r'''
const values = [
  ['cdr_20260817.csv', Date.UTC(2026, 7, 17)],
  ['cdr-20260817.csv', Date.UTC(2026, 7, 17)],
  ['cdr_17-08-2026.csv', Date.UTC(2026, 7, 17)],
  ['cdr-17082026.csv', Date.UTC(2026, 7, 17)],
  ['cdr_2026-Q3.csv', Date.UTC(2026, 6, 1)],
  ['cdr_Q3-2026.csv', Date.UTC(2026, 6, 1)],
  ['cdr_2024-02-29.csv', Date.UTC(2024, 1, 29)],
];
const parsed = values.map(([name]) => datasetNameDate(name));
const invalid = [
  'cdr_2025-02-29.csv', 'cdr_2026-13-01.csv', 'cdr_2026-00-01.csv',
  'cdr_2026-04-31.csv', 'cdr_2026-Q0.csv', 'cdr_Q5-2026.csv',
].map(name => datasetNameDate(name));
process.stdout.write(JSON.stringify({expected: values.map(([, timestamp]) => timestamp), parsed, invalid}));
'''

    result = _run_node_json(program, {})
    assert result['parsed'] == result['expected']
    assert all(value is None for value in result['invalid'])


def test_latest_dataset_shortcuts_prioritize_filename_dates_then_upload_and_id_and_skip_hidden_nr():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    handler_start = script.index("  root.querySelectorAll('[data-scoring-select-datasets]').forEach(button => {")
    handler_end = script.index("\n\n  datasetInputs.forEach(input => input.addEventListener", handler_start)
    functions = '\n'.join(_function_source(script, name) for name in (
        'datasetNameDate', 'selectLatestDatasetForEachKind',
    ))
    handlers = script[handler_start:handler_end]
    program = r'''
const datasetInputs = [];
const datasetOptions = [];
const datasetKindOrder = ['data', 'voice', 'speech'];
const selectedButtons = new Map();
const buttons = ['latest', 'latest-two'].map(choice => ({
  dataset: {scoringSelectDatasets: choice},
  addEventListener: (_name, handler) => selectedButtons.set(choice, handler),
}));
const root = {querySelectorAll: () => buttons};
const updateSelection = () => {};
const scheduleSelectionSave = () => {};
function addDataset(kind, id, name, uploadedAt, nrMode = 'NSA') {
  const input = {value: String(id), checked: false};
  const option = {hidden: nrMode !== 'NSA', dataset: {
    datasetKind: kind, datasetName: name, uploadedAt, nrMode,
  }, querySelector: () => input};
  input.option = option;
  datasetInputs.push(input);
  datasetOptions.push(option);
}
addDataset('data', 1, 'cdr_2025-12-31.csv', '2026-12-01T00:00:00Z');
addDataset('data', 2, 'cdr_2026-03-01.csv', '2026-02-01T00:00:00Z');
addDataset('data', 3, 'cdr_2026-03-01.csv', '2026-02-01T00:00:00Z');
addDataset('data', 6, 'cdr_2026-03-01.csv', '2026-02-02T00:00:00Z');
addDataset('data', 4, 'cdr_2026-02-28.csv', '2026-03-01T00:00:00Z');
addDataset('data', 5, '', '2026-02-15T00:00:00Z');
addDataset('voice', 10, 'voice_invalid_date.csv', '2026-01-01T00:00:00Z');
addDataset('voice', 11, '', '2026-01-01T00:00:00Z');
addDataset('voice', 12, '', '2025-12-31T00:00:00Z');
addDataset('speech', 14, '', '');
addDataset('speech', 99, 'speech_2026-12-01.csv', '2026-12-01T00:00:00Z', 'SA');
''' + functions + '\n' + handlers + r'''
const selectedIds = () => datasetInputs
  .filter(input => input.checked && !input.option.hidden).map(input => Number(input.value)).sort((a, b) => a - b);
selectedButtons.get('latest-two')();
const latestTwo = selectedIds();
selectedButtons.get('latest')();
const latestOne = selectedIds();
selectLatestDatasetForEachKind(3);
const latestThree = selectedIds();
process.stdout.write(JSON.stringify({latestTwo, latestOne, latestThree}));
'''

    result = _run_node_json(program, {})
    assert result['latestTwo'] == [3, 6, 10, 11, 14]
    assert result['latestOne'] == [6, 11, 14]
    assert result['latestThree'] == [2, 3, 6, 10, 11, 12, 14]


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
        # A job without the National & area summary leaves it out.
        'area_summary': {'enabled': False},
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
const areaSummaryEnabled = null, areaSummaryTimeSplit = null, areaSummaryBreakdown = null, areaSummaryCities = null;
const syncAreaSummary = () => {}, refreshAreaSummaryCities = () => {};
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


def test_context_filters_keep_all_values_and_remembered_values_when_the_cdrs_change():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    refresh = _function_source(script, 'refreshContextFilterOptions')
    program = r'''
let selectedIds = ['sa'];
const datasetCatalogues = new Map([
  ['sa', {operators: ['VF', 'EE', 'VF-SA']}], ['nsa', {operators: ['VF', 'EE', 'VF-VoNR']}],
]);
const selectedDatasetIds = () => selectedIds;
const contextFilterDefinitions = [{key: 'Operator', catalogueKey: 'operators'}];
const uniqueCatalogueValues = values => [...new Set((values || []).map(String))];
const contextFilterOptions = (key, values) => values.map(value => ({value, label: value, color: ''}));
const scoringVendorName = value => value;
const mainCityIdentities = new Set();
const decorateOperatorOptions = () => {};
const refreshAreaSummaryCities = () => {};
const document = {createElement: () => ({value: '', textContent: '', selected: false, disabled: false, dataset: {}, style: {}})};
const Event = class {constructor(type) {this.type = type;}};
const select = {
  options: [], dataset: {},
  get selectedOptions() { return this.options.filter(option => option.selected); },
  replaceChildren() { this.options = []; },
  append(option) { this.options.push(option); },
  dispatchEvent() {},
};
const contextFilterSelects = new Map([['Operator', select]]);
''' + refresh + r'''
const state = () => select.options.map(option => option.value + (option.selected ? '*' : '')).join(' ');
const log = [];
refreshContextFilterOptions();
select.options.forEach(option => { option.selected = true; });
for (const ids of [['nsa'], ['sa']]) { selectedIds = ids; refreshContextFilterOptions(); log.push(state()); }
select.options.forEach(option => { option.selected = option.value !== 'VF'; });
for (const ids of [['nsa'], ['sa']]) { selectedIds = ids; refreshContextFilterOptions(); log.push(state()); }
process.stdout.write(JSON.stringify(log));
'''
    assert _run_node_json(program, {}) == [
        # All values stays All values: the Operators the new CDRs add are checked too.
        'VF* EE* VF-VoNR*', 'VF* EE* VF-SA*',
        # A partial choice keeps the values the other CDRs do not have, for when they come back.
        'VF EE* VF-VoNR', 'VF EE* VF-SA*',
    ]
