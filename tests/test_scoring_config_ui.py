from pathlib import Path
import json
import re
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PANEL_TEMPLATE = PROJECT_ROOT / 'src/web_interface/templates/scoring_config_panels.html'
PANEL_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring_config.js'


def test_scoring_configuration_panel_exposes_methodology_and_weight_controls():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'data-scoring-profile-select' in template
    assert 'data-scoring-profile-action="create"' in template
    assert 'data-scoring-profile-action="copy"' in template
    assert 'data-scoring-profile-action="rename"' in template
    assert 'data-scoring-profile-action="delete"' in template
    assert 'data-scoring-weight-mode' in template
    assert '<option value="points">Points</option>' in template
    assert '<option value="weight">Weight (%)</option>' in template
    assert 'KPI Weight in Environment (%) totals 100%' in template
    assert 'Global weight (%) shows the KPI’s share of all environments' in template
    assert 'data-environment-total-points' in template
    assert 'data-environment-total-weight' in template
    assert '<label>Scoring Methodology' in template
    for label in ['Create Methodology', 'Duplicate Methodology', 'Rename Methodology', 'Delete Methodology',
                  'Save Methodology', 'Import Methodology (JSON)', 'Export Methodology (JSON)']:
        assert label in template
    assert "const profilesEndpoint = '/api/workspace-config/scoring-profiles';" in script
    assert 'latest.active_profile_id = profileId' in script


def test_scoring_kpi_table_exposes_editable_category_formula_and_filter_controls():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert '[data-category-add-below]' in template
    assert 'data-scoring-add-kpi' not in template
    assert 'data-scoring-kpi-rows' in template
    assert 'KPI Definition</th>' in template
    assert '<th scope="col">Category</th>' in template
    assert "name.className = 'scoring-config-category-name';" in script
    assert 'data-kpi-category' in script
    assert 'data-kpi-code-input' in script
    assert 'data-kpi-source-kind' in script
    assert 'data-kpi-direction' in script
    assert 'data-kpi-formula' in script
    assert 'data-kpi-filters' in script
    assert 'JSON.parse(input.value)' in script
    assert 'data-kpi-delete' in script
    assert 'data-category-points' in script
    assert 'data-category-weight' in script
    assert 'data-weight-environment-input' in script
    assert 'data-weight-global-percent' in script


def test_scoring_kpi_mapping_methods_are_explicit_and_persisted():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    direction_index = script.index("const directionCell = appendCell(row, '', 'Direction');")
    mapping_index = script.index("const mappingMethodCell = appendCell(row, '', 'Mapping method');")
    points_index = script.index("const pointsCell = appendCell(row, '', 'Max Points');")
    assert direction_index < mapping_index < points_index
    assert "['piecewise_linear', 'Linear']" in script
    assert "['piecewise_quadratic', 'Quadratic']" in script
    assert "['piecewise_smoothstep', 'Smooth curve']" in script
    assert '`Mapping method for ${metric.kpi || metric.code}`' in script
    assert "'data-kpi-mapping-method': ''" in script
    assert 'mappingMethodSelect.title = mappingMethodDescription;' in script
    assert 'between configured score anchors' in script
    assert 'lower intermediate scores (t²)' in script
    assert '3t²−2t³' in script
    assert 'Direction defines which values are better.' in script
    assert 'option.title = mappingMethodDescriptions[option.value] || option.textContent;' in script
    assert 'if (!supportedMappingMethods.has(mappingMethod))' in script
    assert 'metric.mapping_method = mappingMethod;' in script
    assert "? template.mapping_method" in script
    assert ": 'piecewise_linear';" in script
    assert 'cell.colSpan = 20;' in script


def test_kpi_categories_are_selectable_saved_and_created_with_a_first_kpi():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert "appendSelect(categoryCell, selectedCategory" in script
    assert "'data-kpi-category': ''" in script
    assert 'refreshKpiCategoryOptions();' in script
    assert 'select.value = selectedCategory;' in script
    assert "description: 'Create a category with its first KPI. Configure the KPI before saving.'" in script
    assert 'categoryCreate: true' in script
    assert 'categoryNameIsAvailable(name)' in script
    assert 'addKpi(peers.at(-1) || null, category, {categoryCreated: true});' in script
    assert 'metric.category = category;' in script
    assert 'latestConfiguration.metrics = submittedMetrics;' in script
    assert "appendCell(row).textContent = priorityMetric(code)?.category || 'Other';" in script


def test_long_kpi_labels_resize_after_render_and_container_changes():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert "'data-kpi-label': '', class: 'scoring-config-identity-input', maxlength: '160', required: '', rows: '1'" in script
    assert 'if (!textarea?.isConnected || textarea.offsetParent === null) return;' in script
    assert "textarea.style.height = 'auto';" in script
    assert 'textarea.scrollHeight + borderHeight' in script
    assert 'kpiLabelResizeObserver.observe(kpiTableContainer);' in script
    assert "window.addEventListener('resize', refreshKpiLabelHeights);" in script


def test_scoring_environments_are_dynamic_and_zero_point_weights_remain_editable():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'Loading environments…' in template
    assert 'const environmentKeys = () => environmentEntries().map(([key]) => key);' in script
    assert 'weight_share' in script
    assert 'const applyEnvironmentPointsEdit' in script
    assert 'const applyEnvironmentWeightEdit' in script
    assert 'relativeShares[index]' in script
    assert 'globalPercent' in script
    assert 'totals.share * 100' in script
    assert 'data-environment-total-points' in script
    assert 'data-environment-total-weight' in script


