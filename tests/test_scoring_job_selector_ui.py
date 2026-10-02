"""Saved scoring job cards select the results shown in the embedded dropdown."""
import re

import pytest

from tests.test_scoring_results_controls import (
    SCORING_SCRIPT, SCORING_TEMPLATE, _function_source, _run_node_json,
)


def test_job_dropdown_is_inside_results_header_and_constrained_to_button_column():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    header = template.split('<div class="scoring-results-head">', 1)[1].split(
        '<div class="scoring-result-tabs"', 1,
    )[0]
    assert template.count('data-job-list') == 2
    assert template.index('class="panel scoring-results-panel"') < template.index('class="panel scoring-jobs-panel"')
    assert header.index('class="scoring-results-tools"') < header.index('data-scoring-job-selector')
    assert '<summary class="scoring-job-item"' in header
    assert 'data-selected-job-card' in header and 'data-job-list' in header
    assert re.search(r'\.scoring-job-selector\s*\{[^}]*grid-column: 2;[^}]*grid-row: 2;'
                     r'[^}]*justify-self: end;[^}]*width: 100%;[^}]*min-width: 0;'
                     r'[^}]*contain: inline-size;', template)
    assert '.scoring-results-panel { position: relative; z-index: 2; overflow: visible; }' in template
    assert '.scoring-job-selector .scoring-job-item-top strong { white-space: normal;' in template


def test_job_dropdown_selected_card_tracks_selection_and_retains_job_actions():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    program = r'''
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.style = {}; }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.text = ''; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  cloneNode() {
    const copy = new Element(this.tag);
    copy.text = this.text; copy.dataset = {...this.dataset}; copy.attributes = {...this.attributes};
    copy.children = this.children.map(child => child.cloneNode(true));
    return copy;
  }
}
const document = {createElement: tag => new Element(tag)};
const countBadge = new Element('span');
const historyCountBadge = new Element('span');
const root = {querySelectorAll: () => [countBadge, historyCountBadge]};
const jobList = new Element('div'), historyList = new Element('div'), selectedJobCard = new Element('span');
const jobLists = [jobList, historyList];
const jobs = [
  {id: '20', status: 'completed', label: 'Latest job', baseline_operator: 'EE', scoring_profile_name: 'Profile A'},
  {id: '15', status: 'processing', label: 'Earlier job', baseline_operator: 'O2', scoring_profile_name: 'Profile B'},
];
let selectedJobId = '20';
const sortedJobs = jobs => jobs;
const jobIdOf = job => job.id;
const normalizeStatus = job => job.status;
const jobCardTitleSegments = job => [{dimension: 'neutral', value: job.label}];
const jobCardTitle = job => job.label;
const valueOf = (job, keys, fallback) => keys.map(key => job[key]).find(value => value !== undefined) ?? fallback;
const jobLevels = () => 'Operator';
const jobCdrNames = () => ['Example CDR.xlsx'];
const jobCdrSummary = () => 'Example CDR.xlsx';
const isActive = job => job.status === 'processing';
const progressValue = () => 40;
const deletingJobIds = new Set();
''' + _function_source(script, 'syncJobLists') + _function_source(script, 'renderJobs') + r'''
renderJobs();
const latest = selectedJobCard.textContent;
const cards = jobList.children.map(row => ({id: row.children[0].dataset.jobId,
  selected: row.children[0].attributes['aria-current'], deleteId: row.children[2].dataset.deleteJobId}));
const separateCopy = selectedJobCard.children[0] !== jobList.children[0].children[0].children[0];
const historyMatches = historyList.children.every((row, index) => {
  const original = jobList.children[index];
  return row.textContent === original.textContent
    && row.children[0].dataset.jobId === original.children[0].dataset.jobId
    && row.children[0].attributes['aria-current'] === original.children[0].attributes['aria-current']
    && row.children[2].dataset.deleteJobId === original.children[2].dataset.deleteJobId;
});
const historyCounts = [countBadge.textContent, historyCountBadge.textContent];
selectedJobId = '15';
renderJobs();
const earlier = selectedJobCard.textContent;
jobs.length = 0;
renderJobs();
process.stdout.write(JSON.stringify({latest, earlier, cards, separateCopy, historyMatches, historyCounts, emptyHistory: historyList.textContent, empty: selectedJobCard.textContent}));
'''
    result = _run_node_json(program, {})
    assert 'Latest job' in result['latest'] and 'Profile A' in result['latest']
    assert 'Earlier job' in result['earlier'] and 'Profile B' in result['earlier']
    assert 'processing' in result['earlier']
    assert 'Example CDR.xlsx' not in result['earlier']
    assert '1 CDR' in result['earlier']
    assert result['cards'] == [
        {'id': '20', 'selected': 'true', 'deleteId': '20'},
        {'id': '15', 'selected': 'false', 'deleteId': '15'},
    ]
    assert result['separateCopy'] and result['historyMatches']
    assert result['historyCounts'] == ['2 jobs', '2 jobs']
    assert 'No scoring jobs have been run' in result['emptyHistory']
    assert result['empty'] == 'No saved scoring jobs'


