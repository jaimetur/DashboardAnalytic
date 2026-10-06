from __future__ import annotations

from src.branding import apply_legacy_environment, canonical_format
from src.modules.scoring_config import unwrap_scoring_profiles_payload


def test_canonical_format_maps_legacy_product_prefix() -> None:
    assert canonical_format('dashboard-analytic-export') == 'drivetest-analyzer-export'
    assert canonical_format('drivetest-analyzer-main-cities') == 'drivetest-analyzer-main-cities'
    assert canonical_format('nq-call-tracking') == 'nq-call-tracking'
    assert canonical_format(None) is None


def test_legacy_environment_variables_fill_missing_current_names() -> None:
    environment = {
        'DASHBOARD_ANALYTIC_CHROMIUM': '/legacy/chromium',
        'DASHBOARD_ANALYTIC_REPORT_CHART_RENDERER': 'pil',
        'DRIVETEST_ANALYZER_REPORT_CHART_RENDERER': 'dashboard-canvas',
    }
    apply_legacy_environment(environment)
    assert environment['DRIVETEST_ANALYZER_CHROMIUM'] == '/legacy/chromium'
    assert environment['DRIVETEST_ANALYZER_REPORT_CHART_RENDERER'] == 'dashboard-canvas'


def test_legacy_scoring_configuration_export_is_accepted() -> None:
    assert unwrap_scoring_profiles_payload({'format': 'dashboard-analytic-scoring-configuration', 'version': 1, 'configuration': None}) is None
