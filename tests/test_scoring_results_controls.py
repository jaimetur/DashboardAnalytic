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
    marker = f'  function {name}('
    if marker not in script:
        marker = f'  async function {name}('
    start = script.index(marker)
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


def test_results_environment_stays_visible_while_loading_and_exports_selected_scope():
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
    assert 'defaults to the first complete environment when all environments are incomplete' in template


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
    assert 'const scale = scoringChartScale(maxAllocation, maxActual);' in script


def test_best_network_charts_start_scoring_charts_and_legacy_tab_migrates():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert 'data-result-tab="best-network"' not in template
    assert "const resultTabNames = new Set(['scoring', 'gap', 'charts']);" in script
    assert "stored.result_tab === 'best-network' ? 'charts'" in script
    renderer = _function_source(script, 'renderBestNetworkChart')
    allocation_renderer = _function_source(script, 'renderCategoryAllocation')
    assert allocation_renderer.index("makeExpandableChartCard('Maximum score per environment & category'") >= 0
    assert "pane.insertBefore(layout, card)" in allocation_renderer
    assert renderer.index("makeExpandableChartCard('Best Network Scoring per Service'") < renderer.index(
        "makeExpandableChartCard('Maximum score per environment & service'"
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


def test_incomplete_web_values_render_na_star_in_red_bold():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    payload = {
        'snippets': {
            'firstValue': _function_source(script, 'firstValue'),
            'formatMatrixNumber': _function_source(script, 'formatMatrixNumber'),
            'formatScoreCell': _function_source(script, 'formatScoreCell'),
            'formatRawKpiValue': _function_source(script, 'formatRawKpiValue'),
            'styleIncompleteValue': _function_source(script, 'styleIncompleteValue'),
        },
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const context = {};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n') + `
const cases = [
  formatMatrixNumber(null),
  formatScoreCell({points: 12.345, complete: false}).text,
  formatRawKpiValue(null),
];
globalThis.results = cases.map(text => {
  const element = {textContent: text, style: {}};
  styleIncompleteValue(element);
  return {text, color: element.style.color, fill: element.style.fill, fontWeight: element.style.fontWeight};
});`, context);
process.stdout.write(JSON.stringify(context.results));
"""
    result = _run_node_json(program, payload)
    assert result == [
        {'text': 'N/A*', 'color': '#c62828', 'fill': '#c62828', 'fontWeight': '700'},
        {'text': '12.35*', 'color': '#c62828', 'fill': '#c62828', 'fontWeight': '700'},
        {'text': 'N/A*', 'color': '#c62828', 'fill': '#c62828', 'fontWeight': '700'},
    ]


def test_results_controls_are_grouped_with_icons_and_unique_environment_heading():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    from lxml import html
    tree = html.fromstring(template)
    shortcut_navs = tree.xpath('//nav[@aria-label="Scoring configuration sections"]')
    assert len(shortcut_navs) == 2
    for nav in shortcut_navs:
        kpi_shortcut = nav.xpath('./a[@data-config-shortcut="kpi"]')[0]
        assert kpi_shortcut.get('href') == '/workspace-config#scoring-methodology-environments'
        assert kpi_shortcut.xpath('./span')[0].text == 'Methodology Environments'
        assert kpi_shortcut.xpath('./svg/path/@d') == [
            'M2 17h16M3 17V7h5v10M5 10h1M5 13h1M12 3l-2 14M16 3l2 14M14 4v2m0 3v2m0 3v2',
        ]
        assert nav.xpath('./a[@data-config-shortcut="hierarchy"][@href="/workspace-config#scoring-aggregation-hierarchy"]')
        gap_shortcut = nav.xpath('./a[@data-config-shortcut="gap"]')[0]
        assert gap_shortcut.get('href') == '/workspace-config#scoring-gap-priority'
        assert gap_shortcut.xpath('./span')[0].text == 'KPI Priorities'
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
            'hierarchyDisplayValue': _function_source(script, 'hierarchyDisplayValue'),
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
        'formatChartNumber', 'maximumAllocationEnvironments', 'maximumAllocationCategories',
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
const walkConfiguration = {
  scope: {environments: {
    'Walk City': {total_points: 500}, 'Walk Connection Road': {total_points: 300}, 'Zero Walk': {total_points: 0},
  }},
  metrics: [
    {source_kind: 'voice', contexts: {
      'Walk City': {max_points: 300}, 'Walk Connection Road': {max_points: 200}, 'Zero Walk': {max_points: 0},
    }},
    {source_kind: 'data', contexts: {
      'Walk City': {max_points: 200}, 'Walk Connection Road': {max_points: 100}, 'Zero Walk': {max_points: 0},
    }},
  ],
};
const walkEnvironments = maximumAllocationEnvironments({context: {environment: 'Combined'}}, [], walkConfiguration);
const walkSingleEnvironment = maximumAllocationEnvironments({context: {environment: 'Walk City'}}, [], walkConfiguration);
const walkChart = makeMaximumAllocationDonut(walkEnvironments);
const walkSingleChart = makeMaximumAllocationDonut(walkSingleEnvironment);
const environmentIcons = svg => svg.children.filter(item => item.attributes['data-allocation-environment-icon'])
  .map(item => ({...item.attributes, tooltip: item.attributes['data-chart-tooltip']}));
const legendYValues = svg => svg.children.filter(item => item.tagName === 'text'
  && ['74', '94'].includes(item.attributes.x)).map(item => Number(item.attributes.y));
const walkIcons = environmentIcons(walkChart);
const walkSingleIcons = environmentIcons(walkSingleChart);
const unpackIcon = icon => {
  const [translation, scaleText] = icon.transform.split(' scale(');
  const [x, y] = translation.slice('translate('.length, -1).split(' ');
  const scale = Number(scaleText.slice(0, -1));
  const iconSize = 24 * scale;
  const centerX = Number(x) + iconSize / 2, centerY = Number(y) + iconSize / 2;
  return {label: icon['data-allocation-environment-icon'], path: icon.d, scale: Number(scale),
    centerX, centerY, iconSize, left: centerX - iconSize / 2, top: centerY - iconSize / 2,
    right: centerX + iconSize / 2, bottom: centerY + iconSize / 2,
    tooltip: icon.tooltip};
};
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
  walkNames: walkEnvironments.map(item => item.name),
  walkIcons: walkIcons.map(unpackIcon), walkSingleIcons: walkSingleIcons.map(unpackIcon),
  walkViewBox: walkChart.attributes.viewBox, walkSingleViewBox: walkSingleChart.attributes.viewBox,
  walkLegendY: Math.min(...legendYValues(walkChart)), walkSingleLegendY: Math.min(...legendYValues(walkSingleChart)),
  walkLegendIconCount: walkChart.children.filter(item => item.tagName === 'path' && item.attributes.transform
    && !item.attributes['data-allocation-environment-icon']).length,
  expectedWalkPaths: [allocationIconPath('Walk City'), allocationIconPath('Walk Connection Road')],
};`, context);
process.stdout.write(JSON.stringify(context.result));
"""
    result = _run_node_json(program, payload)

    assert result['environments'] == [['DriveCity', 50, 50], ['UrbanRoad', 15, 10]]
    assert result['categories'] == [['Calls', 65], ['Connectivity', 60]]
    assert result['fallback'] == [['Calls', 65], ['Connectivity', 60]]
    assert result['viewBox'].startswith('0 0 460 ')
    assert [segment[:3] for segment in result['segmentGeometry']] == [
        ['Environments', '134.16', '230,230'], ['Environments', '134.16', '230,230'],
        ['KPI categories', '89.54079999999999', '230,230'], ['KPI categories', '89.54079999999999', '230,230'],
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
    assert all(11 <= float(re.search(r'font-size:([\d.]+)px', item['style']).group(1)) <= 14
               and 'font-weight:700' in item['style'] for item in result['percentageLabels'])
    assert all(' of configured maximum' in item['tooltip'] for item in result['percentageLabels'])
    assert '1.4%' not in result['tinyPercentageLabels']
    assert {'98.6%'} <= set(result['tinyPercentageLabels'])
    assert result['singleEnvironmentPercentages'] == ['100.0%', '100.0%']
    assert result['walkNames'] == ['Walk City', 'Walk Connection Road']
    assert [icon['label'] for icon in result['walkIcons']] == result['walkNames']
    assert [icon['path'] for icon in result['walkIcons']] == result['expectedWalkPaths']
    assert len(result['walkSingleIcons']) == 1
    assert result['walkSingleIcons'][0]['label'] == 'Walk City'
    assert result['walkSingleIcons'][0]['path'] == result['expectedWalkPaths'][0]
    assert all(icon['iconSize'] == 42 and icon['scale'] == pytest.approx(42 / 24)
               for icon in [*result['walkIcons'], *result['walkSingleIcons']])
    for view_box, icons, legend_y in (
        (result['walkViewBox'], result['walkIcons'], result['walkLegendY']),
        (result['walkSingleViewBox'], result['walkSingleIcons'], result['walkSingleLegendY']),
    ):
        width, height = view_box.split()[2:]
        width, height = int(width), int(height)
        assert all(0 <= icon['left'] < icon['right'] <= width
                   and 0 <= icon['top'] < icon['bottom'] < height for icon in icons)
        assert max(icon['bottom'] for icon in icons) < legend_y
        assert all(legend_y >= 480 for _icon in icons)
        assert all(((icon['centerX'] - 230) ** 2 + (icon['centerY'] - 230) ** 2) ** .5
                   == pytest.approx(189)
                   for icon in icons)
    assert result['walkLegendIconCount'] > len(result['walkIcons'])
    assert all('Environment:' in icon['tooltip'] and 'Maximum points:' in icon['tooltip']
               for icon in result['walkIcons'])
    assert 'Walk Connection Road' in result['walkIcons'][1]['tooltip']
    assert result['walkSingleLegendY'] >= 480
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
        'scoringChartScale', 'configuredChartMaximum',
        'wrappedSvgLabelLines', 'setChartTooltip', 'formattedChartPoints',
        'chartEnvironmentName', 'categoryLegendGray', 'chartCategoryLegend', 'chartLegendTextWidth',
        'chartLegendRows', 'categoryLegendTextLines', 'categoryLegendTextColor',
        'formatChartNumber', 'stackedSegmentLabelSize', 'bestNetworkHorizontalGeometry',
        'fitBestNetworkChartWidth', 'makeSvgChart', 'makeBestNetworkBars', 'lightenHexColor',
        'hierarchyColumnOperator', 'hierarchyColumnIsReference', 'chartOperatorLegend',
        'makeExpandableChartCard',
        'renderCharts', 'renderHierarchyCharts', 'svgElement', 'hierarchyChartColor',
        'hierarchyDisplayValue', 'hierarchyPathEntry', 'hierarchyPrefixKey', 'appendHierarchyAxisBands',
        'hierarchyPathValueLabel', 'hierarchyPathFullLabel', 'chartFitWidth', 'styleIncompleteValue',
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
    this.textContent = '';
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
  globalThis.renderers = {renderCharts, renderHierarchyCharts, makeSvgChart, makeBestNetworkBars,
    chartLegendRows, bestNetworkHorizontalGeometry};`, context);
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
function compareBestNetwork(count) {
  const names = Array.from({length: count}, (_, index) => `Operator ${index + 1}`);
  const styles = Object.fromEntries(names.map((name, index) => [name, {
    label: name, color: palette[index % palette.length], position: index,
  }]));
  const source = {...table, operators: names, operator_styles: styles, rows: [{max_points: 90}]};
  const rows = names.flatMap(operator => [
    {category: operator, series: 'Data', value: 99.5, complete: true},
    {category: operator, series: 'Voice', value: .5, complete: true},
  ]);
  const categorySvg = context.renderers.makeSvgChart('Best Network Scoring per Category', rows, source, {
    stacked: true, categoryOrder: names, seriesOrder: ['Data', 'Voice'],
    seriesStyles: {Data: {label: 'Data', color: '#555555'}, Voice: {label: 'Voice', color: '#c5c5c5'}},
    legendEntries: names.map((name, index) => ({label: name, color: palette[index % palette.length]})),
    categoryLegendEntries: [{label: 'Data', color: '#555555'}, {label: 'Voice', color: '#c5c5c5'}],
    segmentColor: (_operator, kind) => kind === 'Data' ? '#555555' : '#c5c5c5',
    operatorForCategory: operator => operator,
  });
  const serviceData = {
    operators: names, allocation: {Data: 90, Voice: 0},
    totals: Object.fromEntries(names.map(name => [name, {
      Data: {value: 99.5, complete: true}, Voice: {value: .5, complete: true},
    }])),
  };
  const serviceSvg = context.renderers.makeBestNetworkBars(source, serviceData);
  const geometry = context.renderers.bestNetworkHorizontalGeometry(count);
  const legendRows = context.renderers.chartLegendRows(names.map((name, index) => ({
    label: name, color: palette[index % palette.length],
  })), geometry.width, geometry.left, geometry.right, palette[0]);
  const expectedLegendStarts = legendRows.map(row => geometry.left
    + Math.max(0, (geometry.width - geometry.left - geometry.right - (row.width - 22)) / 2));
  const measure = svg => {
    const rects = svg.children.filter(node => node.tagName === 'rect'
      && (node.attributes['data-chart-tooltip'] || '').includes('Weighted points:'));
    const labels = svg.children.filter(node => node.className === 'scoring-best-network-segment');
    const totals = svg.children.filter(node => node.className.includes('scoring-chart-value'));
    const ticks = svg.children.filter(node => node.className === 'scoring-chart-tick').map(node => node.textContent);
    const legendLabels = svg.children.filter(node => node.className === 'scoring-chart-legend')
      .map(node => ({text: node.textContent, x: Number(node.attributes.x), y: Number(node.attributes.y)}));
    const sharedText = svg.children.filter(node => [
      'scoring-chart-axis-label', 'scoring-chart-tick', 'scoring-chart-operator-legend-title',
      'scoring-chart-legend', 'scoring-chart-category-legend-title', 'scoring-chart-category-legend-label',
    ].includes(node.className)).map(node => node.className).sort();
    return {
      viewBoxWidth: svg.viewBox.baseVal.width, widthStyle: svg.style.width,
      viewBoxHeight: svg.viewBox.baseVal.height, ticks,
      minWidthStyle: svg.style.minWidth,
      positions: rects.filter((_node, index) => index % 2 === 0).map(node => Number(node.attributes.x)),
      barWidths: [...new Set(rects.map(node => Number(node.attributes.width)))],
      labelTexts: labels.map(node => node.textContent),
      labelSizes: labels.map(node => node.style.fontSize),
      totals: totals.map(node => node.textContent), totalY: totals.map(node => Number(node.attributes.y)),
      barTop: Math.min(...rects.map(node => Number(node.attributes.y))), legendLabels,
      hasOperatorsHeading: svg.children.some(node => node.textContent === 'Operators'), sharedText,
    };
  };
  return {count, expectedLegendStarts, category: measure(categorySvg), service: measure(serviceSvg)};
}
const sharedGeometry = [5, 10, 14].map(compareBestNetwork);
process.stdout.write(JSON.stringify({
  simple: inspect(simplePane), hierarchy: inspect(hierarchyPane),
  wideSimple: inspect(wideSimplePane), wideHierarchy: inspect(wideHierarchyPane), palette,
  sharedGeometry,
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
        if charts is result['wideHierarchy']:
            assert bottom['viewBoxWidth'] >= 7 * 10 * 70
            assert float(bottom['widthStyle'].removesuffix('%')) > 100
        else:
            assert bottom['viewBoxWidth'] <= 1000
            assert bottom['widthStyle'] == '100%'
        assert bottom['minWidthStyle'] == '0'

    for comparison in result['sharedGeometry']:
        assert comparison['count'] in {5, 10, 14}
        category, service = comparison['category'], comparison['service']
        assert category['viewBoxWidth'] == service['viewBoxWidth']
        assert category['widthStyle'] == service['widthStyle']
        assert category['minWidthStyle'] == service['minWidthStyle'] == '0'
        assert category['positions'] == service['positions']
        assert len(category['barWidths']) == len(service['barWidths']) == 1
        assert category['barWidths'] == service['barWidths']
        assert category['labelTexts'] == service['labelTexts']
        assert len(category['labelTexts']) == comparison['count']
        assert all(text == '99.5' for text in category['labelTexts'])
        assert category['labelSizes'] == service['labelSizes']
        assert all(float(size.removesuffix('px')) <= 22 for size in category['labelSizes'])
        assert category['totals'] == service['totals']
        assert all(value.endswith('.0') for value in category['totals'])
        assert category['ticks'] == service['ticks']
        assert 4 <= len(category['ticks']) <= 7
        assert all(value.isdigit() for value in category['ticks'])
        tick_steps = [int(left) - int(right) for left, right in zip(category['ticks'], category['ticks'][1:])]
        assert len(set(tick_steps)) == 1
        assert int(category['ticks'][0]) >= 100
        for view in (category, service):
            assert all(0 < total_y < view['barTop'] for total_y in view['totalY'])
            assert view['barTop'] < view['viewBoxHeight']
        assert [(item['text'], item['x']) for item in category['legendLabels']] == [
            (item['text'], item['x']) for item in service['legendLabels']
        ]
        assert not service['hasOperatorsHeading']
        for view in (category, service):
            legend_rows = {}
            for item in view['legendLabels']:
                legend_rows.setdefault(item['y'], []).append(item)
            row_starts = [entries[0]['x'] - 21 for entries in legend_rows.values()]
            assert row_starts == pytest.approx(comparison['expectedLegendStarts'])
        if comparison['count'] <= 10:
            assert category['widthStyle'] == service['widthStyle'] == '100%'
        else:
            assert float(category['widthStyle'].removesuffix('%')) > 100
        for shared_class in ('scoring-chart-axis-label', 'scoring-chart-tick', 'scoring-chart-legend',
                             'scoring-chart-category-legend-title', 'scoring-chart-category-legend-label'):
            assert shared_class in category['sharedText']
            assert shared_class in service['sharedText']


def test_reference_header_uses_operator_mapping_accent_without_yellow_marker():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert '.scoring-comparison-table th.scoring-operator-header { background: color-mix(in srgb, var(--operator-accent, #607d8b) 20%, #fff) !important; color: #263f4b !important; box-shadow: inset 0 3px var(--operator-accent, #607d8b); }' in template
    assert '.scoring-comparison-table th.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-hierarchy-header.scoring-reference-header' not in template
    assert '.scoring-comparison-table th.scoring-gap-header { background: #f4ecd5 !important; color: #655331 !important; }' in template
    assert "function markReferenceHeader(header) {\n    header.classList.add('scoring-reference-header');" in script
    assert 'header.title = `${label} is the reference operator`;' in script


def test_operator_color_and_reference_markers_stay_on_operator_headers():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert '.scoring-comparison-table th.scoring-operator-header { background: color-mix(in srgb, var(--operator-accent, #607d8b) 20%, #fff) !important; color: #263f4b !important; box-shadow: inset 0 3px var(--operator-accent, #607d8b); }' in template
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


def test_dense_powerpoint_export_choice_controls_split_parameter_and_cancel():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    payload = {
        'snippets': {
            'environmentOf': _function_source(script, 'environmentOf'),
            'pptHasDenseCharts': _function_source(script, 'pptHasDenseCharts'),
            'generateScoringPpt': _function_source(script, 'generateScoringPpt'),
        },
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const dense = environment => ({context: {environment}, hierarchy_columns: Array(21).fill({})});
const atLimit = {context: {environment: 'DriveCity'}, hierarchy_columns: Array(20).fill({}),
  rows: [{category: 'Only category'}]};
const cases = [
  {choice: 'confirm', environment: 'DriveCity', tables: [dense('DriveCity')]},
  {choice: 'secondary', environment: 'DriveCity', tables: [dense('DriveCity')]},
  {choice: 'cancel', environment: 'DriveCity', tables: [dense('DriveCity')]},
  {choice: 'confirm', environment: 'all', tables: [dense('DriveCity'), dense('Walk')]},
  {choice: 'no-dialog', environment: 'DriveCity', tables: [atLimit]},
];
const results = [];
(async () => {
  for (const testCase of cases) {
    let assigned = null;
    let dialog = null;
    const context = {
      currentResults: {views: {hierarchy_score_tables: testCase.tables}},
      selectedEnvironment: testCase.environment,
      showConfirmDialog: testCase.choice === 'no-dialog' ? undefined
        : async (message, options) => { dialog = {message, ...options}; return testCase.choice; },
      URL,
      window: {
        location: {href: 'https://example.test/scoring/jobs/1/export/ppt?environment=DriveCity',
          assign: url => { assigned = url; }},
      },
    };
    vm.createContext(context);
    vm.runInContext(Object.values(payload.snippets).join('\n'), context);
    await vm.runInContext("generateScoringPpt({href: window.location.href})", context);
    results.push({
      choice: testCase.choice,
      assigned,
      splitCharts: assigned && new URL(assigned).searchParams.get('split_charts'),
      dialog,
    });
  }
  process.stdout.write(JSON.stringify(results));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""

    result = _run_node_json(program, payload)

    assert [item['splitCharts'] for item in result] == ['true', 'false', None, 'true', 'false']
    assert result[2]['assigned'] is None
    assert result[4]['dialog'] is None
    assert all(item['dialog']['title'] == 'PowerPoint chart layout' for item in result[:4])
    assert all('more than 20 bars' in item['dialog']['message']
               and 'more than 40 bars' in item['dialog']['message'] for item in result[:4])
    assert all(item['dialog']['confirmLabel'] == 'Yes, split charts' for item in result[:4])
    assert all(item['dialog']['secondaryLabel'] == 'No, keep all bars on one slide' for item in result[:4])
    assert all(item['dialog']['cancelLabel'] == 'Cancel' for item in result[:4])


def test_dense_chart_thresholds_respect_best_network_and_category_bar_limits():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    payload = {
        'snippets': {
            'environmentOf': _function_source(script, 'environmentOf'),
            'pptHasDenseCharts': _function_source(script, 'pptHasDenseCharts'),
        },
    }
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const context = {};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n'), context);
const hierarchy = count => ({
  context: {environment: 'DriveCity'}, hierarchy_columns: Array(count).fill({}),
  rows: [{category: 'Only category'}],
});
const simple = (categoryCount, environment = 'DriveCity') => ({
  context: {environment}, operators: ['A', 'B', 'C', 'D'],
  rows: Array.from({length: categoryCount}, (_value, index) => ({category: `Category ${index}`})),
});
const checks = [
  ['best-network-20', {hierarchy_score_tables: [hierarchy(20)]}, 'DriveCity'],
  ['best-network-21', {hierarchy_score_tables: [hierarchy(21)]}, 'DriveCity'],
  ['category-40', {score_tables: [simple(10)]}, 'DriveCity'],
  ['category-44', {score_tables: [simple(11)]}, 'DriveCity'],
  ['selected-environment-excludes-dense', {score_tables: [simple(11, 'Walk')]}, 'DriveCity'],
  ['all-environments-includes-dense', {score_tables: [simple(11, 'Walk')]}, 'all'],
];
const result = checks.map(([name, payload, environment]) => [
  name, context.pptHasDenseCharts(payload, environment),
]);
process.stdout.write(JSON.stringify(result));
"""

    result = _run_node_json(program, payload)

    assert result == [
        ['best-network-20', False], ['best-network-21', True],
        ['category-40', False], ['category-44', True],
        ['selected-environment-excludes-dense', False], ['all-environments-includes-dense', True],
    ]


def test_scoring_tab_is_plural_and_subtotals_and_totals_share_category_background():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert 'data-result-tab="scoring">Scoring Tables</button>' in template
    assert 'data-result-tab="scoring">Scoring Table</button>' not in template
    assert re.search(
        r'\.scoring-comparison-table tbody tr\.scoring-category-subtotal > td,\s*'
        r'\.scoring-comparison-table tfoot tr > :is\(th, td\)\s*'
        r'\{\s*background-color:\s*#edf3f8\s*!important;',
        template,
    )
    assert '.scoring-table-wrap tbody tr.scoring-total-row > td { background-color: #edf3f8;' in template


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


def test_calculation_notes_render_coverage_emphasis_in_one_card_above_result_tabs():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    renderer = _function_source(script, 'renderWarnings')
    note = (
        'VF_UK / Samsung / 2026-Q1: maximum achievable scoring 933.2645 of 1000 points. '
        'Affected environments and scoring ceilings: DriveCity: 933.2645 of 650 points.'
    )
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tagName) { this.tagName = tagName; this.children = []; this.hidden = false; this.className = ''; this._text = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
}
const box = new Element('div');
const list = new Element('ul');
const root = {querySelector(selector) { return selector === '[data-warning-box]' ? box : list; }};
const document = {
  createElement(tagName) { return new Element(tagName); },
  createTextNode(value) { const node = new Element('#text'); node.textContent = value; return node; },
};
const renderWarnings = new Function('root', 'document', 'displayValue', payload.renderer + '\nreturn renderWarnings;')(
  root, document, value => String(value ?? ''));
