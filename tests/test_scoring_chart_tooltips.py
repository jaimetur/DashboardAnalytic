from pathlib import Path
import json
import os
import re
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_TEMPLATE = PROJECT_ROOT / 'src/web_interface/templates/scoring.html'
SCORING_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring.js'


def test_chart_tooltips_use_delegated_pointer_and_keyboard_events_with_fallbacks():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert "root.addEventListener('pointerover'" in script
    assert "root.addEventListener('pointermove'" in script
    assert "root.addEventListener('focusin'" in script
    assert "root.addEventListener('focusout'" in script
    assert "target?.closest?.('[data-chart-tooltip]')" in script
    # Marks with an explicit tooltip work in every chart, such as the location cards.
    assert "anchor.hasAttribute('data-chart-tooltip') || anchor.closest('.scoring-chart-svg')" in script
    assert "anchor?.getAttribute('aria-label')" in script
    assert "anchor?.getAttribute('title')" in script
    assert "anchor?.querySelector('title')?.textContent" in script
    assert "element.setAttribute('aria-describedby', chartTooltip.id);" in script


def test_tooltips_cover_scoring_hierarchy_best_network_and_allocation_marks():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert '`KPI category: ${seriesName}`' in script
    assert '`Hierarchy: ${fullCategory}`' in script
    assert '`Operator: ${operatorPresentation(operatorTable, operatorName).label}`' in script
    assert '`Environment: ${chartEnvironmentName(operatorTable)}`' in script
    assert '`Weighted points: ${formattedChartPoints(numeric)}`' in script
    assert '`Series: ${kind}`' in script
    assert 'Share of configured maximum:' in script
    assert 'Maximum points: ${formattedChartPoints(segment.value)}' in script
    assert "setChartTooltip(rect, segmentTooltip, true);" in script
    assert "setChartTooltip(mark," in script
    assert "setChartTooltip(text, item.lines.join(' '));" in script


def test_category_legend_is_a_continuous_gray_band_inside_each_scoring_chart():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert 'function categoryLegendGray(index, count)' in script
    assert 'color: categoryLegendGray(index, kpiCategories.length)' in script
    assert 'legendEntries: operatorLegend,' in script
    assert 'categoryLegendEntries: categoryLegend,' in script
    assert 'const categoryLegendHeight = categoryLegendEntries.length ? 76 : 0;' in script
    assert 'const height = baseHeight + categoryLegendHeight;' in script
    assert 'const chartHeight = baseHeight - top - baseBottom;' in script
    assert 'const bandWidth = width - left - right;' in script
    assert 'const segmentWidth = bandWidth / categoryLegendEntries.length;' in script
    assert "class: 'scoring-chart-category-legend-segment'" in script
    assert 'categoryLegendTextLines(labelText, maxLength, 2)' in script
    assert 'label.style.fill = categoryLegendTextColor(fill);' in script
    assert "setChartTooltip(segment, tooltip, true);" in script
    assert "setChartTooltip(label, tooltip, true);" in script
    assert "class: 'scoring-chart-category-legend-label'" in script
    assert 'const categories = [...new Set(selected.rows.map(row => String(row.category)))];' in script
    assert 'categoryLegendEntries,' in script
    # The enlarged view shows a copy of the chart (with its legend) and zooms it.
    assert 'holder.append(copy);' in script and 'expandedChart.replaceChildren(holder);' in script
    assert '.scoring-chart-svg .scoring-chart-category-legend-title' in template
    assert '.scoring-chart-svg .scoring-chart-category-legend-label' in template
    assert '.scoring-chart-svg .scoring-chart-category-legend-segment' in template


def test_best_network_bars_include_operator_mapping_legend_in_mapped_order():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert 'const legendByOperator = new Map();' in script
    assert 'data.operators.forEach((operator, index) =>' in script
    assert 'const operatorLegendEntries = [...legendByOperator.values()].sort((leftEntry, rightEntry) =>' in script
    assert 'leftEntry.position - rightEntry.position || leftEntry.sourceIndex - rightEntry.sourceIndex' in script
    assert 'color: mapped.color || barColors.get(operator)?.color' in script
    assert "legendTitle.textContent = 'Operators';" not in script
    assert "const label = svgElement(svg, 'text', {x: x + 21, y: y + 12, class: 'scoring-chart-legend'});" in script
    assert "setChartTooltip(swatch, String(entry.title || entry.label), true);" in script
    assert "const color = kind === 'Data' ? presentation.color : lightenHexColor(presentation.color);" in script
    assert '.scoring-chart-svg .scoring-chart-operator-legend-title' in template


