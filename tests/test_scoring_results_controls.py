from pathlib import Path
import re
import json
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_TEMPLATE = PROJECT_ROOT / 'src/web_interface/templates/scoring.html'
SCORING_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring.js'


def _function_source(script: str, name: str) -> str:
    start = script.index(f'  function {name}(')
    end = script.index('\n  }', start) + len('\n  }')
    return script[start:end]


def _constant_source(script: str, name: str) -> str:
    start = script.index(f'  const {name} =')
    end = script.index('\n  };', start) + len('\n  };')
    return script[start:end]


def _run_node_json(program: str, payload: dict) -> dict:
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for scoring results state behavior checks.')
    completed = subprocess.run(
        [node, '-e', program], input=json.dumps(payload), capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_results_environment_defaults_to_all_and_exports_selected_scope():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert "let selectedEnvironment = restoredScoringViewState.environment || 'all';" in script
    assert "return ordered.length || combinedIsAvailable ? ['all', ...ordered] : [];" in script
    assert "selectedEnvironment === 'all'" in script
    assert "const combinedIsAvailable = tables.some(table => environmentOf(table) === 'Combined');" in script
    assert "? (combinedIsAvailable ? 'Combined' : null)" in script
    assert 'All Environments aggregate is unavailable in this saved result' in script
    assert "actual[0]" not in script
    assert '&environment=${encodeURIComponent(selectedEnvironment || \'all\')}' in script
    assert 'All Environments' in script
    assert 'defaults to all environments' in template


def test_best_network_chart_keeps_its_intrinsic_width_on_narrow_cards():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert re.search(
        r'\.scoring-chart-svg\.scoring-best-network-bars\s*\{[^}]*min-width:\s*0;'
        r'[^}]*max-width:\s*none;[^}]*min-height:\s*0;', template,
    )
    assert "svg.style.minWidth = '0';" in script
    assert "svg.style.width = `${100 * width / visibleWidth}%`;" in script
    assert "svg.style.maxWidth = 'none';" in script
    assert "scroll.className = 'scoring-chart-scroll';" in script
    assert 'const baseHeight = 620;' in script
    assert 'const plotHeight = baseHeight - 72 - bottom;' in script
    assert 'const scaleValue = maxActual > 0 ? maxActual : maxAllocation;' in script


def test_scoring_chart_pairs_render_five_operator_two_category_views():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    names = (
        'firstValue', 'isReferenceOperator', 'operatorPresentation', 'safeHexColor',
        'wrappedSvgLabelLines', 'setChartTooltip', 'formattedChartPoints',
        'chartEnvironmentName', 'categoryLegendGray', 'chartCategoryLegend', 'chartLegendTextWidth',
        'chartLegendRows', 'categoryLegendTextLines', 'categoryLegendTextColor',
        'makeSvgChart', 'chartOperatorLegend', 'makeExpandableChartCard',
        'renderCharts', 'renderHierarchyCharts', 'svgElement', 'hierarchyChartColor',
        'hierarchyPathEntry', 'hierarchyPrefixKey', 'appendHierarchyAxisBands',
        'hierarchyPathValueLabel', 'hierarchyPathFullLabel', 'chartFitWidth',
    )
    payload = {'snippets': {name: _function_source(script, name) for name in names}}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.namespaceURI = 'http://www.w3.org/2000/svg';
    this.attributes = {};
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.className = '';
    this.clientWidth = 1000;
    this.classList = {add: value => { this.className = `${this.className} ${value}`.trim(); }};
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this.className = String(value);
    if (name === 'viewBox') {
      const [,, width, height] = String(value).split(/\s+/).map(Number);
      this.viewBox = {baseVal: {width, height}};
    }
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener() {}
}
const document = {
  createElement: tag => new Element(tag),
  createElementNS: (_namespace, tag) => new Element(tag),
};
const operators = ['Vodafone', 'O2', 'Three', 'EE', 'TestNet'];
const palette = ['#da291c', '#0033a0', '#111111', '#17a09f', '#7851a9'];
const table = {
  title: 'Campaign 2026',
  context: {campaign: '2026Q2', environment: 'DriveCity'},
  operators,
  baseline_operator: 'EE',
  operator_styles: Object.fromEntries(operators.map((operator, index) => [operator, {
    label: operator, color: palette[index], position: index,
  }])),
};
table.chartRows = ['Voice', 'Data'].flatMap((category, categoryIndex) => operators.map((operator, operatorIndex) => ({
  category, operator, weighted_points: 20 + categoryIndex * 7 + operatorIndex, complete: true,
})));
const hierarchyColumns = operators.flatMap((operator, operatorIndex) => [1, 2].map(contextIndex => {
  const id = `${operator}-context-${contextIndex}`;
  table.operator_styles[id] = {label: id, color: palette[operatorIndex], position: operatorIndex};
  return {
    id, operator, label: `${operator} Context ${contextIndex}`, styleSource: table,
    path: [{level: 'Operator', value: operator}, {level: 'City', value: `${operator} Context ${contextIndex}`}],
  };
}));
function hierarchyRows(categories) {
  return categories.flatMap((category, categoryIndex) => hierarchyColumns.map((column, columnIndex) => ({
    category, operator: column.id,
    weighted_points: categoryIndex === 1 && columnIndex === 0 ? null : 8 + categoryIndex * 3 + columnIndex,
    complete: !(categoryIndex === 1 && columnIndex === 0),
  })));
}
function descendants(node) { return [node, ...(node.children || []).flatMap(descendants)]; }
function pane() {
  const value = new Element('div');
  value.classList.add = name => { value.className = `${value.className} ${name}`.trim(); };
  return value;
}
const context = {
  document,
  chartTooltip: {id: 'chart-tooltip'},
  scoreChartRows: tables => tables[0].chartRows,
  chartTableForRow: (_row, tables) => tables[0],
  rowText: (row, names) => {
    for (const name of names) if (row[name] !== undefined && row[name] !== null) return String(row[name]);
    return '';
  },
  appendComparisonSelector: (_pane, groups) => groups[0],
  appendContextHeader: () => {},
  contextLabel: () => 'Campaign 2026 · DriveCity',
  hierarchyColumnEntries: data => data.columns,
  hierarchyColumnOperator: column => column.operator,
  hierarchyColumnIsReference: column => column.operator === 'EE' && column.id.endsWith('context-1'),
  humanizeKey: key => key,
  environmentLabel: value => value,
  normalizeRows: () => [],
  scoreNumber: () => null,
};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + `
  globalThis.renderers = {renderCharts, renderHierarchyCharts};`, context);