renderWarnings([payload.note]);
process.stdout.write(JSON.stringify({
  hidden: box.hidden,
  noteText: list.children[0]?.textContent,
  emphasis: list.children[0]?.children.map(child => ({tag: child.tagName, className: child.className, text: child.textContent})),
}));
"""
    actual = _run_node_json(program, {'renderer': renderer, 'note': note})

    assert actual['hidden'] is False
    assert actual['noteText'] == note
    emphasis = [part for part in actual['emphasis'] if part['tag'] == 'strong']
    assert [part['text'] for part in emphasis] == [
        'maximum achievable scoring 933.2645 of 1000 points',
        '933.2645 of 650 points',
    ]
    assert all(part['className'] == 'scoring-warning-maximum' for part in emphasis)

    assert template.count('data-warning-box') == 1
    assert 'data-environment-warning' not in template
    assert template.index('data-warning-box') < template.index('data-result-tab=')
    assert '.scoring-warning-maximum { font-size: 1.15em; font-weight: 800; }' in template


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
        'styleIncompleteValue',
        'applyGapCategoryRunColors',
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
  querySelectorAll() { return descendants(this).filter(node => node.className === "scoring-category-cell"); }
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


def test_summary_ranking_uses_all_hierarchy_columns_and_keeps_tied_extremes():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    payload = {'summaryOperatorColors': _function_source(script, 'summaryOperatorColors'),
               'operatorValue': _function_source(script, 'operatorValue'),
               'firstValue': _function_source(script, 'firstValue')}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const context = {};
vm.createContext(context);
vm.runInContext(Object.values(payload).join('\n') + `
  const columns = [
    {id: 'north-a'}, {id: 'north-b'}, {id: 'south-a'}, {id: 'south-b'}, {id: 'east-a'},
  ];
  const values = {
    'north-a': {points: 100}, 'north-b': {points: 90},
    'south-a': {points: 10}, 'south-b': {points: 100}, 'east-a': {points: null},
  };
  globalThis.result = [...summaryOperatorColors(values, columns).entries()];`, context);
process.stdout.write(JSON.stringify(context.result));
"""
    result = _run_node_json(program, payload)

    assert result == [['north-a', '#C6EFCE'], ['south-a', '#FFC7CE'], ['south-b', '#C6EFCE']]


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
        _function_source(script, 'operatorGroupLabels'),
        _function_source(script, 'scoringVendorName'),
        _function_source(script, 'firstValue'),
        _function_source(script, 'formatDate'),
        _function_source(script, 'selectedContextFilters'),
        _function_source(script, 'savedJobFilterValues'),
        _function_source(script, 'campaignLabels'),
        _function_source(script, 'jobCampaigns'),
        _function_source(script, 'jobCardTitleSegments'),
        _function_source(script, 'jobCardTitle'),
        _function_source(script, 'jobCdrNames'),
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
  operatorGroups: [],
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
        'NSA', 'All Regions', 'All Clusters', 'All Cities', 'All Operators', 'All Vendors', 'UK_Q2_2026',
    ]
    assert result['cdrSummary'] == 'data.csv, voice.csv'
    assert result['metadataCdrSummary'] == 'data.csv, voice.csv'
    assert result['completeVendors'] == []
    assert result['subsetVendors'] == ['Nokia']
    assert result['submittedFilters'] == {'Vendor': ['Nokia', 'Ericsson']}
    assert result['partialVendors'] == ['Nokia']
    assert result['legacyVendors'] == ['Ericsson']
    assert result['fallbackTitle'].split(' ● ')[1:] == [
        'SA', 'All Regions', 'All Clusters', 'All Cities', 'All Operators', 'All Vendors', 'UK_Q3_2026',
    ]