def test_scoring_config_panels_have_stable_ordered_deep_link_targets():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    panel_ids = [
        'scoring-methodology-environments',
        'scoring-aggregation-hierarchy',
        'scoring-gap-priority',
    ]
    panel_positions = [template.index(f'id="{panel_id}"') for panel_id in panel_ids]
    assert panel_positions == sorted(panel_positions)
    assert 'window.addEventListener(\'hashchange\', openScoringConfigHashTarget)' in script
    assert 'target.open = true' in script
    assert 'target.scrollIntoView' in script
    from lxml import html
    tree = html.fromstring(template)
    assert tree.xpath('//details[@id="scoring-methodology-environments"]')
    assert "ancestor.tagName?.toLowerCase() === 'details'" in script


def test_gap_priority_table_displays_kpi_category():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert '<th scope="col">Category</th><th scope="col">Order</th>' in template
    assert "appendCell(row).textContent = priorityMetric(code)?.category || 'Other';" in script


def test_scoring_environment_crud_and_context_drafts_are_available():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'data-scoring-environment-create' in template
    assert 'data-scoring-environment-rename' in template
    assert 'data-scoring-environment-delete' in template
    assert 'data-environment-g1' in template
    assert 'data-environment-g2' in template
    assert 'data-profile-dialog-environment-fields' in template
    assert 'const createEnvironment = async () =>' in script
    assert 'const renameEnvironment = async () =>' in script
    assert 'const deleteEnvironment = async () =>' in script
    assert 'display_name: requestedName' in script
    assert 'metric.contexts = Object.fromEntries' in script
    assert 'environmentRename: true' in script
    assert 'applyEnvironmentMapping(latestConfiguration.scope)' in script
    assert 'environment.source_filters = {G_Level_1: g1, ...(g2 ? {G_Level_2: g2} : {})};' in script
    assert 'captureSelectedContext(row, lastEnvironment)' in script
    assert 'hydrateSelectedContext(row, lastEnvironment)' in script
    assert "description: `Delete “${environmentLabel(environment)}” and its KPI points, thresholds, and mappings from this methodology?`" in script


def test_code_column_is_the_single_editable_code_input_and_updates_gap_priority():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert '<th scope="col" rowspan="2">Code</th><th scope="col" rowspan="2">KPI</th>' in template
    assert script.count("'data-kpi-code-input': ''") == 1
    assert "const calculationDialog = document.createElement('dialog');" in script
    assert "editFormulaButton.setAttribute('aria-label', `Edit formula and filters for ${metric.kpi || metric.code}`);" in script
    assert "editFormulaButton.title = `Edit formula and filters for ${metric.kpi || metric.code}`;" in script
    assert 'codeMap.get(code)' in script
    assert "title: 'Changing this code also updates its saved GAP priority entry.'" in script
    priority_handler_index = script.index("priorityForm.addEventListener('click', (event) => {")
    assert 'window.prompt' not in script[:priority_handler_index]
    assert 'window.confirm' not in script
    assert 'const orderedCategories = Array.from(grouped.keys());' in script
    assert 'calculationDialog.showModal()' in script
    assert "denominatorLabel.textContent = 'Calculation basis (derived from formula)'" in script
    assert 'const calculation = {formula, filters};' in script
    assert 'calculation.totalpacketlost = totalPacketLossExpression;' in script
    assert "[data-scoring-config] [hidden] { display: none !important; }" in template


def test_reference_distribution_allocates_100_points_in_reference_proportions():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is unavailable for the scoring UI arithmetic check.')
    module_path = json.dumps(str(PANEL_SCRIPT))
    program = (
        f"const math = require({module_path});"
        "const shares = math.normalizeShares([500, 150]);"
        "const points = math.allocatePoints(100, shares);"
        "const display = math.formatPointDisplay(8.645);"
        "const unchanged = math.readPointValue(display, 8.645, display);"
        "const editedAtDisplay = math.readPointValue(display, 8.645, display, true);"
        "const editedPrecise = math.readPointValue('8.6457', 8.645, display, true);"
        "console.log(JSON.stringify({shares, points, total: points.reduce((a, b) => a + b, 0), display, unchanged, editedAtDisplay, editedPrecise}));"
    )
    completed = subprocess.run([node, '-e', program], check=True, capture_output=True, text=True)
    allocation = json.loads(completed.stdout)

    assert allocation['shares'] == pytest.approx([500 / 650, 150 / 650])
    assert allocation['points'] == pytest.approx([100 * 500 / 650, 100 * 150 / 650])
    assert allocation['total'] == pytest.approx(100)
    assert allocation['display'] == '8.65'
    assert allocation['unchanged'] == pytest.approx(8.645)
    assert allocation['editedAtDisplay'] == pytest.approx(8.65)
    assert allocation['editedPrecise'] == pytest.approx(8.6457)


