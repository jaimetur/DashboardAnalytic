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


def test_best_network_charts_start_scoring_charts_and_legacy_tab_migrates():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert 'data-result-tab="best-network"' not in template
    assert "const resultTabNames = new Set(['scoring', 'gap', 'charts']);" in script
    assert "stored.result_tab === 'best-network' ? 'charts'" in script
    renderer = _function_source(script, 'renderBestNetworkChart')
    allocation_renderer = _function_source(script, 'renderCategoryAllocation')
    assert allocation_renderer.index("makeExpandableChartCard('Maximum score allocation per environment & category'") >= 0
    assert "pane.insertBefore(layout, card)" in allocation_renderer
    assert renderer.index("makeExpandableChartCard('Best Network Scoring per Service'") < renderer.index(
        "makeExpandableChartCard('Maximum score allocation per environment & service'"
    )
    assert "pane.insertBefore(layout, pane.querySelector(':scope > .scoring-best-network-layout, :scope > .scoring-chart-card'))" in renderer
    assert "renderBestNetworkChart(chartPane, scoreTables, hierarchyScoreTable, allScoreTables)" in script
    assert "renderCategoryAllocation(chartPane, scoreTables, hierarchyScoreTable, allScoreTables)" in script
    assert script.index('renderCategoryAllocation(chartPane,') < script.index('renderBestNetworkChart(chartPane,')
    assert 'Best Network Scoring per Category' in script
    assert 'Scoring per Category' in script

    payload = {
        'snippets': {
            'readScoringViewState': _function_source(script, 'readScoringViewState'),
        },
        'storageKey': 'dashboard-analytic:scoring-view:test:workspace',
        'legacyState': {'result_tab': 'best-network'},
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const values = new Map([[payload.storageKey, JSON.stringify(payload.legacyState)]]);
const context = {
  scoringViewStorageKey: payload.storageKey,
  resultTabNames: new Set(['scoring', 'gap', 'charts']),
  window: {sessionStorage: {getItem: key => values.get(key) ?? null}},
};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + '\nglobalThis.restored = readScoringViewState();', context);
process.stdout.write(JSON.stringify(context.restored));
"""
    result = _run_node_json(program, payload)
    assert result['resultTab'] == 'charts'


def test_scoring_table_value_row_is_hidden_outside_scoring_tab_without_changing_options():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    assert 'data-scoring-results-value-row' in template

    payload = {'snippet': _function_source(script, 'syncResultTableControls')}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const row = {hidden: false};
const context = {
  row,
  root: {querySelector: selector => selector === '[data-scoring-results-value-row]' ? row : null},
  activeResultTab: 'scoring',
  showKpiValuesToggle: {checked: true},
  showGapValuesToggle: {checked: false},
};
vm.createContext(context);
vm.runInContext(payload.snippet + `
const visibility = {};
for (const tab of ['scoring', 'gap', 'charts']) {
  activeResultTab = tab;
  syncResultTableControls();
  visibility[tab] = {hidden: row.hidden, options: [showKpiValuesToggle.checked, showGapValuesToggle.checked]};
}
globalThis.result = visibility;`, context);
process.stdout.write(JSON.stringify(context.result));
"""
    result = _run_node_json(program, payload)
    assert result == {
        'scoring': {'hidden': False, 'options': [True, False]},
        'gap': {'hidden': True, 'options': [True, False]},
        'charts': {'hidden': True, 'options': [True, False]},
    }