def test_kpi_value_cells_are_blank_for_category_subtotals_in_both_table_modes():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert script.count("cell.textContent = isCategoryRow ? '' : formatRawKpiValue(rawValue);") == 2
    assert script.count("const isCategoryRow = item?.row_type === 'category';") == 2


def test_allocation_donut_global_environment_rings_and_single_environment_radius():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    functions = '\n'.join(_function_source(script, name) for name in (
        'formatChartNumber', 'maximumAllocationEnvironments', 'allocationEnvironmentLabel', 'allocationCategoryLabel', 'allocationIconPath',
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
    assert result['one'][0]['data-allocation-radius'] == result['global'][0]['data-allocation-radius'] == pytest.approx(134.16)
    assert result['one'][0]['data-allocation-center'] == '230,230'
    assert result['one'][0]['d'].count(' A ') == 4
    assert [item['data-allocation-radius'] for item in result['one'][1:]] == pytest.approx([89.5408, 89.5408])
    assert result['global'][0]['data-allocation-radius'] > result['global'][2]['data-allocation-radius']
    assert len(result['single']) == 1 and result['single'][0]['color'] == '#E6A81D'
    assert result['icons'] == 7  # Five legend icons plus two exterior environment markers.
    assert '1000.00' in result['globalText']
    assert '350.00' in result['singleText']
    assert 'Drive - Connecting Roads:' in result['singleText']
    assert 'Global:' not in result['singleText']


def test_summary_operator_highlights_rank_all_columns_and_include_ties():
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
        'C': '#FFC7CE', 'D': '#FFC7CE', 'E': '#C6EFCE',
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
        'styleIncompleteValue',
        'applyGapCategoryRunColors',
    )
    payload = {'snippets': {name: _function_source(script, name) for name in names}}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.style = {setProperty() {}};
    this.className = ''; this.classList = {add: value => { this.className += ` ${value}`; }}; }
  append(...nodes) { this.children.push(...nodes); }
  querySelectorAll() { return descendants(this).filter(node => node.className === "scoring-category-cell"); }
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