def test_operator_accent_and_reference_marker_are_attached_to_operator_hierarchy_headers():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert "String(entry.level).toLocaleLowerCase() === 'operator'" in script
    assert 'th.classList.add(\'scoring-operator-header\');' in script
    assert 'hierarchyColumnIsReference(column)' in script
    assert '.scoring-comparison-table th.scoring-operator-header { background: color-mix(in srgb, var(--operator-accent, #607d8b) 20%, #fff) !important; color: #263f4b !important; box-shadow: inset 0 3px var(--operator-accent, #607d8b); }' in template
    assert '.scoring-comparison-table th.scoring-hierarchy-header {' in template
    assert 'border-bottom' not in re.search(
        r'\.scoring-comparison-table th\.scoring-hierarchy-header\s*\{([^}]*)\}', template,
    ).group(1)


def test_partial_gap_cells_and_averages_show_marker_and_weighted_environment_coverage():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert 'function partialGapCoverage(partial, environments)' in script
    assert 'Partial GAP coverage: the arithmetic comparison is based only on ${names.join' in script
    assert "`${formatMatrixNumber(value, true)}${partial && numeric ? '*' : ''}`" in script
    assert "firstValue(gapPartial, [operator], false), firstValue(gapEnvironments, [operator], [])" in script
    assert "firstValue(gapPartial, [column.id], false), firstValue(gapEnvironments, [column.id], [])" in script
    assert 'const partial = item?.gap_partial === true;' in script
    assert "partialGapCoverage(partial, item?.gap_environments)" in script
    assert 'total_gap_partial: total.gap_partial' in script


def test_scoring_subtotal_and_total_rows_share_the_category_background():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert re.search(
        r'\.scoring-comparison-table tbody tr\.scoring-category-subtotal > td,\s*'
        r'\.scoring-comparison-table tfoot tr > :is\(th, td\)\s*'
        r'\{\s*background-color:\s*#edf3f8\s*!important;',
        template,
    )
    assert '.scoring-table-wrap tbody tr.scoring-total-row > td { background-color: #edf3f8;' in template


def test_stacked_chart_segment_labels_use_contrasting_plain_text():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert script.count('segmentLabel.style.fill = categoryLegendTextColor(color);') == 2
    assert 'segmentLabel.style.stroke' not in script
    label_rule = re.search(r'\.scoring-chart-svg \.scoring-best-network-segment\s*\{([^}]*)\}', template)
    assert label_rule
    assert 'stroke' not in label_rule.group(1)
    assert 'paint-order' not in label_rule.group(1)
    assert 'text-shadow' not in label_rule.group(1)


def test_stacked_chart_labels_fit_segments_and_service_chart_explains_grayscale():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert re.search(
        r'function stackedSegmentLabelSize\(label, width, height\) \{\s*'
        r'const size = Math\.floor\(Math\.min\(22, \(width - 8\) / \(label\.length \* \.68\), '
        r'\(height - 5\) / 1\.2\)\);\s*return size >= 10 \? size : 0;\s*\}',
        script,
    )
    assert 'stackedSegmentLabelSize(segmentText, barWidth, segmentHeight)' in script
    assert script.count('stackedSegmentLabelSize(segmentText, barWidth, segmentHeight)') == 2
    service_chart = script[script.index('function makeBestNetworkBars('):script.index('function maximumAllocationEnvironments(')]
    assert "segmentLabel.textContent = segmentText;" in service_chart
    assert "`${kind}: ${cell.value" not in service_chart
    assert "serviceLegendTitle.textContent = 'Service types';" in service_chart
    assert "[[0, 'Data', '#555555'], [1, 'Voice', '#c5c5c5']]" in service_chart
    assert 'const height = chartHeight + 76;' in service_chart
    assert 'cloneNode(true)' in script[script.index('function makeExpandableChartCard('):]
    assert '.scoring-chart-svg .scoring-chart-axis-label { fill: #445a65; font-size: 18px;' in template
    assert '.scoring-chart-svg .scoring-chart-tick { fill: #657780; font-size: 15px;' in template
    assert '.scoring-chart-svg .scoring-chart-legend { fill: #334854; font-size: 15px;' in template
    assert '.scoring-chart-svg .scoring-chart-category { fill: #435964; font-size: 16px;' in template
    assert '.scoring-chart-card h4 { margin: 0 0 .6rem; color: #245e5a; font-size: 1.3rem; font-weight: 800; }' in template