def test_results_controls_are_grouped_with_icons_and_unique_environment_heading():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    header = re.search(r'<div class="scoring-results-head">(.*?)<div class="scoring-result-tabs"', template, re.S)
    assert header
    markup = header.group(1)
    primary = re.search(r'<div class="scoring-results-primary">(.*?)</div>\s*<div class="scoring-results-tools">', markup, re.S)
    tools = re.search(r'<div class="scoring-results-tools">(.*)</div>\s*$', markup, re.S)
    assert primary and tools
    left_markup = primary.group(1)
    right_markup = tools.group(1)
    assert left_markup.index('data-result-environment-control') < left_markup.index('data-scoring-results-value-row')
    assert left_markup.index('data-show-kpi-values') < left_markup.index('data-show-gap-values')
    assert right_markup.index('data-config-shortcut="kpi"') < right_markup.index('data-export-scoring')
    assert right_markup.index('data-config-shortcut="gap"') < right_markup.index('data-export-scoring')
    for marker in (
        'data-config-shortcut="kpi"', 'data-config-shortcut="hierarchy"', 'data-config-shortcut="gap"',
        'data-export-scoring', 'data-export-gap', 'data-export-ppt',
    ):
        anchor = re.search(rf'<a\b[^>]*{re.escape(marker)}[^>]*>(.*?)</a>', right_markup, re.S)
        assert anchor and '<svg ' in anchor.group(1) and 'viewBox="0 0 20 20"' in anchor.group(1)
    assert '.scoring-results-head { display: grid; grid-template-columns: minmax(0,1fr) auto;' in template
    assert '.scoring-results-tools { grid-column: 2; grid-row: 1; display: flex; align-items: center; justify-content: flex-end; flex-wrap: nowrap;' in template
    assert '.scoring-results-config-shortcuts svg, .scoring-export-actions svg {' in template
    assert 'fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round;' in template
    assert '.scoring-results-config-shortcuts, .scoring-results-tools > .scoring-export-actions { justify-content: flex-end; }' in template

    payload = {
        'snippets': {
            'appendContextHeader': _function_source(script, 'appendContextHeader'),
            'environmentLabel': _function_source(script, 'environmentLabel'),
            'humanizeKey': _function_source(script, 'humanizeKey'),
        },
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tagName) { this.tagName = tagName; this.children = []; this.className = ''; this.ownText = ''; }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get textContent() { return this.ownText + this.children.map(child => child.textContent).join(''); }
  append(...nodes) { this.children.push(...nodes); }
}
const document = {createElement: tag => new Element(tag)};
const context = {document, Element, displayValue: value => String(value)};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + `
const results = [];
for (const [kind, title] of [['score', 'Scoring Tables'], ['gap', 'GAP Analysis'], ['charts', 'Scoring Charts']]) {
  const pane = new Element('section');
  appendContextHeader(pane, {context: {environment: 'DriveCity', campaign: '2026Q2', city: 'London'}}, kind, title);
  const heading = pane.children[0];
  results.push({
    title: heading.ownText,
    environmentChips: heading.children.filter(child => child.className.includes('scoring-environment-chip')).map(child => child.textContent),
    otherContextChips: pane.children.filter(child => child.className === 'scoring-context-chips')
      .flatMap(group => group.children.map(child => child.textContent)),
  });
}
globalThis.result = results;`, context);
process.stdout.write(JSON.stringify(context.result));
"""
    result = _run_node_json(program, payload)
    assert [item['title'] for item in result] == ['Scoring Tables', 'GAP Analysis', 'Scoring Charts']
    assert all(item['environmentChips'] == ['Environment: Drive City'] for item in result)
    assert all('Environment:' not in ' '.join(item['otherContextChips']) for item in result)


def test_category_allocation_donut_uses_configured_maxima_order_and_tooltips():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    names = (
        'maximumAllocationEnvironments', 'maximumAllocationCategories',
        'allocationEnvironmentLabel', 'allocationCategoryLabel', 'allocationIconPath', 'allocationSectorPath',
        'wrappedSvgLabelLines', 'safeHexColor', 'readableTextColor', 'makeMaximumAllocationDonut',
    )
    payload = {
        'snippets': {name: _function_source(script, name) for name in names},
        'configuration': {
            'scope': {'environments': {'DriveCity': {'total_points': 100}, 'UrbanRoad': {'total_points': 50}}},
            'metrics': [
                {'category': 'Calls', 'source_kind': 'voice', 'contexts': {
                    'DriveCity': {'max_points': 30}, 'UrbanRoad': {'max_points': 8},
                }},
                {'category': 'Connectivity', 'source_kind': 'data', 'contexts': {
                    'DriveCity': {'max_points': 50}, 'UrbanRoad': {'max_points': 10},
                }},
                {'category': 'Calls', 'source_kind': 'speech', 'contexts': {
                    'DriveCity': {'max_points': 20}, 'UrbanRoad': {'max_points': 7},
                }},
            ],
        },
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tagName) { this.tagName = tagName; this.namespaceURI = 'svg'; this.attributes = {}; this.children = []; this.style = {}; this.textContent = ''; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  append(...nodes) { this.children.push(...nodes); this.textContent += nodes.map(node => node.textContent || '').join(''); }
}
const document = {createElementNS: (_namespace, tag) => new Element(tag)};
const helpers = `
function svgElement(svg, name, attributes = {}) {
  const node = document.createElementNS(svg.namespaceURI, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}
function setChartTooltip(node, message) { node.setAttribute('data-chart-tooltip', String(message)); }
function formattedChartPoints(value) { return Number(value).toLocaleString(undefined, {maximumFractionDigits: 3}); }
function bestNetworkTotals(table) { return {allocation: table.allocation || {Voice: 0, Data: 0}}; }
`;
const context = {document, console, payload};
vm.createContext(context);
vm.runInContext(helpers + Object.values(payload.snippets).join('\n') + `
const selected = {context: {environment: 'Combined'}, rows: [
  {category: 'Calls', max_points: 30}, {category: 'Connectivity', max_points: 60},
  {category: 'Calls', max_points: 35}, {category: 'Ignored', max_points: 999, row_type: 'category'},
]};
const environments = maximumAllocationEnvironments(selected, [], payload.configuration);
const categories = maximumAllocationCategories(selected, environments, payload.configuration);
const chart = makeMaximumAllocationDonut(environments, categories);
const tinyChart = makeMaximumAllocationDonut([
  {name: 'Tiny', Voice: 1.4, Data: 0, color: '#176E77'},
  {name: 'Large', Voice: 98.6, Data: 0, color: '#E6A81D'},
], [
  {label: 'Tiny KPI', value: 1.4, color: '#C55A11'},
  {label: 'Large KPI', value: 98.6, color: '#7030A5'},
]);
const singleEnvironmentChart = makeMaximumAllocationDonut([
  {name: 'DriveCity', Voice: 100, Data: 0, color: '#176E77'},
]);
const fallback = maximumAllocationCategories(selected, [], {});
globalThis.result = {
  environments: environments.map(item => [item.name, item.Voice, item.Data]),
  categories: categories.map(item => [item.label, item.value]),
  fallback: fallback.map(item => [item.label, item.value]),
  viewBox: chart.attributes.viewBox,
  segmentTooltips: chart.children.filter(item => item.attributes['data-allocation-segment']).map(item => item.attributes['data-chart-tooltip']),
  segmentGeometry: chart.children.filter(item => item.attributes['data-allocation-segment'])
    .map(item => [item.attributes['data-allocation-segment'], item.attributes['data-allocation-radius'], item.attributes['data-allocation-center'], item.attributes.d]),
  percentageLabels: chart.children.filter(item => item.attributes['data-allocation-percentage']).map(item => ({
    value: item.attributes['data-allocation-percentage'], style: item.attributes.style,
    tooltip: item.attributes['data-chart-tooltip'],
  })),
  tinyPercentageLabels: tinyChart.children.filter(item => item.attributes['data-allocation-percentage'])
    .map(item => item.attributes['data-allocation-percentage']),
  singleEnvironmentPercentages: singleEnvironmentChart.children
    .filter(item => item.attributes['data-allocation-percentage']).map(item => item.attributes['data-allocation-percentage']),
      legend: chart.children.filter(item => item.tagName === 'text' && ['18', '74', '94'].includes(item.attributes.x)).map(item => ({
        text: item.children.length ? item.children.map(child => child.textContent).join('') : item.textContent,
        x: item.attributes.x, y: item.attributes.y, style: item.attributes.style,
        amountColor: item.children[1]?.attributes.fill,
      })),
  icons: chart.children.filter(item => item.tagName === 'path' && item.attributes.transform).map(item => item.attributes.d),
  representativeIcons: [allocationIconPath('Classic Calls'), allocationIconPath('WhatsApp Calls')],
};`, context);
process.stdout.write(JSON.stringify(context.result));
"""
    result = _run_node_json(program, payload)

    assert result['environments'] == [['DriveCity', 50, 50], ['UrbanRoad', 15, 10]]
    assert result['categories'] == [['Calls', 65], ['Connectivity', 60]]
    assert result['fallback'] == [['Calls', 65], ['Connectivity', 60]]
    assert result['viewBox'].startswith('0 0 420 ')
    assert [segment[:3] for segment in result['segmentGeometry']] == [
        ['Environments', '140', '210,166'], ['Environments', '140', '210,166'],
        ['KPI categories', '106', '210,166'], ['KPI categories', '106', '210,166'],
    ]
    assert all(segment[3].startswith('M ') and ' A ' in segment[3] and ' Z' in segment[3]
               for segment in result['segmentGeometry'])
    assert all('stroke-dasharray' not in segment[3] for segment in result['segmentGeometry'])
    assert [tooltip.splitlines()[0] for tooltip in result['segmentTooltips']] == [
        'Environments: DriveCity', 'Environments: UrbanRoad',
        'KPI categories: Calls', 'KPI categories: Connectivity',
    ]
    assert 'Maximum points: 100' in result['segmentTooltips'][0]
    assert [item['value'] for item in result['percentageLabels']] == ['80.0%', '20.0%', '52.0%', '48.0%']
    assert all('font-size:11px' in item['style'] and 'font-weight:700' in item['style'] for item in result['percentageLabels'])
    assert all(' of configured maximum' in item['tooltip'] for item in result['percentageLabels'])
    assert '1.4%' not in result['tinyPercentageLabels']
    assert {'98.6%'} <= set(result['tinyPercentageLabels'])
    assert result['singleEnvironmentPercentages'] == ['100.0%', '100.0%']
    assert [item['text'] for item in result['legend']] == [
        'Total Points: 125 pts (100.0%)', 'Points per Environment:', 'Drive - City: 100 pts (80.0%)',
        'UrbanRoad: 25 pts (20.0%)', 'Points per KPI Category:', 'Calls: 65 pts (52.0%)',
        'Connectivity: 60 pts (48.0%)',
    ]
    assert result['legend'][0]['x'] == '74'
    assert [item['x'] for item in result['legend'][1:]] == ['18', '94', '94', '18', '94', '94']
    assert 'font-weight:700' in result['legend'][1]['style']
    assert 'font-weight:400' in result['legend'][2]['style']
    assert all(float(re.search(r'font-size:([\d.]+)px', item['style']).group(1)) <= 14 for item in result['legend'] if item['x'] != '18')
    assert all(item['amountColor'] == '#8A3D0A' for item in result['legend'] if item['x'] in {'74', '94'})
    assert len(set(result['representativeIcons'])) == 2


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

    assert '.scoring-comparison-table th.scoring-operator-header { background: var(--operator-accent, #607d8b) !important; color: var(--operator-text, #ffffff) !important; }' in template
    assert '.scoring-comparison-table th.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-hierarchy-header.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-gap-header { background: #ffff00 !important; color: #242424 !important; }' in template
    assert "function markReferenceHeader(header) {\n    header.classList.add('scoring-reference-header');" in script
    assert 'header.title = `${label} is the reference operator`;' in script