function inspect(target) {
  const svgs = descendants(target).filter(node => node.className === 'scoring-chart-svg');
  return svgs.map(svg => {
    const nodes = descendants(svg);
    const bars = nodes.filter(node => node.tagName === 'rect' && (node.attributes['data-chart-tooltip'] || '').includes('Weighted points:'));
    return {
      title: svg.attributes['aria-label'],
      operatorLegend: nodes.filter(node => node.className === 'scoring-chart-legend').map(node => node.textContent),
      categoryLegendSegments: nodes.filter(node => node.className === 'scoring-chart-category-legend-segment').length,
      scoredBars: bars.length,
      barFills: bars.map(node => node.attributes.fill),
      unavailable: nodes.filter(node => node.className === 'scoring-chart-unavailable' && node.textContent === 'N/A').length,
      viewBoxWidth: svg.viewBox.baseVal.width,
      widthStyle: svg.style.width || '',
      minWidthStyle: svg.style.minWidth || '',
    };
  });
}
const simplePane = pane();
context.renderers.renderCharts(simplePane, [], [table]);
const hierarchyPane = pane();
context.renderers.renderHierarchyCharts(hierarchyPane, {
  ...table, chartRows: hierarchyRows(['Voice', 'Data']), hierarchy_levels: ['Operator', 'City'], columns: hierarchyColumns,
});
const categories = ['Classic Calls', 'WhatsApp Calls', 'Multi RAB', 'Streaming', 'Web Browsing', 'Messaging', 'Upload'];
table.chartRows = categories.flatMap((category, categoryIndex) => operators.map((operator, operatorIndex) => ({
  category, operator, weighted_points: 10 + categoryIndex * 3 + operatorIndex, complete: true,
})));
const wideSimplePane = pane();
context.renderers.renderCharts(wideSimplePane, [], [table]);
const wideHierarchyPane = pane();
context.renderers.renderHierarchyCharts(wideHierarchyPane, {
  ...table, chartRows: hierarchyRows(categories), hierarchy_levels: ['Operator', 'City'], columns: hierarchyColumns,
});
process.stdout.write(JSON.stringify({
  simple: inspect(simplePane), hierarchy: inspect(hierarchyPane),
  wideSimple: inspect(wideSimplePane), wideHierarchy: inspect(wideHierarchyPane), palette,
}));
"""
    result = _run_node_json(program, payload)

    for charts in (result['simple'], result['hierarchy']):
        assert len(charts) == 2
        top, bottom = charts
        assert len(top['operatorLegend']) == 5
        assert len(bottom['operatorLegend']) == 5
        assert top['categoryLegendSegments'] == 2
        assert bottom['categoryLegendSegments'] == 0
        expected_bars = 10 if charts is result['simple'] else 19
        expected_missing = 0 if charts is result['simple'] else 1
        assert top['scoredBars'] == expected_bars
        assert bottom['scoredBars'] == expected_bars
        assert top['unavailable'] == 0
        assert bottom['unavailable'] == expected_missing
        assert set(bottom['barFills']) == set(result['palette'])
    for charts in (result['wideSimple'], result['wideHierarchy']):
        assert len(charts) == 2
        top, bottom = charts
        assert len(top['operatorLegend']) == 5
        assert len(bottom['operatorLegend']) == 5
        assert top['categoryLegendSegments'] == 7
        assert bottom['categoryLegendSegments'] == 0
        expected_bars = 35 if charts is result['wideSimple'] else 69
        expected_missing = 0 if charts is result['wideSimple'] else 1
        assert top['scoredBars'] == expected_bars
        assert bottom['scoredBars'] == expected_bars
        assert top['unavailable'] == 0
        assert bottom['unavailable'] == expected_missing
        assert set(bottom['barFills']) == set(result['palette'])
        assert bottom['viewBoxWidth'] <= 1000
        assert bottom['widthStyle'] == '100%'
        assert bottom['minWidthStyle'] == '0'


def test_reference_header_uses_operator_mapping_accent_without_yellow_marker():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert '.scoring-comparison-table .scoring-operator-header { border-bottom: 3px solid var(--operator-accent, #607d8b) !important; }' in template
    assert '.scoring-comparison-table th.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-hierarchy-header.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-gap-header { background: #ffff00 !important; color: #242424 !important; }' in template
    assert "function markReferenceHeader(header) {\n    header.classList.add('scoring-reference-header');" in script
    assert 'header.title = `${label} is the reference operator`;' in script


def test_operator_color_and_reference_markers_stay_on_operator_headers():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert '.scoring-comparison-table .scoring-operator-header { border-bottom: 3px solid var(--operator-accent, #607d8b) !important; }' in template
    assert '.scoring-comparison-table th.scoring-gap-operator-header { border-bottom: 3px solid var(--operator-accent, #607d8b) !important; }' in template
    assert '.scoring-comparison-table th.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-hierarchy-header.scoring-reference-header' not in template
    hierarchy_header_rule = re.search(
        r'\.scoring-comparison-table th\.scoring-hierarchy-header\s*\{([^}]*)\}', template,
    )
    assert hierarchy_header_rule and 'border-' not in hierarchy_header_rule.group(1)
    assert "String(entry.level).toLocaleLowerCase() === 'operator'" in script


def test_export_links_have_distinct_high_contrast_colors():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert '.scoring-export-actions a[data-export-scoring] { border-color: #16734b; background: #16734b; color: #fff; }' in template
    assert '.scoring-export-actions a[data-export-gap] { border-color: #1267a5; background: #1267a5; color: #fff; }' in template
    assert '.scoring-export-actions a[data-export-ppt] { border-color: #a84d00; background: #a84d00; color: #fff; }' in template


def test_gap_value_toggle_defaults_off_and_only_changes_scoring_tables():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    gap_toggle = re.search(r'<label class="scoring-kpi-values-toggle" data-show-gap-label>(.*?)</label>', template, re.S)
    assert gap_toggle
    assert 'data-show-gap-values' in gap_toggle.group(1)
    assert 'Show GAP values' in gap_toggle.group(1)
    assert 'checked' not in gap_toggle.group(1)
    assert "if (showGapValuesToggle) showGapValuesToggle.checked = restoredScoringViewState.showGapValues === true;" in script
    assert "function showGapValues() {\n    return Boolean(showGapValuesToggle?.checked);" in script
    assert "if (!showGapValues()) {\n      for (const [operatorIndex, operator] of operators.entries()) appendScore(operator, operatorIndex);\n      return;" in script
    assert "if (event.target === showGapValuesToggle) {\n      syncGapValueControls();\n      if (currentResults) renderResult(currentResults, selectedJob, ['scoring']);" in script
    assert "function renderTable(pane, source, emptyCopy, {hideGapColumns = false} = {})" in script
    assert "renderTable(gapPane, gapRows, 'No GAP rows are available for the selected baseline operator.');" in script
    assert "function appendScoringGapScale(pane, tableData) {\n    if (!showGapValues()) return;" in script
    assert script.count("label.textContent = showGapValues() && total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';") == 2


def test_environment_selector_precedes_value_toggles_and_gap_layout_is_conditional():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    selector_row = re.search(r'<div class="scoring-results-selector-row"[^>]*>(.*?)</div>', template, re.S)
    value_row = re.search(r'<div class="scoring-results-value-row"[^>]*>(.*?)</div>', template, re.S)
    assert selector_row and value_row
    environment_index = selector_row.group(1).index('data-result-environment-control')
    assert 'data-scoring-table-mode' not in template
    assert template.index('data-scoring-results-selector-row') < template.index('data-show-kpi-values')
    assert 'data-scoring-gap-layout-control hidden' in template
    assert 'if (gapLayoutControl) gapLayoutControl.hidden = !showGapValues();' in script


def test_gap_value_choice_is_sent_only_to_powerpoint_export():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert "const gapOption = kind === 'ppt' ? `&show_gap_values=${showGapValues() ? 'true' : 'false'}` : '';" in script
    assert "link.href = enabled ? `${exportBase}/${encodeURIComponent(jobId)}/export/${kind}?${query}${gapOption}` : '#';" in script
    assert "const query = `table_mode=${encodeURIComponent(selectedTableMode())}&gap_layout=${encodeURIComponent(selectedGapLayout())}&environment=${encodeURIComponent(selectedEnvironment || 'all')}`;" in script


def test_scoring_tab_is_plural_and_category_subtotals_have_gray_background():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert 'data-result-tab="scoring">Scoring Tables</button>' in template
    assert 'data-result-tab="scoring">Scoring Table</button>' not in template
    assert '.scoring-comparison-table tbody tr.scoring-category-subtotal > td { background-color: #e3e6e7 !important; font-weight: 700 !important; }' in template


def test_render_warnings_hides_only_legacy_campaign_pooling_notice():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    renderer = re.search(r'function renderWarnings\(warnings\) \{(.*?)\n  \}', script, re.S)
    assert renderer
    body = renderer.group(1)

    assert "const legacyCampaignNotice = 'Campaigns are scored separately; the supplied Tableau Prep flow pools campaigns.';" in body
    assert "const visibleItems = items.filter(warning => (\n      (typeof warning === 'string' ? warning : displayValue(warning)) !== legacyCampaignNotice\n    ));" in body
    assert 'box.hidden = !visibleItems.length;' in body
    assert 'for (const warning of visibleItems)' in body
    assert 'items.splice' not in body


def test_scoring_view_state_round_trips_filters_and_false_checkboxes():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    snippets = {
        name: _function_source(script, name)
        for name in ('readScoringViewState', 'persistScoringViewState', 'selectedTableMode', 'selectedGapLayout', 'showGapValues')
    }
    payload = {
        'snippets': snippets,
        'storageKey': 'dashboard-analytic:scoring-view:jaime:workspace-a',
        'initial': {
            'job_id': 'job-17', 'result_tab': 'gap', 'scroll_y': 321,
            'environment': 'DriveCity', 'gap_layout': 'sideways',
            'show_kpi_values': False, 'show_gap_values': False,
        },
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const values = new Map([[payload.storageKey, JSON.stringify(payload.initial)]]);
const context = {
  scoringViewStorageKey: payload.storageKey,
  resultTabNames: new Set(['scoring', 'gap', 'charts', 'best-network']),
  window: {scrollY: 777, sessionStorage: {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  }},
  selectedJobId: null,
  activeResultTab: 'scoring',
  selectedEnvironment: 'all',
  gapLayoutSelect: {value: 'end'},
  showKpiValuesToggle: {checked: true},
  showGapValuesToggle: {checked: true},
};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + '\nglobalThis.restored = readScoringViewState();', context);
const restored = context.restored;
context.selectedJobId = restored.jobId;
context.activeResultTab = restored.resultTab;
context.selectedEnvironment = restored.environment;
context.gapLayoutSelect.value = restored.gapLayout;
context.showKpiValuesToggle.checked = restored.showKpiValues;
context.showGapValuesToggle.checked = restored.showGapValues;
vm.runInContext('persistScoringViewState()', context);
process.stdout.write(JSON.stringify({restored, saved: JSON.parse(values.get(payload.storageKey))}));
"""
    result = _run_node_json(program, payload)

    assert 'tableMode' not in result['restored']
    assert result['restored']['gapLayout'] == 'end'
    assert result['restored']['showKpiValues'] is False
    assert result['restored']['showGapValues'] is False
    assert result['saved']['show_kpi_values'] is False
    assert result['saved']['show_gap_values'] is False
    assert 'table_mode' not in result['saved']
    assert result['saved']['gap_layout'] == 'end'
    assert result['saved']['environment'] == 'DriveCity'