def test_gap_priority_controls_support_inline_position_editor():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is unavailable for the GAP priority behavior check.')
    script_source = json.dumps(str(PANEL_SCRIPT))
    program = r"""
const fs = require('fs');
const source = fs.readFileSync(SCRIPT_PATH, 'utf8');
const setupStart = source.indexOf('  const movePriorityRow =');
const setupEnd = source.indexOf("  hierarchyForm?.addEventListener('click'", setupStart);
if (setupStart < 0 || setupEnd < 0) throw new Error('Priority handler block not found');
const setup = source.slice(setupStart, setupEnd);
function create(names) {
  const rows = names.map((name) => ({name, dataset: {kpiCode: name}, editor: null}));
  const moveButtons = new Map();
  for (const row of rows) {
    for (const direction of ['first', 'up', 'down', 'last', 'position']) {
      const button = {dataset: {priorityMove: direction}, focused: false, focus() { this.focused = true; }, closest: () => row};
      if (direction === 'position') button.after = (editor) => { row.editor = editor; editor.row = row; editor.closest = () => row; };
      moveButtons.set(`${row.name}:${direction}`, button);
      if (direction === 'position') row.querySelector = (selector) => selector === '[data-priority-move="position"]' ? button : null;
    }
    row.after = (editor) => { row.editor = editor; editor.row = row; };
  }
  const priorityRows = {
    children: rows,
    querySelectorAll: () => rows,
    querySelector: () => rows.find((row) => row.editor)?.editor || null,
    contains: () => true,
    insertBefore(item, reference) {
      const oldIndex = rows.indexOf(item);
      rows.splice(oldIndex, 1);
      const newIndex = reference ? rows.indexOf(reference) : rows.length;
      rows.splice(newIndex, 0, item);
    }
  };
  const state = {statuses: [], refreshed: 0, prevented: false, handlers: {}};
  const document = {createElement(tag) {
    if (tag === 'input') return {value: '', dataset: {}, attributes: {}, focused: false, selected: false,
      setAttribute(key, value) { this.attributes[key] = value; }, focus() { this.focused = true; }, select() { this.selected = true; }};
    if (tag === 'button') return {dataset: {}, attributes: {}, textContent: '', focused: false,
      setAttribute(key, value) { this.attributes[key] = value; }, focus() { this.focused = true; }, closest: (selector) => selector === '[data-priority-position-editor]' ? activeEditor : selector === 'tr[data-kpi-code]' ? activeEditor?.row : null};
    if (tag === 'span') return {dataset: {}, setAttribute() {}, children: [], error: null, input: null, apply: null, cancel: null, row: null,
      append(input, apply, cancel, error) { this.input = input; this.apply = apply; this.cancel = cancel; this.error = error; },
      querySelector(selector) { return selector === '[data-priority-position-input]' ? this.input : this.error; },
      closest: () => this.row,
      remove() { if (this.row) this.row.editor = null; }};
    throw new Error(`Unexpected element: ${tag}`);
  }};
  let activeEditor = null;
  // Bind the editor reference through the button's closest method once each editor is created.
  const originalCreate = document.createElement;
  document.createElement = (tag) => {
    const element = originalCreate(tag);
    if (tag === 'button') element.closest = (selector) => selector === '[data-priority-position-editor]' ? activeEditor : selector === 'tr[data-kpi-code]' ? activeEditor?.row : null;
    if (tag === 'span') {
      const append = element.append;
      element.append = (input, apply, cancel, error) => { append.call(element, input, apply, cancel, error); activeEditor = element; };
    }
    return element;
  };
  const context = {window: {}, document, priorityRows, priorityStatus: {}, priorityLabel: (code) => code,
    priorityForm: {addEventListener(name, handler) { state.handlers[name] = handler; }},
    setStatus: (...args) => state.statuses.push(args),
    refreshPriorityButtons: () => state.refreshed++};
  const vm = require('vm');
  vm.runInNewContext(setup, context);
  state.context = context;
  const clickHandler = state.handlers.click;
  const keydownHandler = state.handlers.keydown;
  function clickMove(rowName, direction = 'position') {
    const button = moveButtons.get(`${rowName}:${direction}`);
    clickHandler({target: {closest: (selector) => selector === '[data-priority-move]' ? button : null}});
    return button;
  }
  function clickApply(editor) {
    const button = editor.apply;
    clickHandler({target: {closest: (selector) => selector === '[data-priority-position-apply]' ? button : null}});
  }
  function clickCancel(editor) {
    const button = editor.cancel;
    clickHandler({target: {closest: (selector) => selector === '[data-priority-position-cancel]' ? button : null}});
  }
  function key(editor, key) {
    state.prevented = false;
    keydownHandler({key, target: {closest: (selector) => selector === '[data-priority-position-editor]' ? editor : null, matches: (selector) => key === 'Enter' && selector === '[data-priority-position-input]'},
      preventDefault() { state.prevented = true; }});
  }
  return {rows, state, clickMove, clickApply, clickCancel, key, get editor() { return rows.find((row) => row.editor)?.editor || null; }, moveButtons};
}
function summary(harness) {
  return {order: harness.rows.map((row) => row.name), editorOpen: Boolean(harness.editor), dirty: harness.state.context.priorityDirty === true,
    statuses: harness.state.statuses, refreshed: harness.state.refreshed, prevented: harness.state.prevented};
}
const opening = create(['a', 'b', 'c', 'd']);
opening.clickMove('c');
const openInput = opening.editor.input;
const opened = {...summary(opening), inputFocused: openInput.focused, inputSelected: openInput.selected, initialValue: openInput.value};
openInput.value = '2';
opening.clickApply(opening.editor);
const applied = {...summary(opening), returnedFocus: opening.moveButtons.get('c:position').focused};
const invalid = create(['a', 'b', 'c', 'd']);
invalid.clickMove('c');
const invalidEditor = invalid.editor;
invalidEditor.input.value = '0';
invalid.clickApply(invalidEditor);
const rejected = {...summary(invalid), invalidValue: invalidEditor.input.attributes['aria-invalid'], error: invalidEditor.error.textContent, inputRefocused: invalidEditor.input.focused};
const invalidLarge = create(['a', 'b', 'c', 'd']);
invalidLarge.clickMove('c');
invalidLarge.editor.input.value = '5';
invalidLarge.clickApply(invalidLarge.editor);
const rejectedLarge = {...summary(invalidLarge), error: invalidLarge.editor.error.textContent};
const invalidDecimal = create(['a', 'b', 'c', 'd']);
invalidDecimal.clickMove('c');
invalidDecimal.editor.input.value = '1.5';
invalidDecimal.clickApply(invalidDecimal.editor);
const rejectedDecimal = {...summary(invalidDecimal), error: invalidDecimal.editor.error.textContent};
const exclusive = create(['a', 'b', 'c', 'd']);
exclusive.clickMove('c');
exclusive.clickMove('b');
const exclusiveEditor = {...summary(exclusive), editorRow: exclusive.editor.row.dataset.kpiCode};
const toggled = create(['a', 'b', 'c', 'd']);
toggled.clickMove('c');
toggled.clickMove('c');
const toggleCanceled = summary(toggled);
const clickedCancel = create(['a', 'b', 'c', 'd']);
clickedCancel.clickMove('b');
const cancelEditor = clickedCancel.editor;
clickedCancel.clickCancel(cancelEditor);
const buttonCanceled = {...summary(clickedCancel), returnedFocus: clickedCancel.moveButtons.get('b:position').focused};
const escaped = create(['a', 'b', 'c', 'd']);
escaped.clickMove('c');
escaped.key(escaped.editor, 'Escape');
const escapeCanceled = {...summary(escaped), returnedFocus: escaped.moveButtons.get('c:position').focused};
const entered = create(['a', 'b', 'c', 'd']);
entered.clickMove('a');
entered.editor.input.value = '3';
entered.key(entered.editor, 'Enter');
const enterApplied = {...summary(entered), returnedFocus: entered.moveButtons.get('a:position').focused};
const ends = create(['a', 'b', 'c', 'd']);
ends.clickMove('c', 'first');
const movedFirst = summary(ends);
const movedLastHarness = create(['a', 'b', 'c', 'd']);
movedLastHarness.clickMove('b', 'last');
const movedLast = summary(movedLastHarness);
const movedUpHarness = create(['a', 'b', 'c', 'd']);
movedUpHarness.clickMove('c', 'up');
const movedUp = summary(movedUpHarness);
const movedDownHarness = create(['a', 'b', 'c', 'd']);
movedDownHarness.clickMove('b', 'down');
const movedDown = summary(movedDownHarness);
console.log(JSON.stringify({opened, applied, rejected, rejectedLarge, rejectedDecimal, exclusiveEditor, toggleCanceled, buttonCanceled, escapeCanceled, enterApplied, movedFirst, movedLast, movedUp, movedDown}));
""".replace('SCRIPT_PATH', script_source)
    completed = subprocess.run([node, '-e', program], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result['opened']['order'] == ['a', 'b', 'c', 'd']
    assert result['opened']['editorOpen'] is True
    assert result['opened']['dirty'] is False
    assert result['opened']['inputFocused'] and result['opened']['inputSelected']
    assert result['opened']['initialValue'] == '3'
    assert result['applied']['order'] == ['a', 'c', 'b', 'd']
    assert result['applied']['editorOpen'] is False
    assert result['applied']['dirty'] is True
    assert result['applied']['returnedFocus'] is True
    assert result['rejected']['order'] == ['a', 'b', 'c', 'd']
    assert result['rejected']['editorOpen'] is True
    assert result['rejected']['dirty'] is False
    assert result['rejected']['invalidValue'] == 'true'
    assert result['rejected']['error']
    assert result['rejected']['inputRefocused'] is True
    for key in ['rejectedLarge', 'rejectedDecimal']:
        assert result[key]['editorOpen'] is True
        assert result[key]['dirty'] is False
        assert result[key]['error']
    assert result['exclusiveEditor']['editorOpen'] is True
    assert result['exclusiveEditor']['editorRow'] == 'b'
    assert result['toggleCanceled']['editorOpen'] is False
    assert result['toggleCanceled']['order'] == ['a', 'b', 'c', 'd']
    assert result['buttonCanceled']['editorOpen'] is False
    assert result['buttonCanceled']['order'] == ['a', 'b', 'c', 'd']
    assert result['buttonCanceled']['dirty'] is False
    assert result['buttonCanceled']['returnedFocus'] is True
    assert result['escapeCanceled']['editorOpen'] is False
    assert result['escapeCanceled']['order'] == ['a', 'b', 'c', 'd']
    assert result['escapeCanceled']['prevented'] is True
    assert result['escapeCanceled']['returnedFocus'] is True
    assert result['enterApplied']['order'] == ['b', 'c', 'a', 'd']
    assert result['enterApplied']['editorOpen'] is False
    assert result['enterApplied']['prevented'] is True
    assert result['enterApplied']['returnedFocus'] is True
    assert result['movedFirst']['order'] == ['c', 'a', 'b', 'd']
    assert result['movedLast']['order'] == ['a', 'c', 'd', 'b']
    assert result['movedUp']['order'] == ['a', 'c', 'b', 'd']
    assert result['movedDown']['order'] == ['a', 'c', 'b', 'd']


def test_category_group_moves_preserve_kpi_order_drafts_and_boundary_positions():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is unavailable for the category-order behavior check.')
    script_source = json.dumps(str(PANEL_SCRIPT))
    program = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(SCRIPT_PATH, 'utf8');
const start = source.indexOf('  const moveCategory = (heading, direction) => {');
const end = source.indexOf('  const applyWeightEdit =', start);
if (start < 0 || end < 0) throw new Error('Category movement helper not found');
const helper = source.slice(start, end);
function run(direction, selectedCategory) {
  const draft = {code: 'B2', formula: 'unsaved formula'};
  const rows = [['A1', 'A'], ['A2', 'A'], ['B1', 'B'], ['B2', 'B'], ['C1', 'C']].map(([code, category], index) => ({
    dataset: {kpiCode: code, orderIndex: String(index)}, category,
    ...(code === 'B2' ? {_newMetricTemplate: draft} : {}),
    querySelector: () => ({value: category})
  }));
  const headings = ['A', 'B', 'C'].map((category) => ({dataset: {kpiCategoryHeading: category}}));
  const kpiRows = {children: [], querySelectorAll: () => kpiRows.children.filter((node) => node.dataset?.kpiCategoryHeading),
    replaceChildren(...nodes) { this.children = nodes; }};
  const state = {renders: 0, statuses: []};
  const context = {kpiRows, kpiStatus: {}, kpiDirty: false,
    rowMetrics: () => kpiRows.children.filter((node) => node.dataset?.kpiCode),
    setStatus: (...args) => state.statuses.push(args),
    renderCategoryGroups() {
      state.renders++;
      const groups = new Map();
      context.rowMetrics().forEach((row) => { if (!groups.has(row.category)) groups.set(row.category, []); groups.get(row.category).push(row); });
      kpiRows.replaceChildren(...Array.from(groups, ([category, group]) => [headings.find((item) => item.dataset.kpiCategoryHeading === category),
        ...group.sort((left, right) => Number(left.dataset.orderIndex) - Number(right.dataset.orderIndex))]).flat());
    }};
  vm.createContext(context);
  kpiRows.replaceChildren(headings[0], ...rows.slice(0, 2), headings[1], ...rows.slice(2, 4), headings[2], rows[4]);
  const selected = headings.find((item) => item.dataset.kpiCategoryHeading === selectedCategory);
  vm.runInContext(`${helper}\nmoveCategory(heading, direction);`, Object.assign(context, {heading: selected, direction}));
  return {order: kpiRows.children.map((node) => node.dataset.kpiCategoryHeading || node.dataset.kpiCode),
    metricOrder: context.rowMetrics().map((row) => row.dataset.kpiCode), indexes: context.rowMetrics().map((row) => Number(row.dataset.orderIndex)),
    draftPreserved: rows[3]._newMetricTemplate === draft, dirty: context.kpiDirty, renders: state.renders, statuses: state.statuses.length};
}
console.log(JSON.stringify({up: run('up', 'B'), down: run('down', 'B'), firstBoundary: run('up', 'A'), lastBoundary: run('down', 'C')}));
""".replace('SCRIPT_PATH', script_source)
    completed = subprocess.run([node, '-e', program], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result['up']['order'] == ['B', 'B1', 'B2', 'A', 'A1', 'A2', 'C', 'C1']
    assert result['up']['metricOrder'] == ['B1', 'B2', 'A1', 'A2', 'C1']
    assert result['up']['indexes'] == [0, 1, 2, 3, 4]
    assert result['up']['draftPreserved'] is True
    assert result['up']['dirty'] is True
    assert result['up']['renders'] == 1
    assert result['down']['order'] == ['A', 'A1', 'A2', 'C', 'C1', 'B', 'B1', 'B2']
    assert result['down']['metricOrder'] == ['A1', 'A2', 'C1', 'B1', 'B2']
    assert result['down']['indexes'] == [0, 1, 2, 3, 4]
    assert result['down']['draftPreserved'] is True
    assert result['down']['dirty'] is True
    assert result['down']['renders'] == 1
    for boundary in ['firstBoundary', 'lastBoundary']:
        assert result[boundary]['order'] == ['A', 'A1', 'A2', 'B', 'B1', 'B2', 'C', 'C1']
        assert result[boundary]['dirty'] is False
        assert result[boundary]['renders'] == 0


def test_max_points_editor_keeps_exact_values_behind_two_decimal_display():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'input.value = scoringConfigMath.formatPointDisplay(exactPoints);' in script
    assert 'input.dataset.displayPoints = input.value;' in script
    assert "input?.dataset.pointEdited === 'true'" in script
    assert "target.dataset.pointEdited = 'true';" in script
    assert 'commitPointInput(target);' in script
    assert 'String(pointInputValue(pointsInput))' in script
    assert 'context.max_points = pointsForRow(row, environment);' in script
    assert 'setRowEnvironmentPoints(row, environment, targetPoints);' in script


def test_scoring_gap_setup_parent_keeps_child_anchor_ids_and_opens_ancestors():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'id="scoring-gap-analysis-setup"' in template
    for panel_id in ['scoring-kpi-configuration', 'scoring-methodology-environments',
                     'scoring-aggregation-hierarchy', 'scoring-gap-priority']:
        assert f'id="{panel_id}"' in template
    assert "ancestor.tagName?.toLowerCase() === 'details'" in script
    assert 'if (window.location.hash) openScoringConfigHashTarget();' in script


def test_switching_profiles_does_not_mark_the_kpi_form_dirty():
    import json
    import subprocess

    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    guards = []
    for event in ('input', 'change'):
        start = script.index(f"  kpiForm.addEventListener('{event}', (event) => {{")
        start = script.index('    const target = event.target;', start)
        end = script.index('    kpiDirty = true;', start) + len('    kpiDirty = true;')
        guards.append(script[start:end])
    program = 'let kpiDirty = false;\n' + '\n'.join(
        f"((event) => {{{guard}}})({{target: {{matches: selector => selector.includes('[data-scoring-profile-select]')}}}});"
        for guard in guards
    ) + '\nconsole.log(JSON.stringify({kpiDirty}));'
    result = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['kpiDirty'] is False


def test_environment_save_and_add_category_locations_and_source_dropdowns():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    assert '<h2 id="scoring-environment-controls-title">Methodology Environments</h2>' in template
    assert template.index('data-scoring-environment-source-fields') < template.rindex('data-scoring-kpi-save')
    assert template.rindex('data-scoring-kpi-save') > template.index('KPI Definitions, Scoring &amp; Thresholds')
    assert '<select data-environment-g1 required>' in template
    assert '<select data-environment-g2>' in template
    assert 'scoring-config-status.is-unsaved { color: #b42318; }' in template
    assert 'data-scoring-add-category' not in template
    assert '[data-category-add-below]' in template
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    assert "button.title = direction === 'add' ? 'Add category below'" in script
    assert 'addKpi(peers.at(-1) || null, category, {categoryCreated: true})' in script


def test_methodology_layout_uses_one_form_and_four_shared_save_buttons():
    from lxml import html

    tree = html.fromstring(PANEL_TEMPLATE.read_text(encoding='utf-8'))
    form = tree.xpath('//form[@data-scoring-kpi-form]')[0]
    environments = form.xpath('.//details[@aria-labelledby="scoring-environment-controls-title"]')[0]
    kpis = form.xpath('.//*[@data-scoring-kpi-panel]')[0]
    hierarchy = form.xpath('.//*[@id="scoring-aggregation-hierarchy"]')[0]
    priority = form.xpath('.//*[@id="scoring-gap-priority"]')[0]
    assert kpis.xpath('.//tbody[@data-scoring-kpi-rows]')
    assert kpis.get('open') is None
    title = kpis.xpath('./summary//h5[@data-scoring-kpi-title]')[0]
    summary_text = title.getparent()
    assert 'scoring-config-kpi-summary-text' in summary_text.get('class', '')
    hint = summary_text.xpath('./span[@class="scoring-config-kpi-expand-hint"]')[0]
    assert hint.text == 'Expand this panel to edit KPI specifications, thresholds and weights for the selected environment.'
    assert environments.get('open') is not None
    assert environments in kpis.iterancestors()
    assert hierarchy.getparent() is priority.getparent()
    assert all('scoring-config-section' in panel.get('class', '') for panel in [environments, hierarchy, priority])
    assert not tree.xpath('//details[@id="scoring-kpi-configuration"]')
    assert not tree.xpath('//*[@class and contains(@class, "scoring-config-methodology-group")]')
    buttons = form.xpath('.//button[@data-scoring-kpi-save]')
    assert len(buttons) == 4
    assert [button.text_content().strip() for button in buttons] == ['Save Methodology'] * 4
    assert all(button.get('type') == 'submit' and form in button.iterancestors() for button in buttons)
    assert len(form.xpath('.//*[@data-scoring-kpi-status]')) == 1
    status = form.xpath('.//*[@data-scoring-kpi-status]')[0]
    assert 'scoring-config-save-bar' in status.getparent().get('class', '')
    assert not status.getparent().xpath('.//button[@data-scoring-kpi-save]')
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    assert template.index('data-scoring-kpi-status') < template.index('scoring-environment-controls-title')
    assert environments.xpath('.//button[@data-scoring-kpi-save]')
    assert hierarchy.xpath('.//button[@data-scoring-kpi-save]')
    assert priority.xpath('.//button[@data-scoring-kpi-save]')
    delete_button = form.xpath('.//button[@data-scoring-profile-action="delete"]')[0]
    save_button = delete_button.getprevious()
    default_button = save_button.getprevious()
    assert default_button.get('data-scoring-profile-action') == 'default'
    assert default_button.text_content() == 'Set Default'
    assert save_button.get('data-scoring-kpi-save') is not None
    assert default_button.getprevious().get('data-scoring-profile-action') == 'rename'
    assert environments.xpath('.//h5[@data-scoring-kpi-title]')
    assert '.scoring-config-panel .scoring-config-kpi-expand-hint { display: block;' in template
    assert '.scoring-config-panel .scoring-config-kpi-group[open] .scoring-config-kpi-expand-hint { display: none; }' in template
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    assert "root.querySelector('[data-scoring-kpi-title]')" in script
    header_selector = '.workspace-config-stack .scoring-config-subpanels > .scoring-config-section.collapsible-panel > summary.collapsible-summary'
    assert f'{header_selector} {{' in template
    assert f'{header_selector} :is(h2, .eyebrow) {{ color: #fff; }}' in template
    assert f'{header_selector} .collapse-chip {{ background: #e2f1e9;' in template


def test_methodology_import_export_controls_use_requested_colors():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    import_rules = list(re.finditer(
        r'\.scoring-config-panel\s+\[data-scoring-config-import\]\s*\{([^}]*)\}', template,
    ))
    export_rules = list(re.finditer(
        r'\.scoring-config-panel\s+\[data-scoring-config-export\]\s*\{([^}]*)\}', template,
    ))
    assert import_rules and export_rules
    assert 'background: #f5d6d6' in import_rules[-1].group(1)
    assert 'color: #783737' in import_rules[-1].group(1)
    assert 'background: #267c79' in export_rules[-1].group(1)
    assert 'color: #fff' in export_rules[-1].group(1)


def test_methodology_save_commits_pending_hierarchy_and_clears_all_dirty_sections():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    start = script.index('  const saveKpis = async () => {')
    end = script.index('  const hasUnsavedChanges =', start)
    program = '''
const activeProfileId = 'methodology', environmentSelect = {value: 'City'};
const kpiStatus = {}, kpiSave = {disabled: false};
const setKpiSaveDisabled = disabled => {kpiSave.disabled = disabled;};
let kpiDirty = true, priorityDirty = true, hierarchyDirty = true, hierarchyOrder = [];
const defaultHierarchy = ['Operator', 'Vendor', 'Region', 'City', 'Campaign'];
const hierarchyDimensions = new Set(defaultHierarchy);
const requested = ['Operator', 'City', 'Campaign', 'Region', 'Vendor'];
const hierarchyRows = {querySelectorAll: () => requested.map(aggregationLevel => ({dataset:{aggregationLevel}}))};
let configuration = {title: 'Old title', aggregation_hierarchy: defaultHierarchy};
let savedId = '', verifySave = false, saveCalls = 0;
const readKpiRows = latest => ({...latest, title: 'Updated methodology', scope:{environments:{City:{}, Train:{}}}, metrics:[{code:'K1', contexts:{City:{max_points: 7}, Train:{max_points: 4}}}], gap_priority:['K2','K1']});
const saveConfiguration = async (update, profileId, preserveScope, verify) => {
  saveCalls += 1; savedId = profileId; verifySave = verify; configuration = update(configuration);
};
const setStatus = () => {}, render = () => {};
''' + script[start:end] + '''
(async () => { await saveKpis(); console.log(JSON.stringify({configuration,kpiDirty,priorityDirty,hierarchyDirty,savedId,verifySave,saveCalls})); })();
'''
    completed = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    actual = json.loads(completed.stdout)
    assert actual['configuration']['aggregation_hierarchy'] == ['Operator', 'City', 'Campaign', 'Region', 'Vendor']
    assert set(actual['configuration']['scope']['environments']) == {'City', 'Train'}
    assert actual['configuration']['gap_priority'] == ['K2', 'K1']
    assert actual['configuration']['title'] == 'Updated methodology'
    assert actual['configuration']['metrics'][0]['contexts']['Train']['max_points'] == 4
    assert not any(actual[field] for field in ('kpiDirty', 'priorityDirty', 'hierarchyDirty'))
    assert actual['savedId'] == 'methodology'
    assert actual['verifySave'] is True
    assert actual['saveCalls'] == 1


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_profile_export_tracks_selection_and_blocks_unsaved_changes():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    render_start = script.index('  const renderProfileControls = () => {')
    render_end = script.index('  const render = () => {', render_start)
    click_start = script.index("  root.querySelector('[data-scoring-config-export]')?.addEventListener('click'", render_end)
    click_end = script.index('\n  const importButton =', click_start)
    fixture = '''
const assert = require('node:assert/strict');
let activeProfileId = 'first';
let dirty = false;
const endpoint = '/api/workspace-config/scoring-configuration';
const profileCollection = {profiles: [{id: 'first'}, {id: 'second'}]};
const currentProfile = () => profileCollection.profiles.find(profile => profile.id === activeProfileId);
const exportLink = {href: '', attributes: {}, setAttribute(name, value) {this.attributes[name] = value;}, addEventListener(name, handler) {this.handler = handler;}};
const root = {querySelector: () => exportLink};
const profileSelect = null, methodologyTitleInput = null, profileActions = [];
const hasUnsavedChanges = () => dirty;
let message = '';
const setStatus = (_status, value) => {message = value;};
const kpiStatus = {};
'''+script[render_start:render_end]+script[click_start:click_end]+'''
renderProfileControls();
assert.equal(exportLink.href, '/api/workspace-config/scoring-configuration/export?profile_id=first');
activeProfileId = 'second';
renderProfileControls();
assert.equal(exportLink.href, '/api/workspace-config/scoring-configuration/export?profile_id=second');
assert.equal(exportLink.attributes['aria-disabled'], 'false');
dirty = true;
let prevented = false;
exportLink.handler({preventDefault() {prevented = true;}});
assert.equal(prevented, true);
assert.match(message, /Save the methodology before exporting its JSON/);
'''
    subprocess.run(['node', '-e', fixture], check=True, capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
@pytest.mark.parametrize('navigation, saved, expected', [('navigate', 'open', False), ('reload', 'open', True), ('reload', 'closed', False), ('back_forward', 'open', False)])
def test_kpi_panel_state_is_preserved_only_on_reload(navigation, saved, expected):
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    start = script.index("  const kpiPanel = root.querySelector('[data-scoring-kpi-panel]');")
    end = script.index("  const endpoint =", start)
    fixture = f'''
const assert = require('node:assert/strict');
const panelEvents = {{}};
const windowEvents = {{}};
const panel = {{open: false, addEventListener: (name, handler) => {{panelEvents[name] = handler;}}}};
const root = {{querySelector: () => panel}};
let stored = {json.dumps(saved)};
const window = {{
  performance: {{getEntriesByType: () => [{{type: {json.dumps(navigation)}}}]}},
  sessionStorage: {{getItem: () => stored, setItem: (_key, value) => {{stored = value;}}}},
  addEventListener: (name, handler) => {{windowEvents[name] = handler;}},
}};
{script[start:end]}
assert.equal(panel.open, {json.dumps(expected)});
panel.open = true;
panelEvents.toggle();
assert.equal(stored, 'open');
windowEvents.pagehide();
assert.equal(stored, 'open');
windowEvents.pageshow({{persisted: true}});
assert.equal(panel.open, false);
assert.equal(stored, 'closed');
'''
    subprocess.run(['node', '-e', fixture], check=True, capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_selecting_profile_does_not_change_default_or_write_profiles():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    start = script.index('  const selectProfile = async (profileId) => {')
    end = script.index('  const makeNewMetric =', start)
    fixture = '''
const assert = require('node:assert/strict');
let activeProfileId = 'default';
let profileCollection = {active_profile_id: 'default', profiles: [{id: 'default'}, {id: 'other'}]};
const profileSelect = {value: 'other'};
const kpiStatus = {};
const setProfileControlsDisabled = () => {};
const confirmProfileChange = async () => true;
const setStatus = () => {};
const loadProfiles = async () => profileCollection;
const normalizeProfileCollection = value => value;
const setProfileCollection = value => {profileCollection = value;};
const render = () => {};
const renderProfileControls = () => {};
const currentProfile = () => ({name: 'Other'});
const enqueueProfileUpdate = () => {throw new Error('Selecting must not write');};
'''
    fixture += script[start:end] + '''
(async () => {
  await selectProfile('other');
  assert.equal(activeProfileId, 'other');
  assert.equal(profileCollection.active_profile_id, 'default');
})();
'''
    subprocess.run(['node', '-e', fixture], check=True, capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
@pytest.mark.parametrize('action', ['default', 'rename', 'copy', 'delete'])
def test_profile_actions_target_selected_profile_and_change_default_explicitly(action):
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    start = script.index('  const runProfileAction = async (action) => {')
    end = script.index('  const selectProfile =', start)
    fixture = '''
const assert = require('node:assert/strict');
let activeProfileId = 'other';
let profileCollection = {active_profile_id: 'default', profiles: [{id: 'default', name: 'Default', configuration: {}}, {id: 'other', name: 'Other', configuration: {}}]};
let kpiDirty = true;
const kpiStatus = {};
const setProfileControlsDisabled = () => {};
const confirmProfileChange = async () => true;
const setStatus = () => {};
const currentProfile = () => profileCollection.profiles.find(profile => profile.id === activeProfileId);
const openProfileDialog = async () => 'Changed';
const createProfileId = () => 'copy';
const clone = value => structuredClone(value);
const enqueueProfileUpdate = async (update) => {profileCollection = update(clone(profileCollection));};
const setProfileCollection = () => {};
const discardUnsavedChanges = () => {kpiDirty = false;};
const render = () => {};
const renderProfileControls = () => {};
'''
    fixture += script[start:end] + f'''
(async () => {{
  await runProfileAction({json.dumps(action)});
  assert.equal(profileCollection.active_profile_id, {json.dumps('other' if action == 'default' else 'default')});
  assert.equal(profileCollection.profiles[0].name, 'Default');
  if ({json.dumps(action)} === 'default') assert.equal(kpiDirty, true);
  if ({json.dumps(action)} === 'rename') assert.equal(profileCollection.profiles[1].name, 'Changed');
  if ({json.dumps(action)} === 'copy') assert.equal(activeProfileId, 'copy');
  if ({json.dumps(action)} === 'delete') assert.ok(!profileCollection.profiles.some(profile => profile.id === 'other'));
}})();
'''
    subprocess.run(['node', '-e', fixture], check=True, capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_default_profile_delete_is_disabled_and_rejected():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')
    controls_start = script.index('  const setProfileControlsDisabled = (disabled) => {')
    action_end = script.index('  const selectProfile =', controls_start)
    fixture = '''
const assert = require('node:assert/strict');
let activeProfileId = 'default';
let profileCollection = {active_profile_id: 'default', profiles: [{id: 'default'}, {id: 'other'}]};
const profileSelect = {};
const deleteButton = {dataset: {scoringProfileAction: 'delete'}};
const profileActions = [deleteButton];
const currentProfile = () => profileCollection.profiles.find(profile => profile.id === activeProfileId);
const kpiStatus = {};
const setStatus = () => {};
const renderProfileControls = () => {};
const confirmProfileChange = async () => {throw new Error('Delete must be rejected before confirmation');};
const enqueueProfileUpdate = async () => {throw new Error('Default profile must not be deleted');};
'''
    fixture += script[controls_start:action_end] + '''
(async () => {
  setProfileControlsDisabled(false);
  assert.equal(deleteButton.disabled, true);
  await runProfileAction('delete');
  assert.equal(profileCollection.profiles.length, 2);
  assert.equal(deleteButton.disabled, true);
  activeProfileId = 'other';
  setProfileControlsDisabled(false);
  assert.equal(deleteButton.disabled, false);
})();
'''
    subprocess.run(['node', '-e', fixture], check=True, capture_output=True, text=True)


def test_editor_text_actions_include_svg_icons():
    from lxml import html

    tree = html.fromstring(PANEL_TEMPLATE.read_text(encoding='utf-8'))
    buttons = tree.xpath('//button')
    assert buttons
    assert all(button.xpath('./svg[@aria-hidden="true"]') for button in buttons)
    assert tree.xpath('//a[@data-scoring-config-export]/svg')
