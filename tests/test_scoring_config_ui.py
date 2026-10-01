from pathlib import Path
import json
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
    assert "const profilesEndpoint = '/api/workspace-config/scoring-profiles';" in script
    assert 'latest.active_profile_id = profileId' in script


def test_scoring_kpi_table_exposes_editable_category_formula_and_filter_controls():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'data-scoring-add-kpi' in template
    assert 'data-scoring-kpi-rows' in template
    assert '<th scope="col">Category</th>' in template
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
        'scoring-kpi-configuration',
        'scoring-aggregation-hierarchy',
        'scoring-gap-priority',
    ]
    panel_positions = [template.index(f'id="{panel_id}"') for panel_id in panel_ids]
    assert panel_positions == sorted(panel_positions)
    assert 'window.addEventListener(\'hashchange\', openScoringConfigHashTarget)' in script
    assert 'target.open = true' in script
    assert 'target.scrollIntoView' in script


def test_gap_priority_table_displays_kpi_category():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert '<th scope="col">Category</th><th scope="col">Order</th>' in template
    assert "appendCell(row).textContent = priorityMetric(code)?.category || 'Other';" in script


def test_scoring_environment_crud_and_context_drafts_are_available():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'data-scoring-environment-create' in template
    assert 'data-scoring-environment-delete' in template
    assert 'data-environment-g1' in template
    assert 'data-environment-g2' in template
    assert 'data-profile-dialog-environment-fields' in template
    assert 'const createEnvironment = async () =>' in script
    assert 'const deleteEnvironment = async () =>' in script
    assert 'applyEnvironmentMapping(latestConfiguration.scope)' in script
    assert "mapping[g2 ? `${g1} + ${g2}` : g1] = key;" in script
    assert 'captureSelectedContext(row, lastEnvironment)' in script
    assert 'hydrateSelectedContext(row, lastEnvironment)' in script
    assert "description: `Delete “${environmentLabel(environment)}” and its KPI points, thresholds, and mappings from this methodology?`" in script


def test_code_column_is_the_single_editable_code_input_and_updates_gap_priority():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert '<th scope="col" rowspan="2">Code</th><th scope="col" rowspan="2">KPI</th>' in template
    assert script.count("'data-kpi-code-input': ''") == 1
    assert "summary.textContent = 'Edit formula and filters';" in script
    assert 'codeMap.get(code)' in script
    assert "title: 'Changing this code also updates its saved GAP priority entry.'" in script
    assert 'window.prompt' not in script
    assert 'window.confirm' not in script
    assert 'const orderedCategories = Array.from(grouped.keys());' in script
    assert "summary.textContent = 'Edit formula and filters';" in script
    assert "denominatorLabel.textContent = 'Calculation basis (derived from formula)'" in script
    assert "formula.trim() === originalFormula && storedDenominator ? storedDenominator : deriveDenominator(formula)" in script
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
        "console.log(JSON.stringify({shares, points, total: points.reduce((a, b) => a + b, 0)}));"
    )
    completed = subprocess.run([node, '-e', program], check=True, capture_output=True, text=True)
    allocation = json.loads(completed.stdout)

    assert allocation['shares'] == pytest.approx([500 / 650, 150 / 650])
    assert allocation['points'] == pytest.approx([100 * 500 / 650, 100 * 150 / 650])
    assert allocation['total'] == pytest.approx(100)


def test_scoring_gap_setup_parent_keeps_child_anchor_ids_and_opens_ancestors():
    template = PANEL_TEMPLATE.read_text(encoding='utf-8')
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert 'id="scoring-gap-analysis-setup"' in template
    for panel_id in ['scoring-kpi-configuration', 'scoring-aggregation-hierarchy', 'scoring-gap-priority']:
        assert f'id="{panel_id}"' in template
    assert "ancestor.tagName?.toLowerCase() === 'details'" in script
    assert 'if (window.location.hash) openScoringConfigHashTarget();' in script
