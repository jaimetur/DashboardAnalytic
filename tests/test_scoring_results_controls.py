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
    assert "combinedIsAvailable ? 'Combined' : (actual[0] || null)" in script
    assert 'Combined view unavailable; showing ${environmentLabel(environmentSelection.fallback)}' in script
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
    assert 'const height = 620;' in script
    assert 'const scaleValue = maxActual > 0 ? maxActual : maxAllocation;' in script


def test_hierarchy_reference_header_uses_only_a_yellow_top_marker():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')
    match = re.search(
        r'\.scoring-comparison-table th\.scoring-hierarchy-header\.scoring-reference-header\s*\{([^}]*)\}',
        template,
    )
    assert match
    assert 'border-top: 5px solid #ffff00' in match.group(1)
    assert 'background:' not in match.group(1)
    assert 'color:' not in match.group(1)


def test_export_links_have_distinct_high_contrast_colors():
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert '.scoring-export-actions a[data-export-scoring] { border-color: #16734b; background: #16734b; color: #fff; }' in template
    assert '.scoring-export-actions a[data-export-gap] { border-color: #1267a5; background: #1267a5; color: #fff; }' in template
    assert '.scoring-export-actions a[data-export-ppt] { border-color: #a84d00; background: #a84d00; color: #fff; }' in template