def test_calculation_match_controls_cover_pending_cache_and_stale_responses():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    payload = {'snippets': {
        name: _function_source(script, name)
        for name in ('calculationPayload', 'updateCalculationMatch')
    }}
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const timers = [];
const messages = [];
const requests = [];
const context = {
  calculationMatchKey: '', calculationMatchRevision: 0, calculationMatchTimer: null,
  submittingCalculation: false, jobsUrl: '/api/scoring/jobs',
  calculateButton: {disabled: false}, recalculateButton: {disabled: false},
  selectedLevels: () => ['City'], selectedDatasetIds: () => [12, 14],
  scoringProfileSelect: {value: 'profile-a'}, nrFilter: {value: 'NSA'},
  baselineInput: {value: 'Operator A'}, selectedContextFilters: () => ({Region: ['North']}),
  normalizeStatus: job => job?.status || '', isActive: job => ['queued', 'processing'].includes(job?.status),
  setMessage: (text, kind = '') => messages.push({text, kind}),
  requestJson: (...args) => new Promise((resolve, reject) => requests.push({args, resolve, reject})),
  window: {
    setTimeout: callback => { timers.push(callback); return timers.length; },
    clearTimeout: () => {},
  },
};
vm.createContext(context);
vm.runInContext(Object.values(payload.snippets).join('\n'), context);
async function flush() { await new Promise(resolve => setImmediate(resolve)); }
async function main() {
  context.updateCalculationMatch(true);
  const pending = [context.calculateButton.disabled, context.recalculateButton.disabled];
  timers[0]();
  requests[0].resolve({job: null});
  await flush();
  const noMatch = [context.calculateButton.disabled, context.recalculateButton.disabled, messages.at(-1)?.text];

  context.calculationMatchKey = '';
  context.updateCalculationMatch(true);
  timers[1]();
  requests[1].resolve({job: {id: 8, status: 'completed'}});
  await flush();
  const completed = [context.calculateButton.disabled, context.recalculateButton.disabled];

  context.calculationMatchKey = '';
  context.updateCalculationMatch(true);
  timers[2]();
  requests[2].resolve({job: {id: 9, status: 'queued'}});
  await flush();
  const active = [context.calculateButton.disabled, context.recalculateButton.disabled];

  context.calculationMatchKey = '';
  context.updateCalculationMatch(true);
  const staleRevision = context.calculationMatchRevision;
  timers[3]();
  context.baselineInput.value = 'Operator B';
  context.updateCalculationMatch(true);
  timers[4]();
  requests[4].resolve({job: null});
  await flush();
  const latestMessage = messages.at(-1)?.text;
  requests[3].resolve({job: {id: 10, status: 'completed'}});
  await flush();
  const staleResponseIgnored = context.calculationMatchRevision > staleRevision
    && context.calculateButton.disabled === false && context.recalculateButton.disabled === true
    && messages.at(-1)?.text === latestMessage;
  process.stdout.write(JSON.stringify({pending, noMatch, completed, active, staleResponseIgnored,
    matchUrl: requests[0].args[0], matchPayload: JSON.parse(requests[0].args[1].body)}));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = _run_node_json(program, payload)
    assert result['pending'] == [True, True]
    assert result['noMatch'] == [False, True, 'Ready to calculate a new scoring job.']
    assert result['completed'] == [True, False]
    assert result['active'] == [True, True]
    assert result['staleResponseIgnored'] is True
    assert result['matchUrl'] == '/api/scoring/jobs/match'
    assert result['matchPayload'] == {
        'dataset_ids': [12, 14], 'aggregation_levels': ['Operator', 'City'],
        'scoring_profile_id': 'profile-a', 'nr_mode': 'NSA', 'baseline_operator': 'Operator A',
        'context_filters': {'Region': ['North']},
    }
