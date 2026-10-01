from datetime import datetime

from src.modules.cdr_report_filenames import build_cdr_report_filename, build_scoring_report_filename


def test_build_cdr_report_filename_uses_the_shared_dashboard_format():
    filename = build_cdr_report_filename(
        datetime(2026, 9, 30, 12, 34, 56),
        'NSA',
        'Scoring & GAP Analysis',
        'Operator Comparison',
        'North',
        'UK_Q2_2026_vs_UK_Q3_2026',
    )

    assert filename == (
        '20260930_123456 - NSA - Scoring & GAP Analysis - Operator Comparison - North '
        '- UK_Q2_2026_vs_UK_Q3_2026.pptx'
    )


def test_build_cdr_report_filename_sanitizes_and_limits_long_names():
    filename = build_cdr_report_filename(
        datetime(2026, 9, 30, 12, 34, 56),
        'NSA',
        'Dashboard / ' + 'Very long name ' * 30,
        'Multivendor comparison',
        'Northern region ' * 20,
        'Campaign ' * 30,
    )

    assert '/' not in filename
    assert len(filename.encode('utf-8')) <= 245
    assert filename.endswith('.pptx')


def test_build_scoring_report_filename_uses_saved_filter_dimensions_and_order():
    filename = build_scoring_report_filename(
        datetime(2026, 9, 30, 12, 34, 56), 'NSA',
        {
            'Region': ['North', 'South'], 'City': ['Bristol'],
            'Operator': ['EE', 'O2'], 'Vendor': [], 'Campaign': ['UK_Q2_2026'],
        },
    )

    assert filename == (
        '20260930_123456 - Scoring & GAP Analysis - NSA - North + South - Bristol '
        '- EE + O2 - All Vendors - UK_Q2_2026.pptx'
    )


def test_build_scoring_report_filename_labels_unrestricted_dimensions_and_sanitizes_long_values():
    filename = build_scoring_report_filename(
        datetime(2026, 9, 30, 12, 34, 56), 'SA',
        {'Region': ['All'], 'City': [], 'Operator': [], 'Vendor': [], 'Campaign': []},
    )

    assert filename == (
        '20260930_123456 - Scoring & GAP Analysis - SA - All Regions '
        '- All Cities - All Operators - All Vendors - All Campaigns.pptx'
    )
    long_filename = build_scoring_report_filename(
        datetime(2026, 9, 30, 12, 34, 56), 'NSA',
        {field: [f'{field}/' + 'Long selection ' * 20] for field in
         ('Region', 'City', 'Operator', 'Vendor', 'Campaign')},
    )
    assert '/' not in long_filename
    assert len(long_filename.encode('utf-8')) <= 245
    assert long_filename.endswith('.pptx')