def test_operator_color_and_reference_markers_stay_on_operator_headers():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert '.scoring-comparison-table th.scoring-operator-header { background: var(--operator-accent, #607d8b) !important; color: var(--operator-text, #ffffff) !important; }' in template
    assert 'border-bottom: 3px solid var(--operator-accent' not in template
    assert '.scoring-comparison-table th.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-hierarchy-header.scoring-reference-header' not in template
    hierarchy_header_rule = re.search(
        r'\.scoring-comparison-table th\.scoring-hierarchy-header\s*\{([^}]*)\}', template,
    )
    assert hierarchy_header_rule and 'border-' not in hierarchy_header_rule.group(1)
    assert "String(entry.level).toLocaleLowerCase() === 'operator'" in script


def test_export_links_have_distinct_high_contrast_colors():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    for marker in ('data-config-shortcut="kpi"', 'data-config-shortcut="hierarchy"',
                   'data-config-shortcut="gap"', 'data-export-scoring', 'data-export-gap', 'data-export-ppt'):
        assert re.search(rf'\.scoring-results-tools a\[{re.escape(marker)}\] \{{ background: linear-gradient\(', template)
    assert '.scoring-results-tools a[data-config-shortcut] { color: #fff;' in template


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
        'appendMatrixTable', 'renderScoringViews', 'summaryOperatorColors', 'appendOperatorRankingLegend',
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
    {row_type: 'category', category: 'Voice', kpi: 'Voice', weight_percent: 100, max_points: 1000, values: {EE: {points: 850, complete: true}, O2: {points: 770, complete: true}}},
  ],
  expanded_rows: [
    {row_type: 'kpi', category: 'Voice', kpi: 'Call Setup', kpi_code: 'call_setup', kpi_type: 'Reliable', weight_percent: 50, max_points: 500,
      values: {EE: {value: 12.345, points: 400, complete: true}, O2: {value: 67.891, points: 350, complete: true}}},
    {row_type: 'kpi', category: 'Voice', kpi: 'Drop Rate', kpi_code: 'drop_rate', kpi_type: 'Diff', weight_percent: 50, max_points: 500,
      values: {EE: {value: 1.2, points: 450, complete: true}, O2: {value: 2.3, points: 420, complete: true}}},
  ],
  category_total: {weight_percent: 100, max_points: 1000, values: {EE: {points: 850, complete: true}, O2: {points: 770, complete: false}}},
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
    ranks: nodes.filter(node => node.dataset.operatorRank).map(node => [node.dataset.operatorRank, node.style.backgroundColor]),
    rankingLegend: nodes.filter(node => node.className.includes('scoring-operator-ranking-legend')).length,
    rawCells: nodes.filter(node => node.tagName === 'td' && node.dataset.column === 'kpi-value').map(node => node.textContent),
  };
}
process.stdout.write(JSON.stringify(sections.map(summarize)));
"""
    results = _run_node_json(program, payload)

    assert [section['heading'] for section in results] == [
        'Scoring Tables — Summary', 'Scoring Tables — Breakdown',
    ]
    assert results[0]['valueGroups'] == 0
    assert results[0]['valueHeaders'] == 0
    assert results[0]['rawCells'] == []
    assert results[0]['ranks'] == [['best', '#C6EFCE'], ['worst', '#FFC7CE']] * 2
    assert results[0]['rankingLegend'] == 1
    assert results[1]['ranks'] == []
    assert results[1]['rankingLegend'] == 0
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
        _function_source(script, 'selectedContextFilters'),
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
const context = {job: payload.job,
  catalogueKeyByLevel: new Map([['Vendor', 'vendors']]),
  datasetCatalogues: new Map([['1', {vendors: ['Nokia']}], ['2', {vendors: ['Ericsson']}]]),
  contextFilterDefinitions: [{key: 'Vendor'}],
  contextFilterSelects: new Map([['Vendor', {options: [{value: 'Nokia'}, {value: 'Ericsson'}], selectedOptions: [{value: 'Nokia'}, {value: 'Ericsson'}]}]])};
vm.createContext(context);
vm.runInContext(payload.snippets.join('\n') + `
  globalThis.completeVendors = savedJobFilterValues({dataset_ids: [1, 2], context_filters: {Vendor: ['Ericsson', 'Nokia']}}, 'Vendor');
  globalThis.subsetVendors = savedJobFilterValues({dataset_ids: [1, 2], context_filters: {Vendor: ['Nokia']}}, 'Vendor');
  globalThis.submittedFilters = selectedContextFilters();
  globalThis.title = jobCardTitle(job);
  globalThis.cdrSummary = jobCdrSummary(job);
  globalThis.metadataCdrSummary = jobCdrSummary({source_metadata: {data: {name: 'data.csv'}, voice: {name: 'voice.csv'}}});
  globalThis.partialVendors = savedJobFilterValues({context_filters: {Vendor: ['Nokia']}, resolved_context_filters: {Vendor: ['Nokia', 'Ericsson']}}, 'Vendor');
  globalThis.legacyVendors = savedJobFilterValues({resolved_context_filters: {Vendor: ['Ericsson']}}, 'Vendor');
  globalThis.fallbackTitle = jobCardTitle({created_at: 'not-a-date', nr_mode: 'SA', dataset_ids: [1], source_metadata: [{campaigns: ['UK_Q3_2026']}]});`, context);
process.stdout.write(JSON.stringify({title: context.title, cdrSummary: context.cdrSummary,
  metadataCdrSummary: context.metadataCdrSummary, fallbackTitle: context.fallbackTitle,
  partialVendors: context.partialVendors, legacyVendors: context.legacyVendors,
  completeVendors: context.completeVendors, subsetVendors: context.subsetVendors, submittedFilters: context.submittedFilters}));
"""
    result = _run_node_json(program, payload)

    assert result['title'].split(' ● ')[1:] == [
        'NSA', 'All Operators', 'All Vendors', 'All Regions', 'All Cities', 'UK_Q2_2026',
    ]
    assert result['cdrSummary'] == 'data.csv, voice.csv'
    assert result['metadataCdrSummary'] == 'data.csv, voice.csv'
    assert result['completeVendors'] == []
    assert result['subsetVendors'] == ['Nokia']
    assert result['submittedFilters'] == {'Vendor': []}
    assert result['partialVendors'] == ['Nokia']
    assert result['legacyVendors'] == ['Ericsson']
    assert result['fallbackTitle'].split(' ● ')[1:] == [
        'SA', 'All Operators', 'All Vendors', 'All Regions', 'All Cities', 'UK_Q3_2026',
    ]


