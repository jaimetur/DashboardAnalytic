import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring.js'


def _function_source(script: str, name: str) -> str:
    start = script.index(f'  function {name}(')
    end = script.index('\n  }', start) + len('\n  }')
    return script[start:end]


def _run_node_json(program: str, payload: dict) -> dict:
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for scoring GAP view checks.')
    completed = subprocess.run(
        [node, '-e', program], input=json.dumps(payload), capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_gap_row_order_drops_subtotals_and_keeps_mode_order_or_individual_gap_order():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    helper = _function_source(script, 'orderGapRows')
    program = r'''
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
''' + helper + r'''
const rows = payload.rows;
const combined = orderGapRows(rows, item => [item.gap_points], false);
const individual = orderGapRows(rows, item => [item.gap_points], true);
process.stdout.write(JSON.stringify({
  combined: combined.map(row => row.kpi_code),
  individual: individual.map(row => row.kpi_code),
  types: [...combined, ...individual].map(row => row.row_type),
}));
'''
    rows = [
        {'row_type': 'kpi', 'category': 'A', 'kpi_code': 'K1', 'gap_points': 2},
        {'row_type': 'kpi', 'category': 'B', 'kpi_code': 'K2', 'gap_points': None},
        {'row_type': 'category', 'category': 'A', 'kpi_code': '', 'gap_points': 1},
        {'row_type': 'kpi', 'category': 'A', 'kpi_code': 'K3', 'gap_points': -4},
        {'row_type': 'category', 'category': 'B', 'kpi_code': '', 'gap_points': None},
    ]
    result = _run_node_json(program, {'rows': rows})

    assert result['combined'] == ['K1', 'K2', 'K3']
    assert result['individual'] == ['K3', 'K1', 'K2']
    assert set(result['types']) == {'kpi'}


def test_gap_renderers_have_no_category_or_overall_total_footer():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    for name in ('renderGapViews', 'renderGapSummaryViews', 'renderHierarchyGapViews'):
        source = _function_source(script, name)
        assert "createElement('tfoot')" not in source
        assert 'Average KPI GAP' not in source
        assert 'Total signed GAP' not in source
    assert 'Category and final GAP rows show the arithmetic mean' not in script


def test_gap_operator_selection_restores_and_is_scoped_to_job_and_context():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    snippets = '\n'.join(_function_source(script, name) for name in (
        'readScoringViewState', 'persistScoringViewState', 'comparisonIdentity',
        'gapComparisonIdentity', 'selectedGapLayout', 'showGapValues',
    ))
    program = r'''
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const values = new Map([[payload.storageKey, JSON.stringify(payload.state)]]);
const window = {scrollY: 12, sessionStorage: {
  getItem: key => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
}};
const scoringViewStorageKey = payload.storageKey;
const resultTabNames = new Set(['scoring', 'gap', 'charts']);
let selectedJobId = payload.jobId;
let currentResultsJobId = payload.jobId;
let activeResultTab = 'gap';
let selectedEnvironment = 'Combined';
const gapLayoutSelect = {value: 'end'};
const showGapValuesToggle = {checked: false};
const showKpiValuesToggle = {checked: false};
const gapComparisonSelections = new Map();
const contextSelections = new Map([['score', 'unrelated-context']]);
''' + snippets + r'''
const restored = readScoringViewState();
for (const [key, value] of Object.entries(restored.gapComparisons)) gapComparisonSelections.set(key, value);
const firstKey = gapComparisonIdentity(payload.table, 'hierarchy-gap');
const secondKey = gapComparisonIdentity(payload.table, 'gap-summary:EE');
const otherJob = payload.jobId;
selectedJobId = `${otherJob}-next`;
const nextJobKey = gapComparisonIdentity(payload.table, 'hierarchy-gap');
selectedJobId = otherJob;
gapComparisonSelections.set(firstKey, 'operator:Vodafone UK');
gapComparisonSelections.set(secondKey, 'all');
persistScoringViewState();
const saved = JSON.parse(values.get(payload.storageKey));
const restoredAfterSave = readScoringViewState();
process.stdout.write(JSON.stringify({
  selected: restored.gapComparisons[firstKey],
  summarySelected: restored.gapComparisons[secondKey],
  otherJob: restored.gapComparisons[nextJobKey] || null,
  invalid: restored.gapComparisons.invalid || null,
  savedSelected: restoredAfterSave.gapComparisons[firstKey],
  savedSummarySelected: restoredAfterSave.gapComparisons[secondKey],
  savedUnrelated: saved.context_selections || saved.score || null,
  firstKey, secondKey, nextJobKey,
}));
'''
    table = {
        'title': 'GAP by hierarchy',
        'context': {'environment': 'Combined', 'region': 'North'},
    }
    hierarchy_identity = json.dumps(
        ['hierarchy-gap', table['title'], table['context'], ''], separators=(',', ':'),
    )
    summary_identity = json.dumps(
        ['gap-summary:EE', table['title'], table['context'], ''], separators=(',', ':'),
    )
    hierarchy_key = json.dumps(
        ['job-42', 'hierarchy-gap', hierarchy_identity], separators=(',', ':'),
    )
    summary_key = json.dumps(
        ['job-42', 'gap-summary:EE', summary_identity], separators=(',', ':'),
    )
    result = _run_node_json(program, {
        'storageKey': 'workspace-scoring-view',
        'jobId': 'job-42',
        'table': table,
        'state': {
            'gap_comparisons': {
                hierarchy_key: 'operator:O2 UK',
                summary_key: 'all',
                'invalid': {'operator': 'O2'},
            },
        },
    })

    assert result['selected'] == 'operator:O2 UK'
    assert result['summarySelected'] == 'all'
    assert result['otherJob'] is None
    assert result['invalid'] is None
    assert result['firstKey'] != result['nextJobKey']
    assert result['savedSelected'] == 'operator:Vodafone UK'
    assert result['savedSummarySelected'] == 'all'
    assert result['savedUnrelated'] is None
    assert 'gap_comparisons: typeof gapComparisonSelections' in script
    assert 'gapComparisonSelections.set(hierarchyGapOperator.dataset.hierarchyGapStateKey, hierarchyGapOperator.value);' in script
    assert 'gapComparisonSelections.set(gapSummaryOperator.dataset.gapSummaryStateKey, gapSummaryOperator.value);' in script


def test_gap_category_column_colors_alternate_by_consecutive_category_run():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    helper = _function_source(script, 'applyGapCategoryRunColors')
    program = r'''
const cells = JSON.parse(require('node:fs').readFileSync(0, 'utf8')).runs.map(() => ({
  style: {setProperty(name, value, priority) {this.color = value; this.priority = priority;}}
}));
''' + helper + r'''
applyGapCategoryRunColors({querySelectorAll: () => cells});
process.stdout.write(JSON.stringify(cells.map(cell => [cell.style.color, cell.style.priority])));
'''
    result = _run_node_json(program, {'runs': ['A', 'B', 'A', 'C']})
    assert result == [
        ['#edf3f8', 'important'], ['#e3ecf3', 'important'],
        ['#edf3f8', 'important'], ['#e3ecf3', 'important'],
    ]
    for name in ('renderGapViews', 'renderGapSummaryViews', 'renderHierarchyGapViews'):
        assert 'applyGapCategoryRunColors(tbody);' in _function_source(script, name)
    for name in ('appendMatrixTable', 'appendHierarchyMatrixTable'):
        assert 'if (!isSummary) applyGapCategoryRunColors(tbody);' in _function_source(script, name)


def test_chart_context_subtitles_omit_environment_without_changing_other_context_labels():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    helper = _function_source(script, 'hierarchyDisplayValue') + '\n' + _function_source(script, 'contextLabel')
    program = r'''
const environmentLabel = value => value === 'Combined' ? 'All Environments' : value;
const humanizeKey = value => value;
''' + helper + r'''
const context = {campaign: 'Q2', region: 'North', vendor: 'Nokia', environment: 'Combined'};
process.stdout.write(JSON.stringify({
  chart: contextLabel(context, {environmentPrefix: false}),
  default: contextLabel(context),
}));
'''
    result = _run_node_json(program, {})

    assert result['chart'] == 'campaign: Q2 · region: North · vendor: Nokia · All Environments'
    assert 'Environment:' not in result['chart']
    assert 'environment: All Environments' in result['default']
    assert "contextLabel(selected.context, {environmentPrefix: false})" in script
