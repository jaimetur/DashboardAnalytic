import builtins
from pathlib import Path

import pytest
import pandas as pd

from scoring_fixtures import scoring_configuration
from src.modules import scoring, scoring_config
from src.modules.repository import Repository
from src.modules.scoring_exports import export_scoring_powerpoint
from src.modules.scoring_views import build_scoring_views


def test_scoring_calculation_views_and_export_use_only_the_persisted_configuration(tmp_path, monkeypatch):
    repository = Repository(tmp_path / 'workspace.db')
    repository.initialize()
    imported_configuration = scoring_configuration()
    c10 = next(metric for metric in imported_configuration['metrics'] if metric['code'] == 'C10')
    c10['calculation']['formula'] = (
        '100 * SUM(Call_Status == "Completed" AND Disturbed_and_Impaired_Call == "Yes" '
        'AND Session_Type == "CALL") / COUNT(Call_Status)'
    )
    c31 = next(metric for metric in imported_configuration['metrics'] if metric['code'] == 'C31')
    c31['calculation']['filters'] = {
        'Type_of_Test': 'contains Successful',
        'http_Browser_Transferred_Bytes': '>= 2000000',
    }
    expected = repository.replace_scoring_configuration(imported_configuration)
    assert repository.get_scoring_configuration() == expected

    asset_path = Path(scoring_config.__file__).resolve().parents[2] / 'assets' / 'scoring' / 'netcheck_2026.json'
    original_read_text = Path.read_text
    original_path_open = Path.open
    original_builtin_open = builtins.open

    def is_scoring_asset(path):
        try:
            return Path(path).resolve() == asset_path
        except (TypeError, OSError):
            return False

    def reject_scoring_asset_reads(path, *args, **kwargs):
        if is_scoring_asset(path):
            raise AssertionError('Runtime scoring attempted to read the reference JSON asset.')
        return original_read_text(path, *args, **kwargs)

    def reject_scoring_asset_path_open(path, *args, **kwargs):
        if is_scoring_asset(path):
            raise AssertionError('Runtime scoring attempted to open the reference JSON asset.')
        return original_path_open(path, *args, **kwargs)

    def reject_scoring_asset_builtin_open(path, *args, **kwargs):
        if is_scoring_asset(path):
            raise AssertionError('Runtime scoring attempted to open the reference JSON asset.')
        return original_builtin_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', reject_scoring_asset_reads)
    monkeypatch.setattr(Path, 'open', reject_scoring_asset_path_open)
    monkeypatch.setattr(builtins, 'open', reject_scoring_asset_builtin_open)

    configuration = repository.get_scoring_configuration()
    frames = {
        'data': pd.DataFrame({
            'Operator': ['EE'] * 4,
            'Campaign': ['2026-Q2'] * 4,
            'G_Level_1': ['Drive'] * 4,
            'G_Level_2': ['City'] * 4,
            'Test_Name': ['HTTP Download'] * 4,
            'Test_Result': ['Completed'] * 4,
            'Type_of_Test': [
                'Successful httpBrowser', 'Successful httpBrowser',
                'httpBrowser', 'Successful VideoStreaming',
            ],
            'http_Browser_Transferred_Bytes': [2_500_000, 1_500_000, 3_000_000, 4_000_000],
            'http_Browser_1MB_Reached_Duration': [1_000, 500, 600, 3_000],
        }),
        'voice': pd.DataFrame({
            'Operator': ['EE'] * 4,
            'Campaign': ['2026-Q2'] * 4,
            'G_Level_1': ['Drive'] * 4,
            'G_Level_2': ['City'] * 4,
            'Session_Type': ['CALL', 'MultiRAB CALL', 'CALL', 'CALL'],
            'Call_Status': ['Completed', 'Completed', 'Completed', 'Dropped'],
            'Call_Setup_Time': [2.0, 3.0, 4.0, 12.0],
            'Disturbed_and_Impaired_Call': ['Yes', 'Yes', 'No', 'Yes'],
            'Test_Status': ['Completed'] * 4,
        }),
    }
    result = scoring.calculate_scoring(frames, configuration=configuration)
    assert result['configuration'] == configuration
    assert scoring.method_version_for_configuration(configuration).startswith(f"{configuration['version']}-")
    c31_result = next(row for row in result['scoring'] if row['kpi_code'] == 'C31')
    assert c31_result['value'] == pytest.approx(2_000)
    c10_result = next(row for row in result['scoring'] if row['kpi_code'] == 'C10')
    assert c10_result['value'] == pytest.approx(25)
    assert scoring._totals([], [], configuration) == []

    views = build_scoring_views({}, result)
    assert len(views['score_tables']) == 1
    assert views['score_tables'][0]['context']['environment'] == 'DriveCity'

    template = Path(__file__).resolve().parents[1] / 'assets' / 'ppt-templates' / 'Template_CDR_analysis.pptx'
    export_result = {**result, 'scoring': [], 'totals': [], 'charts': []}
    output = export_scoring_powerpoint(
        {'configuration': configuration, 'levels': ['Operator'], 'nr_mode': 'NSA'},
        export_result, template,
    )
    assert output.startswith(b'PK')

    with pytest.raises(ValueError, match='Import a Scoring Configuration'):
        scoring.calculate_scoring({})
