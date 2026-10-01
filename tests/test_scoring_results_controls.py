from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_TEMPLATE = PROJECT_ROOT / 'src/web_interface/templates/scoring.html'
SCORING_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring.js'


def test_results_environment_defaults_to_all_and_exports_selected_scope():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert 'let selectedEnvironment = \'all\';' in script
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
        r'\.scoring-chart-svg\.scoring-best-network-bars\s*\{[^}]*min-width:\s*980px;'
        r'[^}]*max-width:\s*none;[^}]*min-height:\s*0;', template,
    )
    assert "svg.style.minWidth = `${width}px`;" in script
    assert "svg.style.maxWidth = 'none';" in script
    assert "scroll.className = 'scoring-chart-scroll';" in script
    assert 'const baseHeight = 620;' in script
    assert 'const plotHeight = baseHeight - 72 - bottom;' in script
    assert 'const scaleValue = maxActual > 0 ? maxActual : maxAllocation;' in script


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
    assert "if (showGapValuesToggle) showGapValuesToggle.checked = false;" in script
    assert "function showGapValues() {\n    return Boolean(showGapValuesToggle?.checked);" in script
    assert "if (!showGapValues()) {\n      for (const [operatorIndex, operator] of operators.entries()) appendScore(operator, operatorIndex);\n      return;" in script
    assert "if (event.target === showGapValuesToggle) {\n      syncGapValueControls();\n      if (currentResults) renderResult(currentResults, selectedJob, ['scoring']);" in script
    assert "function renderTable(pane, source, emptyCopy, {hideGapColumns = false} = {})" in script
    assert "renderTable(gapPane, gapRows, 'No GAP rows are available for the selected baseline operator.');" in script
    assert "function appendScoringGapScale(pane, tableData) {\n    if (!showGapValues()) return;" in script
    assert script.count("label.textContent = showGapValues() && total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';") == 2


def test_results_selectors_precede_value_toggles_and_gap_layout_is_conditional():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    selector_row = re.search(r'<div class="scoring-results-selector-row"[^>]*>(.*?)</div>', template, re.S)
    value_row = re.search(r'<div class="scoring-results-value-row"[^>]*>(.*?)</div>', template, re.S)
    assert selector_row and value_row
    environment_index = selector_row.group(1).index('data-result-environment-control')
    mode_index = selector_row.group(1).index('data-scoring-table-mode')
    assert environment_index < mode_index
    assert template.index('data-scoring-results-selector-row') < template.index('data-show-kpi-values')
    assert 'data-scoring-gap-layout-control hidden' in template
    assert 'if (gapLayoutControl) gapLayoutControl.hidden = !showGapValues();' in script


def test_gap_value_choice_is_sent_only_to_powerpoint_export():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert "const gapOption = kind === 'ppt' ? `&show_gap_values=${showGapValues() ? 'true' : 'false'}` : '';" in script
    assert "link.href = enabled ? `${exportBase}/${encodeURIComponent(jobId)}/export/${kind}?${query}${gapOption}` : '#';" in script
    assert "const query = `table_mode=${encodeURIComponent(selectedTableMode())}&gap_layout=${encodeURIComponent(selectedGapLayout())}&environment=${encodeURIComponent(selectedEnvironment || 'all')}`;" in script


def test_scoring_tab_is_singular_and_category_subtotals_have_gray_background():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert 'data-result-tab="scoring">Scoring Table</button>' in template
    assert 'data-result-tab="scoring">Scoring Tables</button>' not in template
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