def test_scoring_tables_render_both_summary_and_expanded_modes():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    payload = {'tableForMode': _function_source(script, 'tableForMode')}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const context = {};
vm.createContext(context);
vm.runInContext(payload.tableForMode + `
  const fixture = {
    rows: [{name: 'legacy'}], total: {points: 99},
    category_rows: [{name: 'summary'}], category_total: {points: 40},
    expanded_rows: [{name: 'expanded'}], expanded_total: {points: 75},
  };
  globalThis.summary = tableForMode(fixture, 'summary');
  globalThis.expanded = tableForMode(fixture, 'expanded');`, context);
process.stdout.write(JSON.stringify({summary: context.summary, expanded: context.expanded}));
"""
    result = _run_node_json(program, payload)

    assert result['summary']['rows'] == [{'name': 'summary'}]
    assert result['summary']['total'] == {'points': 40}
    assert result['expanded']['rows'] == [{'name': 'expanded'}]
    assert result['expanded']['total'] == {'points': 75}
    assert 'data-scoring-table-mode' not in template
    assert "tableForMode(selected, 'summary')" in script
    assert "tableForMode(selected, 'expanded')" in script


def test_raw_kpi_columns_are_hidden_in_summary_and_shown_in_expanded():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    names = (
        'firstValue', 'isReferenceOperator', 'markReferenceHeader', 'operatorPresentation',
        'safeHexColor', 'readableTextColor', 'formatMatrixNumber', 'formatRawKpiValue',
        'formatScoreCell', 'createKpiTypeCell', 'addMatrixScoreCell', 'operatorValue',
        'appendScoreGapCells', 'showGapValues', 'selectedGapLayout', 'tableForMode',
        'appendMatrixTable', 'renderScoringViews',
    )
    payload = {'snippets': {name: _function_source(script, name) for name in names}}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.style = {setProperty() {}};
    this.attributes = {};
    this.className = '';
    this.classList = {add: value => { this.className = `${this.className} ${value}`.trim(); }};
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
}
const document = {createElement: tag => new Element(tag)};
const table = {
  title: 'Campaign 2026', context: {campaign: '2026Q2'},
  operators: ['EE', 'O2'], baseline_operator: 'EE',
  operator_styles: {EE: {label: 'EE', color: '#17a09f'}, O2: {label: 'O2', color: '#0033a0'}},
  category_rows: [
    {row_type: 'category', category: 'Voice', kpi: 'Voice', weight_percent: 100, max_points: 1000, values: {}},
  ],
  expanded_rows: [
    {row_type: 'kpi', category: 'Voice', kpi: 'Call Setup', kpi_code: 'call_setup', kpi_type: 'Reliable', weight_percent: 50, max_points: 500,
      values: {EE: {value: 12.345, points: 400, complete: true}, O2: {value: 67.891, points: 350, complete: true}}},
    {row_type: 'kpi', category: 'Voice', kpi: 'Drop Rate', kpi_code: 'drop_rate', kpi_type: 'Diff', weight_percent: 50, max_points: 500,
      values: {EE: {value: 1.2, points: 450, complete: true}, O2: {value: 2.3, points: 420, complete: true}}},
  ],
  category_total: {weight_percent: 100, max_points: 1000},
  expanded_total: {weight_percent: 100, max_points: 1000},
};
function descendants(node) { return [node, ...(node.children || []).flatMap(descendants)]; }
const context = {
  document,
  showKpiValuesToggle: {checked: true},
  gapLayoutSelect: {value: 'end'},
  showGapValuesToggle: {checked: false},
  scoringValueObservers: new Map(),
  disconnectScoringValueObservers: () => {},
  observeScoringValueCells: () => {},
  appendComparisonSelector: (_pane, tables) => tables[0],
  appendContextHeader: () => {},
  appendThresholdLegend: () => {},
  appendScoringGapScale: () => {},
  addMatrixGapCell: () => {},
};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + `
  globalThis.render = renderScoringViews;`, context);
const pane = new Element('div');
context.render(pane, [table]);
const sections = pane.children.filter(node => node.tagName === 'section');
function summarize(section) {
  const nodes = descendants(section);
  return {
    heading: nodes.find(node => node.className === 'scoring-table-section-title')?.textContent,
    valueGroups: nodes.filter(node => node.className.includes('scoring-kpi-value-group')).length,
    valueHeaders: nodes.filter(node => node.tagName === 'th' && node.className.includes('scoring-kpi-value-header')).length,
    rawCells: nodes.filter(node => node.tagName === 'td' && node.dataset.column === 'kpi-value').map(node => node.textContent),
  };
}
process.stdout.write(JSON.stringify(sections.map(summarize)));
"""
    results = _run_node_json(program, payload)

    assert [section['heading'] for section in results] == [
        'Scoring Tables — Summary', 'Scoring Tables — Expanded',
    ]
    assert results[0]['valueGroups'] == 0
    assert results[0]['valueHeaders'] == 0
    assert results[0]['rawCells'] == []
    assert results[1]['valueGroups'] == 1
    assert results[1]['valueHeaders'] == 2
    assert results[1]['rawCells'] == ['12.35', '67.89', '1.20', '2.30', 'N/A', 'N/A']
    assert script.count("tableData?._display_mode !== 'summary' && Boolean(showKpiValuesToggle?.checked)") == 2


