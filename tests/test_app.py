from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Event
from urllib.parse import quote
import warnings
import zipfile
from concurrent.futures import Future

import pandas as pd
import pytest
from fastapi import BackgroundTasks

from src.modules.auth import hash_password
from src.version import __release_date__, __version__

def login(client) -> None:
    response = client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False)
    assert response.status_code == 303


def test_query_builder_saved_query_can_be_deleted(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.save_query_builder_query('Temporary query', '', 'SELECT 1', [], 'admin')
    saved = app_module.repository.list_query_builder_queries()
    query_id = int(saved[0]['id'])

    page = client.get('/query-builder')
    assert page.status_code == 200
    assert f'data-sql-delete data-query-id="{query_id}"' in page.text

    response = client.delete(f'/api/query-builder/saved/{query_id}')
    assert response.status_code == 200
    assert response.json() == {'deleted': True}
    assert app_module.repository.get_query_builder_query(query_id) is None
    assert 'Temporary query' not in client.get('/query-builder').text
    assert client.delete(f'/api/query-builder/saved/{query_id}').status_code == 404


def test_query_builder_assistant_uses_ready_source_columns(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 7, 'file_name': 'sample.csv', 'dataset_kind': 'data', 'status': 'ready'},
        {'id': 8, 'file_name': 'pending.csv', 'dataset_kind': 'voice', 'status': 'pending'},
    ])
    monkeypatch.setattr(app_module.repository, 'list_dataset_row_columns', lambda dataset_id: ['Operator', 'Test_Result'] if dataset_id == 7 else [])
    monkeypatch.setattr(app_module.repository, 'list_query_builder_queries', lambda: [])

    response = client.get('/query-builder')

    assert response.status_code == 200
    assert 'data-sql-mode="assisted"' in response.text
    assert 'data-sql-types' in response.text
    assert '<legend>CDR types to use</legend>' in response.text
    all_fields_input = re.search(r'<input data-sql-all-fields type="checkbox"([^>]*)>', response.text)
    assert all_fields_input is not None and 'checked' not in all_fields_input.group(1)
    assert 'data-sql-filter-field' in response.text
    assert 'data-sql-filter-connector' in response.text
    match = re.search(r'const datasetColumns = (\[.*?\]);', response.text)
    assert match is not None
    assert json.loads(match.group(1)) == [
        {'id': 7, 'name': 'sample.csv', 'kind': 'data', 'columns': ['Operator', 'Test_Result']},
    ]


def test_query_builder_background_run_and_cancel(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module
    from threading import Event

    login(client)
    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 7, 'file_name': 'sample.csv', 'dataset_kind': 'data', 'status': 'ready'},
    ])
    started = Event()
    release = Event()

    def slow_query(*_args):
        started.set()
        assert release.wait(3)
        return ['Value'], [('visible',)], False, ['selected_data'], 1

    monkeypatch.setattr(app_module, 'execute_query', slow_query)
    request_payload = {
        'dataset_ids': [7], 'query_sql': 'SELECT Value FROM selected_data',
        'offset': 0, 'background': True,
    }
    response = client.post('/api/query-builder/run', json={**request_payload, 'execution_id': 'background-cancel'})
    assert response.status_code == 202
    assert response.json() == {'execution_id': 'background-cancel', 'status': 'running'}
    assert started.wait(1)
    assert client.get('/api/query-builder/run/background-cancel').json() == {'status': 'running'}
    assert client.post('/api/query-builder/run', json={
        **request_payload, 'execution_id': 'background-parallel',
    }).status_code == 409
    job = app_module.QUERY_BUILDER_JOBS['background-cancel']
    session_marker = job['session_marker']
    job['session_marker'] = 'another-session'
    assert client.get('/api/query-builder/run/background-cancel').status_code == 404
    assert client.post('/api/query-builder/run/background-cancel/cancel').status_code == 404
    job['session_marker'] = session_marker
    assert client.post('/api/query-builder/run/background-cancel/cancel').json() == {'cancelling': True}
    release.set()
    for _ in range(100):
        cancelled = client.get('/api/query-builder/run/background-cancel').json()
        if cancelled['status'] == 'cancelled':
            break
        time.sleep(0.01)
    assert cancelled == {'status': 'cancelled', 'detail': 'Query cancelled.'}

    monkeypatch.setattr(app_module, 'execute_query', lambda *_args: (
        ['Value'], [('visible',)], False, ['selected_data'], 1,
    ))
    response = client.post('/api/query-builder/run', json={**request_payload, 'execution_id': 'background-success'})
    assert response.status_code == 202
    for _ in range(100):
        completed = client.get('/api/query-builder/run/background-success').json()
        if completed['status'] == 'completed':
            break
        time.sleep(0.01)
    assert completed == {'status': 'completed', 'result': {
        'columns': ['Value'], 'rows': [['visible']], 'truncated': False,
        'views': ['selected_data'], 'next_offset': None, 'total_rows': 1,
    }}


def test_query_builder_browser_polls_background_result() -> None:
    node_binary = shutil.which('node')
    if node_binary is None:
        pytest.skip('Node.js is required to exercise Query Builder browser polling.')
    template = (Path(__file__).resolve().parents[1] / 'src/web_interface/templates/query_builder.html').read_text(encoding='utf-8')
    start = template.index('  const requestExecutionResult = async ')
    end = template.index('\n  const render = ', start)
    helper = template[start:end]
    harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const helper = fs.readFileSync(0, 'utf8');
const calls = [];
const expected = {columns:['Value'], rows:[[1]], total_rows:1};
const context = {
  activeExecutionId:'background-test', querySignature:() => 'same-query',
  window:{setTimeout:resolve => resolve()},
  request:async (_url, extra) => {calls.push(['start', extra]); return {body:{execution_id:extra.execution_id,status:'running'}};},
  fetch:async url => {calls.push(['poll', url]); return {ok:true,headers:{get:() => 'application/json'},json:async () => ({status:'completed',result:expected})};},
  encodeURIComponent,
};
vm.runInNewContext(`${helper}\nrequestExecutionResult('background-test','same-query',{offset:50})`, context)
  .then(result => process.stdout.write(JSON.stringify({result,calls})));
"""
    completed = subprocess.run([node_binary, '-e', harness], input=helper, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['result'] == {'columns': ['Value'], 'rows': [[1]], 'total_rows': 1}
    assert result['calls'][0] == ['start', {'execution_id': 'background-test', 'background': True, 'offset': 50}]
    assert result['calls'][1] == ['poll', '/api/query-builder/run/background-test']


def test_query_builder_dataset_restore_matches_exact_name_then_unique_kind_and_hash(tmp_path: Path, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    source_path = tmp_path / 'source.csv'
    source_path.write_bytes(b'Operator,Value\nVodafone,1\n')
    renamed_path = tmp_path / 'renamed.csv'
    renamed_path.write_bytes(source_path.read_bytes())
    other_path = tmp_path / 'other.csv'
    other_path.write_bytes(b'Operator,Value\nThree,2\n')

    source_descriptor = {
        'name': 'source.csv', 'kind': 'data',
        'sha256': app_module._query_builder_source_sha256(source_path),
    }

    class DatasetRepository:
        def __init__(self, datasets):
            self.datasets = datasets

        def list_datasets(self):
            return self.datasets

    renamed_repo = DatasetRepository([
        {'id': 41, 'file_name': 'renamed.csv', 'stored_path': str(renamed_path), 'dataset_kind': 'data'},
    ])
    assert app_module._resolve_query_builder_dataset_ids(
        renamed_repo, {'dataset_descriptors': [source_descriptor]}, 'Portable query',
    ) == [41]

    exact_repo = DatasetRepository([
        {'id': 42, 'file_name': 'source.csv', 'stored_path': str(other_path), 'dataset_kind': 'voice'},
        {'id': 43, 'file_name': 'source.csv', 'stored_path': str(other_path), 'dataset_kind': 'data'},
    ])
    original_hash = app_module._query_builder_source_sha256
    monkeypatch.setattr(app_module, '_query_builder_source_sha256', lambda _path: pytest.fail('Exact name and kind match should not hash files.'))
    assert app_module._resolve_query_builder_dataset_ids(
        exact_repo, {'dataset_descriptors': [source_descriptor]}, 'Portable query',
    ) == [43]  # Exact name and kind take precedence without hashing.
    monkeypatch.setattr(app_module, '_query_builder_source_sha256', original_hash)

    ambiguous_repo = DatasetRepository([
        {'id': 44, 'file_name': 'renamed-a.csv', 'stored_path': str(renamed_path), 'dataset_kind': 'data'},
        {'id': 45, 'file_name': 'renamed-b.csv', 'stored_path': str(renamed_path), 'dataset_kind': 'data'},
    ])
    with pytest.raises(ValueError, match='matches multiple local datasets by kind and file hash'):
        app_module._resolve_query_builder_dataset_ids(
            ambiguous_repo, {'dataset_descriptors': [source_descriptor]}, 'Portable query',
        )

    with pytest.raises(ValueError, match='could not be matched to a local dataset'):
        app_module._resolve_query_builder_dataset_ids(
            DatasetRepository([]), {'dataset_descriptors': [source_descriptor]}, 'Portable query',
        )


def test_query_builder_restore_rejects_unresolved_sources_before_saving_any_queries(monkeypatch, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    source_path = tmp_path / 'present.csv'
    source_path.write_bytes(b'value\n1\n')
    saved_queries = []

    class DatasetRepository:
        def __init__(self, *_args):
            pass

        def list_datasets(self):
            return [{'id': 9, 'file_name': 'present.csv', 'stored_path': str(source_path), 'dataset_kind': 'data'}]

        def save_query_builder_query(self, *args):
            saved_queries.append(args)

    class DestinationWorkspace:
        name = 'Destination'
        database_path = tmp_path / 'destination.db'

    monkeypatch.setattr(app_module, 'Repository', DatasetRepository)
    payload = json.dumps({'queries': [
        {
            'name': 'Resolvable', 'query_sql': 'SELECT 1', 'dataset_names': ['present.csv'],
        },
        {
            'name': 'Missing', 'query_sql': 'SELECT 1', 'dataset_names': ['missing.csv'],
        },
    ]}).encode('utf-8')

    with pytest.raises(ValueError, match='dataset "missing.csv" could not be matched'):
        app_module._restore_workspace_query_builder_queries(DestinationWorkspace(), payload)
    assert saved_queries == []


def test_query_builder_preview_updates_completed_filter_while_another_is_incomplete() -> None:
    node_binary = shutil.which('node')
    if node_binary is None:
        pytest.skip('Node.js is required to exercise the Query Builder browser-side SQL generator.')

    template_path = Path(__file__).resolve().parents[1] / 'src/web_interface/templates/query_builder.html'
    template = template_path.read_text(encoding='utf-8')

    def extract(start_marker: str, end_marker: str) -> str:
        start = template.index(start_marker)
        end = template.index(end_marker, start)
        return template[start:end].strip()

    script_data = {
        'sync_action_availability': extract(
            '  const syncActionAvailability = () => {',
            '\n  const invalidateQueryResults',
        ),
        'filter_value_control': extract(
            '  const filterValueControl = ',
            '\n  const updateFilterValueControl',
        ),
        'build_assisted_sql': extract(
            '  function buildAssistedSql() {',
            '\n  const setMode',
        ),
    }
    node_harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
const makeFilter = ({ field, value, connector = 'AND' }) => {
  const controls = new Map([
    ['[data-sql-filter-field]', { value: field }],
    ['[data-sql-filter-operator]', { value: 'eq' }],
    ['[data-sql-filter-value]', { value }],
    ['[data-sql-filter-connector]', { value: connector }],
  ]);
  return { querySelector: selector => controls.get(selector) };
};
const context = {
  mode: 'assisted',
  editor: { value: '' },
  assistantStatus: { textContent: '' },
  results: { querySelector: selector => selector === 'table' ? {} : null },
  selectedKinds: () => ['data'],
  availableColumns: () => ['cdr_type', 'Operator'],
  columnsForKind: () => new Set(['Operator']),
  allFields: { checked: true },
  allRows: { checked: false },
  fieldsPicker: { selectedOptions: [] },
  limit: { value: '100' },
  filters: { children: [
    makeFilter({ field: 'Operator', value: 'before' }),
    makeFilter({ field: '', value: '' }),
  ] },
  sortField: { value: '' },
  sortDirection: { value: 'ASC' },
  quoteIdentifier: value => `"${String(value).replaceAll('"', '""')}"`,
  quoteValue: value => `'${String(value).replaceAll("'", "''")}'`,
  runButton: { disabled: false },
  saveButton: { disabled: false },
  exportButton: { disabled: false },
  copyButton: { disabled: false },
  previousButton: { disabled: false },
  nextButton: { disabled: false },
  pagination: { hidden: false },
  pageLabel: { textContent: '' },
  resultCount: { textContent: '' },
  currentPageIndex: 0,
  nextOffset: null,
  activeExecutionId: '',
  isExporting: false,
  hasCurrentResults: true,
  typeSelectionNotice: false,
  syncPaginationControls() {},
  updateFilterHeaderStates() {},
};
const script = `${source.sync_action_availability}\n${source.filter_value_control}\n${source.build_assisted_sql}\nbuildAssistedSql();\nconst initialPreview = editor.value;\nfilters.children[0].querySelector('[data-sql-filter-value]').value = 'after';\nbuildAssistedSql();\nJSON.stringify({ initialPreview, preview: editor.value, status: assistantStatus.textContent, runDisabled: runButton.disabled, saveDisabled: saveButton.disabled, exportDisabled: exportButton.disabled });`;
process.stdout.write(vm.runInNewContext(script, context));
"""
    completed = subprocess.run(
        [node_binary, '-e', node_harness],
        input=json.dumps(script_data),
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)

    assert result['preview'] != result['initialPreview']
    assert 'WHERE "Operator" = \'after\' COLLATE NOCASE' in result['preview']
    assert "'before'" not in result['preview']
    assert '1 incomplete filter' in result['status']
    assert all(result[action] for action in ('runDisabled', 'saveDisabled', 'exportDisabled'))


def test_query_builder_assistant_preview_and_dataset_name_filter_controls() -> None:
    node_binary = shutil.which('node')
    if node_binary is None:
        pytest.skip('Node.js is required to exercise the Query Builder browser-side SQL generator.')

    template_path = Path(__file__).resolve().parents[1] / 'src/web_interface/templates/query_builder.html'
    template = template_path.read_text(encoding='utf-8')

    def extract(start_marker: str, end_marker: str) -> str:
        start = template.index(start_marker)
        end = template.index(end_marker, start)
        return template[start:end].strip()

    script_data = {
        'set_options': extract('  const setOptions = ', '\n  const selectedKinds'),
        'dataset_helpers': extract('  const selectedKinds = ', '\n  const columnsForKind'),
        'column_helpers': extract('  const columnsForKind = ', '\n  const refreshFields'),
        'refresh_fields': extract('  const refreshFields = ', '\n  function selectDefaultFields'),
        'default_fields': extract('  function selectDefaultFields()', '\n  const refreshTypes'),
        'refresh_types': extract('  const refreshTypes = ', '\n  const refreshFilterConnectors'),
        'build_assisted_sql': extract('  function buildAssistedSql() {', '\n  const setMode'),
        'parser_path': str(Path(__file__).resolve().parents[1] / 'src/web_interface/static/js/query_builder_assistant_state.js'),
    }
    node_harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
class FakeSelect {
  constructor(value = '') { this.options = []; this._value = value; this.hidden = false; this.disabled = false; }
  get value() { return this._value; }
  set value(value) { this._value = value; this.options.forEach(option => { option.selected = option.value === value; }); }
  get selectedOptions() { return this.options.filter(option => option.selected); }
  replaceChildren() { this.options = []; this._value = ''; }
  add(option) { this.options.push(option); if (option.selected) this._value = option.value; }
  dispatchEvent() { return true; }
}
const makeInput = () => ({ checked: false, listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; } });
const typePicker = {
  children: [],
  replaceChildren() { this.children = []; },
  append(label) { this.children.push(label); },
  querySelectorAll(selector) { return selector === 'input:checked' ? this.children.map(label => label.input).filter(input => input.checked) : []; },
};
const datasets = [
  { id: 1, name: 'Data with a long source name.csv', kind: 'data', columns: ['Operator'] },
  { id: 2, name: 'Voice with a long source name.csv', kind: 'voice', columns: ['Operator'] },
  { id: 3, name: 'Unselected source.csv', kind: 'data', columns: ['Operator'] },
  { id: 4, name: 'Second selected data source.csv', kind: 'data', columns: ['Operator'] },
];
const sources = { selectedOptions: [] };
const fieldsPicker = new FakeSelect();
const sortField = new FakeSelect();
const filters = { children: [], querySelectorAll(selector) {
  if (selector === '[data-sql-filter-field]') return this.children.map(row => row.controls.field);
  if (selector === '.query-builder-filter') return this.children;
  return [];
} };
const context = {
  mode: 'assisted', editor: { value: '' }, assistantStatus: { textContent: '' },
  datasetColumns: datasets, sources, typePicker, allFields: { checked: false }, allRows: { checked: false },
  fieldsPicker, sortField, sortDirection: { value: 'ASC' }, limit: { value: '100' }, filters,
  runButton: { disabled: false }, saveButton: { disabled: false }, exportButton: { disabled: false },
  activeExecutionId: '', isExporting: false, hasCurrentResults: false,
  sourceFields: ['source_dataset_id', 'source_dataset_name', 'source_row_id'],
  typeSelectionNotice: false, assistantValid: false,
  FakeSelect,
  syncActionAvailability() {}, invalidateQueryResults() {},
  quoteIdentifier: value => `"${String(value).replaceAll('"', '""')}"`,
  quoteValue: value => `'${String(value).replaceAll("'", "''")}'`,
  Option: function (label, value) { return { label, value, selected: false }; },
  Event: function (type, options) { return { type, ...options }; },
  document: {
    createElement(tag) {
      if (tag === 'input') return makeInput();
      return { append(input) { this.input = input; } };
    },
    createTextNode(value) { return value; },
  },
};
const chunks = [source.set_options, source.dataset_helpers, source.column_helpers, source.refresh_fields,
  source.default_fields, source.refresh_types, source.build_assisted_sql].join('\n');
const run = `${chunks}
refreshTypes();
const initialPreview = editor.value;
const initialDefaultFields = fieldsPicker.selectedOptions.map(option => option.value).sort();
sources.selectedOptions = [{ value: '1' }, { value: '2' }, { value: '4' }];
refreshTypes();
const kinds = typePicker.children.map(label => label.input);
const [dataType, voiceType] = kinds;
voiceType.checked = false;
voiceType.listeners.change();
const singleTypePreview = editor.value;
dataType.checked = false;
dataType.listeners.change();
const lastTypeWasRestored = dataType.checked && editor.value === singleTypePreview
  && assistantStatus.textContent.includes('At least one CDR type must remain selected');
allFields.checked = false;
selectDefaultFields();
const defaultFields = fieldsPicker.selectedOptions.map(option => option.value).sort();
buildAssistedSql();
const previewWithDefaults = editor.value;
const fieldSelect = new FakeSelect('source_dataset_name');
fieldSelect.add({ label: 'source_dataset_name', value: 'source_dataset_name', selected: true });
const operatorSelect = { value: 'eq' };
const textInput = { value: '', hidden: false, disabled: false };
const datasetPicker = new FakeSelect();
datasetPicker.hidden = true;
const row = { className: 'query-builder-filter', dataset: {}, controls: {
  field: fieldSelect, operator: operatorSelect, text: textInput, dataset: datasetPicker,
  connector: { value: 'AND', hidden: true },
}, querySelector(selector) {
  if (selector === '[data-sql-filter-field]') return this.controls.field;
  if (selector === '[data-sql-filter-operator]') return this.controls.operator;
  if (selector === '[data-sql-filter-value]') return this.controls.text;
  if (selector === '[data-sql-filter-dataset-value]') return this.controls.dataset;
  if (selector === '[data-sql-filter-dataset-value]:not([hidden])') return this.controls.dataset.hidden ? null : this.controls.dataset;
  if (selector === '[data-sql-filter-connector]') return this.controls.connector;
  return null;
} };
updateFilterValueControl(row);
const datasetOptions = datasetPicker.options.map(option => option.value).filter(Boolean);
const datasetPickerShown = !datasetPicker.hidden && textInput.hidden;
datasetPicker.value = 'Data with a long source name.csv';
filters.children = [row];
buildAssistedSql();
const isSql = editor.value;
operatorSelect.value = 'ne';
updateFilterValueControl(row);
const datasetPickerShownForIsNot = !datasetPicker.hidden && textInput.hidden;
buildAssistedSql();
const isNotSql = editor.value;
operatorSelect.value = 'contains';
updateFilterValueControl(row);
const textInputShownForOtherComparisons = datasetPicker.hidden && !textInput.hidden;
filters.children = [];
voiceType.checked = true;
refreshFields();
allFields.checked = true;
buildAssistedSql();
const limitedSql = editor.value;
allRows.checked = true;
buildAssistedSql();
const allRowsSql = editor.value;
JSON.stringify({ singleTypePreview, lastTypeWasRestored, status: assistantStatus.textContent,
  initialPreview, initialDefaultFields, defaultFields, previewWithDefaults, datasetOptions, datasetPickerShown, datasetPickerShownForIsNot,
  textInputShownForOtherComparisons, isSql, isNotSql, unfilteredSql: limitedSql, allRowsSql });`;
const result = JSON.parse(vm.runInNewContext(run, context));
require(source.parser_path);
result.parsedFilterQuery = globalThis.QueryBuilderAssistantState.parseGeneratedSql(result.isSql);
result.parsedAllRowsQuery = globalThis.QueryBuilderAssistantState.parseGeneratedSql(result.allRowsSql);
result.unrepresentableQuery = globalThis.QueryBuilderAssistantState.parseGeneratedSql('SELECT * FROM selected_data LIMIT 100');
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node_binary, '-e', node_harness],
        input=json.dumps(script_data),
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)

    assert 'Select at least one CDR source' in result['initialPreview']
    assert result['initialDefaultFields'] == ['cdr_type', 'source_dataset_name']
    assert 'FROM "selected_data"' in result['singleTypePreview']
    assert result['lastTypeWasRestored']
    assert result['defaultFields'] == ['cdr_type', 'source_dataset_name']
    assert 'SELECT "source_dataset_name", "cdr_type"' in result['previewWithDefaults']
    assert result['datasetOptions'] == ['Data with a long source name.csv', 'Second selected data source.csv']
    assert result['datasetPickerShown']
    assert result['datasetPickerShownForIsNot']
    assert result['textInputShownForOtherComparisons']
    assert 'WHERE "source_dataset_name" = \'Data with a long source name.csv\' COLLATE NOCASE' in result['isSql']
    assert 'WHERE "source_dataset_name" <> \'Data with a long source name.csv\' COLLATE NOCASE' in result['isNotSql']
    assert 'WHERE' not in result['unfilteredSql']
    assert 'FROM "selected_data"' in result['unfilteredSql']
    assert 'FROM "selected_voice"' in result['unfilteredSql']
    assert result['unfilteredSql'].endswith('LIMIT 100')
    assert 'LIMIT' not in result['allRowsSql']
    assert result['parsedFilterQuery']['kinds'] == ['data']
    assert result['parsedFilterQuery']['fields'] == ['source_dataset_name', 'cdr_type']
    assert result['parsedFilterQuery']['filters'] == [{
        'field': 'source_dataset_name', 'operator': 'eq', 'value': 'Data with a long source name.csv', 'connector': 'AND',
    }]
    assert result['parsedFilterQuery']['limit'] == 100
    assert result['parsedAllRowsQuery']['limit'] is None
    assert result['unrepresentableQuery'] is None


def test_query_builder_saved_query_restores_assisted_controls_or_keeps_manual_sql() -> None:
    node_binary = shutil.which('node')
    if node_binary is None:
        pytest.skip('Node.js is required to exercise Query Builder saved-query restoration.')

    template_path = Path(__file__).resolve().parents[1] / 'src/web_interface/templates/query_builder.html'
    template = template_path.read_text(encoding='utf-8')

    def extract(start_marker: str, end_marker: str) -> str:
        start = template.index(start_marker)
        end = template.index(end_marker, start)
        return template[start:end].strip()

    script_data = {
        'availability': extract('  const syncActionAvailability = () => {', '\n  const invalidateQueryResults'),
        'build_sql': extract('  function buildAssistedSql() {', '\n  const setMode'),
        'set_mode': extract('  const setMode = ', '\n  modeButtons.forEach'),
        'restore': extract('  const restoreAssistedQuery = ', '\n  const loadSavedQuery'),
        'load_saved': extract('  const loadSavedQuery = ', "\n  document.querySelector('[data-sql-load-saved]')"),
        'parser_path': str(Path(__file__).resolve().parents[1] / 'src/web_interface/static/js/query_builder_assistant_state.js'),
    }
    node_harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
require(source.parser_path);
const representableSql = `SELECT "source_dataset_name", "cdr_type"
FROM (
  SELECT "source_dataset_name", 'DATA' AS "cdr_type"
FROM "selected_data"
) AS "combined_cdr"
LIMIT 100`;
const manualSql = 'SELECT * FROM selected_data LIMIT 100';
const dataType = {value: 'data', checked: true};
const typePicker = {querySelectorAll: selector => selector === 'input' ? [dataType] : []};
const fieldsPicker = {
  options: ['source_dataset_name', 'cdr_type'].map(value => ({value, selected: false})),
  get selectedOptions() { return this.options.filter(option => option.selected); },
  dispatchEvent() {},
};
const sources = {options: [{value: '1', selected: false}], dispatchEvent() {}};
const filters = {children: [], replaceChildren() { this.children = []; }};
const button = () => ({disabled: false});
const context = {
  QueryBuilderAssistantState: globalThis.QueryBuilderAssistantState,
  representableSql, manualSql,
  mode: 'assisted', lastGeneratedSql: '', assistantValid: false, hasCurrentResults: false,
  activeExecutionId: '', isExporting: false, typeSelectionNotice: false,
  editor: {value: '', readOnly: true}, editorLabel: {textContent: ''}, assistant: {hidden: false}, status: {textContent: ''},
  modeButtons: [], sources, typePicker, fieldsPicker, fieldsWrap: {hidden: false}, filters,
  allFields: {checked: false}, allRows: {checked: false}, limit: {value: '100', disabled: false},
  sortField: {value: ''}, sortDirection: {value: 'ASC'}, assistantStatus: {textContent: ''},
  runButton: button(), saveButton: button(), exportButton: button(), copyButton: button(),
  previousButton: button(), nextButton: button(), pagination: {hidden: true}, pageLabel: {textContent: ''},
  results: {querySelector: () => null}, currentPageIndex: 0, nextOffset: null,
  sourceFields: ['source_dataset_id', 'source_dataset_name', 'source_row_id'],
  syncPaginationControls() {},
  updateFilterHeaderStates() {},
  selectedKinds: () => ['data'], availableColumns: () => ['source_dataset_name', 'cdr_type'],
  columnsForKind: () => new Set(['source_dataset_name']),
  refreshFields() {}, addFilter() {}, updateFilterValueControl() {}, filterValueControl() {},
  quoteIdentifier: value => `"${String(value).replaceAll('"', '""')}"`,
  quoteValue: value => `'${String(value).replaceAll("'", "''")}'`,
  Event: function(type, options) { return {type, ...options}; },
};
const script = `${source.availability}
${source.build_sql}
${source.set_mode}
${source.restore}
${source.load_saved}
const load = sql => loadSavedQuery({dataset: {query: JSON.stringify(sql), datasetIds: '[1]'}});
load(representableSql);
const assisted = {mode, editorSql: editor.value, status: status.textContent, fields: fieldsPicker.selectedOptions.map(option => option.value)};
load(manualSql);
JSON.stringify({assisted, manual: {mode, editorSql: editor.value, status: status.textContent}});`;
process.stdout.write(vm.runInNewContext(script, context));
"""
    completed = subprocess.run(
        [node_binary, '-e', node_harness],
        input=json.dumps(script_data),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result['assisted']['mode'] == 'assisted', result
    assert result['assisted']['editorSql'] == '''SELECT "source_dataset_name", "cdr_type"
FROM (
  SELECT "source_dataset_name", 'DATA' AS "cdr_type"
FROM "selected_data"
) AS "combined_cdr"
LIMIT 100'''
    assert result['assisted']['fields'] == ['source_dataset_name', 'cdr_type']
    assert 'Saved query loaded in Assisted mode' in result['assisted']['status']
    assert result['manual']['mode'] == 'sql'
    assert result['manual']['editorSql'] == 'SELECT * FROM selected_data LIMIT 100'
    assert 'cannot be shown in Assisted mode' in result['manual']['status']


def test_query_builder_result_pages_and_copy_cover_only_visible_page() -> None:
    node_binary = shutil.which('node')
    if node_binary is None:
        pytest.skip('Node.js is required to exercise the Query Builder browser-side result controls.')

    template_path = Path(__file__).resolve().parents[1] / 'src/web_interface/templates/query_builder.html'
    template = template_path.read_text(encoding='utf-8')

    def extract(start_marker: str, end_marker: str) -> str:
        start = template.index(start_marker)
        end = template.index(end_marker, start)
        return template[start:end].strip()

    script_data = {
        'pagination_controls': extract('  const lastPageOffset = ', '\n  const syncActionAvailability'),
        'availability': extract('  const syncActionAvailability = () => {', '\n  const invalidateQueryResults'),
        'escape': extract('  const escape = (value) => ', '\n  const payload'),
        'render': extract('  const render = (body) => {', '\n  const loadPage = async'),
        'page_handlers': extract('  const loadPage = async ', '\n  copyButton.addEventListener'),
        'copy_handler': extract('  copyButton.addEventListener(', '\n  cancelRunButton.addEventListener'),
    }
    node_harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
class FakeResults {
  set innerHTML(markup) {
    this.markup = markup;
    const tableMarkup = markup.match(/<table>([\s\S]*?)<\/table>/)?.[1];
    this.table = tableMarkup ? {
      querySelectorAll: selector => selector === 'tr' ? [...tableMarkup.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(match => ({
        querySelectorAll: cellsSelector => cellsSelector === 'th, td'
          ? [...match[1].matchAll(/<(?:th|td)>([\s\S]*?)<\/(?:th|td)>/g)].map(cell => ({ textContent: cell[1].replace(/<[^>]*>/g, '') }))
          : [],
      })) : [],
    } : null;
  }
  querySelector(selector) { return selector === 'table' ? this.table : null; }
  querySelectorAll() { return []; }
  hasColumnFilterButtons() { return Boolean(this.markup?.includes('data-sql-column-filter-trigger')); }
}
const makeButton = () => ({ disabled: false, listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; } });
const makePage = (offset, count, totalRows) => ({
  columns: ['Value'],
  rows: Array.from({length: count}, (_unused, index) => [offset + index + 1]),
  next_offset: offset + count < totalRows ? offset + count : null,
  total_rows: totalRows,
  views: ['selected_data'],
});
const pages = {0: makePage(0, 50, 117), 50: makePage(50, 50, 117), 100: makePage(100, 17, 117)};
const requestOffsets = [];
const context = {
  pages,
  requestOffsets,
  columnFilters: new Map(),
  pageSize: 50, totalRows: 0, currentOffset: 0,
  mode: 'sql', assistantValid: true, activeExecutionId: '', isExporting: false, hasCurrentResults: false,
  nextOffset: null,
  results: new FakeResults(), resultCount: { textContent: '' },
  paginationGroups: [{hidden: true}, {hidden: true}], pageLabels: [{textContent: ''}, {textContent: ''}],
  runButton: makeButton(), saveButton: makeButton(), copyButton: makeButton(), exportButton: makeButton(),
  firstButtons: [makeButton(), makeButton()], previousButtons: [makeButton(), makeButton()],
  nextButtons: [makeButton(), makeButton()], lastButtons: [makeButton(), makeButton()],
  updateFilterHeaderStates() {},
  serializeColumnFilters: () => [],
  status: { textContent: '' }, runningOverlay: { hidden: true }, cancelRunButton: { disabled: false },
  querySignature: () => 'same-query',
  serializeColumnFilters: () => [],
  requestExecutionResult: async (_id, _signature, extra) => { requestOffsets.push(extra.offset); return pages[extra.offset]; },
  navigator: { clipboard: { text: '', writeText: async function(value) { this.text = value; } } },
  setTimeout,
};
const run = `(async () => {
${source.pagination_controls}
${source.availability}
const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
${source.render}
${source.page_handlers}
${source.copy_handler}
const snapshot = () => ({labels: pageLabels.map(label => label.textContent), groupsHidden: paginationGroups.map(group => group.hidden),
  firstDisabled: firstButtons.map(button => button.disabled), previousDisabled: previousButtons.map(button => button.disabled),
  nextDisabled: nextButtons.map(button => button.disabled), lastDisabled: lastButtons.map(button => button.disabled),
  count: resultCount.textContent, hasColumnFilterButtons: results.hasColumnFilterButtons()});
const clickAndWait = async button => { button.listeners.click(); while (activeExecutionId) await new Promise(resolve => setTimeout(resolve, 0)); };
render(pages[0]); hasCurrentResults = true; syncActionAvailability();
const firstPage = snapshot();
await clickAndWait(lastButtons[0]);
const lastPage = snapshot();
await copyButton.listeners.click();
const lastPageCopy = navigator.clipboard.text;
const lastPageCopyStatus = status.textContent;
await clickAndWait(firstButtons[1]);
const returnedToFirstPage = snapshot();
await clickAndWait(nextButtons[1]);
const middlePage = snapshot();
await clickAndWait(previousButtons[0]);
const finalPage = snapshot();
render({columns: ['Value'], rows: [[1]], next_offset: null, total_rows: 1, views: ['selected_data']});
hasCurrentResults = true; syncActionAvailability();
const singlePage = snapshot();
return JSON.stringify({firstPage, lastPage, returnedToFirstPage, middlePage, finalPage, singlePage, lastPageCopy,
  requestOffsets, copyStatus: lastPageCopyStatus});
})()`;
vm.runInNewContext(run, context).then(value => process.stdout.write(value));
"""
    completed = subprocess.run(
        [node_binary, '-e', node_harness],
        input=json.dumps(script_data),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result['firstPage'] == {
        'labels': ['Page 1 of 3', 'Page 1 of 3'],
        'groupsHidden': [False, False],
        'firstDisabled': [True, True],
        'previousDisabled': [True, True],
        'nextDisabled': [False, False],
        'lastDisabled': [False, False],
        'count': '50 rows on this page · 1 columns · 117 total rows',
        'hasColumnFilterButtons': True,
    }
    assert result['lastPage'] == {
        'labels': ['Page 3 of 3', 'Page 3 of 3'],
        'groupsHidden': [False, False],
        'firstDisabled': [False, False],
        'previousDisabled': [False, False],
        'nextDisabled': [True, True],
        'lastDisabled': [True, True],
        'count': '17 rows on this page · 1 columns · 117 total rows',
        'hasColumnFilterButtons': True,
    }
    assert result['returnedToFirstPage'] == result['firstPage']
    assert result['middlePage']['labels'] == ['Page 2 of 3', 'Page 2 of 3']
    assert result['middlePage']['firstDisabled'] == [False, False]
    assert result['middlePage']['previousDisabled'] == [False, False]
    assert result['middlePage']['nextDisabled'] == [False, False]
    assert result['middlePage']['lastDisabled'] == [False, False]
    assert result['finalPage'] == result['firstPage']
    assert result['singlePage'] == {
        'labels': ['Page 1 of 1', 'Page 1 of 1'],
        'groupsHidden': [False, False],
        'firstDisabled': [True, True],
        'previousDisabled': [True, True],
        'nextDisabled': [True, True],
        'lastDisabled': [True, True],
        'count': '1 rows on this page · 1 columns · 1 total rows',
        'hasColumnFilterButtons': True,
    }
    assert result['lastPageCopy'].splitlines()[0] == 'Value'
    assert result['lastPageCopy'].splitlines()[1:] == [str(value) for value in range(101, 118)]
    assert result['requestOffsets'] == [100, 0, 50, 0]
    assert result['copyStatus'] == 'Current page copied to clipboard.'


def test_query_builder_executes_union_all_with_disjoint_columns_and_grouped_filters(tmp_path: Path) -> None:
    from src.modules.query_builder import execute_query

    database_path = tmp_path / 'query-builder.sqlite'
    with sqlite3.connect(database_path) as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Status TEXT, Alpha INTEGER)')
        connection.executemany(
            'INSERT INTO dataset_rows_1 VALUES (?, ?)',
            [('keep', 0), ('keep', 2), ('also', 3), ('skip', 4)],
        )
        connection.execute('CREATE TABLE dataset_rows_2 (Status TEXT, Beta TEXT)')
        connection.executemany(
            'INSERT INTO dataset_rows_2 VALUES (?, ?)',
            [('keep', 'x'), ('keep', 'x'), ('also', 'x'), ('also', 'y')],
        )

    datasets = [
        {'id': 1, 'name': 'data.csv', 'kind': 'data'},
        {'id': 2, 'name': 'voice.csv', 'kind': 'voice'},
    ]
    query_sql = """
        SELECT "Status", "Alpha", "Beta", "cdr_type"
        FROM (
          SELECT "Status", "Alpha", NULL AS "Beta", 'DATA' AS "cdr_type"
          FROM "selected_data"
          UNION ALL
          SELECT "Status", NULL AS "Alpha", "Beta", 'VOICE' AS "cdr_type"
          FROM "selected_voice"
        ) AS "combined_cdr"
        WHERE (("Status" = 'keep' COLLATE NOCASE AND CAST("Alpha" AS REAL) > 1)
          OR "Beta" = 'x' COLLATE NOCASE)
        ORDER BY "Status" ASC
        LIMIT 100
    """

    columns, rows, truncated, views = execute_query(database_path, datasets, query_sql)

    assert columns == ['Status', 'Alpha', 'Beta', 'cdr_type']
    assert Counter(rows) == Counter([
        ('also', None, 'x', 'VOICE'),
        ('keep', 2, None, 'DATA'),
        ('keep', None, 'x', 'VOICE'),
        ('keep', None, 'x', 'VOICE'),
    ])
    assert not truncated
    assert views == ['selected_data', 'selected_voice']


def test_query_builder_run_returns_offset_pages_and_rejects_invalid_offsets(client, monkeypatch, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 1, 'file_name': 'paged.csv', 'dataset_kind': 'data', 'status': 'ready'},
    ])
    monkeypatch.setattr(app_module, 'MAX_PREVIEW_ROWS', 2)
    database_path = tmp_path / 'query-builder-api.sqlite'
    monkeypatch.setattr(app_module, 'active_workspace', replace(app_module.active_workspace, database_path=database_path))
    with sqlite3.connect(database_path) as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Value INTEGER)')
        connection.executemany('INSERT INTO dataset_rows_1 VALUES (?)', [(1,), (2,), (3,), (4,), (5,)])

    payload = {
        'dataset_ids': [1],
        'query_sql': 'SELECT "Value" FROM "selected_data" ORDER BY "Value" ASC',
    }
    first_page = client.post('/api/query-builder/run', json={**payload, 'execution_id': 'page-0001', 'offset': 0})
    second_page = client.post('/api/query-builder/run', json={**payload, 'execution_id': 'page-0002', 'offset': 2})
    final_page = client.post('/api/query-builder/run', json={**payload, 'execution_id': 'page-0003', 'offset': 4})

    assert first_page.status_code == second_page.status_code == final_page.status_code == 200, [
        first_page.text, second_page.text, final_page.text,
    ]
    assert first_page.json()['rows'] == [[1], [2]]
    assert first_page.json()['next_offset'] == 2
    assert first_page.json()['total_rows'] == 5
    assert second_page.json()['rows'] == [[3], [4]]
    assert second_page.json()['next_offset'] == 4
    assert second_page.json()['total_rows'] == 5
    assert final_page.json()['rows'] == [[5]]
    assert final_page.json()['next_offset'] is None
    assert final_page.json()['total_rows'] == 5

    limited_page = client.post('/api/query-builder/run', json={
        **payload,
        'query_sql': 'SELECT "Value" FROM "selected_data" ORDER BY "Value" ASC LIMIT 3',
        'execution_id': 'page-limit',
        'offset': 2,
    })
    assert limited_page.status_code == 200
    assert limited_page.json()['rows'] == [[3]]
    assert limited_page.json()['next_offset'] is None
    assert limited_page.json()['total_rows'] == 3

    for invalid_offset in (True, -1, 1.5, '1'):
        response = client.post(
            '/api/query-builder/run',
            json={**payload, 'execution_id': 'page-invalid', 'offset': invalid_offset},
        )
        assert response.status_code == 400


def test_query_builder_column_filters_cover_complete_results_pages_and_csv(client, monkeypatch, tmp_path: Path) -> None:
    import csv
    import io

    import src.DashboardAnalytic as app_module

    login(client)
    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 1, 'file_name': 'filterable.csv', 'dataset_kind': 'data', 'status': 'ready'},
    ])
    monkeypatch.setattr(app_module, 'MAX_PREVIEW_ROWS', 2)
    database_path = tmp_path / 'query-builder-column-filters.sqlite'
    monkeypatch.setattr(app_module, 'active_workspace', replace(app_module.active_workspace, database_path=database_path))
    with sqlite3.connect(database_path) as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Category TEXT, Score INTEGER)')
        connection.executemany(
            'INSERT INTO dataset_rows_1 VALUES (?, ?)',
            [('north', 1), ('other', 2), ('other', 3), ('target', 4), ('target', 5), ('target', 6)],
        )

    payload = {
        'dataset_ids': [1],
        'query_sql': 'SELECT "Category", "Score" FROM "selected_data" ORDER BY "Score" ASC',
        'column_filters': [{'index': 0, 'values': ['target']}],
    }
    first_page = client.post('/api/query-builder/run', json={
        **payload, 'execution_id': 'filter-page-01', 'offset': 0,
    })
    second_page = client.post('/api/query-builder/run', json={
        **payload, 'execution_id': 'filter-page-02', 'offset': 2,
    })

    assert first_page.status_code == second_page.status_code == 200, [first_page.text, second_page.text]
    assert first_page.json()['rows'] == [['target', 4], ['target', 5]]
    assert first_page.json()['next_offset'] == 2
    assert first_page.json()['total_rows'] == 3
    assert second_page.json()['rows'] == [['target', 6]]
    assert second_page.json()['next_offset'] is None
    assert second_page.json()['total_rows'] == 3

    no_matches = client.post('/api/query-builder/run', json={
        **payload,
        'column_filters': [{'index': 0, 'values': []}],
        'execution_id': 'filter-empty-01',
        'offset': 0,
    })
    assert no_matches.status_code == 200
    assert no_matches.json()['rows'] == []
    assert no_matches.json()['total_rows'] == 0

    exported = client.post('/api/query-builder/export', json=payload)
    assert exported.status_code == 200
    assert list(csv.reader(io.StringIO(exported.text))) == [
        ['Category', 'Score'], ['target', '4'], ['target', '5'], ['target', '6'],
    ]


def test_query_builder_filter_values_are_distinct_faceted_searchable_and_typed(client, monkeypatch, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 1, 'file_name': 'filter-values.csv', 'dataset_kind': 'data', 'status': 'ready'},
    ])
    database_path = tmp_path / 'query-builder-filter-values.sqlite'
    monkeypatch.setattr(app_module, 'active_workspace', replace(app_module.active_workspace, database_path=database_path))
    with sqlite3.connect(database_path) as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Region TEXT, Score INTEGER)')
        connection.executemany(
            'INSERT INTO dataset_rows_1 VALUES (?, ?)',
            [('North', 1), ('South', 2), ('West', 3), ('North', 4), ('South', 5)]
            + [(f'Region {index}', index + 6) for index in range(200)],
        )

    payload = {
        'dataset_ids': [1],
        'query_sql': 'SELECT "Region", "Score" FROM "selected_data"',
        'column_index': 0,
        'column_filters': [
            {'index': 0, 'values': ['West']},
            {'index': 1, 'values': [1, 2, 3, 4]},
        ],
        'search': 'or',
    }
    faceted_values = client.post('/api/query-builder/filter-values', json=payload)

    assert faceted_values.status_code == 200, faceted_values.text
    assert faceted_values.json() == {'values': ['North'], 'truncated': False}

    typed_values = client.post('/api/query-builder/filter-values', json={
        **payload,
        'column_index': 1,
        'column_filters': [{'index': 0, 'values': ['North']}],
        'search': '',
    })
    assert typed_values.status_code == 200, typed_values.text
    assert typed_values.json() == {'values': [1, 4], 'truncated': False}
    assert all(isinstance(value, int) for value in typed_values.json()['values'])

    capped_values = client.post('/api/query-builder/filter-values', json={
        **payload,
        'column_index': 1,
        'column_filters': [],
        'search': '',
    })
    assert capped_values.status_code == 200, capped_values.text
    assert len(capped_values.json()['values']) == 200
    assert all(isinstance(value, int) for value in capped_values.json()['values'])
    assert capped_values.json()['truncated'] is True


def test_query_builder_csv_stream_includes_more_than_one_hundred_thousand_rows(tmp_path: Path) -> None:
    from src.modules.query_builder import iter_query_csv

    database_path = tmp_path / 'query-builder-csv.sqlite'
    with sqlite3.connect(database_path) as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Value INTEGER, Detail TEXT)')
        connection.execute('''
            WITH RECURSIVE values_to_insert(value) AS (
                VALUES (1)
                UNION ALL
                SELECT value + 1 FROM values_to_insert WHERE value < 100001
            )
            INSERT INTO dataset_rows_1 SELECT value, 'detail-' || value FROM values_to_insert
        ''')

    completed_rows: list[int] = []
    chunks = iter_query_csv(
        database_path,
        [{'id': 1, 'name': 'all-rows.csv', 'kind': 'data'}],
        'SELECT "Value", "Detail" FROM "selected_data" ORDER BY "Value" ASC',
        on_complete=completed_rows.append,
    )

    header = next(chunks)
    exported_line_count = 0
    first_chunk = ''
    last_chunk = ''
    for chunk in chunks:
        first_chunk = first_chunk or chunk
        last_chunk = chunk
        exported_line_count += chunk.count('\n')

    assert header == 'Value,Detail\r\n'
    assert first_chunk.startswith('1,detail-1\r\n')
    assert last_chunk.endswith('100001,detail-100001\r\n')
    assert exported_line_count == 100001
    assert completed_rows == [100001]


def test_login_does_not_reinitialize_the_active_workspace(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    initialize_calls = 0

    def count_initialize() -> None:
        nonlocal initialize_calls
        initialize_calls += 1

    monkeypatch.setattr(app_module.repository, 'initialize', count_initialize)
    response = client.post(
        '/login',
        data={
            'username': 'admin', 'password': 'admin123',
            'workspace_id': app_module.active_workspace.id,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert initialize_calls == 0


def test_login_reports_a_busy_workspace_without_an_internal_server_error(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    def fail_activation(_workspace_id: str) -> None:
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(app_module, 'activate_workspace', fail_activation)
    response = client.post(
        '/login',
        data={
            'username': 'admin', 'password': 'admin123',
            'workspace_id': app_module.active_workspace.id,
        },
    )

    assert response.status_code == 503
    assert 'Workspace database is busy' in response.text


def test_passive_polling_stops_without_redirecting_after_an_expired_session() -> None:
    import src.DashboardAnalytic as app_module

    script = (app_module.PROJECT_ROOT / 'src' / 'web_interface' / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')

    assert script.count("if (!document.body.dataset.authenticatedUser) return;") >= 2
    assert "window.clearInterval(pollingInterval)" in script
    assert "window.location.replace('/login')" not in script


def test_expired_passive_polling_returns_an_inert_response_without_unauthorized_errors(client) -> None:
    import src.DashboardAnalytic as app_module

    app_module.SESSIONS.clear()
    client.cookies.clear()

    tasks_response = client.get('/api/background-tasks')
    sizes_response = client.get('/api/workspaces/sizes')

    assert tasks_response.status_code == 200
    assert tasks_response.json() == {'authenticated': False, 'active_workspace_id': None, 'groups': []}
    assert sizes_response.status_code == 200
    assert sizes_response.json() == {
        'authenticated': False, 'active_workspace_id': None, 'sizes': {}, 'cache_sizes': {},
    }


def test_repository_reads_remain_available_while_a_background_writer_is_active(tmp_path: Path) -> None:
    from src.modules.repository import Repository

    database_path = tmp_path / 'concurrent-workspace.db'
    repository = Repository(database_path)
    repository.initialize()

    with sqlite3.connect(database_path) as journal_connection:
        assert journal_connection.execute('PRAGMA journal_mode').fetchone()[0].casefold() == 'wal'

    writer = sqlite3.connect(database_path, timeout=1.0)
    try:
        writer.execute('BEGIN IMMEDIATE')
        started_at = time.monotonic()
        assert repository.list_datasets() == []
        assert time.monotonic() - started_at < 1.0
    finally:
        writer.rollback()
        writer.close()


def test_large_excel_ingestion_cooperatively_yields_to_the_web_server(monkeypatch) -> None:
    from src.modules import ingestion

    class Worksheet:
        def iter_rows(self, values_only: bool = True):
            assert values_only is True
            yield ('market', 'score')
            yield ('UK', 91)
            yield ('ES', 88)
            yield ('DE', 86)

    pauses: list[float] = []
    monkeypatch.setattr(ingestion, 'EXCEL_READ_YIELD_EVERY_ROWS', 2)
    monkeypatch.setattr(ingestion, 'EXCEL_READ_YIELD_SECONDS', 0.003)
    monkeypatch.setattr(ingestion, 'sleep', pauses.append)

    frame = ingestion._read_openxml_sheet(Worksheet(), None, {'processed_rows': 0, 'last_progress': 14}, 4)

    assert frame.to_dict('records') == [
        {'market': 'UK', 'score': 91},
        {'market': 'ES', 'score': 88},
        {'market': 'DE', 'score': 86},
    ]
    assert pauses == [0.003, 0.003]


def test_report_template_timestamp_migration_does_not_rewrite_complete_rows(tmp_path: Path) -> None:
    from src.modules.repository import Repository

    database_path = tmp_path / 'workspace.db'
    repository = Repository(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            '''
            CREATE TABLE report_templates (
                technology TEXT NOT NULL,
                name TEXT NOT NULL,
                content BLOB NOT NULL,
                is_default INTEGER NOT NULL,
                created_at TEXT,
                updated_at TEXT
            )
            ''',
        )
        connection.execute(
            "INSERT INTO report_templates VALUES ('nsa', 'Template', X'', 1, '2026-09-16', '2026-09-16')",
        )
        statements: list[str] = []
        connection.set_trace_callback(statements.append)

        repository._ensure_report_template_columns(connection)

    timestamp_updates = [
        statement for statement in statements
        if statement.upper().startswith('UPDATE REPORT_TEMPLATES SET CREATED_AT')
        or statement.upper().startswith('UPDATE REPORT_TEMPLATES SET UPDATED_AT')
    ]
    assert timestamp_updates == []


def test_catalogue_editor_offers_result_group_for_every_cdr_source(client) -> None:
    import src.DashboardAnalytic as app_module

    dimensions = app_module.parse_calculated_dimensions(app_module.default_calculated_dimensions())
    columns = app_module.catalogue_editor_columns([], dimensions)

    assert all('Result Group' in values for values in columns.values())


def test_catalogue_editor_offers_declarative_distribution_bucket_fields(client) -> None:
    import src.DashboardAnalytic as app_module

    columns = app_module.catalogue_editor_columns([], ())

    assert {'Buckets', 'Rate Bucket'} <= set(columns['cdr-data'])


def test_config_page_persists_runtime_overrides(client, monkeypatch) -> None:
    monkeypatch.setenv('DASHBOARD_ANALYTIC_REPORT_CHART_RENDERER', 'dashboard-canvas')
    monkeypatch.setenv('IGNORE_EVENT_TIME_FILTERING', 'false')
    login(client)
    page = client.get('/config')
    assert page.status_code == 200
    assert 'Application Runtime' in page.text
    assert 'href="/config"' in page.text
    assert 'data-configuration-timezone-picker' in page.text
    assert 'data-timezone="Europe/Madrid"' in page.text
    assert page.text.count('data-configuration-card') == 4
    assert 'name="max_background_tasks" value="1" min="1" max="32"' in page.text
    assert '<section class="configuration-card configuration-field-wide" data-configuration-card>' not in page.text

    response = client.post('/config', data={
        'timezone_name': 'UTC',
        'report_chart_renderer': 'pil',
        'chromium_path': '',
        'ignore_event_time_filtering': 'true',
        'max_background_tasks': '1',
    }, follow_redirects=False)
    assert response.status_code == 303
    import src.DashboardAnalytic as app_module

    persisted = app_module.runtime_configuration()
    assert persisted['timezone'] == 'UTC'
    assert persisted['report_chart_renderer'] == 'pil'
    assert persisted['ignore_event_time_filtering'] is True
    assert persisted['max_background_tasks'] == 1
    assert app_module.os.environ['DASHBOARD_ANALYTIC_REPORT_CHART_RENDERER'] == 'pil'
    assert app_module.os.environ['IGNORE_EVENT_TIME_FILTERING'] == 'true'


def test_cdr_materialisation_adds_workspace_dimensions_to_dataset_rows() -> None:
    import pandas as pd
    import src.DashboardAnalytic as app_module

    dimensions = app_module.parse_calculated_dimensions(app_module.default_calculated_dimensions())
    frame = app_module.materialize_calculated_dimensions(pd.DataFrame({
        'Session_Type': ['VoLTE'], 'Type_of_Test': ['HTTP'], 'Test_Name': ['YouTube'],
        'Test Family': ['stale duplicate candidate'],
    }), dimensions, 'cdr-data')

    assert 'Call Family' not in frame.columns
    assert frame['Test Family'].tolist() == ['YouTube']
    assert frame.columns.tolist().count('Test Family') == 1


def test_calculated_dimension_rules_ignore_case_and_compact_redundant_field_aliases() -> None:
    import pandas as pd
    from src.modules.cdr_reporting import calculated_dimensions_json, materialize_calculated_dimensions, parse_calculated_dimensions

    dimensions = parse_calculated_dimensions([{
        'name': 'Test Family', 'sources': ['cdr-data'], 'default': '', 'default_from': 'Test_Name|test_name',
        'rules': [{'when': 'Test_Name|test_name CONTAINS YOUTUBE', 'value': 'YouTube'}],
    }])
    frame = materialize_calculated_dimensions(pd.DataFrame({'test_name': ['youtube']}), dimensions, 'cdr-data')
    voice_frame = materialize_calculated_dimensions(
        pd.DataFrame({'Session_Type': ['VoLTE'], 'Test Family': ['stale value']}), dimensions, 'cdr-voice',
    )

    assert frame['Test Family'].tolist() == ['YouTube']
    assert 'Test Family' not in voice_frame.columns
    payload = calculated_dimensions_json(dimensions)[0]
    assert payload['default_from'] == '[Test_Name]'
    assert payload['rules'][0]['when'] == '[Test_Name] CONTAINS YOUTUBE'


def test_calculated_dimension_alias_separators_are_serialized_with_readable_spacing() -> None:
    import pandas as pd
    from src.modules.cdr_reporting import (
        calculated_dimensions_json, materialize_calculated_dimensions, parse_calculated_dimensions,
    )

    dimensions = parse_calculated_dimensions([{
        'name': 'Fallback Group', 'sources': ['cdr-data'], 'default': '',
        'default_from': 'RAT | RAT_A| Sample_RAT_A',
        'rules': [{
            'when': 'RAT | RAT_A| Sample_RAT_A CONTAINS LTE',
            'value': 'LTE',
        }],
    }])

    payload = calculated_dimensions_json(dimensions)[0]
    assert payload['default_from'] == '[RAT] OR [RAT_A] OR [Sample_RAT_A]'
    assert payload['rules'][0]['when'] == '[RAT] OR [RAT_A] OR [Sample_RAT_A] CONTAINS LTE'
    frame = materialize_calculated_dimensions(pd.DataFrame({'RAT_A': ['LTE']}), dimensions, 'cdr-data')
    assert frame['Fallback Group'].tolist() == ['LTE']


def test_calculated_dimensions_support_nested_tableau_if_expressions() -> None:
    import pandas as pd
    from src.modules.cdr_reporting import calculated_dimensions_json, materialize_calculated_dimensions, parse_calculated_dimensions

    expression = '''IF ([Test Name] = "FDTT UDP UL ST") THEN
  IF ([Mean Data Rate] < 1) THEN 'below1'
  ELSEIF ([Mean Data Rate] < 3) THEN 'below3'
  ELSEIF ([Mean Data Rate] < 10) THEN 'below10'
  ELSEIF ([Mean Data Rate] < 20) THEN 'below20'
  ELSEIF ([Mean Data Rate] > 20) THEN 'Above'
  END
ELSEIF ([Test Name] = "FDTT http DL MT") THEN
  IF ([Mean Data Rate] < 2) THEN 'below2'
  ELSEIF ([Mean Data Rate] < 5) THEN 'below5'
  ELSEIF ([Mean Data Rate] < 20) THEN 'below20'
  ELSEIF ([Mean Data Rate] < 100) THEN 'below100'
  ELSEIF ([Mean Data Rate] > 100) THEN 'Above'
  END
ELSE 'Not applicable'
END'''
    dimensions = parse_calculated_dimensions([{
        'name': 'Rate Group', 'sources': ['cdr-data'], 'expression': expression,
    }])
    frame = materialize_calculated_dimensions(pd.DataFrame({
        'Test Name': [
            'FDTT UDP UL ST', 'FDTT UDP UL ST', 'FDTT UDP UL ST',
            'FDTT http DL MT', 'FDTT http DL MT', 'Other',
        ],
        'Mean Data Rate': [0.5, 20, 20.1, 2, 101, 50],
    }), dimensions, 'cdr-data')

    values = frame['Rate Group'].tolist()
    assert values[:1] == ['below1']
    assert pd.isna(values[1])
    assert values[2:] == ['Above', 'below5', 'Above', 'Not applicable']
    serialized = calculated_dimensions_json(dimensions)[0]
    assert serialized['expression'] == expression
    assert {rule['value'] for rule in serialized['rules']} >= {'below1', 'below100', 'Above', 'Not applicable'}


def test_nested_if_consumes_matching_outer_branch_before_outer_elseif() -> None:
    import pandas as pd
    from src.modules.cdr_reporting import materialize_calculated_dimensions, parse_calculated_dimensions

    dimensions = parse_calculated_dimensions([{
        'name': 'Decision', 'sources': ['cdr-data'], 'default': 'Fallback',
        'expression': '''IF ([Score] > 0) THEN
  IF ([Kind] = "accepted") THEN 'First branch'
  END
ELSEIF ([Score] > -1) THEN 'Second branch'
ELSE 'Negative'
END''',
    }])
    frame = materialize_calculated_dimensions(pd.DataFrame({
        'Score': [1, 1, 0, -1],
        'Kind': ['accepted', 'other', 'other', 'other'],
    }), dimensions, 'cdr-data')

    assert frame['Decision'].tolist() == ['First branch', 'Fallback', 'Second branch', 'Negative']


def test_incremental_auto_field_materialization_compiles_tableau_if_expression(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'if-expression.db')
    repository.initialize()
    with repository.connection() as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Test_Name TEXT, Mean_Data_Rate REAL)')
        connection.executemany('INSERT INTO dataset_rows_1 VALUES (?, ?)', [
            ('FDTT UDP UL ST', 0.5),
            ('FDTT UDP UL ST', 20),
            ('FDTT http DL MT', 4),
            ('Other', 50),
        ])
    dimensions = app_module.parse_calculated_dimensions([{
        'name': 'Rate Group', 'sources': ['cdr-data'], 'default': 'Unclassified',
        'expression': '''IF ([Test_Name] = "FDTT UDP UL ST") THEN
  IF ([Mean_Data_Rate] < 1) THEN 'below1'
  ELSEIF ([Mean_Data_Rate] > 20) THEN 'Above'
  END
ELSEIF ([Test_Name] = "FDTT http DL MT") THEN
  IF ([Mean_Data_Rate] < 5) THEN 'below5'
  ELSE 'Above'
  END
END''',
    }])

    app_module._incremental_auto_field_table_update(
        repository, 'dataset_rows_1', 'cdr-data', (), dimensions, {},
    )

    with repository.connection() as connection:
        values = [row['Rate Group'] for row in connection.execute('SELECT "Rate Group" FROM dataset_rows_1 ORDER BY rowid')]
    assert values == ['below1', 'Unclassified', 'below5', 'Unclassified']


def test_incremental_auto_field_materialization_updates_columns_in_place(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'incremental.db')
    repository.initialize()
    with repository.connection() as connection:
        connection.execute(
            'CREATE TABLE dataset_rows_1 ('
            'Test_Name TEXT, Score TEXT, Fallback TEXT, "Old Group" TEXT)'
        )
        connection.executemany(
            'INSERT INTO dataset_rows_1 VALUES (?, ?, ?, ?)',
            [
                ('YOUTUBE', '1', 'raw-a', 'stale'),
                ('web', '12', 'raw-b', 'stale'),
                ('web', 'bad', 'raw-c', 'stale'),
            ],
        )
    previous = app_module.parse_calculated_dimensions([{
        'name': 'Old Group', 'sources': ['cdr-data'], 'default': 'Old', 'rules': [],
    }])
    current = app_module.parse_calculated_dimensions([{
        'name': 'Result Group', 'sources': ['cdr-data'], 'default': '', 'default_from': 'Fallback',
        'rules': [
            {'when': 'Test_Name CONTAINS youtube', 'value': 'Video'},
            {'when': 'Score >= 10', 'value': 'High'},
        ],
    }])

    changed = app_module._incremental_auto_field_table_update(
        repository, 'dataset_rows_1', 'cdr-data', previous, current,
        {'Old Group': 'Result Group'},
    )

    assert changed is True
    with repository.connection() as connection:
        columns = [row['name'] for row in connection.execute('PRAGMA table_info(dataset_rows_1)')]
        values = [row['Result Group'] for row in connection.execute('SELECT "Result Group" FROM dataset_rows_1')]
    assert 'Old Group' not in columns
    assert columns.count('Result Group') == 1
    assert values == ['Video', 'High', 'raw-c']


def test_incremental_auto_fields_preserve_ordered_dependencies(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'dependencies.db')
    repository.initialize()
    with repository.connection() as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Test_Name TEXT)')
        connection.executemany(
            'INSERT INTO dataset_rows_1 VALUES (?)', [('youtube',), ('web',)],
        )
    dimensions = app_module.parse_calculated_dimensions([
        {
            'name': 'Family', 'sources': ['cdr-data'], 'default': 'Other',
            'rules': [{'when': 'Test_Name CONTAINS youtube', 'value': 'Video'}],
        },
        {
            'name': 'Category', 'sources': ['cdr-data'], 'default': 'General',
            'rules': [{'when': 'Family = VIDEO', 'value': 'Streaming'}],
        },
    ])

    app_module._incremental_auto_field_table_update(
        repository, 'dataset_rows_1', 'cdr-data', (), dimensions, {},
    )

    with repository.connection() as connection:
        values = [tuple(row) for row in connection.execute(
            'SELECT Family, Category FROM dataset_rows_1 ORDER BY rowid',
        )]
    assert values == [('Video', 'Streaming'), ('Other', 'General')]


def test_incremental_auto_field_materialization_yields_between_write_batches(
    tmp_path: Path, monkeypatch,
) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'batched-auto-fields.db')
    repository.initialize()
    with repository.connection() as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Test_Name TEXT)')
        connection.executemany(
            'INSERT INTO dataset_rows_1 VALUES (?)',
            [(f'test-{index}',) for index in range(7)],
        )
    dimensions = app_module.parse_calculated_dimensions([{
        'name': 'Family', 'sources': ['cdr-data'], 'default': 'Other',
        'rules': [{'when': 'Test_Name CONTAINS test', 'value': 'Matched'}],
    }])
    monkeypatch.setattr(app_module, 'AUTO_FIELD_UPDATE_BATCH_SIZE', 2)
    checkpoints: list[int] = []
    row_progress: list[tuple[int, int]] = []

    def checkpoint() -> None:
        checkpoints.append(len(checkpoints) + 1)
        if len(checkpoints) == 2:
            repository.set_workspace_state('foreground_save', 'completed')

    app_module._incremental_auto_field_table_update(
        repository, 'dataset_rows_1', 'cdr-data', (), dimensions, {},
        checkpoint=checkpoint,
        row_progress=lambda completed, total: row_progress.append((completed, total)),
    )

    assert len(checkpoints) >= 5
    assert row_progress[0] == (0, 7)
    assert row_progress[-1] == (7, 7)
    assert any(0 < completed < total for completed, total in row_progress)
    assert repository.get_workspace_state('foreground_save') == 'completed'
    with repository.connection() as connection:
        assert connection.execute(
            'SELECT COUNT(*) FROM dataset_rows_1 WHERE Family = ?', ('Matched',),
        ).fetchone()[0] == 7


def test_incremental_auto_fields_use_fallback_when_rule_columns_are_missing(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'missing-source.db')
    repository.initialize()
    with repository.connection() as connection:
        connection.execute('CREATE TABLE dataset_rows_1 (Existing TEXT)')
        connection.executemany('INSERT INTO dataset_rows_1 VALUES (?)', [('one',), ('two',)])
    dimensions = app_module.parse_calculated_dimensions([{
        'name': 'Family', 'sources': ['cdr-data'], 'default': 'Other',
        'rules': [{'when': 'Missing_Source = Value', 'value': 'Matched'}],
    }])

    app_module._incremental_auto_field_table_update(
        repository, 'dataset_rows_1', 'cdr-data', (), dimensions, {},
    )

    with repository.connection() as connection:
        values = [row['Family'] for row in connection.execute('SELECT Family FROM dataset_rows_1')]
    assert values == ['Other', 'Other']


def test_incremental_auto_fields_update_existing_combined_reporting_table(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'combined.db')
    repository.initialize()
    dataset_id, _created = repository.add_dataset('data.csv', str(tmp_path / 'data.csv'), 'admin')
    repository.update_dataset_profile(dataset_id, status='ready', dataset_kind='data')
    with repository.connection() as connection:
        connection.execute(f'CREATE TABLE dataset_rows_{dataset_id} (Test_Name TEXT)')
        connection.execute(f"INSERT INTO dataset_rows_{dataset_id} VALUES ('youtube')")
    repository.copy_dataset_rows_to_reporting(dataset_id, 'data')
    dimensions = app_module.parse_calculated_dimensions([{
        'name': 'Family', 'sources': ['cdr-data'], 'default': 'Other',
        'rules': [{'when': 'Test_Name CONTAINS youtube', 'value': 'Video'}],
    }])

    progress: list[tuple[int, int, str]] = []
    stats = app_module.materialize_workspace_auto_fields_incrementally(
        (), dimensions, {}, repository, {'cdr-data'},
        progress_callback=lambda completed, total, message: progress.append((completed, total, message)),
    )

    assert stats['datasets'] == 1
    assert stats['combined_tables'] == 1
    assert progress[-1][0] == progress[-1][1] == 2_000
    assert any('Table 1 of 2' in message and 'row operations' in message for _, _, message in progress)
    with repository.connection() as connection:
        value = connection.execute('SELECT Family FROM reporting_rows_data').fetchone()[0]
    assert value == 'Video'


def test_incremental_auto_fields_reconcile_new_dataset_into_existing_combined_table(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'combined-membership.db')
    repository.initialize()
    first_id, _created = repository.add_dataset('first.csv', str(tmp_path / 'first.csv'), 'admin')
    second_id, _created = repository.add_dataset('second.csv', str(tmp_path / 'second.csv'), 'admin')
    for dataset_id in (first_id, second_id):
        repository.update_dataset_profile(dataset_id, status='ready', dataset_kind='voice')
        with repository.connection() as connection:
            connection.execute(
                f'CREATE TABLE dataset_rows_{dataset_id} (Test_Name TEXT)'
            )
            connection.execute(
                f"INSERT INTO dataset_rows_{dataset_id} VALUES (?)", (f'test-{dataset_id}',)
            )
    repository.copy_dataset_rows_to_reporting(first_id, 'voice')
    dimensions = app_module.parse_calculated_dimensions([{
        'name': 'Family', 'sources': ['cdr-voice'], 'default': 'Other',
        'rules': [{'when': 'Test_Name CONTAINS test', 'value': 'Video'}],
    }])

    app_module.materialize_workspace_auto_fields_incrementally(
        (), dimensions, {}, repository, {'cdr-voice'},
    )

    with repository.connection() as connection:
        count = connection.execute('SELECT COUNT(*) AS count FROM reporting_rows_voice').fetchone()['count']
    assert count == 2


def test_incremental_auto_fields_create_missing_combined_reporting_table(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'new-combined.db')
    repository.initialize()
    dataset_id, _created = repository.add_dataset('data.csv', str(tmp_path / 'data.csv'), 'admin')
    repository.update_dataset_profile(dataset_id, status='ready', dataset_kind='data')
    with repository.connection() as connection:
        connection.execute(f'CREATE TABLE dataset_rows_{dataset_id} (Test_Name TEXT)')
        connection.execute(f"INSERT INTO dataset_rows_{dataset_id} VALUES ('youtube')")
    dimensions = app_module.parse_calculated_dimensions([{
        'name': 'Family', 'sources': ['cdr-data'], 'default': 'Other',
        'rules': [{'when': 'Test_Name CONTAINS youtube', 'value': 'Video'}],
    }])

    stats = app_module.materialize_workspace_auto_fields_incrementally(
        (), dimensions, {}, repository, {'cdr-data'},
    )

    assert stats['combined_tables'] == 1
    with repository.connection() as connection:
        value = connection.execute('SELECT Family FROM reporting_rows_data').fetchone()[0]
    assert value == 'Video'


def test_combined_tables_materialize_fixed_preview_fields_and_every_saved_template_kpi(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.column_names import MAIN_CDR_FIELDS, PREVIEW_METADATA_FIELDS, column_identity
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'template-kpis.db')
    repository.initialize()
    fixture = (app_module.PROJECT_ROOT / 'tests' / 'fixtures' / 'NSA Slide Template.csv').read_bytes()
    entries = app_module.parse_catalog_csv(fixture, 'nsa', validate_filters=False)
    data_entry = next(entry for entry in entries if entry.source_kind == 'data')
    voice_entry = next(entry for entry in entries if entry.source_kind == 'voice')
    repository.add_report_template(
        'nsa', 'Data coordinates',
        app_module.catalogue_csv([replace(data_entry, kpi='Latitude vs Longitude')]),
    )
    repository.add_report_template(
        'sa', 'Voice quality',
        app_module.catalogue_csv([replace(voice_entry, kpi='Voice_Metric | Voice_Backup')]),
    )
    dataset_id, _created = repository.add_dataset('data.csv', str(tmp_path / 'data.csv'), 'admin')
    repository.update_dataset_profile(dataset_id, status='ready', dataset_kind='data', row_count=1)
    with repository.connection() as connection:
        connection.execute(
            f'CREATE TABLE dataset_rows_{dataset_id} ('
            'source_file TEXT, source_sheet TEXT, dataset_kind TEXT, Operator TEXT, '
            'Latitude REAL, Longitude REAL)'
        )
        connection.execute(
            f'INSERT INTO dataset_rows_{dataset_id} VALUES (?, ?, ?, ?, ?, ?)',
            ('data.csv', 'CDR', 'data', 'EE', 51.5, -0.1),
        )

    required = app_module.combined_reporting_required_columns((), 'data', repository)
    updated = app_module.materialize_workspace_combined_columns(repository, ())

    required_identities = {column_identity(column) for column in required}
    assert {column_identity(column) for column in (*PREVIEW_METADATA_FIELDS, *MAIN_CDR_FIELDS)} <= required_identities
    assert {'Latitude', 'Longitude'} <= set(required)
    assert 'Voice_Metric' not in required
    assert updated == 1
    assert {'Latitude', 'Longitude'} <= set(repository.list_reporting_row_columns('data'))


def test_recreate_combined_table_recovers_empty_source_rows_and_required_columns(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository
    from src.modules.workspaces import Workspace

    database_path = tmp_path / 'workspace.db'
    source_path = tmp_path / 'voice.csv'
    source_path.write_text(
        'Operator,vendor,RAT_A,Session_Type,Call_Status,Rule_Source,Fallback,Test_Name\n'
        'EE,Ericsson,ENDC,VoLTE,Completed,matched,ok,Voice\n'
        '3,Nokia,NR,WhatsApp,Failed,other,bad,Voice\n',
        encoding='utf-8',
    )
    repository = Repository(database_path)
    repository.initialize()
    dataset_id, _created = repository.add_dataset(source_path.name, str(source_path), 'admin')
    repository.update_dataset_profile(
        dataset_id, status='ready', dataset_kind='voice', row_count=2, column_count=8,
    )
    with repository.connection() as connection:
        connection.execute(f'CREATE TABLE dataset_rows_{dataset_id} (Test_Name TEXT)')
    repository.replace_calculated_dimensions([{
        'name': 'Outcome', 'sources': ['cdr-voice'], 'default': '', 'default_from': 'Fallback',
        'rules': [{'when': 'Rule_Source CONTAINS matched', 'value': 'Success'}],
    }, {
        'name': 'Outcome Group', 'sources': ['cdr-voice'], 'default': 'Other',
        'rules': [{'when': 'Outcome = Success', 'value': 'Passed'}],
    }])
    workspace = Workspace(
        'test', 'Test', database_path, tmp_path, tmp_path, tmp_path, tmp_path, '', '',
    )
    progress: list[tuple[int, int, str]] = []

    stats = app_module.recreate_combined_cdr_table(
        workspace, 'voice', lambda completed, total, message: progress.append((completed, total, message)),
    )

    assert stats == {'datasets': 1, 'rows': 2, 'tables': 2}
    assert repository.dataset_row_count(dataset_id) == 2
    assert repository.reporting_row_count('voice') == 2
    columns = repository.list_reporting_row_columns('voice')
    assert {'Rule_Source', 'Fallback', 'Outcome', 'Outcome Group'} <= set(columns)
    for _parameter, _label, candidates in app_module.CDR_PREVIEW_FILTER_DEFINITIONS:
        assert any(repository.resolve_reporting_row_column_name('voice', candidate) for candidate in candidates)
    assert len(progress) > 2
    assert progress[-1][0] == progress[-1][1]


def test_replacing_calculated_dimensions_marks_materialization_pending_atomically(tmp_path: Path) -> None:
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    repository.set_workspace_state('calculated_dimensions_need_materialization', '0')

    repository.replace_calculated_dimensions([{
        'name': 'Seven Cities', 'sources': ['cdr-data'], 'default': 'No', 'default_from': '',
        'rules': [{'when': 'G Level 4 IN (Belfast, Bristol)', 'value': 'Yes'}],
    }])

    assert repository.get_workspace_state('calculated_dimensions_need_materialization') == '1'


def test_starting_auto_field_job_does_not_repeat_pending_state_write(tmp_path: Path, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.cdr_reporting import parse_calculated_dimensions
    from src.modules.repository import Repository
    from src.modules.workspaces import Workspace

    database_path = tmp_path / 'workspace.db'
    repository = Repository(database_path)
    repository.initialize()
    workspace = Workspace(
        'test', 'Test', database_path, tmp_path, tmp_path, tmp_path, tmp_path, '', '',
    )
    submitted = []
    events = []

    def capture_submit(_repository, callback, *args, **_kwargs):
        events.append('submit')
        submitted.append((callback, args))

    monkeypatch.setattr(app_module, '_submit_workspace_job', capture_submit)
    monkeypatch.setattr(
        Repository, 'set_workspace_state',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('redundant pending-state write')),
    )
    current = parse_calculated_dimensions([{
        'name': 'Seven Cities', 'sources': ['cdr-data'], 'default': 'No',
        'rules': [{'when': 'G Level 4 IN (Belfast, Bristol)', 'value': 'Yes'}],
    }])

    job = app_module.start_auto_calculated_field_job(
        workspace, (), current, {}, 'tester', background=True,
        before_submit=lambda _job: events.append('audit'),
    )

    assert job['status'] == 'queued'
    assert len(submitted) == 1
    assert events == ['audit', 'submit']


def test_workspace_calculated_dimensions_panel_exports_and_imports_json(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    page = client.get('/workspace')
    assert page.status_code == 200
    assert 'data-workspace-calculated-dimensions-panel' in page.text
    assert 'data-auto-calculated-field-progress' in page.text
    assert 'data-auto-calculated-field-job-list' in page.text
    assert 'data-materialization-job-key="initial"' in page.text
    assert '>Edit</button>' in page.text
    assert 'Manage Auto-calculated Fields' not in page.text
    assert 'workspace-calculated-dimensions-import-panel' in page.text
    assert 'workspace-calculated-dimensions-list' in page.text
    assert 'combined-dataset-row' not in page.text
    assert '>Export</a>' in page.text
    assert '>Field<' in page.text
    assert '>Applied to<' in page.text
    assert page.text.index('workspace-calculated-dimensions-import-panel') < page.text.index('workspace-calculated-dimensions-list-panel')
    assert page.text.index('<h2>Datasets</h2>') < page.text.index('id="calculated-dimensions"')
    assert page.text.index('data-auto-calculated-field-progress') < page.text.index('id="calculated-dimensions"')
    materialization_panel = page.text.split('data-auto-calculated-field-progress', 1)[1].split('</section>', 1)[0]
    assert '<span>Re-materialize auto-calculate fields</span>' in materialization_panel
    assert materialization_panel.index('data-auto-calculated-field-rematerialize') < materialization_panel.index('data-auto-calculated-field-progress-status')
    calculated_panel = page.text.split('id="calculated-dimensions"', 1)[1]
    assert 'workspace-calculated-dimensions-intro' in calculated_panel
    assert 'data-auto-calculated-field-rematerialize' not in calculated_panel
    assert calculated_panel.index('data-workspace-manage-calculated-dimensions') < calculated_panel.index('workspace-calculated-dimensions-export-link')

    current_definitions = client.get('/api/workspace/calculated-dimensions')
    assert current_definitions.status_code == 200
    assert current_definitions.headers['cache-control'] == 'no-store'
    assert current_definitions.json()['dimensions'] == app_module.calculated_dimensions_json(
        app_module.load_workspace_calculated_dimensions()
    )
    assert {'cdr-data', 'cdr-voice', 'cdr-speech'} == set(current_definitions.json()['columns'])
    assert 'RAT' in current_definitions.json()['columns']['cdr-data']

    status = client.get('/api/workspace/auto-calculated-fields/materialization')
    assert status.status_code == 200
    assert status.json()['status'] in {'idle', 'queued', 'processing', 'ready'}

    rematerialized = client.post('/api/workspace/auto-calculated-fields/rematerialize')
    assert rematerialized.status_code == 200
    assert rematerialized.json()['materialization_job']
    assert rematerialized.json()['materialization_status_url'].startswith('/api/workspace/auto-calculated-fields/materialization/')

    exported = client.get('/workspace/calculated-dimensions/export')
    assert exported.status_code == 200
    assert exported.headers['content-type'].startswith('application/json')
    assert exported.json()

    imported = client.post(
        '/workspace/calculated-dimensions/import',
        files={'dimensions_file': ('dimensions.json', BytesIO(json.dumps([{
            'name': 'Imported Group', 'sources': ['cdr-data'], 'default': 'Other',
            'default_from': '', 'rules': [{'when': 'Test_Result = Completed', 'value': 'Success'}],
        }]).encode()), 'application/json')},
        follow_redirects=False,
    )
    assert imported.status_code == 303

    assert any(item.name == 'Imported Group' for item in app_module.load_workspace_calculated_dimensions())
    assert not list(app_module.settings.slides_templates_dir.rglob('*.dimensions.json'))


def test_saving_calculated_dimensions_without_materialization_does_not_start_a_job(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    dimensions = app_module.calculated_dimensions_json(app_module.load_workspace_calculated_dimensions())
    dimensions[0]['default'] = 'Saved without materialization'
    monkeypatch.setattr(
        app_module,
        'start_auto_calculated_field_job',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('materialization must not start')),
    )

    response = client.put('/api/workspace/calculated-dimensions', json={
        'dimensions': dimensions,
        'renames': [],
        'materialize': False,
    })

    assert response.status_code == 200
    assert response.json()['notice'] == 'The fields were saved. Materialization was not started.'
    assert 'materialization_job' not in response.json()
    assert 'materialization_status_url' not in response.json()
    assert app_module.repository.get_workspace_state('calculated_dimensions_need_materialization') == 'saved'
    assert app_module.calculated_dimensions_json(app_module.load_workspace_calculated_dimensions())[0]['default'] == 'Saved without materialization'

    status = client.get('/api/workspace/auto-calculated-fields/materialization')
    assert status.json()['status'] == 'pending'


def test_materialization_status_returns_every_active_workspace_job(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace_id = app_module.active_workspace.id
    monkeypatch.setattr(app_module, 'AUTO_CALCULATED_FIELD_JOBS', {
        'speech-job': {
            'id': 'speech-job', 'workspace_id': workspace_id, 'operation': 'combined_recreation',
            'combined_kind': 'speech', 'status': 'processing', 'completed': 45, 'total': 301,
            'message': 'Migrating individual CDR-SPEECH table 1 of 3', 'created_at': 1,
            'username': 'admin',
        },
        'data-job': {
            'id': 'data-job', 'workspace_id': workspace_id, 'operation': 'combined_recreation',
            'combined_kind': 'data', 'status': 'queued', 'completed': 0, 'total': 0,
            'message': 'Waiting to migrate individual CDR-DATA tables', 'created_at': 2,
            'username': 'admin',
        },
    })

    response = client.get('/api/workspace/auto-calculated-fields/materialization')

    assert response.status_code == 200
    assert [job['id'] for job in response.json()['jobs']] == ['speech-job', 'data-job']
    assert all('username' not in job for job in response.json()['jobs'])

    background_tasks = client.get('/api/background-tasks').json()['groups']
    tasks = next(group['tasks'] for group in background_tasks if group['workspace_id'] == workspace_id)
    task_by_id = {task['id']: task for task in tasks}
    assert task_by_id['auto-fields:speech-job']['status'] == 'processing'
    assert task_by_id['auto-fields:speech-job']['progress'] == 15
    assert task_by_id['auto-fields:data-job']['status'] == 'queued'
    assert task_by_id['auto-fields:data-job']['progress'] == 0
    assert task_by_id['auto-fields:data-job']['started_at'] is None


def test_stopped_materialization_status_retains_its_real_progress(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace_id = app_module.active_workspace.id
    app_module.repository.set_workspace_state('calculated_dimensions_need_materialization', 'stopped')
    monkeypatch.setattr(app_module, 'AUTO_CALCULATED_FIELD_JOBS', {
        'stopped-job': {
            'id': 'stopped-job', 'workspace_id': workspace_id, 'status': 'stopped',
            'completed': 2, 'total': 10, 'created_at': 1,
            'message': 'Materialization stopped by user.',
        },
    })

    status = client.get('/api/workspace/auto-calculated-fields/materialization').json()

    assert status['status'] == 'stopped'
    assert status['completed'] == 2
    assert status['total'] == 10
    assert status['jobs'] == []


def test_combined_table_progress_matches_its_active_recreation_job(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('cdr_data.csv', BytesIO(b'operator,score\nVodafone UK,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    app_module.repository.copy_dataset_rows_to_reporting(1, 'data', ['score'])
    workspace_id = app_module.active_workspace.id
    monkeypatch.setattr(app_module, 'AUTO_CALCULATED_FIELD_JOBS', {
        'queued-data': {
            'id': 'queued-data', 'workspace_id': workspace_id, 'operation': 'combined_recreation',
            'combined_kind': 'data', 'status': 'queued', 'completed': 0, 'total': 0, 'created_at': 1,
        },
    })

    queued = next(item for item in app_module.workspace_combined_tables(workspace_id=workspace_id) if item['kind'] == 'data')
    assert queued['is_recalculating'] is True
    assert queued['recreation_status'] == 'queued'
    assert queued['recreation_progress'] == 0
    assert queued['recreation_stop_task_id'] == 'auto-fields:queued-data'
    assert queued['recreation_stop_url'] == f'/api/background-tasks/{workspace_id}/stop'
    workspace_page = client.get('/workspace')
    assert workspace_page.status_code == 200
    assert 'data-combined-dataset-stop' in workspace_page.text
    assert 'data-stop-task-id="auto-fields:queued-data"' in workspace_page.text
    assert 'aria-label="Stop combined table recreation"' in workspace_page.text

    app_module.AUTO_CALCULATED_FIELD_JOBS['queued-data'].update(status='processing', completed=41, total=100)
    processing = next(item for item in app_module.workspace_combined_tables(workspace_id=workspace_id) if item['kind'] == 'data')
    assert processing['recreation_progress'] == 41


def test_renaming_calculated_dimension_rebuilds_references_in_templates_and_dashboards(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.set_workspace_state(app_module.DASHBOARD_STATE_KEY, json.dumps({
        'dashboard-1': {
            'name': 'Calculated fields dashboard', 'template': 'Baseline Q4',
            'filters': {'Test Family': ['Video'], 'Operator': ['EE']},
            'custom_fields': ['Test Family', 'Call Family'],
            'hidden_filters': ['Test Family'],
        },
    }))
    dimensions = app_module.calculated_dimensions_json(app_module.load_workspace_calculated_dimensions())
    renamed = next(item for item in dimensions if item['name'] == 'Test Family')
    renamed['name'] = 'Test Classification'

    response = client.put('/api/workspace/calculated-dimensions', json={
        'dimensions': dimensions,
        'renames': [{'from': 'Test Family', 'to': 'Test Classification'}],
    })

    assert response.status_code == 200
    assert response.json()['materialization_job']
    assert response.json()['materialization_status_url'].startswith('/api/workspace/auto-calculated-fields/materialization/')
    assert response.json()['renamed_templates'] >= 1
    assert response.json()['renamed_dashboards'] == 1
    assert any(item.name == 'Test Classification' for item in app_module.load_workspace_calculated_dimensions())
    template = next(item for item in app_module.report_catalogue_options('nsa') if item['active'])
    template_text = bytes(template['content']).decode('utf-8')
    assert 'Test Classification' in template_text
    assert 'Test Family' not in template_text
    dashboards = json.loads(app_module.repository.get_workspace_state(app_module.DASHBOARD_STATE_KEY) or '{}')
    assert dashboards['dashboard-1']['custom_fields'] == ['Test Classification', 'Call Family']
    assert dashboards['dashboard-1']['hidden_filters'] == ['Test Classification']
    assert dashboards['dashboard-1']['filters'] == {'Test Classification': ['Video'], 'Operator': ['EE']}


def test_reporting_deletion_requires_admin(client) -> None:
    import src.DashboardAnalytic as app_module

    endpoints = [
        '/reporting/chart-sets/delete-all',
        '/reporting/chart-sets/missing/delete',
        '/reporting/chart-jobs/999999/delete',
        '/reporting/jobs/999999/charts/delete',
        '/reporting/jobs/999999/delete',
        '/reporting/jobs/delete-all',
    ]
    for username, password, allowed in [
        ('demo', 'demo123', False),
        ('admin', 'admin123', True),
        ('super', 'super123', True),
    ]:
        response = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
        assert response.status_code == 303
        page = client.get('/reporting')
        assert page.status_code == 200
        assert ('data-report-chart-set-delete>Delete Selected' in page.text) == allowed
        assert ('class="report-jobs-bulk-actions"' in page.text) == allowed
        # Live job renderers must not recreate delete buttons for normal users.
        assert ('remove.dataset.reportJobDelete = job.delete_url' in page.text) == allowed
        assert ('remove.dataset.reportChartJobDelete = job.delete_url' in page.text) == allowed
        marker = app_module.settings.output_dir / 'reports' / 'permission-check.txt'
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('Preserve for normal users', encoding='utf-8')
        for endpoint in endpoints:
            result = client.post(endpoint)
            expected = (202 if endpoint.endswith('delete-all') else 404) if allowed else 403
            assert result.status_code == expected
        if allowed:
            deadline = time.monotonic() + 5
            while marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        assert marker.exists() == (not allowed)


def login_super(client) -> None:
    response = client.post("/login", data={"username": "super", "password": "super123"}, follow_redirects=False)
    assert response.status_code == 303


def test_login_page_loads(client) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "Log in" in response.text
    assert "Dashboard Analytic" in response.text
    assert __release_date__ in response.text
    assert "Default Access:" in response.text
    assert "<strong class=\"login-default-role login-default-role-super-admin\">Role: super-admin</strong>" in response.text
    assert "<strong class=\"login-default-role login-default-role-admin\">Role: admin</strong>" in response.text
    assert "<strong class=\"login-default-role login-default-role-user\">Role: user</strong>" in response.text
    assert 'class="login-workspace-field">Workspace' in response.text
    assert 'data-login-password-toggle' in response.text
    assert '<span class="login-password-editor">' in response.text
    assert 'Default' in response.text


def test_successful_login_and_authenticated_root_open_readme(client) -> None:
    response = client.post(
        '/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers['location'] == '/documents/view/readme'

    root = client.get('/', follow_redirects=False)
    assert root.status_code == 303
    assert root.headers['location'] == '/documents/view/readme'


def test_new_environment_creates_the_three_bootstrap_roles(client) -> None:
    import src.DashboardAnalytic as app_module

    roles = {row['username']: row['role'] for row in app_module.repository.list_users()}
    assert roles['super'] == 'super-admin'
    assert roles['admin'] == 'admin'
    assert roles['demo'] == 'user'


def test_bootstrap_users_are_not_recreated_after_the_first_start(client) -> None:
    import src.DashboardAnalytic as app_module

    with app_module.repository.global_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", ('super',))
        conn.execute("UPDATE users SET username = ? WHERE username = ?", ('renamed-admin', 'admin'))

    app_module.repository.initialize()

    assert app_module.repository.get_user('super') is None
    assert app_module.repository.get_user('admin') is None
    assert app_module.repository.get_user('renamed-admin') is not None
    assert app_module.repository.get_user('demo') is not None


def test_login_page_hides_missing_default_access_accounts(client) -> None:
    import src.DashboardAnalytic as app_module

    with app_module.repository.global_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", ("demo",))

    response = client.get("/login")
    assert response.status_code == 200
    assert "Default Access:" in response.text
    assert "admin / admin123" in response.text
    assert "demo / demo123" not in response.text


def test_login_page_hides_default_access_when_password_differs_from_default(client) -> None:
    import src.DashboardAnalytic as app_module

    with app_module.repository.global_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password("changed-password"), "demo"),
        )

    response = client.get("/login")
    assert response.status_code == 200
    assert "Default Access:" in response.text
    assert "admin / admin123" in response.text
    assert "demo / demo123" not in response.text


def test_login_page_hides_default_access_section_when_no_default_users_exist(client) -> None:
    import src.DashboardAnalytic as app_module

    with app_module.repository.global_connection() as conn:
        conn.execute("DELETE FROM users WHERE username IN (?, ?, ?)", ("super", "admin", "demo"))

    response = client.get("/login")
    assert response.status_code == 200
    assert "Default Access:" not in response.text
    assert "admin / admin123" not in response.text
    assert "demo / demo123" not in response.text


def test_login_username_is_case_insensitive_and_rejects_case_duplicates(client) -> None:
    import src.DashboardAnalytic as app_module

    admin = next(row for row in app_module.repository.list_users() if row['username'] == 'admin')
    app_module.repository.set_user_workspace_access(int(admin['id']), ['default'])
    mixed_case_login = client.post(
        '/login',
        data={'username': 'AdMiN', 'password': 'admin123', 'workspace_id': 'default'},
        follow_redirects=False,
    )
    assert mixed_case_login.status_code == 303

    assert app_module.repository.get_user('ADMIN').username == 'admin'
    demo = next(row for row in app_module.repository.list_users() if row['username'] == 'demo')
    app_module.repository.set_user_workspace_access(int(demo['id']), ['default'])
    assert app_module.repository.user_has_workspace_access('DeMo', 'default')

    duplicate = client.post(
        '/admin/users',
        data={'username': 'ADMIN', 'password': 'other-password', 'role': 'user'},
    )
    assert duplicate.status_code == 400
    assert 'already exists' in duplicate.text


def test_bootstrap_demo_can_access_default_workspace(client) -> None:
    response = client.post(
        '/login',
        data={'username': 'demo', 'password': 'demo123', 'workspace_id': 'default'},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_bootstrap_users_have_default_workspace_access(client) -> None:
    import src.DashboardAnalytic as app_module

    granted_admin = client.post(
        '/login',
        data={'username': 'admin', 'password': 'admin123', 'workspace_id': 'default'},
        follow_redirects=False,
    )
    assert granted_admin.status_code == 303

    granted_demo = client.post(
        '/login',
        data={'username': 'demo', 'password': 'demo123', 'workspace_id': 'default'},
        follow_redirects=False,
    )
    assert granted_demo.status_code == 303
    assert app_module.repository.user_has_workspace_access('super', 'default')
    assert app_module.repository.user_has_workspace_access('admin', 'default')
    assert app_module.repository.user_has_workspace_access('demo', 'default')

    super_admin = client.post(
        '/login',
        data={'username': 'super', 'password': 'super123', 'workspace_id': 'default'},
        follow_redirects=False,
    )
    assert super_admin.status_code == 303


def test_admin_import_export_packages_detect_configuration_and_workspaces(client) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    admin_response = client.get('/admin')
    assert admin_response.status_code == 200
    assert 'Import / Export / Transfer' in admin_response.text
    assert 'Transfer to other server' in admin_response.text
    assert 'name="export_target" multiple size="1" data-export-target-select data-multiselect-groups="true"' in admin_response.text
    assert '<optgroup label="Configuration Content">' in admin_response.text
    assert '<optgroup label="Workspace Content">' in admin_response.text
    assert '<optgroup label="Full Workspace">' in admin_response.text
    assert '<optgroup label="Full Environment">' in admin_response.text
    assert admin_response.text.index('<optgroup label="Full Workspace">') < admin_response.text.index('<optgroup label="Full Environment">')
    assert 'Config</option>' in admin_response.text
    assert 'Operator/Vendor Mappings &amp; Colors (from active workspace)' in admin_response.text
    assert 'Full Environment (App Config + Dashboards + Report Templates + Operator/Vendor Mappings &amp; Colors + Auto-calculated Fields + Selected Workspaces)' in admin_response.text
    assert 'Workspace: Default' in admin_response.text
    stylesheet = app_module.PROJECT_ROOT.joinpath('src/web_interface/static/css/app.css').read_text(encoding='utf-8')
    assert '.multiselect-shell { position: relative; min-width: 0; max-width: 100%; }' in stylesheet
    assert '.multiselect-trigger-label { flex: 1 1 auto; min-width: 0;' in stylesheet
    assert '.admin-export-components { min-width: 0; }' in stylesheet

    config_response = client.get('/admin/import-export/export?export_target=config')
    assert config_response.status_code == 200
    with zipfile.ZipFile(BytesIO(config_response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert 'config/workspace-registry.db' not in archive.namelist()
    assert manifest == {
        'components': ['app_database'],
        'format': 'dashboard-analytic-export',
        'includes_slides_templates': False,
        'kind': 'config',
        'version': 1,
    }

    fields_response = client.get('/admin/import-export/export?export_target=auto-calculated-fields')
    assert fields_response.status_code == 200
    with zipfile.ZipFile(BytesIO(fields_response.content)) as archive:
        fields_manifest = json.loads(archive.read('manifest.json'))
        exported_fields = json.loads(archive.read(fields_manifest['archive_path']))
    assert fields_manifest['kind'] == 'auto-calculated-fields'
    assert fields_manifest['source_workspace']['name'] == 'Default'
    assert exported_fields
    fields_inspection = client.post(
        '/admin/import-export/inspect',
        files={'package': ('auto-fields.zip', BytesIO(fields_response.content), 'application/zip')},
    )
    assert fields_inspection.status_code == 200
    assert fields_inspection.json()['destination_workspaces'] == [{'id': 'default', 'name': 'Default'}]
    fields_import = client.post(
        '/admin/import-export/import/jobs',
        data={
            'upload_id': fields_inspection.headers['X-Import-Upload-Id'],
            'confirmed_import': 'true',
            'workspace_ids': 'default',
        },
    )
    assert fields_import.status_code == 200
    for _attempt in range(100):
        fields_status = client.get(fields_import.json()['status_url']).json()
        if fields_status['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert fields_status['status'] == 'ready'
    saved_field_names = [
        app_module._normalise_catalogue_dimension_name(item.name)
        for item in app_module.load_workspace_calculated_dimensions()
    ]
    assert len(saved_field_names) == len(set(saved_field_names))

    workspace_response = client.get('/admin/import-export/export?export_target=workspace:default')
    assert workspace_response.status_code == 200
    inspection_response = client.post(
        '/admin/import-export/inspect',
        files={'package': ('default-workspace.zip', BytesIO(workspace_response.content), 'application/zip')},
    )
    assert inspection_response.json() == {
        'kind': 'workspace',
        'includes_slides_templates': False,
        'workspace_collisions': ['Default'],
    }
    close_response = client.post('/workspace/close', data={'workspace_id': 'default'}, follow_redirects=False)
    assert close_response.status_code == 303
    imported_response = client.post(
        '/admin/import-export/import',
        data={'confirmed_import': 'true'},
        files={'package': ('default-workspace.zip', BytesIO(workspace_response.content), 'application/zip')},
        follow_redirects=False,
    )
    assert imported_response.status_code == 303
    assert 'import_export_notice=' in imported_response.headers['location']
    assert any(workspace.name == 'Default' for workspace in app_module.workspace_registry.list())

    app_module.repository.set_workspace_state('e2e_dashboards_v2', json.dumps({
        'exported-dashboard': {'name': 'Exported Dashboard'},
    }))
    full_response = client.get('/admin/import-export/export?export_target=full-environment')
    assert full_response.status_code == 200
    with zipfile.ZipFile(BytesIO(full_response.content)) as archive:
        full_manifest = json.loads(archive.read('manifest.json'))
        assert full_manifest['kind'] == 'full-environment'
        assert len(full_manifest['workspaces']) == 1
        assert full_manifest['workspaces'][0]['id'] == 'default'
        assert {'super', 'admin', 'demo'} <= set(full_manifest['workspaces'][0]['access_usernames'])
        assert 'dashboards' in full_manifest['workspace_components']
        assert 'operator_mappings' in full_manifest['workspace_components']
        exported_dashboards = json.loads(archive.read('workspaces/Default/dashboards/dashboards.json'))
        assert exported_dashboards['dashboards']['exported-dashboard']['name'] == 'Exported Dashboard'
        exported_mappings = json.loads(archive.read('workspaces/Default/operator-mappings/operator-mappings.json'))
        assert exported_mappings['version'] == 2
        assert exported_mappings['mappings'][0]['canonical'] == 'VF'
        assert exported_mappings['mappings'][0]['color'] == '#E15759'
        assert exported_mappings['vendor_mappings'][0]['canonical'] == 'Ericsson'
        assert exported_mappings['vendor_mappings'][0]['color'] == '#2E8B57'
        assert 'config/workspace-registry.db' not in archive.namelist()
    full_import_response = client.post(
        '/admin/import-export/import',
        data={'confirmed_import': 'true'},
        files={'package': ('full-environment.zip', BytesIO(full_response.content), 'application/zip')},
        follow_redirects=False,
    )
    assert full_import_response.status_code == 303
    assert len(app_module.workspace_registry.list()) == 1


def test_multi_selection_export_applies_containment_rules_and_builds_importable_bundle(client, tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    assert app_module.normalize_export_targets([
        'config', 'dashboards', 'workspace:default', 'auto-calculated-fields',
    ]) == ['config', 'workspace:default']
    assert app_module.normalize_export_targets([
        'config', 'workspace:default', 'full-environment',
    ]) == ['full-environment']

    package_path = tmp_path / 'selection.zip'
    filename = app_module.build_export_archive_file(
        ['config', 'workspace:default'], package_path, include_generated_outputs=False,
    )
    assert filename.startswith('dashboard-analytic-selection_')
    with zipfile.ZipFile(package_path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['kind'] == 'bundle'
        assert manifest['targets'] == ['config', 'workspace:default']
        assert [entry['kind'] for entry in manifest['packages']] == ['config', 'workspace']
        assert all(entry['archive_path'] in archive.namelist() for entry in manifest['packages'])

    inspection = client.post(
        '/admin/import-export/inspect',
        files={'package': ('selection.zip', package_path.read_bytes(), 'application/zip')},
    )
    assert inspection.status_code == 200
    assert inspection.json()['kind'] == 'bundle'
    assert inspection.json()['workspace_collisions'] == ['Default']

    imported = client.post(
        '/admin/import-export/import/jobs',
        data={
            'upload_id': inspection.headers['X-Import-Upload-Id'],
            'confirmed_import': 'true',
        },
    )
    assert imported.status_code == 200
    for _attempt in range(200):
        import_status = client.get(imported.json()['status_url']).json()
        if import_status['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert import_status['status'] == 'ready'
    assert import_status['notice'] == 'Import selection completed (2 packages).'


def test_auto_calculated_fields_export_does_not_materialize_active_cdrs(client, tmp_path, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)

    def unexpected_materialization() -> None:
        raise AssertionError('Export must not load or materialize CDR tables.')

    monkeypatch.setattr(app_module, 'load_workspace_calculated_dimensions', unexpected_materialization)
    package_path = tmp_path / 'auto-calculated-fields.zip'
    app_module.build_export_archive_file('auto-calculated-fields', package_path)

    with zipfile.ZipFile(package_path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['kind'] == 'auto-calculated-fields'
        assert json.loads(archive.read(manifest['archive_path']))


def test_operator_mappings_export_and_import_replace_the_selected_workspace_groups(client) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    app_module.repository.replace_operator_mapping_group(None, 'Portable Carrier', ['Portable Alias'])
    app_module.repository.replace_vendor_mapping_group(None, 'Portable Vendor', ['PV'], '#123456')

    exported = client.get('/admin/import-export/export?export_target=operator-mappings')

    assert exported.status_code == 200
    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        payload = json.loads(archive.read(manifest['archive_path']))
    assert manifest['kind'] == 'operator-mappings'
    assert manifest['workspace_components'] == ['operator_mappings']
    assert payload['format'] == 'dashboard-analytic-operator-mappings'
    assert payload['version'] == 2
    assert any(group['canonical'] == 'Portable Carrier' for group in payload['mappings'])
    assert any(
        group['canonical'] == 'Portable Vendor' and group['color'] == '#123456'
        for group in payload['vendor_mappings']
    )

    app_module.repository.delete_operator_mapping_group('Portable Carrier')
    app_module.repository.delete_vendor_mapping_group('Portable Vendor')
    inspected = client.post(
        '/admin/import-export/inspect',
        files={'package': ('operator-mappings.zip', BytesIO(exported.content), 'application/zip')},
    )
    assert inspected.status_code == 200
    assert inspected.json()['kind'] == 'operator-mappings'
    assert inspected.json()['destination_workspaces'] == [{'id': 'default', 'name': 'Default'}]
    started = client.post('/admin/import-export/import/jobs', data={
        'upload_id': inspected.headers['X-Import-Upload-Id'],
        'confirmed_import': 'true',
        'workspace_ids': 'default',
    })
    assert started.status_code == 200
    for _attempt in range(100):
        status_payload = client.get(started.json()['status_url']).json()
        if status_payload['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert status_payload['status'] == 'ready'
    assert app_module.repository.list_operator_mappings()['portable alias'] == 'Portable Carrier'
    assert app_module.repository.list_vendor_mappings()['pv'] == 'Portable Vendor'


def test_full_environment_import_remaps_permissions_to_replaced_workspace_id(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    source_workspace = app_module.workspace_registry.create('Imported Team')
    app_module.repository.set_workspace_user_access(source_workspace.id, ['admin', 'demo'])
    app_module.activate_workspace(source_workspace.id)
    exported = client.get('/admin/import-export/export?export_target=full-environment')
    assert exported.status_code == 200
    package_path = tmp_path / 'full-environment.zip'
    package_path.write_bytes(exported.content)
    manifest = app_module.read_import_manifest(package_path)

    app_module.close_active_workspace()
    app_module.workspace_registry.remove(source_workspace.id)
    app_module.repository.remove_workspace_access(source_workspace.id)
    occupying_workspace = app_module.workspace_registry.create('Local Only')
    replacement = app_module.workspace_registry.create('Imported Team')
    assert occupying_workspace.id == source_workspace.id
    assert replacement.id != source_workspace.id
    app_module.activate_workspace(replacement.id)

    app_module._apply_import_archive(package_path, manifest)

    replaced = next(workspace for workspace in app_module.workspace_registry.list() if workspace.name == 'Imported Team')
    assert replaced.id == replacement.id
    assert app_module.active_workspace is None
    assert app_module.repository.user_has_workspace_access('admin', replaced.id)
    assert app_module.repository.user_has_workspace_access('demo', replaced.id)
    assert not app_module.repository.user_has_workspace_access('admin', source_workspace.id)


def test_config_import_replaces_global_users_and_preserves_user_ids(client) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    created = client.post(
        '/admin/users',
        data={'username': 'exported-user', 'password': 'exported123', 'role': 'user'},
        follow_redirects=False,
    )
    assert created.status_code == 303
    expected_users = [
        (int(row['id']), row['username'], row['role'], bool(row['active']))
        for row in app_module.repository.list_users()
    ]

    exported = client.get('/admin/import-export/export?export_target=config')
    assert exported.status_code == 200
    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
        assert 'config/application.db' in archive.namelist()

    exported_user = next(row for row in app_module.repository.list_users() if row['username'] == 'exported-user')
    changed_password = client.post(
        f"/admin/users/{exported_user['id']}/update",
        data={'username': 'exported-user', 'password': 'local-change123', 'role': 'user', 'active': '1'},
        follow_redirects=False,
    )
    assert changed_password.status_code == 303

    local_only = client.post(
        '/admin/users',
        data={'username': 'local-only-user', 'password': 'local123', 'role': 'user'},
        follow_redirects=False,
    )
    assert local_only.status_code == 303
    assert app_module.repository.get_user('local-only-user') is not None

    # Simulate a different deployment whose application database contains
    # conflicting records.  Importing configuration must replace it exactly,
    # including user IDs and roles, rather than merge it with the source.
    with app_module.repository.global_connection() as conn:
        conn.execute("UPDATE users SET username = 'destination-user', role = 'admin' WHERE username = 'exported-user'")

    imported = client.post(
        '/admin/import-export/import',
        data={'confirmed_import': 'true'},
        files={'package': ('configuration.zip', BytesIO(exported.content), 'application/zip')},
        follow_redirects=False,
    )
    assert imported.status_code == 303
    assert app_module.repository.get_user('local-only-user') is None
    assert app_module.repository.get_user('destination-user') is None
    restored_user = app_module.repository.get_user('exported-user')
    assert restored_user is not None
    assert app_module.verify_password('exported123', restored_user.password_hash)
    assert [
        (int(row['id']), row['username'], row['role'], bool(row['active']))
        for row in app_module.repository.list_users()
    ] == expected_users


def test_admin_export_job_creates_a_disk_backed_download(client) -> None:
    login_super(client)
    started = client.post('/admin/import-export/export/jobs', data={'export_target': 'config'})
    assert started.status_code == 200
    status_url = started.json()['status_url']
    payload = {}
    for _ in range(100):
        status_response = client.get(status_url)
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert payload['status'] == 'ready'
    assert payload['size'] > 0
    assert payload['progress'] == 100
    assert payload['bytes_total'] > 0
    download = client.get(payload['download_url'])
    assert download.status_code == 200
    with zipfile.ZipFile(BytesIO(download.content)) as archive:
        assert json.loads(archive.read('manifest.json'))['kind'] == 'config'


def test_export_scheduler_tasks_use_the_dedicated_background_task_panel(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    job_id = 'export-panel-test'
    with app_module.EXPORT_JOBS_LOCK:
        app_module.EXPORT_JOBS[job_id] = {
            'id': job_id, 'owner': 'admin', 'target': 'config', 'status': 'queued',
            'created_at': datetime.now(timezone.utc).timestamp(), 'workspace_ids': None,
        }
    try:
        groups = client.get('/api/background-tasks').json()['groups']
        export_group = next(group for group in groups if group['workspace_id'] == '__export__')
        assert export_group['workspace_name'] == 'Export tasks'
        assert export_group['dock'] == 'export'
        assert export_group['tasks'][0]['id'] == f'export:{job_id}'
    finally:
        with app_module.EXPORT_JOBS_LOCK:
            app_module.EXPORT_JOBS.pop(job_id, None)


def test_full_environment_export_job_uses_selected_workspaces(client) -> None:
    login_super(client)
    started = client.post(
        '/admin/import-export/export/jobs',
        data={'export_target': 'full-environment', 'workspace_ids': ['default']},
    )
    assert started.status_code == 200
    payload = {}
    for _ in range(100):
        payload = client.get(started.json()['status_url']).json()
        if payload['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert payload['status'] == 'ready'
    with zipfile.ZipFile(BytesIO(client.get(payload['download_url']).content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    assert [workspace['name'] for workspace in manifest['workspaces']] == ['Default']


def test_workspace_export_can_exclude_generated_dashboards_reports_and_chart_sets(client, tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    report = app_module.settings.output_dir / 'reports' / 'generated.pptx'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b'report')
    chart = app_module.settings.output_dir / 'charts' / '20260907-120000' / 'chart-1.png'
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_bytes(b'chart')
    dashboard = app_module.settings.output_dir / 'dashboards' / '20260907_120000 - Dashboard' / 'dashboard.pptx'
    dashboard.parent.mkdir(parents=True, exist_ok=True)
    dashboard.write_bytes(b'dashboard')

    included_archive = tmp_path / 'included.zip'
    app_module.build_export_archive_file('workspace:default', included_archive, include_generated_outputs=True)
    with zipfile.ZipFile(included_archive) as archive:
        assert json.loads(archive.read('manifest.json'))['includes_generated_outputs'] is True
        assert 'workspaces/Default/output/reports/generated.pptx' in archive.namelist()
        assert 'workspaces/Default/output/charts/20260907-120000/chart-1.png' in archive.namelist()
        assert 'workspaces/Default/output/dashboards/20260907_120000 - Dashboard/dashboard.pptx' in archive.namelist()

    excluded_archive = tmp_path / 'excluded.zip'
    app_module.build_export_archive_file('workspace:default', excluded_archive, include_generated_outputs=False)
    with zipfile.ZipFile(excluded_archive) as archive:
        assert json.loads(archive.read('manifest.json'))['includes_generated_outputs'] is False
    assert not any(name.startswith('workspaces/Default/output/') for name in archive.namelist())


def test_full_environment_selector_offers_generated_outputs_by_default(client) -> None:
    login_super(client)

    response = client.get('/admin')

    assert response.status_code == 200
    assert 'data-full-environment-generated-outputs' in response.text
    assert 'Include generated dashboards, reports and chart sets' in response.text
    workspace_page = client.get('/workspace')
    assert 'Also duplicate generated dashboards, reports and chart sets.' in workspace_page.text
    app_script = (Path(__file__).parents[1] / 'src/web_interface/static/js/app.js').read_text(encoding='utf-8')
    assert "String(group.workspace_id) !== '__server__' && group.dock !== 'export' && (Boolean(group.is_active) || group.dock === 'right')" in app_script
    assert 'activeDock.replaceChildren(...activeGroups.map(refreshPanel), ...exportGroups.map(refreshPanel));' in app_script
    assert "exportTarget?.addEventListener('change'" not in app_script
    assert 'selectedFullEnvironment' not in app_script
    assert app_script.count('const selection = await selectFullEnvironmentWorkspaces();') == 2


def test_voice_and_speech_import_without_measured_kpis_remain_ready(client) -> None:
    login(client)

    for filename, kind, content in (
        ('voice.csv', 'voice', b'Operator,Call_Status\nOrange,Completed\n'),
        ('speech.csv', 'speech', b'Operator,Test_Result\nOrange,Completed\n'),
    ):
        response = client.post(
            '/datasets-analysis/upload', data={'dataset_kinds': kind},
            files={'dataset_files': (filename, BytesIO(content), 'text/csv')},
        )
        assert response.status_code == 200

    import src.DashboardAnalytic as app_module
    datasets = app_module.repository.list_datasets()
    assert [dataset['status'] for dataset in datasets] == ['ready', 'ready']
    assert all('attempt_count' in json.loads(dataset['available_metrics_json']) for dataset in datasets)


def test_admin_import_job_reuses_the_inspected_disk_upload(client) -> None:
    login_super(client)
    exported = client.get('/admin/import-export/export?export_target=config')
    inspected = client.post(
        '/admin/import-export/inspect',
        files={'package': ('configuration.zip', BytesIO(exported.content), 'application/zip')},
    )
    upload_id = inspected.headers['x-import-upload-id']
    started = client.post(
        '/admin/import-export/import/jobs',
        data={'upload_id': upload_id, 'confirmed_import': 'true'},
    )
    assert started.status_code == 200
    payload = {}
    for _ in range(100):
        payload = client.get(started.json()['status_url']).json()
        if payload['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert payload['status'] == 'ready'
    assert 'Configuration imported successfully' in payload['notice']


def test_admin_import_stream_upload_avoids_multipart_staging(client) -> None:
    login_super(client)
    exported = client.get('/admin/import-export/export?export_target=config')
    inspected = client.post(
        '/admin/import-export/inspect/upload',
        content=exported.content,
        headers={'Content-Type': 'application/zip'},
    )
    assert inspected.status_code == 200
    assert inspected.headers['x-import-upload-id']
    assert inspected.json()['kind'] == 'config'


def test_recover_complete_transfer_packages_and_remove_incomplete_ones(client, monkeypatch, tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    package, _ = app_module.build_export_archive('config')
    complete_path = tmp_path / 'incoming-transfer-complete.upload'
    incomplete_path = tmp_path / 'incoming-transfer-incomplete.upload'
    outgoing_path = tmp_path / 'transfer-interrupted.zip'
    complete_path.write_bytes(package)
    incomplete_path.write_bytes(b'partial transfer')
    outgoing_path.write_bytes(b'partial outgoing transfer')
    monkeypatch.setattr(app_module, 'export_package_dir', lambda: tmp_path)
    existing_offer_ids = set(app_module.TRANSFER_OFFERS)
    try:
        app_module._recover_unimported_transfer_packages()
        assert not incomplete_path.exists()
        assert not outgoing_path.exists()
        recovered = [offer for offer_id, offer in app_module.TRANSFER_OFFERS.items() if offer_id not in existing_offer_ids]
        assert len(recovered) == 1
        assert recovered[0]['status'] == 'recovered'
        assert recovered[0]['content'] == 'Config'
        assert recovered[0]['workspaces'] == []
        login_super(client)
        listed = client.get('/admin/import-export/transfers/recoveries')
        assert listed.status_code == 200
        assert recovered[0]['id'] in [offer['id'] for offer in listed.json()['offers']]
        assert len(listed.json()['offers'][0]['created_at']) == 16
        assert listed.json()['offers'][0]['created_at'][4] == '-'
        admin_panel = client.get('/admin')
        assert 'Recovered transfer packages' in admin_panel.text
        assert '<th>Workspaces</th>' in admin_panel.text
        deleted = client.post(f'/admin/import-export/transfers/recoveries/{recovered[0]["id"]}/delete')
        assert deleted.status_code == 200
        assert not complete_path.exists()
    finally:
        for offer_id in set(app_module.TRANSFER_OFFERS) - existing_offer_ids:
            app_module.TRANSFER_OFFERS.pop(offer_id, None)


def test_auto_calculated_field_transfer_requires_destination_workspaces(client) -> None:
    secret = 'auto-field-transfer-secret-that-is-long-enough'
    headers = {'X-Dashboard-Transfer-Secret': secret}
    offered = client.post(
        '/api/import-export/transfers/offers',
        headers=headers,
        json={
            'source': 'Test source', 'archive_version': 1, 'kind': 'auto-calculated-fields',
            'content': 'Auto-calculated Fields', 'workspaces': ['Source'],
        },
    )
    assert offered.status_code == 200
    offer_id = offered.json()['offer_id']
    login_super(client)
    assert client.post(f'/admin/import-export/transfers/offers/{offer_id}/accept', json={}).status_code == 400
    accepted = client.post(
        f'/admin/import-export/transfers/offers/{offer_id}/accept',
        json={'workspace_ids': ['default']},
    )
    assert accepted.status_code == 200
    cancelled = client.delete(f'/api/import-export/transfers/offers/{offer_id}', headers=headers)
    assert cancelled.status_code == 200


def test_incoming_server_transfer_requires_acceptance_and_imports_after_upload(client) -> None:
    secret = 'server-transfer-test-secret-that-is-long-enough'
    headers = {'X-Dashboard-Transfer-Secret': secret}
    offer = client.post(
        '/api/import-export/transfers/offers',
        headers=headers,
        json={'source': 'Test source', 'archive_version': 1, 'kind': 'config', 'content': 'config', 'workspaces': []},
    )
    assert offer.status_code == 200
    offer_id = offer.json()['offer_id']
    repeated_offer = client.post(
        '/api/import-export/transfers/offers',
        headers=headers,
        json={'source': 'Test source', 'archive_version': 1, 'kind': 'config', 'content': 'config', 'workspaces': []},
    )
    assert repeated_offer.status_code == 200
    assert repeated_offer.json()['offer_id'] == offer_id

    login_super(client)
    exported = client.get('/admin/import-export/export?export_target=config')
    blocked_upload = client.put(
        f'/api/import-export/transfers/offers/{offer_id}/package',
        headers={**headers, 'Content-Type': 'application/zip'},
        content=exported.content,
    )
    assert blocked_upload.status_code == 409

    pending = client.get('/admin/import-export/transfers/offers')
    assert [item['id'] for item in pending.json()['offers']] == [offer_id]
    accepted = client.post(f'/admin/import-export/transfers/offers/{offer_id}/accept')
    assert accepted.status_code == 200
    destination_progress = client.get(f'/admin/import-export/transfers/offers/{offer_id}')
    assert destination_progress.status_code == 200
    assert destination_progress.json()['status'] == 'accepted'
    assert destination_progress.json()['progress'] == 0.0
    repeated_accept = client.post(f'/admin/import-export/transfers/offers/{offer_id}/accept')
    assert repeated_accept.status_code == 200
    assert client.get('/workspace').text.count('data-server-transfer-listener') == 1

    uploaded = client.put(
        f'/api/import-export/transfers/offers/{offer_id}/package',
        headers={**headers, 'Content-Type': 'application/zip'},
        content=exported.content,
    )
    assert uploaded.status_code == 200
    payload = {}
    for _ in range(100):
        payload = client.get(f'/api/import-export/transfers/offers/{offer_id}', headers=headers).json()
        if payload['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert payload['status'] == 'ready'
    assert 'Configuration imported successfully' in payload['notice']


def test_server_transfer_listener_keeps_a_persistent_pending_offer_reminder() -> None:
    script = (Path(__file__).parents[1] / 'src' / 'web_interface' / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')

    assert "pendingOfferReminder.className = 'incoming-transfer-reminder'" in script
    assert 'window.addEventListener(\'online\', () => scheduleIncomingOfferPoll(0));' in script
    assert 'document.addEventListener(\'visibilitychange\', () => { if (!document.hidden) scheduleIncomingOfferPoll(0); });' in script
    assert 'window.setInterval(pollIncomingTransferOffers, 3000);' not in script


def test_incoming_transfer_offer_survives_process_memory_loss(client, monkeypatch, tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(app_module, 'export_package_dir', lambda: tmp_path)
    secret = 'persistent-transfer-test-secret-long-enough'
    offer = client.post(
        '/api/import-export/transfers/offers',
        headers={'X-Dashboard-Transfer-Secret': secret},
        json={
            'source': 'Docker source', 'archive_version': 1,
            'kind': 'slides-templates', 'content': 'Slides Templates', 'workspaces': [],
        },
    )
    assert offer.status_code == 200
    offer_id = offer.json()['offer_id']
    app_module.TRANSFER_OFFERS.pop(offer_id)

    login_super(client)
    pending = client.get('/admin/import-export/transfers/offers')
    assert pending.status_code == 200
    assert [item['id'] for item in pending.json()['offers']] == [offer_id]
    app_module.TRANSFER_OFFERS.pop(offer_id, None)


def test_equivalent_pending_transfer_offer_is_reused_with_the_new_secret(client, monkeypatch, tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(app_module, 'export_package_dir', lambda: tmp_path)
    payload = {
        'source': 'Retrying Docker source', 'archive_version': 1,
        'kind': 'slides-templates', 'content': 'Slides Templates', 'workspaces': [],
    }
    first_secret = 'first-retry-transfer-secret-long-enough'
    second_secret = 'second-retry-transfer-secret-long-enough'
    first = client.post(
        '/api/import-export/transfers/offers',
        headers={'X-Dashboard-Transfer-Secret': first_secret},
        json=payload,
    )
    second = client.post(
        '/api/import-export/transfers/offers',
        headers={'X-Dashboard-Transfer-Secret': second_secret},
        json=payload,
    )
    offer_id = first.json()['offer_id']
    try:
        assert second.status_code == 200
        assert second.json()['offer_id'] == offer_id
        assert second.json()['reused'] is True
        assert client.get(
            f'/api/import-export/transfers/offers/{offer_id}',
            headers={'X-Dashboard-Transfer-Secret': first_secret},
        ).status_code == 404
        assert client.get(
            f'/api/import-export/transfers/offers/{offer_id}',
            headers={'X-Dashboard-Transfer-Secret': second_secret},
        ).status_code == 200
    finally:
        app_module.TRANSFER_OFFERS.pop(offer_id, None)


def test_new_transfer_offer_supersedes_old_pending_requests_from_same_server(client, monkeypatch, tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(app_module, 'export_package_dir', lambda: tmp_path)
    offer_ids = []
    try:
        for index in range(7):
            response = client.post(
                '/api/import-export/transfers/offers',
                headers={'X-Dashboard-Transfer-Secret': f'superseding-transfer-secret-{index:02d}-long-enough'},
                json={
                    'source': f'Persistent Docker source {index}', 'archive_version': 1,
                    'kind': 'slides-templates', 'content': f'Slides Templates {index}', 'workspaces': [],
                },
            )
            assert response.status_code == 200
            offer_ids.append(response.json()['offer_id'])
        assert app_module.TRANSFER_OFFERS[offer_ids[-1]]['status'] == 'pending'
        assert all(app_module.TRANSFER_OFFERS[offer_id]['status'] == 'cancelled' for offer_id in offer_ids[:-1])
    finally:
        for offer_id in offer_ids:
            app_module.TRANSFER_OFFERS.pop(offer_id, None)


def test_persisted_pending_transfer_offer_expires_after_approval_window(client, monkeypatch, tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(app_module, 'export_package_dir', lambda: tmp_path)
    secret = 'expiring-transfer-offer-secret-long-enough'
    response = client.post(
        '/api/import-export/transfers/offers',
        headers={'X-Dashboard-Transfer-Secret': secret},
        json={
            'source': 'Expiring source', 'archive_version': 1,
            'kind': 'slides-templates', 'content': 'Slides Templates', 'workspaces': [],
        },
    )
    offer_id = response.json()['offer_id']
    offer = app_module.TRANSFER_OFFERS[offer_id]
    offer['created_at'] = time.time() - app_module.TRANSFER_OFFER_TTL.total_seconds() - 1
    app_module._save_transfer_offer(offer)
    app_module.TRANSFER_OFFERS.pop(offer_id)
    try:
        app_module._cleanup_expired_export_packages()
        assert app_module.TRANSFER_OFFERS[offer_id]['status'] == 'expired'
        persisted = next(
            offer for offer in app_module.repository.list_transfer_offers()
            if offer['id'] == offer_id
        )
        assert persisted['status'] == 'expired'
    finally:
        app_module.TRANSFER_OFFERS.pop(offer_id, None)


def test_outgoing_server_transfer_waits_for_acceptance_and_streams_package(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    state = {'uploaded': False, 'bytes': 0, 'post_attempts': 0, 'client_kwargs': {}}

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            state['client_kwargs'] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, *args, **kwargs):
            state['post_attempts'] += 1
            if state['post_attempts'] == 1:
                raise app_module.httpx.ConnectError('temporary first-contact failure')
            return FakeResponse({'offer_id': 'remote-offer'})

        def get(self, *args, **kwargs):
            return FakeResponse({'status': 'ready', 'notice': 'Imported remotely.'} if state['uploaded'] else {'status': 'accepted'})

        def put(self, *args, **kwargs):
            for chunk in kwargs['content']:
                state['bytes'] += len(chunk)
            state['uploaded'] = True
            return FakeResponse({'status': 'received'})

    def fake_export(target, destination, workspace_ids=None, progress_callback=None, include_generated_outputs=True):
        destination.write_bytes(b'streamed-transfer-package')
        if progress_callback:
            progress_callback(len(b'streamed-transfer-package'))
        return 'transfer.zip'

    monkeypatch.setattr(app_module.httpx, 'Client', FakeClient)
    monkeypatch.setattr(app_module, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(app_module, 'build_export_archive_file', fake_export)
    user = app_module.SessionUser(username='super', role='super-admin')
    job = app_module.start_transfer_job('http://destination.example', 8080, 'config', None, user)
    payload = {}
    for _ in range(100):
        payload = app_module.transfer_job_payload(job['id'], user)
        if payload['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert payload['status'] == 'ready'
    assert payload['destination'] == 'http://destination.example:8080'
    assert payload['progress'] == 100.0
    assert state['post_attempts'] == 2
    assert state['bytes'] == len(b'streamed-transfer-package')
    assert state['client_kwargs']['trust_env'] is True


def test_transfer_owner_can_request_job_cancellation(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    job_id = 'cancel-transfer-test'
    app_module.TRANSFER_JOBS[job_id] = {'id': job_id, 'owner': 'admin', 'status': 'connecting', 'path': '/tmp/unused-transfer.zip'}
    try:
        response = client.post(f'/admin/import-export/transfers/jobs/{job_id}/cancel')
        assert response.status_code == 200
        assert response.json()['status'] == 'cancelling'
        assert app_module.TRANSFER_JOBS[job_id]['cancel_requested'] is True
    finally:
        app_module.TRANSFER_JOBS.pop(job_id, None)


def test_transfer_url_explicit_port_overrides_prefilled_default_port() -> None:
    import src.DashboardAnalytic as app_module

    assert app_module.normalize_transfer_destination('https://destination.example:8443', 7278) == 'https://destination.example:8443'
    assert app_module.normalize_transfer_destination('destination.example', 7278) == 'http://destination.example:7278'
    assert app_module.normalize_transfer_destination('https://destination.example', 7278) == 'https://destination.example'
    assert app_module.normalize_transfer_destination('http://destination.example', 7278) == 'http://destination.example'
    assert app_module.normalize_transfer_destination('https://destination.example', 8443) == 'https://destination.example:8443'


def test_private_transfer_addresses_bypass_environment_proxies() -> None:
    import src.DashboardAnalytic as app_module

    assert app_module.transfer_uses_environment_proxy('http://192.168.1.17:7278') is False
    assert app_module.transfer_uses_environment_proxy('http://127.0.0.1:7278') is False
    assert app_module.transfer_uses_environment_proxy('http://169.254.10.20:7278') is False
    assert app_module.transfer_uses_environment_proxy('https://destination.example') is True
    assert app_module.transfer_uses_environment_proxy('https://8.8.8.8') is True


def test_private_transfer_connection_error_has_docker_lan_diagnostics() -> None:
    import src.DashboardAnalytic as app_module

    message = app_module.transfer_connection_error('http://192.168.1.17:7278')
    assert 'contacted directly without using Docker or system proxy settings' in message
    assert 'listening on 0.0.0.0' in message
    assert 'host.docker.internal' in message


def test_admin_export_and_transfer_are_limited_to_templates_and_accessible_workspaces(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    restricted = app_module.workspace_registry.create('Restricted Team')
    login(client)

    panel = client.get('/admin')
    assert panel.status_code == 200
    assert 'data-panel-state-key="admin:import-export"' in panel.text
    assert 'Report Templates (from active workspace)</option>' in panel.text
    assert 'Transfer to other server' in panel.text
    assert 'value="config"' not in panel.text
    assert 'value="workspace:default"' in panel.text
    assert 'Workspace: Default</option>' in panel.text
    assert f'value="workspace:{restricted.id}"' not in panel.text

    blocked_export = client.get('/admin/import-export/export?export_target=config')
    assert blocked_export.status_code == 403

    templates_export = client.get('/admin/import-export/export?export_target=slides-templates')
    assert templates_export.status_code == 200
    with zipfile.ZipFile(BytesIO(templates_export.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['kind'] == 'slides-templates'
        assert manifest['archive_path'].endswith('/report-templates')

    workspace_export = client.get('/admin/import-export/export?export_target=workspace:default')
    assert workspace_export.status_code == 200
    assert client.get(f'/admin/import-export/export?export_target=workspace:{restricted.id}').status_code == 403

    monkeypatch.setattr(app_module, 'start_transfer_job', lambda *args, **kwargs: {'id': 'admin-transfer', 'status': 'queued'})
    transfer = client.post('/admin/import-export/transfers/jobs', data={
        'destination_url': 'destination.example', 'destination_port': '7278',
        'export_target': 'workspace:default',
    })
    assert transfer.status_code == 200
    blocked_transfer = client.post('/admin/import-export/transfers/jobs', data={
        'destination_url': 'destination.example', 'destination_port': '7278',
        'export_target': 'config',
    })
    assert blocked_transfer.status_code == 403

    config_package = BytesIO()
    with zipfile.ZipFile(config_package, 'w') as archive:
        archive.writestr('manifest.json', json.dumps({
            'format': 'dashboard-analytic-export', 'version': 1, 'kind': 'config',
        }))
    config_package.seek(0)
    blocked_import = client.post(
        '/admin/import-export/inspect',
        files={'package': ('config.zip', config_package, 'application/zip')},
    )
    assert blocked_import.status_code == 403

    blocked_workspace_import = client.post(
        '/admin/import-export/inspect',
        files={'package': ('workspace.zip', BytesIO(workspace_export.content), 'application/zip')},
    )
    assert blocked_workspace_import.status_code == 403


def test_admin_can_login_upload_and_see_automatic_dashboard(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\nDE,2026-Q2,76,5.2\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    dashboard_response = client.get(upload_response.headers["location"])
    assert dashboard_response.status_code == 200
    assert "sample.csv" in dashboard_response.text
    assert "Data Ingestion" in dashboard_response.text
    assert "Workspace" in dashboard_response.text
    assert "Workspace opened from cache" in dashboard_response.text

    analysis_redirect = client.post(
        "/datasets-analysis/analyze",
        data={
            "dataset_id": 1,
            "metric": "score",
            "market": "ES",
            "period": "2026-Q1",
            "aggregation": "all",
        },
        follow_redirects=False,
    )
    assert analysis_redirect.status_code == 303
    filtered_dashboard = client.get(analysis_redirect.headers["location"])
    assert filtered_dashboard.status_code == 200
    assert "Processed Metrics" in filtered_dashboard.text
    assert "CDF Curve" in filtered_dashboard.text
    assert "89" in filtered_dashboard.text


def test_dashboard_disables_metrics_without_non_null_values(client) -> None:
    login(client)
    csv_content = (
        b"market,period,operator,region,latency_ms,score\n"
        b"ES,2026-Q1,Vodafone,North,,91\n"
        b"ES,2026-Q1,Orange,South,,87\n"
    )
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200
    assert 'value="score"' in response.text
    assert 'value="latency_ms" disabled' in response.text


def test_datasets_analysis_excludes_timestamp_columns_from_metrics(client) -> None:
    login(client)
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(
            b"market,operator,score,Call_Start_Time\nES,3,91,2026-07-10 10:00:00\n"
        ), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get(
        "/datasets-analysis?dataset_id=1&metric=score&metric=Call_Start_Time&aggregation=all&load=1"
    )
    assert response.status_code == 200
    assert 'value="Call_Start_Time"' not in response.text
    assert 'value="operator"  disabled' in response.text
    assert 'value="score"' in response.text
    assert "data-table-wrap" in response.text
    assert "Global Aggregation" in response.text


def test_admin_can_retry_stuck_dataset(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(1, status="failed", progress=100, dataset_kind=None, row_count=None, column_count=None, default_metric=None)
    retry_response = client.post("/datasets-analysis/retry/1", follow_redirects=False)
    assert retry_response.status_code == 303

    dashboard_response = client.get(retry_response.headers["location"])
    assert dashboard_response.status_code == 200
    assert "Workspace opened from cache" in dashboard_response.text


def test_ready_dataset_can_be_reprocessed_and_return_to_admin(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("ready.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.post(
        "/datasets-analysis/retry/1",
        data={"return_to": "admin"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_chart_builder_uses_dashboard_canvas_model(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.replace_operator_mapping_group(None, 'VF', ['Vodafone'])
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("chart.csv", BytesIO(
            b"operator,Vendor,score\nVodafone,Vodafone_Ericsson,91\nEE,EE_Huawei,87\n"
        ), "text/csv")},
        follow_redirects=False,
    )

    page = client.get('/chart-builder')
    assert page.status_code == 200
    assert 'data-chart-builder-chart' in page.text
    assert 'js/dashboard_charts.js' in page.text

    response = client.post('/api/chart-builder/preview', json={
        'dataset_ids': [1],
        'definition': {
            'chart_title': 'Operator score',
            'chart_type': 'Average Vertical Bars',
            'cdr_source': 'CDR-Data',
            'kpi': 'score',
            'grouping_rows': 'Vendor',
            'grouping_columns': '',
            'legend': '',
            'legend_position': 'Top',
        },
    })

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    payload = response.json()
    assert payload['width'] == 1600
    assert payload['height'] == 900
    assert payload['title'] == 'Operator score'
    assert 'VF_Ericsson' in json.dumps(payload)
    assert 'Vodafone_Ericsson' not in json.dumps(payload)


def test_workspace_bulk_dataset_actions_reprocess_in_dependency_order(client, monkeypatch) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "mapping_three"},
        files={"dataset_files": ("mapping.csv", BytesIO(b"Cid__ECI,Vendor\n200,Nokia\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "mapping_vodafone"},
        files={"dataset_files": ("vf-mapping.csv", BytesIO(b"Cell_ID_A,Vendor\n100,Ericsson\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("cdr.csv", BytesIO(b"operator,Cell_ID_A,score\n3,200 -> 200,91\n"), "text/csv")},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(
        3,
        processing_options_json=json.dumps({"three_mapping_dataset_id": 1}),
    )
    page = client.get('/workspace')
    assert page.status_code == 200
    toolbar = page.text.split('<div class="queue-bulk-actions"', 1)[1].split('</div>', 1)[0]
    assert toolbar.index('>Map Vendor & Region<') < toolbar.index('>Clear Vendor & Region Mapping<') < toolbar.index('>Reprocess All<') < toolbar.index('>Stop All<') < toolbar.index('>Remove All<')
    assert 'data-dataset-reprocess-dialog' in page.text
    assert 'name="dataset_ids" value="1" data-reprocess-dataset-choice checked' in page.text
    assert 'name="dataset_ids" value="2" data-reprocess-dataset-choice checked' in page.text
    assert 'name="dataset_ids" value="3" data-reprocess-dataset-choice checked' in page.text

    calls = []

    def capture_enqueue(
        _background_tasks, dataset_id, dataset_path, _username,
        vodafone_mapping_dataset_id=None, three_mapping_dataset_id=None,
        region_mapping_dataset_id=None,
        *, dependencies=(), **_kwargs,
    ):
        token = object()
        calls.append({
            'dataset_id': dataset_id,
            'path': dataset_path,
            'vodafone_mapping_dataset_id': vodafone_mapping_dataset_id,
            'three_mapping_dataset_id': three_mapping_dataset_id,
            'region_mapping_dataset_id': region_mapping_dataset_id,
            'dependencies': list(dependencies),
            'token': token,
        })
        return token

    monkeypatch.setattr(app_module, 'enqueue_dataset_processing', capture_enqueue)
    response = client.post(
        '/workspace/reprocess-datasets',
        data={'dataset_ids': ['3', '1', '2']},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert [call['dataset_id'] for call in calls] == [1, 2, 3]
    assert calls[2]['three_mapping_dataset_id'] == 1
    assert calls[2]['dependencies'] == [calls[0]['token'], calls[1]['token']]


def test_admin_dataset_table_includes_ordered_global_icon_actions(client, monkeypatch) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "mapping_three"},
        files={"dataset_files": ("mapping.csv", BytesIO(b"Cid__ECI,Vendor\n200,Nokia\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("cdr.csv", BytesIO(b"operator,Cell_ID_A,score\n3,200 -> 200,91\n"), "text/csv")},
        follow_redirects=False,
    )
    page = client.get('/admin')

    assert page.status_code == 200
    toolbar = page.text.split('class="queue-bulk-actions admin-dataset-bulk-actions"', 1)[1].split('</div>', 1)[0]
    assert toolbar.index('>Map All<') < toolbar.index('>Clear All<') < toolbar.index('>Reprocess All<') < toolbar.index('>Stop All<') < toolbar.index('>Remove All<')
    assert 'data-admin-vendor-mapping-dialog' in page.text
    assert 'data-admin-vendor-clearing-dialog' in page.text
    assert 'data-admin-dataset-reprocess-dialog' in page.text
    assert 'class="admin-dataset-move admin-dataset-move-up icon-action"' in page.text
    assert 'class="admin-dataset-move admin-dataset-move-down icon-action"' in page.text
    assert page.text.count('name="return_to" value="admin"') >= 5
    styles = client.get('/static/css/app.css')
    assert styles.status_code == 200
    assert '.admin-stack .admin-dataset-bulk-actions .queue-map-all {' in styles.text
    assert '.admin-stack .admin-dataset-bulk-actions .queue-clear-all {' in styles.text
    assert '.admin-stack .admin-dataset-bulk-actions :is(.queue-reprocess-all, .queue-stop-all) {' in styles.text
    assert '.admin-stack .admin-dataset-bulk-actions .queue-remove-all {' in styles.text

    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(app_module, 'enqueue_dataset_processing', lambda *_args, **_kwargs: object())
    response = client.post(
        '/workspace/reprocess-datasets',
        data={'dataset_ids': '1', 'return_to': 'admin'},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers['location'] == '/admin'


def test_admin_dataset_rows_can_be_reordered_in_descending_order_and_all_ids_are_propagated(client, monkeypatch) -> None:
    login(client)
    for name, score in (('first.csv', 91), ('second.csv', 92), ('third.csv', 93)):
        client.post(
            '/datasets-analysis/upload',
            data={'dataset_kinds': 'data'},
            files={'dataset_files': (name, BytesIO(f'market,period,score\nES,2026-Q1,{score}\n'.encode()), 'text/csv')},
            follow_redirects=False,
        )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(
        3,
        processing_options_json=json.dumps({'vodafone_mapping_dataset_id': 1}),
    )
    app_module.repository.set_workspace_state(
        'e2e_dashboards_v2',
        json.dumps({'dashboard': {'datasets': {'data': [3, 1]}}}),
    )
    with app_module.repository.connection() as connection:
        connection.execute(
            """
            INSERT INTO generated_jobs (
                job_type, report_type, technology, scope, data_dataset_id,
                template_name, created_by, dataset_ids_json
            ) VALUES ('report', 'summary', 'nsa', 'single', 3, 'Template', 'admin', ?)
            """,
            (json.dumps({'data': [3, 1]}),),
        )

    first_move = client.post(
        '/admin/datasets/1/move',
        data={'direction': 'up'},
        headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        follow_redirects=False,
    )
    second_move = client.post(
        '/admin/datasets/2/move', data={'direction': 'up'}, follow_redirects=False,
    )

    assert first_move.status_code == 200
    assert first_move.json() == {'ok': True, 'id_mapping': {'1': 2, '2': 1, '3': 3}}
    assert second_move.status_code == 303
    datasets = sorted(app_module.repository.list_datasets(), key=lambda row: int(row['id']))
    assert [(int(row['id']), row['file_name']) for row in datasets] == [
        (1, 'second.csv'), (2, 'third.csv'), (3, 'first.csv'),
    ]
    assert app_module.repository.dataset_rows_table_exists(1)
    assert app_module.repository.dataset_rows_table_exists(2)
    assert app_module.repository.dataset_rows_table_exists(3)
    assert json.loads(app_module.repository.get_dataset(2)['processing_options_json']) == {
        'vodafone_mapping_dataset_id': 3,
    }
    reprocessing_calls = []
    def record_reprocessing(
        _tasks, dataset_id, _path, _username,
        vodafone_mapping_dataset_id, three_mapping_dataset_id, region_mapping_dataset_id,
    ):
        reprocessing_calls.append({
            'dataset_id': dataset_id,
            'vodafone_mapping_dataset_id': vodafone_mapping_dataset_id,
            'three_mapping_dataset_id': three_mapping_dataset_id,
            'region_mapping_dataset_id': region_mapping_dataset_id,
        })
        return object()

    monkeypatch.setattr(app_module, 'enqueue_dataset_processing', record_reprocessing)
    reprocess = client.post(
        '/datasets-analysis/retry/2', data={'return_to': 'admin'}, follow_redirects=False,
    )
    assert reprocess.status_code == 303
    assert reprocessing_calls == [{
        'dataset_id': 2,
        'vodafone_mapping_dataset_id': 3,
        'three_mapping_dataset_id': None,
        'region_mapping_dataset_id': None,
    }]
    dashboard_state = json.loads(app_module.repository.get_workspace_state('e2e_dashboards_v2'))
    assert dashboard_state['dashboard']['datasets']['data'] == [2, 3]
    with app_module.repository.connection() as connection:
        job = connection.execute(
            'SELECT data_dataset_id, dataset_ids_json FROM generated_jobs ORDER BY id DESC LIMIT 1'
        ).fetchone()
        sequence = connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'datasets'"
        ).fetchone()
    assert int(job['data_dataset_id']) == 2
    assert json.loads(job['dataset_ids_json']) == {'data': [2, 3]}
    assert int(sequence['seq']) == 3
    admin_page = client.get('/admin')
    dataset_table = admin_page.text.split('<table class="admin-datasets-table"', 1)[1].split('</table>', 1)[0]
    assert dataset_table.index('data-label="ID">3<') < dataset_table.index('data-label="ID">2<') < dataset_table.index('data-label="ID">1<')
    assert dataset_table.count('data-admin-dataset-move=') == 6
    assert 'data-admin-dataset-apply-changes' in admin_page.text
    assert 'data-admin-dataset-draft-body' in dataset_table
    individual_tables = admin_page.text.split('<optgroup label="Individual Datasets">', 1)[1].split('</optgroup>', 1)[0]
    assert individual_tables.index('value="dataset_rows_3"') < individual_tables.index('value="dataset_rows_2"') < individual_tables.index('value="dataset_rows_1"')
    assert 'Individual dataset rows' not in admin_page.text
    app_script = client.get('/static/js/app.js').text
    assert "currentTable.replaceWith(freshTable)" in app_script
    assert "window.scrollTo({top: scrollTop, left: scrollLeft, behavior: 'auto'})" in app_script


def test_database_management_orders_individual_dataset_tables_by_numeric_id_descending(client) -> None:
    login(client)
    import src.DashboardAnalytic as app_module

    for dataset_number in range(1, 13):
        dataset_id, _ = app_module.repository.add_dataset(
            f'dataset-{dataset_number}.csv',
            str(app_module.settings.input_dir / f'dataset-{dataset_number}.csv'),
            'admin',
        )
        app_module.repository.replace_dataset_rows(dataset_id, pd.DataFrame({'value': [dataset_number]}))

    page = client.get('/admin')
    individual_tables = page.text.split('<optgroup label="Individual Datasets">', 1)[1].split('</optgroup>', 1)[0]
    positions = [individual_tables.index(f'value="dataset_rows_{dataset_id}"') for dataset_id in range(12, 0, -1)]

    assert positions == sorted(positions)
    assert individual_tables.index('value="dataset_rows_12"') < individual_tables.index('value="dataset_rows_9"')
    assert individual_tables.index('value="dataset_rows_10"') < individual_tables.index('value="dataset_rows_2"')


def test_workspace_stop_all_stops_queued_and_processing_datasets(client) -> None:
    login(client)
    for name in ('first.csv', 'second.csv'):
        client.post(
            "/datasets-analysis/upload",
            data={"dataset_kinds": "data"},
            files={"dataset_files": (name, BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
            follow_redirects=False,
        )
    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(1, status='processing', progress=40)
    app_module.repository.update_dataset_profile(2, status='queued', progress=0)
    workspace = client.get('/workspace')
    assert 'title="Stop all queued and processing datasets" aria-label="Stop all queued and processing datasets">Stop All</button>' in workspace.text
    response = client.post('/workspace/stop-datasets', follow_redirects=False)

    assert response.status_code == 303
    assert 'All+2+queued+or+processing+datasets+have+been+stopped.' in response.headers['location']
    assert app_module.repository.get_dataset(1)['status'] == 'stopped'
    assert app_module.repository.get_dataset(2)['status'] == 'stopped'
    assert app_module.repository.get_dataset(1)['last_error'] is None
    assert app_module.repository.get_dataset(2)['last_error'] is None
    stopped_page = client.get(response.headers['location'])
    assert stopped_page.text.count('All 2 queued or processing datasets have been stopped.') == 1
    assert 'Processing stopped by user.' not in stopped_page.text


def test_queued_dataset_can_be_stopped_individually_across_worker_memory(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    dataset_id, _ = app_module.repository.add_dataset(
        'queued-stop.csv', str(app_module.settings.input_dir / 'queued-stop.csv'), 'admin',
    )
    app_module.repository.update_dataset_profile(dataset_id, status='queued', progress=0)
    page = client.get('/workspace')
    assert f'action="/datasets-analysis/stop/{dataset_id}"' in page.text

    response = client.post(f'/datasets-analysis/stop/{dataset_id}', follow_redirects=False)
    assert response.status_code == 303
    assert app_module.repository.get_dataset(dataset_id)['status'] == 'stopped'
    with app_module.STOP_REQUESTS_LOCK:
        app_module.STOP_REQUESTS.clear()
    try:
        assert app_module.stop_requested(dataset_id)
    finally:
        app_module.clear_stop_request(dataset_id)


def test_stopping_isolated_dataset_worker_terminates_its_process(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    class StoppableProcess:
        terminated = False

        def wait(self, timeout=None):
            if not self.terminated:
                raise app_module.subprocess.TimeoutExpired('dataset worker', timeout)
            return -15

        def terminate(self):
            self.terminated = True

    process = StoppableProcess()
    launched = []
    monkeypatch.setattr(
        app_module.subprocess, 'Popen',
        lambda *_args, **kwargs: launched.append(kwargs) or process,
    )
    dataset_id = 123
    app_module.request_stop(dataset_id)
    app_module._run_dataset_in_worker(
        dataset_id, Path('/tmp/stopped-dataset.csv'), 'admin',
        None, None, None, app_module.repository,
    )
    assert process.terminated is True
    assert launched[0]['env']['OPENBLAS_NUM_THREADS'] == '1'
    assert app_module.stop_requested(dataset_id) is False


def test_workspace_remove_all_deletes_every_non_processing_dataset(client) -> None:
    login(client)
    for name in ('first.csv', 'second.csv'):
        client.post(
            "/datasets-analysis/upload",
            data={"dataset_kinds": "data"},
            files={"dataset_files": (name, BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
            follow_redirects=False,
        )
    import src.DashboardAnalytic as app_module

    source_paths = [Path(row['stored_path']) for row in app_module.repository.list_datasets()]
    response = client.post('/workspace/delete-datasets', follow_redirects=False)

    assert response.status_code == 303
    assert app_module.repository.list_datasets() == []
    assert all(not path.exists() for path in source_paths)


def test_admin_cannot_retry_queued_dataset(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(1, status="queued", progress=0)

    response = client.post("/datasets-analysis/retry/1")
    assert response.status_code == 400
    assert "Only ready, failed or stopped datasets can be reprocessed" in response.text


def test_admin_can_delete_queued_dataset(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    dataset_path = Path(dataset["stored_path"])
    assert dataset_path.exists()
    response = client.post("/datasets-analysis/delete/1", follow_redirects=False)
    assert response.status_code == 303
    assert app_module.repository.get_dataset(1) is None
    assert not dataset_path.exists()


def test_admin_can_stop_processing_dataset(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(1, status="processing", progress=33)
    processing_page = client.get('/workspace').text
    processing_actions = processing_page.split('<div class="queue-actions">', 1)[1].split('</div>', 1)[0]
    assert 'action-link-stop' in processing_actions
    assert 'action-link-reprocess' not in processing_actions
    response = client.post("/datasets-analysis/stop/1", follow_redirects=False)
    assert response.status_code == 303

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    assert dataset["status"] == "stopped"
    stopped_page = client.get('/workspace').text
    stopped_actions = stopped_page.split('<div class="queue-actions">', 1)[1].split('</div>', 1)[0]
    assert 'action-link-reprocess' in stopped_actions
    assert 'action-link-stop' not in stopped_actions


def test_reupload_same_file_reuses_existing_dataset_entry(client) -> None:
    login(client)
    payload = b"market,period,score\nES,2026-Q1,91\n"
    first_upload = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(payload), "text/csv")},
        follow_redirects=False,
    )
    second_upload = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(payload), "text/csv")},
        follow_redirects=False,
    )
    assert first_upload.status_code == 303
    assert second_upload.status_code == 303

    import src.DashboardAnalytic as app_module

    datasets = app_module.repository.list_datasets()
    assert len(datasets) == 1


def test_reupload_preserves_original_upload_date_for_dataset_ordering(client) -> None:
    login(client)
    payload = b"market,period,score\nES,2026-Q1,91\n"
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(payload), "text/csv")},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    original_upload = '2025-01-02 03:04:05'
    with app_module.repository.connection() as conn:
        conn.execute('UPDATE datasets SET uploaded_at = ? WHERE id = 1', (original_upload,))
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(payload), "text/csv")},
        follow_redirects=False,
    )

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    assert dataset['uploaded_at'] == original_upload

    workspace = client.get('/workspace')
    assert workspace.text.index('data-queue-sort-key="id"') < workspace.text.index('data-queue-sort-key="dataset"')
    assert 'data-queue-id data-queue-sort-value="1"' in workspace.text
    assert 'data-queue-sort-key="uploaded"' in workspace.text
    assert 'data-queue-sort-key="updated"' in workspace.text
    assert workspace.text.index('data-queue-sort-key="uploaded"') < workspace.text.index('data-queue-sort-key="updated"')
    styles = client.get('/static/css/app.css').text
    assert '.queue-table th:nth-child(2), .queue-table td:nth-child(2) { width: 360px; min-width: 360px; max-width: 360px; overflow-wrap: anywhere; }' in styles
    assert '.queue-table [data-queue-updated] { white-space: pre; }' in styles
    assert 'Default (' in workspace.text


def test_workspace_management_save_updates_name_and_user_access(client) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    created = client.post('/workspace/create', data={'name': 'Germany'}, follow_redirects=False)
    assert created.status_code == 303
    germany = next(item for item in app_module.workspace_registry.list() if item.name == 'Germany')
    demo = next(row for row in app_module.repository.list_users() if row['username'] == 'demo')

    response = client.post(
        '/workspace/save',
        data={'workspace_id': germany.id, 'name': 'Germany Q3', 'usernames': [str(demo['username'])]},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )

    assert response.status_code == 200
    assert response.json() == {
        'ok': True,
        'notice': 'Workspace name and access updated.',
        'workspace': {'id': germany.id, 'name': 'Germany Q3'},
    }
    assert app_module.workspace_registry.get(germany.id).name == 'Germany Q3'
    assert app_module.repository.list_user_workspace_ids(int(demo['id'])) == ['default', germany.id]
    workspace_page = client.get('/workspace')
    assert '<th class="workspace-name-column">Workspace</th>' in workspace_page.text
    assert '<th>Size</th>' in workspace_page.text
    assert 'Save access' not in workspace_page.text
    assert 'class="workspace-action-save icon-action"' in workspace_page.text
    assert 'title="Save workspace changes"' in workspace_page.text
    assert 'data-workspace-row-open' in workspace_page.text
    users_page = client.get('/admin')
    demo_row = users_page.text.split(f'aria-label="Filter workspaces for {demo["username"]}"', 1)[1].split('</details>', 1)[0]
    assert f'value="{germany.id}"' in demo_row
    assert 'checked' in demo_row

    unchanged_name = client.post(
        '/workspace/save',
        data={'workspace_id': germany.id, 'name': 'Germany Q3', 'usernames': []},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert unchanged_name.status_code == 200
    assert app_module.repository.list_user_workspace_ids(int(demo['id'])) == ['default']


def test_workspace_management_isolates_dataset_databases_and_remembers_last_opened_workspace(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    admin = next(row for row in app_module.repository.list_users() if row['username'] == 'admin')
    app_module.repository.set_user_workspace_access(int(admin['id']), ['default'])
    assert app_module.workspace_registry.registry_path.name == 'workspace-registry.db'
    assert app_module.workspace_registry.registry_path == app_module.settings.input_dir.parent.parent / 'workspace-registry.db'
    payload = b"market,period,score\nES,2026-Q1,91\n"
    client.post(
        '/datasets-analysis/upload', data={'dataset_kinds': 'data'},
        files={'dataset_files': ('default.csv', BytesIO(payload), 'text/csv')},
    )
    default_db = app_module.repository.db_path
    assert default_db.parent == app_module.settings.input_dir.parent
    assert default_db.name == 'Default.db'

    created = client.post('/workspace/create', data={'name': 'Campaign benchmark'}, follow_redirects=False)
    assert created.status_code == 303
    assert app_module.active_workspace is not None
    assert app_module.active_workspace.name == 'Campaign benchmark'
    assert app_module.repository.db_path != default_db
    assert app_module.repository.db_path.name == 'Campaign benchmark.db'
    assert app_module.repository.db_path.parent.name == 'Campaign benchmark'
    assert app_module.repository.list_datasets() == []

    page = client.get('/workspace')
    assert 'Campaign benchmark' in page.text
    assert 'Manage workspaces' in page.text
    assert 'data-workspace-open disabled>Open</button>' in page.text
    active_row = page.text.split('active-workspace-row', 1)[1].split('</tr>', 1)[0]
    assert 'workspace-action-remove icon-action' in active_row
    assert 'title="Remove workspace" disabled>×</button>' in active_row
    assert "const isActiveWorkspace = row?.classList.contains('active-workspace-row');" in page.text
    assert "control.disabled = isActiveWorkspace && control.matches('[data-workspace-row-open], .workspace-action-remove');" in page.text
    assert page.text.index('>Campaign benchmark (') < page.text.index('>Default (')
    workspace_id = app_module.active_workspace.id
    renamed = client.post('/workspace/rename', data={'workspace_id': workspace_id, 'name': 'Campaign benchmark Q3'})
    assert renamed.status_code == 200
    assert 'Campaign benchmark Q3' in renamed.text
    assert app_module.repository.db_path.name == 'Campaign benchmark Q3.db'
    assert app_module.repository.db_path.parent.name == 'Campaign benchmark Q3'
    assert app_module.repository.db_path.exists()

    selected = client.post('/workspace/select', data={'workspace_id': 'default'}, follow_redirects=False)
    assert selected.status_code == 303
    assert app_module.repository.db_path == default_db
    assert len(app_module.repository.list_datasets()) == 1

    dashboard_output = app_module.settings.output_dir / 'dashboards' / '20260915_120000 - Default Dashboard' / 'dashboard.pptx'
    dashboard_output.parent.mkdir(parents=True, exist_ok=True)
    dashboard_output.write_bytes(b'dashboard')
    with app_module.repository.connection() as conn:
        conn.execute('CREATE TABLE dashboard_ppt_jobs (output_path TEXT NOT NULL)')
        conn.execute('INSERT INTO dashboard_ppt_jobs (output_path) VALUES (?)', (str(dashboard_output),))

    duplicated = client.post('/workspace/duplicate', data={
        'workspace_id': 'default', 'include_generated_outputs': 'true',
    }, follow_redirects=False)
    assert duplicated.status_code == 303
    copied_workspace = None
    for _attempt in range(100):
        copied_workspace = next(
            (item for item in app_module.workspace_registry.list() if item.name == 'Default - Copy'),
            None,
        )
        if copied_workspace and copied_workspace.status == 'ready':
            break
        time.sleep(0.01)
    assert copied_workspace is not None
    assert copied_workspace.database_path.name == 'Default - Copy.db'
    assert app_module.repository.user_has_workspace_access('admin', copied_workspace.id)
    with app_module.repository.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM datasets').fetchone()[0] == 1
    copied_dashboard_output = copied_workspace.output_dir / 'dashboards' / '20260915_120000 - Default Dashboard' / 'dashboard.pptx'
    assert copied_dashboard_output.read_bytes() == b'dashboard'
    with sqlite3.connect(copied_workspace.database_path) as conn:
        assert conn.execute('SELECT output_path FROM dashboard_ppt_jobs').fetchone()[0] == str(copied_dashboard_output)

    copied_selected = client.post('/workspace/select', data={'workspace_id': copied_workspace.id}, follow_redirects=False)
    assert copied_selected.status_code == 303
    assert app_module.active_workspace is not None
    assert app_module.active_workspace.id == copied_workspace.id

    selected = client.post('/workspace/select', data={'workspace_id': 'default'}, follow_redirects=False)
    assert selected.status_code == 303

    cannot_remove_open = client.post('/workspace/delete', data={'workspace_id': 'default'}, follow_redirects=False)
    assert cannot_remove_open.headers['location'].startswith('/workspace?workspace_warning=')

    closed = client.post('/workspace/close', data={'workspace_id': 'default'}, follow_redirects=False)
    assert closed.status_code == 303
    assert app_module.active_workspace is None
    closed_workspace = client.get('/workspace')
    assert 'Data Ingestion' not in closed_workspace.text
    assert 'module-tab-disabled' in closed_workspace.text
    assert client.get('/datasets-analysis', follow_redirects=False).status_code == 303
    login_page = client.get('/login')
    assert login_page.text.index('>Campaign benchmark Q3</option>') < login_page.text.index('>Default</option>')
    assert '<option value="default" selected>Default</option>' in login_page.text

    deleted = client.post('/workspace/delete', data={'workspace_id': workspace_id}, follow_redirects=False)
    assert deleted.status_code == 303
    assert app_module.workspace_registry.get(workspace_id) is None


def test_workspace_remove_preserves_files_unless_explicitly_requested(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    first = app_module.workspace_registry.create('Preserve files')
    admin = next(row for row in app_module.repository.list_users() if row['username'] == 'admin')
    app_module.repository.set_user_workspace_access(int(admin['id']), [first.id])
    first_root = first.database_path.parent
    (first_root / 'input').mkdir()
    (first_root / 'input' / 'source.csv').write_text('value\n1\n', encoding='utf-8')

    removed = client.post('/workspace/delete', data={'workspace_id': first.id}, follow_redirects=False)
    assert removed.status_code == 303
    assert app_module.workspace_registry.get(first.id) is None
    assert (first_root / 'input' / 'source.csv').exists()
    assert not first.database_path.exists()

    second = app_module.workspace_registry.create('Delete files')
    app_module.repository.set_user_workspace_access(int(admin['id']), [second.id])
    second_root = second.database_path.parent
    (second_root / 'output').mkdir()
    (second_root / 'output' / 'report.pptx').write_bytes(b'report')

    removed_with_files = client.post(
        '/workspace/delete',
        data={'workspace_id': second.id, 'delete_workspace_files': 'true'},
        follow_redirects=False,
    )
    assert removed_with_files.status_code == 303
    assert app_module.workspace_registry.get(second.id) is None
    assert not second_root.exists()


def test_workspace_cache_clear_removes_only_derived_dashboard_artifacts(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.workspace_registry.get('default')
    assert workspace is not None
    workspace_root = workspace.database_path.parent
    cached_model = workspace_root / '.dashboard-data-cache' / 'charts-canvas' / 'chart.json'
    cached_model.parent.mkdir(parents=True, exist_ok=True)
    cached_model.write_text('{}', encoding='utf-8')
    legacy_png = workspace_root / '.dashboard-chart-cache' / 'chart.png'
    legacy_png.parent.mkdir(parents=True, exist_ok=True)
    legacy_png.write_bytes(b'png')
    before_clear = client.get('/api/workspaces/status').json()
    before_workspace = next(item for item in before_clear['workspaces'] if item['id'] == workspace.id)
    assert before_workspace['cache_size'] != '0 B'

    class StillRunningWorker:
        def result(self, *args, **kwargs):
            raise AssertionError('Cache clearing must not wait for Dashboard workers.')

    monkeypatch.setattr(
        app_module, 'e2e_dashboard_cancel_workspace_tasks',
        lambda _workspace: [StillRunningWorker()],
    )

    response = client.post(
        '/workspace/cache/delete', data={'workspace_id': workspace.id},
        headers={'X-Requested-With': 'XMLHttpRequest'}, follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json()['workspace_id'] == workspace.id
    assert response.json()['job_id']
    tasks = client.get('/api/background-tasks').json()['groups']
    assert any(
        task['label'] == 'Clearing workspace cache'
        for group in tasks for task in group['tasks']
    )
    for _attempt in range(100):
        if not cached_model.exists() and not legacy_png.exists():
            break
        time.sleep(0.01)
    assert not cached_model.exists()
    assert not legacy_png.exists()
    assert workspace.database_path.exists()
    status = client.get('/api/workspaces/status').json()
    assert workspace.id in status['cleared_cache_workspace_ids']
    cleared_workspace = next(item for item in status['workspaces'] if item['id'] == workspace.id)
    assert cleared_workspace['cache_size'] == '0 B'
    completed_tasks = client.get('/api/background-tasks').json()['groups']
    assert any(
        task['label'] == 'Clearing workspace cache' and task['detail'] == 'Cache cleared'
        for group in completed_tasks for task in group['tasks']
    )


def test_opening_workspace_removes_only_cache_from_previous_versions(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.workspace_registry.get('default')
    assert workspace is not None
    workspace_root = workspace.database_path.parent
    version_file = workspace_root / '.dashboard-cache-version.json'
    stale_model = workspace_root / '.dashboard-data-cache' / 'charts-canvas' / 'stale.json'
    stale_model.parent.mkdir(parents=True, exist_ok=True)
    stale_model.write_text('{}', encoding='utf-8')
    legacy_chart = workspace_root / '.dashboard-chart-cache' / 'stale.png'
    legacy_chart.parent.mkdir(parents=True, exist_ok=True)
    legacy_chart.write_bytes(b'png')
    version_file.write_text('{"application":"0.2.0"}', encoding='utf-8')
    with app_module.repository.connection() as connection:
        connection.execute("INSERT INTO dashboard_filter_selections (cache_key) VALUES ('stale-selection')")

    app_module.activate_workspace(workspace.id)

    assert not stale_model.exists()
    assert not legacy_chart.exists()
    assert json.loads(version_file.read_text(encoding='utf-8')) == app_module.workspace_cache_version_signature()
    with app_module.repository.connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM dashboard_filter_selections').fetchone()[0] == 0

    current_model = workspace_root / '.dashboard-data-cache' / 'charts-canvas' / 'current.json'
    current_model.parent.mkdir(parents=True, exist_ok=True)
    current_model.write_text('{}', encoding='utf-8')
    app_module.activate_workspace(workspace.id)
    assert current_model.exists()

    previous_patch_signature = dict(app_module.workspace_cache_version_signature())
    previous_patch_signature['application'] = '0.3.0'
    version_file.write_text(json.dumps(previous_patch_signature), encoding='utf-8')
    app_module.activate_workspace(workspace.id)
    assert current_model.exists()
    assert json.loads(version_file.read_text(encoding='utf-8')) == app_module.workspace_cache_version_signature()

    prepared_manifest = workspace_root / '.dashboard-data-cache' / 'dashboard-previews' / 'prepared.json'
    prepared_manifest.parent.mkdir(parents=True, exist_ok=True)
    prepared_manifest.write_text('{}', encoding='utf-8')
    stale_png = workspace_root / '.dashboard-data-cache' / 'charts-pil' / 'stale.png'
    stale_png.parent.mkdir(parents=True, exist_ok=True)
    stale_png.write_bytes(b'png')
    render_only_signature = dict(app_module.workspace_cache_version_signature())
    render_only_signature['dashboard_render'] = int(render_only_signature['dashboard_render']) - 1
    version_file.write_text(json.dumps(render_only_signature), encoding='utf-8')
    with app_module.repository.connection() as connection:
        connection.execute("INSERT INTO dashboard_filter_selections (cache_key) VALUES ('prepared-selection')")

    app_module.activate_workspace(workspace.id)

    assert prepared_manifest.exists()
    assert not stale_png.exists()
    with app_module.repository.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM dashboard_filter_selections WHERE cache_key = 'prepared-selection'").fetchone()[0] == 1


def test_workspace_management_reports_every_supported_row_status(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'super', 'password': 'super123'})
    workspace = app_module.workspace_registry.get('default')
    assert workspace is not None

    page = client.get('/workspace')
    header = page.text.split('<table class="workspace-library-table">', 1)[1].split('</thead>', 1)[0]
    assert header.index('>Workspace</th>') < header.index('Users with access') < header.index('<th>Size</th>')
    assert header.index('<th>Cache Size</th>') < header.index('<th>Status</th>') < header.index('<th>Actions</th>')
    assert 'workspace-status-active' in page.text
    first_row = page.text.split('<tr class="workspace-library-row', 1)[1].split('</tr>', 1)[0]
    assert first_row.index('workspace-action-close') < first_row.index('workspace-action-duplicate')
    assert 'action="/workspace/close"' in first_row
    assert 'aria-label="Close workspace"' in first_row
    assert '>⏻</button>' in first_row
    stylesheet = (Path(__file__).parents[1] / 'src/web_interface/static/css/app.css').read_text(encoding='utf-8')
    assert '.workspace-row-actions .workspace-action-open.icon-action::after' in stylesheet
    assert "d='M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z'" in stylesheet
    assert '.workspace-row-actions .workspace-action-clear-cache.icon-action::after' in stylesheet
    assert "d='m7 21-4-4a2 2 0 0 1 0-2.83L12.17 5" in stylesheet
    assert '.workspace-action-close { background: linear-gradient(135deg, #08736d, #20a797);' in stylesheet
    assert '.workspace-action-duplicate { background: linear-gradient(135deg, #b97813, #e0a33e);' in stylesheet
    assert '.workspace-library-table .workspace-name-column { width: 42.5rem; min-width: 42.5rem; }' in stylesheet
    assert '.workspace-library-table .workspace-access-column { width: 12rem; min-width: 12rem; }' in stylesheet

    active = app_module.workspace_table_status(workspace, [])
    ready = app_module.workspace_table_status(replace(workspace, id='ready-copy'), [])
    duplicating = app_module.workspace_table_status(replace(workspace, id='copy', status='duplicating'), [])
    unavailable = app_module.workspace_table_status(
        replace(workspace, id='missing', database_path=tmp_path / 'missing.db'), [],
    )
    assert {active['status'], ready['status'], duplicating['status'], unavailable['status']} == {
        'active', 'ready', 'duplicating', 'unavailable',
    }

    cache_job = {
        'operation': 'cache-clear', 'workspace_id': workspace.id, 'workspace_name': workspace.name,
        'owner': 'super', 'status': 'processing', 'created_at': time.time(),
    }
    delete_job = {
        'operation': 'delete', 'workspace_id': 'deleting-workspace', 'workspace_name': 'Deleting',
        'owner': 'super', 'status': 'processing', 'created_at': time.time(),
    }
    with app_module.WORKSPACE_LIFECYCLE_JOBS_LOCK:
        app_module.WORKSPACE_LIFECYCLE_JOBS['status-cache-test'] = cache_job
        app_module.WORKSPACE_LIFECYCLE_JOBS['status-delete-test'] = delete_job
    try:
        payload = client.get('/api/workspaces/status').json()
        current = next(item for item in payload['workspaces'] if item['id'] == workspace.id)
        assert (current['status'], current['status_label']) == ('clearing-cache', 'Clearing cache')
        deleting = next(item for item in payload['lifecycle_workspaces'] if item['id'] == 'deleting-workspace')
        assert (deleting['status'], deleting['status_label']) == ('deleting', 'Deleting')

        with app_module.WORKSPACE_LIFECYCLE_JOBS_LOCK:
            app_module.WORKSPACE_LIFECYCLE_JOBS['status-cache-test']['status'] = 'failed'
            app_module.WORKSPACE_LIFECYCLE_JOBS['status-cache-test']['finished_at'] = time.time()
        failed = client.get('/api/workspaces/status').json()
        current = next(item for item in failed['workspaces'] if item['id'] == workspace.id)
        assert (current['status'], current['status_label']) == ('error', 'Error')
    finally:
        with app_module.WORKSPACE_LIFECYCLE_JOBS_LOCK:
            app_module.WORKSPACE_LIFECYCLE_JOBS.pop('status-cache-test', None)
            app_module.WORKSPACE_LIFECYCLE_JOBS.pop('status-delete-test', None)


def test_workspace_status_reports_cancelled_duplicate_for_live_row_removal(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    with app_module.WORKSPACE_LIFECYCLE_JOBS_LOCK:
        app_module.WORKSPACE_LIFECYCLE_JOBS['cancelled-duplicate-test'] = {
            'operation': 'duplicate-cancel', 'workspace_id': 'cancelled-copy',
            'workspace_name': 'Cancelled Copy', 'owner': 'admin', 'status': 'ready',
            'finished_at': time.time(),
        }
    try:
        response = client.get('/api/workspaces/status')
        assert response.status_code == 200
        assert 'cancelled-copy' in response.json()['removed_workspace_ids']
    finally:
        with app_module.WORKSPACE_LIFECYCLE_JOBS_LOCK:
            app_module.WORKSPACE_LIFECYCLE_JOBS.pop('cancelled-duplicate-test', None)


def test_interrupted_background_jobs_become_retryable_failures(client) -> None:
    import src.DashboardAnalytic as app_module

    source = app_module.settings.input_dir / 'interrupted.csv'
    source.write_text('value\n1\n', encoding='utf-8')
    dataset_id, _ = app_module.repository.add_dataset(source.name, str(source), 'admin')
    app_module.repository.update_dataset_profile(dataset_id, status='processing', progress=45)
    queued_source = app_module.settings.input_dir / 'interrupted-queued.csv'
    queued_source.write_text('value\n2\n', encoding='utf-8')
    queued_dataset_id, _ = app_module.repository.add_dataset(queued_source.name, str(queued_source), 'admin')
    app_module.repository.update_dataset_profile(queued_dataset_id, status='queued', progress=0)
    report_id = app_module.repository.create_report_job(
        report_type='netcheck_cdr', technology='nsa', scope='single',
        data_dataset_id=dataset_id, voice_dataset_id=dataset_id, speech_dataset_id=dataset_id,
        dataset_ids={'data': [dataset_id], 'voice': [dataset_id], 'speech': [dataset_id]},
        dataset_names={'data': [source.name], 'voice': [source.name], 'speech': [source.name]},
        slide_count=1, template_name='NSA Slide Template', output_file='interrupted.pptx',
        output_path=app_module.settings.output_dir / 'reports' / 'interrupted.pptx', created_by='admin',
    )

    datasets, reports = app_module.repository.fail_interrupted_background_jobs()

    assert datasets == [dataset_id, queued_dataset_id]
    assert reports == [report_id]
    assert app_module.repository.get_dataset(dataset_id)['status'] == 'failed'
    queued_dataset = app_module.repository.get_dataset(queued_dataset_id)
    assert queued_dataset['status'] == 'failed'
    assert 'application restarted' in queued_dataset['last_error']
    report = app_module.repository.get_report_run(report_id)
    assert report['status'] == 'failed'
    assert 'application restarted' in report['last_error']
    assert app_module.serialize_report_job(report)['retry_url'] == f'/e2e-reporting/jobs/{report_id}/retry'


def test_interrupted_dataset_processing_is_resumed_instead_of_failed(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    source = workspace.input_dir / 'resume-interrupted.csv'
    source.write_text('market,score\nES,91\n', encoding='utf-8')
    dataset_id, _ = app_module.repository.add_dataset(source.name, str(source), 'admin')
    app_module.repository.update_dataset_profile(
        dataset_id,
        status='processing',
        progress=45,
        dataset_kind='data',
        processing_options_json=json.dumps({
            'vodafone_mapping_dataset_id': None,
            'three_mapping_dataset_id': None,
        }),
    )

    datasets, reports = app_module.repository.fail_interrupted_background_jobs(fail_datasets=False)
    assert datasets == []
    assert reports == []
    assert app_module.repository.get_dataset(dataset_id)['status'] == 'processing'

    resumed = app_module.resume_interrupted_dataset_processing(workspace)
    assert resumed == [dataset_id]
    for _attempt in range(200):
        if app_module.repository.get_dataset(dataset_id)['status'] == 'ready':
            break
        time.sleep(0.01)
    completed = app_module.repository.get_dataset(dataset_id)
    assert completed['status'] == 'ready'
    assert completed['progress'] == 100
    assert completed['last_error'] in {None, ''}


def test_restart_recovery_preserves_descending_order_for_a_saved_cdr_batch(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    low_source = workspace.input_dir / 'resume-low.csv'
    high_source = workspace.input_dir / 'resume-high.csv'
    low_source.write_text('market,score\nES,91\n', encoding='utf-8')
    high_source.write_text('market,score\nES,92\n', encoding='utf-8')
    low_id, _ = app_module.repository.add_dataset(low_source.name, str(low_source), 'admin')
    high_id, _ = app_module.repository.add_dataset(high_source.name, str(high_source), 'admin')
    for dataset_id in (low_id, high_id):
        app_module.repository.update_dataset_profile(
            dataset_id, status='queued', dataset_kind='data',
            processing_options_json=json.dumps({'batch_priority': True}),
        )

    submissions = []
    monkeypatch.setattr(
        app_module, '_submit_workspace_job',
        lambda _repository, _callback, *args, **kwargs: submissions.append((args[0], kwargs['batch_priority'])) or Future(),
    )
    monkeypatch.setattr(app_module, '_track_dataset_future', lambda *_args: None)

    try:
        assert app_module.resume_interrupted_dataset_processing(workspace) == [high_id, low_id]
        assert submissions == [(high_id, True), (low_id, True)]
    finally:
        app_module._unregister_dataset_processing(low_id, app_module.repository)
        app_module._unregister_dataset_processing(high_id, app_module.repository)


def test_ready_dataset_progress_cannot_be_replaced_by_a_late_worker_update(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    workspace = app_module.active_workspace
    assert workspace is not None
    source = workspace.input_dir / 'late-progress.csv'
    source.write_text('market,score\nES,91\n', encoding='utf-8')
    dataset_id, _ = app_module.repository.add_dataset(source.name, str(source), 'admin')
    app_module.repository.update_dataset_profile(dataset_id, status='ready', progress=100)

    app_module.repository.update_dataset_profile(dataset_id, progress=55)

    row = app_module.repository.get_dataset(dataset_id)
    assert row['status'] == 'ready'
    assert row['progress'] == 100


def test_inconsistent_ready_dataset_pauses_recovered_queue_until_retry(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    source = workspace.input_dir / 'inconsistent-progress.csv'
    source.write_text('market,score\nES,91\n', encoding='utf-8')
    failed_id, _ = app_module.repository.add_dataset(source.name, str(source), 'admin')
    app_module.repository.update_dataset_profile(failed_id, status='ready', progress=55, dataset_kind='data')
    queued_source = workspace.input_dir / 'queued-after-inconsistent.csv'
    queued_source.write_text('market,score\nES,92\n', encoding='utf-8')
    queued_id, _ = app_module.repository.add_dataset(queued_source.name, str(queued_source), 'admin')
    app_module.repository.update_dataset_profile(queued_id, status='queued', progress=0, dataset_kind='data')

    assert app_module.repository.fail_inconsistent_ready_datasets() == [failed_id]
    assert app_module.resume_interrupted_dataset_processing(workspace) == []
    queued_task = next(
        task for task in app_module._workspace_background_tasks(workspace)
        if task['dataset_id'] == queued_id
    )
    assert queued_task['detail'] == f'Waiting for interrupted dataset #{failed_id} to be retried'
    assert app_module.repository.get_dataset(failed_id)['status'] == 'failed'


def test_background_card_uses_the_dataset_worker_step(client) -> None:
    import src.DashboardAnalytic as app_module

    workspace = app_module.active_workspace
    assert workspace is not None
    source = workspace.input_dir / 'step-progress.csv'
    source.write_text('market,score\nES,91\n', encoding='utf-8')
    dataset_id, _ = app_module.repository.add_dataset(source.name, str(source), 'admin')
    app_module.repository.update_dataset_profile(
        dataset_id, status='processing', progress=62,
        processing_step='Writing dataset rows', dataset_kind='data',
    )

    task = next(
        task for task in app_module._workspace_background_tasks(workspace)
        if task['dataset_id'] == dataset_id
    )
    assert task['detail'] == 'Writing dataset rows'
    assert task['progress'] == 62


def test_queued_dataset_message_tracks_its_current_blocker(client) -> None:
    import src.DashboardAnalytic as app_module

    workspace = app_module.active_workspace
    assert workspace is not None
    active_id = None
    for name, kind, status in (
        ('mapping.csv', 'mapping_three', 'ready'),
        ('active.csv', 'data', 'processing'),
        ('waiting.csv', 'speech', 'queued'),
    ):
        source = workspace.input_dir / name
        source.write_text('market,score\nES,91\n', encoding='utf-8')
        dataset_id, _ = app_module.repository.add_dataset(name, str(source), 'admin')
        if status == 'processing':
            active_id = dataset_id
        app_module.repository.update_dataset_profile(
            dataset_id, dataset_kind=kind, status=status,
            progress=100 if status == 'ready' else 10 if status == 'processing' else 0,
        )

    waiting = next(
        task for task in app_module._workspace_background_tasks(workspace)
        if task['label'] == 'Processing dataset: waiting.csv'
    )
    assert waiting['detail'] == f'Waiting for dataset #{active_id} to finish'


def test_legacy_vendor_recovery_queues_without_writing_in_workspace_request(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    workspace = app_module.active_workspace
    assert workspace is not None
    source = workspace.input_dir / 'legacy-locked.csv'
    source.write_text('market,score\nES,91\n', encoding='utf-8')
    dataset_id, _ = app_module.repository.add_dataset(source.name, str(source), 'admin')
    app_module.repository.update_dataset_profile(
        dataset_id,
        status='failed',
        progress=100,
        dataset_kind='data',
        last_error='database is locked',
        processing_options_json='{}',
    )
    dataset = app_module.serialize_dataset_row(app_module.repository.get_dataset(dataset_id))

    class DeferredFuture:
        @staticmethod
        def result():
            return None

    class CapturingExecutor:
        submitted = False

        def submit_ordered(self, *_args, **_kwargs):
            self.submitted = True
            return DeferredFuture()

    executor = CapturingExecutor()
    monkeypatch.setattr(app_module, '_dataset_processing_executor', lambda _repository: executor)
    monkeypatch.setattr(
        app_module.repository,
        'update_dataset_profile',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('request attempted a synchronous write')),
    )
    tasks = BackgroundTasks()
    try:
        queued = app_module.queue_legacy_vendor_mapping_recovery(tasks, [dataset], 'admin')
    finally:
        app_module._unregister_dataset_processing(dataset_id, app_module.repository)

    assert queued is True
    assert executor.submitted is True
    assert len(tasks.tasks) == 1


def test_dataset_executor_defaults_to_one_fifo_background_worker(client) -> None:
    import src.DashboardAnalytic as app_module

    assert app_module._dataset_processing_executor(app_module.repository)._max_workers == 1


def test_background_task_scheduler_starts_queued_work_in_fifo_order() -> None:
    from src.modules.background_scheduler import BackgroundTaskScheduler

    scheduler = BackgroundTaskScheduler(max_workers=1, thread_name_prefix='test-fifo')
    started = Event()
    release = Event()
    order: list[str] = []

    def task(name: str, block: bool = False) -> str:
        order.append(name)
        if block:
            started.set()
            assert release.wait(timeout=2)
        return name

    try:
        first = scheduler.submit(task, 'first', True)
        assert started.wait(timeout=2)
        second = scheduler.submit(task, 'second')
        third = scheduler.submit(task, 'third')
        assert order == ['first']
        release.set()
        assert [first.result(timeout=2), second.result(timeout=2), third.result(timeout=2)] == ['first', 'second', 'third']
        assert order == ['first', 'second', 'third']
    finally:
        scheduler.shutdown()


def test_background_task_scheduler_orders_workspace_phases_and_dataset_ids() -> None:
    from src.modules.background_scheduler import BackgroundTaskScheduler

    scheduler = BackgroundTaskScheduler(max_workers=2, thread_name_prefix='test-workspace-order')
    started = Event()
    release = Event()
    order: list[str] = []

    def task(name: str, block: bool = False) -> None:
        order.append(name)
        if block:
            started.set()
            assert release.wait(timeout=2)

    try:
        first = scheduler.submit_ordered(
            task, 'active', True, workspace_key='workspace', priority=(1, 8),
        )
        assert started.wait(timeout=2)
        combined = scheduler.submit_ordered(task, 'combined', workspace_key='workspace', priority=(2, 0))
        dataset_high = scheduler.submit_ordered(task, 'dataset-7', workspace_key='workspace', priority=(1, 7))
        mapping = scheduler.submit_ordered(task, 'mapping', workspace_key='workspace', priority=(0, 10))
        dataset_low = scheduler.submit_ordered(task, 'dataset-3', workspace_key='workspace', priority=(1, 3))
        materialization = scheduler.submit_ordered(task, 'materialization', workspace_key='workspace', priority=(3, 0))
        assert order == ['active']
        release.set()
        for future in (first, mapping, dataset_low, dataset_high, combined, materialization):
            future.result(timeout=2)
        assert order == ['active', 'mapping', 'dataset-3', 'dataset-7', 'combined', 'materialization']
    finally:
        scheduler.shutdown()


def test_workspace_dataset_priority_uses_fifo_for_individual_cdrs_and_descending_ids_for_batches() -> None:
    import src.DashboardAnalytic as app_module

    assert app_module.workspace_dataset_job_priority(1, 8, 'data') == (1, 0, 0)
    assert app_module.workspace_dataset_job_priority(1, 3, 'speech') == (1, 0, 0)
    assert app_module.workspace_dataset_job_priority(1, 8, 'data', batch_priority=True) == (1, 0, -8)
    assert app_module.workspace_dataset_job_priority(1, 3, 'speech', batch_priority=True) == (1, 0, -3)


def test_combined_recreation_is_queued_while_cdr_processing_is_pending(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    dataset_id, _ = app_module.repository.add_dataset(
        'pending-cdr.csv', str(workspace.input_dir / 'pending-cdr.csv'), 'admin',
    )
    app_module.repository.update_dataset_profile(dataset_id, dataset_kind='data', status='queued')
    submitted = []
    monkeypatch.setattr(
        app_module, '_submit_workspace_job',
        lambda _repository, _callback, *_args, **kwargs: submitted.append(kwargs),
    )

    job = app_module.start_combined_cdr_recreation_job(workspace, 'data', 'admin')
    try:
        assert job['status'] == 'queued'
        assert submitted == [{'phase': 2}]
    finally:
        with app_module.AUTO_CALCULATED_FIELD_JOBS_LOCK:
            app_module.AUTO_CALCULATED_FIELD_JOBS.pop(job['id'], None)


def test_opening_workspace_page_does_not_enqueue_materialization(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    monkeypatch.setattr(
        app_module, 'queue_workspace_dimension_materialization',
        lambda _workspace: (_ for _ in ()).throw(AssertionError('Workspace page started background work')),
    )
    assert client.get('/workspace').status_code == 200


def test_cancelled_backup_removes_its_partial_archive(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    source_file = app_module.settings.input_dir / 'cancelled-backup-source.txt'
    source_file.write_text('cancel this archive', encoding='utf-8')
    config = app_module.recurring_backup_settings() | {
        'components': ['input'],
        'workspace_ids': [app_module.active_workspace.id],
        'backup_path': str(tmp_path),
    }
    checks = 0

    def cancel_during_archive() -> None:
        nonlocal checks
        checks += 1
        if checks >= 5:
            raise InterruptedError('Backup stopped by user.')

    with pytest.raises(InterruptedError):
        app_module.create_recurring_database_backup(config, cancel_callback=cancel_during_archive)

    assert list(tmp_path.glob('dashboard-analytic-backup-*.zip')) == []
    assert list(tmp_path.glob('dashboard-analytic-export-*')) == []


def test_dashboard_library_open_close_and_view_actions_include_labels() -> None:
    root = Path(__file__).parents[1] / 'src' / 'web_interface' / 'static'
    script = (root / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')
    styles = (root / 'css' / 'e2e_dashboards.css').read_text(encoding='utf-8')

    assert "action('View Dashboard', 'View Dashboard'" in script
    assert "filtersAreOpen ? 'Close Filters' : 'Open Filters'" in script
    assert script.index("action('View Dashboard', 'View Dashboard'") < script.index("filtersAreOpen ? 'Close Filters' : 'Open Filters'")
    assert 'width:fit-content!important;min-width:max-content!important' in styles
    assert '.ds-dashboard-action.ds-dashboard-close' in styles
    assert "primaryActionLabel(view, 'View', 'Dashboard');" in script
    assert "primaryActionLabel(open, filtersAreOpen ? 'Close' : 'Open', 'Filters');" in script
    assert 'grid-column:span 2' in styles
    assert '.ds-dashboard-action-label{display:contents}' in styles
    assert 'height:3.35rem!important' in styles
    assert 'border-radius:.85rem!important' in styles


def test_dashboard_library_ppt_export_selects_scope_cdrs_explicitly() -> None:
    root = Path(__file__).parents[1] / 'src' / 'web_interface'
    template = (root / 'templates' / 'e2e_dashboards.html').read_text(encoding='utf-8')
    script = (root / 'static' / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')
    styles = (root / 'static' / 'css' / 'e2e_dashboards.css').read_text(encoding='utf-8')

    assert 'id="ds-ppt-dataset-overlay"' in template
    assert 'id="ds-ppt-dataset-choices"' in template
    assert 'id="ds-ppt-dataset-scope"' in template
    assert 'id="ds-ppt-region-section"' in template
    assert 'id="ds-ppt-dataset-region"' in template
    assert 'aria-label="PowerPoint regions"' in template
    assert 'id="ds-ppt-city-section"' in template
    assert 'id="ds-ppt-dataset-city"' in template
    assert 'data-multiselect-preset-label="7 Main Cities"' in template
    assert '>Select Dashboard Datasets Universe<' in template
    assert 'id="ds-ppt-date-from"' in template
    assert 'id="ds-ppt-date-to"' in template
    assert template.index('id="ds-ppt-scope-title"') < template.index('id="ds-ppt-cdr-title"') < template.index('id="ds-ppt-dates-title"')
    assert template.index('id="ds-ppt-dates-title"') < template.index('id="ds-ppt-dataset-cancel"') < template.index('id="ds-ppt-dataset-confirm"')
    assert "const chooseDashboardPptUniverse = dashboard" in script
    assert ".slice(0, scope === 'multivendor' ? 1 : 2)" in script
    assert "const savedDateFrom = String(dashboard?.date_from || 'Oldest');" in script
    assert "const savedDateTo = String(dashboard?.date_to || 'Newest');" in script
    assert 'const universeChoice = await chooseDashboardPptUniverse(item);' in script
    assert "api('/geography-options', 'POST', exportUniverse())" in script
    assert 'const withPptSelection = (dashboard, selectionField, values)' in script
    assert "withPptSelection(exportDefinition, 'City', selectedCities);" in script
    assert 'selected_regions: selectedRegions' in script
    assert 'exportDefinition.scope = universeChoice.scope;' in script
    assert 'exportDefinition.datasets = universeChoice.datasets;' in script
    assert 'exportDefinition.date_from = universeChoice.date_from;' in script
    assert 'exportDefinition.date_to = universeChoice.date_to;' in script
    assert "title: 'Choose PowerPoint Scope'" not in script
    assert 'delete exportDefinition.datasets;' not in script
    assert 'grid-template-rows:auto minmax(0,1fr) auto' in styles
    assert '.ds-ppt-universe-body{min-height:0;overflow-y:auto' in styles
    assert 'max-height:calc(100dvh - .75rem)' in styles
    assert '.ds-ppt-date-choice input[type="date"]{box-sizing:border-box;width:100%;min-width:0}' in styles
    assert 'input[type="checkbox"]{box-sizing:border-box;width:1rem' in styles


def test_dashboard_filters_panel_defaults_hidden_and_expanded_and_persists_for_the_session() -> None:
    root = Path(__file__).parents[1] / 'src' / 'web_interface'
    template = (root / 'templates' / 'e2e_dashboards.html').read_text(encoding='utf-8')
    app_script = (root / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')

    panel = template.split('id="ds-filter-panel"', 1)[1].split('>', 1)[0]
    assert ' open' in panel
    assert 'data-panel-state-storage="session"' in panel
    assert "const sessionScoped = panel.dataset.panelStateStorage === 'session';" in app_script
    assert 'const storage = sessionScoped ? window.sessionStorage : window.localStorage;' in app_script

    dashboard_script = (root / 'static' / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')
    assert "const authenticatedSession = document.body.dataset.authenticatedSession || 'anonymous';" in dashboard_script
    assert ':open:${authenticatedSession}`' in dashboard_script
    assert ':filters-open:${authenticatedSession}`' in dashboard_script
    assert 'await openDashboard(last, {showFilters: rememberedFiltersOpen()});' in dashboard_script


def test_dashboard_open_hydrates_saved_state_before_preparation_catalogues() -> None:
    script = (Path(__file__).parents[1] / 'src' / 'web_interface' / 'static' / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')

    assert 'return hasStoredUniverse(value) ? saved : {...saved, ...(rememberedUniverse(id) || {})};' in script
    assert 'const hasStoredSelection = Object.prototype.hasOwnProperty.call(definition.filters, field);' in script
    assert '...selected].map(value => String(value))' in script


def test_ready_open_dashboard_preloads_chart_models_before_viewer_opens() -> None:
    script = (Path(__file__).parents[1] / 'src' / 'web_interface' / 'static' / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')

    assert 'function scheduleBackgroundChartPreload(token)' in script
    assert "scheduleBackgroundChartPreload(payload.token);" in script
    assert "await loadChartPayload(chart, 'low').catch(() => null);" in script
    assert "|| !$('ds-viewer').hidden" in script


def test_dashboard_standard_universe_warmup_and_open_state_restoration_are_configured() -> None:
    root = Path(__file__).parents[1] / 'src'
    dashboard_source = (root / 'modules' / 'e2e_dashboards.py').read_text(encoding='utf-8')
    script = (root / 'web_interface' / 'static' / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')

    assert "('operator', 'single', {kind: [int(row['id']) for row in rows[:2]]" in dashboard_source
    assert "('multivendor', 'multivendor', {kind: [int(row['id']) for row in rows[:1]]" in dashboard_source
    assert "('all-cdrs', 'single', {kind: [int(row['id']) for row in rows]" in dashboard_source
    assert "definition.date_from = 'Oldest'" in dashboard_source
    assert "definition.date_to = 'Newest'" in dashboard_source
    assert 'schedule_dashboard_warmup(workspace, dashboard_id, saved_definition, user.username, force=True)' in dashboard_source
    assert "dashboard_warmup_cancellations[key] = {'requested': False}" in dashboard_source
    assert "cancelled=lambda: bool(cancellation['requested'])" in dashboard_source
    assert "last = sessionStorage.getItem(openStorageKey) || '';" in script
    assert 'const restoreOpenDashboard = restorePageState;' not in script


def test_ppt_job_can_open_its_immutable_dashboard_snapshot() -> None:
    root = Path(__file__).parents[1] / 'src'
    dashboard_source = (root / 'modules' / 'e2e_dashboards.py').read_text(encoding='utf-8')
    script = (root / 'web_interface' / 'static' / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')
    styles = (root / 'web_interface' / 'static' / 'css' / 'e2e_dashboards.css').read_text(encoding='utf-8')

    assert "'slides': snapshot.payload.get('slides', [])" in dashboard_source
    assert "'viewer_available': bool(slides)" in dashboard_source
    assert "jobAction('View Dashboard snapshot', 'report-job-dashboard-button'" in script
    assert 'async function openDashboardPptViewer(job)' in script
    assert 'pptDashboardViewer = {' in script
    assert 'const chartPayloadUrl = chart => chart.payload_url ||' in script
    assert '.report-job-dashboard-button::before' in styles
    assert 'const pptSnapshotChart = Boolean(pptDashboardViewer && chart.data_url);' in script
    assert "Boolean(pptDashboardViewer) && !chart.data_url" in script
    assert "if (pptDashboardViewer) {\n      $('ds-generate-ppt').disabled = true;" in script


def test_dashboard_ppt_job_is_queued_before_preparation_and_chart_rendering() -> None:
    root = Path(__file__).parents[1] / 'src'
    dashboard_source = (root / 'modules' / 'e2e_dashboards.py').read_text(encoding='utf-8')
    script = (root / 'web_interface' / 'static' / 'js' / 'e2e_dashboards.js').read_text(encoding='utf-8')

    assert 'never make the library button wait for' in script
    assert 'scopePreview = await api' not in script
    assert 'for (const index of chartIndexes)' not in script
    assert 'Inserting the export job must remain quick.' in dashboard_source
    assert 'preview = restore_matching_preview_manifest(workspace, dashboard_id, definition)' in dashboard_source


def test_cold_dashboard_ppt_job_progress_covers_prepare_models_and_presentation() -> None:
    source = (Path(__file__).parents[1] / 'src' / 'modules' / 'e2e_dashboards.py').read_text(encoding='utf-8')

    assert 'min(24, 1 + round(percent * 0.23))' in source
    assert 'model_progress_start = 25 + round(position * 65 / max(len(indexes), 1))' in source
    assert 'progress=91 + round(rendered * 4 / max(chart_total, 1))' in source
    assert "progress=90, last_error=''" in source
    assert 'progress=96, chart_count=rendered' in source
    assert 'def pulse_canvas_progress()' in source
    assert 'except sqlite3.Error:' in source


def test_dashboard_background_tasks_are_named_without_dashboard_subgroups() -> None:
    script = (Path(__file__).parents[1] / 'src' / 'web_interface' / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')

    assert 'Dashboard “${dashboardName}”: ${String(task.label || \'Background task\')}' in script
    assert 'let previousDashboardName' not in script


def test_complete_dashboard_universe_uses_materialized_row_counts() -> None:
    source = (Path(__file__).parents[1] / 'src' / 'modules' / 'e2e_dashboards.py').read_text(encoding='utf-8')

    assert 'def is_complete_unfiltered_universe(' in source
    assert 'known_full_row_counts=selected_source_rows if complete_unfiltered_universe else None' in source
    assert "'Using materialized combined CDR row counts for the complete Dataset Universe'" in source


def test_dashboard_reduced_and_filtered_universes_share_one_combined_count_query(tmp_path: Path) -> None:
    root = Path(__file__).parents[1] / 'src' / 'modules'
    dashboard_source = (root / 'e2e_dashboards.py').read_text(encoding='utf-8')
    repository_source = (root / 'repository.py').read_text(encoding='utf-8')

    assert 'COUNT(*) AS universe_count' in dashboard_source
    assert 'SUM(CASE WHEN {filtered_where} THEN 1 ELSE 0 END) AS filtered_count' in dashboard_source
    assert 'universe_row_counts_json' in dashboard_source
    assert 'universe_row_counts_json' in repository_source
    from src.modules.repository import Repository

    repository = Repository(tmp_path / 'dashboard-counts.db')
    repository.initialize()
    with repository.connection() as connection:
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(dashboard_filter_selections)')}
    assert 'universe_row_counts_json' in columns


def test_large_datasets_share_one_memory_slot_per_workspace(client, monkeypatch, tmp_path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    monkeypatch.setattr(app_module, 'HEAVY_DATASET_PROCESSING_THRESHOLD_BYTES', 10)
    large = tmp_path / 'large.csv'
    large.write_bytes(b'x' * 11)
    small = tmp_path / 'small.csv'
    small.write_bytes(b'x')

    repository = Repository(tmp_path / 'workspace.db')
    other_repository = Repository(tmp_path / 'other-workspace.db')
    first = app_module._dataset_resource_slot(repository, large)
    second = app_module._dataset_resource_slot(repository, large)
    other = app_module._dataset_resource_slot(other_repository, large)

    assert first is second
    assert first is not other
    assert app_module._dataset_resource_slot(repository, small) is not first


def test_ready_chart_set_job_supports_relaunch_and_row_reuse(client) -> None:
    import src.DashboardAnalytic as app_module

    job_id = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={'data': [], 'voice': [], 'speech': []},
        dataset_names={'data': [], 'voice': [], 'speech': []}, template_name='NSA Slide Template', created_by='admin',
    )
    app_module.repository.update_report_chart_job(
        job_id, status='ready', progress=100, chart_count=2, generation='2026-09-03_12-00-00', finished=True,
    )

    ready_job = app_module.repository.get_report_chart_job(job_id)
    assert ready_job is not None
    assert app_module.serialize_report_chart_job(ready_job)['retry_url'] == f'/e2e-reporting/chart-jobs/{job_id}/retry'
    assert app_module.repository.retry_report_chart_job(job_id)

    relaunched_job = app_module.repository.get_report_chart_job(job_id)
    assert relaunched_job is not None
    assert relaunched_job['status'] == 'queued'
    assert relaunched_job['generation'] is None


def test_workspace_management_lists_restricted_workspaces_without_enabling_actions(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    restricted = app_module.workspace_registry.create('Restricted workspace')

    page = client.get('/workspace')
    assert page.status_code == 200
    assert f'value="{restricted.id}" data-workspace-name="Restricted workspace" data-workspace-access="false" disabled' in page.text
    assert 'Restricted workspace (' in page.text
    assert 'workspace-no-access-row' in page.text
    assert 'No access' in page.text

    assert client.post('/workspace/select', data={'workspace_id': restricted.id}, follow_redirects=False).status_code == 303
    assert client.post('/workspace/duplicate', data={'workspace_id': restricted.id}, follow_redirects=False).status_code == 403
    assert client.post('/workspace/delete', data={'workspace_id': restricted.id}, follow_redirects=False).status_code == 403


def test_global_background_tasks_groups_active_and_other_workspaces(client) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.repository import Repository

    login_super(client)
    active = app_module.active_workspace
    assert active is not None
    other = app_module.workspace_registry.create('Background workspace')
    other_repository = Repository(
        other.database_path,
        global_db_path=app_module.repository.global_db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    other_repository.initialize()
    with app_module.repository.connection() as connection:
        connection.execute(
            """INSERT INTO generated_jobs
               (job_type, technology, scope, template_name, created_by, status, progress)
               VALUES ('report', 'nsa', 'single', 'Active Template', 'admin', 'processing', 42)"""
        )
    with other_repository.connection() as connection:
        connection.execute(
            """INSERT INTO generated_jobs
               (job_type, technology, scope, template_name, created_by, status, progress)
               VALUES ('chart_set', 'nsa', 'single', 'Other Template', 'admin', 'processing', 67)"""
        )

    response = client.get('/api/background-tasks')

    assert response.status_code == 200
    groups = {group['workspace_id']: group for group in response.json()['groups']}
    assert groups[active.id]['is_active'] is True
    assert groups[active.id]['tasks'][0]['progress'] == 42
    assert 'Active Template' in groups[active.id]['tasks'][0]['label']
    assert groups[other.id]['workspace_name'] == 'Background workspace'
    assert groups[other.id]['is_active'] is False
    assert groups[other.id]['tasks'][0]['progress'] == 67
    assert 'Other Template' in groups[other.id]['tasks'][0]['label']

    page = client.get('/workspace')
    assert 'id="background-task-panels"' in page.text
    assert 'data-background-task-dock="active"' in page.text
    assert 'data-background-task-dock="other"' in page.text
    app_css = (Path(__file__).parents[1] / 'src/web_interface/static/css/app.css').read_text(encoding='utf-8')
    app_script = (Path(__file__).parents[1] / 'src/web_interface/static/js/app.js').read_text(encoding='utf-8')
    assert '.background-task-panel { position: relative; pointer-events: auto; flex: 0 0 auto; display: flex; flex-direction: column;' in app_css
    assert '.background-task-panel-header { flex: 0 0 auto;' in app_css
    assert '.background-task-count { flex: 0 0 auto;' in app_css
    assert '.background-task-list { min-height: 0; display: grid;' in app_css
    assert 'overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; touch-action: pan-y;' in app_css
    assert "!event.target.closest('.background-task-panel-header')" in app_script
    assert "taskCount.textContent = `${tasks.length} task${tasks.length === 1 ? '' : 's'}`;" in app_script
    assert 'const leftBatch = left.task.queue_batch_priority === true;' in app_script
    assert 'if (leftBatch) return Number(right.task.dataset_id) - Number(left.task.dataset_id);' in app_script
    assert 'return leftTime - rightTime;' in app_script
    assert "if (panelKey && list) panelScrollPositions.set(panelKey, list.scrollTop);" in app_script
    assert "list.dataset.restoreScrollTop = String(panelScrollPositions.get(panelStateKey) || 0);" in app_script
    assert 'const restoredScrollTop = Number(list.dataset.restoreScrollTop) || 0;' in app_script
    assert 'list.replaceChildren(...replacementList.childNodes);' in app_script
    assert "if (list.dataset.restoringScroll === 'true') return;" in app_script
    assert 'const preservedScrollTop = panelScrollPositions.get(panelKey) ?? list.scrollTop;' in app_script
    assert 'window.requestAnimationFrame(() => {' in app_script

    with app_module.repository.connection() as connection:
        connection.execute("UPDATE generated_jobs SET status = 'ready', progress = 100")
    with other_repository.connection() as connection:
        connection.execute("UPDATE generated_jobs SET status = 'ready', progress = 100")
    completed_groups = {
        group['workspace_id']: group for group in client.get('/api/background-tasks').json()['groups']
    }
    assert not any(
        task['id'].startswith('generated:')
        for workspace_id in (active.id, other.id)
        for task in completed_groups.get(workspace_id, {}).get('tasks', [])
    )


def test_background_task_poll_closes_workspace_database_connection(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    real_connect = app_module.sqlite3.connect
    closed_connections = []
    connection_calls = []

    class TrackedConnection:
        def __init__(self, connection):
            object.__setattr__(self, '_connection', connection)

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def __setattr__(self, name, value):
            setattr(self._connection, name, value)

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return self._connection.__exit__(exc_type, exc_value, traceback)

        def close(self):
            self._connection.close()
            closed_connections.append(True)

    def tracked_connect(*args, **kwargs):
        connection_calls.append((args, kwargs))
        return TrackedConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(app_module.sqlite3, 'connect', tracked_connect)

    app_module._workspace_background_tasks(app_module.active_workspace)

    assert closed_connections == [True]
    read_only_calls = [call for call in connection_calls if str(call[0][0]).startswith('file:')]
    assert read_only_calls
    assert read_only_calls[0][0][0].endswith('?mode=ro')
    assert read_only_calls[0][1]['uri'] is True


def test_dataset_background_task_reports_running_and_completed_duration(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    source_path = app_module.settings.input_dir / 'timed-background-dataset.csv'
    source_path.write_bytes(b'market,score\nES,91\n')
    dataset_id, _ = app_module.repository.add_dataset(source_path.name, str(source_path), 'admin')
    finished_at = app_module.datetime.now(app_module.timezone.utc)
    started_at = finished_at - app_module.timedelta(seconds=65)
    app_module.repository.update_dataset_profile(
        dataset_id,
        status='processing',
        progress=45,
        processing_started_at=started_at.isoformat(),
        processed_at=None,
    )

    running = None
    for _attempt in range(20):
        tasks = app_module._workspace_background_tasks(workspace)
        running = next((
            task for task in tasks
            if task['id'] == f'dataset:{workspace.id}:{dataset_id}'
        ), None)
        if running:
            break
        time.sleep(0.01)
    assert running is not None
    assert running['detail'] == 'Reading and normalizing source data'
    assert running['progress'] == 45
    assert running['duration_seconds'] >= 65

    app_module.repository.update_dataset_profile(
        dataset_id,
        status='ready',
        progress=100,
        processed_at=finished_at.isoformat(),
    )
    completed = None
    for _attempt in range(20):
        tasks = app_module._workspace_background_tasks(workspace)
        completed = next((
            task for task in tasks
            if task['id'] == f'dataset:{workspace.id}:{dataset_id}'
        ), None)
        if completed:
            break
        time.sleep(0.01)
    assert completed is not None
    assert completed['detail'] == 'Completed'
    assert completed['progress'] == 100
    assert completed['duration_seconds'] == 65
    assert 'stop_url' not in completed


def test_every_global_background_task_exposes_execution_timing(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    started_at = time.time() - 12
    with app_module.MANUAL_BACKUP_JOBS_LOCK:
        app_module.MANUAL_BACKUP_JOBS['timed-task'] = {
            'id': 'timed-task', 'owner': 'admin', 'status': 'processing',
            'message': 'Testing task timing', 'progress': 40,
            'created_at': started_at - 30, 'started_at': started_at,
        }
    try:
        tasks = app_module._global_background_tasks(next(iter(app_module.SESSIONS.values())), set())
    finally:
        with app_module.MANUAL_BACKUP_JOBS_LOCK:
            app_module.MANUAL_BACKUP_JOBS.pop('timed-task', None)

    task = next(item for item in tasks if item['id'] == 'manual-backup:timed-task')
    assert task['started_at'] == started_at
    assert task['duration_seconds'] >= 12


def test_queued_background_task_reports_queue_age_without_execution_duration(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    queued_at = time.time() - 420
    with app_module.MANUAL_BACKUP_JOBS_LOCK:
        app_module.MANUAL_BACKUP_JOBS['queued-timing-task'] = {
            'id': 'queued-timing-task', 'owner': 'admin', 'status': 'queued',
            'message': 'Waiting to create backup', 'progress': 0, 'created_at': queued_at,
        }
    try:
        tasks = app_module._global_background_tasks(next(iter(app_module.SESSIONS.values())), set())
    finally:
        with app_module.MANUAL_BACKUP_JOBS_LOCK:
            app_module.MANUAL_BACKUP_JOBS.pop('queued-timing-task', None)

    task = next(item for item in tasks if item['id'] == 'manual-backup:queued-timing-task')
    assert task['status'] == 'queued'
    assert task['queued_at'] == queued_at
    assert task['started_at'] is None
    assert task['duration_seconds'] is None


def test_reprocessed_dataset_queue_age_uses_current_queue_transition(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    source_path = app_module.settings.input_dir / 'requeued-background-dataset.csv'
    source_path.write_bytes(b'market,score\nES,91\n')
    dataset_id, _ = app_module.repository.add_dataset(source_path.name, str(source_path), 'admin')
    old_upload = (app_module.datetime.now().astimezone() - app_module.timedelta(days=3)).isoformat()
    with app_module.repository.connection() as connection:
        connection.execute('UPDATE datasets SET uploaded_at = ? WHERE id = ?', (old_upload, dataset_id))
    queued_after = time.time() - 2
    queued_at = app_module.datetime.now().astimezone().isoformat()
    app_module.repository.update_dataset_profile(
        dataset_id, status='queued', progress=0, processing_queued_at=queued_at,
        processing_started_at=None, processed_at=None,
    )
    app_module.repository.update_dataset_profile(
        dataset_id, status='processing', progress=42,
        processing_started_at=app_module.datetime.now().astimezone().isoformat(),
    )

    task = next(
        item for item in app_module._workspace_background_tasks(workspace)
        if item['id'] == f'dataset:{workspace.id}:{dataset_id}'
    )

    assert task['queued_at'] >= queued_after
    assert task['queued_at'] > app_module.parse_dataset_timestamp(old_upload).timestamp()
    assert task['queued_at'] == app_module.parse_dataset_timestamp(queued_at).timestamp()


def test_workspace_dataset_upload_uses_non_blocking_progress_card(client) -> None:
    login(client)

    page = client.get('/workspace')

    assert page.status_code == 200
    assert 'data-background-upload' in page.text
    assert "new XMLHttpRequest()" in page.text
    assert "dashboard-analytic:background-task" in page.text
    assert 'cancel: () => request.abort()' in page.text
    assert "detail: 'Uploading files', progress: uploadProgress" in page.text
    assert 'if (progress !== null) uploadProgress = progress;' in page.text
    assert "request.addEventListener('abort'" in page.text
    assert 'data-loading-label="Uploading datasets"' not in page.text

    app_script = (Path(__file__).parents[1] / 'src/web_interface/static/js/app.js').read_text(encoding='utf-8')
    assert 'formatQueuedAge' in app_script
    assert 'const minimizedPanels = new Map();' in app_script
    assert "typeof task?.cancel === 'function'" in app_script
    assert 'await task.cancel();' in app_script
    assert "const minimizedKey = `dashboard-analytic:background-task-panel:${group.workspace_id}:minimized`;" in app_script
    assert "localStorage.getItem(minimizedKey) === 'true'" in app_script
    assert 'localStorage.setItem(minimizedKey, String(value))' in app_script
    assert 'const locallyStoppedTaskIds = new Set();' in app_script
    assert 'for (const task of stoppableTasks)' in app_script
    assert 'Promise.allSettled(stoppableTasks.map(requestTaskStop))' not in app_script
    assert 'Background tasks stopped' in app_script

    upload = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('background-upload.csv', BytesIO(b'market,score\nES,91\n'), 'text/csv')},
        headers={'Accept': 'application/json'},
    )
    assert upload.status_code == 202
    assert upload.json() == {
        'dataset_ids': [1], 'redirect_url': '/workspace?dataset_id=1', 'status': 'queued',
    }


def test_background_task_stop_endpoint_stops_accessible_workspace_work(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    source_path = app_module.settings.input_dir / 'stoppable-background-dataset.csv'
    source_path.write_bytes(b'market,period,score\nES,2026-Q1,91\n')
    dataset_id, _ = app_module.repository.add_dataset(source_path.name, str(source_path), 'admin')
    app_module.repository.update_dataset_profile(dataset_id, status='queued', progress=42)

    response = client.post(
        f'/api/background-tasks/{workspace.id}/stop', data={'task_id': f'dataset:{dataset_id}'},
    )

    assert response.status_code == 200
    assert app_module.repository.get_dataset(dataset_id)['status'] == 'stopped'
    app_module.process_dataset(
        dataset_id, source_path, 'admin', task_repository=app_module.repository, workspace=workspace,
    )
    assert app_module.repository.get_dataset(dataset_id)['status'] == 'stopped'

    chart_job_id = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={}, dataset_names={},
        template_name='Stop task test', created_by='admin', generate_tooltips=True,
    )
    generated_response = client.post(
        f'/api/background-tasks/{workspace.id}/stop', data={'task_id': f'generated:{chart_job_id}'},
    )
    assert generated_response.status_code == 200
    assert app_module.repository.get_report_chart_job(chart_job_id)['status'] == 'stopped'

    with app_module.AUTO_CALCULATED_FIELD_JOBS_LOCK:
        app_module.AUTO_CALCULATED_FIELD_JOBS['stoppable-auto-fields'] = {
            'id': 'stoppable-auto-fields', 'workspace_id': workspace.id, 'status': 'processing',
        }
    auto_response = client.post(
        f'/api/background-tasks/{workspace.id}/stop', data={'task_id': 'auto-fields:stoppable-auto-fields'},
    )
    assert auto_response.status_code == 200
    with app_module.AUTO_CALCULATED_FIELD_JOBS_LOCK:
        assert app_module.AUTO_CALCULATED_FIELD_JOBS['stoppable-auto-fields']['cancel_requested'] is True
        app_module.AUTO_CALCULATED_FIELD_JOBS.pop('stoppable-auto-fields')


def test_orphaned_auto_field_materialization_can_be_stopped_from_background_panel(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    monkeypatch.setattr(app_module, 'AUTO_CALCULATED_FIELD_JOBS', {})
    monkeypatch.setattr(app_module, 'read_persisted_auto_field_progress', lambda _workspace_id: {})
    workspace_repository = app_module.Repository(
        workspace.database_path,
        global_db_path=app_module.repository.global_db_path,
        workspace_registry_db_path=app_module.workspace_registry.registry_path,
    )
    workspace_repository.set_workspace_state('calculated_dimensions_need_materialization', 'processing')

    task = next(
        task for task in app_module._workspace_background_tasks(workspace)
        if task['id'] == f'auto-fields-state:{workspace.id}'
    )
    assert task['stop_task_id'] == f'auto-fields-state:{workspace.id}'
    assert task['stop_url'] == f'/api/background-tasks/{workspace.id}/stop'

    response = client.post(task['stop_url'], data={'task_id': task['stop_task_id']})

    assert response.status_code == 200
    assert workspace_repository.get_workspace_state('calculated_dimensions_need_materialization') == 'stopped'
    remaining = app_module._workspace_background_tasks(workspace)
    assert all(
        candidate['id'] != f'auto-fields-state:{workspace.id}'
        for candidate in remaining
    )


def test_incoming_transfer_cannot_stop_after_import_begins(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    offer_id = 'incoming-stop-test'
    monkeypatch.setattr(app_module, '_save_transfer_offer', lambda _offer: None)
    monkeypatch.setattr(app_module, '_refresh_persisted_transfer_offers', lambda: None)
    monkeypatch.setattr(app_module, 'TRANSFER_OFFERS', {
        offer_id: {
            'id': offer_id, 'status': 'importing', 'phase': 'validating', 'progress': 0,
            'content': 'Auto-calculated Fields', 'destination_workspace_ids': [workspace.id],
            'created_at': 1,
        },
    })
    monkeypatch.setattr(app_module, 'AUTO_CALCULATED_FIELD_JOBS', {
        'child-materialization': {
            'id': 'child-materialization', 'workspace_id': workspace.id, 'status': 'processing',
            'parent_task_id': f'incoming-transfer:{offer_id}', 'created_at': 2,
        },
    })

    groups = client.get('/api/background-tasks').json()['groups']
    task = next(
        task for group in groups for task in group['tasks']
        if task['id'] == f'incoming-transfer:{offer_id}'
    )
    assert 'stop_url' not in task

    response = client.post('/api/server-background-tasks/stop', data={'task_id': f'incoming-transfer:{offer_id}'})

    assert response.status_code == 409
    assert not app_module.TRANSFER_OFFERS[offer_id].get('cancel_requested')
    assert not app_module.AUTO_CALCULATED_FIELD_JOBS['child-materialization'].get('cancel_requested')


def test_import_can_stop_while_queued_but_not_while_replacing_data(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    monkeypatch.setattr(app_module, 'IMPORT_JOBS', {
        'pending-import': {
            'id': 'pending-import', 'owner': 'admin', 'status': 'queued',
            'destination_workspace_ids': [workspace.id], 'created_at': time.time(),
        },
        'active-import': {
            'id': 'active-import', 'owner': 'admin', 'status': 'processing',
            'destination_workspace_ids': [workspace.id], 'created_at': time.time(),
        },
    })

    tasks = [
        task for group in client.get('/api/background-tasks').json()['groups']
        for task in group['tasks'] if task['id'].startswith('import:')
    ]
    assert next(task for task in tasks if task['id'] == 'import:pending-import')['stop_task_id'] == 'import:pending-import'
    assert 'stop_task_id' not in next(task for task in tasks if task['id'] == 'import:active-import')

    active_response = client.post(
        f'/api/background-tasks/{workspace.id}/stop', data={'task_id': 'import:active-import'},
    )
    queued_response = client.post(
        f'/api/background-tasks/{workspace.id}/stop', data={'task_id': 'import:pending-import'},
    )

    assert active_response.status_code == 409
    assert queued_response.status_code == 200
    assert not app_module.IMPORT_JOBS['active-import'].get('cancel_requested')
    assert app_module.IMPORT_JOBS['pending-import']['cancel_requested'] is True


def test_persisted_materialization_stop_is_observed_across_workers(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    job_id = 'job-owned-by-another-worker'
    created_at = time.time() - 1
    monkeypatch.setattr(app_module, 'AUTO_CALCULATED_FIELD_JOBS', {
        job_id: {
            'id': job_id, 'workspace_id': workspace.id, 'status': 'processing',
            'created_at': created_at,
        },
    })
    app_module.request_persisted_auto_field_stop(workspace.id, job_id)
    app_module.persist_auto_field_progress({
        'id': job_id, 'workspace_id': workspace.id, 'status': 'processing',
        'completed': 250, 'total': 1_000, 'message': 'Table 1 of 4 · 250 of 1,000 row operations',
        'created_at': created_at,
    })

    assert app_module.any_persisted_auto_field_stop_requested(workspace.id) is True
    with pytest.raises(app_module.ProcessingStopped):
        app_module.ensure_auto_calculated_field_job_not_stopped(job_id)

    monkeypatch.setattr(app_module, 'AUTO_CALCULATED_FIELD_JOBS', {})
    app_module.repository.set_workspace_state('calculated_dimensions_need_materialization', 'processing')
    status = client.get('/api/workspace/auto-calculated-fields/materialization').json()
    assert status['status'] == 'processing'
    assert status['cancel_requested'] is True
    assert status['completed'] == 250
    assert status['total'] == 1_000
    assert status['message'] == 'Table 1 of 4 · 250 of 1,000 row operations'


def test_interactive_template_save_fails_fast_while_workspace_writer_is_busy(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    template = app_module.report_catalogue_options('nsa')[0]

    class BusyWorkspaceLock:
        def acquire(self, timeout=None):
            return False

        def release(self):
            raise AssertionError('An unacquired lock must not be released.')

    monkeypatch.setattr(app_module, 'workspace_write_lock', lambda _path: BusyWorkspaceLock())
    response = client.post(
        f'/admin/report-templates/nsa/{quote(template["identifier"], safe="")}/save',
        data={'catalogue_content': bytes(template['content']).decode('utf-8')},
        headers={'accept': 'application/json'},
    )

    assert response.status_code == 409
    assert 'workspace is busy updating CDR tables' in response.json()['detail']


def test_dashboard_interruption_succeeds_when_its_audit_log_is_locked(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    monkeypatch.setattr(app_module, 'e2e_dashboard_stop_task', lambda _database_path, _task_id: True)
    monkeypatch.setattr(app_module.Repository, 'try_add_log', lambda *_args, **_kwargs: False)

    response = client.post(
        f'/api/background-tasks/{workspace.id}/stop',
        data={'task_id': 'dashboard-prepare:dashboard-prefetch:locked-audit'},
    )

    assert response.status_code == 200
    assert response.json() == {
        'stopping': 'dashboard-prepare:dashboard-prefetch:locked-audit',
    }


def test_queued_import_continues_after_its_workspace_is_closed(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    source_path = app_module.settings.input_dir / 'continue-after-close.csv'
    source_path.write_bytes(b'market,period,score\nES,2026-Q1,91\n')
    dataset_id, _ = app_module.repository.add_dataset(source_path.name, str(source_path), 'admin')
    app_module.repository.update_dataset_profile(dataset_id, dataset_kind='data')
    workspace_database = app_module.repository.db_path

    tasks = BackgroundTasks()
    app_module.enqueue_dataset_processing(tasks, dataset_id, source_path, 'admin')
    queued = app_module.repository.get_dataset(dataset_id)
    assert json.loads(queued['processing_options_json']) == {
        'vodafone_mapping_dataset_id': None,
        'three_mapping_dataset_id': None,
    }
    closed = client.post('/workspace/close', data={'workspace_id': 'default'}, follow_redirects=False)
    assert closed.status_code == 303
    assert app_module.active_workspace is None

    queued_task = tasks.tasks[0]
    queued_task.func(*queued_task.args, **queued_task.kwargs)

    completed = app_module.Repository(workspace_database).get_dataset(dataset_id)
    assert completed is not None
    assert completed['status'] == 'ready'


def test_cdr_import_finishes_before_its_combined_table_recreation(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    source_path = app_module.settings.input_dir / 'separate-combined-recreation.csv'
    source_path.write_bytes(b'market,period,score\nES,2026-Q1,91\n')
    dataset_id, _ = app_module.repository.add_dataset(source_path.name, str(source_path), 'admin')
    app_module.repository.update_dataset_profile(dataset_id, dataset_kind='data')
    workspace = app_module.active_workspace
    assert workspace is not None
    calls = []

    def capture_combined_recreation(job_workspace, kind, username, *, background=True):
        dataset = app_module.Repository(job_workspace.database_path).get_dataset(dataset_id)
        calls.append((kind, username, background, dataset['status'], dataset['progress']))
        return {}

    monkeypatch.setattr(app_module, 'start_combined_cdr_recreation_job', capture_combined_recreation)

    app_module.process_dataset(
        dataset_id, source_path, 'admin', task_repository=app_module.repository, workspace=workspace,
    )

    assert calls == [('data', 'admin', True, 'ready', 100)]


def test_workspace_import_replaces_an_open_workspace_and_removes_old_files(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    original = app_module.active_workspace
    assert original is not None
    old_output = original.output_dir / 'obsolete-report.txt'
    old_output.parent.mkdir(parents=True, exist_ok=True)
    old_output.write_text('old workspace output', encoding='utf-8')

    payload = tmp_path / 'workspace-import'
    (payload / 'input').mkdir(parents=True)
    (payload / 'input' / 'new-data.csv').write_text('value\n1\n', encoding='utf-8')
    archived_template = payload / 'report-templates' / 'library' / 'nsa' / 'Archived.csv'
    archived_template.parent.mkdir(parents=True)
    archived_template.write_bytes(b'legacy template payload')
    imported_report = payload / 'output' / 'reports' / 'imported.pptx'
    imported_report.parent.mkdir(parents=True)
    imported_report.write_bytes(b'imported report')
    source_input = '/exported/workspace/input'
    source_output = '/exported/workspace/output'
    with sqlite3.connect(payload / 'database.sqlite') as connection:
        connection.execute('CREATE TABLE datasets (stored_path TEXT)')
        connection.execute('INSERT INTO datasets (stored_path) VALUES (?)', (f'{source_input}/new-data.csv',))
        connection.execute('CREATE TABLE generated_jobs (id INTEGER PRIMARY KEY, job_type TEXT, output_file TEXT, output_path TEXT)')
        connection.execute(
            "INSERT INTO generated_jobs (job_type, output_file, output_path) VALUES ('report', 'imported.pptx', ?)",
            (f'{source_output}/reports/imported.pptx',),
        )

    imported = app_module.import_workspace_archive(
        payload,
        {'name': original.name, 'source_input_dir': source_input, 'source_output_dir': source_output},
        replace_existing=True,
    )

    assert imported.id == original.id
    assert imported.name == original.name
    assert app_module.active_workspace is None
    assert not old_output.exists()
    assert (imported.input_dir / 'new-data.csv').read_text(encoding='utf-8') == 'value\n1\n'
    with sqlite3.connect(imported.database_path) as connection:
        stored_path = connection.execute('SELECT stored_path FROM datasets').fetchone()[0]
        report_path = connection.execute('SELECT output_path FROM generated_jobs').fetchone()[0]
    assert stored_path == str(imported.input_dir / 'new-data.csv')
    assert report_path == str(imported.export_dir / 'imported.pptx')
    assert app_module.repository.user_has_workspace_access('admin', imported.id)
    assert all(' - Importing ' not in workspace.name for workspace in app_module.workspace_registry.list())
    assert not imported.slides_templates_dir.exists()
    assert not (imported.database_path.parent / 'slides-templates').exists()


def test_workspace_import_keeps_chart_sets_visible_in_reporting(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    source = app_module.active_workspace
    assert source is not None
    payload = tmp_path / 'workspace-import-chart-set'
    payload.mkdir()
    shutil.copy2(source.database_path, payload / 'database.sqlite')
    generation = '20260910-120000'
    chart_directory = payload / 'output' / 'charts' / generation
    chart_directory.mkdir(parents=True)
    (chart_directory / 'chart-1.png').write_bytes(b'chart')
    (chart_directory / 'manifest.json').write_text(json.dumps({
        'generation': generation,
        'template': 'Imported template',
        'technology': 'NSA',
        'scope': 'single',
        'dataset_counts': {'data': 1, 'voice': 0, 'speech': 0},
        'generated_at': '2026-09-10T12:00:00+00:00',
        'charts': [{'file': 'chart-1.png', 'slide': 1, 'title': 'Imported chart', 'source': 'Data', 'chart_type': 'Bar'}],
    }), encoding='utf-8')

    imported = app_module.import_workspace_archive(payload, {'name': 'Imported chart workspace'})
    app_module.activate_workspace(imported.id)

    reporting = client.get('/reporting')
    assert reporting.status_code == 200
    assert 'Imported template' in reporting.text
    assert generation in reporting.text


def test_delete_all_reports_removes_orphaned_output_directories(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    reports_root = Path(app_module.settings.output_dir) / 'reports'
    orphaned = reports_root / 'report-without-job' / 'report-charts'
    orphaned.mkdir(parents=True, exist_ok=True)
    (orphaned / 'chart-1.png').write_bytes(b'old chart')

    response = client.post('/reporting/jobs/delete-all')

    assert response.status_code == 202
    job_id = response.json()['job_id']
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status_response = client.get(f'/api/e2e-reporting/bulk-deletions/{job_id}')
        assert status_response.status_code == 200
        if status_response.json()['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert status_response.json()['status'] == 'ready'
    assert reports_root.is_dir()
    assert list(reports_root.iterdir()) == []


def test_admin_panel_is_available_for_admin(client) -> None:
    login(client)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin panel" in response.text
    assert '<span class="table-input user-role-locked" aria-label="Role for super: super-admin"' in response.text
    assert '<span class="user-role-full-label">super-admin</span>' in response.text
    assert '<span class="user-role-compact-label" aria-hidden="true">super</span>' in response.text
    assert 'type="text" value="super-admin" aria-label="Role for super"' not in response.text
    assert 'name="username" value="super" form="user-update-1" autocomplete="off" readonly data-user-autofill-guard required disabled' in response.text
    assert 'name="password" value="" placeholder="••••••••" autocomplete="off" spellcheck="false" readonly form="user-update-1" data-user-password data-user-autofill-guard' in response.text
    assert 'data-user-password-toggle' in response.text
    assert 'data-create-user-password-toggle' in response.text
    assert 'protectAdminFields' in response.text
    assert '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.2 12' in response.text
    assert 'Keep current' not in response.text
    assert 'restoreUsersFromServerMarkup' in response.text
    assert 'form="user-update-1" disabled title="Only super-admins can modify super-admin accounts">Save</button>' not in response.text


def test_admin_operator_mapping_panel_groups_and_edits_aliases(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    initial_mappings = app_module.repository.list_operator_mappings()
    assert initial_mappings['vodafone uk'] == 'VF'
    assert initial_mappings['three uk'] == '3'
    assert [group['canonical'] for group in app_module.repository.list_operator_mapping_groups()[:4]] == [
        'VF', '3', 'EE', 'O2',
    ]
    assert [group['color'] for group in app_module.repository.list_operator_mapping_groups()[:4]] == [
        '#E15759', '#F28E2B', '#76B7B2', '#4E79A7',
    ]
    app_module.repository.replace_operator_mapping_group(
        None, 'Legacy Carrier', ['Legacy A', 'Legacy B'],
    )
    page = client.get('/admin')
    assert page.status_code == 200
    assert 'data-panel-state-key="admin:operator-mappings"' in page.text
    assert '<h2>Operator Mappings</h2>' in page.text
    assert '<h2>Vendor Mappings</h2>' in page.text
    assert page.text.index('<h2>Report Templates Management</h2>') < page.text.index('<h2>Operator Mappings</h2>')
    assert 'value="VF"' in page.text
    assert 'value="Legacy Carrier"' in page.text
    assert 'Legacy A\nLegacy B' in page.text
    assert 'Add operator mapping' not in page.text
    assert 'data-add-operator-mapping' not in page.text

    created = client.post('/admin/operator-mappings/save', data={
        'canonical_value': 'Example Mobile',
        'aliases': 'Example\nEX; Example Telecom',
    }, follow_redirects=False)
    assert created.status_code == 303
    assert app_module.repository.list_operator_mappings()['example'] == 'Example Mobile'
    assert app_module.repository.list_operator_mappings()['ex'] == 'Example Mobile'
    assert app_module.repository.list_operator_mappings()['example telecom'] == 'Example Mobile'
    assert app_module.repository.list_operator_mappings()['example mobile'] == 'Example Mobile'

    updated = client.post('/admin/operator-mappings/save', data={
        'original_canonical': 'Example Mobile',
        'canonical_value': 'Example Wireless',
        'aliases': 'Example\nEW',
    }, follow_redirects=False)
    assert updated.status_code == 303
    mappings = app_module.repository.list_operator_mappings()
    assert mappings['example'] == 'Example Wireless'
    assert mappings['ew'] == 'Example Wireless'
    assert mappings['example wireless'] == 'Example Wireless'
    assert 'ex' not in mappings
    assert 'example mobile' not in mappings

    deleted = client.post('/admin/operator-mappings/delete', data={
        'canonical_value': 'Example Wireless',
    }, follow_redirects=False)
    assert deleted.status_code == 303
    assert not any(value == 'Example Wireless' for value in app_module.repository.list_operator_mappings().values())


def test_admin_vendor_mappings_support_aliases_colours_and_reordering(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    groups = app_module.repository.list_vendor_mapping_groups()
    assert [group['canonical'] for group in groups[:4]] == ['Ericsson', 'Huawei', 'Samsung', 'NSN']
    assert [group['color'] for group in groups[:4]] == ['#2E8B57', '#E15759', '#7B3FB5', '#4E79A7']

    created = client.post('/admin/vendor-mappings/save', data={
        'canonical_value': 'Nokia', 'aliases': 'Nokia Networks', 'color': '#123456',
    }, follow_redirects=False)
    assert created.status_code == 303
    assert app_module.repository.list_vendor_mappings()['nokia networks'] == 'Nokia'
    assert app_module.repository.list_vendor_mapping_groups()[-1]['color'] == '#123456'

    moved = client.post('/admin/vendor-mappings/move', data={
        'canonical_value': 'Nokia', 'direction': 'up',
    }, follow_redirects=False)
    assert moved.status_code == 303
    reordered = app_module.repository.list_vendor_mapping_groups()
    assert [group['canonical'] for group in reordered][-2:] == ['Nokia', '(blank)']

    page = client.get('/admin')
    assert 'data-panel-state-key="admin:vendor-mappings"' in page.text
    assert 'name="color" value="#123456"' in page.text
    assert 'action="/admin/vendor-mappings/move"' in page.text
    script = app_module.PROJECT_ROOT.joinpath('src/web_interface/static/js/app.js').read_text(encoding='utf-8')
    assert 'async function submitChartMappingForm(form)' in script
    assert 'currentBody.replaceWith(freshBody);' in script
    assert 'top: scrollTop, left: scrollLeft, behavior: \'auto\'' in script


def test_canonical_mapping_renames_update_all_templates_and_dashboards_exactly(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.replace_operator_mapping_group(
        None, 'VF_SA', ['VF SA UK'], '#8000FF',
    )
    app_module.repository.replace_vendor_mapping_group(None, 'SA', [], '#ABCDEF')
    entry = app_module.CatalogEntry(
        slide=1,
        slide_title='VF vs VF_SA',
        slide_subtitle='',
        layout='Title and 1 column + Comments',
        chart_title='VF and VF_SA by Ericsson',
        cdr_source='CDR-Data',
        kpi='Mean_Data_Rate',
        chart_type='CDF Line',
        filters='Operator IN (VF, VF_SA); Vendor IN (VF_Ericsson, VF_SA_Ericsson, Ericsson)',
        grouping_rows='Operator',
        grouping_columns='',
        legend='Operator',
    )
    app_module.repository.add_report_template(
        'nsa', 'Mapping references', app_module.catalogue_csv([entry]),
    )
    app_module.repository.set_workspace_state('e2e_dashboards_v2', json.dumps({
        'mapping-dashboard': {
            'name': 'VF vs VF_SA',
            'template': 'VF',
            'filters': {
                'Operator': ['VF', 'VF_SA'],
                'Vendor': ['VF_Ericsson', 'VF_SA_Ericsson', 'Ericsson'],
            },
        },
    }))

    operator_rename = client.post('/admin/operator-mappings/save', data={
        'original_canonical': 'VF',
        'canonical_value': 'VF_UK',
        'aliases': 'Vodafone\nVodafone UK\nVFUK',
        'color': '#E15759',
    }, follow_redirects=False)

    assert operator_rename.status_code == 303
    renamed_entry = app_module.parse_catalog_csv(
        app_module.repository.report_template_content('nsa', 'Mapping references'), 'nsa',
        validate_filters=False,
    )[0]
    assert renamed_entry.slide_title == 'VF_UK vs VF_SA'
    assert renamed_entry.chart_title == 'VF_UK and VF_SA by Ericsson'
    assert renamed_entry.filters == (
        'Operator IN (VF_UK, VF_SA); '
        'Vendor IN (VF_UK_Ericsson, VF_SA_Ericsson, Ericsson)'
    )
    dashboard = json.loads(app_module.repository.get_workspace_state('e2e_dashboards_v2'))['mapping-dashboard']
    assert dashboard['name'] == 'VF_UK vs VF_SA'
    assert dashboard['template'] == 'VF'
    assert dashboard['filters']['Operator'] == ['VF_UK', 'VF_SA']
    assert dashboard['filters']['Vendor'] == ['VF_UK_Ericsson', 'VF_SA_Ericsson', 'Ericsson']

    vendor_rename = client.post('/admin/vendor-mappings/save', data={
        'original_canonical': 'Ericsson',
        'canonical_value': 'ERI',
        'aliases': '',
        'color': '#2E8B57',
    }, follow_redirects=False)

    assert vendor_rename.status_code == 303
    renamed_entry = app_module.parse_catalog_csv(
        app_module.repository.report_template_content('nsa', 'Mapping references'), 'nsa',
        validate_filters=False,
    )[0]
    assert renamed_entry.chart_title == 'VF_UK and VF_SA by ERI'
    assert renamed_entry.filters == (
        'Operator IN (VF_UK, VF_SA); '
        'Vendor IN (VF_UK_ERI, VF_SA_ERI, ERI)'
    )
    dashboard = json.loads(app_module.repository.get_workspace_state('e2e_dashboards_v2'))['mapping-dashboard']
    assert dashboard['filters']['Vendor'] == ['VF_UK_ERI', 'VF_SA_ERI', 'ERI']

    duplicate = client.post('/admin/operator-mappings/save', data={
        'original_canonical': 'VF_UK', 'canonical_value': '3', 'aliases': '',
    }, follow_redirects=False)
    assert duplicate.status_code == 303
    assert 'operator_mapping_error=' in duplicate.headers['location']
    groups = app_module.repository.list_operator_mapping_groups()
    assert any(group['canonical'] == 'VF_UK' for group in groups)
    assert sum(group['canonical'] == '3' for group in groups) == 1

    duplicate_vendor = client.post('/admin/vendor-mappings/save', data={
        'original_canonical': 'ERI', 'canonical_value': 'Huawei', 'aliases': '',
    }, follow_redirects=False)
    assert duplicate_vendor.status_code == 303
    assert 'vendor_mapping_error=' in duplicate_vendor.headers['location']
    vendor_groups = app_module.repository.list_vendor_mapping_groups()
    assert any(group['canonical'] == 'ERI' for group in vendor_groups)
    assert sum(group['canonical'] == 'Huawei' for group in vendor_groups) == 1


def test_paginated_dataset_viewers_preserve_the_exact_horizontal_scroll_offset() -> None:
    import src.DashboardAnalytic as app_module

    script = app_module.PROJECT_ROOT.joinpath(
        'src/web_interface/static/js/app.js',
    ).read_text(encoding='utf-8')

    assert "columnName: anchor?.dataset.columnName || ''," in script
    assert "inset: anchor ? Math.max(0, viewportLeft - anchor.getBoundingClientRect().left) : 0," in script
    assert "tableWrap.scrollLeft = anchorContentLeft + horizontalPosition.inset;" in script
    assert "requestAnimationFrame(() => requestAnimationFrame(restoreHorizontalOffset));" in script


def test_admin_recurring_backup_settings_are_persisted(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    saved = client.post('/admin/database/backups', data={
        'enabled': 'true', 'components': ['app_database', 'report_templates'],
        'workspace_ids': ['default'],
        'recurrence': 'weekly', 'execution_time': '03:15', 'weekly_day': '4', 'monthly_day': '14', 'max_backups': '12',
        'backup_path': 'scheduled-backups',
    }, follow_redirects=False)

    assert saved.status_code == 303
    config = app_module.recurring_backup_settings()
    assert config['enabled'] is True
    assert config['components'] == ['app_database', 'report_templates']
    assert config['recurrence'] == 'weekly'
    assert config['execution_time'] == '03:15'
    assert config['weekly_day'] == 4
    assert config['monthly_day'] == 14
    assert config['max_backups'] == 12
    assert config['backup_path'].endswith('scheduled-backups')
    assert any(
        row['action'] == 'save_scheduled_backup_settings'
        for row in app_module.repository.list_logs()
    )
    page = client.get('/admin')
    assert 'Backup Protection' in page.text
    assert 'database-view-subpanel' in page.text
    assert 'Retention backups' in page.text
    assert 'Stored backups:' in page.text
    assert 'Retention backups' in page.text
    directories = client.get('/api/admin/backup-directories')
    assert directories.status_code == 200
    assert directories.json()['path']
    created_directory = client.post('/api/admin/backup-directories', data={
        'parent_path': directories.json()['path'], 'name': 'created-from-picker',
    })
    assert created_directory.status_code == 200
    assert created_directory.json()['path'].endswith('created-from-picker')


def test_scheduled_backup_records_automatic_lifecycle_in_app_logs(client, monkeypatch, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    now = datetime.now().astimezone()
    config = app_module.recurring_backup_settings() | {
        'enabled': True,
        'components': ['app_database'],
        'recurrence': 'hourly',
        'execution_time': now.strftime('%H:%M'),
        'last_run_period': '',
    }
    destination = tmp_path / 'scheduled.zip'

    def run_immediately(callback, *args):
        callback(*args)

    monkeypatch.setattr(app_module, 'recurring_backup_settings', lambda: dict(config))
    monkeypatch.setattr(app_module, 'create_recurring_database_backup', lambda *_args: destination)
    monkeypatch.setattr(app_module, 'submit_background_task', run_immediately)
    app_module.RECURRING_BACKUP_RUNNING = False

    app_module.run_recurring_backup_scheduler()

    actions = [row['action'] for row in app_module.repository.list_logs()]
    assert 'scheduled_database_backup_started' in actions
    assert 'scheduled_database_backup_completed' in actions


def test_manual_database_backup_uses_current_form_selection_without_enabling_schedule(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    captured: dict[str, object] = {}
    schedule_enabled_before = app_module.recurring_backup_settings()['enabled']

    def capture_backup(config, username):
        captured['config'] = config
        captured['username'] = username
        return {'id': 'manual-backup'}

    monkeypatch.setattr(app_module, 'start_manual_database_backup', capture_backup)
    response = client.post('/admin/database/backups/run', data={
        'components': ['app_database', 'auto_calculated_fields'],
        'workspace_ids': ['default'],
        'max_backups': '7',
        'backup_path': 'scheduled-backups/manual',
    }, headers={'X-Requested-With': 'XMLHttpRequest'}, follow_redirects=False)

    assert response.status_code == 200
    assert response.json()['job_id'] == 'manual-backup'
    config = captured['config']
    assert config['components'] == ['app_database', 'auto_calculated_fields']
    assert config['max_backups'] == 7
    assert config['backup_path'].endswith('scheduled-backups/manual')
    assert config['workspace_ids'] == ['default']
    assert app_module.recurring_backup_settings()['enabled'] is schedule_enabled_before


def test_backup_notices_render_in_backup_protection_not_database_view(client) -> None:
    login(client)

    page = client.get('/admin?database_notice=Manual+backup+started.')

    assert 'class="alert backup-notice">Manual backup started.' in page.text
    assert 'class="alert database-cleanup-notice">Manual backup started.' not in page.text


def test_backup_skips_stale_workspace_registry_entries(monkeypatch, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    def workspace(identifier: str, *, database_exists: bool):
        root = tmp_path / identifier
        database_path = root / f'{identifier}.db'
        if database_exists:
            database_path.parent.mkdir(parents=True)
            workspace_repository = app_module.Repository(database_path, app_module.repository.global_db_path)
            workspace_repository.initialize()
            workspace_repository.add_report_template(
                'nsa', f'{identifier} template', b'template', is_default=True,
            )
        templates = root / 'report-templates'
        templates.mkdir(parents=True)
        return app_module.Workspace(
            id=identifier, name=identifier.title(), database_path=database_path,
            input_dir=root / 'input', output_dir=root / 'output', export_dir=root / 'output' / 'reports',
            slides_templates_dir=templates, created_at='', last_opened_at='',
        )

    valid = workspace('current-workspace', database_exists=True)
    stale = workspace('default', database_exists=False)
    inaccessible = workspace('workspace-3', database_exists=True)
    monkeypatch.setattr(app_module.workspace_registry, 'list', lambda: [valid, stale, inaccessible])

    archive_path = app_module.create_recurring_database_backup({
        'components': ['report_templates'], 'backup_path': str(tmp_path / 'backups'), 'max_backups': 30,
        'workspace_ids': [valid.id],
    })

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read('manifest.json'))
    assert 'workspaces/Current-Workspace/report-templates/library/nsa/current-workspace template.csv' in names
    assert 'workspaces/Current-Workspace/report-templates/default/nsa/current-workspace template.csv' in names
    assert not any(name.startswith('workspaces/Default/') for name in names)
    assert not any(name.startswith('workspaces/Workspace-3/') for name in names)
    assert manifest['components'] == ['workspace_components']
    assert manifest['workspace_components'] == ['report_templates']
    assert manifest['workspaces'] == [{'id': 'current-workspace', 'name': 'Current-Workspace'}]


def test_dashboard_backup_declares_dashboard_component_for_selective_restore(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.set_workspace_state(
        app_module.DASHBOARD_STATE_KEY,
        json.dumps({'dashboard-1': {'name': 'Executive Dashboard', 'comments': {'1': 'Review'}}}),
    )

    archive_path = app_module.create_recurring_database_backup({
        'components': ['dashboards'],
        'backup_path': str(tmp_path / 'backups'),
        'max_backups': 30,
        'workspace_ids': ['default'],
    })

    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        names = archive.namelist()
    assert manifest['workspace_components'] == ['dashboards']
    assert 'workspaces/Default/dashboards/dashboards.json' in names
    assert app_module._backup_archive_components(archive_path) == ['dashboards']


def test_operator_mapping_backup_supports_selective_restore(client, tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.replace_operator_mapping_group(None, 'Backup Carrier', ['Backup Alias'])
    app_module.repository.replace_vendor_mapping_group(None, 'Backup Vendor', ['Backup Vendor Alias'], '#654321')
    archive_path = app_module.create_recurring_database_backup({
        'components': ['operator_mappings'],
        'backup_path': str(tmp_path / 'backups'),
        'max_backups': 30,
        'workspace_ids': ['default'],
    })

    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert 'workspaces/Default/operator-mappings/operator-mappings.json' in archive.namelist()
    assert manifest['workspace_components'] == ['operator_mappings']
    assert app_module._backup_archive_components(archive_path) == ['operator_mappings']

    app_module.repository.delete_operator_mapping_group('Backup Carrier')
    app_module.repository.delete_vendor_mapping_group('Backup Vendor')
    progress_steps = []
    app_module.restore_database_backup(
        archive_path, ['operator_mappings'],
        lambda message, completed, total: progress_steps.append((message, completed, total)),
    )

    assert app_module.repository.list_operator_mappings()['backup alias'] == 'Backup Carrier'
    assert progress_steps[-1][1:] == (1, 1)
    assert 'Operator Mappings restored' in progress_steps[-1][0]
    restored_vendor = next(
        group for group in app_module.repository.list_vendor_mapping_groups()
        if group['canonical'] == 'Backup Vendor'
    )
    assert app_module.repository.list_vendor_mappings()['backup vendor alias'] == 'Backup Vendor'
    assert restored_vendor['color'] == '#654321'


def test_login_and_admin_remain_available_after_closing_the_active_workspace(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.close_active_workspace()

    login_page = client.get('/login')
    assert login_page.status_code == 200

    admin = client.get('/admin')
    assert admin.status_code == 200
    assert 'Open a workspace from Workspace Management before managing its datasets.' in admin.text
    assert 'Open a workspace from Workspace Management before viewing or editing its database.' in admin.text


def test_admin_database_management_lists_and_updates_active_workspace_tables(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    client.post(
        "/admin/users",
        data={"username": "database-editor", "password": "start123", "role": "user"},
        follow_redirects=False,
    )
    app_module.repository.replace_dataset_rows(987, pd.DataFrame({"obsolete": ["row"]}))
    app_module.repository.replace_reporting_rows(987, 'data', pd.DataFrame({"Campaign": ["legacy"]}))
    with app_module.repository.connection() as conn:
        conn.execute("INSERT INTO dashboard_filter_selections (cache_key) VALUES ('database-viewer-test')")
    assert app_module.repository.dataset_rows_table_exists(987)
    admin = client.get("/admin")
    assert admin.status_code == 200
    assert "Database Management" in admin.text
    assert 'data-database-table-select' in admin.text
    assert 'Workspace: Default' in admin.text
    assert 'Clean orphaned rows' in admin.text
    assert 'value="users"' in admin.text
    assert 'value="application_state"' in admin.text
    assert 'value="report_templates"' in admin.text
    assert 'value="transfer_offers"' in admin.text
    assert 'Server transfer offers' in admin.text
    assert 'value="__workspace_registry__"' in admin.text
    assert 'Workspace registry' in admin.text
    assert '<optgroup label="Workspace Tables">' in admin.text
    assert 'value="generated_jobs"' in admin.text
    assert 'Dashboard selected rows' not in admin.text
    assert 'Generated jobs' in admin.text
    assert 'value="report_chart_jobs"' not in admin.text
    assert 'value="report_runs"' not in admin.text
    assert 'Other tables' not in admin.text
    assert app_module.repository.dataset_rows_table_exists(987)
    assert app_module.repository.database_table_page('reporting_rows_data')['total_rows'] == 1
    cleanup = client.post('/admin/database/cleanup', follow_redirects=False)
    assert cleanup.status_code == 303
    assert not app_module.repository.dataset_rows_table_exists(987)
    assert app_module.repository.database_table_page('reporting_rows_data')['total_rows'] == 0

    workspace_registry = client.get('/admin/database/table', params={'table': '__workspace_registry__', 'limit': 100})
    assert workspace_registry.status_code == 200
    workspace_payload = workspace_registry.json()
    assert any(column['name'] == 'name' for column in workspace_payload['columns'])
    assert any(row['id'] == 'default' for row in workspace_payload['rows'])
    assert all(column['primary_key'] for column in workspace_payload['columns'])

    users = client.get("/admin/database/table", params={"table": "users", "limit": 100})
    assert users.status_code == 200
    payload = users.json()
    assert any(column["name"] == "id" and column["primary_key"] for column in payload["columns"])
    editor = next(row for row in payload["rows"] if row["username"] == "database-editor")

    values = client.get(
        "/admin/database/table/values",
        params={"table": "users", "column": "username", "search": "database-editor"},
    )
    assert values.status_code == 200
    assert values.json()["values"] == ["database-editor"]

    filtered = client.post(
        "/admin/database/table/query",
        json={"table": "users", "offset": 0, "limit": 100, "filters": {"username": ["database-editor"]}},
    )
    assert filtered.status_code == 200
    assert [row["username"] for row in filtered.json()["rows"]] == ["database-editor"]
    assert filtered.json()["total_rows"] == 1
    assert filtered.json()["all_rows"] > filtered.json()["total_rows"]

    saved = client.post(
        "/admin/database/table",
        json={"table": "users", "rowid": editor["__database_rowid__"], "updates": {"active": "0"}},
    )
    assert saved.status_code == 200
    assert app_module.repository.get_user("database-editor").active is False

    protected = client.post(
        "/admin/database/table",
        json={"table": "users", "rowid": editor["__database_rowid__"], "updates": {"id": "999"}},
    )
    assert protected.status_code == 400
    assert "Primary-key values cannot be edited" in protected.json()["detail"]

    deleted = client.post(
        "/admin/database/table/delete",
        json={"table": "users", "rowid": editor["__database_rowid__"]},
    )
    assert deleted.status_code == 200
    assert app_module.repository.get_user("database-editor") is None


def test_admin_dataset_management_renames_dataset_file_and_materialised_source_labels(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    upload = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('original-cdr.csv', BytesIO(b'Campaign,LQ\nUK_Q2_SA_2026,3.8\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    before = app_module.repository.get_dataset(1)
    assert before is not None
    old_path = Path(before['stored_path'])
    app_module.repository.copy_dataset_rows_to_reporting(1, 'data', ['source_file'])

    renamed = client.post(
        '/admin/datasets/1/rename', data={'file_name': 'renamed-cdr.csv'}, follow_redirects=False,
    )
    assert renamed.status_code == 303
    after = app_module.repository.get_dataset(1)
    assert after is not None
    new_path = Path(after['stored_path'])
    assert after['file_name'] == 'renamed-cdr.csv'
    assert new_path.name == 'renamed-cdr.csv'
    assert not old_path.exists()
    assert new_path.exists()

    with app_module.repository.connection() as conn:
        dataset_source = conn.execute('SELECT DISTINCT source_file FROM "dataset_rows_1"').fetchall()
        reporting_source = conn.execute(
            'SELECT DISTINCT source_file FROM "reporting_rows_data" WHERE dataset_id = 1'
        ).fetchall()
    assert [row['source_file'] for row in dataset_source] == ['renamed-cdr.csv']
    assert [row['source_file'] for row in reporting_source] == ['renamed-cdr.csv']

    workspace = client.get('/workspace')
    assert 'data-dataset-name-editor' not in workspace.text
    admin = client.get('/admin')
    assert 'Datasets Management' in admin.text
    assert '<th>Uploaded</th>' in admin.text
    assert '<th>Updated</th>' in admin.text
    assert admin.text.index('<th>Uploaded</th>') < admin.text.index('<th>Updated</th>')
    assert 'data-admin-dataset-original-name="renamed-cdr.csv"' in admin.text
    assert 'data-admin-dataset-apply-changes' in admin.text
    assert 'Save name' not in admin.text
    assert 'Show Analysis' in admin.text
    assert 'Preview' in admin.text


def test_admin_dataset_management_rename_returns_compact_json_for_interactive_table(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    upload = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('original-cdr.csv', BytesIO(b'Campaign,LQ\nUK_Q2_SA_2026,3.8\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert upload.status_code == 303

    renamed = client.post(
        '/admin/datasets/1/rename',
        data={'file_name': 'renamed-cdr.csv'},
        headers={'Accept': 'application/json'},
        follow_redirects=False,
    )

    assert renamed.status_code == 200
    assert renamed.json()['file_name'] == 'renamed-cdr.csv'
    assert Path(renamed.json()['stored_path']).name == 'renamed-cdr.csv'
    assert app_module.repository.get_dataset(1)['file_name'] == 'renamed-cdr.csv'


def test_admin_dataset_management_applies_staged_names_and_order_in_background(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    for name in ('first.csv', 'second.csv'):
        response = client.post(
            '/datasets-analysis/upload', data={'dataset_kinds': 'data'},
            files={'dataset_files': (name, BytesIO(b'market,score\nES,91\n'), 'text/csv')},
            follow_redirects=False,
        )
        assert response.status_code == 303

    queued = client.post('/admin/datasets/apply-changes', json={
        'order': [1, 2],
        'names': {'1': 'renamed-first.csv'},
    })
    assert queued.status_code == 202, queued.text
    job_id = queued.json()['job_id']
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = json.loads(app_module.repository.get_workspace_state('admin_dataset_management_job_v1') or '{}')
        if job.get('status') in {'ready', 'failed', 'stopped'}:
            break
        time.sleep(0.02)
    assert job['id'] == job_id
    assert job['status'] == 'ready', job
    rows = sorted(app_module.repository.list_datasets(), key=lambda row: int(row['id']))
    assert [(int(row['id']), row['file_name']) for row in rows] == [
        (1, 'second.csv'), (2, 'renamed-first.csv'),
    ]


def test_dashboard_upload_accepts_multiple_files(client) -> None:
    login(client)

    response = client.post(
        "/datasets-analysis/upload",
        files=[
            ("dataset_files", ("sample-a.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")),
            ("dataset_files", ("sample-b.csv", BytesIO(b"market,period,score\nDE,2026-Q2,78\n"), "text/csv")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303

    import src.DashboardAnalytic as app_module

    datasets = app_module.repository.list_datasets()
    assert len(datasets) == 2


def test_workspace_upload_persists_selected_dataset_kind(client) -> None:
    login(client)

    response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "mapping_vodafone"},
        files={"dataset_files": ("operator_cells.csv", BytesIO(b"Cell ID,OP/ Vendor\n123,Ericsson\n"), "text/csv")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    import src.DashboardAnalytic as app_module

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    assert dataset["dataset_kind"] == "mapping_vodafone"


def test_workspace_preview_and_cdr_dashboard_action(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("cdr_data.csv", BytesIO(b"operator,score\nVodafone UK,91\n"), "text/csv")},
        follow_redirects=False,
    )

    workspace_response = client.get("/workspace")
    assert workspace_response.status_code == 200
    assert 'data-queue-type-filter' in workspace_response.text
    assert 'value="">All Types' in workspace_response.text
    assert 'href="/workspace/preview/1" target="_blank" rel="noopener" data-preview-open-link data-loading-label="Generating dataset preview"' in workspace_response.text
    assert 'id="dataset-preview-overlay"' in workspace_response.text
    assert 'id="dataset-preview-dialog-close"' in workspace_response.text
    assert 'aria-label="Close Dataset preview" title="Close Dataset preview">×</button>' in workspace_response.text
    assert 'id="dataset-preview-dialog-loading"' in workspace_response.text
    assert 'Show Analysis</a>' in workspace_response.text

    preview_response = client.get("/workspace/preview/1")
    assert preview_response.status_code == 200
    assert "Dataset preview" in preview_response.text
    assert "Vodafone UK" in preview_response.text
    assert "Show Analysis" in preview_response.text
    assert 'name="row_limit"' not in preview_response.text
    assert 'data-server-dataset-preview' in preview_response.text
    assert 'data-preview-column-filter' not in preview_response.text
    assert 'data-preview-row-filter' not in preview_response.text
    assert 'data-preview-filter-table' in preview_response.text
    embedded_preview = client.get('/workspace/preview/1?embedded=1')
    assert embedded_preview.status_code == 200
    assert 'data-embedded-dataset-preview' in embedded_preview.text
    assert 'class="topbar"' not in embedded_preview.text
    assert 'class="module-tabs"' not in embedded_preview.text
    assert 'id="background-task-panels"' not in embedded_preview.text
    assert 'Back to Workspace' not in embedded_preview.text
    assert 'data-url="/workspace/preview/1?embedded=1"' in embedded_preview.text
    preview_script = client.get('/static/js/app.js')
    assert preview_script.status_code == 200
    assert 'preview-column-filter-trigger' in preview_script.text
    assert 'data-preview-value-option' in preview_script.text
    assert "title: 'Open Dataset Preview'" in preview_script.text
    assert "confirmLabel: 'New tab'" in preview_script.text
    assert "secondaryLabel: 'Current tab'" in preview_script.text
    assert 'openDatasetPreviewInNewTab' in preview_script.text
    assert 'openDatasetPreviewInDialog' in preview_script.text
    assert "if (event.target === datasetPreviewOverlay) closeDatasetPreviewDialog();" in preview_script.text
    assert "datasetPreviewFrameWindow?.addEventListener('keydown', handleEmbeddedDatasetPreviewKeydown, true);" in preview_script.text
    assert "event.stopImmediatePropagation();" in preview_script.text

    limited_preview_response = client.get("/workspace/preview/1?row_limit=25")
    assert limited_preview_response.status_code == 200
    assert 'name="row_limit"' not in limited_preview_response.text

    dashboard_response = client.get('/datasets-analysis?dataset_id=1&input_kind=data')
    assert dashboard_response.status_code == 200
    assert 'href="/workspace/preview/1" target="_blank" rel="noopener" data-preview-open-link data-loading-label="Generating dataset preview">Preview Dataset</a>' in dashboard_response.text


def test_operator_mapping_is_applied_to_charts_but_not_materialized_tables(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.replace_operator_mapping_group(
        None, 'VF', ['Vodafone UK', 'Vodafone', 'VFUK'],
    )
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': (
            'cdr_data.csv', BytesIO(
                b'Operator,Subscriber,Vendor,Mean_Data_Rate\n'
                b'Vodafone UK,Vodafone UK,Vodafone UK_Ericsson,91\n'
                b'O2,O2,O2_Huawei,87\n'
            ), 'text/csv',
        )},
        follow_redirects=False,
    )
    assert response.status_code == 303

    for _ in range(300):
        if app_module.repository.get_dataset(1)['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert app_module.repository.get_dataset(1)['status'] == 'ready'
    for _ in range(300):
        if not app_module.combined_cdr_integrity('data')['has_missing_rows']:
            break
        time.sleep(0.01)
    assert app_module.combined_cdr_integrity('data')['has_missing_rows'] is False

    dataset = app_module.serialize_dataset_row(app_module.repository.get_dataset(1))
    materialized = app_module.repository.load_dataset_rows(1, ['Operator', 'Subscriber', 'Vendor'], {})
    combined = app_module.repository.load_reporting_rows('data', [1], ['Operator', 'Subscriber', 'Vendor'])
    chart_frame = app_module._combined_reporting_frame([dataset], 'nsa', [], False)

    assert materialized['Operator'].tolist() == ['Vodafone UK', 'O2']
    assert combined['Operator'].tolist() == ['Vodafone UK', 'O2']
    assert chart_frame['Operator'].tolist() == ['VF', 'O2']
    assert materialized['Subscriber'].tolist() == ['Vodafone UK', 'O2']
    assert combined['Subscriber'].tolist() == ['Vodafone UK', 'O2']
    assert chart_frame['Subscriber'].tolist() == ['VF', 'O2']
    assert materialized['Vendor'].tolist() == ['Vodafone UK_Ericsson', 'O2_Huawei']
    assert combined['Vendor'].tolist() == ['Vodafone UK_Ericsson', 'O2_Huawei']
    assert chart_frame['Vendor'].tolist() == ['VF_Ericsson', 'O2_Huawei']
    operator_options = next(
        values for field, values in dataset['filter_options'].items()
        if app_module.column_identity(field) == 'operator'
    )
    assert operator_options == ['O2', 'Vodafone UK']


def test_operator_storage_migration_recovers_raw_values_from_the_source(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.replace_operator_mapping_group(
        None, 'VF', ['Vodafone UK', 'Vodafone', 'VFUK'],
    )
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': (
            'cdr_data.csv', BytesIO(b'Operator,Mean_Data_Rate\nVodafone UK,91\n'), 'text/csv',
        )},
        follow_redirects=False,
    )
    legacy = app_module.repository.load_dataset_rows(
        1, app_module.repository.list_dataset_row_columns(1), {},
    )
    legacy['Operator'] = 'VF'
    app_module.repository.replace_dataset_rows(1, legacy)
    app_module.repository.replace_reporting_rows(1, 'data', legacy)
    # Version 12 could be recorded by a Vendor-only update without proving
    # that the stored Operator had been restored from the source.
    app_module.repository.update_dataset_profile(1, normalization_version=12)

    dataset = app_module.serialize_dataset_row(app_module.repository.get_dataset(1))
    app_module.refresh_selected_dataset_if_stale(dataset)

    materialized = app_module.repository.load_dataset_rows(1, ['Operator'], {})
    combined = app_module.repository.load_reporting_rows('data', [1], ['Operator'])
    assert materialized['Operator'].tolist() == ['Vodafone UK']
    assert combined['Operator'].tolist() == ['Vodafone UK']


def test_combined_recreation_migrates_individual_operator_storage_before_rebuilding(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    app_module.repository.replace_operator_mapping_group(
        None, 'VF', ['Vodafone UK', 'Vodafone', 'VFUK'],
    )
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': (
            'cdr_data.csv', BytesIO(b'Operator,Mean_Data_Rate\nVodafone UK,91\n'), 'text/csv',
        )},
        follow_redirects=False,
    )
    legacy = app_module.repository.load_dataset_rows(
        1, app_module.repository.list_dataset_row_columns(1), {},
    )
    legacy['Operator'] = 'VF'
    app_module.repository.replace_dataset_rows(1, legacy)
    app_module.repository.replace_reporting_rows(1, 'data', legacy)
    # Reproduce a table that the former migration incorrectly considered current.
    app_module.repository.update_dataset_profile(1, normalization_version=12)
    progress: list[tuple[int, int, str]] = []

    app_module.recreate_combined_cdr_table(
        app_module.active_workspace,
        'data',
        lambda completed, total, message: progress.append((completed, total, message)),
    )

    materialized = app_module.repository.load_dataset_rows(1, ['Operator'], {})
    combined = app_module.repository.load_reporting_rows('data', [1], ['Operator'])
    refreshed = app_module.repository.get_dataset(1)
    assert materialized['Operator'].tolist() == ['Vodafone UK']
    assert combined['Operator'].tolist() == ['Vodafone UK']
    assert int(refreshed['normalization_version']) == app_module.DATASET_NORMALIZATION_VERSION
    assert any('Migrating individual CDR-DATA table 1 of 1' in message for _, _, message in progress)
    assert progress[-1][0] == progress[-1][1]


def test_workspace_lists_combined_cdr_with_preview_and_kind_filter_metadata(client) -> None:
    login(client)
    import src.DashboardAnalytic as app_module

    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("cdr_data.csv", BytesIO(b"operator,score\nVodafone UK,91\n"), "text/csv")},
        follow_redirects=False,
    )
    app_module.repository.copy_dataset_rows_to_reporting(1, 'data', ['score'])

    workspace_response = client.get('/workspace')
    assert workspace_response.status_code == 200
    assert 'CDR-Data (combined)' in workspace_response.text
    assert 'data-dataset-row data-dataset-kind="data"' in workspace_response.text
    assert workspace_response.text.count('<th') >= 22
    assert workspace_response.text.count('data-queue-sort-key="columns"') == 1
    assert workspace_response.text.count('>Columns</th>') == 1
    assert 'data-combined-dataset-structure-row' in workspace_response.text
    dataset_columns = int(app_module.repository.get_dataset(1)['column_count'])
    assert f'data-queue-sort-cell="columns">{dataset_columns:,}</td>' in workspace_response.text
    assert 'href="/workspace/combined/data/preview"' in workspace_response.text
    assert 'Combined CDR tables' in workspace_response.text
    assert 'they cannot be uploaded or imported as separate datasets' in workspace_response.text
    assert workspace_response.text.index('class="combined-dataset-section-row"') < workspace_response.text.index('data-combined-dataset-row')
    assert workspace_response.text.index('data-combined-dataset-row') < workspace_response.text.index('data-auto-calculated-field-progress')
    combined_columns = len(app_module.repository.list_reporting_row_columns('data'))
    assert f'data-combined-dataset-columns>{combined_columns:,}</td>' in workspace_response.text
    workspace_template = app_module.PROJECT_ROOT / 'src' / 'web_interface' / 'templates' / 'workspace.html'
    assert workspace_template.read_text(encoding='utf-8').count("'{:,}'.format(") >= 4
    live_status = client.get('/api/datasets/status')
    assert live_status.status_code == 200
    assert live_status.json()['combined_tables'][0]['kind'] == 'data'
    assert live_status.json()['combined_tables'][0]['column_count'] == combined_columns
    app_script = app_module.PROJECT_ROOT / 'src' / 'web_interface' / 'static' / 'js' / 'app.js'
    script_text = app_script.read_text(encoding='utf-8')
    assert 'workspace-dataset-table-refresh-requested' in script_text
    assert 'combinedTables.forEach(updateCombinedQueueRow)' in script_text
    assert 'syncCombinedDatasetStopButton(row' in script_text
    assert "event.target.closest('[data-combined-dataset-stop]')" in script_text
    assert "className = 'auto-calculated-field-stop-button combined-dataset-stop-button'" in script_text
    assert '`auto-fields-state:${job.workspace_id}`' in script_text
    assert 'aria-label="Recreate combined table">↻</button>' in workspace_response.text
    assert 'data-combined-dataset-stop' not in workspace_response.text

    preview_response = client.get('/workspace/combined/data/preview')
    assert preview_response.status_code == 200
    assert 'CDR-Data (combined)' in preview_response.text
    assert 'Vodafone UK' in preview_response.text
    assert 'action="/workspace/combined/data/preview"' not in preview_response.text
    assert 'data-endpoint="/api/workspace/combined/data/preview/data"' in preview_response.text
    assert 'data-server-preview-export' in preview_response.text
    assert 'name="cdr_operator"' not in preview_response.text
    assert 'data-preview-column-filter' not in preview_response.text
    assert 'data-preview-row-filter' not in preview_response.text
    assert 'data-preview-clear-filters disabled' in preview_response.text
    assert 'Show Analysis' not in preview_response.text
    embedded_combined = client.get('/workspace/combined/data/preview?embedded=1')
    assert embedded_combined.status_code == 200
    assert 'data-embedded-dataset-preview' in embedded_combined.text
    assert 'id="background-task-panels"' not in embedded_combined.text
    combined_page = client.post('/api/workspace/combined/data/preview/data', json={
        'page': 0, 'column_filters': {'operator': ['Vodafone UK']}, 'filter_column': 'operator',
    })
    assert combined_page.status_code == 200
    assert combined_page.json()['total'] == 1
    assert combined_page.json()['filter_values'] == ['Vodafone UK']
    combined_export = client.post('/api/workspace/combined/data/preview/data', json={
        'column_filters': {'operator': ['Vodafone UK']}, 'download': True,
    })
    assert combined_export.headers['content-type'].startswith('text/csv')
    assert 'Vodafone UK' in combined_export.text


def test_combined_dataset_missing_rows_are_flagged_and_require_confirmation(client, tmp_path: Path) -> None:
    login(client)
    import src.DashboardAnalytic as app_module

    source_path = tmp_path / 'cdr_data.csv'
    source_path.write_text('operator,score\nVodafone UK,91\nVodafone UK,92\n', encoding='utf-8')
    dataset_id, _created = app_module.repository.add_dataset(source_path.name, str(source_path), 'admin')
    app_module.repository.update_dataset_profile(
        dataset_id, status='ready', dataset_kind='data', row_count=2, column_count=2,
    )
    with app_module.repository.connection() as connection:
        connection.execute(f'CREATE TABLE dataset_rows_{dataset_id} (operator TEXT, score INTEGER)')
        connection.execute(f"INSERT INTO dataset_rows_{dataset_id} VALUES ('Vodafone UK', 91), ('Vodafone UK', 92)")
    app_module.repository.copy_dataset_rows_to_reporting(dataset_id, 'data', ['operator', 'score'])
    with app_module.repository.connection() as connection:
        connection.execute('DELETE FROM reporting_rows_data WHERE dataset_id = ? AND source_row_id = 2', (dataset_id,))

    integrity = client.get('/api/workspace/combined/data/integrity')
    assert integrity.status_code == 200
    assert integrity.json()['has_missing_rows'] is True
    assert integrity.json()['row_count'] == 1
    assert integrity.json()['expected_row_count'] == 2

    assert client.get('/workspace/combined/data/preview').status_code == 409
    assert client.get('/workspace/combined/data/preview?allow_incomplete=1').status_code == 200

    workspace_response = client.get('/workspace')
    assert workspace_response.status_code == 200
    assert 'Missing Rows' in workspace_response.text
    assert 'queue-status-warning' in workspace_response.text


def test_combined_recreation_returns_materialization_job_for_progress(client, monkeypatch) -> None:
    login(client)
    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(
        app_module,
        'start_combined_cdr_recreation_job',
        lambda workspace, kind, username: {'id': 'combined-job'},
    )

    response = client.post('/workspace/combined/voice/recreate')

    assert response.status_code == 200
    assert response.json()['materialization_job'] == 'combined-job'
    assert response.json()['materialization_status_url'].endswith('/combined-job')
    assert 'individual CDR-VOICE tables' in response.json()['notice']


def test_recreating_the_same_combined_kind_stops_the_previous_job_before_queueing_a_replacement(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    workspace = app_module.active_workspace
    assert workspace is not None
    submitted: list[tuple[object, tuple[object, ...]]] = []

    previous_id = 'existing-voice-recreation'
    with app_module.AUTO_CALCULATED_FIELD_JOBS_LOCK:
        app_module.AUTO_CALCULATED_FIELD_JOBS[previous_id] = {
            'id': previous_id, 'workspace_id': workspace.id, 'workspace_name': workspace.name,
            'operation': 'combined_recreation', 'combined_kind': 'voice', 'status': 'processing',
        }
    monkeypatch.setattr(
        app_module, '_submit_workspace_job',
        lambda _repository, callback, *args, **_kwargs: submitted.append((callback, args)),
    )

    replacement = app_module.start_combined_cdr_recreation_job(workspace, 'voice', 'admin')

    with app_module.AUTO_CALCULATED_FIELD_JOBS_LOCK:
        previous = app_module.AUTO_CALCULATED_FIELD_JOBS[previous_id]
        app_module.AUTO_CALCULATED_FIELD_JOBS.pop(previous_id)
        app_module.AUTO_CALCULATED_FIELD_JOBS.pop(replacement['id'])
    assert previous['cancel_requested'] is True
    assert replacement['restarted_job_ids'] == [previous_id]
    assert 'Waiting for the previous CDR-VOICE recreation to stop' in replacement['message']
    assert len(submitted) == 1


def test_combined_recreation_keeps_its_success_response_when_audit_logging_is_unavailable(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    monkeypatch.setattr(
        app_module,
        'start_combined_cdr_recreation_job',
        lambda workspace, kind, username: {'id': 'combined-job'},
    )
    monkeypatch.setattr(app_module.repository, 'try_add_log', lambda *_args, **_kwargs: False)

    response = client.post('/workspace/combined/voice/recreate')

    assert response.status_code == 200
    assert response.json()['materialization_job'] == 'combined-job'


def test_queued_dataset_actions_remain_compact_icons_during_live_updates(client) -> None:
    login(client)
    import src.DashboardAnalytic as app_module

    source = app_module.settings.input_dir / 'queued.csv'
    source.write_text('value\n1\n', encoding='utf-8')
    dataset_id, _ = app_module.repository.add_dataset(source.name, str(source), 'admin')
    app_module.repository.update_dataset_profile(dataset_id, status='queued', progress=0)

    page = client.get('/workspace')
    assert page.status_code == 200
    assert 'class="ghost-link action-link-preview" disabled' in page.text
    assert 'aria-label="Preview unavailable"' in page.text
    assert 'class="action-link-clear-vendors" disabled' in page.text
    assert 'class="warning-button icon-action action-link-stop" aria-label="Stop processing" title="Stop processing"' in page.text
    assert 'class="danger-button icon-action" aria-label="Delete dataset"' in page.text
    actions = page.text.split('<div class="queue-actions">', 1)[1].split('</div>', 1)[0]
    assert actions.index('action-link-clear-vendors') < actions.index('action-link-stop') < actions.index('danger-button')

    script = client.get('/static/js/app.js')
    assert 'class="ghost-link action-link-preview" disabled' in script.text
    assert 'action-link-clear-vendors' in script.text
    assert 'action-link-reprocess' in script.text
    assert 'class="danger-button icon-action" aria-label="Delete dataset"' in script.text

    styles = client.get('/static/css/app.css')
    assert ".queue-actions .action-link-map-vendors::before, .admin-dataset-actions .action-link-map-vendors::before { content: '';" in styles.text
    assert ".queue-actions .action-link-clear-vendors::before, .admin-dataset-actions .action-link-clear-vendors::before { content: '';" in styles.text
    assert '.queue-actions .action-link-reprocess::before, .admin-dataset-actions .action-link-reprocess::before' in styles.text
    assert '.queue-actions .danger-button::before, .admin-dataset-actions .danger-button::before' in styles.text
    assert '.queue-actions .action-link-stop::before, .admin-dataset-actions .action-link-stop::before' in styles.text
    assert '.admin-dataset-actions .danger-button { font-size: 0 !important; }' in styles.text
    assert '.action-link-clear-vendors { background: linear-gradient(135deg, #d58f1f, #e9ac39);' in styles.text
    assert '.queue-actions :is(.action-link-reprocess,.action-link-stop), .admin-dataset-actions :is(.action-link-reprocess,.action-link-stop) { background: linear-gradient(135deg, #c75683, #ed98b7);' in styles.text
    assert '.report-job-actions { display: flex; max-width: none; flex-wrap: nowrap;' in styles.text
    assert '.report-jobs-table th:nth-child(2), .report-jobs-table td:nth-child(2) { width: 10%; min-width: 130px;' in styles.text
    assert '.report-jobs-table th:nth-child(10), .report-jobs-table td:nth-child(10) { width: 20%; min-width: 240px;' in styles.text
    assert '.report-jobs-table th:nth-child(1), .report-jobs-table td:nth-child(1) { width: 6%; min-width: 76px;' in styles.text
    assert '.report-jobs-table th:nth-child(3), .report-jobs-table td:nth-child(3) { width: 9%; min-width: 132px;' in styles.text
    assert '.report-jobs-table th:nth-child(4), .report-jobs-table td:nth-child(4) { width: 7.5%; min-width: 96px;' in styles.text
    assert '.report-jobs-table th:nth-child(5), .report-jobs-table td:nth-child(5) { width: 6%; min-width: 68px;' in styles.text
    assert '.report-jobs-table th:nth-child(8), .report-jobs-table td:nth-child(8),\n.report-jobs-table th:nth-child(9), .report-jobs-table td:nth-child(9) { width: 6%; min-width: 72px;' in styles.text
    assert '.report-jobs-table th:nth-child(12), .report-jobs-table td:nth-child(12) { width: 10%; min-width: 110px;' in styles.text


def test_cdr_preview_groups_every_non_source_field_after_source_sheet(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    source = tmp_path / 'source.csv'
    source.write_text('Campaign,Operator,score\nUK_Q3_2026,VF,91\n', encoding='utf-8')
    ordered, derived = app_module._ordered_cdr_preview_columns(
        ['Campaign', 'source_sheet', 'market', 'Operator', 'vendor', 'score'], [source],
    )

    assert ordered == ['source_sheet', 'Operator', 'vendor', 'Campaign', 'market', 'score']
    assert derived == {'source_sheet', 'market', 'vendor'}


def test_cdr_preview_uses_clean_duplicate_names_and_orders_vendor_only_after_vendor(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module
    from src.modules.column_names import clean_column_name

    source = tmp_path / 'source.csv'
    source.write_text('Campaign,Vendor,Cell_Duplicate_2\nUK_Q3_2026,Ericsson,A\n', encoding='utf-8')
    ordered, derived, main, _auto = app_module._preview_column_categories(
        ['source_sheet', 'Campaign', 'Vendor', 'Vendor_Only', 'Cell_Duplicate_2'], [source],
    )

    assert clean_column_name('campaign__2') == 'campaign_Duplicate_2'
    assert 'Cell_Duplicate_2' in ordered
    assert ordered.index('Vendor_Only') == ordered.index('Vendor') + 1
    assert 'Vendor_Only' in derived
    assert {'Campaign', 'Vendor', 'Vendor_Only'} <= main


def test_cdr_preview_badges_follow_physical_source_columns(tmp_path: Path, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(app_module.repository, 'list_calculated_dimensions', lambda: [])

    source = tmp_path / 'source.csv'
    source.write_text(
        'Operator,Vendor,Vendor_Only,Campaign,Source_File\n'
        'Vodafone UK,Ericsson,Ericsson,UK_Q3_2026,original.csv\n',
        encoding='utf-8',
    )
    columns = [
        'Operator', 'Vendor', 'Campaign', 'Source_File', 'Source_Sheet',
        'Vendor_Only', 'Campaign_Year',
    ]

    _ordered, derived, main, auto = app_module._preview_column_categories(columns, [source])
    _labels, kinds, _rules = app_module._preview_column_metadata(
        columns, [source], derived, main, auto, 'data',
    )

    assert kinds['Operator'] == 'CDR-Main'
    assert kinds['Vendor'] == 'CDR-Main'
    assert kinds['Campaign'] == 'CDR-Main'
    assert kinds['Source_File'] == 'CDR-Data'
    assert kinds['Source_Sheet'] == 'Derived'
    assert kinds['Vendor_Only'] == 'Derived'
    assert kinds['Campaign_Year'] == 'Derived'

    source_identities = {
        app_module.column_identity(column)
        for column in app_module.get_dataset_source_columns(source)
    }
    cdr_main_columns = {column for column, kind in kinds.items() if kind == 'CDR-Main'}
    derived_columns = {column for column, kind in kinds.items() if kind == 'Derived'}
    assert all(app_module.column_identity(column) in source_identities for column in cdr_main_columns)
    assert all(
        app_module.column_identity(column) not in source_identities
        or app_module.column_identity(column) == 'vendoronly'
        for column in derived_columns
    )

    missing_source = tmp_path / 'missing.csv'
    _ordered, unknown_derived, unknown_main, unknown_auto = app_module._preview_column_categories(
        columns, [missing_source],
    )
    _labels, unknown_kinds, _rules = app_module._preview_column_metadata(
        columns, [missing_source], unknown_derived, unknown_main, unknown_auto, 'data',
    )
    assert 'CDR-Main' not in unknown_kinds.values()
    assert {column for column, kind in unknown_kinds.items() if kind == 'Derived'} == {'Vendor_Only'}


def test_cdr_preview_paginates_and_filters_every_column(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    cdr_rows = [
        'Vodafone UK,Ericsson,ENDC,VoLTE,Completed,Streaming,YouTube playback,91,Alpha User,UK_Q3_2026',
        '3,Nokia,NR,WhatsApp,Dropped,Interactivity,Chat,90,Target User,UK_Q4_2026',
        *[
            f'Vodafone UK,Ericsson,ENDC,VoLTE,Completed,Streaming,YouTube playback,{index},Alpha User,UK_Q3_2026'
            for index in range(100)
        ],
        ',Ericsson,ENDC,VoLTE,Completed,Streaming,YouTube playback,blank-operator,Alpha User,UK_Q3_2026',
    ]
    cdr_content = (
        'operator,vendor,RAT_A,Session_Type,Call_Status,Type_of_Test,Test_Name,score,Suscriber,Campaign\n'
        + '\n'.join(cdr_rows)
        + '\n'
    ).encode()
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': (
            'cdr_data.csv',
            BytesIO(cdr_content),
            'text/csv',
        )},
        follow_redirects=False,
    )

    assert app_module.repository.list_dataset_source_columns(1) == [
        'operator', 'vendor', 'RAT_A', 'Session_Type', 'Call_Status',
        'Type_of_Test', 'Test_Name', 'score', 'Suscriber', 'Campaign',
    ]
    monkeypatch.setattr(
        app_module,
        'get_dataset_source_columns',
        lambda _path: (_ for _ in ()).throw(AssertionError('Preview reopened the source CDR.')),
    )

    default_preview = client.get('/workspace/preview/1')
    assert default_preview.status_code == 200
    assert 'Rows to preview' not in default_preview.text
    assert 'name="cdr_operator"' not in default_preview.text
    assert 'name="cdr_vendor"' not in default_preview.text
    assert 'name="cdr_rat"' not in default_preview.text
    assert 'name="cdr_session_type"' not in default_preview.text
    assert 'name="cdr_call_status"' not in default_preview.text
    assert 'data-server-dataset-preview' in default_preview.text
    assert 'data-preview-clear-filters disabled>' in default_preview.text
    assert '<span data-preview-clear-label>Clear 0 Filters</span>' in default_preview.text
    assert 'data-preview-next-page disabled' not in default_preview.text
    assert 'Showing 1-100 of 103 rows' in default_preview.text
    footer = default_preview.text.split('<div class="preview-server-footer">', 1)[1].split('</div>', 1)[0]
    assert '<nav class="preview-pagination"' in footer
    assert footer.count('<svg viewBox="0 0 24 24"') == 5
    assert 'data-preview-first-page disabled aria-label="First page"' in footer
    assert 'data-preview-last-page aria-label="Last page"' in footer
    assert '>Call Family<' not in default_preview.text
    assert 'class="auto-calculated-preview-column"' in default_preview.text
    assert 'data-column-label="Test Family"' in default_preview.text
    assert 'data-server-preview-column-search' in default_preview.text
    assert 'data-server-preview-export' in default_preview.text
    assert 'data-preview-dataset-switch' in default_preview.text
    assert 'data-preview-dataset-switch-menu' in default_preview.text
    assert "showLoadingOverlay(\n      'Loading Workspace Dataset'" in app_module.PROJECT_ROOT.joinpath(
        'src/web_interface/static/js/app.js',
    ).read_text(encoding='utf-8')
    assert "new Intl.NumberFormat('en-US')" in app_module.PROJECT_ROOT.joinpath(
        'src/web_interface/static/js/app.js',
    ).read_text(encoding='utf-8')
    assert "'{:,}'.format(preview_total_rows)" in app_module.PROJECT_ROOT.joinpath(
        'src/web_interface/templates/dataset_preview.html',
    ).read_text(encoding='utf-8')
    assert 'data-preview-tag-filter' in default_preview.text
    assert 'data-preview-tag-filter-all>All Labels</button>' in default_preview.text
    assert '>PINNED</button>' in default_preview.text
    assert '>UN_PINNED</button>' in default_preview.text
    assert '>CDR-Main</button>' in default_preview.text
    vendor_badge = default_preview.text.split('data-column-label="Vendor"', 1)[1][:100]
    vendor_only_badge = default_preview.text.split('data-column-label="Vendor_Only"', 1)[1][:100]
    assert 'data-column-kind="CDR-Main"' in vendor_badge
    assert 'data-column-kind="Derived"' in vendor_only_badge
    preview_css = app_module.PROJECT_ROOT.joinpath(
        'src/web_interface/static/css/app.css',
    ).read_text(encoding='utf-8')
    assert '.dataset-preview-table .main-cdr-column { background: #ccebd9;' in preview_css
    assert '.dataset-preview-table .derived-cdr-column { background: #e6f7ed;' in preview_css
    assert '.dataset-preview-table thead th.main-cdr-column { background: #78bd94;' in preview_css
    assert '.dataset-preview-table thead th.derived-cdr-column { background: #9fd8b7;' in preview_css
    assert '>Main</button>' not in default_preview.text
    assert 'Select Workspace Dataset' in default_preview.text
    assert 'target="_blank" rel="noopener">Back to Workspace</a>' in default_preview.text
    assert '>Auto-calculated</button>' in default_preview.text
    assert 'data-column-label="Result Group"' in default_preview.text
    header = default_preview.text.split('<thead>', 1)[1].split('</thead>', 1)[0]
    assert header.index('data-column-label="Source_File"') < header.index('data-column-label="Source_Sheet"')
    assert header.index('data-column-label="Source_Sheet"') < header.index('data-column-label="Dataset_Kind"')
    assert header.index('data-column-label="Operator"') < header.index('data-column-label="Campaign"')
    assert header.index('data-column-label="Test_Name"') < header.index('data-column-label="Test_Result"') < header.index('data-column-label="Call_Status"')
    assert 'preview-column-kind-badge' not in header
    assert header.index('data-column-name="operator"') < header.index('data-column-name="Result Group"')
    assert header.index('data-column-name="Test Family"') < header.index('data-column-name="score"')
    values_response = client.post('/api/workspace/preview/1/data', json={
        'page': 0, 'column_filters': {}, 'filter_column': 'operator',
    })
    assert values_response.status_code == 200
    assert values_response.json()['filter_values'] == ['', '3', 'Vodafone UK']
    assert values_response.json()['total'] == 103
    assert all('report_vendor' not in column.casefold() for column in values_response.json()['columns'])

    cascading_values = client.post('/api/workspace/preview/1/data', json={
        'page': 0, 'column_filters': {'operator': ['3']}, 'filter_column': 'Session_Type',
    })
    assert cascading_values.status_code == 200
    assert cascading_values.json()['filter_values'] == ['WhatsApp']

    second_page = client.post('/api/workspace/preview/1/data', json={
        'page': 1, 'column_filters': {},
    })
    assert second_page.status_code == 200
    assert second_page.json()['page'] == 1
    assert len(second_page.json()['rows']) == 3

    filtered_response = client.post('/api/workspace/preview/1/data', json={
        'page': 0,
        'column_filters': {
            'OPERATOR': ['3'], 'Vendor': ['nOkIa'], 'rat a': ['nr'],
            'SUBSCRIBER': ['target user'], 'campaign': ['uk_q4_2026'],
        },
    })
    assert filtered_response.status_code == 200
    assert filtered_response.json()['total'] == 1
    assert filtered_response.json()['unfiltered_total'] == 103
    assert filtered_response.json()['rows'][0]['operator'] == '3'
    vendor_key = next(key for key in filtered_response.json()['rows'][0] if key.casefold() == 'vendor')
    assert filtered_response.json()['rows'][0][vendor_key] == 'Nokia'
    assert filtered_response.json()['rows'][0]['Vendor_Only'] == 'Nokia'
    assert filtered_response.json()['rows'][0]['Suscriber'] == 'Target User'
    assert filtered_response.json()['rows'][0]['Campaign'] == 'UK_Q4_2026'

    filtered_export = client.post('/api/workspace/preview/1/data', json={
        'column_filters': {'operator': ['3'], 'Vendor': ['nOkIa']}, 'download': True,
    })
    assert filtered_export.headers['content-type'].startswith('text/csv')
    assert 'attachment; filename="dataset-1-preview.csv"' == filtered_export.headers['content-disposition']
    assert ',3,Target User,Nokia,Nokia,' in filtered_export.text
    assert 'Vodafone UK' not in filtered_export.text

    empty_selection = client.post('/api/workspace/preview/1/data', json={
        'page': 0, 'column_filters': {'operator': []},
    })
    assert empty_selection.status_code == 200
    assert empty_selection.json()['total'] == 0
    assert empty_selection.json()['rows'] == []


def test_workspace_uses_persisted_vendor_flags_without_reloading_cdr_files(client, monkeypatch) -> None:
    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('cdr_data.csv', BytesIO(b'operator,score\nVodafone UK,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    def source_reload_should_not_run(*_args, **_kwargs):
        raise AssertionError('Workspace should use the persisted Vendor flags, not reload CDR files.')

    monkeypatch.setattr(app_module, 'load_cached_dataset', source_reload_should_not_run)
    assert client.get('/workspace').status_code == 200


def test_workspace_maps_unassigned_cdr_vendors_from_available_multivendor_mapping(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('cdr_data.csv', BytesIO(b'operator,Cell_ID_A,score\n3,200 -> 200,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')},
        follow_redirects=False,
    )

    workspace = client.get('/workspace')
    assert 'data-vendor-map-open' in workspace.text
    assert 'data-queue-status="ready"' in workspace.text
    assert 'name="cdr_dataset_ids"' in workspace.text
    assert 'name="three_mapping_dataset_id"' in workspace.text
    assert 'value="2" selected' in workspace.text
    assert 'data-loading-label="Mapping Vendors to CDR samples"' not in workspace.text
    assert 'Vendor mapping rule' in workspace.text
    assert 'the same non-empty Vendor at both endpoints returns' in workspace.text
    live_status = client.get('/api/datasets/status').json()['datasets']
    assert next(dataset for dataset in live_status if dataset['id'] == 1)['can_map_vendors'] is True

    # Vendor Mapping rebuilds from the uploaded source so it can restore the
    # original Operator values before adding the calculated Vendor fields.
    app_module.repository.update_dataset_profile(1, normalization_version=12)
    response = client.post(
        '/workspace/map-vendors',
        data={'cdr_dataset_id': 1, 'three_mapping_dataset_id': 2},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert int(app_module.repository.get_dataset(1)['normalization_version']) == 13

    preview = client.get('/workspace/preview/1')
    assert preview.status_code == 200
    assert '>3_Nokia<' in preview.text

    workspace_after_mapping = client.get('/workspace').text.split('<table class="queue-table" data-queue-sortable-table>', 1)[1].split('</tbody>', 1)[0]
    assert 'data-dataset-id="1"' in workspace_after_mapping
    assert 'data-vendor-map-open' not in workspace_after_mapping
    assert 'data-vendor-clear-open' in workspace_after_mapping
    assert 'action="/workspace/clear-vendors"' in workspace.text
    live_status_after_mapping = client.get('/api/datasets/status').json()['datasets']
    assert next(dataset for dataset in live_status_after_mapping if dataset['id'] == 1)['can_clear_vendors'] is True

    clear_response = client.post('/workspace/clear-vendors/1', follow_redirects=False)
    assert clear_response.status_code == 303
    workspace_after_clear = client.get('/workspace').text.split('<table class="queue-table" data-queue-sortable-table>', 1)[1].split('</tbody>', 1)[0]
    assert 'data-vendor-map-open' in workspace_after_clear
    assert 'data-vendor-clear-open' not in workspace_after_clear


def test_workspace_queues_vendor_mapping_for_multiple_cdrs(client) -> None:
    login(client)
    uploads = [
        ('cdr_data_q1.csv', 'data', b'operator,Cell_ID_A,Campaign\n3,200 -> 200,2026 Q1\n'),
        ('cdr_data_q2.csv', 'data', b'operator,Cell_ID_A,Campaign\n3,200 -> 200,2026 Q2\n'),
        ('Multivendor_Mapping_3UK.csv', 'mapping_three', b'Cid__ECI,Vendor\n200,Nokia\n'),
    ]
    for file_name, kind, content in uploads:
        response = client.post(
            '/datasets-analysis/upload',
            data={'dataset_kinds': kind},
            files={'dataset_files': (file_name, BytesIO(content), 'text/csv')},
            follow_redirects=False,
        )
        assert response.status_code == 303

    response = client.post(
        '/workspace/map-vendors',
        data={'cdr_dataset_ids': ['1', '2'], 'three_mapping_dataset_id': '3'},
        follow_redirects=False,
    )
    assert response.status_code == 303
    datasets = client.get('/api/datasets/status').json()['datasets']
    assert all(dataset['vendor_mapping_applied'] for dataset in datasets if dataset['id'] in {1, 2})

    response = client.post(
        '/workspace/clear-vendors',
        data={'cdr_dataset_ids': ['1', '2']},
        follow_redirects=False,
    )
    assert response.status_code == 303
    datasets = client.get('/api/datasets/status').json()['datasets']
    assert all(not dataset['vendor_mapping_applied'] for dataset in datasets if dataset['id'] in {1, 2})


def test_failed_vendor_mapping_keeps_the_cdr_available(client) -> None:
    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('cdr_without_cell_id.csv', BytesIO(b'Operator,score\n3,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')},
        follow_redirects=False,
    )

    response = client.post('/workspace/map-vendors', data={'cdr_dataset_id': 1, 'three_mapping_dataset_id': 2})
    assert response.status_code == 200
    dataset = next(item for item in client.get('/api/datasets/status').json()['datasets'] if item['id'] == 1)
    assert dataset['status'] == 'ready'
    assert client.get('/workspace/preview/1').status_code == 200
    app_logs = client.get('/app-logs').text
    assert 'map_dataset_vendors_failed' in app_logs
    assert 'Cell ID field' in app_logs


def test_workspace_recovers_legacy_vendor_mapping_failures(client) -> None:
    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('legacy_cdr.csv', BytesIO(b'Operator,score\n3,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(
        1,
        status='failed',
        progress=100,
        last_error='The selected CDR must contain Operator and Cell_ID_A to assign vendors.',
    )

    response = client.get('/workspace')
    assert response.status_code == 200
    dataset = next(item for item in client.get('/api/datasets/status').json()['datasets'] if item['id'] == 1)
    assert dataset['status'] == 'ready'
    assert client.get('/workspace/preview/1').status_code == 200


def test_workspace_upload_can_map_selected_cdr_vendor_during_processing(client) -> None:
    login(client)
    mapping_response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert mapping_response.status_code == 303

    workspace = client.get('/workspace')
    assert 'data-three-mapping-options=' in workspace.text
    assert 'Multivendor_Mapping_3UK.csv' in workspace.text
    assert 'No Map Vendor Column' in workspace.text
    assert 'name = \'three_mapping_dataset_ids\'' not in workspace.text
    assert "mappingSelect.name = fieldName" in workspace.text

    cdr_response = client.post(
        '/datasets-analysis/upload',
        data={
            'dataset_kinds': 'data',
            'vodafone_mapping_dataset_ids': '',
            'three_mapping_dataset_ids': '1',
        },
        files={'dataset_files': ('cdr_data.csv', BytesIO(b'Operator,Cell_ID_A,score\n3,200 -> 200,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert cdr_response.status_code == 303

    preview = client.get('/workspace/preview/2')
    assert preview.status_code == 200
    assert '>3_Nokia<' in preview.text
    vendor_badge = preview.text.split('data-column-label="Vendor"', 1)[1][:100]
    vendor_only_badge = preview.text.split('data-column-label="Vendor_Only"', 1)[1][:100]
    assert 'data-column-kind="Vendor-Map"' in vendor_badge
    assert 'data-column-kind="Derived"' in vendor_only_badge

    import src.DashboardAnalytic as app_module
    dataset = app_module.serialize_dataset_row(app_module.repository.get_dataset(2))
    assert dataset['vendor_mapping_applied'] is True


def test_retry_reuses_persisted_vendor_mapping_selections(client) -> None:
    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')},
        follow_redirects=False,
    )
    client.post(
        '/datasets-analysis/upload',
        data={
            'dataset_kinds': 'data',
            'vodafone_mapping_dataset_ids': '',
            'three_mapping_dataset_ids': '1',
        },
        files={'dataset_files': ('retry_mapped.csv', BytesIO(b'Operator,Cell_ID_A,score\n3,200 -> 200,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    original = app_module.repository.get_dataset(2)
    assert original is not None
    assert json.loads(original['processing_options_json'])['three_mapping_dataset_id'] == 1
    app_module.repository.update_dataset_profile(
        2, status='failed', progress=100, vendor_mapping_applied=False,
        last_error='Synthetic retry request',
    )

    response = client.post('/datasets-analysis/retry/2', follow_redirects=False)

    assert response.status_code == 303
    retried = app_module.serialize_dataset_row(app_module.repository.get_dataset(2))
    assert retried['status'] == 'ready'
    assert retried['vendor_mapping_applied'] is True
    assert '>3_Nokia<' in client.get('/workspace/preview/2').text


def test_workspace_recovers_database_lock_failure_with_saved_vendor_mapping(client) -> None:
    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')},
        follow_redirects=False,
    )
    client.post(
        '/datasets-analysis/upload',
        data={
            'dataset_kinds': 'data',
            'vodafone_mapping_dataset_ids': '',
            'three_mapping_dataset_ids': '1',
        },
        files={'dataset_files': ('locked_mapped.csv', BytesIO(b'Operator,Cell_ID_A,score\n3,200 -> 200,91\n'), 'text/csv')},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(
        2, status='failed', progress=100, vendor_mapping_applied=False,
        last_error='database is locked',
    )

    response = client.get('/workspace')

    assert response.status_code == 200
    recovered = app_module.serialize_dataset_row(app_module.repository.get_dataset(2))
    assert recovered['status'] == 'ready'
    assert recovered['vendor_mapping_applied'] is True
    assert '>3_Nokia<' in client.get('/workspace/preview/2').text


def test_workspace_batch_upload_keeps_vendor_mapping_choices_aligned_per_file(client) -> None:
    login(client)
    client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')},
        follow_redirects=False,
    )

    response = client.post(
        '/datasets-analysis/upload',
        data={
            'dataset_kinds': ['data', 'generic'],
            'vodafone_mapping_dataset_ids': ['', ''],
            'three_mapping_dataset_ids': ['1', ''],
        },
        files=[
            ('dataset_files', ('cdr_data.csv', BytesIO(b'Operator,Cell_ID_A,score\n3,200 -> 200,91\n'), 'text/csv')),
            ('dataset_files', ('other.csv', BytesIO(b'name,value\nother,1\n'), 'text/csv')),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert '>3_Nokia<' in client.get('/workspace/preview/2').text


def test_workspace_batch_upload_processes_uploaded_mapping_before_its_cdr(client) -> None:
    login(client)

    upload_page = client.get('/datasets-analysis')
    assert upload_page.status_code == 200
    assert 'uploaded with this batch' not in upload_page.text

    response = client.post(
        '/datasets-analysis/upload',
        data={
            'dataset_kinds': ['mapping_three', 'data'],
            'vodafone_mapping_dataset_ids': ['', ''],
            'three_mapping_dataset_ids': ['', 'upload:0'],
        },
        files=[
            ('dataset_files', ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')),
            ('dataset_files', ('cdr_data.csv', BytesIO(b'Operator,Cell_ID_A,score\n3,200 -> 200,91\n'), 'text/csv')),
        ],
        follow_redirects=False,
    )

    assert response.status_code == 303
    preview = client.get('/workspace/preview/2')
    assert '>3_Nokia<' in preview.text

    import src.DashboardAnalytic as app_module
    cdr = app_module.serialize_dataset_row(app_module.repository.get_dataset(2))
    assert cdr['vendor_mapping_applied'] is True


def test_dataset_processing_fails_when_selected_vendor_mapping_cannot_be_applied(client) -> None:
    login(client)

    response = client.post(
        '/datasets-analysis/upload',
        data={
            'dataset_kinds': ['mapping_three', 'data'],
            'vodafone_mapping_dataset_ids': ['', ''],
            'three_mapping_dataset_ids': ['', 'upload:0'],
        },
        files=[
            ('dataset_files', ('Multivendor_Mapping_3UK.csv', BytesIO(b'Cid__ECI,Vendor\n200,Nokia\n'), 'text/csv')),
            ('dataset_files', ('cdr_without_cell_id.csv', BytesIO(b'Operator,score\n3,91\n'), 'text/csv')),
        ],
        follow_redirects=False,
    )

    assert response.status_code == 303
    import src.DashboardAnalytic as app_module

    cdr = app_module.serialize_dataset_row(app_module.repository.get_dataset(2))
    assert cdr['status'] == 'failed'
    assert cdr['vendor_mapping_applied'] is False
    assert 'Vendor mapping failed' in str(cdr['last_error'])
    assert 'Cell ID field' in str(cdr['last_error'])
    assert client.get('/workspace/preview/2').status_code == 400


def test_vfuk_preview_limits_mapping_sheets_and_displays_materialised_gcid(client) -> None:
    login(client)
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine='openpyxl') as writer:
        pd.DataFrame({
            'eNodeB ID': [13008],
            'Local Cell ID': [1],
            'OP/ Vendor': ['Samsung'],
        }).to_excel(writer, sheet_name='4G', index=False)
        pd.DataFrame({
            'gNodeB ID': [53986],
            'Local Cell ID': [302],
            'OP/ Vendor': ['Samsung'],
        }).to_excel(writer, sheet_name='5G', index=False)
        pd.DataFrame({'Cell ID': [1]}).to_excel(writer, sheet_name='2G', index=False)
    workbook.seek(0)

    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_vodafone'},
        files={'dataset_files': ('Multivendor_Mapping_VFUK.xlsx', workbook, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Simulate a mapping that was processed before the GCID materialisation
    # was introduced; opening its preview must upgrade the stored rows.
    import src.DashboardAnalytic as app_module
    stored_rows = app_module.repository.load_dataset_rows(
        1,
        app_module.repository.list_dataset_row_columns(1),
        {},
    ).drop(columns=['GCID'])
    app_module.repository.replace_dataset_rows(1, stored_rows)

    default_preview = client.get('/workspace/preview/1')
    assert default_preview.status_code == 200
    assert 'name="source_sheet"' in default_preview.text
    assert '<option value="4G" selected>4G</option>' in default_preview.text
    assert '<option value="5G">5G</option>' in default_preview.text
    assert '2G' not in default_preview.text
    assert '3330049' in default_preview.text
    assert '>Source_Sheet<' in default_preview.text
    assert 'class="gcid-column"' in default_preview.text

    five_g_preview = client.get('/workspace/preview/1?source_sheet=5G')
    assert five_g_preview.status_code == 200
    assert '<option value="5G" selected>5G</option>' in five_g_preview.text
    assert '221126958' in five_g_preview.text


def test_three_mapping_preview_excludes_empty_normalized_columns(client) -> None:
    login(client)
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'MBNL_ID,Vendor,Site_Name,Cid__ECI\nAAB013,Ericsson,United Reformed Church,123\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert response.status_code == 303

    preview = client.get('/workspace/preview/1')
    assert preview.status_code == 200
    assert 'MBNL_ID' in preview.text
    assert 'Cid__ECI' in preview.text
    assert 'Vendor' in preview.text
    assert 'data-column-label="Source_File"' in preview.text
    assert 'data-column-label="Source_Sheet"' in preview.text
    assert 'data-column-label="Dataset_Kind"' in preview.text
    assert 'data-column-label="Region"' in preview.text
    assert 'data-column-label="GCID"' in preview.text
    assert 'data-column-label="Operator"' in preview.text
    assert '>vendor__2<' not in preview.text
    assert 'data-column-label="Technology_Primary"' in preview.text
    assert 'data-column-kind="Analysis-derived"' not in preview.text
    assert '>GCID<' in preview.text
    assert '>123<' in preview.text
    assert preview.text.index('>GCID<') < preview.text.index('>MBNL_ID<')
    assert 'data-column-label="Vendor"' in preview.text


def test_mapping_preview_shows_every_source_column(client) -> None:
    login(client)
    source_columns = ['CId___ECI', 'Vendor', *(f'Extra_{number:02d}' for number in range(1, 27))]
    source_row = ['123', 'Ericsson', *(str(number) for number in range(1, 27))]
    content = (','.join(source_columns) + '\n' + ','.join(source_row) + '\n').encode()
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )
    assert response.status_code == 303

    preview = client.get('/workspace/preview/1')
    assert preview.status_code == 200
    assert '>Extra_26<' in preview.text


def test_mapping_preview_formats_integral_gcid_without_decimal_suffix(client) -> None:
    login(client)
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_vodafone'},
        files={'dataset_files': ('Multivendor_Mapping_VFUK.csv', BytesIO(b'source_sheet,gNodeB ID,Local Cell ID,OP/ Vendor\n5G,53986,302,Ericsson\n5G,,,Ericsson\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert response.status_code == 303

    preview = client.get('/workspace/preview/1?source_sheet=5G')
    assert preview.status_code == 200
    assert '>221126958<' in preview.text
    assert '>221126958.0<' not in preview.text


def test_mapping_preview_hides_unnamed_columns_but_keeps_cell_name(client) -> None:
    login(client)
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_vodafone'},
        files={'dataset_files': ('Multivendor_Mapping_VFUK.csv', BytesIO(b'source_sheet,eNodeB ID,Local Cell ID,Cell Name,Unnamed_2,OP/ Vendor\n4G,13008,1,Cell A,,Samsung\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert response.status_code == 303

    preview = client.get('/workspace/preview/1')
    assert preview.status_code == 200
    assert '>Cell Name<' in preview.text
    assert '>Cell A<' in preview.text
    assert '>Unnamed_2<' not in preview.text
    assert '>Source_Sheet<' in preview.text


def test_vfuk_preview_uses_only_the_selected_source_sheet_columns(client) -> None:
    login(client)
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine='openpyxl') as writer:
        pd.DataFrame({
            'Cell Name': ['4G Cell'],
            'eNodeB ID': [13008],
            'Local Cell ID': [1],
            'OP/ Vendor': ['Samsung'],
        }).to_excel(writer, sheet_name='4G', index=False)
        pd.DataFrame({
            'Cell Name': ['5G Cell'],
            'gNodeB ID': [53986],
            'Local Cell ID': [302],
            'Only 5G': ['present only in 5G'],
            'OP/ Vendor': ['Ericsson'],
        }).to_excel(writer, sheet_name='5G', index=False)
    workbook.seek(0)
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_vodafone'},
        files={'dataset_files': ('Multivendor_Mapping_VFUK.xlsx', workbook, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        follow_redirects=False,
    )
    assert response.status_code == 303

    four_g_preview = client.get('/workspace/preview/1?source_sheet=4G')
    assert four_g_preview.status_code == 200
    assert '>Cell Name<' in four_g_preview.text
    assert '>4G Cell<' in four_g_preview.text
    assert '>Only 5G<' not in four_g_preview.text

    five_g_preview = client.get('/workspace/preview/1?source_sheet=5G')
    assert five_g_preview.status_code == 200
    assert '>Only 5G<' in five_g_preview.text
    assert '>present only in 5G<' in five_g_preview.text
    assert 'available columns' in five_g_preview.text
    assert '<span>Available Columns</span><strong>' in five_g_preview.text


def test_mapping_preview_filters_by_vendor_and_gcid(client) -> None:
    login(client)
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'mapping_three'},
        files={'dataset_files': ('Multivendor_Mapping_3UK.csv', BytesIO(b'Vendor,CId___ECI,Site_Name\nEricsson,123,Site A\nNokia,456,Site B\n'), 'text/csv')},
        follow_redirects=False,
    )
    assert response.status_code == 303

    vendor_preview = client.get('/workspace/preview/1?mapping_vendor=Nokia')
    assert vendor_preview.status_code == 200
    vendor_rows = vendor_preview.text.split('<tbody>', 1)[1].split('</tbody>', 1)[0]
    assert '>Nokia<' in vendor_rows
    assert '>Ericsson<' not in vendor_rows
    assert 'name="mapping_vendor"' in vendor_preview.text

    gcid_preview = client.get('/workspace/preview/1?gcid=123')
    assert gcid_preview.status_code == 200
    gcid_rows = gcid_preview.text.split('<tbody>', 1)[1].split('</tbody>', 1)[0]
    assert '>123<' in gcid_rows
    assert '>456<' not in gcid_rows


def test_workspace_queue_type_filter_lists_all_supported_types_in_order(client) -> None:
    login(client)

    response = client.get("/workspace")
    assert response.status_code == 200
    filter_html = response.text.split('<select data-queue-type-filter>', 1)[1].split('</select>', 1)[0]
    labels = [
        'All Types',
        'CDR-Data',
        'CDR-Speech',
        'CDR-Voice',
        'Multivendor Mapping — Three UK (3UK)',
        'Multivendor Mapping — Vodafone UK (VFUK)',
        'Other supported dataset',
        'Smart Orchestrator Logs',
    ]
    positions = [filter_html.index(label) for label in labels]
    assert positions == sorted(positions)
    assert 'value="data" disabled' in filter_html
    assert '<summary class="collapsible-summary">\n      <div>\n        <p class="eyebrow">Data Processing</p>' in response.text


def test_dataset_selector_shows_all_datasets_when_no_input_kind_filter_is_set(client) -> None:
    login(client)

    client.post(
        "/datasets-analysis/upload",
        files={"dataset_files": ("voice.csv", BytesIO(b"POLQA_LQ_Avg,market,period\n4.2,ES,2026-Q1\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        files={"dataset_files": ("data.csv", BytesIO(b"Mean_Data_Rate,market,period\n25.1,DE,2026-Q2\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/datasets-analysis?dataset_id=2")
    assert response.status_code == 200
    assert '<option value="1"' in response.text
    assert '<option value="2"' in response.text


def test_dataset_selector_only_lists_ready_datasets(client) -> None:
    login(client)

    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("ready.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("stopped.csv", BytesIO(b"market,period,score\nDE,2026-Q2,78\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(2, status="stopped", progress=50)

    response = client.get("/datasets-analysis")
    selector_fragment = response.text.split('data-dataset-select', 1)[1].split('</select>', 1)[0]
    assert response.status_code == 200
    assert 'value="1"' in selector_fragment
    assert 'ready.csv' in selector_fragment
    assert 'value="2"' not in selector_fragment
    assert 'stopped.csv' not in selector_fragment


def test_dashboard_selector_excludes_mapping_and_other_dataset_types(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("cdr-data.csv", BytesIO(b"Mean_Data_Rate,Operator\n12.5,EE\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "mapping_vodafone"},
        files={"dataset_files": ("VFUK.csv", BytesIO(b"eNodeB ID,Local Cell ID,OP/ Vendor\n1,1,Ericsson\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/datasets-analysis?dataset_id=2")
    selector_fragment = response.text.split('data-dataset-select', 1)[1].split('</select>', 1)[0]
    assert 'cdr-data.csv' in selector_fragment
    assert 'VFUK.csv' not in selector_fragment
    assert 'All CDR Types' in response.text


def test_dashboard_ignores_non_ready_dataset_id_in_selector_flow(client) -> None:
    login(client)

    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("ready.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("failed.csv", BytesIO(b"market,period,score\nDE,2026-Q2,78\n"), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(2, status="failed", progress=100, last_error="broken")

    response = client.get("/datasets-analysis?dataset_id=2")
    selector_fragment = response.text.split('data-dataset-select', 1)[1].split('</select>', 1)[0]
    assert response.status_code == 200
    assert 'option value="1"' in selector_fragment
    assert 'option value="2"' not in selector_fragment


def test_reporting_preselects_two_latest_ready_cdrs_of_each_type(client) -> None:
    login(client)
    uploads = [
        ('old-data.csv', 'data', b'Mean_Data_Rate,RAT_A\n10,ENDC\n'),
        ('voice.csv', 'voice', b'Call_Setup_Time,RAT_A\n1.2,ENDC\n'),
        ('latest-data.csv', 'data', b'Mean_Data_Rate,RAT_A\n20,ENDC\n'),
        ('speech.csv', 'speech', b'LQ,RAT_A\n3.8,ENDC\n'),
    ]
    for filename, kind, content in uploads:
        response = client.post(
            '/datasets-analysis/upload',
            data={'dataset_kinds': kind},
            files={'dataset_files': (filename, BytesIO(content), 'text/csv')},
            follow_redirects=False,
        )
        assert response.status_code == 303

    reporting = client.get('/reporting')
    data_select = reporting.text.split('name="data_dataset_id"', 1)[1].split('</select>', 1)[0]
    voice_select = reporting.text.split('name="voice_dataset_id"', 1)[1].split('</select>', 1)[0]
    speech_select = reporting.text.split('name="speech_dataset_id"', 1)[1].split('</select>', 1)[0]

    assert 'value="3" data-vendor-mapped="false" data-uploaded-at=' in data_select
    assert 'selected>latest-data.csv' in data_select
    assert 'value="1" data-vendor-mapped="false" data-uploaded-at=' in data_select
    assert 'selected>old-data.csv' in data_select
    assert data_select.count(' selected>') == 2
    assert 'value="2" data-vendor-mapped="false" data-uploaded-at=' in voice_select
    assert 'selected>voice.csv' in voice_select
    assert voice_select.count(' selected>') == 1
    assert 'value="4" data-vendor-mapped="false" data-uploaded-at=' in speech_select
    assert 'selected>speech.csv' in speech_select
    assert speech_select.count(' selected>') == 1
    assert 'if (active) catalogue.value = active.value;' in reporting.text


def test_dashboard_explicit_dataset_id_overrides_mismatched_input_kind_filter(client) -> None:
    login(client)

    client.post(
        "/datasets-analysis/upload",
        files={"dataset_files": ("voice.csv", BytesIO(b"POLQA_LQ_Avg,market,period\n4.2,ES,2026-Q1\n"), "text/csv")},
        follow_redirects=False,
    )
    client.post(
        "/datasets-analysis/upload",
        files={"dataset_files": ("data.csv", BytesIO(b"Mean_Data_Rate,market,period,test_name,vendor,region\n25.1,DE,2026-Q2,Speed,Nokia,North\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/datasets-analysis?dataset_id=2&input_kind=voice")
    assert response.status_code == 200
    assert "<h2>data.csv</h2>" in response.text
    assert 'option value="2" data-dataset-kind="data" selected' in response.text


def test_dashboard_data_filters_show_test_name_between_vendor_and_region(client) -> None:
    login(client)

    client.post(
        "/datasets-analysis/upload",
        files={"dataset_files": ("data.csv", BytesIO(b"Mean_Data_Rate,market,period,test_name,vendor,region\n25.1,DE,2026-Q2,Speed,Nokia,North\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/datasets-analysis?dataset_id=1")
    assert response.status_code == 200
    vendor_pos = response.text.index("Vendor")
    test_name_pos = response.text.index("Test Name")
    region_pos = response.text.index("Region")
    assert vendor_pos < test_name_pos < region_pos


def test_admin_can_update_user_identity_fields(client) -> None:
    login(client)

    create_response = client.post(
        "/admin/users",
        data={"username": "analyst", "password": "start123", "role": "user"},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    import src.DashboardAnalytic as app_module

    users = app_module.repository.list_users()
    analyst = next(row for row in users if row["username"] == "analyst")

    update_response = client.post(
        f"/admin/users/{analyst['id']}/update",
        data={"username": "analyst-updated", "password": "newpass456", "role": "admin"},
        headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
    )
    assert update_response.status_code == 200
    assert update_response.json()['user'] == {
        'id': analyst['id'], 'username': 'analyst-updated', 'role': 'admin', 'active': False, 'workspace_ids': [],
    }

    updated = app_module.repository.get_user("analyst-updated")
    assert updated is not None
    assert next(row for row in app_module.repository.list_users() if row['username'] == 'analyst-updated')['id'] == analyst['id']
    assert updated.role == "admin"
    assert updated.active is False
    assert app_module.verify_password("newpass456", updated.password_hash)


def test_automatic_user_field_update_preserves_the_canonical_username(client) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    created = client.post(
        '/admin/users',
        data={'username': 'analyst', 'password': 'start123', 'role': 'user'},
        follow_redirects=False,
    )
    assert created.status_code == 303
    analyst = next(row for row in app_module.repository.list_users() if row['username'] == 'analyst')

    response = client.post(
        f"/admin/users/{analyst['id']}/update",
        data={'username': 'admin', 'password': '', 'role': 'admin', 'active': '1', 'edited_field': 'role'},
        headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
    )
    assert response.status_code == 200
    assert response.json()['user']['username'] == 'analyst'
    assert response.json()['user']['role'] == 'admin'


def test_admin_can_delete_user(client) -> None:
    login(client)

    create_response = client.post(
        "/admin/users",
        data={"username": "temporary", "password": "temp123", "role": "user"},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    import src.DashboardAnalytic as app_module

    user_row = next(row for row in app_module.repository.list_users() if row["username"] == "temporary")
    delete_response = client.post(f"/admin/users/{user_row['id']}/delete", follow_redirects=False)
    assert delete_response.status_code == 303
    assert app_module.repository.get_user("temporary") is None


def test_password_reset_uses_the_expected_account_defaults(client) -> None:
    import src.DashboardAnalytic as app_module

    login_super(client)
    custom = client.post(
        '/admin/users',
        data={'username': 'analyst', 'password': 'initial-password', 'role': 'user'},
        follow_redirects=False,
    )
    assert custom.status_code == 303

    expected_passwords = {
        'super': 'super123',
        'admin': 'admin123',
        'demo': 'demo123',
        'analyst': 'Ericsson123',
    }
    for username, expected_password in expected_passwords.items():
        record = next(row for row in app_module.repository.list_users() if row['username'] == username)
        app_module.repository.update_password(username, 'different-password')
        response = client.post(f"/admin/users/{record['id']}/reset-password", follow_redirects=False)
        assert response.status_code == 303
        assert app_module.verify_password(expected_password, app_module.repository.get_user(username).password_hash)


def test_admin_cannot_delete_current_signed_in_user(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    admin_row = next(row for row in app_module.repository.list_users() if row["username"] == "admin")
    response = client.post(f"/admin/users/{admin_row['id']}/delete")
    assert response.status_code == 400
    assert "You cannot delete the current signed-in admin user" in response.text


def test_super_admin_cannot_demote_or_deactivate_last_active_super_admin(client) -> None:
    login_super(client)

    import src.DashboardAnalytic as app_module

    admin_row = next(row for row in app_module.repository.list_users() if row["username"] == "super")
    response = client.post(
        f"/admin/users/{admin_row['id']}/update",
        data={"username": "super", "password": "", "role": "user"},
    )
    assert response.status_code == 400
    assert "At least one active super-admin must remain" in response.text

    response = client.post(
        f"/admin/users/{admin_row['id']}/update",
        data={"username": "super", "password": "", "role": "admin"},
    )
    assert response.status_code == 400
    assert "At least one active super-admin must remain" in response.text


def test_admin_cannot_delete_super_admin_even_if_not_current_user(client) -> None:
    login_super(client)

    import src.DashboardAnalytic as app_module

    create_response = client.post(
        "/admin/users",
        data={"username": "backup-admin", "password": "backup123", "role": "admin"},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    users = app_module.repository.list_users()
    backup_admin = next(row for row in users if row["username"] == "backup-admin")
    admin_row = next(row for row in users if row["username"] == "super")

    switch_session = client.post(
        "/login",
        data={"username": "backup-admin", "password": "backup123"},
        follow_redirects=False,
    )
    assert switch_session.status_code == 303

    disable_backup = client.post(
        f"/admin/users/{backup_admin['id']}/update",
        data={"username": "backup-admin", "password": "", "role": "admin"},
        follow_redirects=False,
    )
    assert disable_backup.status_code == 303

    response = client.post(f"/admin/users/{admin_row['id']}/delete")
    assert response.status_code == 403
    assert "Only super-admins can assign or modify super-admin accounts" in response.text


def test_admin_cannot_assign_or_modify_super_admin_roles(client) -> None:
    login(client)

    create_super = client.post(
        "/admin/users",
        data={"username": "forbidden-super", "password": "password123", "role": "super-admin"},
    )
    assert create_super.status_code == 400
    assert "Only super-admins can create super-admin users" in create_super.text

    created = client.post(
        "/admin/users",
        data={"username": "managed-user", "password": "password123", "role": "user"},
        follow_redirects=False,
    )
    assert created.status_code == 303

    import src.DashboardAnalytic as app_module

    managed_user = next(row for row in app_module.repository.list_users() if row["username"] == "managed-user")
    promoted = client.post(
        f"/admin/users/{managed_user['id']}/update",
        data={"username": "managed-user", "password": "", "role": "super-admin", "active": "1"},
    )
    assert promoted.status_code == 403
    assert "Only super-admins can assign or modify super-admin accounts" in promoted.text

    super_row = next(row for row in app_module.repository.list_users() if row["username"] == "super")
    modified_super = client.post(
        f"/admin/users/{super_row['id']}/update",
        data={"username": "renamed-super", "password": "forbidden-password", "role": "admin", "active": "1"},
    )
    assert modified_super.status_code == 403
    assert "Only super-admins can assign or modify super-admin accounts" in modified_super.text
    assert app_module.repository.get_user('renamed-super') is None
    assert app_module.repository.get_user('super') is not None
    assert app_module.verify_password('super123', app_module.repository.get_user('super').password_hash)

    deleted_super = client.post(f"/admin/users/{super_row['id']}/delete")
    assert deleted_super.status_code == 403
    assert "Only super-admins can assign or modify super-admin accounts" in deleted_super.text


def test_top_navigation_shows_document_links(client) -> None:
    login(client)
    response = client.get("/workspace")
    assert response.status_code == 200
    assert "<h1>Dashboard Analytic</h1>" in response.text
    assert f"v{__version__} · {__release_date__}" in response.text
    assert 'href="/documents/view/readme"' in response.text
    assert 'href="/documents/view/changelog"' in response.text
    assert 'href="/documents/view/help"' in response.text
    assert 'target="_blank"' not in response.text
    assert 'href="/datasets-analysis"' in response.text
    assert 'class="module-tabs"' in response.text
    assert 'class="module-tabs-secondary"' in response.text
    assert 'data-module-navigator' in response.text
    assert '>Main Modules</h4>' in response.text
    assert '>Administrative Modules</h4>' in response.text
    assert '>Documentation</h4>' in response.text
    assert '>Workspace Management</a>' in response.text
    assert '>Dataset Analysis</a>' in response.text
    assert '>E2E Dashboard</a>' in response.text
    assert '>E2E Reporting</a>' in response.text
    assert '>Chart Builder</a>' in response.text
    assert '>Administrator Panel</a>' in response.text
    assert '>Configuration Panel</a>' in response.text
    assert '>Application Logs</a>' in response.text
    assert '>Help</a>' in response.text
    assert '>Readme</a>' in response.text
    assert '>Changelog</a>' in response.text
    assert 'module-hero-datasets-analysis' not in response.text
    assert 'class="module-tab module-tab-workspace active" href="/workspace"' in response.text
    assert '<span class="module-tab-label-desktop">E2E Reporting</span>' in response.text
    assert 'title="Open Changelog"' in response.text
    assert '<span class="module-tab-label-mobile">Reporting</span>' in response.text
    assert '<span class="module-tab-label-mobile">Analysis</span>' in response.text
    assert 'href="/logout"' in response.text
    assert '<span class="topnav-link topnav-user-badge topnav-user-badge-admin">User: admin (admin)</span>' in response.text

    dashboard = client.get("/datasets-analysis")
    assert dashboard.status_code == 200
    assert 'module-hero-datasets-analysis' in dashboard.text
    assert 'linear-gradient(135deg, #0c4c8c, #68b8ff)' in dashboard.text

    reporting = client.get("/reporting")
    assert reporting.status_code == 200
    assert 'module-hero-reporting' in reporting.text
    assert 'linear-gradient(135deg, #4b208a, #bd90ff)' in reporting.text

    admin = client.get("/admin")
    assert admin.status_code == 200
    assert 'module-hero-admin' in admin.text
    assert 'linear-gradient(135deg, #ff8070, #861919)' in admin.text


def test_collapsed_side_navigators_reveal_near_viewport_edges() -> None:
    root = Path(__file__).parents[1]
    app_script = (root / 'src/web_interface/static/js/app.js').read_text(encoding='utf-8')
    app_styles = (root / 'src/web_interface/static/css/app.css').read_text(encoding='utf-8')

    assert 'function setupEdgeNavigatorReveal() {' in app_script
    assert "'.page-panel-navigator, .help-navigator, .release-navigator'" in app_script
    assert "event.pointerType !== 'mouse'" in app_script
    assert "['touch', 'pen'].includes(event.pointerType)" in app_script
    assert "navigator.classList.add('is-edge-revealed')" in app_script
    assert 'const autoHideDelay = 5000;' in app_script
    assert "navigator.classList.remove('is-open', 'is-edge-revealed');" in app_script
    assert "navigator.contains(document.activeElement) && (forceBlur || lastInteraction !== 'keyboard')" in app_script
    assert 'navigators.forEach((navigator) => closeNavigator(navigator, true));' in app_script
    assert "window.addEventListener('scroll', hideAll, {passive: true});" in app_script
    assert "lastInteraction === 'mouse' && navigator.matches(':hover')" in app_script
    assert 'if (navigator.classList.contains(\'is-open\')) scheduleClose(navigator);' in app_script
    assert 'setupEdgeNavigatorReveal();' in app_script
    assert ':not(.is-edge-revealed):not(:has(:focus-visible)) .page-panel-navigator-tab {' in app_styles
    assert 'transform:translate(calc(-100% + .32rem),-50%);' in app_styles
    assert 'transform:translate(calc(100% - .32rem),-50%);' in app_styles
    assert '.is-edge-revealed :is(.page-panel-navigator-tab,.help-navigator-tab,.release-navigator-tab)' in app_styles
    assert ':has(:focus-visible) :is(.page-panel-navigator-tab,.help-navigator-tab,.release-navigator-tab)' in app_styles


def test_non_admin_navigation_hides_admin_tab(client) -> None:
    response = client.post("/login", data={"username": "demo", "password": "demo123"}, follow_redirects=False)
    assert response.status_code == 303

    workspace = client.get("/workspace")
    assert workspace.status_code == 200
    assert 'class="module-tabs-secondary"' in workspace.text
    assert 'href="/documents/view/readme"' in workspace.text
    assert 'href="/documents/view/changelog"' in workspace.text
    assert 'href="/documents/view/help"' in workspace.text
    assert 'href="/admin"' not in workspace.text
    assert 'data-module-navigator' in workspace.text
    assert '>Administrator Panel</span>' in workspace.text
    assert '>Configuration Panel</span>' in workspace.text
    assert 'User: demo' in workspace.text


def test_admin_imports_report_catalogue(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    content = (
        ','.join(CATALOG_HEADERS)
            + '\n8,Completed Call Ratio,Voice quality,Title and 1 column + Comments,Completed call ratio,CDR-Voice,Call_Status,100% Stacked Vertical Bars,Call Family = VoLTE,Operator,Campaign,Completed/Dropped/Failed,,,,\n'
    ).encode('utf-8')

    response = client.post(
        '/admin/report-templates/nsa',
        data={'catalogue_name': 'Test baseline'},
        files={'catalogue_file': ('nsa-slides-template.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert app_module.reporting_catalog_content('nsa') == content

    exported = client.get('/admin/report-templates/nsa/export')
    assert exported.status_code == 200
    assert exported.content == content

    confirmation = client.get('/admin?catalogue_notice=Imported%20Test%20baseline%20%28NSA%29.')
    assert 'data-catalogue-import-notice' in confirmation.text
    assert 'catalogue-management-notice' not in confirmation.text
    assert 'id="info-overlay"' in confirmation.text


def test_admin_import_preserves_hyphens_in_uploaded_template_name(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    content = (
        ','.join(CATALOG_HEADERS)
        + '\n1,Imported template,,Title and 1 column + Comments,,,,Title Slide,,,,,\n'
    ).encode('utf-8')
    response = client.post(
        '/admin/slides-templates/import', data={'template_type': 'nsa', 'catalogue_name': ''},
        files={'catalogue_file': ('NSA Slide Template - Gabriele.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert app_module.repository.report_template_content('nsa', 'NSA Slide Template - Gabriele') == content


def test_importing_an_existing_template_requires_explicit_overwrite(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    original = (','.join(CATALOG_HEADERS) + '\n' + ','.join(['1', 'Original', '', 'Title and 1 column + Comments', '', '', '', 'Title Slide', '', '', '', '', '']) + '\n').encode('utf-8')
    replacement = (','.join(CATALOG_HEADERS) + '\n' + ','.join(['1', 'Replacement', '', 'Title and 1 column + Comments', '', '', '', 'Title Slide', '', '', '', '', '']) + '\n').encode('utf-8')
    created = client.post(
        '/admin/slides-templates/import', data={'template_type': 'nsa', 'catalogue_name': 'Shared Template'},
        files={'catalogue_file': ('Shared Template.csv', BytesIO(original), 'text/csv')}, follow_redirects=False,
    )
    assert created.status_code == 303

    blocked = client.post(
        '/admin/slides-templates/import', data={'template_type': 'nsa', 'catalogue_name': 'shared template'},
        files={'catalogue_file': ('shared template.csv', BytesIO(replacement), 'text/csv')}, follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert 'Confirm+overwrite' in blocked.headers['location']
    assert b'Original' in app_module.repository.report_template_content('nsa', 'Shared Template')

    overwritten = client.post(
        '/admin/slides-templates/import',
        data={'template_type': 'nsa', 'catalogue_name': 'shared template', 'overwrite_existing': 'true'},
        files={'catalogue_file': ('shared template.csv', BytesIO(replacement), 'text/csv')}, follow_redirects=False,
    )
    assert overwritten.status_code == 303
    assert 'Overwrote+Shared+Template' in overwritten.headers['location']
    assert b'Replacement' in app_module.repository.report_template_content('nsa', 'Shared Template')
    assert b'Replacement' in app_module.reporting_catalog_content('nsa')


def test_admin_import_converts_a_legacy_catalogue_when_requested(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    legacy = (
        'Slide,Slide title,Slide subtitle,Layout,CDR Source,KPI,Chart Type,Filters,Grouping\n'
        '8,Legacy quality,,Title and 1 column + Comments,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator × Campaign\n'
    ).encode('utf-8')

    response = client.post(
        '/admin/report-templates/nsa',
        data={'catalogue_name': 'Legacy baseline', 'convert_catalogue': '1'},
        files={'catalogue_file': ('legacy.csv', BytesIO(legacy), 'text/csv')},
        follow_redirects=False,
    )

    assert response.status_code == 303
    stored = app_module.reporting_catalog_content('nsa').decode('utf-8')
    assert 'Chart Tittle' in stored
    assert 'Legacy quality' in stored


def test_admin_stores_multiple_named_report_catalogues_and_can_activate_one(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    first = (','.join(CATALOG_HEADERS) + '\n8,First,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,\n').encode('utf-8')
    second = (','.join(CATALOG_HEADERS) + '\n8,Second,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,\n').encode('utf-8')

    for name, content in [('Baseline Q4', first), ('Updated Q4', second)]:
        response = client.post(
            '/admin/report-templates/nsa',
            data={'catalogue_name': name},
            files={'catalogue_file': ('nsa.csv', BytesIO(content), 'text/csv')},
            follow_redirects=False,
        )
        assert response.status_code == 303

    admin = client.get('/admin')
    assert 'Baseline Q4' in admin.text
    assert 'Updated Q4' in admin.text
    assert 'name="catalogue_selection"' not in admin.text
    assert 'data-admin-template-editor' in admin.text
    assert 'data-open-template-editor="/admin/report-templates/nsa/Baseline%20Q4/editor"' in admin.text
    assert 'data-catalogue-editor-table' not in admin.text
    assert '<th>Default</th>' in admin.text
    assert 'catalogue-default-mark is-default' in admin.text
    assert '/admin/report-templates/nsa/Baseline Q4/export' in admin.text
    assert app_module.reporting_catalog_entries('nsa')[0].slide_title == 'Second'
    assert next(item['identifier'] for item in app_module.report_catalogue_options('nsa') if item['active']) == 'Updated Q4'
    assert app_module.repository.report_template_content('nsa', 'Baseline Q4') == first

    reporting = client.get('/reporting')
    assert 'value="nsa:Updated Q4" data-catalogue-technology="nsa" data-catalogue-active="true" selected' in reporting.text
    assert 'data-report-charts-edit-template' in reporting.text
    assert 'data-report-chart-viewer-edit-template' in reporting.text
    assert 'data-report-template-editor-frame' in reporting.text

    editor = client.get('/admin?catalogue_technology=nsa&catalogue_id=Baseline%20Q4')
    assert editor.status_code == 200
    assert 'data-catalogue-editor-table' not in editor.text
    assert 'data-admin-template-editor' in editor.text

    embedded_editor = client.get('/admin/report-templates/nsa/Baseline%20Q4/editor')
    assert embedded_editor.status_code == 200
    assert 'data-embedded-template-editor' in embedded_editor.text
    assert 'data-catalogue-editor-table' in embedded_editor.text
    assert 'Slides Templates Management' not in embedded_editor.text
    assert 'Import / Export / Transfer' not in embedded_editor.text
    assert 'data-catalogue-field="Layout"' in embedded_editor.text
    assert 'data-catalogue-editor-options' in embedded_editor.text
    assert 'data-catalogue-editor-kpi-aggregation' in embedded_editor.text
    assert '<option value="COUNTD">COUNTD</option>' in embedded_editor.text
    assert '<th class="catalogue-slide-actions-heading">Slide Actions</th>' in embedded_editor.text
    assert '<th class="catalogue-chart-actions-heading">Chart Actions</th>' in embedded_editor.text
    assert 'data-catalogue-slide-actions' in embedded_editor.text
    assert 'data-catalogue-chart-actions' in embedded_editor.text
    assert 'data-template-copy-url=' in embedded_editor.text
    assert 'data-manage-calculated-dimensions' in embedded_editor.text
    assert 'data-calculated-dimensions-url=' in embedded_editor.text
    assert 'catalogue-chart-preview-header-actions' in embedded_editor.text
    assert embedded_editor.text.index('data-catalogue-chart-preview-manage-dimensions') < embedded_editor.text.index('data-catalogue-chart-preview-close')
    assert 'data-catalogue-row-index="0"' in embedded_editor.text
    assert 'data-catalogue-reenumerate' in embedded_editor.text
    assert 'Title and 1 column + Comments' in embedded_editor.text
    assert 'catalogue-editor-catalogue-picker" aria-label="Workspace templates" hidden' in embedded_editor.text

    app_script = (app_module.PROJECT_ROOT / 'src/web_interface/static/js/app.js').read_text(encoding='utf-8')
    assert "fetch(editor.dataset.calculatedDimensionsUrl, {credentials: 'same-origin', cache: 'no-store'})" in app_script
    assert 'window.top.location.origin === window.location.origin' in app_script
    assert 'managerDocument.body.append(overlay)' in app_script
    assert "expressionLabel.textContent = 'IF expression'" in app_script
    assert app_script.count('await returnToList(false);') == 2
    assert app_script.count('else void returnToList();') >= 2
    assert 'data-materialization-job-key' in app_script
    assert 'progressJobList.replaceChildren();' not in app_script
    assert 'Math.max(previousPercent, computedPercent)' in app_script

    copy_options = client.get('/api/admin/report-templates/copy-options')
    assert copy_options.status_code == 200
    assert {(item['technology'], item['identifier']) for item in copy_options.json()['templates']} >= {
        ('nsa', 'Baseline Q4'), ('nsa', 'Updated Q4'),
    }
    dimensions = app_module.calculated_dimensions_json(app_module.load_workspace_calculated_dimensions())
    dimensions.append({
        'name': 'Network Result', 'sources': ['cdr-data'], 'default': 'Other', 'default_from': '',
        'rules': [{'when': 'Test_Result IN (Completed)', 'value': 'Success'}],
    })
    saved_dimensions = client.put(
        '/api/admin/report-templates/nsa/Baseline%20Q4/calculated-dimensions',
        json={'dimensions': dimensions},
    )
    assert saved_dimensions.status_code == 200
    assert any(item['name'] == 'Network Result' for item in saved_dimensions.json()['dimensions'])
    filter_values = client.get(
        '/admin/catalogue-filter-values',
        params={'source': 'cdr-data', 'column': 'Network Result', 'technology': 'nsa', 'catalogue_id': 'Baseline Q4'},
    )
    assert filter_values.status_code == 200
    assert filter_values.json()['values'] == ['Other', 'Success']
    assert any(
        item.name == 'Network Result'
        for item in app_module.load_workspace_calculated_dimensions()
    )
    copied_chart = client.post('/admin/report-templates/nsa/Baseline%20Q4/copy-items', json={
        'kind': 'chart', 'catalogue_content': first.decode(), 'source_row_index': 0,
        'target_technology': 'nsa', 'target_identifier': 'Updated Q4',
        'target_slide_index': 0, 'chart_position': 1,
    })
    assert copied_chart.status_code == 200
    assert len(app_module.load_template_catalogue(app_module.repository.report_template_content('nsa', 'Updated Q4'), 'nsa')) == 2
    copied_slide = client.post('/admin/report-templates/nsa/Baseline%20Q4/copy-items', json={
        'kind': 'slide', 'catalogue_content': first.decode(), 'source_row_index': 0,
        'target_technology': 'nsa', 'target_identifier': 'Updated Q4', 'slide_position': 1,
    })
    assert copied_slide.status_code == 200
    copied_entries = app_module.load_template_catalogue(app_module.repository.report_template_content('nsa', 'Updated Q4'), 'nsa')
    assert len(copied_entries) == 3
    assert sorted({entry.slide for entry in copied_entries}) == [1, 2]

    edited = (
        ','.join(CATALOG_HEADERS)
        + '\n9,Late,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,Right\n'
        + '\n8,Edited,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,Right\n'
    )
    saved = client.post('/admin/report-templates/nsa/Baseline%20Q4/save', data={'catalogue_content': edited}, follow_redirects=False)
    assert saved.status_code == 303
    saved_editor = client.get('/admin/report-templates/nsa/Baseline%20Q4/editor')
    assert '>Edited</td>' in saved_editor.text
    assert saved_editor.text.index('>Edited</td>') < saved_editor.text.index('>Late</td>')

    saved_in_background = client.post(
        '/admin/report-templates/nsa/Baseline%20Q4/save',
        data={'catalogue_content': edited},
        headers={'accept': 'application/json'},
    )
    assert saved_in_background.status_code == 200
    assert saved_in_background.json() == {
        'template': 'Baseline Q4',
        'technology': 'nsa',
        'chart_rows': 2,
    }

    activated = client.post('/admin/report-templates/nsa/Baseline%20Q4/activate', follow_redirects=False)
    assert activated.status_code == 303
    assert app_module.reporting_catalog_entries('nsa')[0].slide_title == 'Edited'
    assert next(item['identifier'] for item in app_module.report_catalogue_options('nsa') if item['active']) == 'Baseline Q4'
    assert app_module.repository.report_template_content('nsa', 'Updated Q4')

    protected_delete = client.post('/admin/report-templates/nsa/Baseline%20Q4/delete')
    assert protected_delete.status_code == 400
    assert 'The default template cannot be deleted.' in protected_delete.text

    reporting_after_activation = client.get('/reporting')
    assert 'value="nsa:Baseline Q4" data-catalogue-technology="nsa" data-catalogue-active="true" selected' in reporting_after_activation.text

    exported = client.get('/admin/report-templates/nsa/Updated%20Q4/export')
    assert exported.status_code == 200
    assert b'Second' in exported.content
    assert 'filename="Updated Q4.csv"' in exported.headers['content-disposition']

    selected_export = client.get('/admin/report-templates/export-selected?catalogue_selection=nsa:Updated%20Q4')
    assert selected_export.status_code == 200
    assert 'filename="Updated Q4.csv"' in selected_export.headers['content-disposition']


def test_reporting_chart_viewer_uses_hover_canvas_dataset_and_zoom_controls(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    reporting = client.get('/reporting')
    assert reporting.status_code == 200
    controls = reporting.text.split('data-report-chart-viewer-canvas-controls', 1)[1].split('</div>', 2)[0]
    assert controls.index('data-report-chart-viewer-data') < controls.index('data-report-chart-zoom="in"')
    assert controls.count('data-report-chart-zoom=') == 2
    assert 'data-report-chart-zoom-reset' in controls
    assert '<span>View filtered dataset</span>' not in reporting.text
    assert "reportChartViewerDataOverlay.hidden = false;" in reporting.text
    assert "reportChartViewerDataPanel.setAttribute('aria-busy', 'true');" in reporting.text
    assert "showLoadingOverlay('Loading Filtered Dataset', 'Please wait while the filtered dataset is prepared.');" in reporting.text
    assert "hideLoadingOverlay();" in reporting.text
    navigation = reporting.text.split('class="report-chart-viewer-navigation"', 1)[1].split('</div>', 1)[0]
    assert 'data-report-chart-zoom' not in navigation
    assert navigation.count('class="report-chart-arrow-icon"') == 4
    assert 'M5 5v14M18 6l-6 6 6 6M12 6l-6 6 6 6' in navigation
    assert 'M19 5v14M6 6l6 6-6 6M12 6l6 6-6 6' in navigation
    assert '⏮' not in navigation
    assert '⏭' not in navigation
    assert "addEventListener('pointerenter', showReportChartViewerControls)" in reporting.text
    assert "addEventListener('pointerleave', hideReportChartViewerControls)" in reporting.text
    assert '}, 3000);' in reporting.text
    assert "querySelector('[data-preview-kpi-aggregation]')?.value" in reporting.text
    assert "`${operation}(${input.value})`" in reporting.text
    css = app_module.PROJECT_ROOT.joinpath(
        'src/web_interface/static/css/app.css',
    ).read_text(encoding='utf-8')
    assert '.report-chart-viewer-canvas-controls { position: absolute; top: 0.6rem; right: 0.6rem;' in css
    assert '.report-chart-viewer-image.is-controls-visible .report-chart-viewer-canvas-controls' in css
    assert '.report-chart-viewer-canvas-data-button { width: 2.5rem;' in css
    assert '.report-chart-viewer-canvas-data-button svg { width: 1.4rem;' in css
    assert '.report-chart-viewer-data-loading { display: grid;' in css
    assert '.report-chart-viewer-data-dialog { position: absolute; inset: 2%;' in css


def test_admin_catalogue_rename_supports_background_json_save(client) -> None:
    import src.DashboardAnalytic as app_module

    login(client)
    default_name = next(item['identifier'] for item in app_module.report_catalogue_options('nsa') if item['active'])
    response = client.post(
        f'/admin/report-templates/nsa/{quote(default_name)}/rename',
        data={'catalogue_name': 'Renamed default'},
        headers={'accept': 'application/json'},
    )

    assert response.status_code == 200
    assert response.json() == {'name': 'Renamed default', 'identifier': 'Renamed default'}
    assert next(item for item in app_module.report_catalogue_options('nsa') if item['identifier'] == 'Renamed default')['name'] == 'Renamed default'


def test_admin_renaming_named_catalogue_renames_its_csv_file(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    content = (
        ','.join(CATALOG_HEADERS)
        + '\n8,First,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,\n'
    ).encode('utf-8')
    imported = client.post(
        '/admin/report-templates/nsa',
        data={'catalogue_name': 'Original catalogue'},
        files={'catalogue_file': ('nsa.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )
    assert imported.status_code == 303

    app_module.repository.set_workspace_state('e2e_dashboards_v2', json.dumps({
        'template-rename-dashboard': {
            'name': 'Original catalogue · Validation', 'template': 'Original catalogue',
            'technology': 'nsa', 'template_technology': 'nsa',
        },
    }))

    replacement = client.post(
        '/admin/report-templates/nsa',
        data={'catalogue_name': 'Replacement template'},
        files={'catalogue_file': ('replacement.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )
    assert replacement.status_code == 303

    response = client.post(
        '/admin/report-templates/nsa/Original%20catalogue/rename',
        data={'catalogue_name': 'Renamed catalogue'},
        headers={'accept': 'application/json'},
    )

    assert response.status_code == 200
    assert response.json() == {'name': 'Renamed catalogue', 'identifier': 'Renamed catalogue'}
    assert all(str(row['name']) != 'Original catalogue' for row in app_module.repository.list_report_templates('nsa'))
    assert app_module.repository.report_template_content('nsa', 'Renamed catalogue') == content
    assert not next(item for item in app_module.report_catalogue_options('nsa') if item['identifier'] == 'Renamed catalogue')['active']
    renamed_dashboard = json.loads(app_module.repository.get_workspace_state('e2e_dashboards_v2'))['template-rename-dashboard']
    assert renamed_dashboard['template'] == 'Renamed catalogue'
    assert renamed_dashboard['name'] == 'Renamed catalogue · Validation'


def test_admin_duplicates_template_using_the_source_template_name(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    content = (
        ','.join(CATALOG_HEADERS)
        + '\n8,First,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,\n'
    ).encode('utf-8')
    imported = client.post(
        '/admin/report-templates/nsa',
        data={'catalogue_name': 'Regional NSA Template'},
        files={'catalogue_file': ('nsa.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )
    assert imported.status_code == 303

    duplicated = client.post('/admin/report-templates/nsa/Regional%20NSA%20Template/duplicate', follow_redirects=False)

    assert duplicated.status_code == 303
    copied = next(item for item in app_module.report_catalogue_options('nsa') if item['identifier'] == 'Regional NSA Template - Copy')
    assert copied['name'] == 'Regional NSA Template - Copy'
    assert copied['content'] == content


def test_template_registry_does_not_rescan_legacy_csv_directories(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    library_dir = app_module.settings.slides_templates_dir / 'library' / 'nsa'
    library_dir.mkdir(parents=True, exist_ok=True)
    content = (
        ','.join(CATALOG_HEADERS)
        + '\n8,First,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,\n'
    ).encode('utf-8')
    (library_dir / 'Historic baseline.csv').write_bytes(content)

    assert all(
        item['identifier'] != 'Historic baseline'
        for item in app_module.report_catalogue_options('nsa')
    )


def test_template_registry_ignores_unregistered_library_csvs(client) -> None:
    import src.DashboardAnalytic as app_module

    rogue = app_module.settings.slides_templates_dir / 'library' / 'nsa' / 'nsa NSA Slide Template slides template.csv'
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_bytes(app_module.catalogue_csv([]))

    assert all(item['identifier'] != rogue.stem for item in app_module.report_catalogue_options('nsa'))


def test_admin_importer_selects_template_type_and_moves_a_named_template(client) -> None:
    from src.modules.cdr_reporting import CATALOG_HEADERS
    import src.DashboardAnalytic as app_module

    login(client)
    content = (
        ','.join(CATALOG_HEADERS)
        + '\n8,First,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,\n'
    ).encode('utf-8')
    imported_sa = client.post(
        '/admin/slides-templates/import',
        data={'template_type': 'sa', 'catalogue_name': 'SA imported template'},
        files={'catalogue_file': ('sa.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )
    assert imported_sa.status_code == 303
    assert next(item['identifier'] for item in app_module.report_catalogue_options('sa') if item['active']) == 'SA imported template'

    # Add two NSA templates: the second becomes default, so the first remains
    # a movable library item.
    for name in ('Move me', 'NSA default replacement'):
        response = client.post(
            '/admin/report-templates/nsa',
            data={'catalogue_name': name},
            files={'catalogue_file': ('nsa.csv', BytesIO(content), 'text/csv')},
            follow_redirects=False,
        )
        assert response.status_code == 303
    moved = client.post(
        '/admin/report-templates/nsa/Move%20me/type',
        data={'template_type': 'sa'},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    assert app_module.repository.report_template_content('sa', 'Move me') == content
    assert all(str(row['name']) != 'Move me' for row in app_module.repository.list_report_templates('nsa'))


def test_docs_routes_expose_readme_changelog_and_help(client) -> None:
    login(client)

    readme_view = client.get("/documents/view/readme")
    assert readme_view.status_code == 200
    assert "Loading document..." in readme_view.text
    assert "/api/documents/readme" in readme_view.text
    assert '>Readme<' in readme_view.text

    changelog_api = client.get("/api/documents/changelog")
    assert changelog_api.status_code == 200
    payload = changelog_api.json()
    assert payload["name"] == "CHANGELOG.md"
    assert "0.1.0" in payload["content"]
    changelog_view = client.get("/documents/view/changelog")
    assert changelog_view.status_code == 200
    assert 'changelog-nav-list' in changelog_view.text
    assert 'class="doc-layout"' in changelog_view.text
    assert 'makeChangelogReleasesCollapsible' in changelog_view.text
    assert 'collapseOthers' in changelog_view.text
    changelog_index = client.get('/api/documents/changelog-index')
    assert changelog_index.status_code == 200
    assert changelog_index.json()['releases'][0] == {
        'version': __version__, 'id': f'release-v{__version__}',
    }

    help_view = client.get("/documents/view/help")
    assert help_view.status_code == 200
    assert "/api/documents/help" in help_view.text
    assert '>Documentation<' in help_view.text

    help_api = client.get("/api/documents/help")
    assert help_api.status_code == 200
    assert help_api.json()["name"] == "00-help.md"

    help_index = client.get("/api/documents/help-index")
    assert help_index.status_code == 200
    help_documents = help_index.json()["documents"]
    assert help_documents[0]["relative_path"] == "00-help.md"
    assert help_documents[0]["number"] == "00"
    assert help_documents[1]["label"] == "Product Overview"
    assert help_documents[2]["label"] == "Technical Considerations"
    assert any(item["relative_path"] == "04-web-interface.md" for item in help_documents)
    assert any(
        item["relative_path"] == "06-datasets-analysis.md"
        and item["label"] == "Datasets Analysis"
        for item in help_documents
    )
    assert any(
        item["relative_path"] == "08-e2e-reporting.md"
        and item["label"] == "E2E Reporting"
        for item in help_documents
    )
    assert any(
        item["relative_path"] == "09-chart-builder.md"
        and item["label"] == "Chart Builder"
        for item in help_documents
    )
    assert any(
        item["relative_path"] == "10-query-builder.md"
        and item["label"] == "Query Builder"
        for item in help_documents
    )
    assert [item['relative_path'] for item in help_documents[9:]] == [
        '09-chart-builder.md',
        '10-query-builder.md',
        '11-administration.md',
        '12-docker-deployment.md',
        '13-project-structure.md',
        '14-roadmap.md',
    ]
    excluded_help_documents = {
        "02-arguments-description.md",
        "02-arguments-description-short.md",
        "05-word-reporting.md",
        "09-github-actions.md",
        "10-testing.md",
    }
    assert not excluded_help_documents.intersection(item["relative_path"] for item in help_documents)

    help_article = client.get("/documents/view/help/04-web-interface.md")
    assert help_article.status_code == 200
    assert 'id="help-nav-list"' in help_article.text
    assert "/api/documents/help/04-web-interface.md" in help_article.text
    assert "`${number}. ${label}`" in help_article.text
    assert "includeHeadingIds: true" in help_article.text
    assert "const fragment = hashIndex >= 0 ? raw.slice(hashIndex) : '';" in help_article.text
    assert "document.getElementById(targetId)?.scrollIntoView" in help_article.text


def test_dashboard_analysis_reuses_cached_result_on_reload(client, monkeypatch) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    calls = {"count": 0}
    original_load_dataset = app_module.load_dataset
    app_module.ANALYSIS_CACHE.clear()
    app_module.DATAFRAME_CACHE.clear()
    assert app_module.repository.dataset_rows_table_exists(1)

    def counting_load_dataset(path):
        calls["count"] += 1
        return original_load_dataset(path)

    monkeypatch.setattr(app_module, "load_dataset", counting_load_dataset)

    first_response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert first_response.status_code == 200
    assert calls["count"] == 0

    second_response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert second_response.status_code == 200
    assert calls["count"] == 0


def test_dashboard_analysis_reuses_cached_dataset_frame_across_metric_changes(client, monkeypatch) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    calls = {"count": 0}
    original_load_dataset = app_module.load_dataset
    app_module.ANALYSIS_CACHE.clear()
    app_module.DATAFRAME_CACHE.clear()
    assert app_module.repository.dataset_rows_table_exists(1)

    def counting_load_dataset(path):
        calls["count"] += 1
        return original_load_dataset(path)

    monkeypatch.setattr(app_module, "load_dataset", counting_load_dataset)

    first_response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert first_response.status_code == 200
    assert calls["count"] == 0

    second_response = client.get("/datasets-analysis?dataset_id=1&metric=gap&aggregation=all&load=1")
    assert second_response.status_code == 200
    assert calls["count"] == 0


def test_dashboard_renders_multiple_selected_metrics(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&metric=gap&aggregation=all&load=1")
    assert response.status_code == 200
    assert "Use the dropdown to select one, several, or all KPIs." in response.text
    assert response.text.count("Metric View") >= 2
    assert response.text.count("Selected Metric") >= 2
    assert "mean metric" in response.text.lower()
    assert "score" in response.text
    assert "gap" in response.text


def test_dashboard_shows_date_range_filters_and_applies_them(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,Call Start Time\n"
        b"ES,2026-Q1,91,2026-07-10 10:00:00\n"
        b"ES,2026-Q1,87,2026-07-11 12:00:00\n"
    )
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&date_from=2026-07-11&load=1")
    assert response.status_code == 200
    assert 'name="date_from"' in response.text
    assert 'name="date_to"' in response.text
    assert 'value="2026-07-11"' in response.text
    assert "2026-07-10" not in response.text


def test_date_filters_are_disabled_and_ignored_when_event_time_filtering_is_disabled(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    monkeypatch.setenv('IGNORE_EVENT_TIME_FILTERING', 'true')
    login(client)
    csv_content = (
        b"market,period,score,Call Start Time\n"
        b"ES,2026-Q1,91,2026-07-10 10:00:00\n"
        b"ES,2026-Q1,87,2026-07-11 12:00:00\n"
    )
    upload_response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': 'data'},
        files={'dataset_files': ('sample.csv', BytesIO(csv_content), 'text/csv')},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get('/datasets-analysis?dataset_id=1&metric=score&date_from=2026-07-11&load=1')

    assert response.status_code == 200
    assert response.text.count('Date filters are disabled because Ignore event time filtering is enabled in Config.') >= 2
    assert 'name="date_from" value="" disabled aria-disabled="true"' in response.text
    assert 'name="date_to" value="" disabled aria-disabled="true"' in response.text
    page, filters, filter_column = app_module._dataset_preview_request({
        'page': 0,
        'column_filters': {'Event_Start_Time': ['2026-07-11 12:00:00']},
        'filter_column': 'Event_End_Time',
    }, ['Event_Start_Time', 'Event_End_Time'])
    assert page == 0
    assert filters == {'Event_Start_Time': ['2026-07-11 12:00:00']}
    assert filter_column == 'Event_End_Time'


def test_dashboard_adaptive_filters_include_city_and_multi_select_fields(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,City,Region,Operator,Vendor\n"
        b"ES,2026-Q1,91,Madrid,Central,Vodafone UK,Vodafone UK_Ericsson\n"
        b"ES,2026-Q1,87,Barcelona,East,3,3_Ericsson\n"
    )
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample_data.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200
    assert 'select name="city" multiple' in response.text
    assert 'select name="region" multiple' in response.text
    assert 'select name="vendor" multiple' in response.text
    assert 'select name="vendor_only" multiple' in response.text
    assert response.text.index('select name="vendor" multiple') < response.text.index('select name="vendor_only" multiple')
    assert ">Madrid<" in response.text
    assert ">Barcelona<" in response.text
    assert ">Ericsson<" in response.text
    assert response.text.index('>operators<') < response.text.index('>vendors<')
    assert response.text.index('>completed tests<') < response.text.index('>success tests<')
    assert response.text.index('>success tests<') < response.text.index('>failed tests<')
    assert response.text.index('>failed tests<') < response.text.index('>dropped calls<')
    assert response.text.index('>dropped calls<') < response.text.index('>success rate pct<')
    assert "All values are selected by default. Clearing all values applies an empty filter." in response.text


def test_dashboard_adaptive_filters_populate_netcheck_a_columns_for_existing_cdrs(client) -> None:
    login(client)
    csv_content = (
        b"RAT_A,Operator_A,Session_Type_A,Call_Status_A,Call_Duration\n"
        b"ENDC,Vodafone UK,VoLTE,Completed,61\n"
        b"NR,Three UK,VoNR,Dropped,42\n"
    )
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "voice"},
        files={"dataset_files": ("netcheck_voice.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    table_name = app_module.repository.dataset_rows_table_name(1)
    with app_module.repository.connection() as conn:
        conn.execute(
            f'''UPDATE "{table_name}" SET "operator" = NULL, "session_type" = NULL, "status" = NULL'''
        )
        conn.execute(
            """
            UPDATE dataset_profiles
            SET normalization_version = 4, filter_options_json = '{}'
            WHERE dataset_id = 1
            """
        )

    response = client.get("/datasets-analysis?dataset_id=1&metric=Call_Duration&aggregation=all&load=1")
    assert response.status_code == 200
    assert 'select name="operator" multiple' in response.text
    assert 'value="Vodafone UK"' in response.text
    assert 'value="Three UK"' in response.text
    assert 'select name="session_type" multiple' in response.text
    assert 'value="VoLTE"' in response.text
    assert 'value="VoNR"' in response.text


def test_dashboard_adaptive_filters_label_technology_without_primary(client) -> None:
    login(client)
    csv_content = b"market,period,score,RAT\nES,2026-Q1,91,5G\nES,2026-Q1,87,LTE\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200
    assert ">Technology<" in response.text
    assert "Technology Primary" not in response.text


def test_dashboard_comparison_chart_exposes_per_metric_aggregation_override_control(client) -> None:
    login(client)
    csv_content = b"market,period,score,gap,operator,region\nES,2026-Q1,91,2.1,Vodafone,North\nES,2026-Q1,87,3.3,o2,South\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&metric=gap&aggregation=region&aggregation_overrides=score=operator&load=1")
    assert response.status_code == 200
    assert 'data-chart-aggregation-select' in response.text
    assert 'data-metric="score"' in response.text
    assert 'data-current-overrides="score=operator"' in response.text


def test_dashboard_exposes_global_and_per_metric_cdf_comparison_controls(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,vendor,region,operator,city\n"
        b"ES,2026-Q1,91,Nokia,North,Vodafone,Madrid\n"
        b"ES,2026-Q1,87,Huawei,South,Vodafone,Barcelona\n"
    )
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&load=1&cdf_grouping=vendor")
    assert response.status_code == 200
    assert "Global CDF Comparison" in response.text
    assert 'data-global-cdf-grouping-select' in response.text
    assert 'data-chart-cdf-grouping-select' in response.text
    assert 'data-cdf-range-control' in response.text
    assert 'Compare CDF by' in response.text
    assert 'input type="hidden" name="cdf_grouping" value="vendor"' in response.text


def test_dashboard_powerpoint_export_includes_visual_analytics_payload(client) -> None:
    login(client)
    csv_content = (
        b"market,period,score,gap,vendor,operator,region,city,Call Start Time\n"
        b"ES,2026-Q1,91,2.1,Nokia,Vodafone,North,Madrid,2026-07-10 10:00:00\n"
        b"ES,2026-Q1,87,3.3,Huawei,Orange,South,Barcelona,2026-07-11 11:00:00\n"
    )
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.post(
        "/datasets-analysis/export/powerpoint",
        data={
            "dataset_id": "1",
            "metric": ["score", "gap"],
            "market": ["ES"],
            "aggregation": "operator",
            "cdf_grouping": "vendor",
            "date_from": "2026-07-10",
            "date_to": "2026-07-11",
            "extra_filters": "vendor=Nokia,Huawei; region=North,South",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    from pptx import Presentation

    presentation = Presentation(BytesIO(response.content))
    assert len(presentation.slides) >= 4
    slide_text = "\n".join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if hasattr(shape, "text")
    )
    assert "sample.csv" in slide_text
    assert "Visual Analytics · score" in slide_text
    assert "Visual Analytics · gap" in slide_text
    assert "Date From: 2026-07-10" in slide_text
    assert "Mean" in slide_text
    assert "Avg" in slide_text
    assert "P10" in slide_text
    assert "P90" in slide_text
    assert "Min" in slide_text
    assert "Max" in slide_text


def test_workspace_logs_capture_analysis_warnings(client, monkeypatch) -> None:
    login(client)
    csv_content = b"market,period,score,gap\nES,2026-Q1,91,2.1\nES,2026-Q1,87,3.3\n"
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )

    import src.DashboardAnalytic as app_module

    original_build_analysis = app_module.build_analysis

    def warned_build_analysis(*args, **kwargs):
        warnings.warn("Synthetic analysis warning for workspace logs", UserWarning)
        return original_build_analysis(*args, **kwargs)

    monkeypatch.setattr(app_module, "build_analysis", warned_build_analysis)

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200

    logs = app_module.repository.list_workspace_logs(1)
    warning_logs = [log for log in logs if log["action"] == "analyze_dataset_warning"]
    assert warning_logs
    assert "Synthetic analysis warning for workspace logs" in warning_logs[0]["details_text"]


def test_dashboard_handles_empty_table_rows_without_template_failure(client) -> None:
    login(client)
    csv_content = b"market,period,operator,score\nES,2026-Q1,VDF,91\nES,2026-Q1,VDF,87\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=operator&market=DE&load=1")
    assert response.status_code == 200
    assert "No rows match the selected filters" in response.text or "No tabular rows match the selected filters" in response.text


def test_dashboard_materializes_legacy_ready_dataset_on_first_analysis(client) -> None:
    login(client)
    csv_content = b"market,period,operator,score\nES,2026-Q1,VDF,91\nES,2026-Q1,VDF,87\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    app_module.repository.drop_dataset_rows(1)
    assert not app_module.repository.dataset_rows_table_exists(1)

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=operator&load=1")
    assert response.status_code == 200
    assert "Charts and Scorecards" in response.text
    assert app_module.repository.dataset_rows_table_exists(1)


def test_dashboard_reuses_materialized_table_when_legacy_columns_only_differ_by_case(client, monkeypatch) -> None:
    login(client)
    csv_content = b"market,period,operator,score\nES,2026-Q1,VDF,91\nES,2026-Q1,ORG,87\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    legacy_frame = pd.DataFrame({
        "Market": ["ES", "ES"],
        "Period": ["2026-Q1", "2026-Q1"],
        "Operator": ["VDF", "ORG"],
        "score": [91, 87],
        "dataset_kind": ["generic", "generic"],
        "source_file": ["sample.csv", "sample.csv"],
    })
    app_module.repository.replace_dataset_rows(1, legacy_frame)
    app_module.DATAFRAME_CACHE.clear()
    app_module.ANALYSIS_CACHE.clear()

    calls = {"count": 0}
    original_load_dataset = app_module.load_dataset

    def counting_load_dataset(path):
        calls["count"] += 1
        return original_load_dataset(path)

    monkeypatch.setattr(app_module, "load_dataset", counting_load_dataset)

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=operator&load=1")
    assert response.status_code == 200
    assert "Charts and Scorecards" in response.text
    assert calls["count"] == 0


def test_dashboard_refreshes_stale_dataset_normalization_before_render(client) -> None:
    login(client)
    csv_content = b"market,period,score,RAT,PCell_RAT_Timeline\nES,2026-Q1,91,5G NSA,NR->LTE\nES,2026-Q1,87,LTE,LTE->NR\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        table_name = app_module.repository.dataset_rows_table_name(1)
        conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN campaign__2 TEXT')
        conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN operator__2 TEXT')
        conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN report_vendor TEXT')
        conn.execute(f'UPDATE "{table_name}" SET campaign__2 = Campaign, operator__2 = Operator')
        conn.execute(f'UPDATE "{table_name}" SET report_vendor = ?', ('O2',))
        conn.execute(
            """
            UPDATE dataset_profiles
            SET normalization_version = 1,
                filter_options_json = ?,
                available_aggregations_json = ?
            WHERE dataset_id = 1
            """,
            (
                json.dumps({"technology_primary": ["NR->LTE", "LTE->NR"]}),
                json.dumps(["technology_primary"]),
            ),
        )

    response = client.get("/datasets-analysis?dataset_id=1&metric=score&aggregation=all&load=1")
    assert response.status_code == 200
    assert ">5G NSA<" in response.text
    assert ">LTE<" in response.text
    assert "NR-&gt;LTE" not in response.text

    refreshed = app_module.repository.get_dataset(1)
    assert refreshed is not None
    assert int(refreshed["normalization_version"]) == app_module.DATASET_NORMALIZATION_VERSION
    refreshed_columns = app_module.repository.list_dataset_row_columns(1)
    assert not any(column.endswith('__2') for column in refreshed_columns)
    assert not any(app_module.column_identity(column) == 'reportvendor' for column in refreshed_columns)
    migrated = app_module.repository.load_dataset_rows(1, ['Vendor'], {})
    assert migrated['Vendor'].tolist() == ['O2', 'O2']
    assert not any(
        column.endswith('__2') for column in app_module.repository.list_reporting_row_columns('data')
    )


def test_dataset_status_endpoint_returns_queue_payload(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/api/datasets/status")
    assert response.status_code == 200
    payload = response.json()
    assert "datasets" in payload
    assert payload["datasets"][0]["file_name"] == "sample.csv"
    assert payload["datasets"][0]["size_mb_label"].endswith("MB")


def test_dataset_status_persists_completed_processing_duration(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("timed.csv", BytesIO(b"market,score\nES,91\n"), "text/csv")},
        follow_redirects=False,
    )
    import src.DashboardAnalytic as app_module

    app_module.repository.update_dataset_profile(
        1,
        status="processing",
        progress=45,
        processing_started_at=app_module.now_iso(),
        processed_at=None,
    )
    processing_dataset = client.get("/api/datasets/status").json()["datasets"][0]
    assert processing_dataset["elapsed_seconds"] is not None
    assert processing_dataset["elapsed_label"]
    processing_html = client.get("/workspace").text
    assert "45%" in processing_html
    assert processing_dataset["elapsed_label"] in processing_html
    assert 'data-queue-poll-ms="3000"' in processing_html

    app_module.repository.update_dataset_profile(
        1,
        status="ready",
        progress=100,
        processing_started_at="2026-09-16T10:00:00+02:00",
        processed_at="2026-09-16T10:01:05+02:00",
    )

    dataset = client.get("/api/datasets/status").json()["datasets"][0]
    assert dataset["elapsed_seconds"] == 65
    assert dataset["elapsed_label"] == "1m 05s"
    workspace_html = client.get("/workspace").text
    assert "100%" in workspace_html
    assert "1m 05s" in workspace_html
    assert 'data-queue-progress-separator' in workspace_html
    assert 'title="Total processing time"' in workspace_html


def test_dashboard_handles_missing_source_file_without_500(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        conn.execute(
            "INSERT INTO datasets (id, file_name, stored_path, uploaded_by) VALUES (?, ?, ?, ?)",
            (99, "missing.xlsx", "/tmp/does-not-exist.xlsx", "admin"),
        )
        conn.execute(
            """
            INSERT INTO dataset_profiles (
                dataset_id, status, progress, dataset_kind, default_metric, default_aggregation,
                available_metrics_json, available_aggregations_json, filter_options_json, summary_json, kpis_json
            ) VALUES (?, 'ready', 100, 'data', 'throughput_mbps', 'operator', '["throughput_mbps"]', '["operator"]', '{}', '{}', '{}')
            """,
            (99,),
        )

    response = client.get("/datasets-analysis?dataset_id=99&metric=throughput_mbps&aggregation=operator&load=1")
    assert response.status_code == 200
    assert "source file is missing" in response.text


def test_materialized_dataset_handles_case_insensitive_duplicate_columns(client) -> None:
    login(client)
    csv_content = b"Campaign,campaign,score\nES_Q1_2026,manual-campaign,91\n"
    upload_response = client.post(
        "/datasets-analysis/upload",
        files={"dataset_files": ("duplicate-columns.csv", BytesIO(csv_content), "text/csv")},
        follow_redirects=False,
    )
    assert upload_response.status_code == 303

    import src.DashboardAnalytic as app_module

    dataset = app_module.repository.get_dataset(1)
    assert dataset is not None
    assert dataset["status"] == "ready"
    assert dataset["last_error"] in (None, "")


def test_failed_dataset_shows_last_error_in_queue(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    with app_module.repository.connection() as conn:
        conn.execute(
            "INSERT INTO datasets (id, file_name, stored_path, uploaded_by) VALUES (?, ?, ?, ?)",
            (50, "broken.csv", "/tmp/broken.csv", "admin"),
        )
        conn.execute(
            """
            INSERT INTO dataset_profiles (
                dataset_id, status, progress, dataset_kind, last_error, available_metrics_json,
                available_aggregations_json, filter_options_json, summary_json, kpis_json
            ) VALUES (?, 'failed', 100, 'generic', 'duplicate column name: campaign', '[]', '[]', '{}', '{}', '{}')
            """,
            (50,),
        )

    response = client.get("/workspace")
    assert response.status_code == 200
    assert "duplicate column name: campaign" in response.text


def test_workspace_queue_shows_dataset_size_column(client) -> None:
    login(client)
    client.post(
        "/datasets-analysis/upload",
        data={"dataset_kinds": "data"},
        files={"dataset_files": ("sample.csv", BytesIO(b"market,period,score\nES,2026-Q1,91\n"), "text/csv")},
        follow_redirects=False,
    )

    response = client.get("/workspace")
    assert response.status_code == 200
    assert "<th>Size</th>" in response.text
    assert "MB" in response.text


def test_workspace_dataset_table_defaults_to_descending_ids_and_has_sortable_columns(client) -> None:
    login(client)
    for name in ('first.csv', 'second.csv'):
        response = client.post(
            '/datasets-analysis/upload',
            data={'dataset_kinds': 'data'},
            files={'dataset_files': (name, BytesIO(b'market,period,score\nES,2026-Q1,91\n'), 'text/csv')},
            follow_redirects=False,
        )
        assert response.status_code == 303

    page = client.get('/workspace')
    table = page.text.split('<table class="queue-table" data-queue-sortable-table>', 1)[1].split('</table>', 1)[0]

    assert table.index('data-dataset-id="2"') < table.index('data-dataset-id="1"')
    assert '<th aria-sort="descending"><button type="button" class="queue-sort-button" data-queue-sort-key="id" data-queue-sort-type="number">' in table
    for key in ('dataset', 'kind', 'rows', 'columns', 'size', 'status', 'progress', 'uploaded', 'updated'):
        assert f'data-queue-sort-key="{key}"' in table
    script = client.get('/static/js/app.js').text
    assert "const queueSortState = {key: 'id', direction: 'desc'};" in script
    assert 'combinedBoundary' in script


def test_app_logs_combines_operational_and_audit_activity(client) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    app_module.repository.add_log(
        "admin",
        "process_dataset_failed",
        '{"dataset_id": 1, "file": "sample.csv", "error": "Synthetic processing failure"}',
    )
    app_module.repository.add_log("admin", "change_password", "Password changed from the account badge.")

    response = client.get("/app-logs")
    assert response.status_code == 200
    assert "App Logs" in response.text
    assert "App Events" in response.text
    assert response.text.index('data-app-log-date-filter') < response.text.index('data-app-log-user-filter')
    assert response.text.index('data-app-log-user-filter') < response.text.index('data-app-log-executor-filter')
    assert "All events" in response.text
    assert "Info only" in response.text
    assert "Error only" in response.text
    assert "All users" in response.text
    assert "All executors" in response.text
    assert "All actions" in response.text
    assert 'data-app-log-refresh' in response.text
    assert 'data-app-log-count' in response.text
    assert 'data-execution-log-output' in response.text
    assert 'Execution Log' in response.text
    assert "Type" in response.text
    assert "Error" in response.text
    assert "Synthetic processing failure" in response.text
    assert "change_password" in response.text

    payload = client.get('/api/app-logs').json()
    assert any(log['action'] == 'process_dataset_failed' for log in payload['logs'])
    assert 'execution_logs' in payload


def test_server_log_formatter_uses_the_configured_timezone_and_timestamp_prefix(monkeypatch) -> None:
    import logging

    from src.main import ConfiguredTimezoneDefaultFormatter

    monkeypatch.setenv('TZ', 'Europe/Madrid')
    record = logging.LogRecord('uvicorn.error', logging.INFO, __file__, 1, 'Server ready', (), None)
    record.created = datetime(2026, 9, 18, 20, 30, tzinfo=timezone.utc).timestamp()
    formatter = ConfiguredTimezoneDefaultFormatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    assert formatter.format(record) == '[2026-09-18 22:30:00] Server ready'


def test_docker_uses_the_timestamped_server_launcher() -> None:
    root = Path(__file__).parents[1]
    dockerfile = (root / 'docker/dockerfile').read_text(encoding='utf-8')
    production_compose = (root / 'docker/docker-compose.yml').read_text(encoding='utf-8')
    development_compose = (root / 'docker/docker-compose-dev.yml').read_text(encoding='utf-8')
    launcher = (root / 'src/main.py').read_text(encoding='utf-8')

    assert 'CMD ["python", "-m", "src.main"]' in dockerfile
    assert 'DASHBOARD_ANALYTIC_BIND_PORT: "7278"' in production_compose
    assert 'DASHBOARD_ANALYTIC_RELOAD: "true"' in development_compose
    assert 'command: python -m src.main' in development_compose
    assert "'fmt': '[%(asctime)s] %(levelprefix)s %(message)s'" in launcher
    assert "'src.DashboardAnalytic:app' if reload_enabled else app" in launcher


def test_app_logs_use_the_configured_timezone_for_display_and_date_filter(client, monkeypatch) -> None:
    login(client)

    import src.DashboardAnalytic as app_module

    monkeypatch.setenv('TZ', 'Europe/Madrid')
    app_module.repository.add_log('admin', 'timezone_display_test', '{}')
    with app_module.repository.connection() as connection:
        connection.execute(
            "UPDATE audit_logs SET created_at = ? WHERE action = ?",
            ('2026-09-18T22:30:00+00:00', 'timezone_display_test'),
        )

    log = next(
        item for item in client.get('/api/app-logs').json()['logs']
        if item['action'] == 'timezone_display_test'
    )

    assert log['created_at'] == '2026-09-19 00:30:00'
    assert log['date'] == '2026-09-19'
    assert log['summary'].startswith('[2026-09-19 00:30:00] ')


def test_app_logs_normalises_user_case_and_records_login_outcomes(client) -> None:
    import src.DashboardAnalytic as app_module

    failed = client.post('/login', data={
        'username': 'ADMIN', 'password': 'wrong-password', 'workspace_id': 'default',
    })
    assert failed.status_code == 401
    successful = client.post('/login', data={
        'username': 'AdMiN', 'password': 'admin123', 'workspace_id': 'default',
    }, follow_redirects=False)
    assert successful.status_code == 303
    app_module.repository.add_log('ADMIN', 'mixed_case_test', '{}')
    app_module.repository.add_log('ADMIN', 'system_test', '{"executed_by": "SYSTEM"}')

    response = client.get('/app-logs')

    assert response.text.count('<option value="admin">admin</option>') == 1
    assert 'data-app-log-user="admin"' in response.text
    assert '<option value="system">system</option>' in response.text
    assert 'data-app-log-executor="system"' in response.text
    login_details = [json.loads(row['details']) for row in app_module.repository.list_logs() if row['action'] == 'login']
    assert any(details['success'] is False and details['reason'] == 'invalid_credentials' for details in login_details)
    assert any(details['success'] is True and details['result'] == 'successful' for details in login_details)


def test_generic_button_click_audit_endpoint_is_not_exposed(client) -> None:
    login(client)

    response = client.post('/api/app-logs/button-click', json={
        'page': '/reporting', 'label': 'Select All / None', 'control': 'multiselect-action',
    })

    assert response.status_code == 404
