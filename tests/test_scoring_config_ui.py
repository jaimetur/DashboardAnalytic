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

    assert 'data-scoring-add-category' in template
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
    assert 'cell.colSpan = 19;' in script


def test_kpi_categories_are_selectable_saved_and_created_with_a_first_kpi():
    script = PANEL_SCRIPT.read_text(encoding='utf-8')

    assert "appendSelect(categoryCell, selectedCategory" in script
    assert "'data-kpi-category': ''" in script
    assert 'refreshKpiCategoryOptions();' in script
    assert 'select.value = selectedCategory;' in script
    assert "description: 'Create a category with its first KPI. Configure the KPI before saving.'" in script
    assert 'categoryCreate: true' in script
    assert 'categoryNameIsAvailable(name)' in script
    assert 'addKpi(null, category, {categoryCreated: true});' in script
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
    assert "mapping[g2 ? `${g1} + ${g2}` : g1] = key;" in script
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
    assert 'window.prompt' not in script
    assert 'window.confirm' not in script
    assert 'const orderedCategories = Array.from(grouped.keys());' in script
    assert 'calculationDialog.showModal()' in script
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
    for panel_id in ['scoring-kpi-configuration', 'scoring-aggregation-hierarchy', 'scoring-gap-priority']:
        assert f'id="{panel_id}"' in template
    assert "ancestor.tagName?.toLowerCase() === 'details'" in script
    assert 'if (window.location.hash) openScoringConfigHashTarget();' in script