def test_scoring_view_state_falls_back_to_all_when_saved_environment_is_unavailable():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    helpers_start = script.index('  const environmentOrder =')
    helpers_end = script.index('  function chartRowsForEnvironment', helpers_start)
    environment_helpers = script[helpers_start:helpers_end]
    payload = {'helpers': environment_helpers}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const select = {
  options: [], value: '',
  replaceChildren() { this.options = []; },
  append(option) { this.options.push(option); },
};
const context = {
  document: {createElement: () => ({value: '', textContent: ''})},
  selectedEnvironment: 'DriveConnectionroad',
  environmentSelect: select,
  environmentControl: {hidden: true},
  currentEffectiveEnvironment: null,
};
vm.createContext(context);
vm.runInContext(payload.helpers + `
  globalThis.result = syncResultEnvironment([
    {context: {environment: 'DriveCity'}},
    {context: {environment: 'Combined'}},
  ]);`, context);
process.stdout.write(JSON.stringify({
  selectedEnvironment: context.selectedEnvironment,
  effective: context.result.effective,
  unavailable: context.result.unavailable,
  options: select.options.map(option => option.value),
}));
"""
    result = _run_node_json(program, payload)

    assert result['selectedEnvironment'] == 'all'
    assert result['effective'] == 'Combined'
    assert result['unavailable'] is False
    assert result['options'] == ['all', 'DriveCity']


def test_scoring_job_title_and_cdr_summary_use_saved_filters_and_source_names():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    snippets = [
        _constant_source(script, 'valueOf'),
        _function_source(script, 'uniqueCatalogueValues'),
        _function_source(script, 'firstValue'),
        _function_source(script, 'formatDate'),
        _function_source(script, 'savedJobFilterValues'),
        _function_source(script, 'campaignLabels'),
        _function_source(script, 'jobCampaigns'),
        _function_source(script, 'jobCardTitleSegments'),
        _function_source(script, 'jobCardTitle'),
        _function_source(script, 'jobCdrSummary'),
    ]
    payload = {
        'snippets': snippets,
        'job': {
            'created_at': '2026-10-01T12:00:00Z', 'nr_mode': 'NSA',
            'dataset_names': ['data.csv', 'voice.csv', 'voice.csv'],
            'context_filters': {'Operator': [], 'Vendor': [], 'Region': [], 'City': [], 'Campaign': []},
            'resolved_context_filters': {
                'Operator': ['EE', 'EE', 'O2'], 'Vendor': ['Nokia'], 'Region': ['North'],
                'City': ['Leeds'], 'Campaign': ['UK_Q2_2026'],
            },
            'source_metadata': [{'campaign': 'UK_Q2_2026'}],
        },
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const context = {job: payload.job};
vm.createContext(context);
vm.runInContext(payload.snippets.join('\n') + `
  globalThis.title = jobCardTitle(job);
  globalThis.cdrSummary = jobCdrSummary(job);
  globalThis.metadataCdrSummary = jobCdrSummary({source_metadata: {data: {name: 'data.csv'}, voice: {name: 'voice.csv'}}});
  globalThis.fallbackTitle = jobCardTitle({created_at: 'not-a-date', nr_mode: 'SA', dataset_ids: [1], source_metadata: [{campaigns: ['UK_Q3_2026']}]});`, context);
process.stdout.write(JSON.stringify({title: context.title, cdrSummary: context.cdrSummary,
  metadataCdrSummary: context.metadataCdrSummary, fallbackTitle: context.fallbackTitle}));
"""
    result = _run_node_json(program, payload)

    assert result['title'].split(' ● ')[1:] == [
        'NSA', 'EE, O2', 'Nokia', 'North', 'Leeds', 'UK_Q2_2026',
    ]
    assert result['cdrSummary'] == 'data.csv, voice.csv'
    assert result['metadataCdrSummary'] == 'data.csv, voice.csv'
    assert result['fallbackTitle'].split(' ● ')[1:] == [
        'SA', 'All Operators', 'All Vendors', 'All Regions', 'All Cities', 'UK_Q3_2026',
    ]


def test_kpi_value_cells_are_blank_for_category_subtotals_in_both_table_modes():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert script.count("cell.textContent = isCategoryRow ? '' : formatRawKpiValue(rawValue);") == 2
    assert script.count("const isCategoryRow = item?.row_type === 'category';") == 2
