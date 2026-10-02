from pathlib import Path
import re


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
    assert "expandedChart.replaceChildren(chart);" in script
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
    assert "legendTitle.textContent = 'Operators';" in script
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
    assert '.scoring-comparison-table th.scoring-operator-header { background: var(--operator-accent, #607d8b) !important; color: var(--operator-text, #ffffff) !important; }' in template
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