@pytest.mark.parametrize('list_index', [0, 1])
def test_choosing_job_from_either_list_loads_selected_results(list_index):
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    start = script.index("  for (const list of jobLists) list.addEventListener('click', async event => {")
    end = script.index("\n  root.addEventListener('click',", start)
    program = r'''
let loaded, persisted = false, focused = false, deleted;
const handlers = [];
const jobLists = [0, 1].map(() => ({addEventListener: (_name, callback) => {handlers.push(callback);}}));
const jobs = [{id: '20'}, {id: '15'}];
const jobIdOf = job => job.id;
let userSelectedJob = false, selectedJobId = '20', selectedJob = jobs[0];
const root = {querySelector: () => ({scrollIntoView: () => {focused = true;}})};
const jobSelector = {open: true, contains: () => LIST_INDEX === 0, querySelector: () => ({focus: () => {focused = true;}})};
const persistScoringViewState = () => {persisted = true;};
const loadJob = async (job, force) => {loaded = {id: job.id, force};};
const deleteJob = id => {deleted = id;};
''' + f'\nconst LIST_INDEX = {list_index};\n' + script[start:end] + f'\nconst handler = handlers[{list_index}];\n' + r'''
(async () => {
  await handler({target: {closest: selector => selector === '[data-job-id]' ? {dataset: {jobId: '15'}} : null}});
  const selection = {loaded, persisted, focused, open: jobSelector.open, selectedJobId, userSelectedJob};
  loaded = null;
  await handler({target: {closest: () => ({dataset: {deleteJobId: '20'}})}});
  process.stdout.write(JSON.stringify({selection, deleted, loaded}));
})();
'''
    result = _run_node_json(program, {})
    assert result['selection'] == {
        'loaded': {'id': '15', 'force': True}, 'persisted': True, 'focused': True,
        'open': False, 'selectedJobId': '15', 'userSelectedJob': True,
    }
    assert result['deleted'] == '20' and result['loaded'] is None


def test_export_actions_remain_visible_and_disabled_until_results_are_available():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    for kind in ('scoring', 'gap', 'ppt'):
        assert f'data-export-{kind} aria-disabled="true" tabindex="-1"' in template
        assert f'data-export-{kind} hidden' not in template
    program = r'''
const links = ['scoring', 'gap', 'ppt'].map(() => ({hidden: true, attributes: {},
  setAttribute(key, value) {this.attributes[key] = value;}}));
const root = {querySelector: selector => links[['[data-export-scoring]', '[data-export-gap]', '[data-export-ppt]'].indexOf(selector)]};
const exportBase = '/scoring/jobs';
const selectedTableMode = () => 'expanded';
const selectedGapLayout = () => 'end';
const selectedEnvironment = 'all';
const showGapValues = () => false;
''' + _function_source(script, 'setExportLinks') + r'''
setExportLinks('21', false);
const unavailable = links.map(link => ({hidden: link.hidden, disabled: link.attributes['aria-disabled'], tabIndex: link.tabIndex, href: link.href}));
setExportLinks('21', true);
const available = links.map(link => ({hidden: link.hidden, disabled: link.attributes['aria-disabled'], tabIndex: link.tabIndex, href: link.href}));
setExportLinks('', false);
const reset = links.map(link => link.attributes['aria-disabled']);
process.stdout.write(JSON.stringify({unavailable, available, reset}));
'''
    result = _run_node_json(program, {})
    assert all(link == {'hidden': False, 'disabled': 'true', 'tabIndex': -1, 'href': '#'}
               for link in result['unavailable'])
    assert all(link['hidden'] is False and link['disabled'] == 'false' and link['tabIndex'] == 0
               and link['href'].startswith('/scoring/jobs/21/export/') for link in result['available'])
    assert result['reset'] == ['true', 'true', 'true']