def test_chart_numbers_keep_decimal_dot_under_spanish_locale():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    dashboard_script = (PROJECT_ROOT / 'src/web_interface/static/js/dashboard_charts.js').read_text(encoding='utf-8')
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required to verify chart number formatting.')

    start = script.index('  function formatChartNumber(')
    end = script.index('\n  function chartEnvironmentName(', start)
    formatter_source = script[start:end]
    program = f"""
{formatter_source}
console.log(JSON.stringify({{
  locale: Intl.NumberFormat().resolvedOptions().locale,
  decimal: formatChartNumber(1234.56, {{maximumFractionDigits: 2}}),
  integer: formatChartNumber(1234, {{maximumFractionDigits: 2}}),
  rounded: formatChartNumber(12.345, {{maximumFractionDigits: 2}}),
  padded: formatChartNumber(1234.5, {{minimumFractionDigits: 2, maximumFractionDigits: 2}}),
  fixedInteger: formatChartNumber(838, {{minimumFractionDigits: 1, maximumFractionDigits: 1}}),
  tooltip: formattedChartPoints(1234.5678),
  unavailable: formattedChartPoints('not-a-number')
}}));
"""
    environment = os.environ.copy()
    environment['LANG'] = 'es_ES.UTF-8'
    environment['LC_ALL'] = 'es_ES.UTF-8'
    completed = subprocess.run([node, '-e', program], capture_output=True, text=True,
                               check=False, env=environment)
    assert completed.returncode == 0, completed.stderr
    formatted = json.loads(completed.stdout)
    assert formatted == {
        'locale': 'es-ES', 'decimal': '1234.56', 'integer': '1234', 'rounded': '12.35',
        'padded': '1234.50', 'fixedInteger': '838.0', 'tooltip': '1234.568', 'unavailable': 'N/A',
    }

    assert script.count('formatChartNumber(Math.round(value), {maximumFractionDigits: 0})') == 2
    assert 'formatChartNumber(numeric, {minimumFractionDigits: 1, maximumFractionDigits: 1})' in script
    assert 'formatChartNumber(total, {minimumFractionDigits: 1, maximumFractionDigits: 1})' in script
    assert 'formatChartNumber(cell.value, {minimumFractionDigits: 1, maximumFractionDigits: 1})' in script
    assert 'formatChartNumber(totalPoints, {minimumFractionDigits: 1, maximumFractionDigits: 1})' in script
    assert 'formatChartNumber(row.value, {maximumFractionDigits: Number.isInteger(row.value) ? 0 : 2})' in script
    assert 'formatChartNumber(total, {minimumFractionDigits: 2, maximumFractionDigits: 2})' in script
    assert "number.toLocaleString('en-US', {useGrouping: false, maximumFractionDigits: 0})" in dashboard_script


def test_chart_axis_scale_uses_integer_intervals_and_covers_actual_peaks():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required to verify scoring chart scales.')

    start = script.index('  function scoringChartScale(')
    end = script.index('\n  function configuredChartMaximum(', start)
    program = f"""
{script[start:end]}
const cases = [
  scoringChartScale(1000, 0), scoringChartScale(650, 0), scoringChartScale(1200, 0),
  scoringChartScale(0, 12.5), scoringChartScale(0, 650.5), scoringChartScale(0, 0),
  scoringChartScale(0, 13), scoringChartScale(1000.0000000001, 0),
  scoringChartScale(650, 700),
];
console.log(JSON.stringify(cases.map(item => ({{maximum: item.maximum, intervals: item.intervals}}))));
"""
    completed = subprocess.run([node, '-e', program], capture_output=True, text=True,
                               check=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        {'maximum': 1000, 'intervals': 5}, {'maximum': 650, 'intervals': 5},
        {'maximum': 1200, 'intervals': 4}, {'maximum': 15, 'intervals': 5},
        {'maximum': 660, 'intervals': 6}, {'maximum': 5, 'intervals': 5},
        {'maximum': 15, 'intervals': 5}, {'maximum': 1000, 'intervals': 5},
        {'maximum': 700, 'intervals': 5},
    ]