def test_kpi_value_cells_are_blank_for_category_subtotals_in_both_table_modes():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert script.count("cell.textContent = isCategoryRow ? '' : formatRawKpiValue(rawValue);") == 2
    assert script.count("const isCategoryRow = item?.row_type === 'category';") == 2


def test_allocation_donut_global_environment_rings_and_single_environment_radius():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    functions = '\n'.join(_function_source(script, name) for name in (
        'maximumAllocationEnvironments', 'allocationEnvironmentLabel', 'allocationCategoryLabel', 'allocationIconPath',
        'allocationSectorPath', 'wrappedSvgLabelLines', 'safeHexColor', 'readableTextColor', 'makeMaximumAllocationDonut',
    ))
    program = functions + """
const document = {createElementNS: () => ({attributes: {}, children: [],
  setAttribute(name, value) {this.attributes[name] = value;},
  append(...children) {this.children.push(...children);}})};
const svgElement = (svg, tag, attributes) => ({tag, attributes, children: [], textContent: '',
  setAttribute(name, value) {this.attributes[name] = value;},
  append(...children) {this.children.push(...children);}});
const setChartTooltip = () => {};
const formattedChartPoints = number => Number(number).toFixed(2);
const config = {scope: {environments: {DriveCity: {total_points: 650}, 'Drive Connecting Roads': {total_points: 350}}},
 metrics: [
 {source_kind: 'voice', contexts: {DriveCity: {max_points: 227.5}, 'Drive Connecting Roads': {max_points: 122.5}}},
 {source_kind: 'data', contexts: {DriveCity: {max_points: 422.5}, 'Drive Connecting Roads': {max_points: 227.5}}}]};
const all = maximumAllocationEnvironments({context: {environment: 'Combined'}}, [], config);
const single = maximumAllocationEnvironments({context: {environment: 'Drive Connecting Roads'}}, [], config);
const globalSvg = makeMaximumAllocationDonut(all);
const singleSvg = makeMaximumAllocationDonut(single);
const segments = svg => svg.children.filter(item => item.attributes?.['data-allocation-segment']).map(item => item.attributes);
const icons = svg => svg.children.filter(item => item.tag === 'path' && item.attributes?.transform);
const textContent = svg => svg.children.filter(item => item.tag === 'text').map(item => item.children?.length
  ? item.children.map(child => child.textContent || '').join('') : item.textContent || '').join('|');
console.log(JSON.stringify({all, single, global: segments(globalSvg), one: segments(singleSvg),
 icons: icons(globalSvg).length,
 globalText: textContent(globalSvg),
 singleText: textContent(singleSvg)}));
"""
    result = _run_node_json(program, {})
    assert len(result['global']) == 4  # Environment allocation plus one global Voice/Data ring.
    assert [item['fill'] for item in result['global'][:2]] == ['#176E77', '#E6A81D']
    assert [item['fill'] for item in result['global'][2:]] == ['#4472C4', '#7030A0']
    assert len(result['one']) == 3
    assert [item['fill'] for item in result['one']] == ['#E6A81D', '#4472C4', '#7030A0']
    assert result['one'][0]['data-allocation-radius'] == result['global'][0]['data-allocation-radius'] == 140
    assert result['one'][0]['data-allocation-center'] == '210,166'
    assert result['one'][0]['d'].count(' A ') == 4
    assert [item['data-allocation-radius'] for item in result['one'][1:]] == [106, 106]
    assert result['global'][0]['data-allocation-radius'] > result['global'][2]['data-allocation-radius']
    assert len(result['single']) == 1 and result['single'][0]['color'] == '#E6A81D'
    assert result['icons'] == 5
    assert '1,000.00' in result['globalText']
    assert '350.00' in result['singleText']
    assert 'Drive - Connecting Roads:' in result['singleText']
    assert 'Global:' not in result['singleText']


