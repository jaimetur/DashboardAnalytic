"""Filters of the Scoring report editor: All, Main Cities, Select All / None and their summaries."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1] / 'src/web_interface/static/js/scoring_report_editor.js').read_text(encoding='utf-8')

# A minimal DOM: elements with children, inputs that toggle on click and fire their change listeners.
DOM = r'''
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.className = '';
    this.textContent = ''; this.hidden = false; this.checked = false; this.disabled = false; this.title = ''; this.classList = {add: name => { this.className += ` ${name}`; }}; }
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  setAttribute() {}
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatch(type) { (this.listeners[type] || []).forEach(listener => listener({target: this})); }
  click() { if (this.tagName === 'INPUT') { this.checked = !this.checked; this.dispatch('change'); } else this.dispatch('click'); }
  descendants() { return this.children.flatMap(child => [child, ...(child.descendants ? child.descendants() : [])]); }
  querySelector(selector) { return this.descendants().find(node => node.tagName === selector.toUpperCase()) || null; }
  get text() { return [this.textContent, ...this.children.map(child => child.text || '')].join(''); }
}
globalThis.document = {createElement: tag => new Element(tag), querySelectorAll: () => []};
'''


def _function(name: str) -> str:
    start = SCRIPT.index(f'  function {name}(')
    end = SCRIPT.index('\n  }\n', start) + 4
    return SCRIPT[start:end]


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_filters_keep_values_editable_check_main_cities_and_count_the_selection():
    el_start = SCRIPT.index('  const el = (tag, className, text) => {')
    el_end = SCRIPT.index('  };\n', el_start) + 5
    program = DOM + SCRIPT[el_start:el_end] + "const campaignField = () => false;\n" + _function('checkbox') + _function('checklist') + r'''
const result = {};
const saved = [];
const preset = {label: 'Main Cities', checked: false, values: ['belfast', 'Leeds', 'London'], onChange: checked => saved.push(['main', checked])};
const picker = checklist('City', ['Bangor', 'Belfast', 'Cardiff', 'Leeds'], [], values => saved.push(values), {preset, allOption: true});
const list = picker.children[1];
const rows = list.children.filter(node => node.tagName === 'LABEL');
const box = text => rows.find(row => row.text === text).querySelector('input');
const values = ['Bangor', 'Belfast', 'Cardiff', 'Leeds'];
const state = () => ({summary: picker.children[0].textContent, all: box('All').checked, main: box('Main Cities').checked,
  checked: values.filter(value => box(value).checked), disabled: values.filter(value => box(value).disabled)});
result.initial = state();
box('Main Cities').click(); result.mainCities = state();
box('Leeds').click(); result.afterUncheckingLeeds = state();
const toggle = list.children.find(node => node.tagName === 'BUTTON');
toggle.click(); result.selectAll = state();
toggle.click(); result.selectNone = state();
box('Bangor').click(); box('Cardiff').click(); result.twoValues = state();
result.saved = saved.slice(-1)[0];
console.log(JSON.stringify(result));
'''
    completed = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    # All keeps the values checked and editable.
    assert result['initial'] == {'summary': 'City: All', 'all': True, 'main': False, 'checked': ['Bangor', 'Belfast', 'Cardiff', 'Leeds'], 'disabled': []}
    # Main Cities checks the workspace main cities found in the CDRs and shows their number.
    assert result['mainCities'] == {'summary': 'City: Main Cities (2/4)', 'all': False, 'main': True, 'checked': ['Belfast', 'Leeds'], 'disabled': []}
    # Editing a value starts from what is shown: the preset becomes an explicit selection.
    assert result['afterUncheckingLeeds'] == {'summary': 'City: Belfast', 'all': False, 'main': False, 'checked': ['Belfast'], 'disabled': []}
    assert result['selectAll']['all'] is True and result['selectAll']['checked'] == ['Bangor', 'Belfast', 'Cardiff', 'Leeds']
    assert result['selectNone'] == {'summary': 'City: All', 'all': False, 'main': False, 'checked': [], 'disabled': []}
    assert result['twoValues']['summary'] == 'City: 2/4 selected'
    assert result['saved'] == ['Bangor', 'Cardiff']


def test_choosing_a_configuration_loads_it_and_unsaved_changes_ask_first():
    # No Load or Default buttons: the selector loads what is chosen, Default included.
    assert "button('Load'" not in SCRIPT and "button('Default'" not in SCRIPT
    assert "saved.addEventListener('change'" in SCRIPT
    assert "choices: [['cancel', 'Cancel'], ['discard', 'Discard changes', 'danger-button'], ['save', 'Save as…', 'primary-button']]" in SCRIPT
    # Every toolbar button has its icon; the JSON buttons share one colour and Delete is red.
    for kind in ('save', 'delete', 'export', 'import'):
        assert f"{kind}: '<path" in SCRIPT
    css = (Path(__file__).resolve().parents[1] / 'src/web_interface/static/css/app.css').read_text(encoding='utf-8')
    assert '.scoring-report-tool:is(.is-export, .is-import)' in css
    assert '.scoring-report-tool.is-delete { border-color: #c62828; background: #c62828;' in css


def test_the_selector_shows_the_configuration_whose_scenarios_are_shown():
    assert "const openedName = String(state.name || '');" in SCRIPT
    assert "close({configuration: {...clone(state), ...(chosenName ? {name: chosenName} : {})}, action});" in SCRIPT
    # Named configurations keep only their scenarios.
    assert "configuration: {scenarios: state.scenarios}" in SCRIPT
    # The selector follows the content: the saved configuration with the same scenarios, or none.
    assert "saved.replaceChildren(el('option', '', '<Not saved configuration>'));" in SCRIPT
    assert "current = matchingConfiguration();" in SCRIPT
    assert "const hasUnsavedChanges = () => !matchingConfiguration();" in SCRIPT
    assert "list.addEventListener('input', refreshDifferences);" in SCRIPT


def test_reporting_artifacts_show_the_cdrs_of_their_automatic_choice_and_tabs_sit_on_their_panel():
    root = Path(__file__).resolve().parents[1]
    script = (root / 'src/web_interface/static/js/report_jobs.js').read_text(encoding='utf-8')
    # Every automatic CDR choice shows the CDRs it selects now, checked in the locked list.
    assert 'preview = preview || {primary: datasets.map((item) => item.id)};' in script
    assert 'if (shown) box.checked = shown.has(Number(box.value));' in script
    css = (root / 'src/web_interface/static/css/report_jobs.css').read_text(encoding='utf-8')
    assert 'border-radius: 10px 10px 0 0;' in css and 'margin: .3rem 0 -1rem;' in css
    assert 'margin-bottom: -1px; padding: .62rem 1.15rem .6rem;' in css
    # Module artifacts (Non-Qualified Calls) sit inside #rj-providers and join the tabs as well.
    assert '.report-jobs :is(.rj-artifact-tabs ~ .rj-card, .rj-artifact-tabs ~ #rj-providers > .rj-card)[data-rj-module] { margin-top: 0;' in css


def test_every_reporting_artifact_with_cdrs_offers_the_two_automatic_choices():
    script = (Path(__file__).resolve().parents[1] / 'src/web_interface/static/js/report_jobs.js').read_text(encoding='utf-8')
    assert 'Every ready' not in script
    # CDR Analysis (in each NR Mode), Network Insights and Scoring share the picker with both choices.
    assert script.count('selected, NEWEST_COMPLETE_TEXT, allCompleteChoice(') == 2
    assert "allCompleteChoice(dataset.cdr_selection === 'all_complete'), automaticPreview());" in script
    # Dashboards keep their own CDR list with the same two choices.
    assert "{selection: config.cdr_selection || '', preview: automaticPreview(nrMode.value)}" in script


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_settings_that_differ_between_scenarios_are_highlighted_in_every_scenario():
    program = _function('settingValue') + _function('markDifferences') + r'''
const options = (enabled = true) => ({enabled, environments: 'all', charts: {service: true}, tables: {kpi_values: false},
  gap: {operators: ['VF', '3'], profile: true}});
const scenario = (filters, levels, mostReliable = true) => ({context_filters: filters, main_cities: false, aggregation_levels: levels,
  scorings: {best_network: options(), most_reliable: options(mostReliable)}});
const scenarios = [scenario({}, ['Operator', 'Campaign']), scenario({City: ['London']}, ['Operator', 'City', 'Campaign']),
  scenario({}, ['Operator', 'Campaign'], false)];
const keys = ['filter:City', 'filter:Region', 'level:City', 'level:Campaign', 'scoring:best_network:charts:service',
  'scoring:most_reliable:enabled', 'scoring:most_reliable:environments', 'scoring:best_network:gap:operators'];
const nodes = scenarios.flatMap((_item, index) => keys.map(key => {
  const classes = new Set();
  return {index, dataset: {diffKey: key}, classes, classList: {toggle: (name, on) => (on ? classes.add(name) : classes.delete(name))},
    closest: () => ({dataset: {scenarioIndex: String(index)}})};
}));
const list = {querySelectorAll: () => nodes};
const highlighted = () => scenarios.map((_item, index) => nodes.filter(node => node.index === index && node.classes.has('is-scenario-diff'))
  .map(node => node.dataset.diffKey));
markDifferences(list, scenarios);
const result = {differences: highlighted()};
scenarios[0].scorings.best_network.charts.service = false;
markDifferences(list, scenarios);
result.afterChange = highlighted()[2];
markDifferences(list, scenarios.slice(0, 1));
result.single = highlighted()[0];
console.log(JSON.stringify(result));
'''
    completed = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    # The City filter and level and the left-out Most Reliable scoring differ: they are highlighted in every scenario
    # where they apply (a left-out scoring has no environments to compare).
    assert result['differences'] == [
        ['filter:City', 'level:City', 'scoring:most_reliable:enabled'],
        ['filter:City', 'level:City', 'scoring:most_reliable:enabled'],
        ['filter:City', 'level:City', 'scoring:most_reliable:enabled'],
    ]
    # A changed option is highlighted at once, also in the scenarios that kept it.
    assert 'scoring:best_network:charts:service' in result['afterChange']
    # A single scenario has nothing to compare.
    assert result['single'] == []