def test_summary_operator_highlights_compare_only_matching_contexts_and_include_ties():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    names = ('firstValue', 'operatorValue', 'summaryOperatorColors')
    payload = {'snippets': {name: _function_source(script, name) for name in names}}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const context = {};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + `
  const columns = ['A', 'B', 'C', 'D', 'E', 'F'].map((id, index) => ({
    id, path: [{level: 'Operator', value: id}, {level: 'Region', value: index < 4 ? 'North' : 'South'}],
  }));
  const values = {A: {points: 10}, B: {points: 10}, C: {points: 2}, D: {points: 2},
    E: {points: 100}, F: {points: 50, complete: false}};
  globalThis.ranked = [...summaryOperatorColors(values, columns)];
  globalThis.equal = [...summaryOperatorColors({A: {points: 2}, B: {points: 2}}, [{id: 'A'}, {id: 'B'}])];
  globalThis.missing = [...summaryOperatorColors({A: {points: 0}, B: {points: null}, C: {points: 'bad'}},
    [{id: 'A'}, {id: 'B'}, {id: 'C'}])];
`, context);
process.stdout.write(JSON.stringify({ranked: context.ranked, equal: context.equal, missing: context.missing}));
"""
    result = _run_node_json(program, payload)
    assert dict(result['ranked']) == {
        'A': '#C6EFCE', 'B': '#C6EFCE', 'C': '#FFC7CE', 'D': '#FFC7CE',
        'E': '#C6EFCE', 'F': '#FFC7CE',
    }
    assert result['equal'] == []
    assert result['missing'] == []
    assert script.count('appendOperatorRankingLegend(summarySection);') == 2
    assert script.count('appendThresholdLegend(expandedSection,') == 2
    assert script.count('isSummary ? (summaryColors.get(') == 4


def test_scoring_category_cells_span_kpis_and_subtotal_in_both_renderers():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    names = (
        'firstValue', 'operatorValue', 'operatorPresentation', 'safeHexColor', 'readableTextColor',
        'formatMatrixNumber', 'createKpiTypeCell', 'showGapValues', 'selectedGapLayout',
        'appendScoreGapCells', 'hierarchyColumnEntries', 'hierarchyColumnIsReference',
        'appendMatrixTable', 'appendHierarchyMatrixTable', 'summaryOperatorColors',
    )
    payload = {'snippets': {name: _function_source(script, name) for name in names}}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.style = {};
    this.className = ''; this.classList = {add: value => { this.className += ` ${value}`; }}; }
  append(...nodes) { this.children.push(...nodes); }
}
const context = {
  document: {createElement: tag => new Element(tag)}, showKpiValuesToggle: {checked: false},
  showGapValuesToggle: {checked: false}, gapLayoutSelect: {value: 'end'},
  observeScoringValueCells: () => {},
  appendHierarchyHeaders: (thead, _data, _columns, definitions) => {
    const row = new Element('tr');
    for (const [label, column] of definitions) {
      const th = new Element('th'); th.textContent = label; th.dataset.column = column; row.append(th);
    }
    thead.append(row);
  },
};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + `
  globalThis.renderers = [appendMatrixTable, appendHierarchyMatrixTable];`, context);
const fixture = {_display_mode: 'expanded', operators: [], rows: [
  {category: 'Voice', kpi: 'Call Setup'}, {category: 'Voice', kpi: 'Drop Rate'},
  {category: 'Voice', kpi: 'Voice total', row_type: 'category'},
  {category: 'Data', kpi: 'Throughput'}, {category: 'Data', kpi: 'Data total', row_type: 'category'},
]};
function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }
const result = context.renderers.map(render => {
  const pane = new Element('div'); render(pane, fixture); const nodes = descendants(pane);
  return {
    categories: nodes.filter(node => node.tagName === 'td' && node.dataset.column === 'category')
      .map(node => [node.textContent, node.rowSpan]),
    headers: nodes.filter(node => node.tagName === 'th' && ['category', 'kpi'].includes(node.dataset.column))
      .map(node => [node.textContent, node.dataset.column]),
    subtotals: nodes.filter(node => node.className.includes('scoring-category-subtotal'))
      .map(node => node.children.filter(child => child.dataset.column === 'kpi').map(child => child.textContent)),
  };
});
process.stdout.write(JSON.stringify(result));
"""
    for result in _run_node_json(program, payload):
        assert result['categories'] == [['Voice', 3], ['Data', 2]]
        assert result['headers'] == [['CATEGORY', 'category'], ['KPI', 'kpi']]
        assert result['subtotals'] == [['Voice total'], ['Data total']]
