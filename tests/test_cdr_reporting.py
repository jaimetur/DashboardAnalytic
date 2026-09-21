from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
import pandas as pd
import pytest
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, call, patch
from urllib.parse import urlencode
from pptx import Presentation
from pptx.dml.color import RGBColor

from src.modules.cdr_reporting import CATALOG_HEADERS, CatalogEntry, _apply_catalog_filters, _apply_catalog_grouping, _cdf_campaign_line_widths, _cdf_plot_geometry, _cdf_terminal_x_maximum, _cdf_visible_points, _draw_adjacent_stacked_bar_label, _draw_chart_legend, _draw_configured_bar_label, _draw_inside_bar_label, _draw_top_column_group_separators, _hierarchical_complete_keys, _hierarchical_unique_keys, _hierarchy_caption_spans, _hierarchy_group_colours, _hierarchy_spans, _horizontal_legend_columns, _layout_chart_frames, _legend_dimensions, _legend_labels, _named_slide_layout, _render_cdf_line, _render_failure_count, _render_failure_count_hierarchy, _render_map, _render_mean_column, _render_stacked_distribution, _render_status_100, _render_table, _resolved_legend_items, _series_colours, _series_line_dashes, _status_chart_categories, assign_cdr_vendors, catalog_chart_hover_targets, catalog_chart_payload, catalogue_csv, classify_sessions, convert_catalog_csv, ensure_vendor_group, enrich_multivendor, load_catalog_csv, normalise_operator_aliases, parse_axis_range, parse_calculated_dimensions, parse_catalog_csv, parse_catalog_filters, parse_catalog_grouping, parse_kpi_expression, parse_label_position, parse_legend_position, parse_template_boolean, prepare_catalog_chart_preview_frame, prepare_multivendor_catalog_entry, render_catalog_chart_preview, render_cdr_report, vendor_from_cells


CHART_MAPPING_ATTRS = {
    'operator_mapping_groups': [
        {'canonical': 'VF', 'aliases': ['Vodafone', 'Vodafone UK', 'VFUK'], 'position': 0, 'color': '#E15759'},
        {'canonical': '3', 'aliases': ['Three', 'Three UK', '3 UK'], 'position': 1, 'color': '#F28E2B'},
        {'canonical': 'EE', 'aliases': ['EE UK', 'Everything Everywhere'], 'position': 2, 'color': '#76B7B2'},
        {'canonical': 'O2', 'aliases': ['Telefonica', 'Telefonica O2'], 'position': 3, 'color': '#4E79A7'},
    ],
    'vendor_mapping_groups': [
        {'canonical': 'Ericsson', 'aliases': [], 'position': 0, 'color': '#2E8B57'},
        {'canonical': 'Huawei', 'aliases': [], 'position': 1, 'color': '#E15759'},
        {'canonical': 'Samsung', 'aliases': [], 'position': 2, 'color': '#7B3FB5'},
        {'canonical': 'NSN', 'aliases': [], 'position': 3, 'color': '#4E79A7'},
        {'canonical': 'Mixed Vendor', 'aliases': ['Mixed'], 'position': 4, 'color': '#D9A514'},
        {'canonical': 'Other Vendor', 'aliases': ['Other'], 'position': 5, 'color': '#D9A514'},
        {'canonical': '(blank)', 'aliases': ['Blank'], 'position': 6, 'color': '#7A8791'},
    ],
}


def chart_frame(data: dict[str, object]) -> pd.DataFrame:
    frame = pd.DataFrame(data)
    frame.attrs.update(CHART_MAPPING_ATTRS)
    return frame


def test_kpi_expression_supports_explicit_aggregation_aliases() -> None:
    assert parse_kpi_expression('COUNTD(Test_ID)') == ('Test_ID', 'countd')
    assert parse_kpi_expression('MEAN(`Mean Data Rate`)') == ('Mean Data Rate', 'mean')
    assert parse_kpi_expression('AVERAGE(Mean_Data_Rate)') == ('Mean_Data_Rate', 'mean')
    assert parse_kpi_expression('Test_ID') == ('Test_ID', None)


def test_table_payload_counts_test_ids_across_the_declared_row_hierarchy() -> None:
    frame = chart_frame({
        'Benchmark': ['UK_Q1_2026'] * 4,
        'Subscriber': ['EE'] * 4,
        'G Level 4': ['Belfast'] * 4,
        'Test Result': ['Completed'] * 4,
        'Test_ID': ['A', 'A', 'B', None],
    })
    base = dict(
        slide=3, slide_title='Validation', slide_subtitle='', layout='', chart_title='Test count',
        cdr_source='CDR-Data', chart_type='Table', legend='', filters='',
        grouping_rows='Benchmark × Subscriber × G Level 4 × Test Result',
        # A KPI accidentally repeated as a column dimension must not split its
        # own aggregation. Cell Assistance now makes the intended KPI syntax explicit.
        grouping_columns='Test_ID', legend_position='Top',
    )

    count = catalog_chart_payload(frame, CatalogEntry(kpi='COUNT(Test_ID)', **base), prefiltered=True)
    distinct = catalog_chart_payload(frame, CatalogEntry(kpi='COUNTD(Test_ID)', **base), prefiltered=True)

    assert count['headers'] == ['Benchmark', 'Subscriber', 'G Level 4', 'Test Result', 'COUNT(Test_ID)']
    assert count['rows'] == [['UK_Q1_2026', 'EE', 'Belfast', 'Completed', '3']]
    assert distinct['rows'] == [['UK_Q1_2026', 'EE', 'Belfast', 'Completed', '2']]


def test_dynamic_table_pivots_columns_and_exposes_hierarchy_metadata() -> None:
    frame = chart_frame({
        'Benchmark': ['UK_Q1_2026'] * 6,
        'Subscriber': ['EE'] * 6,
        'Test_Result': ['Completed', 'Cutoff', 'Failed', 'Completed', 'Failed', 'Completed'],
        'G_Level_4': ['Bristol', 'Bristol', 'Bristol', 'Belfast', 'Belfast', 'Belfast'],
        'Test_ID': ['A', 'B', 'C', 'D', 'E', 'F'],
    })
    entry = CatalogEntry(
        slide=3, slide_title='Validation', slide_subtitle='', layout='', chart_title='Test count',
        cdr_source='CDR-Data', kpi='COUNT(Test_ID)', chart_type='Dynamic Table', legend='Subscriber', filters='',
        grouping_rows='Benchmark × Subscriber × G Level 4 × Test_Result', grouping_columns='G Level 4',
        legend_position='',
    )

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['type'] == 'table'
    assert model['dynamic'] is True
    assert model['row_dimension_count'] == 3
    assert model['column_heading'] == 'G Level 4'
    assert model['legend']['position'] == 'top'
    assert model['headers'] == ['Benchmark', 'Subscriber', 'Test_Result', 'Belfast', 'Bristol']
    assert model['column_keys'] == [['Belfast'], ['Bristol']]
    assert model['rows'] == [
        ['UK_Q1_2026', 'EE', 'Completed', '2', '1'],
        ['UK_Q1_2026', 'EE', 'Cutoff', '', '1'],
        ['UK_Q1_2026', 'EE', 'Failed', '1', '1'],
    ]


def test_dynamic_table_uses_operator_mapping_order_by_default() -> None:
    frame = chart_frame({
        'Subscriber': ['VF_SA', 'VF_UK', 'O2', 'EE', '3'],
        'Test_Result': ['Completed'] * 5,
        'G_Level_4': ['London'] * 5,
        'Test_ID': ['A', 'B', 'C', 'D', 'E'],
    })
    frame.attrs['operator_mapping_groups'] = [
        {'canonical': '3', 'aliases': [], 'position': 0, 'color': '#F28E2B'},
        {'canonical': 'EE', 'aliases': [], 'position': 1, 'color': '#76B7B2'},
        {'canonical': 'O2', 'aliases': [], 'position': 2, 'color': '#4E79A7'},
        {'canonical': 'VF_UK', 'aliases': [], 'position': 3, 'color': '#E15759'},
        {'canonical': 'VF_SA', 'aliases': [], 'position': 4, 'color': '#8000FF'},
    ]
    entry = CatalogEntry(
        slide=3, slide_title='Validation', slide_subtitle='', layout='', chart_title='Test count',
        cdr_source='CDR-Data', kpi='COUNT(Test_ID)', chart_type='Dynamic Table', legend='', filters='',
        grouping_rows='Subscriber × Test_Result', grouping_columns='G Level 4',
        legend_position='',
    )

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert [row[0] for row in model['rows']] == ['3', 'EE', 'O2', 'VF_UK', 'VF_SA']
    column_model = catalog_chart_payload(
        frame,
        replace(entry, grouping_rows='Test_Result', grouping_columns='Subscriber'),
        prefiltered=True,
    )
    assert column_model['headers'][1:] == ['3', 'EE', 'O2', 'VF_UK', 'VF_SA']
    assert column_model['column_keys'] == [['3'], ['EE'], ['O2'], ['VF_UK'], ['VF_SA']]


def test_multivendor_dynamic_table_places_operator_only_identities_after_vendors() -> None:
    frame = chart_frame({
        'vendor': ['EE', 'O2', 'VF_SA', '3_Huawei', '3_Ericsson', 'VF_Ericsson'],
        'Test_Result': ['Completed'] * 6,
        'G_Level_4': ['London'] * 6,
        'Test_ID': ['A', 'B', 'C', 'D', 'E', 'F'],
    })
    frame.attrs['operator_mapping_groups'].append({
        'canonical': 'VF_SA', 'aliases': [], 'position': 4, 'color': '#8000FF',
    })
    frame.attrs['operator_mappings'] = {'vf': 'VF', 'vf_sa': 'VF_SA'}
    entry = CatalogEntry(
        slide=3, slide_title='Validation', slide_subtitle='', layout='', chart_title='Test count',
        cdr_source='CDR-Data', kpi='COUNT(Test_ID)', chart_type='Dynamic Table', legend='', filters='',
        grouping_rows='Vendor × Operator × Test_Result', grouping_columns='G Level 4',
        legend_position='',
    )

    model = catalog_chart_payload(frame, entry, multivendor=True, prefiltered=True)

    assert [row[:2] for row in model['rows']] == [
        ['Ericsson', 'VF'], ['Ericsson', '3'], ['Huawei', '3'],
        ['EE', 'EE'], ['O2', 'O2'], ['VF_SA', 'VF_SA'],
    ]


def test_dynamic_table_rejects_an_unreadable_number_of_pivot_columns() -> None:
    frame = chart_frame({
        'Benchmark': ['UK_Q1_2026'] * 21,
        'G_Level_4': [f'City {index}' for index in range(21)],
        'Test_ID': [f'Test {index}' for index in range(21)],
    })
    entry = CatalogEntry(
        slide=3, slide_title='Validation', slide_subtitle='', layout='', chart_title='Test count',
        cdr_source='CDR-Data', kpi='COUNT(Test_ID)', chart_type='Dynamic Table', legend='', filters='',
        grouping_rows='Benchmark', grouping_columns='G Level 4', legend_position='',
    )

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['type'] == 'empty'
    assert model['message'] == (
        'Dynamic Table has 21 distinct column values for G Level 4. '
        'Add a filter to reduce the table to 20 columns or fewer.'
    )
from src.modules.repository import Repository


def with_default_calculated_dimensions(entry: CatalogEntry) -> CatalogEntry:
    payload = json.loads((Path(__file__).parents[1] / 'assets' / 'default-calculated-dimensions.json').read_text(encoding='utf-8'))
    return replace(entry, calculated_dimensions=parse_calculated_dimensions(payload))


def wait_for_report_job(client, job_id: int) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get('/api/e2e-reporting/jobs')
        assert response.status_code == 200
        job = next(item for item in response.json()['jobs'] if item['id'] == job_id)
        if job['status'] not in {'queued', 'processing'}:
            return job
        time.sleep(0.05)
    raise AssertionError(f'Report job {job_id} did not finish in time.')


def wait_for_report_chart_job(client, job_id: int) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get('/api/e2e-reporting/chart-jobs')
        assert response.status_code == 200
        job = next(item for item in response.json()['jobs'] if item['id'] == job_id)
        if job['status'] not in {'queued', 'processing'}:
            return job
        time.sleep(0.05)
    raise AssertionError(f'Report Charts job {job_id} did not finish in time.')


def test_vendor_formula_keeps_vodafone_ericsson_null_exception_as_mixed() -> None:
    lookup = {'first': 'Ericsson'}

    assert vendor_from_cells('Vodafone UK', 'first -> unknown', lookup) == 'Vodafone_Mixed Vendor'
    assert vendor_from_cells('Vodafone UK', 'first -> first', lookup) == 'Vodafone_Ericsson'
    assert vendor_from_cells('3', 'first -> unknown', lookup) == '3_Mixed Vendor'
    assert vendor_from_cells('O2', 'first -> unknown', lookup) == 'O2'


def test_report_operator_aliases_use_only_workspace_configuration() -> None:
    frame = chart_frame({
        "Operator": ["Vodafone", "Vodafone UK", "o2 - de", "O2(UK)", "Telefónica", "Three", "Three UK", "3 UK", "EE UK", "Everything Everywhere"],
        "Campaign": ["UK_Q4_2025", "UK_Q2_2026", "UK_Q4_2025", "UK_Q2_2026", "UK_Q2_2026", "UK_Q4_2025", "UK_Q2_2026", "UK_Q4_2025", "UK_Q2_2026", "UK_Q4_2025"],
        "Call_Status": ["Completed"] * 10,
    })
    entry = CatalogEntry(
        1, "", "", "", "", "CDR-Voice", "Call_Status", "100% Stacked Vertical Bars", "",
        "Operator IN (VF, O2, 3, EE)", "Operator", "Campaign",
    )

    normalised = normalise_operator_aliases(frame, {
        'vodafone': 'VF', 'vodafone uk': 'VF', 'o2(uk)': 'O2',
        'o2 - de': 'O2', 'telefónica': 'O2', 'three': '3', 'three uk': '3', '3 uk': '3',
        'ee uk': 'EE', 'everything everywhere': 'EE',
    })
    filtered = _apply_catalog_filters(normalised, entry, False, "Call_Status")
    grouped, primary, series = _apply_catalog_grouping(filtered, entry, False, "Call_Status")

    assert filtered["Operator"].tolist() == ["VF", "VF", "O2", "O2", "O2", "3", "3", "3", "EE", "EE"]
    assert set(grouped[primary]) == {"VF", "O2", "3", "EE"}
    assert set(grouped[series]) == {"2025-Q4", "2026-Q2"}


def test_catalog_filters_accept_case_separators_and_subscriber_spelling_alias() -> None:
    frame = chart_frame({
        'Suscriber': ['Alpha User', 'Beta User'],
        'Test_Result': ['Completed', 'Failed'],
        'Campaign': ['UK_Q3_2026', 'UK_Q4_2026'],
    })
    entry = CatalogEntry(
        slide=1, slide_title='', slide_subtitle='', layout='', chart_title='',
        cdr_source='CDR-Data', kpi='test result', chart_type='Table', legend='',
        filters='SUBSCRIBER = alpha user; test result = completed; campaign = uk_q3_2026',
        grouping_rows='', grouping_columns='',
    )

    filtered = _apply_catalog_filters(frame, entry, False, 'test result')

    assert filtered['Suscriber'].tolist() == ['Alpha User']


def test_catalog_timestamp_conditions_remain_active_when_date_range_filtering_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv('IGNORE_EVENT_TIME_FILTERING', 'true')
    frame = chart_frame({
        'Event_Start_Time': ['2026-09-01 10:00:00', '2026-09-02 10:00:00'],
        'Metric': [1, 2],
    })
    entry = CatalogEntry(
        slide=1, slide_title='', slide_subtitle='', layout='', chart_title='',
        cdr_source='CDR-Data', kpi='Metric', chart_type='Table', legend='',
        filters='Event_Start_Time = 2026-09-01 10:00:00', grouping_rows='', grouping_columns='',
    )

    filtered = _apply_catalog_filters(frame, entry, False, 'Metric')

    assert filtered['Metric'].tolist() == [1]


def test_h3g_is_not_normalised_as_operator_three() -> None:
    frame = chart_frame({"Operator": ["H3G", "H3G UK", "Three UK"]})

    assert normalise_operator_aliases(frame)["Operator"].tolist() == ["H3G", "H3G UK", "Three UK"]


def test_vendor_aliases_normalise_only_with_workspace_configuration() -> None:
    frame = chart_frame({"vendor": ["Vodafone_Ericsson", "Three UK_Nokia", "O2 (UK)_Huawei", "EE_Ericsson", "H3G_Huawei"]})

    assert normalise_operator_aliases(frame)["vendor"].tolist() == frame["vendor"].tolist()
    assert normalise_operator_aliases(frame, {
        'vodafone': 'VF', 'three uk': '3', 'o2 (uk)': 'O2', 'ee': 'EE',
    })["vendor"].tolist() == [
        "VF_Ericsson", "3_Nokia", "O2_Huawei", "EE_Ericsson", "H3G_Huawei",
    ]


def test_combined_vendor_identity_preserves_an_operator_with_an_underscore() -> None:
    frame = chart_frame({'Vendor': ['VF_SA_Ericsson', 'VF_NSA_Huawei']})
    frame.attrs['operator_mappings'] = {'vf_sa': 'VF_SA', 'vf_nsa': 'VF_NSA'}
    frame.attrs['vendor_mappings'] = {'ericsson': 'Ericsson', 'huawei': 'Huawei'}

    normalized = normalise_operator_aliases(frame)

    assert normalized['Vendor'].tolist() == ['VF_SA_Ericsson', 'VF_NSA_Huawei']


def test_vendor_legend_colours_match_the_vendor_bar_colours() -> None:
    entry = CatalogEntry(
        1, "", "", "", "", "CDR-Speech", "LQ", "Average Vertical Bars",
        "Vendor", "", "Vendor", "", "Right",
    )
    frame = chart_frame({
        "__catalog_row_0": ["VF_Ericsson", "VF_Samsung", "VF_Huawei", "3_Huawei"],
        "LQ": [4.64, 4.65, 4.64, 4.64],
    })
    frame.attrs["catalogue_dimension_labels"] = {"__catalog_row_0": "Vendor"}
    keys = [(value,) for value in frame["__catalog_row_0"]]

    legend = _resolved_legend_items(entry, frame, "LQ")

    assert {caption: colour for caption, colour, _width in legend} == {
        key[0]: colour for key, colour in _series_colours(keys, ["__catalog_row_0"], frame).items()
    }


def test_reporting_cache_resolves_separator_variants_and_refreshes_derived_dimensions(tmp_path) -> None:
    repository = Repository(tmp_path / 'workspace.db')
    repository.replace_dataset_rows(1, pd.DataFrame({
        'RAT_A': ['EN-DC'], 'G_Level_4': ['London'], 'Call Family': [None],
    }))
    repository.copy_dataset_rows_to_reporting(1, 'voice', ['RAT_A', 'G Level 4', 'Call Family'])

    # Simulate a CDR that received its derived field after its first reporting
    # copy. The cache must not retain the original null value indefinitely.
    repository.replace_dataset_rows(1, pd.DataFrame({
        'RAT_A': ['EN-DC'], 'G_Level_4': ['London'], 'Call Family': ['VoLTE'],
    }))
    repository.copy_dataset_rows_to_reporting(1, 'voice', ['RAT_A', 'G Level 4', 'Call Family'])

    loaded = repository.load_reporting_rows('voice', [1], ['G Level 4', 'Call Family'])
    assert loaded.to_dict(orient='records') == [{'G Level 4': 'London', 'Call Family': 'VoLTE'}]


def test_dataset_storage_coalesces_case_only_columns_without_sqlite_suffixes(tmp_path) -> None:
    repository = Repository(tmp_path / 'workspace.db')
    repository.replace_dataset_rows(1, pd.DataFrame({
        'Campaign': ['UK_Q3_2026'], 'campaign': ['normalized-copy'],
        'Vendor': ['source-vendor'], 'vendor': ['VF_Ericsson'],
    }))

    assert repository.list_dataset_row_columns(1) == ['Campaign', 'Vendor']
    stored = repository.load_dataset_rows(1, ['Campaign', 'Vendor'], {})
    assert stored.to_dict(orient='records') == [{'Campaign': 'UK_Q3_2026', 'Vendor': 'VF_Ericsson'}]


def test_vendor_only_removes_equivalent_operator_alias_prefixes() -> None:
    from src.modules.column_names import vendor_only_value

    assert vendor_only_value('Vodafone_Ericsson', 'Vodafone UK') == 'Ericsson'
    assert vendor_only_value('VF_Samsung', 'Vodafone UK') == 'Samsung'
    assert vendor_only_value('3_Nokia', 'Three UK') == 'Nokia'
    assert vendor_only_value('Huawei', 'Vodafone UK') == 'Huawei'


def test_reporting_cache_repairs_an_empty_requested_source_column(tmp_path) -> None:
    repository = Repository(tmp_path / 'workspace.db')
    repository.replace_dataset_rows(1, pd.DataFrame({'RAT': ['EN-DC'], 'G_Level_4': ['London']}))
    repository.copy_dataset_rows_to_reporting(1, 'data', ['RAT', 'G Level 4'])
    with repository.connection() as connection:
        connection.execute('UPDATE reporting_rows_data SET G_Level_4 = NULL WHERE dataset_id = 1')

    repository.copy_dataset_rows_to_reporting(1, 'data', ['RAT', 'G Level 4'])

    loaded = repository.load_reporting_rows('data', [1], ['G Level 4'])
    assert loaded.to_dict(orient='records') == [{'G Level 4': 'London'}]


def test_reporting_cache_checks_requested_columns_in_bounded_table_scans(tmp_path) -> None:
    class TracedRepository(Repository):
        def __init__(self, db_path: Path) -> None:
            super().__init__(db_path)
            self.statements: list[str] = []

        @contextmanager
        def connection(self):
            with super().connection() as connection:
                connection.set_trace_callback(self.statements.append)
                yield connection

    repository = TracedRepository(tmp_path / 'workspace.db')
    repository.replace_dataset_rows(1, pd.DataFrame({
        'first': ['A', 'B'], 'second': [None, None], 'third': ['C', None],
    }))
    repository.copy_dataset_rows_to_reporting(1, 'data', ['first', 'second', 'third'])
    repository.statements.clear()

    assert repository.copy_dataset_rows_to_reporting(1, 'data', ['first', 'second', 'third']) is False

    presence_queries = [
        statement for statement in repository.statements
        if statement.startswith('SELECT MAX(CASE WHEN')
    ]
    assert len(presence_queries) == 2
    assert '"first" IS NOT NULL' in presence_queries[0]
    assert '"second" IS NOT NULL' in presence_queries[0]
    assert '"third" IS NOT NULL' in presence_queries[0]
    assert 'FROM "dataset_rows_1"' in presence_queries[1]


def test_session_classification_and_multivendor_enrichment() -> None:
    cdr = pd.DataFrame({
        'Operator': ['Vodafone UK', '3'],
        'RAT_A': ['LTE EN-DC', 'NR'],
        'Cell_ID_A': ['100 -> 100', '200 -> 201'],
    })
    vodafone_mapping = pd.DataFrame({
        'source_sheet': ['4G'],
        'eNodeB ID': [0],
        'Local Cell ID': [100],
        'OP/ Vendor': ['Ericsson'],
    })
    three_mapping = pd.DataFrame({
        'Cid__ECI': [200, 201],
        'Vendor': ['Nokia', 'Ericsson'],
    })

    nsa = classify_sessions(cdr, 'nsa')
    sa = classify_sessions(cdr, 'sa')

    assert len(nsa) == 1
    assert len(sa) == 1
    assert enrich_multivendor(nsa, vodafone_mapping, three_mapping)['vendor'].tolist() == ['Vodafone_Ericsson']
    assert enrich_multivendor(sa, vodafone_mapping, three_mapping)['vendor'].tolist() == ['3_Mixed Vendor']


def test_speech_session_classification_uses_call_mode_when_sample_rat_is_blank() -> None:
    speech = pd.DataFrame({
        'sample': ['native-volte', 'native-vonr', 'whatsapp-endc', 'whatsapp-nr'],
        'Sample_RAT_A': [None, None, 'EN-DC', 'NR SA'],
        'L1_Call_Mode_A': ['VoLTE', 'VoNR', 'VoIP', 'VoIP'],
    })

    assert classify_sessions(speech, 'nsa')['sample'].tolist() == ['native-volte', 'whatsapp-endc']
    assert classify_sessions(speech, 'sa')['sample'].tolist() == ['native-vonr', 'whatsapp-nr']


def test_voice_session_classification_prioritises_call_mode_over_rat() -> None:
    voice = pd.DataFrame({
        'sample': ['volte-lte', 'multirab-volte', 'epsfb', 'vonr-endc', 'whatsapp-endc', 'whatsapp-nr'],
        'Session_Type': ['CALL', 'MultiRAB CALL', 'CALL', 'CALL', 'WhatsApp CALL', 'WhatsApp CALL'],
        'RAT_A': ['LTE', 'LTE', 'NR/LTE', 'EN-DC', 'EN-DC', 'NR'],
        'L1_Call_Mode_A': ['VoLTE', 'VoLTE', 'EPSFB', 'VoNR', 'VoIP', 'VoIP'],
    })

    assert classify_sessions(voice, 'nsa')['sample'].tolist() == [
        'volte-lte', 'multirab-volte', 'epsfb', 'whatsapp-endc',
    ]
    assert classify_sessions(voice, 'sa')['sample'].tolist() == ['vonr-endc', 'whatsapp-nr']


def test_multirab_lte_uses_nsa_fallback_when_call_mode_is_unknown() -> None:
    voice = pd.DataFrame({
        'sample': ['multirab-lte', 'native-lte'],
        'Session_Type': ['MultiRAB CALL', 'CALL'],
        'RAT_A': ['LTE', 'LTE'],
        'L1_Call_Mode_A': ['CSFB', 'CSFB'],
    })

    assert classify_sessions(voice, 'nsa')['sample'].tolist() == ['multirab-lte']
    assert classify_sessions(voice, 'sa').empty


def test_combined_reporting_frame_keeps_every_data_attempt_before_template_filters(tmp_path) -> None:
    import src.DashboardAnalytic as app_module

    repository = Repository(tmp_path / 'workspace.db')
    dataset_id = 1
    rows = pd.DataFrame({
        'source_sheet': ['EE', 'EE', 'EE', 'TMP_CLIPBOARD'],
        'Campaign': ['UK_Q2_2026'] * 4,
        'Operator': ['EE'] * 4,
        'Test_Name': ['FDFS HTTPS UL ST'] * 4,
        'Test_Result': ['Cutoff'] * 4,
        'G_Level_4': ['London'] * 4,
        'RAT': ['EN-DC', 'LTE', 'NR SA', 'EN-DC'],
    })
    repository.replace_dataset_rows(dataset_id, rows)
    entry = CatalogEntry(
        slide=5, slide_title='Data failures', slide_subtitle='', layout='', chart_title='',
        cdr_source='CDR-Data', kpi='Test_Result', chart_type='100% Stacked Vertical Bars',
        legend='Test_Result', filters=(
            'Test Name CONTAINS FDFS; Test_Result IN (Completed, Cutoff, Failed); '
            'Operator IN (Vodafone UK, 3, EE); G Level 4 IN (London)'
        ), grouping_rows='Test_Name',
        grouping_columns='Operator × Campaign', legend_position='Right',
    )

    frame = app_module._combined_reporting_frame(
        [{'id': dataset_id, 'dataset_kind': 'data'}],
        'nsa', [entry], False, repository,
    )

    assert frame['RAT'].tolist() == ['EN-DC', 'LTE', 'NR SA']
    assert frame['source_sheet'].tolist() == ['EE', 'EE', 'EE']
    preview, summary = app_module.preview_catalog_chart_data(frame, entry, limit=100)
    assert summary['matched_rows'] == 3
    assert preview['Filter · Test_Result'].tolist() == ['Cutoff', 'Cutoff', 'Cutoff']
    assert preview['Resolved Column Aggregation'].tolist() == ['EE · 2026-Q2'] * 3


def test_workspace_vendor_assignment_writes_the_normalized_vendor_field() -> None:
    cdr = pd.DataFrame({
        'Operator': ['Vodafone UK', '3', 'O2 (UK)'],
        'Cell_ID_A': ['100 -> 100', '200 -> 201', '300'],
    })
    vodafone_mapping = pd.DataFrame({
        'source_sheet': ['4G'], 'eNodeB ID': [0], 'Local Cell ID': [100], 'OP/ Vendor': ['Ericsson'],
    })
    three_mapping = pd.DataFrame({'Cid__ECI': [200, 201], 'Vendor': ['Nokia', 'Ericsson']})

    mapped = assign_cdr_vendors(cdr, vodafone_mapping, three_mapping)

    assert mapped['vendor'].tolist() == ['Vodafone_Ericsson', '3_Mixed Vendor', 'O2 (UK)']
    assert mapped.columns[:2].tolist() == ['vendor', 'Operator']


def test_workspace_vendor_assignment_replaces_source_vendor_collisions() -> None:
    cdr = pd.DataFrame({
        'source_sheet': ['Vodafone'],
        'Vendor': ['legacy source value'],
        'vendor__2': ['normalised source value'],
        'Operator': ['3'],
        'Cell_ID_A': ['200 -> 200'],
    })
    three_mapping = pd.DataFrame({'Cid__ECI': [200], 'Vendor': ['Nokia']})

    mapped = assign_cdr_vendors(cdr, None, three_mapping)

    assert mapped.columns[:2].tolist() == ['source_sheet', 'vendor']
    assert 'Vendor' not in mapped.columns
    assert 'vendor__2' not in mapped.columns
    assert mapped.loc[0, 'vendor'] == '3_Nokia'
    assert mapped.columns[1] == 'vendor'


def test_workspace_vendor_assignment_supports_a_single_selected_mapping() -> None:
    cdr = pd.DataFrame({
        'Operator': ['Vodafone UK', '3'],
        'Cell_ID_A': ['100 -> 100', '200 -> 200'],
    })
    vodafone_mapping = pd.DataFrame({
        'source_sheet': ['4G'], 'eNodeB ID': [0], 'Local Cell ID': [100], 'OP/ Vendor': ['Ericsson'],
    })

    mapped = assign_cdr_vendors(cdr, vodafone_mapping, None)

    assert mapped.loc[0, 'vendor'] == 'Vodafone_Ericsson'
    assert mapped['vendor'].tolist() == ['Vodafone_Ericsson', '3']


def test_workspace_vendor_assignment_accepts_equivalent_global_cell_id_columns() -> None:
    cdr = pd.DataFrame({
        'Operator': ['3'],
        'Global CI': ['200 -> 200'],
    })
    three_mapping = pd.DataFrame({'Cid__ECI': [200], 'Vendor': ['Nokia']})

    mapped = assign_cdr_vendors(cdr, None, three_mapping)

    assert mapped['vendor'].tolist() == ['3_Nokia']


def test_catalogue_converter_migrates_legacy_headers_and_grouping() -> None:
    legacy = (
        'Slide,Slide title,Slide subtitle,Layout,CDR Source,KPI,Chart Type,Filters,Grouping\n'
        '8,Quality,Voice,Title and 1 column + Comments,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator × Campaign\n'
    )

    converted = convert_catalog_csv(legacy, 'nsa')
    entries = parse_catalog_csv(converted, 'nsa')

    assert converted.decode('utf-8').splitlines()[0] == ','.join(CATALOG_HEADERS)
    assert entries[0].slide_title == 'Quality'
    assert entries[0].chart_title == ''
    assert entries[0].legend == ''
    assert entries[0].grouping_rows == 'Operator'
    assert entries[0].grouping_columns == 'Campaign'


def test_catalogue_converter_assigns_layouts_for_missing_legacy_layouts() -> None:
    legacy = (
        'Slide,Slide title,Slide subtitle,Layout,CDR Source,KPI,Chart Type,Filters,Grouping\n'
        '9,Quality,,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator × Campaign\n'
        '9,Quality,,,CDR-Voice,Call_Setup_Time,Average Vertical Bars,,Operator × Campaign\n'
    )

    entries = parse_catalog_csv(convert_catalog_csv(legacy, 'nsa'), 'nsa')

    assert {entry.layout for entry in entries} == {'Title and 2 columns + Comments'}


def test_vendor_group_fills_unmapped_operators_in_the_official_vendor_field() -> None:
    frame = chart_frame({'Operator': ['Vodafone UK', 'O2 (UK)'], 'vendor': ['Vodafone_Ericsson', pd.NA]})

    grouped = ensure_vendor_group(frame)

    assert grouped['vendor'].tolist() == ['Vodafone_Ericsson', 'O2 (UK)']


def test_vodafone_mapping_derives_gcid_from_4g_enodeb_and_local_cell() -> None:
    cdr = pd.DataFrame({'Operator': ['Vodafone UK'], 'Cell_IDs_A': ['3330049']})
    vodafone_mapping = pd.DataFrame({
        'source_sheet': ['4G'],
        'eNodeB ID': [13008],
        'Local Cell ID': [1],
        'OP/ Vendor': ['Samsung'],
    })
    three_mapping = pd.DataFrame({'Cid__ECI': [1], 'Vendor': ['Nokia']})

    assert enrich_multivendor(cdr, vodafone_mapping, three_mapping)['vendor'].tolist() == ['Vodafone_Samsung']


def test_catalogue_csv_requires_the_report_chart_contract_columns() -> None:
    catalogue = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,Voice quality,Title and 1 column + Comments,Completed call ratio,CDR-Voice,Call_Status,100% Stacked Vertical Bars,Call Family = VoLTE,Operator,Campaign,Completed/Dropped/Failed,\n'
    ).encode('utf-8')

    entries = parse_catalog_csv(catalogue, 'nsa')

    assert entries[0].slide == 8
    assert entries[0].slide_title == 'Completed Call Ratio'
    assert entries[0].slide_subtitle == 'Voice quality'
    assert entries[0].chart_title == 'Completed call ratio'
    assert entries[0].legend == 'Completed/Dropped/Failed'
    assert entries[0].source_kind == 'voice'
    assert entries[0].chart_type == '100% Stacked Vertical Bars'


def test_catalogue_parses_legend_position_and_accepts_prior_schema() -> None:
    current = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Quality,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,Completed/Dropped/Failed,Left\n'
    )
    entry = parse_catalog_csv(current, 'nsa')[0]

    assert entry.legend_position == 'left'
    assert parse_legend_position('Bottom') == 'bottom'
    with pytest.raises(ValueError, match='Legend Position'):
        parse_legend_position('Centre')

    previous = 'Slide,Slide tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Legend,Filters,Grouping_Rows,Grouping_Columns' + '\n8,Quality,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,,Operator,Campaign\n'
    assert parse_catalog_csv(previous, 'nsa')[0].legend_position == ''
    two_columns = ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 2 columns + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,Operator,Campaign,,\n'
    assert parse_catalog_csv(two_columns, 'nsa')[0].legend_position == ''


def test_catalogue_cdf_axis_ranges_are_optional_and_backward_compatible() -> None:
    rangeless = (
        'Slide,Slide Tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Filters,Rows Aggregation,Column Aggregation,Legend,Legend Position\n'
        '8,Quality,,Title and 1 column + Comments,Quality,CDR-Speech,LQ,CDF Line,,Operator,,,Top\n'
    )
    legacy_entry = parse_catalog_csv(rangeless, 'nsa')[0]
    assert legacy_entry.axis_x_range == ''
    assert legacy_entry.axis_y_range == ''

    current = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Speech,LQ,CDF Line,,Operator,,,Top,,"[0.01,]","[75,100]"\n'
    )
    entry = parse_catalog_csv(current, 'nsa')[0]
    assert parse_axis_range(entry.axis_x_range, 'x') == (0.01, None)
    assert parse_axis_range(entry.axis_y_range, 'y') == (75.0, 100.0)
    assert b'Label,Axis X Range,Axis Y Range' in catalogue_csv([entry])


def test_catalogue_bar_label_position_is_validated_and_serialised() -> None:
    assert parse_label_position('Middle') == 'middle'
    with pytest.raises(ValueError, match='Label'):
        parse_label_position('Centre')
    content = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Failures,,Title and 1 column + Comments,Failures,CDR-Voice,Call_Status,Count Stacked Horizontal Bars,,Operator,,,Top,Down,,\n'
    )
    entry = parse_catalog_csv(content, 'nsa')[0]
    assert entry.label_position == 'down'
    assert b',Down,,' in catalogue_csv([entry])


def test_catalogue_null_and_zero_exclusions_are_independent_and_backward_compatible() -> None:
    assert parse_template_boolean('', 'Exclude Zero') is False
    assert parse_template_boolean('Yes', 'Exclude Zero') is True
    with pytest.raises(ValueError, match='Exclude Zero'):
        parse_template_boolean('Sometimes', 'Exclude Zero')

    previous_visual_schema = (
        'Slide,Slide Tittle,Slide Subtittle,Layout,Chart Tittle,CDR source,KPI,Chart type,Filters,Rows Aggregation,Column Aggregation,Legend,Legend Position,Label,Axis X Range,Axis Y Range\n'
        '8,Quality,,Layout,Quality,CDR-Data,Metric,CDF Line,,Operator,,,Top,,,\n'
    )
    previous = parse_catalog_csv(previous_visual_schema, 'nsa')[0]
    assert previous.exclude_null_empty is False
    assert previous.exclude_zero is False

    content = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Quality,,Layout,Quality,CDR-Data,Metric,CDF Line,,Operator,,,Top,,,,Yes,Yes\n'
    )
    entry = parse_catalog_csv(content, 'nsa')[0]
    assert entry.exclude_null_empty is True
    assert entry.exclude_zero is True
    assert b'Exclude Null/Empty,Exclude Zero' in catalogue_csv([entry])


def test_null_and_zero_exclusions_filter_plotted_values_independently() -> None:
    frame = chart_frame({'Operator': ['A'] * 4, 'Metric': [None, 0.0, 1.0, 2.0]})
    base = dict(
        slide=1, slide_title='Chart', slide_subtitle='', layout='Layout', chart_title='Chart',
        cdr_source='CDR-Data', kpi='Metric', chart_type='CDF Line', legend='', filters='',
        grouping_rows='Operator', grouping_columns='',
    )

    without_nulls, _ = prepare_catalog_chart_preview_frame(
        frame, CatalogEntry(exclude_null_empty=True, **base),
    )
    without_zeroes, _ = prepare_catalog_chart_preview_frame(
        frame, CatalogEntry(exclude_zero=True, **base),
    )
    without_either, _ = prepare_catalog_chart_preview_frame(
        frame, CatalogEntry(exclude_null_empty=True, exclude_zero=True, **base),
    )

    assert without_nulls['Metric'].tolist() == [0.0, 1.0, 2.0]
    assert without_zeroes['Metric'].isna().sum() == 1
    assert without_zeroes['Metric'].dropna().tolist() == [1.0, 2.0]
    assert without_either['Metric'].tolist() == [1.0, 2.0]

    payload = catalog_chart_payload(without_either, CatalogEntry(exclude_null_empty=True, exclude_zero=True, **base), prefiltered=True)
    assert payload['series'][0]['samples'] == 2
    assert payload['domain']['x'][0] == 1.0

    scatter_frame = chart_frame({
        'Operator': ['A'] * 5,
        'Y': [10.0, 0.0, 20.0, None, 30.0],
        'X': [1.0, 2.0, 0.0, 3.0, None],
    })
    scatter = catalog_chart_payload(
        scatter_frame,
        CatalogEntry(
            slide=1, slide_title='Scatter', slide_subtitle='', layout='Layout', chart_title='Scatter',
            cdr_source='CDR-Data', kpi='Y vs X', chart_type='Scatter', legend='', filters='',
            grouping_rows='Operator', grouping_columns='', exclude_null_empty=True, exclude_zero=True,
        ),
    )
    assert scatter['series'][0]['points'] == [[1.0, 10.0]]


def test_catalogue_accepts_axis_ranges_and_labels_for_every_chart_type() -> None:
    non_cdf_range = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Data,Metric,Average Vertical Bars,,Operator,,,Top,,"[0.01,]",\n'
    )
    bar_entry = parse_catalog_csv(non_cdf_range, 'nsa')[0]
    assert bar_entry.axis_x_range == '[0.01,]'

    non_bar_label = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Data,Metric,CDF Line,,Operator,,,Top,Down,,\n'
    )
    cdf_entry = parse_catalog_csv(non_bar_label, 'nsa')[0]
    assert cdf_entry.label_position == 'down'


def test_chart_payload_applies_cdf_ranges_and_bar_label_override() -> None:
    frame = chart_frame({'Operator': ['A'] * 4, 'Metric': [0.0, 1.0, 2.0, 3.0]})
    base = dict(
        slide=1, slide_title='Chart', slide_subtitle='', layout='Layout', chart_title='Chart',
        cdr_source='CDR-Data', kpi='Metric', legend='', filters='',
        grouping_rows='Operator', grouping_columns='',
    )
    cdf = catalog_chart_payload(
        frame,
        CatalogEntry(chart_type='CDF Line', axis_x_range='[0.01,]', axis_y_range='[50,100]', **base),
        prefiltered=True,
    )
    bars = catalog_chart_payload(
        frame,
        CatalogEntry(
            chart_type='Average Vertical Bars', axis_y_range='[1,5]',
            label_position='down', **base,
        ),
        prefiltered=True,
    )

    assert cdf['domain'] == {'x': [0.01, 3.0], 'y': [0.5, 1.0]}
    assert cdf['series'][0]['x'][0] == 0.01
    assert bars['label_position'] == 'down'
    assert bars['domain']['y'] == [1.0, 5.0]
    assert bars['axis_ranges']['y'] == [1.0, 5.0]

    scatter_frame = chart_frame({
        'Operator': ['A', 'B'], 'Y': [10.0, 20.0], 'X': [1.0, 2.0],
    })
    scatter = catalog_chart_payload(
        scatter_frame,
        CatalogEntry(
            chart_type='Scatter', kpi='Y vs X', axis_x_range='[0,3]',
            axis_y_range='[5,25]', label_position='top',
            **{key: value for key, value in base.items() if key != 'kpi'},
        ),
    )
    assert scatter['domain'] == {'x': [0.0, 3.0], 'y': [5.0, 25.0]}
    assert scatter['label_position'] == 'top'


def test_cdf_visible_points_preserve_the_vertical_step_at_the_automatic_minimum() -> None:
    values = [0.0, 0.0, 0.0, 1.0]

    assert _cdf_visible_points(values, 0.0, 1.0) == [
        (0.0, 0.25), (0.0, 0.5), (0.0, 0.75), (1.0, 1.0),
    ]
    assert _cdf_visible_points(values, 0.01, 1.0) == [
        (0.01, 0.75), (1.0, 1.0),
    ]

    frame = chart_frame({'Operator': ['A'] * 4, 'Metric': values})
    payload = catalog_chart_payload(
        frame,
        CatalogEntry(
            slide=1, slide_title='CDF', slide_subtitle='', layout='Layout', chart_title='CDF',
            cdr_source='CDR-Data', kpi='Metric', chart_type='CDF Line', legend='', filters='',
            grouping_rows='Operator', grouping_columns='',
        ),
        prefiltered=True,
    )
    assert payload['domain']['x'] == [0.0, 1.0]
    assert payload['series'][0]['x'] == [0.0, 0.0, 0.0, 1.0]
    assert payload['series'][0]['y'] == [0.25, 0.5, 0.75, 1.0]


@pytest.mark.parametrize('value', ['0,1', '[,]', '[2,1]', '[nan,3]'])
def test_catalogue_rejects_invalid_axis_ranges(value: str) -> None:
    with pytest.raises(ValueError, match='Axis X Range'):
        parse_axis_range(value, 'x')


def test_legend_parser_supports_manual_captions_and_dimension_selection() -> None:
    assert _legend_labels('Completed/Dropped/Failed') == ('Completed', 'Dropped', 'Failed')
    assert _legend_dimensions('Completed/Dropped/Failed') == ()
    assert _legend_dimensions('Operator, Campaign') == ('Operator', 'Campaign')
    assert _legend_labels('Operator, Campaign') == ()


def test_resolved_legend_uses_selected_chart_field_values_and_empty_disables_it() -> None:
    frame = chart_frame({'Test_Name': ['FDFS', 'FDTT', 'FDFS'], 'Test_Result': ['Completed', 'Failed', 'Completed']})
    base = dict(
        slide=5, slide_title='', slide_subtitle='', layout='', chart_title='', cdr_source='CDR-Data',
        kpi='Test_Result', chart_type='100% Stacked Vertical Bars', filters='',
        grouping_rows='Test_Name', grouping_columns='', legend_position='top',
    )
    assert _resolved_legend_items(CatalogEntry(legend='', **base), frame, 'Test_Result') == []
    assert [item[0] for item in _resolved_legend_items(CatalogEntry(legend='Test_Name', **base), frame, 'Test_Result')] == ['FDFS', 'FDTT']


def test_resolved_filter_legend_is_text_only() -> None:
    entry = CatalogEntry(
        slide=5, slide_title='', slide_subtitle='', layout='', chart_title='', cdr_source='CDR-Data',
        kpi='Test_Result', chart_type='100% Stacked Vertical Bars', legend='Operator',
        filters='Operator IN (Vodafone UK, EE);', grouping_rows='Test_Name', grouping_columns='',
        legend_position='top',
    )
    items = _resolved_legend_items(entry, pd.DataFrame({'Test_Name': ['FDFS']}), 'Test_Result')
    assert items == [('Operator IN (Vodafone UK, EE)', '', 0)]


def test_cdf_resolved_legend_reproduces_historical_and_latest_line_widths() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['EE', 'EE'],
        '__catalog_column_0': ['2026-Q1', '2026-Q2'],
        'Campaign': ['2026-Q1', '2026-Q2'],
        'KPI': [1.0, 2.0],
    })
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': ('Operator',),
        '__catalog_column_0': ('Campaign',),
    }
    entry = CatalogEntry(
        slide=1, slide_title='', slide_subtitle='', layout='', chart_title='', cdr_source='CDR-Data',
        kpi='KPI', chart_type='CDF Lines', legend='Operator, Campaign', filters='',
        grouping_rows='Operator', grouping_columns='Campaign', legend_position='top',
    )
    items = _resolved_legend_items(entry, frame, 'KPI')
    assert [(caption, width) for caption, _colour_value, width in items] == [
        ('EE · 2026-Q1', 1), ('EE · 2026-Q2', 4),
    ]


def test_cdf_resolved_legend_decreases_four_campaign_widths_per_operator() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['EE'] * 4 + ['O2'] * 3,
        '__catalog_column_0': [
            '2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4',
            '2025-Q4', '2026-Q1', '2026-Q2',
        ],
        'Campaign': [
            '2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4',
            '2025-Q4', '2026-Q1', '2026-Q2',
        ],
        'KPI': [1.0, 2.0, 3.0, 4.0, 1.5, 2.5, 3.5],
    })
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': ('Operator',),
        '__catalog_column_0': ('Campaign',),
    }
    entry = CatalogEntry(
        slide=1, slide_title='', slide_subtitle='', layout='', chart_title='', cdr_source='CDR-Data',
        kpi='KPI', chart_type='CDF Lines', legend='Operator, Campaign', filters='',
        grouping_rows='Operator', grouping_columns='Campaign', legend_position='top',
    )

    items = _resolved_legend_items(entry, frame, 'KPI')

    assert {caption: width for caption, _colour_value, width in items} == {
        'EE · 2026-Q1': 1,
        'EE · 2026-Q2': 2,
        'EE · 2026-Q3': 3,
        'EE · 2026-Q4': 4,
        'O2 · 2025-Q4': 2,
        'O2 · 2026-Q1': 3,
        'O2 · 2026-Q2': 4,
    }


def test_interactive_cdf_model_uses_reporting_hierarchy_palette_and_legend() -> None:
    entry = CatalogEntry(
        1, 'Speech', '', '', 'POLQA CDF', 'CDR-Speech', 'LQ', 'CDF Line',
        'Vendor, Campaign', '', 'Vendor', 'Campaign', 'Right',
    )
    frame = chart_frame({
        'Vendor': ['VF_Ericsson'] * 4 + ['VF_Huawei'] * 4,
        'Campaign': ['UK_Q2_2026', 'UK_Q2_2026', 'UK_Q1_2026', 'UK_Q1_2026'] * 2,
        'LQ': [1.2, 4.2, 1.0, 4.0, 1.4, 4.4, 1.1, 4.1],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert (model['renderer'], model['type'], model['width'], model['height'], model['title']) == (
        'catalog-v2', 'cdf', 1600, 900, 'POLQA CDF',
    )
    assert [(series['key'], series['colour'], series['width'], series['dash']) for series in model['series']] == [
        (['VF_Ericsson', '2026-Q1'], '#2E8B57', 1, []),
        (['VF_Ericsson', '2026-Q2'], '#2E8B57', 4, []),
        (['VF_Huawei', '2026-Q1'], '#E15759', 1, []),
        (['VF_Huawei', '2026-Q2'], '#E15759', 4, []),
    ]
    assert model['legend'] == {
        'position': 'right',
        'line_markers': True,
        'items': [
            {'label': 'VF_Ericsson · 2026-Q1', 'colour': '#2E8B57', 'width': 1, 'dash': []},
            {'label': 'VF_Ericsson · 2026-Q2', 'colour': '#2E8B57', 'width': 4, 'dash': []},
            {'label': 'VF_Huawei · 2026-Q1', 'colour': '#E15759', 'width': 1, 'dash': []},
            {'label': 'VF_Huawei · 2026-Q2', 'colour': '#E15759', 'width': 4, 'dash': []},
        ],
    }
    assert all(series['x'] and series['y'] and series['samples'] == 2 for series in model['series'])


def test_interactive_cdf_model_uses_progressive_campaign_widths() -> None:
    entry = CatalogEntry(
        1, 'Data', '', '', 'Rate CDF', 'CDR-Data', 'Rate', 'CDF Line',
        'Operator, Campaign', '', 'Operator', 'Campaign', 'Top',
    )
    campaigns = ['2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4']
    frame = chart_frame({
        'Operator': ['EE'] * 8,
        'Campaign': [campaign for campaign in campaigns for _ in range(2)],
        'Rate': [1.0, 2.0, 1.1, 2.1, 1.2, 2.2, 1.3, 2.3],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert [series['width'] for series in model['series']] == [1, 2, 3, 4]
    assert [item['width'] for item in model['legend']['items']] == [1, 2, 3, 4]


def test_multi_cdf_payload_bounds_high_cardinality_identifier_groups() -> None:
    entries = 250
    entry = CatalogEntry(
        1, 'Interactivity score', '', '', 'Interactivity score', 'CDR-Data',
        'Twamp Interactivity Score | Packet Delay Variation Score | Packet Loss Score',
        'Multi KPI CDF Lines', 'Operator', '',
        'Test Info × Test_Name × Latency Score × Operator', '', 'Right',
    )
    frame = chart_frame({
        'Test_Info': [f'test-{index}' for index in range(entries)],
        'Test_Name': ['Interactivity'] * entries,
        'Latency_Score': [str(index % 4) for index in range(entries)],
        'Operator': ['EE' if index % 2 else 'VF' for index in range(entries)],
        'Twamp_Interactivity_Score': list(range(entries)),
        'Packet_Delay_Variation_Score': list(range(entries)),
        'Packet_Loss_Score': list(range(entries)),
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['type'] == 'multi_cdf'
    assert model['legend']['items'] == []
    assert all(len(panel['series']) <= 120 for panel in model['panels'])
    assert all({series['key'][-1] for series in panel['series']} == {'EE', 'VF'} for panel in model['panels'])


def test_multivendor_cdf_legend_keeps_operator_and_vendor_for_each_curve() -> None:
    entry = CatalogEntry(
        1, 'Speech', '', '', 'Interactivity', 'CDR-Speech', 'LQ', 'CDF Line',
        'Operator', '', 'Operator', 'Campaign', 'Bottom',
    )
    frame = chart_frame({
        'vendor': ['VF_Ericsson'] * 3 + ['VF_Huawei'] * 3 + ['3_Ericsson'] * 3,
        'Campaign': ['2026 Q1'] * 9,
        'LQ': [1.0, 2.0, 3.0] * 3,
    })

    model = catalog_chart_payload(frame, entry, multivendor=True, prefiltered=True)

    labels = [item['label'] for item in model['legend']['items']]
    assert labels == ['Ericsson · VF · 2026-Q1', 'Ericsson · 3 · 2026-Q1', 'Huawei · VF · 2026-Q1']
    assert [series['name'] for series in model['series']] == [
        'Ericsson · VF · 2026-Q1', 'Ericsson · 3 · 2026-Q1', 'Huawei · VF · 2026-Q1',
    ]
    assert [item['colour'] for item in model['legend']['items']] == ['#2E8B57', '#2E8B57', '#E15759']
    assert [item['dash'] for item in model['legend']['items']] == [[], [18, 8], []]


def test_interactive_status_model_preserves_reporting_row_and_column_aggregation() -> None:
    entry = CatalogEntry(
        1, 'Voice', '', '', 'Completed Ratio', 'CDR-Voice', 'Test_Result',
        '100% Stacked Vertical Bars', 'Test_Result', '', 'Call Family',
        'Operator × Campaign', 'Right',
    )
    entry = replace(entry, axis_y_range='[25,75]', label_position='middle')
    frame = chart_frame({
        'Call Family': ['VoLTE'] * 8,
        'Operator': ['VF'] * 4 + ['3'] * 4,
        'Campaign': ['UK_Q2_2026', 'UK_Q2_2026', 'UK_Q1_2026', 'UK_Q1_2026'] * 2,
        'Test_Result': [
            'Completed', 'Failed', 'Completed', 'Completed',
            'Failed', 'Failed', 'Completed', 'Failed',
        ],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert (model['type'], model['mode'], model['row_keys']) == ('status_100', 'hierarchy', [['VoLTE']])
    assert model['domain']['y'] == [.25, .75]
    assert model['label_position'] == 'middle'
    assert model['column_keys'] == [
        ['VF', '2026-Q1'], ['VF', '2026-Q2'],
        ['3', '2026-Q1'], ['3', '2026-Q2'],
    ]
    assert model['cells'][0] == [
        pytest.approx([1.0, 0.0]), pytest.approx([0.5, 0.5]),
        pytest.approx([0.5, 0.5]), pytest.approx([0.0, 1.0]),
    ]
    assert model['states'] == [
        {'name': 'Completed', 'colour': '#2C9A62'},
        {'name': 'Failed', 'colour': '#C83E4D'},
    ]
    assert model['legend']['items'] == [
        {'label': 'Completed', 'colour': '#2C9A62', 'width': 2},
        {'label': 'Failed', 'colour': '#C83E4D', 'width': 2},
    ]


def test_interactive_status_model_preserves_sql_aggregated_row_weights() -> None:
    entry = CatalogEntry(
        1, 'Data', '', '', 'Completed Ratio', 'CDR-Data', 'Test_Result',
        '100% Stacked Vertical Bars', 'Test_Result', '', 'Type_of_Test',
        'Operator × Campaign', 'Right',
    )
    frame = chart_frame({
        'Type_of_Test': ['Browsing'] * 6,
        'Operator': ['VF'] * 3 + ['3'] * 3,
        'Campaign': ['2026 Q1'] * 2 + ['2026 Q2'] + ['2026 Q1'] + ['2026 Q2'] * 2,
        'Test_Result': ['Completed', 'Failed', 'Completed', 'Failed', 'Completed', 'Completed'],
    })
    weighted = (
        frame.groupby(
            ['Type_of_Test', 'Operator', 'Campaign', 'Test_Result'],
            sort=False,
            dropna=False,
        )
        .size()
        .rename('__catalog_weight')
        .reset_index()
    )
    weighted.attrs.update(CHART_MAPPING_ATTRS)

    expanded_model = catalog_chart_payload(frame, entry, prefiltered=True)
    weighted_model = catalog_chart_payload(weighted, entry, prefiltered=True)

    assert weighted_model == expanded_model


def test_interactive_status_legend_uses_the_colours_of_its_plotted_states() -> None:
    entry = CatalogEntry(
        1, 'Voice', '', '', 'Failed ratio', 'CDR-Voice', 'Test_Result',
        '100% Stacked Vertical Bars', 'Operator', '', 'Test Name', 'Operator', 'Right',
    )
    frame = chart_frame({
        'Test Name': ['httpBrowser', 'httpBrowser', 'VideoStreaming', 'VideoStreaming'],
        'Operator': ['O2', 'O2', 'VF', 'VF'],
        'Test_Result': ['Completed', 'Failed', 'Completed', 'Failed'],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['legend']['items'] == [
        {'label': state['name'], 'colour': state['colour'], 'width': 2}
        for state in model['states']
    ]


def test_interactive_distribution_model_uses_reporting_buckets_and_nested_keys() -> None:
    entry = CatalogEntry(
        1, 'Data', '', '', 'Rate distribution', 'CDR-Data', 'Mean_Data_Rate',
        'Distribution Stacked Vertical Bars', 'Buckets', 'Buckets = 1,5,20;',
        'Operator', 'Campaign × Rate Bucket', 'Bottom',
    )
    entry = replace(entry, axis_y_range='[10,90]', label_position='down')
    frame = chart_frame({
        'Operator': ['VF'] * 4 + ['3'] * 4,
        'Campaign': ['UK_Q2_2026', 'UK_Q2_2026', 'UK_Q1_2026', 'UK_Q1_2026'] * 2,
        'Mean_Data_Rate': [2, 25, .5, 7, 2, 2, .2, 25],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['type'] == 'distribution'
    assert model['domain']['y'] == [.1, .9]
    assert model['label_position'] == 'down'
    assert model['keys'] == [
        ['VF', '2026-Q1'], ['VF', '2026-Q2'],
        ['3', '2026-Q1'], ['3', '2026-Q2'],
    ]
    assert [bucket['name'] for bucket in model['buckets']] == ['<1', '5-20', '1-5', '20+']
    assert model['cells'] == [
        pytest.approx([.5, .5, 0, 0]), pytest.approx([0, 0, .5, .5]),
        pytest.approx([.5, 0, 0, .5]), pytest.approx([0, 0, 1, 0]),
    ]
    assert model['legend']['position'] == 'bottom'
    assert [item['label'] for item in model['legend']['items']] == ['<1', '5-20', '1-5', '20+']
    assert [item['colour'] for item in model['legend']['items']] == [
        bucket['colour'] for bucket in model['buckets']
    ]


def test_distribution_upper_bound_buckets_match_tableau_formula_and_palette() -> None:
    entry = CatalogEntry(
        1, 'FDTT DL', '', '', 'FDTT http DL MT', 'CDR-Data', 'Mean_Data_Rate',
        'Distribution Stacked Vertical Bars', 'Buckets', 'Buckets < 2,5,20,100;',
        'Operator', 'Campaign × Rate Bucket', 'Right',
    )
    frame = chart_frame({
        'Operator': ['EE'] * 6,
        'Campaign': ['UK_Q2_2026'] * 6,
        'Mean_Data_Rate': [.5, 2, 5, 20, 100, 101],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert [bucket['name'] for bucket in model['buckets']] == [
        'Above', 'below100', 'below20', 'below5', 'below2',
    ]
    assert [bucket['colour'] for bucket in model['buckets']] == [
        '#4E79A7', '#76B7B2', '#E15759', '#F28E2B', '#FF9DA7',
    ]
    assert model['cells'] == [pytest.approx([.2, .2, .2, .2, .2])]
    assert model['legend']['items'] == [
        {'label': 'below2', 'colour': '#FF9DA7', 'width': 2},
        {'label': 'below5', 'colour': '#F28E2B', 'width': 2},
        {'label': 'below20', 'colour': '#E15759', 'width': 2},
        {'label': 'below100', 'colour': '#76B7B2', 'width': 2},
        {'label': 'Above', 'colour': '#4E79A7', 'width': 2},
    ]


def test_distribution_inclusive_upper_bound_buckets_are_supported() -> None:
    entry = CatalogEntry(
        1, 'Custom', '', '', 'Custom distribution', 'CDR-Data', 'Rate',
        'Distribution Stacked Vertical Bars', 'Buckets', 'Buckets <= 1,3,10,20;',
        'Operator', 'Campaign × Rate Bucket', 'Right',
    )
    frame = chart_frame({
        'Operator': ['EE'] * 5,
        'Campaign': ['2026-Q2'] * 5,
        'Rate': [1, 3, 10, 20, 21],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert [bucket['name'] for bucket in model['buckets']] == [
        'Above', 'below20', 'below10', 'below3', 'below1',
    ]
    assert model['cells'] == [pytest.approx([.2, .2, .2, .2, .2])]


def test_static_distribution_draws_horizontal_white_percentage_labels_inside_segments() -> None:
    frame = chart_frame({
        'Operator': ['EE'] * 10,
        'Campaign': ['2026-Q2'] * 10,
        '__catalog_stack': ['Above'] * 8 + ['below100'] * 2,
    })
    frame.attrs['catalogue_distribution_buckets'] = [
        'below2', 'below5', 'below20', 'below100', 'Above',
    ]

    with patch('src.modules.cdr_reporting._draw_inside_bar_label') as draw_label:
        _render_stacked_distribution(
            'Distribution', frame, 'Operator', 'Campaign', '__catalog_stack',
        )

    assert [item.args[2] for item in draw_label.call_args_list] == ['80.0%', '20.0%']
    assert {item.kwargs['fill'] for item in draw_label.call_args_list} == {'#FFFFFF'}
    assert {item.kwargs['font'].size for item in draw_label.call_args_list} == {17}


def test_interactive_mean_model_uses_reporting_aggregation_and_vendor_palette() -> None:
    entry = CatalogEntry(
        1, 'Speech', '', '', 'Average POLQA', 'CDR-Speech', 'LQ',
        'Average Vertical Bars', 'Vendor', '', 'Vendor', 'Campaign', 'Right',
    )
    frame = chart_frame({
        'Vendor': ['VF_Ericsson'] * 4 + ['VF_Huawei'] * 4,
        'Campaign': ['UK_Q2_2026', 'UK_Q2_2026', 'UK_Q1_2026', 'UK_Q1_2026'] * 2,
        'LQ': [4.0, 4.4, 3.8, 4.0, 3.0, 3.4, 2.8, 3.0],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['type'] == 'mean_bar'
    assert [(bar['key'], bar['value'], bar['colour']) for bar in model['bars']] == [
        (['VF_Ericsson', '2026-Q1'], pytest.approx(3.9), '#2E8B57'),
        (['VF_Ericsson', '2026-Q2'], pytest.approx(4.2), '#2E8B57'),
        (['VF_Huawei', '2026-Q1'], pytest.approx(2.9), '#E15759'),
        (['VF_Huawei', '2026-Q2'], pytest.approx(3.2), '#E15759'),
    ]
    assert [(item['label'], item['colour']) for item in model['legend']['items']] == [
        ('VF_Ericsson', '#2E8B57'), ('VF_Huawei', '#E15759'),
    ]


def test_interactive_mean_model_nests_column_only_hierarchies_by_parent() -> None:
    entry = CatalogEntry(
        1, 'Speech', '', '', 'Average POLQA', 'CDR-Speech', 'LQ',
        'Average Vertical Bars', 'Vendor', '', '', 'Operator × Campaign', 'Right',
    )
    frame = chart_frame({
        # This is the natural order after appending one CDR per campaign.
        'Operator': ['VF', '3', 'EE', 'VF', '3', 'EE'],
        'Campaign': ['UK_Q1_2026'] * 3 + ['UK_Q2_2026'] * 3,
        'LQ': [4.0, 3.8, 4.2, 4.1, 3.9, 4.3],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['mode'] == 'hierarchy'
    assert model['row_keys'] == [[]]
    assert model['column_keys'] == [
        ['VF', '2026-Q1'], ['VF', '2026-Q2'],
        ['3', '2026-Q1'], ['3', '2026-Q2'],
        ['EE', '2026-Q1'], ['EE', '2026-Q2'],
    ]
    assert model['cell_colours'] == [[
        '#E15759', '#E15759',
        '#F28E2B', '#F28E2B',
        '#76B7B2', '#76B7B2',
    ]]
    filtered_entry = replace(entry, filters='Operator IN (VF, 3, EE)')
    filtered = _apply_catalog_filters(frame, filtered_entry, False, 'LQ')
    filtered_model = catalog_chart_payload(filtered, filtered_entry, prefiltered=True)
    assert filtered_model['column_keys'] == model['column_keys']
    assert filtered_model['cell_colours'] == model['cell_colours']


def test_bar_value_label_rotates_when_it_only_fits_vertically() -> None:
    image = Image.new('RGB', (200, 200), 'white')
    draw = ImageDraw.Draw(image)

    with patch('src.modules.cdr_reporting._draw_vertical_label') as draw_vertical:
        drawn = _draw_inside_bar_label(
            image, draw, '104.62', x=20, y=20, width=30, height=150,
            fill='white', font=ImageFont.load_default(),
        )

    assert drawn is True
    draw_vertical.assert_called_once()


def test_configured_vertical_bar_label_rotates_when_many_bars_make_it_too_wide() -> None:
    image = Image.new('RGB', (200, 200), 'white')
    draw = ImageDraw.Draw(image)

    with patch('src.modules.cdr_reporting._draw_vertical_label') as draw_vertical:
        _draw_configured_bar_label(
            image, draw, '104.62', x=20, y=20, width=30, height=150,
            colour='#4E79A7', font=ImageFont.load_default(), position='middle',
            horizontal=False, automatic=lambda: None,
        )

    draw_vertical.assert_called_once()


def test_tiny_stacked_label_uses_clear_space_beside_its_bar() -> None:
    draw = MagicMock()
    draw.textbbox.return_value = (0, 0, 28, 12)

    drawn = _draw_adjacent_stacked_bar_label(
        draw, '0.6%', x=100, y=20, width=80, height=2,
        bar_top=20, bar_bottom=180, side_space=40, fill='#C83E4D', font=ImageFont.load_default(),
    )

    assert drawn is True
    draw.rectangle.assert_not_called()
    assert draw.text.call_args.args[0][0] == pytest.approx(184)
    assert draw.text.call_args.kwargs['fill'] == '#C83E4D'


def test_tiny_stacked_label_is_hidden_without_lateral_space() -> None:
    draw = MagicMock()
    draw.textbbox.return_value = (0, 0, 28, 12)

    drawn = _draw_adjacent_stacked_bar_label(
        draw, '0.6%', x=100, y=20, width=80, height=2,
        bar_top=20, bar_bottom=180, side_space=5, fill='#C83E4D',
        font=ImageFont.load_default(),
    )

    assert drawn is False
    draw.text.assert_not_called()


def test_top_column_group_separator_is_solid_from_the_header_to_the_plot() -> None:
    draw = MagicMock()

    _draw_top_column_group_separators(
        draw,
        [('VF', '2026-Q1'), ('VF', '2026-Q2'), ('3', '2026-Q1')],
        ['__catalog_column_0', '__catalog_column_1'],
        left=155, width=1165, top=280, bottom=680,
    )

    assert call((155 + 2 * 1165 / 3, 212, 155 + 2 * 1165 / 3, 680), fill='#AEBBC4', width=2) in draw.line.call_args_list
    assert call((155 + 1165 / 3, 242, 155 + 1165 / 3, 250), fill='#AEBBC4', width=1) in draw.line.call_args_list


def test_nested_column_group_separator_is_dashed_below_its_parent_header() -> None:
    draw = MagicMock()

    _draw_top_column_group_separators(
        draw,
        [('VF', 'Ericsson', '2026-Q1'), ('VF', 'Ericsson', '2026-Q2')],
        ['__catalog_row_0', '__catalog_row_1', '__catalog_column_0'],
        left=155, width=1165, top=280, bottom=680,
    )

    assert draw.line.call_args_list[0] == call.line((155 + 1165 / 2, 242, 155 + 1165 / 2, 250), fill='#AEBBC4', width=1)
    assert all(item.kwargs.get('width') == 1 for item in draw.line.call_args_list)


def test_interactive_failure_model_matches_reporting_legend_plot_geometry() -> None:
    entry = CatalogEntry(
        1, 'Failures', '', '', 'Voice failures', 'CDR-Voice', 'Call_Status',
        'Count Stacked Horizontal Bars', 'Call_Status', '', 'Call Family',
        'Operator × Campaign', 'Right',
    )
    entry = replace(entry, axis_x_range='[0,4]', label_position='top')
    frame = chart_frame({
        'Call Family': ['VoLTE', 'VoLTE', 'MultiRAB'],
        'Operator': ['VF', 'VF', '3'],
        'Campaign': ['2026 Q1', '2026 Q2', '2026 Q2'],
        'Call_Status': ['Failed', 'Dropped', 'Completed'],
    })

    field_legend = catalog_chart_payload(frame, entry, prefiltered=True)
    manual_legend = catalog_chart_payload(
        frame, replace(entry, legend='Failed/Dropped'), prefiltered=True,
    )

    assert field_legend['type'] == manual_legend['type'] == 'failure_count'
    assert field_legend['domain']['x'] == [0.0, 4.0]
    assert field_legend['label_position'] == 'top'
    assert field_legend['plot_legend_position'] == 'none'
    assert manual_legend['plot_legend_position'] == 'right'
    assert [state['name'] for state in manual_legend['states']] == ['Failed', 'Dropped']


def test_interactive_map_model_preserves_operator_colours_and_osm_geometry() -> None:
    entry = CatalogEntry(
        1, 'Map', '', '', 'Coverage', 'CDR-Data', 'Latitude vs Longitude',
        'Map', 'Operator', '', 'Operator', 'Campaign', 'Right',
    )
    entry = replace(entry, axis_x_range='[-2,0]', axis_y_range='[50,55]', label_position='up')
    frame = chart_frame({
        'Latitude': [51.5, 51.51, 53.8],
        'Longitude': [-.12, -.11, -1.55],
        'Operator': ['VF', 'VF', '3'],
        'Campaign': ['2026 Q2'] * 3,
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert model['type'] == 'map'
    assert model['domain'] == {'x': [-2.0, 0.0], 'y': [50.0, 55.0]}
    assert model['label_position'] == 'up'
    assert [(series['name'], series['colour'], len(series['points'])) for series in model['series']] == [
        ('VF', '#E15759', 2), ('3', '#F28E2B', 1),
    ]
    assert model['basemap']['provider'] == 'OpenStreetMap'
    tile_left, tile_top, tile_right, tile_bottom = model['basemap']['tile_range']
    assert (tile_right - tile_left + 1) * (tile_bottom - tile_top + 1) <= 48
    assert len(model['basemap']['world_bounds']) == 4


def test_interactive_map_keeps_manual_legend_labels_only_when_they_cover_every_series() -> None:
    entry = CatalogEntry(
        1, 'Map', '', '', 'Coverage', 'CDR-Data', 'Latitude vs Longitude',
        'Map', 'Success/Failure', '', 'Operator', '', 'Right',
    )
    frame = chart_frame({
        'Latitude': [51.5, 51.51, 53.8],
        'Longitude': [-.12, -.11, -1.55],
        'Operator': ['VF', '3', 'EE'],
    })

    model = catalog_chart_payload(frame, entry, prefiltered=True)

    assert [(item['label'], item['colour']) for item in model['legend']['items']] == [
        (series['name'], series['colour']) for series in model['series']
    ]


def test_cdf_plot_reserves_space_for_side_legends() -> None:
    left, _top, width, _height = _cdf_plot_geometry('right')
    assert left + width < 1320
    left, _top, width, _height = _cdf_plot_geometry('left')
    assert left >= 400
    assert _cdf_plot_geometry('top') == (100, 135, 1320, 590)


def test_threshold_legend_uses_the_resolved_value_and_chart_segment_colours() -> None:
    entry = CatalogEntry(
        slide=8, slide_title='', slide_subtitle='', layout='', chart_title='POLQA <1.6',
        cdr_source='CDR-Speech', kpi='POLQA < 1.6 vs >= 1.6',
        chart_type='Threshold Stacked Vertical Bars', legend='Threshold', filters='',
        grouping_rows='Operator', grouping_columns='Campaign', legend_position='bottom',
    )
    assert _resolved_legend_items(entry, pd.DataFrame({'POLQA': [1.2, 2.1]}), 'POLQA') == [
        ('< 1.6', '#E15759', 2),
        ('≥ 1.6', '#59A14F', 2),
    ]


def test_distribution_bucket_legend_uses_resolved_bucket_colours_not_filter_text() -> None:
    frame = chart_frame({
        '__catalog_stack': ['20-100', '100+', '5-20', '1-5', '<1', '20-100'],
    })
    entry = CatalogEntry(
        slide=10, slide_title='', slide_subtitle='', layout='', chart_title='FDTT DL (7s)',
        cdr_source='CDR-Data', kpi='FDTT_Sustainable_MDR',
        chart_type='Distribution Stacked Vertical Bars', legend='Buckets',
        filters='Buckets = 1,5,20,100;', grouping_rows='Operator',
        grouping_columns='Campaign x Rate Bucket', legend_position='bottom',
    )
    items = _resolved_legend_items(entry, frame, 'FDTT_Sustainable_MDR')
    assert [caption for caption, _colour_value, _width in items] == ['20-100', '100+', '5-20', '1-5', '<1']
    assert all(colour for _caption, colour, _width in items)


def test_mean_chart_renders_selected_dimension_legend_at_requested_position() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['VF', '3'], '__catalog_column_0': ['2026-Q2', '2026-Q2'],
        'Metric': [1.0, 2.0], '__catalog_primary': ['VF', '3'], '__catalog_series': ['2026-Q2', '2026-Q2'],
    })
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': 'Operator', '__catalog_column_0': 'Campaign',
    }

    with patch('src.modules.cdr_reporting._draw_chart_legend') as draw_legend:
        _render_mean_column(
            'Average', frame, '__catalog_primary', '__catalog_series', 'Metric',
            legend_dimensions=('Operator',), legend_position='right',
        )

    assert {item[0] for item in draw_legend.call_args.args[1]} == {'VF', '3'}
    assert draw_legend.call_args.args[2] == 'right'


def test_status_chart_draws_legend_at_the_catalogue_position() -> None:
    frame = chart_frame({
        'Operator': ['Vodafone'],
        'Campaign': ['2026 Q1'],
        'Call_Status': ['Completed'],
    })

    with patch('src.modules.cdr_reporting._draw_chart_legend') as draw_legend:
        _render_status_100('Status', frame, 'Operator', 'Campaign', legend_position='left')

    assert draw_legend.call_args.args[2] == 'left'


def test_chart_legend_normalises_title_case_position_from_interactive_preview() -> None:
    draw = MagicMock()

    _draw_chart_legend(draw, [('VF', '#E60000', 1)], 'Left')

    assert draw.rectangle.call_args.args[0][0] == 26


def test_catalogue_accepts_structural_slides_and_rejects_chart_configuration_on_them() -> None:
    title = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n1,Quarterly report,NSA analysis,Title Page,,,,Title Slide,,,,,\n',
        'nsa',
    )[0]
    transition = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n2,Voice analysis,Seven cities,Title Only,,,,Transition Slide,,,,,\n',
        'nsa',
    )[0]

    assert title.structural_type == 'title slide'
    assert transition.structural_type == 'transition slide'
    with pytest.raises(ValueError, match='cannot define chart, CDR, KPI'):
        parse_catalog_csv(
            ','.join(CATALOG_HEADERS) + '\n1,Quarterly report,,Title Page,,CDR-Data,LQ,Title Slide,,,,,\n',
            'nsa',
        )


def test_catalogue_filter_and_grouping_contract_is_parsed_and_applied() -> None:
    conditions = parse_catalog_filters('Session_Type IN (VoLTE, MultiRAB); LQ >= 1.6')
    grouping = parse_catalog_grouping('City × Operator × Campaign')
    assert [(item.column, item.operator, item.values) for item in conditions] == [
        ('Session_Type', 'IN', ('VoLTE', 'MultiRAB')), ('LQ', '>=', ('1.6',)),
    ]
    assert grouping.dimensions == ('City', 'Operator', 'Campaign')
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,Quality by city,CDR-Speech,LQ,Average Vertical Bars,Session_Type IN (VoLTE); LQ >= 1.6,City,Operator × Campaign,,\n',
        'nsa',
    )[0]
    frame = chart_frame({
        'Session_Type': ['VoLTE', 'WhatsApp'], 'LQ': [3.2, 4.0], 'City': ['London', 'Leeds'],
        'Operator': ['EE', 'O2'], 'Campaign': ['Q1', 'Q1'],
    })
    filtered = _apply_catalog_filters(frame, entry, False, 'LQ')
    grouped, primary, series = _apply_catalog_grouping(filtered, entry, False, 'LQ')
    assert len(grouped) == 1
    assert grouped[primary].tolist() == ['London']
    assert grouped[series].tolist() == ['EE · Q1']
    assert '__catalog_stack' not in grouped.columns


def test_catalogue_filters_accept_lines_but_reject_a_missing_condition_separator() -> None:
    conditions = parse_catalog_filters('Test Name CONTAINS FDFS\nTest_Result IN (Completed, Dropped, Failed)')
    assert [condition.column for condition in conditions] == ['Test Name', 'Test_Result']

    malformed = (
        'Test Name CONTAINS FDFS;'
        'Test_Result IN (Completed, Dropped, Failed)Operator IN (Vodafone UK, 3, EE);'
        'G Level 4 IN (Belfast, Bristol, Cardiff, Edinburgh, London, Leeds, Sheffield);'
    )
    with pytest.raises(ValueError, match='semicolon is required'):
        parse_catalog_filters(malformed)

    row = ','.join(CATALOG_HEADERS) + (
        '\n5,Failures,,Title and 1 column + Comments,Failures,CDR-Data,Test_Result,'
        '100% Stacked Vertical Bars,"Test_Result IN (Completed, Dropped, Failed)Operator IN (EE, 3)",'
        'Operator,Campaign,,Top\n'
    )
    with pytest.raises(ValueError, match=r'Slide: 5 - Chart: 1 ->.*semicolon is required'):
        parse_catalog_csv(row, 'nsa')
    editable = parse_catalog_csv(row, 'nsa', validate_filters=False)
    assert editable[0].filters.endswith('Operator IN (EE, 3)')


def test_multivendor_rendering_rewrites_display_and_grouping_and_excludes_unresolved_vendors() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n8,Operator comparison,Operator subtitle,Title and 1 column + Comments,Operator chart,CDR-Speech,LQ,Average Vertical Bars,Operator = Vodafone UK,Operator,Operator × Campaign,Operator,\n',
        'nsa',
    )[0]
    rendered = prepare_multivendor_catalog_entry(entry)

    assert rendered.slide_title == 'Vendor comparison'
    assert rendered.slide_subtitle == 'Vendor subtitle'
    assert rendered.chart_title == 'Vendor chart'
    assert rendered.legend == 'Vendor, Operator'
    assert rendered.grouping_rows == 'Vendor × Operator'
    assert rendered.grouping_columns == 'Vendor × Operator × Campaign'
    assert rendered.filters == 'Operator = Vodafone UK; vendor NOT CONTAINS (Mixed, Other)'

    frame = chart_frame({
        'Operator': ['Vodafone UK', 'Vodafone UK', '3'],
        'vendor': ['Vodafone_Ericsson', 'Vodafone_Mixed Vendor', '3_Nokia'],
        'Campaign': ['UK_Q2_SA_2026', 'UK_Q2_SA_2026', 'UK_Q2_SA_2026'],
        'LQ': [3.8, 3.6, 3.5],
    })
    frame = normalise_operator_aliases(frame, {'vodafone uk': 'VF', 'vodafone': 'VF'})
    filtered = _apply_catalog_filters(frame, rendered, True, 'LQ')
    grouped, primary, series = _apply_catalog_grouping(filtered, rendered, True, 'LQ')
    assert grouped[primary].tolist() == ['Ericsson · VF']
    assert grouped[series].tolist() == ['Ericsson · VF · 2026-Q2_SA']

    already_filtered = replace(entry, filters='vendor NOT CONTAINS (Mixed, Other)')
    assert prepare_multivendor_catalog_entry(already_filtered).filters == already_filtered.filters


def test_vendor_filters_accept_full_or_operator_independent_vendor_values() -> None:
    frame = chart_frame({
        'vendor': [
            'VF_Ericsson', 'VF_Huawei', 'VF_Mixed Vendor', '3_Ericsson',
            '3_Huawei', '3_Samsung', '3_Mixed Vendor', 'O2_NSN',
        ],
        'LQ': [4.0] * 8,
    })
    bare_entry = CatalogEntry(
        1, '', '', '', '', 'CDR-Speech', 'LQ', 'Average Vertical Bars',
        'Vendor IN (Ericsson, Huawei, Samsung, NSN, Mixed Vendor)', '', 'Operator', '',
    )
    full_entry = replace(bare_entry, filters='Vendor IN (3_Ericsson, 3_Huawei, 3_Mixed Vendor, VF_Ericsson, VF_Huawei, VF_Mixed Vendor, O2_NSN)')

    bare = _apply_catalog_filters(frame, bare_entry, True, 'LQ')
    full = _apply_catalog_filters(frame, full_entry, True, 'LQ')

    assert bare['vendor'].tolist() == frame['vendor'].tolist()
    assert full['vendor'].tolist() == [
        'VF_Ericsson', 'VF_Huawei', 'VF_Mixed Vendor', '3_Ericsson',
        '3_Huawei', '3_Mixed Vendor', 'O2_NSN',
    ]


def test_multivendor_operator_filters_match_vendor_prefixes_and_keep_full_grouping_values() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n8,Operator comparison,,Title and 1 column + Comments,Operator chart,CDR-Speech,LQ,Average Vertical Bars,"Operator IN (Vodafone UK, 3, O2)",Operator,Operator × Campaign,Operator,Top\n',
        'nsa',
    )[0]
    rendered = prepare_multivendor_catalog_entry(entry)
    frame = chart_frame({
        'Operator': ['Vodafone UK', 'Vodafone UK', '3', 'O2', 'EE'],
        'vendor': ['Vodafone_Ericsson', 'Vodafone_Huawei', '3_Nokia', 'O2_Ericsson', 'EE_Nokia'],
        'Campaign': ['2025 Q4', '2026 Q1', '2025 Q4', '2026 Q1', '2026 Q1'],
        'LQ': [3.8, 3.7, 3.6, 3.5, 3.4],
    })

    frame = normalise_operator_aliases(frame, {'vodafone uk': 'VF', 'vodafone': 'VF'})
    filtered = _apply_catalog_filters(frame, rendered, True, 'LQ')
    grouped, primary, series = _apply_catalog_grouping(filtered, rendered, True, 'LQ')

    assert filtered['vendor'].tolist() == ['VF_Ericsson', 'VF_Huawei', '3_Nokia', 'O2_Ericsson']
    assert grouped[primary].tolist() == ['Ericsson · VF', 'Ericsson · O2', 'Huawei · VF', 'Nokia · 3']
    assert grouped[series].tolist() == [
        'Ericsson · VF · 2025-Q4', 'Ericsson · O2 · 2026-Q1',
        'Huawei · VF · 2026-Q1', 'Nokia · 3 · 2025-Q4',
    ]
    assert [caption for caption, _colour, _width in _resolved_legend_items(rendered, grouped, 'LQ')] == [
        'Ericsson · VF', 'Ericsson · O2', 'Huawei · VF', 'Nokia · 3',
    ]


def test_multivendor_grouping_orders_vendors_then_operators() -> None:
    entry = CatalogEntry(
        1, "", "", "", "", "CDR-Speech", "LQ", "Average Vertical Bars",
        "", "", "Operator", "Campaign", "Top",
    )
    frame = chart_frame({
        "vendor": ["O2_NSN", "Lebara_NSN", "EE_NSN", "3_Ericsson", "VF_Huawei"],
        "Campaign": ["2026 Q2"] * 5,
        "LQ": [4.0] * 5,
    })

    grouped, primary, _series = _apply_catalog_grouping(
        frame, prepare_multivendor_catalog_entry(entry), True, "LQ",
    )

    assert grouped["__catalog_row_0"].tolist() == ["Ericsson", "Huawei", "NSN", "NSN", "NSN"]
    assert grouped["__catalog_row_1"].tolist() == ["3", "VF", "EE", "O2", "Lebara"]


def test_chart_grouping_uses_workspace_order_for_subscribers_and_combined_vendors() -> None:
    subscriber_entry = CatalogEntry(
        1, '', '', '', '', 'CDR-Data', 'Mean_Data_Rate', 'Average Vertical Bars',
        '', '', 'Subscriber', 'Campaign', 'Top',
    )
    subscriber_frame = chart_frame({
        'Subscriber': ['Alpha', 'Beta'], 'Campaign': ['2026 Q1', '2026 Q1'],
        'Mean_Data_Rate': [1.0, 2.0],
    })
    subscriber_frame.attrs['operator_mapping_groups'] = [
        {'canonical': 'Beta', 'aliases': [], 'position': 0, 'color': '#112233'},
        {'canonical': 'Alpha', 'aliases': [], 'position': 1, 'color': '#445566'},
    ]

    grouped, primary, _series = _apply_catalog_grouping(
        subscriber_frame, subscriber_entry, False, 'Mean_Data_Rate',
    )
    assert grouped[primary].tolist() == ['Beta', 'Alpha']

    vendor_entry = replace(subscriber_entry, grouping_rows='Vendor')
    vendor_frame = chart_frame({
        'Vendor': ['VF_Ericsson', 'VF_Huawei'], 'Campaign': ['2026 Q1', '2026 Q1'],
        'Mean_Data_Rate': [1.0, 2.0],
    })
    vendor_frame.attrs['vendor_mapping_groups'] = [
        {'canonical': 'Huawei', 'aliases': [], 'position': 0, 'color': '#ABCDEF'},
        {'canonical': 'Ericsson', 'aliases': [], 'position': 1, 'color': '#123456'},
    ]

    grouped, primary, _series = _apply_catalog_grouping(
        vendor_frame, vendor_entry, False, 'Mean_Data_Rate',
    )
    assert grouped[primary].tolist() == ['VF_Huawei', 'VF_Ericsson']


def test_cdf_campaigns_share_the_exact_workspace_theme_colour() -> None:
    frame = chart_frame({'operator': [], 'campaign': []})
    frame.attrs['operator_mapping_groups'] = [
        {'canonical': 'Carrier', 'aliases': [], 'position': 0, 'color': '#204060'},
    ]
    frame.attrs['catalogue_dimension_labels'] = {
        'operator': ('Operator',), 'campaign': ('Campaign',),
    }

    colours = _series_colours(
        [('Carrier', 'Q1'), ('Carrier', 'Q2')], ['operator', 'campaign'], frame, line_chart=True,
    )

    assert colours[('Carrier', 'Q1')] == '#204060'
    assert colours[('Carrier', 'Q2')] == '#204060'


def test_vf_uk_cdf_quarters_share_colour_and_use_width_for_recency() -> None:
    frame = chart_frame({'operator': [], 'campaign': []})
    frame.attrs['operator_mapping_groups'] = [
        {'canonical': 'VF_UK', 'aliases': [], 'position': 0, 'color': '#C83E4D'},
    ]
    frame.attrs['catalogue_dimension_labels'] = {
        'operator': ('Operator',), 'campaign': ('Campaign',),
    }
    keys = [('VF_UK', '2026-Q1'), ('VF_UK', '2026-Q2')]

    colours = _series_colours(keys, ['operator', 'campaign'], frame, line_chart=True)
    widths = _cdf_campaign_line_widths(
        [(key, [key[1]]) for key in keys], ['operator', 'campaign'], frame,
    )

    assert set(colours.values()) == {'#C83E4D'}
    assert widths[('VF_UK', '2026-Q2')] > widths[('VF_UK', '2026-Q1')]


def test_multivendor_grouping_uses_the_same_vendor_order_for_each_operator() -> None:
    entry = CatalogEntry(
        1, "", "", "", "", "CDR-Speech", "LQ", "Average Vertical Bars",
        "Vendor", "", "Vendor", "Campaign", "Top",
    )
    frame = chart_frame({
        "vendor": [
            "VF_Samsung", "VF_NSN", "VF_Huawei", "VF_Ericsson",
            "3_Huawei", "3_Samsung", "3_Ericsson",
        ],
        "Campaign": ["2026 Q2"] * 7,
        "LQ": [4.0] * 7,
    })

    grouped, primary, _series = _apply_catalog_grouping(frame, prepare_multivendor_catalog_entry(entry), True, "LQ")

    assert grouped[primary].drop_duplicates().tolist() == [
        "Ericsson · VF", "Ericsson · 3", "Huawei · VF", "Huawei · 3",
        "Samsung · VF", "Samsung · 3", "NSN · VF",
    ]


def test_multivendor_grouping_does_not_split_an_exact_underscore_operator() -> None:
    entry = CatalogEntry(
        1, "", "", "", "", "CDR-Speech", "LQ", "Average Vertical Bars",
        "Vendor", "", "Vendor", "Campaign", "Top",
    )
    frame = chart_frame({
        "Operator": ["VF_SA"],
        "vendor": ["VF_SA"],
        "Campaign": ["2026 Q2"],
        "LQ": [4.0],
    })
    frame.attrs['operator_mappings'] = {'vf': 'VF', 'vf_sa': 'VF_SA'}
    frame.attrs['vendor_mappings'] = {'sa': 'SA'}
    frame.attrs['operator_mapping_groups'].append({
        'canonical': 'VF_SA', 'aliases': [], 'position': 4, 'color': '#8000FF',
    })
    frame.attrs['vendor_mapping_groups'].append({
        'canonical': 'SA', 'aliases': [], 'position': 7, 'color': '#123456',
    })

    grouped, primary, _series = _apply_catalog_grouping(
        frame, prepare_multivendor_catalog_entry(entry), True, "LQ",
    )

    assert grouped[primary].tolist() == ['VF_SA · VF_SA']


def test_vendor_grouping_keeps_each_operator_together_outside_multivendor_mode() -> None:
    entry = CatalogEntry(
        1, "", "", "", "", "CDR-Speech", "LQ", "Average Vertical Bars",
        "Vendor", "", "Vendor", "Campaign", "Top",
    )
    frame = chart_frame({
        "Vendor": [
            "VF_Ericsson", "VF_Huawei", "3_Ericsson", "3_Huawei",
            "3_Samsung", "VF_Samsung", "VF_NSN",
        ],
        "Campaign": ["2026 Q2"] * 7,
        "LQ": [4.0] * 7,
    })

    grouped, primary, _series = _apply_catalog_grouping(frame, entry, False, "LQ")

    assert grouped[primary].drop_duplicates().tolist() == [
        "VF_Ericsson", "VF_Huawei", "VF_Samsung", "VF_NSN",
        "3_Ericsson", "3_Huawei", "3_Samsung",
    ]


def test_rows_only_grouping_uses_one_all_series_without_repeating_the_category() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Speech,LQ,Average Vertical Bars,,Operator,,,\n',
        'nsa',
    )[0]
    frame = chart_frame({'Operator': ['EE', 'O2'], 'LQ': [3.2, 3.8]})

    grouped, primary, series = _apply_catalog_grouping(frame, entry, False, 'LQ')

    assert grouped[primary].tolist() == ['EE', 'O2']
    assert grouped[series].tolist() == ['(all)', '(all)']


def test_campaign_grouping_displays_only_year_and_quarter() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Speech,LQ,Average Vertical Bars,,Operator,Campaign,,\n',
        'nsa',
    )[0]
    frame = chart_frame({
        'Operator': ['EE', '3', 'Vodafone UK'],
        'Campaign': ['UK_Q2_SA_2026', 'UK_Q4_2025', '2024 Q3 NSA'],
        'LQ': [3.2, 3.8, 4.0],
    })

    grouped, _primary, series = _apply_catalog_grouping(frame, entry, False, 'LQ')

    assert grouped['Campaign'].tolist() == ['2024 Q3 NSA', 'UK_Q4_2025', 'UK_Q2_SA_2026']
    assert grouped['__catalog_column_0'].tolist() == ['2024-Q3_NSA', '2025-Q4', '2026-Q2_SA']
    assert grouped[series].tolist() == ['2024-Q3_NSA', '2025-Q4', '2026-Q2_SA']


def test_cdf_renders_a_curve_for_each_complete_rows_and_columns_combination() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['Vodafone', 'Vodafone', 'Vodafone', 'Vodafone', 'O2', 'O2', 'O2', 'O2'],
        '__catalog_column_0': ['2025', '2025', '2026', '2026', '2025', '2025', '2026', '2026'],
        '__catalog_primary': ['unused'] * 8,
        '__catalog_series': ['unused'] * 8,
        'Campaign': ['2025', '2025', '2026', '2026', '2025', '2025', '2026', '2026'],
        'Metric': [1.0, 2.0, 1.5, 2.5, 1.2, 2.2, 1.7, 2.7],
    })

    with patch('src.modules.cdr_reporting._draw_chart_legend') as draw_legend:
        _render_cdf_line('CDF', frame, '__catalog_primary', '__catalog_series', 'Metric')

    legend_items = draw_legend.call_args.args[1]
    assert [item[0] for item in legend_items] == [
        'Vodafone · 2025', 'Vodafone · 2026', 'O2 · 2025', 'O2 · 2026',
    ]


def test_cdf_uses_emphasised_lines_when_only_one_campaign_is_rendered() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['Vodafone', 'Vodafone', 'O2', 'O2'],
        '__catalog_primary': ['unused'] * 4, '__catalog_series': ['unused'] * 4,
        'Campaign': ['2026 Q2'] * 4, 'Metric': [1.0, 2.0, 1.2, 2.2],
    })

    with patch('src.modules.cdr_reporting._draw_chart_legend') as draw_legend:
        _render_cdf_line('CDF', frame, '__catalog_primary', '__catalog_series', 'Metric')

    assert {item[2] for item in draw_legend.call_args.args[1]} == {4}


def test_cdf_renderer_uses_progressive_widths_for_four_campaigns() -> None:
    campaigns = ['2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4']
    frame = chart_frame({
        '__catalog_row_0': ['Vodafone'] * 8,
        '__catalog_column_0': [campaign for campaign in campaigns for _ in range(2)],
        '__catalog_primary': ['unused'] * 8,
        '__catalog_series': ['unused'] * 8,
        'Campaign': [campaign for campaign in campaigns for _ in range(2)],
        'Metric': [1.0, 2.0, 1.1, 2.1, 1.2, 2.2, 1.3, 2.3],
    })
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': ('Operator',),
        '__catalog_column_0': ('Campaign',),
    }

    with patch('src.modules.cdr_reporting._draw_chart_legend') as draw_legend:
        _render_cdf_line('CDF', frame, '__catalog_primary', '__catalog_series', 'Metric')

    assert [item[2] for item in draw_legend.call_args.args[1]] == [1, 2, 3, 4]


def test_cdf_trims_only_after_80_percent_of_curves_exceed_99_percent() -> None:
    # With four curves, ceil(4 * 80%) requires all four curves.  Three
    # converged curves must retain the fourth curve's meaningful tail.
    assert _cdf_terminal_x_maximum(
        [[1.0] * 100 + [10.0], [2.0] * 100 + [10.0], [3.0] * 100 + [10.0], [4.0] * 70 + [30.0] * 31],
        1.0, 30.0, minimum_separation=0.08,
    ) == 30.0
    # With five curves, ceil(5 * 80%) requires four curves and permits the
    # converged tail to be removed once four are above 99%.
    assert _cdf_terminal_x_maximum(
        [[1.0] * 100 + [10.0], [2.0] * 100 + [10.0], [3.0] * 100 + [10.0], [4.0] * 100 + [10.0], [5.0] * 70 + [30.0] * 31],
        1.0, 30.0, minimum_separation=0.08,
    ) == 4.0
    # Exactly 99% does not satisfy the strictly-above-99% threshold.
    assert _cdf_terminal_x_maximum(
        [[1.0] * 99 + [10.0], [2.0] * 99 + [10.0], [3.0] * 99 + [10.0]],
        1.0, 10.0, minimum_separation=0.08,
    ) == 10.0


def test_outcome_series_colours_use_green_for_success_and_red_for_failure() -> None:
    frame = pd.DataFrame()
    keys = [('Success',), ('Failure',), ('Completed',), ('Dropped',)]

    colours = _series_colours(keys, ['__catalog_column_0'], frame)

    assert colours == {
        ('Success',): '#2C9A62',
        ('Failure',): '#C83E4D',
        ('Completed',): '#197A4A',
        ('Dropped',): '#D8555F',
    }


def test_status_categories_colour_failure_and_success_outcomes_semantically() -> None:
    data = pd.DataFrame({'Test_Result': ['Failure', 'Success', 'Dropped']})

    _result, states, colours = _status_chart_categories(
        data, 'Test_Result', quality=False, threshold=1.6,
    )

    palette = dict(zip(states, colours, strict=True))
    assert palette['Success'] == '#2C9A62'
    assert palette['Dropped'] == '#C83E4D'
    assert palette['Failure'] == '#D8555F'


def test_operator_vendor_column_groups_keep_campaign_bars_in_their_operator_palette() -> None:
    frame = chart_frame({})
    colours = _hierarchy_group_colours([
        ('Vodafone_Ericsson', '2026 Q1'), ('Vodafone_Ericsson', '2026 Q2'),
        ('Vodafone_Huawei', '2026 Q1'), ('Vodafone_Huawei', '2026 Q2'),
        ('3_Ericsson', '2026 Q1'), ('3_Ericsson', '2026 Q2'),
    ], frame=frame)

    assert colours['Vodafone_Ericsson'] == '#E15759'
    assert colours['Vodafone_Huawei'] == '#8C3637'
    assert colours['3_Ericsson'] == '#F28E2B'


def test_exact_operator_mapping_wins_over_underscore_prefix_fallback() -> None:
    frame = chart_frame({})
    frame.attrs['operator_mapping_groups'].append({
        'canonical': 'VF_SA', 'aliases': ['VF SA UK'], 'position': 4, 'color': '#8000FF',
    })
    frame.attrs['catalogue_dimension_labels'] = {'__catalog_row_0': ('Operator',)}

    colours = _series_colours(
        [('VF',), ('VF_SA',)], ['__catalog_row_0'], frame, line_chart=True,
    )

    assert colours == {('VF',): '#E15759', ('VF_SA',): '#8000FF'}


def test_vendor_is_the_complete_suffix_after_the_longest_configured_operator() -> None:
    frame = chart_frame({})
    frame.attrs['operator_mapping_groups'].extend([
        {'canonical': 'VF_SA', 'aliases': [], 'position': 4, 'color': '#8000FF'},
        {'canonical': 'VF_NSA', 'aliases': [], 'position': 5, 'color': '#0080FF'},
    ])
    frame.attrs['vendor_mapping_groups'].append({
        'canonical': 'Open_RAN', 'aliases': [], 'position': 7, 'color': '#12AB34',
    })
    frame.attrs['catalogue_dimension_labels'] = {'__catalog_row_0': ('Vendor',)}

    colours = _series_colours(
        [('VF_SA_Open_RAN',), ('VF_NSA_Open_RAN',)], ['__catalog_row_0'], frame,
    )

    assert colours == {
        ('VF_SA_Open_RAN',): '#12AB34',
        ('VF_NSA_Open_RAN',): '#12AB34',
    }


def test_neutral_operator_colour_matches_between_campaign_bars_and_legend() -> None:
    bars = _hierarchy_group_colours([
        ('O2', '2026 Q1'), ('O2', '2026 Q2'),
        ('Vodafone', '2026 Q1'), ('Vodafone', '2026 Q2'),
        ('3', '2026 Q1'), ('3', '2026 Q2'),
        ('EE', '2026 Q1'), ('EE', '2026 Q2'),
        ('Lebara', '2026 Q1'), ('Lebara', '2026 Q2'),
    ])
    legend = _hierarchy_group_colours([
        ('O2',), ('Vodafone',), ('3',), ('EE',), ('Lebara',),
    ])

    assert bars['Lebara'] == legend['Lebara']


def test_table_renders_percentages_for_a_categorical_metric() -> None:
    frame = chart_frame({
        'Test': ['Browse', 'Browse', 'Transfer'],
        'Result': ['Completed', 'Failed', 'Completed'],
    })

    rendered = _render_table('Result ratio', frame, 'Test', None, 'Result')

    assert rendered.getbuffer().nbytes > 0


def test_chart_colours_use_vendor_families_for_multi_operator_dimensions() -> None:
    keys = [('Vodafone', 'Ericsson'), ('Vodafone', 'Huawei'), ('3', 'Ericsson'), ('3', 'Huawei')]
    frame = chart_frame({'__catalog_row_0': [], '__catalog_row_1': []})
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': ('Operator',), '__catalog_row_1': ('Vendor',),
    }

    colours = _series_colours(keys, ['__catalog_row_0', '__catalog_row_1'], frame)

    assert colours[('Vodafone', 'Ericsson')] == '#2E8B57'
    assert colours[('3', 'Ericsson')] == '#2E8B57'
    assert colours[('Vodafone', 'Huawei')] == '#E15759'
    assert colours[('3', 'Huawei')] == '#E15759'

    line_colours = _series_colours(keys, ['__catalog_row_0', '__catalog_row_1'], frame, line_chart=True)
    assert line_colours == colours

    line_dashes = _series_line_dashes(keys, ['__catalog_row_0', '__catalog_row_1'], frame)
    assert line_dashes[('Vodafone', 'Ericsson')] == ()
    assert line_dashes[('Vodafone', 'Huawei')] == ()
    assert line_dashes[('3', 'Ericsson')] == (18, 8)
    assert line_dashes[('3', 'Huawei')] == (18, 8)


def test_chart_colours_use_vendor_families_for_one_operator() -> None:
    keys = [('Vodafone', 'Ericsson'), ('Vodafone', 'Huawei'), ('Vodafone', 'Samsung'), ('Vodafone', 'NSN')]
    frame = chart_frame({'__catalog_row_0': [], '__catalog_row_1': []})
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': ('Operator',), '__catalog_row_1': ('Vendor',),
    }

    colours = _series_colours(keys, ['__catalog_row_0', '__catalog_row_1'], frame)

    assert colours == {
        ('Vodafone', 'Ericsson'): '#2E8B57', ('Vodafone', 'Huawei'): '#E15759',
        ('Vodafone', 'Samsung'): '#7B3FB5', ('Vodafone', 'NSN'): '#4E79A7',
    }


def test_multivendor_chart_uses_operator_colour_when_vendor_is_missing() -> None:
    keys = [('Vodafone', '(blank)'), ('3', '(blank)'), ('EE', 'EE')]
    frame = chart_frame({'__catalog_row_0': [], '__catalog_row_1': []})
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': ('Operator',), '__catalog_row_1': ('Vendor',),
    }

    colours = _series_colours(keys, ['__catalog_row_0', '__catalog_row_1'], frame)

    assert colours == {
        ('Vodafone', '(blank)'): '#E15759',
        ('3', '(blank)'): '#F28E2B',
        ('EE', 'EE'): '#76B7B2',
    }


def test_cdf_uses_solid_first_operator_and_distinct_later_operators_per_vendor() -> None:
    keys = [
        ('Ericsson', '3'), ('Huawei', '3'), ('Samsung', '3'),
        ('Ericsson', 'VF'), ('Huawei', 'VF'), ('Samsung', 'VF'),
        ('Ericsson', 'EE'), ('Huawei', 'EE'),
        ('NSN', 'VF'), ('EE', 'EE'), ('O2', 'O2'), ('VF_SA', 'VF_SA'),
    ]
    frame = chart_frame({'__catalog_row_0': [], '__catalog_row_1': []})
    frame.attrs['operator_mapping_groups'].append({
        'canonical': 'VF_SA', 'aliases': [], 'position': 4, 'color': '#8000FF',
    })
    frame.attrs['operator_mapping_groups'] = [
        {**group, 'position': index}
        for index, group in enumerate(sorted(
            frame.attrs['operator_mapping_groups'],
            key=lambda group: {'3': 0, 'VF': 1, 'EE': 2, 'O2': 3, 'VF_SA': 4}.get(str(group['canonical']), 9),
        ))
    ]
    frame.attrs['catalogue_dimension_labels'] = {
        '__catalog_row_0': ('Vendor',), '__catalog_row_1': ('Operator',),
    }

    dashes = _series_line_dashes(keys, ['__catalog_row_0', '__catalog_row_1'], frame)

    assert dashes[('Ericsson', '3')] == ()
    assert dashes[('Huawei', '3')] == ()
    assert dashes[('Samsung', '3')] == ()
    assert dashes[('Ericsson', 'VF')] == (18, 8)
    assert dashes[('Huawei', 'VF')] == (18, 8)
    assert dashes[('Samsung', 'VF')] == (18, 8)
    assert dashes[('Ericsson', 'EE')] == (2, 10)
    assert dashes[('Huawei', 'EE')] == (2, 10)
    assert dashes[('NSN', 'VF')] == ()
    assert dashes[('EE', 'EE')] == ()
    assert dashes[('O2', 'O2')] == ()
    assert dashes[('VF_SA', 'VF_SA')] == ()


def test_chart_colours_detect_a_single_operator_from_composite_vendor_values() -> None:
    keys = [('3_Ericsson',), ('3_Huawei',), ('3_Nokia',)]
    frame = chart_frame({'__catalog_column_0': []})
    frame.attrs['catalogue_dimension_labels'] = {'__catalog_column_0': ('Vendor',)}

    colours = _series_colours(keys, ['__catalog_column_0'], frame)

    assert colours[('3_Ericsson',)] == '#2E8B57'
    assert len(set(colours.values())) == 3


def test_primary_vendor_dimension_assigns_semantic_colours_to_special_vendors() -> None:
    keys = [
        ('(blank)',), ('Vodafone_Ericsson',), ('Vodafone_Mixed Vendor',), ('Vodafone_Huawei',),
        ('Vodafone_Other Vendor',), ('Vodafone_NSN',), ('3_Ericsson',), ('3_Mixed Vendor',),
        ('3_Huawei',), ('3_Samsung',),
    ]
    frame = chart_frame({'__catalog_column_0': []})
    frame.attrs['catalogue_dimension_labels'] = {'__catalog_column_0': ('Vendor',)}

    colours = _series_colours(keys, ['__catalog_column_0'], frame)

    assert colours == {
        ('(blank)',): '#7A8791', ('Vodafone_Ericsson',): '#2E8B57',
        ('Vodafone_Mixed Vendor',): '#D9A514', ('Vodafone_Huawei',): '#E15759',
        ('Vodafone_Other Vendor',): '#D9A514', ('Vodafone_NSN',): '#4E79A7',
        ('3_Ericsson',): '#2E8B57', ('3_Mixed Vendor',): '#D9A514',
        ('3_Huawei',): '#E15759', ('3_Samsung',): '#7B3FB5',
    }


def test_horizontal_line_legend_reduces_columns_for_long_cdf_labels() -> None:
    captions = [
        'VF_UK · Ericsson · 2026-Q2', 'VF_UK · Huawei · 2026-Q2',
        'VF_UK · Samsung · 2026-Q2', 'VF_SA · Ericsson · 2026-Q2',
        'VF_SA · Huawei · 2026-Q2', 'VF_SA · Samsung · 2026-Q2',
    ]

    assert _horizontal_legend_columns(captions, 11, line_markers=True) < 6


def test_reporting_query_columns_splits_map_coordinates() -> None:
    import src.DashboardAnalytic as app_module

    entry = CatalogEntry(
        9, 'Map', '', '', 'DL Thput vs RF', 'CDR-Data',
        'Test_Start_Latitude vs Test_Start_Longitude', 'Map', '', 'Test Name IN (FDTT http DL MT)', 'Test_Result', '', 'Right',
    )

    columns = app_module.reporting_query_columns('data', [entry], False)

    assert 'Test_Start_Latitude' in columns
    assert 'Test_Start_Longitude' in columns
    assert 'Test_Start_Latitude vs Test_Start_Longitude' not in columns


def test_map_renderer_keeps_a_colour_key_for_every_filtered_point() -> None:
    frame = chart_frame({
        'Latitude': [51.5, 51.51, 51.52],
        'Longitude': [-0.12, -0.11, -0.10],
        'Operator': ['VF', 'EE', 'VF'],
        'Campaign': ['2026 Q2', '2026 Q2', '2026 Q1'],
    })

    image = _render_map('Coverage', frame, 'Operator', 'Campaign', 'Latitude', 'Longitude')

    assert image.getvalue().startswith(b'\x89PNG\r\n\x1a\n')


def test_reporting_query_columns_splits_multi_kpi_cdf_metrics() -> None:
    import src.DashboardAnalytic as app_module

    entry = CatalogEntry(
        43, 'FDTT DL SINR', '', '', 'FDTT DL SINR', 'CDR-Data',
        'NR_PCell_SINR_Avg | LTE_PCell_SINR_Avg', 'Multi KPI CDF Lines',
        'Operator', 'Test_Result IN (Completed)', 'Operator', '', 'Right',
    )

    columns = app_module.reporting_query_columns('data', [entry], False)

    assert {'NR_PCell_SINR_Avg', 'LTE_PCell_SINR_Avg'} <= set(columns)
    assert 'NR_PCell_SINR_Avg | LTE_PCell_SINR_Avg' not in columns


def test_reporting_query_columns_include_calculated_dimension_dependencies() -> None:
    import src.DashboardAnalytic as app_module

    entry = CatalogEntry(
        22, 'LTE PCell ARFCN', '', '', 'LTE PCell ARFCN', 'CDR-Data',
        'First LTE PCC ARFCN', '100% Stacked Vertical Bars',
        'First LTE PCC ARFCN', 'Tput Above IN (above100, above20)', 'Operator', '', 'Right',
    )

    columns = app_module.reporting_query_columns('data', [entry], False)

    assert {'LTE_PCC_EARFCN', 'Mean_Data_Rate', 'Test_Name'} <= set(columns)


def test_catalogue_filter_contract_supports_not_in_and_not_contains() -> None:
    conditions = parse_catalog_filters('Session_Type NOT IN (WhatsApp, SMS); Vendor NOT CONTAINS (Mixed, Other); Campaign NOT CONTAINS legacy')
    assert [(item.column, item.operator, item.values) for item in conditions] == [
        ('Session_Type', 'NOT IN', ('WhatsApp', 'SMS')),
        ('Vendor', 'NOT CONTAINS', ('Mixed', 'Other')),
        ('Campaign', 'NOT CONTAINS', ('legacy',)),
    ]
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Speech,LQ,Average Vertical Bars,Session_Type NOT IN (WhatsApp); Campaign NOT CONTAINS legacy,Operator,Campaign,,\n',
        'nsa',
    )[0]
    frame = chart_frame({
        'Session_Type': ['VoLTE', 'WhatsApp', 'VoLTE'], 'Campaign': ['Q1', 'Q1', 'legacy-Q2'],
        'LQ': [3.2, 4.0, 3.8], 'Operator': ['EE', 'EE', 'O2'],
    })
    assert _apply_catalog_filters(frame, entry, False, 'LQ')['Operator'].tolist() == ['EE']


def test_campaign_filters_accept_compact_permutations_without_merging_sa_and_nsa() -> None:
    frame = chart_frame({
        'Campaign': ['UK_Q2_2026', 'UK_Q2_2026_SA', '2026_Q2_NSA_UK'],
        'Metric': [1, 2, 3],
    })
    plain = replace(CatalogEntry(1, '', '', '', '', 'CDR-Data', 'Metric', 'Average Vertical Bars', '', '', '', '', '', ''), filters='Campaign = 2026-Q2')
    sa = replace(plain, filters='Campaign = 2026-Q2_SA')
    modes = replace(plain, filters='Campaign IN (2026-Q2_SA, UK_Q2_2026_NSA)')

    assert _apply_catalog_filters(frame, plain, False, 'Metric')['Metric'].tolist() == [1]
    assert _apply_catalog_filters(frame, sa, False, 'Metric')['Metric'].tolist() == [2]
    assert _apply_catalog_filters(frame, modes, False, 'Metric')['Metric'].tolist() == [2, 3]


def test_tableau_result_group_filter_uses_the_workbook_bins() -> None:
    dimensions = parse_calculated_dimensions([{
        'name': 'Result Group', 'sources': ['cdr-data'],
        'rules': [
            {'when': 'Test_Result IN (Completed, Visible Completed)', 'value': 'Success'},
            {'when': 'Test_Result IN (Cutoff, Failed)', 'value': 'Failure'},
        ],
    }])
    entry = CatalogEntry(
        1, 'Failures', '', '', 'Failures', 'CDR-Data', 'Result Group',
        '100% Stacked Vertical Bars', 'Result Group', 'Result Group NOT IN (Success)',
        'Operator', '', 'Right', dimensions,
    )
    frame = chart_frame({
        'Operator': ['EE'] * 5,
        'Test_Result': ['Completed', 'Visible Completed', 'Cutoff', 'Failed', 'Unknown'],
    })

    filtered = _apply_catalog_filters(frame, entry, False, None)

    assert filtered['Test_Result'].tolist() == ['Cutoff', 'Failed', 'Unknown']


def test_multi_kpi_cdf_lines_render_each_tableau_measure() -> None:
    entry = CatalogEntry(
        1, 'Radio quality', '', '', 'Radio quality', 'CDR-Data',
        'NR SINR | LTE SINR', 'Multi KPI CDF Lines', 'Operator', '',
        'Operator', 'Campaign', 'Right',
    )
    frame = chart_frame({
        'Operator': ['EE', 'EE', 'VF', 'VF'],
        'Campaign': ['2026 Q1', '2026 Q2', '2026 Q1', '2026 Q2'],
        'NR SINR': [4.0, 5.0, 6.0, 7.0],
        'LTE SINR': [8.0, 9.0, 10.0, 11.0],
    })

    image = render_catalog_chart_preview(frame, entry)
    targets = catalog_chart_hover_targets(frame, entry)

    assert image.startswith(b'\x89PNG\r\n\x1a\n')
    assert {target['label'] for target in targets} == {'NR SINR', 'LTE SINR'}
    assert any(target['x'] < 750 for target in targets)
    assert any(target['x'] > 750 for target in targets)


def test_dashboard_canvas_report_renderer_uses_dashboard_payload() -> None:
    entry = CatalogEntry(
        1, 'Radio quality', '', '', 'Radio quality', 'CDR-Data',
        'NR SINR', 'CDF Line', 'Operator', '', 'Operator', 'Campaign', 'Right',
    )
    frame = chart_frame({
        'Operator': ['EE', 'VF'],
        'Campaign': ['2026 Q1', '2026 Q1'],
        'NR SINR': [4.0, 8.0],
    })

    with patch('src.modules.cdr_reporting._render_dashboard_payload_png', return_value=b'canvas-png') as render:
        image = render_catalog_chart_preview(frame, entry, renderer='dashboard-canvas')

    assert image == b'canvas-png'
    payload = render.call_args.args[0]
    assert payload['renderer'] == 'catalog-v2'
    assert payload['type'] == 'cdf'
    assert payload['title'] == 'Radio quality'


def test_dashboard_canvas_renderer_uses_configured_node_path(monkeypatch, tmp_path: Path) -> None:
    import src.modules.cdr_reporting as reporting

    node = tmp_path / 'node'
    node.write_text('', encoding='utf-8')
    node.chmod(0o755)
    monkeypatch.setenv('DASHBOARD_ANALYTIC_NODE_PATH', str(node))

    assert reporting._node_executable() == str(node)


def test_report_renderer_rejects_unknown_engine() -> None:
    entry = CatalogEntry(
        1, 'Radio quality', '', '', 'Radio quality', 'CDR-Data',
        'NR SINR', 'CDF Line', '', '', 'Operator', 'Campaign', 'Right',
    )
    frame = chart_frame({'Operator': ['EE'], 'Campaign': ['2026 Q1'], 'NR SINR': [4.0]})

    with pytest.raises(ValueError, match="Expected 'pil' or 'dashboard-canvas'"):
        render_catalog_chart_preview(frame, entry, renderer='unknown')


def test_report_renderer_defaults_to_canvas_and_keeps_pil_override(monkeypatch) -> None:
    import src.modules.cdr_reporting as reporting

    monkeypatch.delenv(reporting.REPORT_CHART_RENDERER_ENV, raising=False)
    assert reporting.report_chart_renderer_name() == 'dashboard-canvas'
    monkeypatch.setenv(reporting.REPORT_CHART_RENDERER_ENV, 'pil')
    assert reporting.report_chart_renderer_name() == 'pil'


def test_canvas_hits_are_reused_by_static_chart_tooltips() -> None:
    import src.modules.cdr_reporting as reporting

    entry = CatalogEntry(
        1, 'Throughput', '', '', 'Throughput', 'CDR-Data',
        'Mean_Data_Rate', 'Average Vertical Bars', '', '', 'Operator', 'Campaign', 'Right',
    )
    frame = chart_frame({'Operator': ['EE'], 'Campaign': ['2026 Q1'], 'Mean_Data_Rate': [42.0]})
    hits = [{
        'kind': 'rectangle', 'x': 10, 'y': 20, 'width': 30, 'height': 40,
        'label': 'EE · 2026 Q1', 'series': 'EE', 'value': '42.00',
    }]

    with patch('src.modules.cdr_reporting._render_dashboard_payload', return_value=(b'canvas-png', hits)):
        image, targets = reporting.render_catalog_chart_preview_with_hover(frame, entry)

    assert image == b'canvas-png'
    assert targets == [{
        'kind': 'bar', 'x': 10.0, 'y': 20.0, 'width': 30.0, 'height': 40.0,
        'label': 'EE · 2026 Q1', 'legend': 'EE', 'value': '42.00',
    }]


def test_not_contains_filter_excludes_each_comma_separated_term() -> None:
    entry = CatalogEntry(
        1, 'Quality', '', 'Title and 1 column', '', 'CDR-Speech', 'LQ', 'CDF Line',
        '', 'Vendor NOT CONTAINS (Mixed, Other)', 'Vendor', 'Campaign', 'Top',
    )
    frame = chart_frame({
        'Vendor': ['Vodafone_Ericsson', 'Vodafone_Mixed Vendor', '3_Other Vendor'],
        'Campaign': ['2026 Q1'] * 3,
        'LQ': [3.5, 3.6, 3.7],
    })

    assert _apply_catalog_filters(frame, entry, False, 'LQ')['Vendor'].tolist() == ['Vodafone_Ericsson']


def test_catalogue_call_family_uses_documented_netcheck_session_values() -> None:
    entry = with_default_calculated_dimensions(parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,"Call Family IN (VoLTE, MultiRAB, WhatsApp)",Call Family,Operator × Campaign,,\n',
        'nsa',
    )[0])
    frame = chart_frame({
        'Session_Type': ['CALL', 'MultiRAB CALL', 'WhatsApp CALL'],
        'L1_Call_Mode_A': ['VoLTE', '', ''],
        'Operator': ['EE', 'EE', 'EE'],
        'Campaign': ['Q1', 'Q1', 'Q1'],
        'Call_Status': ['Completed', 'Completed', 'Completed'],
    })

    filtered = _apply_catalog_filters(frame, entry, False, 'Call_Status')
    grouped, primary, series = _apply_catalog_grouping(filtered, entry, False, 'Call_Status')

    assert grouped[primary].tolist() == ['VoLTE', 'MultiRAB', 'WhatsApp']
    assert grouped['__catalog_row_0'].tolist() == ['VoLTE', 'MultiRAB', 'WhatsApp']
    assert grouped['__catalog_column_0'].tolist() == ['EE', 'EE', 'EE']
    assert grouped['__catalog_column_1'].tolist() == ['Q1', 'Q1', 'Q1']

    with patch('src.modules.cdr_reporting._render_status_100_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'nested-chart')
        chart = _render_status_100('Completed Call Ratio', grouped, primary, series)

    assert chart.getvalue() == b'nested-chart'
    assert hierarchy_renderer.call_args.args[2] == ['__catalog_row_0']
    assert hierarchy_renderer.call_args.args[3] == ['__catalog_column_0', '__catalog_column_1']


def test_status_chart_uses_nested_columns_without_a_row_grouping() -> None:
    entry = CatalogEntry(
        8, 'Completed Call Ratio', '', 'Title and 1 column + Comments', '', 'CDR-Voice',
        'Call_Status', '100% Stacked Vertical Bars', '', '', '', 'Operator × Campaign',
    )
    frame = chart_frame({
        'Operator': ['Vodafone', 'Vodafone', 'O2', 'O2'],
        'Campaign': ['2025 Q4', '2026 Q1', '2025 Q4', '2026 Q1'],
        'Call_Status': ['Completed', 'Failed', 'Completed', 'Dropped'],
    })
    grouped, primary, series = _apply_catalog_grouping(frame, entry, False, 'Call_Status')

    with patch('src.modules.cdr_reporting._render_status_100_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'nested-columns')
        chart = _render_status_100('Completed Call Ratio', grouped, primary, series)

    assert chart.getvalue() == b'nested-columns'
    assert hierarchy_renderer.call_args.args[2] == []
    assert hierarchy_renderer.call_args.args[3] == ['__catalog_column_0', '__catalog_column_1']


def test_status_chart_keeps_row_only_hierarchy_on_the_left() -> None:
    entry = CatalogEntry(
        8, 'Status', '', '', '', 'CDR-Data', 'Test_Result',
        '100% Stacked Vertical Bars', '', '', 'City × G Level 1', '',
    )
    frame = chart_frame({
        'City': ['London', 'London'],
        'G_Level_1': ['Drive', 'Connecting Roads'],
        'Test_Result': ['Completed', 'Failed'],
    })
    grouped, primary, series = _apply_catalog_grouping(frame, entry, False, 'Test_Result')

    with patch('src.modules.cdr_reporting._render_status_100_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'row-hierarchy')
        chart = _render_status_100('Status', grouped, primary, series)

    assert chart.getvalue() == b'row-hierarchy'
    assert hierarchy_renderer.call_args.args[2] == ['__catalog_row_0', '__catalog_row_1']
    assert hierarchy_renderer.call_args.args[3] == ['__catalog_single_column']


def test_status_chart_leaves_status_row_inclusion_to_the_template_filter() -> None:
    frame = chart_frame({
        'Operator': ['EE'] * 8,
        'Campaign': ['2026-Q2'] * 8,
        'Test_Result': ['Completed', 'Failed', None, float('nan'), '', ' NaN ', 'Not executed', 'Unknown'],
        '__catalog_column_0': ['EE'] * 8,
    })

    with patch('src.modules.cdr_reporting._render_status_100_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'filtered-status-chart')
        chart = _render_status_100('Data failures', frame, 'Operator', 'Campaign')

    rendered_data = hierarchy_renderer.call_args.args[1]
    assert chart.getvalue() == b'filtered-status-chart'
    assert len(rendered_data.index) == 8
    assert rendered_data['state'].iloc[:2].tolist() == ['Completed', 'Failed']
    assert rendered_data['state'].iloc[2:].isna().all()


def test_status_chart_honours_selected_kpi_when_other_status_columns_exist() -> None:
    frame = chart_frame({
        'Operator': ['EE', 'EE'],
        'Campaign': ['2026-Q2', '2026-Q2'],
        'Call_Status': ['Completed', 'Completed'],
        'Test_Result': ['Completed', 'Failed'],
        '__catalog_column_0': ['EE', 'EE'],
    })

    with patch('src.modules.cdr_reporting._render_status_100_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'selected-status-kpi')
        chart = _render_status_100('Data failures', frame, 'Operator', 'Campaign', metric='Test_Result')

    rendered_data = hierarchy_renderer.call_args.args[1]
    assert chart.getvalue() == b'selected-status-kpi'
    assert rendered_data['state'].tolist() == ['Completed', 'Failed']


def test_status_chart_maps_cutoff_to_a_visible_failure_segment_without_filtering_rows() -> None:
    frame = chart_frame({
        'Operator': ['EE'] * 8,
        'Campaign': ['2026-Q2'] * 8,
        'Test_Result': ['Incomplete', 'Unsuccessful', 'Aborted', 'Cancelled', 'Timeout', 'Cutoff', 'Failed', 'Completed'],
        '__catalog_column_0': ['EE'] * 8,
    })

    with patch('src.modules.cdr_reporting._render_status_100_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'negative-statuses')
        _render_status_100('Data failures', frame, 'Operator', 'Campaign', metric='Test_Result')

    states = hierarchy_renderer.call_args.args[1]['state']
    assert states.tolist() == ['Incomplete', 'Unsuccessful', 'Aborted', 'Cancelled', 'Timeout', 'Cutoff', 'Failed', 'Completed']
    assert hierarchy_renderer.call_args.args[4] == (
        'Completed', 'Cutoff', 'Failed', 'Aborted', 'Cancelled', 'Incomplete', 'Timeout', 'Unsuccessful',
    )
    assert hierarchy_renderer.call_args.args[5] == (
        '#2C9A62', '#C83E4D', '#D8555F', '#E26A70', '#AE2F42', '#F08A8F', '#8F2035', '#C83E4D',
    )


def test_data_cutoffs_are_excluded_from_tableau_status_denominator() -> None:
    frame = chart_frame({
        'Operator': ['EE'] * 1000,
        'Campaign': ['2026-Q2'] * 1000,
        'Test_Result': ['Completed'] * 692 + ['Cutoff'] * 278 + ['Failed'] * 30,
        '__catalog_column_0': ['EE'] * 1000,
    })

    with patch('src.modules.cdr_reporting._render_status_100_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'tableau-status-ratio')
        _render_status_100('Data failures', frame, 'Operator', 'Campaign', metric='Test_Result')

    states = hierarchy_renderer.call_args.args[1]['state']
    assert states.eq('Completed').sum() == 692
    assert states.eq('Failed').sum() == 30


def test_hierarchical_grouping_keeps_campaign_bars_together_per_operator() -> None:
    frame = chart_frame({
        '__catalog_column_0': ['Vodafone', 'O2', 'Vodafone', 'O2'],
        '__catalog_column_1': ['2025 Q4', '2025 Q4', '2026 Q1', '2026 Q1'],
    })

    keys = _hierarchical_unique_keys(frame, ['__catalog_column_0', '__catalog_column_1'])

    assert keys == [
        ('Vodafone', '2025 Q4'),
        ('Vodafone', '2026 Q1'),
        ('O2', '2025 Q4'),
        ('O2', '2026 Q1'),
    ]


def test_hierarchy_spans_nest_each_level_without_compound_captions() -> None:
    keys = [
        ('City', 'Drive', 'EE'), ('City', 'Drive', '3'),
        ('City', 'Connecting Roads', 'EE'), ('Rural', 'Drive', 'EE'),
    ]

    assert _hierarchy_caption_spans(keys, 0) == [(0, 3, 'City'), (3, 4, 'Rural')]
    assert _hierarchy_caption_spans(keys, 1) == [
        (0, 2, 'Drive'), (2, 3, 'Connecting Roads'), (3, 4, 'Drive'),
    ]
    assert _hierarchy_caption_spans(keys, 2) == [
        (0, 1, 'EE'), (1, 2, '3'), (2, 3, 'EE'), (3, 4, 'EE'),
    ]


def test_campaign_aggregation_is_ordered_oldest_to_newest_for_every_chart_renderer() -> None:
    entry = CatalogEntry(
        5, 'Data failures', '', '', '', 'CDR-Data', 'Test_Result',
        '100% Stacked Vertical Bars', '', '', 'Test_Name', 'Operator × Campaign',
    )
    frame = chart_frame({
        'Test_Name': ['FDFS', 'FDFS', 'FDFS', 'FDFS'],
        'Operator': ['EE', 'VF', 'EE', 'VF'],
        'Campaign': ['UK_Q2_2026', 'UK_Q2_2026', 'UK_Q1_2026', 'UK_Q1_2026'],
        'Test_Result': ['Completed'] * 4,
    })

    grouped, _, _ = _apply_catalog_grouping(frame, entry, False, 'Test_Result')
    keys = _hierarchical_unique_keys(grouped, ['__catalog_column_0', '__catalog_column_1'])

    assert keys == [
        ('VF', '2026-Q1'), ('VF', '2026-Q2'),
        ('EE', '2026-Q1'), ('EE', '2026-Q2'),
    ]


def test_nsa_speech_catalogue_filters_produce_samples_and_use_latest_campaign() -> None:
    entries = [with_default_calculated_dimensions(entry) for entry in load_catalog_csv(Path(__file__).parent / 'fixtures' / 'NSA Slide Template.csv', 'nsa')]
    speech = pd.DataFrame({
        'sample': ['volte', 'multirab', 'whatsapp-old', 'whatsapp-latest', 'whatsapp-sa', 'o2-latest'],
        'Session_Type': ['CALL', 'MultiRAB CALL', 'WhatsApp CALL', 'WhatsApp CALL', 'WhatsApp CALL', 'WhatsApp CALL'],
        'L1_Call_Mode_A': ['VoLTE', 'VoLTE', 'VoIP', 'VoIP', 'VoIP', 'VoIP'],
        'Sample_RAT_A': [None, None, 'EN-DC', 'EN-DC', 'NR SA', 'EN-DC'],
        'Call_Status': ['Completed'] * 6,
        'Operator': ['Vodafone UK', '3', 'EE', 'EE', 'EE', 'O2 (UK)'],
        'Campaign': ['UK_Q3_2025', 'UK_Q3_2025', 'UK_Q3_2025', 'UK_Q4_2025', 'UK_Q4_2025', 'UK_Q4_2025'],
        'LQ': [3.8, 3.7, 3.9, 4.0, 4.1, 4.2],
    })
    nsa = classify_sessions(speech, 'nsa')
    filtered_by_entry = {
        (entry.slide, entry.chart_type, index): _apply_catalog_filters(nsa, entry, False, 'LQ')
        for index, entry in enumerate(entries)
        if entry.slide in {7, 8, 9}
    }

    assert all(not frame.empty for frame in filtered_by_entry.values())
    latest_whatsapp = [frame for (slide, _chart, _index), frame in filtered_by_entry.items() if slide == 8][2]
    assert latest_whatsapp['sample'].tolist() == ['whatsapp-latest']


def test_layout_chart_frames_are_always_ordered_by_visual_rows_then_columns() -> None:
    presentation = Presentation('assets/ppt-templates/Template_CDR_analysis.pptx')
    layout = _named_slide_layout(presentation, 'Title and 2 columns and 2 rows + Comments right')

    frames = _layout_chart_frames(layout)

    assert len(frames) == 4
    assert frames[0][0] < frames[1][0]
    assert frames[0][1] < frames[2][1]
    assert frames[2][0] < frames[3][0]


def test_failure_count_uses_row_and_column_hierarchies_without_flattening() -> None:
    entry = with_default_calculated_dimensions(parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n9,Voice failures per Q/city,,Title and 1 column + Comments,Failures,CDR-Voice,Call_Status,Count Stacked Horizontal Bars,,Call Family × G Level 4,Operator × Campaign,Failed/Dropped,\n',
        'nsa',
    )[0])
    frame = chart_frame({
        'Session_Type': ['VoLTE', 'VoLTE', 'MultiRAB CALL'],
        'G_Level_4': ['London', 'London', 'Belfast'],
        'Operator': ['EE', 'EE', '3'],
        'Campaign': ['Q2', 'Q2', 'Q3'],
        'Call_Status': ['Failed', 'Dropped', 'Failed'],
    })
    grouped, primary, series = _apply_catalog_grouping(frame, entry, False, 'Call_Status')

    with patch('src.modules.cdr_reporting._render_failure_count_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'nested-failure-chart')
        chart = _render_failure_count('Voice failures per Q/city', grouped, primary, series)

    assert chart.getvalue() == b'nested-failure-chart'
    assert hierarchy_renderer.call_args.args[2] == ['__catalog_row_0', '__catalog_row_1']
    assert hierarchy_renderer.call_args.args[3] == ['__catalog_column_0', '__catalog_column_1']


def test_failure_count_hover_targets_cover_rendered_horizontal_segments() -> None:
    entry = with_default_calculated_dimensions(parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n9,Voice failures per Q/city,,Title and 1 column + Comments,Failures,CDR-Voice,Call_Status,Count Stacked Horizontal Bars,,Call Family × G Level 4,Operator × Campaign,Failed/Dropped,Right\n',
        'nsa',
    )[0])
    frame = chart_frame({
        'Session_Type': ['VoLTE', 'VoLTE', 'VoLTE'], 'G_Level_4': ['London', 'London', 'Belfast'],
        'Operator': ['EE', 'EE', '3'], 'Campaign': ['Q2', 'Q2', 'Q3'],
        'Call_Status': ['Failed', 'Dropped', 'Completed'],
    })

    targets = catalog_chart_hover_targets(frame, entry)

    assert {(target['legend'], target['value']) for target in targets} == {('Failed', '1'), ('Dropped', '1')}
    assert all(target['width'] > 0 and target['height'] > 0 for target in targets)


def test_failure_count_hover_targets_use_the_renderer_width_for_field_legends() -> None:
    entry = with_default_calculated_dimensions(parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n9,Voice failures,,Title and 1 column + Comments,Failures,CDR-Voice,Call_Status,Count Stacked Horizontal Bars,,Call Family,Operator × Campaign,Call_Status,Right\n',
        'nsa',
    )[0])
    frame = chart_frame({
        'Session_Type': ['VoLTE', 'VoLTE'], 'Operator': ['EE', '3'],
        'Campaign': ['Q2', 'Q2'], 'Call_Status': ['Failed', 'Failed'],
    })

    targets = catalog_chart_hover_targets(frame, entry)

    # A field legend is resolved after rendering, so the horizontal plot keeps
    # the full 1250-pixel renderer width instead of reserving a right lane.
    assert sorted(target['x'] for target in targets) == [289.0, 914.0]


def test_status_100_hover_targets_support_multi_level_row_grouping() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n12,Success Ratio per Type of Test (Vendor Split),,Title and 1 column + Comments,Success Ratio per Type of Test (Vendor Split),CDR-Data,Result Group,100% Stacked Vertical Bars,,Type_of_Test × Vendor,,Result Group,Right\n',
        'nsa',
    )[0]
    frame = chart_frame({
        'Type_of_Test': ['FTP', 'HTTP', 'FTP', 'HTTP'],
        'Vendor': ['EE', 'EE', '3', '3'],
        'Result Group': ['Completed', 'Failed', 'Completed', 'Cutoff'],
    })

    targets = catalog_chart_hover_targets(frame, entry)

    assert len(targets) == 12
    assert {target['label'] for target in targets} == {'FTP · EE', 'HTTP · EE', 'FTP · 3', 'HTTP · 3'}
    assert any(target['height'] > 0 for target in targets)


def test_status_100_hover_targets_support_tableau_dashboard_geography_hierarchy() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n1,SR Dashboard,,Title and 3 columns + Comments,Success Ratio per glevel,CDR-Data,Result Group,100% Stacked Vertical Bars,,G_Level_2 × G_Level_1 × Operator,,Result Group,Right\n',
        'nsa',
    )[0]
    frame = chart_frame({
        'G_Level_2': ['England', 'England', 'Scotland', 'Scotland'],
        'G_Level_1': ['North', 'North', 'Central', 'Central'],
        'Operator': ['EE', '3', 'EE', '3'],
        'Result Group': ['Completed', 'Failed', 'Completed', 'Cutoff'],
    })

    targets = catalog_chart_hover_targets(frame, entry)

    assert len(targets) == 12
    assert {target['label'] for target in targets} == {
        'England · North · EE', 'England · North · 3',
        'Scotland · Central · EE', 'Scotland · Central · 3',
    }
    assert any(target['height'] > 0 for target in targets)


def test_cdf_hover_targets_use_the_same_clipped_domain_as_the_renderer() -> None:
    entry = CatalogEntry(
        13, 'POLQA CDF', '', '', '', 'CDR-Speech', 'LQ', 'CDF Line', 'Operator × Campaign', '', 'Operator', 'Campaign', 'Top',
    )
    # 100 / 101 samples exceeds 99%, so the common terminal value remains
    # inside the clipped renderer domain under the stricter CDF policy.
    values = list(range(1, 101)) + [1000]
    frame = chart_frame({
        'Session_Type': ['WhatsApp CALL'] * 303, 'Operator': ['VF'] * 101 + ['3'] * 101 + ['EE'] * 101,
        'Campaign': ['UK_Q2_2026'] * 303, 'LQ': values * 3,
    })

    targets = catalog_chart_hover_targets(frame, entry)
    low = 1.0
    high = _cdf_terminal_x_maximum([values, values, values], low, 1000.0)
    left, top, width, height = _cdf_plot_geometry('top')
    vf_last = [target for target in targets if target['legend'].startswith('VF')][-1]

    assert vf_last['x'] == pytest.approx(left + (100.0 - low) / (high - low) * width)
    assert vf_last['y'] == pytest.approx(top + height - 100 / 101 * height)
    assert all(target['x'] <= left + width for target in targets)


def test_cdf_hover_targets_are_bounded_per_series() -> None:
    entry = CatalogEntry(
        13, 'POLQA CDF', '', '', '', 'CDR-Speech', 'LQ', 'CDF Line', 'Operator', '', 'Operator', '', 'Top',
    )
    frame = chart_frame({
        'Session_Type': ['WhatsApp CALL'] * 2_000,
        'Operator': ['VF'] * 1_000 + ['EE'] * 1_000,
        'LQ': list(range(1_000)) * 2,
    })

    targets = catalog_chart_hover_targets(frame, entry)

    assert len([target for target in targets if target['legend'].startswith('VF')]) == 120
    assert len([target for target in targets if target['legend'].startswith('EE')]) == 120


def test_failure_count_keeps_zero_count_hierarchy_categories_from_all_filtered_rows() -> None:
    entry = with_default_calculated_dimensions(parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n9,Voice failures,,Title and 1 column + Comments,Failures,CDR-Voice,Call_Status,Count Stacked Horizontal Bars,,Call Family,Operator × Campaign,Failed/Dropped,\n',
        'nsa',
    )[0])
    frame = chart_frame({
        'Session_Type': ['VoLTE', 'VoLTE'], 'Operator': ['Vodafone', '3'],
        'Campaign': ['Q2', 'Q2'], 'Call_Status': ['Completed', 'Completed'],
    })
    grouped, primary, series = _apply_catalog_grouping(frame, entry, False, 'Call_Status')

    with patch('src.modules.cdr_reporting._render_failure_count_hierarchy') as hierarchy_renderer:
        hierarchy_renderer.return_value = BytesIO(b'zero-count-grid')
        chart = _render_failure_count('Voice failures', grouped, primary, series)

    assert chart.getvalue() == b'zero-count-grid'
    assert hierarchy_renderer.call_args.kwargs['comparison_frame'] is grouped
    assert hierarchy_renderer.call_args.args[1].empty


def test_failure_count_keeps_explicit_in_filter_categories_with_zero_matching_rows() -> None:
    entry = CatalogEntry(
        4, 'Failures', '', '', '', 'CDR-Voice', 'Call_Status', 'Count Stacked Horizontal Bars', '',
        'Call_Status IN (Failed, Dropped); G Level 4 IN (Belfast, Bristol, Cardiff)',
        'Call Family × G Level 4', 'Operator × Campaign',
    )
    frame = chart_frame({
        'Call Family': ['VoLTE'], 'G_Level_4': ['Belfast'], 'Operator': ['EE'],
        'Campaign': ['2026 Q2'], 'Call_Status': ['Failed'],
    })

    filtered = _apply_catalog_filters(frame, entry, False, 'Call_Status')
    grouped, _primary, _series = _apply_catalog_grouping(filtered, entry, False, 'Call_Status')

    assert grouped.attrs['catalogue_dimension_values']['__catalog_row_1'] == ['Belfast', 'Bristol', 'Cardiff']
    assert _hierarchical_complete_keys(grouped, ['__catalog_row_0', '__catalog_row_1']) == [
        ('VoLTE', 'Belfast'), ('VoLTE', 'Bristol'), ('VoLTE', 'Cardiff'),
    ]


def test_failure_hierarchy_reserves_a_right_legend_lane() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['VoLTE'],
        '__catalog_column_0': ['Vodafone'],
        '__catalog_column_1': ['2026 Q2'],
        '__catalog_failure_state': ['Failed'],
    })

    with patch('src.modules.cdr_reporting._draw_chart_legend') as draw_legend:
        _render_failure_count_hierarchy(
            'Voice failures per Q/city', frame,
            ['__catalog_row_0'], ['__catalog_column_0', '__catalog_column_1'],
            legend_position='right',
        )

    assert draw_legend.call_args.kwargs['side_x'] == 1289


def test_failure_hierarchy_uses_dashed_child_boundaries_within_one_operator() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['VoLTE', 'VoLTE'],
        '__catalog_column_0': ['Vodafone', 'Vodafone'],
        '__catalog_column_1': ['2026 Q2', '2026 Q1'],
        '__catalog_failure_state': ['Failed', 'Dropped'],
    })

    with patch('src.modules.cdr_reporting._draw_dashed_vertical_line') as draw_dashed:
        _render_failure_count_hierarchy(
            'Voice failures per campaign', frame,
            ['__catalog_row_0'], ['__catalog_column_0', '__catalog_column_1'],
        )

    assert draw_dashed.call_count == 1


def test_failure_hierarchy_uses_dashed_child_boundaries_within_one_row_group() -> None:
    frame = chart_frame({
        '__catalog_row_0': ['VoLTE', 'VoLTE', 'MultiRAB'],
        '__catalog_row_1': ['Belfast', 'Bristol', 'Belfast'],
        '__catalog_column_0': ['VF', 'VF', 'VF'],
        '__catalog_failure_state': ['Failed', 'Dropped', 'Failed'],
    })

    with patch('src.modules.cdr_reporting._draw_dashed_horizontal_line') as draw_dashed:
        _render_failure_count_hierarchy(
            'Voice failures per city', frame,
            ['__catalog_row_0', '__catalog_row_1'], ['__catalog_column_0'],
        )

    assert draw_dashed.call_count == 1
    assert draw_dashed.call_args.args[2] == 20 + (285 - 28) / 2


def test_nsa_catalogue_splits_template_screenshots_into_individual_charts() -> None:
    entries = [with_default_calculated_dimensions(entry) for entry in load_catalog_csv(Path(__file__).parent / 'fixtures' / 'NSA Slide Template.csv', 'nsa')]
    slide_ten = [entry for entry in entries if entry.slide == 10]
    slide_thirteen = [entry for entry in entries if entry.slide == 13]

    assert len(slide_ten) == 2
    assert {entry.layout for entry in slide_ten} == {'Title and 2 columns + Comments'}
    assert len(slide_thirteen) == 3
    assert {entry.layout for entry in slide_thirteen} == {'Title and 3 columns + Comments'}
    assert {slide: sum(entry.slide == slide for entry in entries) for slide in range(12, 17)} == {
        12: 2, 13: 3, 14: 3, 15: 4, 16: 2,
    }


def test_catalogue_uses_explicit_title_and_transition_slides() -> None:
    entries = [with_default_calculated_dimensions(entry) for entry in load_catalog_csv(Path(__file__).parent / 'fixtures' / 'NSA Slide Template.csv', 'nsa')]
    structural = [entry.chart_type for entry in entries if not entry.source_kind]
    title = next(entry for entry in entries if entry.slide == 1)
    conclusions = next(entry for entry in entries if entry.slide == 17)

    assert set(structural) == {'Title Slide', 'Transition Slide'}
    assert (title.chart_type, title.layout) == ('Title Slide', 'Title Page')
    assert (conclusions.chart_type, conclusions.layout) == ('Transition Slide', 'Title Only')


def test_catalogue_rows_use_matching_master_image_placeholders(tmp_path) -> None:
    catalogue = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,Voice quality,Title and 2 rows + Comments right,Status ratio,CDR-Voice,Call_Status,100% Stacked Vertical Bars,Call Family = VoLTE,Call Family,Operator × Campaign,Completed/Dropped/Failed,'
        + '\n8,Completed Call Ratio,Voice quality,Title and 2 rows + Comments right,Setup time,CDR-Voice,Call_Setup_Time,Average Vertical Bars,,Call Family = VoLTE,Call Family,Operator × Campaign\n'
    ).encode('utf-8')
    frames = {
        'data': pd.DataFrame(),
        'speech': pd.DataFrame(),
        'voice': pd.DataFrame({
            'Campaign': ['Q1'], 'Operator': ['EE'], 'Session_Type': ['VoLTE'],
            'Call_Status': ['Completed'], 'Call_Setup_Time': [1.2],
        }),
    }
    destination = tmp_path / 'catalogue-layout.pptx'

    render_cdr_report(
        destination,
        Path('assets/ppt-templates/Template_CDR_analysis.pptx'),
        frames,
        'nsa',
        False,
        [with_default_calculated_dimensions(entry) for entry in parse_catalog_csv(catalogue, 'nsa')],
        chart_output_dir=tmp_path / 'charts',
    )

    generated = Presentation(destination)
    assert len(generated.slides) == 1
    slide = generated.slides[0]
    assert slide.slide_layout.name == 'Title and 2 rows + Comments right'
    pictures = sorted((shape for shape in slide.shapes if hasattr(shape, 'image')), key=lambda shape: shape.top)
    assert len(pictures) >= 2
    assert pictures[0].top < pictures[1].top
    comments = next(shape for shape in slide.placeholders if shape.placeholder_format.idx == 10)
    layout_comments = next(shape for shape in slide.slide_layout.placeholders if shape.placeholder_format.idx == 10)
    assert (comments.left, comments.top, comments.width, comments.height) == (
        layout_comments.left, layout_comments.top, layout_comments.width, layout_comments.height,
    )
    title_shape = next(
        shape for shape in slide.shapes
        if getattr(shape, 'has_text_frame', False) and getattr(shape, 'is_placeholder', False)
        and shape.placeholder_format.type in {1, 3}
    )
    assert [paragraph.text for paragraph in title_shape.text_frame.paragraphs] == ['Completed Call Ratio', 'Voice quality']
    subtitle_paragraph = title_shape.text_frame.paragraphs[1]
    assert subtitle_paragraph.font.size.pt == 16
    assert subtitle_paragraph.font.color.rgb == RGBColor(36, 90, 150)
    assert not any(shape.name == 'catalogue-subtitle' for shape in slide.shapes)
    manifest = json.loads((tmp_path / 'charts' / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['generate_tooltips'] is True
    assert manifest['hover_targets_version'] == 3
    assert all((tmp_path / 'charts' / chart['hover_file']).is_file() for chart in manifest['charts'])


def test_layout_only_template_builds_one_new_slide_per_catalogue_number(tmp_path) -> None:
    template = Path('assets/ppt-templates/Template_CDR_analysis.pptx')
    assert len(Presentation(template).slides) == 0
    catalogue = (
        ','.join(CATALOG_HEADERS)
        + '\n1,Quarterly report,NSA analysis,Title Page,,,,Title Slide,,,,,'
        + '\n2,Voice section,Seven cities,Title Only,,,,Transition Slide,,,,'
        + '\n8,Completed Call Ratio,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,,Operator,Campaign\n'
    )
    destination = tmp_path / 'catalogue-built.pptx'

    render_cdr_report(
        destination,
        template,
        {'data': pd.DataFrame(), 'speech': pd.DataFrame(), 'voice': pd.DataFrame()},
        'nsa',
        False,
        parse_catalog_csv(catalogue, 'nsa'),
    )

    generated = Presentation(destination)
    assert len(generated.slides) == 3
    assert [slide.slide_layout.name for slide in generated.slides] == [
        'Title Page', 'Title Only', 'Title and 1 column + Comments',
    ]
    assert generated.slides[0].placeholders[0].text == 'Quarterly report'
    assert generated.slides[0].placeholders[1].text == 'NSA analysis'


def test_powerpoint_report_can_disable_tooltip_sidecars(tmp_path) -> None:
    catalogue = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,,Operator,Campaign\n',
        'nsa',
    )
    chart_directory = tmp_path / 'charts'

    render_cdr_report(
        tmp_path / 'without-tooltips.pptx',
        Path('assets/ppt-templates/Template_CDR_analysis.pptx'),
        {'data': pd.DataFrame(), 'speech': pd.DataFrame(), 'voice': pd.DataFrame({
            'Campaign': ['Q1'], 'Operator': ['EE'], 'Call_Status': ['Completed'],
        })},
        'nsa', False, catalogue, chart_output_dir=chart_directory, generate_tooltips=False,
    )

    manifest = json.loads((chart_directory / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['generate_tooltips'] is False
    assert not list(chart_directory.glob('*.hover.json'))


def test_reporting_module_is_available_to_authenticated_users(client) -> None:
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert response.status_code == 303

    page = client.get('/reporting')

    assert page.status_code == 200
    assert 'NetCheck CDR Reports' in page.text
    assert 'Total Reports: 0' in page.text
    assert 'Total Chart Sets: 0' in page.text
    assert 'Smart Orchestrator Logs Reports' in page.text
    assert 'data-reporting-module' in page.text
    assert 'data-reporting-module-panel="cdr"' in page.text
    assert 'data-reporting-module-panel="logs"' in page.text
    assert 'Generate PowerPoint Report' in page.text
    assert 'name="vodafone_mapping_dataset_id"' not in page.text
    assert 'name="three_mapping_dataset_id"' not in page.text
    assert '<option value="multivendor" disabled>Multivendor Comparison</option>' in page.text
    assert 'name="slides_templates"' in page.text
    assert 'value="nsa:NSA Slide Template"' in page.text
    assert 'data-report-job-form' in page.text
    assert 'name="data_dataset_id" multiple required' not in page.text
    assert 'data-reporting-filter-panel="charts"' in page.text
    assert 'data-reporting-filter-panel="jobs"' not in page.text
    assert 'data-report-job-datasets-dialog' in page.text
    assert 'data-report-job-datasets-tooltip' in page.text
    assert page.text.count('data-reporting-job-filter="tech"') == 1
    assert page.text.count('data-reporting-job-filter="type"') == 1
    assert page.text.count('data-reporting-job-filter="template"') == 1
    assert page.text.count('data-reporting-job-filter="scope"') == 1
    assert 'data-report-multicampaign-dialog' in page.text
    assert 'Review selected campaigns' in page.text
    assert 'latest selected CDR for each type is preselected' in page.text
    assert 'campaignPeriod' in page.text
    assert 'uploadedRecency' in page.text
    assert 'latestCampaignOption' in page.text
    assert "select.dispatchEvent(new Event('change', {bubbles: true}))" in page.text
    assert 'Reports and Charts Jobs' in page.text
    assert '<th>NR Mode</th><th>Type</th><th>Template</th>' in page.text
    assert '<th>Report Name</th>' not in page.text
    assert 'data-report-job-stop' in page.text
    assert 'data-report-chart-job-stop' in page.text


def test_processing_report_and_chart_jobs_can_be_stopped_then_deleted(client) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    report_id = app_module.repository.create_report_job(
        report_type='netcheck_cdr', technology='nsa', scope='single',
        data_dataset_id=1, voice_dataset_id=2, speech_dataset_id=3,
        dataset_ids={'data': [1], 'voice': [2], 'speech': [3]},
        dataset_names={'data': ['Data'], 'voice': ['Voice'], 'speech': ['Speech']},
        slide_count=1, template_name='NSA Slide Template', output_file='stop-test.pptx',
        output_path=app_module.settings.output_dir / 'reports' / 'stop-test.pptx', created_by='admin',
    )
    assert app_module.repository.get_report_run(report_id)['generate_tooltips'] == 1
    app_module.repository.update_report_job(report_id, status='processing', progress=40)
    stopped_report = client.post(f'/reporting/jobs/{report_id}/stop')
    assert stopped_report.status_code == 200
    report = next(item for item in client.get('/api/e2e-reporting/jobs').json()['jobs'] if item['id'] == report_id)
    assert report['status'] == 'stopped'
    assert report['duration_seconds'] is not None
    assert report['duration_label'].endswith('s')
    assert report['stop_url'] is None
    assert report['retry_url'] == f'/e2e-reporting/jobs/{report_id}/retry'
    assert client.post(report['delete_url']).status_code == 200

    chart_id = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={'data': [1], 'voice': [2], 'speech': [3]},
        dataset_names={'data': ['Data'], 'voice': ['Voice'], 'speech': ['Speech']},
        template_name='NSA Slide Template', created_by='admin', generate_tooltips=False,
    )
    assert app_module.repository.get_report_chart_job(chart_id)['generate_tooltips'] == 0
    app_module.repository.update_report_chart_job(chart_id, status='processing', progress=40)
    stopped_chart = client.post(f'/reporting/chart-jobs/{chart_id}/stop')
    assert stopped_chart.status_code == 200
    chart = next(item for item in client.get('/api/e2e-reporting/chart-jobs').json()['jobs'] if item['id'] == chart_id)
    assert chart['status'] == 'stopped'
    assert chart['duration_seconds'] is not None
    assert chart['duration_label'].endswith('s')
    assert chart['stop_url'] is None
    assert chart['retry_url'] == f'/e2e-reporting/chart-jobs/{chart_id}/retry'
    assert client.post(chart['delete_url']).status_code == 200


def test_chart_set_selector_excludes_published_but_processing_job(client) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    chart_set = app_module.persist_report_charts(
        'NSA Slide Template', 'single',
        [({'slide': 1, 'title': 'Completed chart', 'source': 'data', 'chart_type': 'Bar'}, b'PNG')],
        {'data': 1, 'voice': 1, 'speech': 1},
    )
    assert (app_module.report_charts_directory() / chart_set['generation']).is_dir()
    assert chart_set['generation'].startswith(
        datetime.strptime(chart_set['generated_at'], '%Y-%m-%d %H:%M:%S').strftime('%Y%m%d-%H%M%S')
    )
    job_id = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={'data': [1], 'voice': [2], 'speech': [3]},
        dataset_names={'data': ['Data'], 'voice': ['Voice'], 'speech': ['Speech']},
        template_name='NSA Slide Template', created_by='admin',
    )
    app_module.repository.update_report_chart_job(job_id, status='processing', generation=chart_set['generation'])
    selector_value = f'value="standalone:{chart_set["generation"]}"'
    assert selector_value not in client.get('/reporting').text

    app_module.repository.update_report_chart_job(job_id, status='ready', progress=100, finished=True)
    assert selector_value in client.get('/reporting').text


def test_persisted_chart_set_keeps_template_order_when_rendered_by_cdr_source(client) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    chart_set = app_module.persist_report_charts(
        'NSA Slide Template', 'single',
        [
            ({'order': 2, 'slide': 3, 'title': 'Speech chart', 'source': 'speech', 'chart_type': 'Bar'}, b'SPEECH'),
            ({'order': 0, 'slide': 1, 'title': 'Data chart', 'source': 'data', 'chart_type': 'Bar'}, b'DATA'),
            ({'order': 1, 'slide': 2, 'title': 'Voice chart', 'source': 'voice', 'chart_type': 'Bar'}, b'VOICE'),
        ],
        {'data': 1, 'voice': 1, 'speech': 1},
    )

    manifest = json.loads((app_module.report_charts_directory() / chart_set['generation'] / 'manifest.json').read_text(encoding='utf-8'))
    assert [chart['title'] for chart in manifest['charts']] == ['Data chart', 'Voice chart', 'Speech chart']
    assert [chart['file'] for chart in manifest['charts']] == ['chart-001.png', 'chart-002.png', 'chart-003.png']


def test_chart_set_persists_precomputed_hover_targets(client) -> None:
    import src.DashboardAnalytic as app_module

    chart_set = app_module.persist_report_charts(
        'NSA Slide Template', 'single',
        [({'slide': 1, 'title': 'Chart', 'source': 'data', 'chart_type': 'Bar', 'hover_targets': [{'kind': 'bar', 'x': 1}]}, b'PNG')],
        {'data': 1, 'voice': 1, 'speech': 1},
    )

    assert app_module._stored_chart_hover_targets(chart_set['generation'], 0) == [{'kind': 'bar', 'x': 1}]


def test_chart_set_ignores_obsolete_hover_target_geometry(client) -> None:
    import src.DashboardAnalytic as app_module

    chart_set = app_module.persist_report_charts(
        'NSA Slide Template', 'single',
        [({'slide': 1, 'title': 'Chart', 'source': 'data', 'chart_type': 'Bar', 'hover_targets': [{'kind': 'bar', 'x': 1}]}, b'PNG')],
        {'data': 1, 'voice': 1, 'speech': 1},
    )
    manifest_path = app_module.report_charts_directory() / chart_set['generation'] / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['hover_targets_version'] = 1
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    assert app_module._stored_chart_hover_targets(chart_set['generation'], 0) is None


def test_chart_set_can_disable_tooltips_without_creating_sidecars(client) -> None:
    import src.DashboardAnalytic as app_module

    chart_set = app_module.persist_report_charts(
        'NSA Slide Template', 'single',
        [({'slide': 1, 'title': 'Chart', 'source': 'data', 'chart_type': 'Bar'}, b'PNG')],
        {'data': 1, 'voice': 1, 'speech': 1},
        generate_tooltips=False,
    )
    generation_dir = app_module.report_charts_directory() / chart_set['generation']
    manifest = json.loads((generation_dir / 'manifest.json').read_text(encoding='utf-8'))

    assert manifest['generate_tooltips'] is False
    assert not list(generation_dir.glob('*.hover.json'))
    assert app_module._chart_set_tooltips_enabled(chart_set['generation']) is False


def test_chart_set_writes_sidecars_directly_to_its_final_generation(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    published: list[str] = []

    def rendered_charts():
        generation = published[0]
        assert (tmp_path / 'charts' / generation).is_dir()
        assert not list((tmp_path / 'charts').glob('.report-charts-*'))
        yield ({
            'slide': 1, 'title': 'Chart', 'source': 'data', 'chart_type': 'Bar',
            'hover_targets': [{'kind': 'bar', 'x': 1}],
        }, b'PNG')

    chart_set = app_module.persist_report_charts(
        'NSA Slide Template', 'single', rendered_charts(),
        {'data': 1, 'voice': 0, 'speech': 0}, tmp_path,
        before_publish=published.append,
    )

    generation_dir = tmp_path / 'charts' / chart_set['generation']
    assert (generation_dir / 'chart-001.png').read_bytes() == b'PNG'
    assert json.loads((generation_dir / 'chart-001.hover.json').read_text(encoding='utf-8')) == [{'kind': 'bar', 'x': 1}]


def test_interrupted_chart_set_reuses_only_verified_assets(tmp_path: Path) -> None:
    import src.DashboardAnalytic as app_module

    directory = tmp_path / 'charts' / '20260914-120000'
    directory.mkdir(parents=True)
    # Valid 1×1 transparent PNG; the second file mimics an interrupted write.
    image = Image.new('RGBA', (1, 1))
    image.save(directory / 'chart-001.png', format='PNG')
    directory.joinpath('chart-001.hover.json').write_text('[{"kind":"point"}]', encoding='utf-8')
    directory.joinpath('chart-002.png').write_bytes(b'incomplete')
    entries = [
        CatalogEntry(1, '', '', '', 'One', 'CDR-Data', 'KPI', 'CDF Line', '', '', '', '', 'Top'),
        CatalogEntry(1, '', '', '', 'Two', 'CDR-Data', 'KPI', 'CDF Line', '', '', '', '', 'Top'),
    ]

    reusable = app_module._load_reusable_chart_set_assets(directory, entries, True)

    assert reusable[0][0].startswith(b'\x89PNG')
    assert reusable[0][1] == [{'kind': 'point'}]
    assert 1 not in reusable
    assert not (directory / 'chart-002.png').exists()


def test_retrying_a_failed_chart_job_reuses_its_row(client) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    job_id = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={'data': [], 'voice': [], 'speech': []},
        dataset_names={}, template_name='NSA Slide Template', created_by='admin',
    )
    app_module.repository.update_report_chart_job(job_id, status='failed', progress=100, last_error='Synthetic failure', finished=True)
    before_ids = [row['id'] for row in app_module.repository.list_report_chart_jobs(limit=None)]

    response = client.post(f'/reporting/chart-jobs/{job_id}/retry')

    assert response.status_code == 400
    assert response.json()['detail'] == 'The Chart Set job does not contain any selected CDR.'
    assert [row['id'] for row in app_module.repository.list_report_chart_jobs(limit=None)] == before_ids


def test_deleting_a_ready_chart_job_removes_its_chart_set(client) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    chart_set = app_module.persist_report_charts(
        'NSA Slide Template', 'single',
        [({'slide': 1, 'title': 'Chart', 'source': 'data', 'chart_type': 'Bar'}, b'PNG')],
        {'data': 1, 'voice': 1, 'speech': 1},
    )
    job_id = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={'data': [], 'voice': [], 'speech': []},
        dataset_names={}, template_name='NSA Slide Template', created_by='admin',
    )
    app_module.repository.update_report_chart_job(
        job_id, status='ready', progress=100, generation=chart_set['generation'], finished=True,
    )

    deleted = client.post(f'/reporting/chart-jobs/{job_id}/delete')

    assert deleted.status_code == 200
    assert deleted.json()['generation'] == chart_set['generation']
    assert not (app_module.report_charts_directory() / chart_set['generation']).exists()


def test_reporting_multivendor_requires_a_previously_mapped_selected_cdr(client) -> None:
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploads = [
        ('NetCheck_CDR_Data.csv', 'data', b'RAT,Operator,Mean_Data_Rate\nENDC,Vodafone UK,42\n'),
        ('NetCheck_CDR_Voice.csv', 'voice', b'RAT_A,Operator,Call_Duration\nENDC,Vodafone UK,60\n'),
        ('NetCheck_CDR_Speech.csv', 'speech', b'Sample_RAT_A,Operator,LQ\nENDC,Vodafone UK,3.8\n'),
    ]
    for filename, dataset_kind, content in uploads:
        response = client.post(
            '/datasets-analysis/upload',
            data={'dataset_kinds': dataset_kind},
            files={'dataset_files': (filename, BytesIO(content), 'text/csv')},
        )
        assert response.status_code == 200

    page = client.get('/reporting')
    assert page.status_code == 200
    assert 'data-vendor-mapped="false"' in page.text
    report = client.post('/reporting/netcheck-cdr', data={
        'data_dataset_id': 1, 'voice_dataset_id': 2, 'speech_dataset_id': 3,
        'technology': 'nsa', 'report_scope': 'multivendor',
    })
    assert report.status_code == 400
    assert 'requires every selected Data, Voice and Speech CDR to have a Workspace Vendor mapping' in report.text


def test_netcheck_reporting_generates_template_backed_pptx(client) -> None:
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploads = [
        ('NetCheck_CDR_Data.csv', b'RAT,Operator,Mean_Data_Rate,Test_Result\nENDC,Vodafone UK,42,Success\n', 'text/csv'),
        ('NetCheck_CDR_Voice.csv', b'RAT_A,Operator,Call_Status,Call_Duration\nENDC,Vodafone UK,Completed,60\n', 'text/csv'),
        ('NetCheck_CDR_Speech.csv', b'Sample_RAT_A,Operator,LQ\nENDC,Vodafone UK,3.8\n', 'text/csv'),
    ]
    for filename, content, media_type in uploads:
        response = client.post('/datasets-analysis/upload', files={'dataset_files': (filename, BytesIO(content), media_type)})
        assert response.status_code == 200

    report = client.post('/reporting/netcheck-cdr', data={
        'data_dataset_id': 1,
        'voice_dataset_id': 2,
        'speech_dataset_id': 3,
        'technology': 'nsa',
        'report_scope': 'single',
        'slides_templates': 'nsa:NSA Slide Template',
    })

    assert report.status_code == 202
    job = wait_for_report_job(client, report.json()['job_id'])
    import src.DashboardAnalytic as app_module

    assert job['status'] == 'ready'
    assert job['slides'] == 17
    assert re.fullmatch(r'\d{8}-\d{6}_NetCheck_CDR_NSA_operator-comparison\.pptx', job['report_name'])
    assert app_module._report_job_directory(job['report_name']).name == Path(job['report_name']).stem
    download = client.get(job['download_url'])
    assert download.status_code == 200
    assert download.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.presentationml.presentation')
    assert download.content[:2] == b'PK'
    opened = client.get(job['open_url'])
    assert opened.status_code == 200
    assert opened.headers['content-disposition'].startswith('inline;')
    stale_file = app_module._report_job_directory(job['report_name']) / 'stale-output.txt'
    stale_file.write_text('remove me', encoding='utf-8')
    relaunched = client.post(job['retry_url'])
    assert relaunched.status_code == 202
    assert relaunched.json()['job_id'] == job['id']
    rerun = wait_for_report_job(client, job['id'])
    assert rerun['status'] == 'ready'
    assert not stale_file.exists()
    assert [item['id'] for item in client.get('/api/e2e-reporting/jobs').json()['jobs']] == [job['id']]
    deleted = client.post(job['delete_url'])
    assert deleted.status_code == 200
    assert client.get(job['download_url']).status_code == 404


def test_reporting_chart_dataset_reuses_one_source_frame_and_projects_chart_columns(monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    first = CatalogEntry(
        slide=1, slide_title='Slide', slide_subtitle='', layout='', chart_title='First',
        cdr_source='CDR-Data', kpi='Metric_A', chart_type='Table', legend='', filters='',
        grouping_rows='Operator', grouping_columns='Campaign',
    )
    second = replace(first, chart_title='Second', kpi='Metric_B')
    loads: list[list[str]] = []
    monkeypatch.setattr(app_module, '_reporting_datasets', lambda *_args: [{
        'id': 7, 'dataset_kind': 'data', 'updated_at': '1', 'processed_at': '1',
        'normalization_version': '1',
    }])

    def load_shared(_datasets, _technology, entries, _multivendor):
        loads.append([entry.kpi for entry in entries])
        return pd.DataFrame({
            'Operator': ['VF'], 'Campaign': ['2026-Q3'], 'Metric_A': [1], 'Metric_B': [2],
        })

    monkeypatch.setattr(app_module, '_combined_reporting_frame', load_shared)
    app_module._clear_chart_preview_caches()

    first_key, first_frame = app_module._shared_reporting_preview_frame(
        [7], first, [first, second], 'nsa', False,
    )
    second_key, second_frame = app_module._shared_reporting_preview_frame(
        [7], second, [first, second], 'nsa', False,
    )

    assert first_key == second_key
    assert len(loads) == 1
    assert {'Operator', 'Campaign', 'Metric_A'} <= set(first_frame.columns)
    assert 'Metric_B' not in first_frame.columns
    assert {'Operator', 'Campaign', 'Metric_B'} <= set(second_frame.columns)
    assert 'Metric_A' not in second_frame.columns


def test_reporting_generates_template_chart_previews(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploads = [
        ('NetCheck_CDR_Data.csv', 'data', b'RAT,Operator,Mean_Data_Rate\nENDC,Vodafone UK,42\n'),
        ('NetCheck_CDR_Voice.csv', 'voice', b'RAT_A,Operator,Call_Status\nENDC,Vodafone UK,Completed\n'),
        ('NetCheck_CDR_Speech.csv', 'speech', b'Sample_RAT_A,Operator,LQ\nENDC,Vodafone UK,3.8\n'),
    ]
    for filename, kind, content in uploads:
        response = client.post(
            '/datasets-analysis/upload', data={'dataset_kinds': kind},
            files={'dataset_files': (filename, BytesIO(content), 'text/csv')},
        )
        assert response.status_code == 200

    rendered: list[tuple[str, bool]] = []

    def render_preview(frame, entry, *, multivendor=False, **_kwargs):
        rendered.append((entry.cdr_source, multivendor))
        return b'PNG'

    monkeypatch.setattr(app_module, 'render_catalog_chart_preview', render_preview)
    monkeypatch.setattr(app_module, 'report_chart_renderer_name', lambda: 'pil')
    response = client.post('/reporting/netcheck-cdr/charts', data={
        'data_dataset_id': 1, 'voice_dataset_id': 2, 'speech_dataset_id': 3,
        'technology': 'nsa', 'report_scope': 'single', 'slides_templates': 'nsa:NSA Slide Template',
    })

    assert response.status_code == 202
    job = wait_for_report_chart_job(client, response.json()['job_id'])
    assert job['status'] == 'ready'
    payload = client.get(job['open_url']).json()
    assert payload['template'] == 'NSA Slide Template'
    assert payload['scope'] == 'single'
    assert payload['dataset_counts'] == {'data': 1, 'voice': 1, 'speech': 1}
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', payload['generated_at'])
    assert job['date'] == payload['generated_at']
    assert payload['generation'] == datetime.strptime(payload['generated_at'], '%Y-%m-%d %H:%M:%S').strftime('%Y%m%d-%H%M%S')
    assert payload['charts']
    preview_context = client.get('/api/e2e-reporting/chart-preview/context', params={
        'source': 'standalone', 'identifier': payload['generation'], 'chart_index': 0,
    })
    assert preview_context.status_code == 200
    context_payload = preview_context.json()
    assert isinstance(context_payload['template_row_index'], int)
    assert context_payload['template_row_index'] >= 0
    assert context_payload['dataset_ids_by_source'] == {'cdr-data': ['1'], 'cdr-voice': ['2'], 'cdr-speech': ['3']}
    source_key = context_payload['cdr_source'].lower()
    expected_id = {'cdr-data': '1', 'cdr-voice': '2', 'cdr-speech': '3'}[source_key]
    assert context_payload['dataset_ids'] == [expected_id]
    assert context_payload['datasets_by_source']['cdr-data'] == [{'value': '1', 'label': 'NetCheck_CDR_Data.csv'}]
    assert context_payload['datasets_by_source']['cdr-voice'] == [{'value': '2', 'label': 'NetCheck_CDR_Voice.csv'}]
    dataset_preview = client.post('/api/e2e-reporting/chart-preview/data', json={
        'source': 'standalone', 'identifier': payload['generation'], 'chart_index': 0,
        'definition': {}, 'page': 0, 'page_size': 100, 'column_filters': {},
    })
    assert dataset_preview.status_code == 200, dataset_preview.text
    dataset_payload = dataset_preview.json()
    assert dataset_payload['page_size'] == 100
    assert dataset_payload['filter_values'] == {}
    assert set(dataset_payload['column_metadata']) == set(dataset_payload['columns'])
    assert all({'label', 'kind', 'rule', 'pinned', 'class_name'} <= set(item) for item in dataset_payload['column_metadata'].values())
    filter_values = client.post('/api/e2e-reporting/chart-preview/data', json={
        'source': 'standalone', 'identifier': payload['generation'], 'chart_index': 0,
        'definition': {}, 'page': 0, 'page_size': 100, 'column_filters': {},
        'filter_column': dataset_payload['columns'][0],
    })
    assert filter_values.status_code == 200, filter_values.text
    assert isinstance(filter_values.json()['filter_values'], list)
    dataset_export = client.post('/api/e2e-reporting/chart-preview/data', json={
        'source': 'standalone', 'identifier': payload['generation'], 'chart_index': 0,
        'definition': {}, 'column_filters': {}, 'download': True,
    })
    assert dataset_export.status_code == 200, dataset_export.text
    assert dataset_export.headers['content-type'].startswith('text/csv')
    assert 'attachment; filename="filtered-chart-dataset.csv"' == dataset_export.headers['content-disposition']
    assert dataset_payload['columns'][0] in dataset_export.text.splitlines()[0]
    wrong_id = next(value for value in ('1', '2', '3') if value != expected_id)
    invalid_dataset_type = client.post('/api/e2e-reporting/chart-preview', json={
        'source': 'standalone', 'identifier': payload['generation'], 'chart_index': 0,
        'definition': {'cdr_source': context_payload['cdr_source'], 'dataset_ids': [wrong_id]},
    })
    assert invalid_dataset_type.status_code == 400
    image_url = payload['charts'][0]['image_url']
    assert re.match(r'/e2e-reporting/charts/\d{8}-\d{6}/chart-\d+\.png\?v=', image_url)
    assert client.get(image_url).content == b'PNG'
    second = client.post('/reporting/netcheck-cdr/charts', data={
        'data_dataset_id': 1, 'voice_dataset_id': 2, 'speech_dataset_id': 3,
        'technology': 'nsa', 'report_scope': 'single', 'slides_templates': 'nsa:NSA Slide Template',
    })
    assert second.status_code == 202
    second_job = wait_for_report_chart_job(client, second.json()['job_id'])
    assert second_job['status'] == 'ready'
    second_payload = client.get(second_job['open_url']).json()
    assert second_payload['generation'] != payload['generation']
    assert client.get(f"/api/e2e-reporting/chart-sets/{payload['generation']}").status_code == 200
    deleted = client.post(f"/reporting/chart-sets/{second_payload['generation']}/delete")
    assert deleted.status_code == 200
    assert [item['generation'] for item in deleted.json()['chart_sets']] == [payload['generation']]
    assert client.get(image_url).content == b'PNG'
    page = client.get('/reporting')
    assert image_url in page.text
    assert 'Operator Comparison' in page.text
    assert '(Data:1 | Voice:1 | Speech:1)' in page.text
    assert 'Delete Selected Charts Set' in page.text
    assert 'Delete All Charts Sets' in page.text
    assert 'data-report-chart-viewer' in page.text
    assert 'data-report-chart-viewer-canvas' in page.text
    assert 'data-report-chart-zoom-reset' in page.text
    assert rendered and all(multivendor is False for _, multivendor in rendered)
    orphaned_job = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={}, dataset_names={},
        template_name='Interrupted Chart Set', created_by='admin',
    )
    orphaned_directory = app_module.report_charts_directory() / '.incomplete-chart-set'
    orphaned_directory.mkdir(parents=True)
    (orphaned_directory / 'partial.png').write_bytes(b'partial')
    cleared = client.post('/reporting/chart-sets/delete-all')
    assert cleared.status_code == 202
    deletion_id = cleared.json()['job_id']
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        deletion = client.get(f'/api/e2e-reporting/bulk-deletions/{deletion_id}')
        assert deletion.status_code == 200
        if deletion.json()['status'] in {'ready', 'failed'}:
            break
        time.sleep(0.01)
    assert deletion.json()['status'] == 'ready'
    assert deletion.json()['total'] == 2
    assert app_module.repository.get_report_chart_job(orphaned_job) is None
    assert app_module.repository.list_report_chart_jobs(limit=None) == []
    assert list(app_module.report_charts_directory().iterdir()) == []
    assert client.get(f"/api/e2e-reporting/chart-sets/{payload['generation']}").status_code == 404


def test_reporting_accepts_partial_cdr_sources_and_marks_missing_chart_sources(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploaded = client.post(
        '/datasets-analysis/upload', data={'dataset_kinds': 'data'},
        files={'dataset_files': ('NetCheck_CDR_Data.csv', BytesIO(b'RAT,Operator,Mean_Data_Rate,Test_Result\nENDC,Vodafone UK,42,Success\n'), 'text/csv')},
    )
    assert uploaded.status_code == 200
    rendered_sources: list[str] = []

    def render_preview(frame, entry, *, multivendor=False, **_kwargs):
        rendered_sources.append(entry.cdr_source)
        return b'PNG'

    monkeypatch.setattr(app_module, 'render_catalog_chart_preview', render_preview)
    monkeypatch.setattr(app_module, 'report_chart_renderer_name', lambda: 'pil')
    response = client.post('/reporting/netcheck-cdr/charts', data={
        'data_dataset_id': 1, 'technology': 'nsa', 'report_scope': 'single',
        'slides_templates': 'nsa:NSA Slide Template',
    })
    assert response.status_code == 202
    job = wait_for_report_chart_job(client, response.json()['job_id'])
    assert job['status'] == 'ready'
    payload = client.get(job['open_url']).json()
    assert payload['technology'] == 'NSA'
    assert payload['dataset_counts'] == {'data': 1, 'voice': 0, 'speech': 0}
    assert rendered_sources and set(rendered_sources) == {'CDR-Data'}
    unavailable_index = next(index for index, chart in enumerate(payload['charts']) if chart['source'] in {'CDR-Voice', 'CDR-Speech'})
    unavailable_image = client.get(payload['charts'][unavailable_index]['image_url'])
    assert unavailable_image.status_code == 200
    assert unavailable_image.content.startswith(b'\x89PNG')
    context = client.get('/api/e2e-reporting/chart-preview/context', params={
        'source': 'standalone', 'identifier': payload['generation'], 'chart_index': unavailable_index,
    })
    assert context.status_code == 200
    assert context.json()['source_available'] is False
    assert context.json()['dataset_ids'] == []


def test_chart_preview_focus_row_matches_the_editors_sorted_row(client) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    content = (
        ','.join(CATALOG_HEADERS)
        + '\n2,Second slide,,Title and 1 column + Comments,Second chart,CDR-Data,Mean_Data_Rate,Average Vertical Bars,,Operator,,,,,'
        + '\n1,First slide,,Title and 1 column + Comments,First chart,CDR-Data,Mean_Data_Rate,Average Vertical Bars,,Operator,,,,,\n'
    ).encode()
    imported = client.post(
        '/admin/report-templates/nsa', data={'catalogue_name': 'Out of order'},
        files={'catalogue_file': ('out-of-order.csv', BytesIO(content), 'text/csv')},
        follow_redirects=False,
    )
    assert imported.status_code == 303
    job_id = app_module.repository.create_report_chart_job(
        technology='nsa', scope='single', dataset_ids={'data': [], 'voice': [], 'speech': []},
        dataset_names={}, template_name='Out of order', created_by='admin',
    )
    app_module.repository.update_report_chart_job(job_id, status='failed', generation='20260101-000000')

    context = client.get('/api/e2e-reporting/chart-preview/context', params={
        'source': 'standalone', 'identifier': '20260101-000000', 'chart_index': 0,
    })

    assert context.status_code == 200
    assert context.json()['chart_title'] == 'Second chart'
    assert context.json()['template_row_index'] == 1


def test_template_chart_image_preview_uses_combined_reporting_rows(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    catalogue_content = (
        ','.join(CATALOG_HEADERS)
        + '\n1,Preview slide,,Title and 1 column + Comments,Preview chart,CDR-Data,Mean_Data_Rate,Average Vertical Bars,,Operator,Campaign,,Top\n'
    )
    created = client.post(
        '/admin/report-templates/nsa', data={'catalogue_name': 'Combined Preview'},
        files={'catalogue_file': ('combined-preview.csv', BytesIO(catalogue_content.encode()), 'text/csv')},
        follow_redirects=False,
    )
    assert created.status_code == 303

    observed: dict[str, object] = {}
    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 7, 'status': 'ready', 'dataset_kind': 'data', 'updated_at': '', 'processed_at': '', 'normalization_version': ''},
    ])
    monkeypatch.setattr(app_module.repository, 'load_dataset_rows', lambda *_args: pytest.fail('Individual CDR tables must not be loaded.'))
    monkeypatch.setattr(
        app_module,
        '_combined_reporting_frame',
        lambda datasets, technology, entries, multivendor: observed.update({
            'dataset_ids': [dataset['id'] for dataset in datasets],
            'technology': technology,
            'entries': entries,
            'multivendor': multivendor,
        }) or pd.DataFrame(),
    )
    monkeypatch.setattr(app_module, '_cached_filtered_chart_frame', lambda _key, frame, *_args: frame)
    monkeypatch.setattr(app_module, 'render_catalog_chart_preview', lambda *_args, **_kwargs: b'PNG')
    monkeypatch.setattr(
        app_module,
        'preview_catalog_chart_data',
        lambda *_args, **_kwargs: (pd.DataFrame([{'Operator': 'EE'}]), {'filter_values': {}}),
    )

    data_preview = client.post(
        '/admin/report-templates/nsa/Combined%20Preview/chart-preview',
        json={'catalogue_content': catalogue_content, 'row_index': 0},
    )
    data_export = client.post(
        '/admin/report-templates/nsa/Combined%20Preview/chart-preview',
        json={'catalogue_content': catalogue_content, 'row_index': 0, 'download': True},
    )

    preview = client.post(
        '/admin/report-templates/nsa/Combined%20Preview/chart-image-preview',
        json={'catalogue_content': catalogue_content, 'row_index': 0},
    )

    assert data_preview.status_code == 200
    assert data_preview.json()['rows'] == [{'Operator': 'EE'}]
    assert set(data_preview.json()['column_metadata']) == {'Operator'}
    assert data_export.headers['content-type'].startswith('text/csv')
    assert data_export.text == 'Operator\nEE\n'
    assert preview.status_code == 200
    assert preview.content == b'PNG'
    assert observed['dataset_ids'] == [7]
    assert observed['technology'] == 'nsa'
    assert observed['multivendor'] is False


def test_reporting_requires_at_least_one_cdr_source(client) -> None:
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    form = {'technology': 'nsa', 'report_scope': 'single', 'slides_templates': 'nsa:NSA Slide Template'}
    report = client.post('/reporting/netcheck-cdr', data=form)
    charts = client.post('/reporting/netcheck-cdr/charts', data=form)
    assert report.status_code == 400
    assert charts.status_code == 400
    assert report.json()['detail'] == 'Select at least one Data, Voice or Speech CDR.'


def test_partial_cdr_report_worker_receives_unavailable_frames(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploaded = client.post(
        '/datasets-analysis/upload', data={'dataset_kinds': 'data'},
        files={'dataset_files': ('NetCheck_CDR_Data.csv', BytesIO(b'RAT,Operator,Mean_Data_Rate,Test_Result\nENDC,Vodafone UK,42,Success\n'), 'text/csv')},
    )
    assert uploaded.status_code == 200
    observed: dict[str, bool] = {}

    def render_report(destination, _template, _frames, _technology, _multivendor, _entries, **kwargs):
        loader = kwargs['frame_loader']
        observed['data'] = bool(loader('data').attrs.get('report_source_unavailable'))
        observed['voice'] = bool(loader('voice').attrs.get('report_source_unavailable'))
        observed['speech'] = bool(loader('speech').attrs.get('report_source_unavailable'))
        Path(destination).write_bytes(b'PK')

    monkeypatch.setattr(app_module, 'render_cdr_report', render_report)
    response = client.post('/reporting/netcheck-cdr', data={
        'data_dataset_id': 1, 'technology': 'nsa', 'report_scope': 'single',
        'slides_templates': 'nsa:NSA Slide Template',
    })
    assert response.status_code == 202
    job = wait_for_report_job(client, response.json()['job_id'])
    assert job['status'] == 'ready'
    assert observed == {'data': False, 'voice': True, 'speech': True}


def test_temporary_preview_accepts_dataset_ids_with_legacy_multiplication_separator(monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    monkeypatch.setattr(app_module.repository, 'list_datasets', lambda: [
        {'id': 2, 'status': 'ready', 'dataset_kind': 'voice'},
        {'id': 5, 'status': 'ready', 'dataset_kind': 'voice'},
    ])

    assert app_module._temporary_preview_dataset_ids({'dataset_ids': '2 × 5'}, {}, 'voice') == [2, 5]


def test_report_chart_generation_failures_return_json_and_are_logged(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    for filename, kind, content in (
        ('NetCheck_CDR_Data.csv', 'data', b'RAT,Operator,Mean_Data_Rate\nENDC,Vodafone UK,42\n'),
        ('NetCheck_CDR_Voice.csv', 'voice', b'RAT_A,Operator,Call_Status\nENDC,Vodafone UK,Completed\n'),
        ('NetCheck_CDR_Speech.csv', 'speech', b'Sample_RAT_A,Operator,LQ\nENDC,Vodafone UK,3.8\n'),
    ):
        upload = client.post('/datasets-analysis/upload', data={'dataset_kinds': kind}, files={'dataset_files': (filename, BytesIO(content), 'text/csv')})
        assert upload.status_code == 200

    def fail_render(*_args, **_kwargs):
        raise RuntimeError('Synthetic renderer failure')

    monkeypatch.setattr(app_module, 'render_catalog_chart_preview', fail_render)
    monkeypatch.setattr(app_module, 'report_chart_renderer_name', lambda: 'pil')
    response = client.post('/reporting/netcheck-cdr/charts', data={
        'data_dataset_id': 1, 'voice_dataset_id': 2, 'speech_dataset_id': 3,
        'technology': 'nsa', 'report_scope': 'single', 'slides_templates': 'nsa:NSA Slide Template',
    })

    assert response.status_code == 202
    job = wait_for_report_chart_job(client, response.json()['job_id'])
    assert job['status'] == 'failed'
    assert job['error'].endswith(': Synthetic renderer failure')
    assert job['error'].startswith('Slide ')
    log = next(row for row in app_module.repository.list_logs() if row['action'] == 'chart_set_generation_failed')
    assert log['username'] == 'admin'
    assert 'Synthetic renderer failure' in log['details']
    app_log = next(row for row in app_module.build_app_logs() if row['action'] == 'chart_set_generation_failed')
    assert app_log['log_type'] == 'Error'
    assert app_log['username'] == 'admin'
    assert app_log['executed_by'] == 'system'
    assert re.match(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Chart Set job 1 failed: Slide ', app_log['summary'])
    assert app_log['summary'].endswith(': Synthetic renderer failure')
    assert 'Synthetic renderer failure' in client.get('/reporting').text
    app_logs_page = client.get('/app-logs').text
    assert 'Chart Set job 1 failed: Slide ' in app_logs_page
    assert 'Synthetic renderer failure' in app_logs_page


def test_report_generation_failures_show_the_error_and_are_logged(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    for filename, kind, content in (
        ('NetCheck_CDR_Data.csv', 'data', b'RAT,Operator,Mean_Data_Rate\nENDC,Vodafone UK,42\n'),
        ('NetCheck_CDR_Voice.csv', 'voice', b'RAT_A,Operator,Call_Status\nENDC,Vodafone UK,Completed\n'),
        ('NetCheck_CDR_Speech.csv', 'speech', b'Sample_RAT_A,Operator,LQ\nENDC,Vodafone UK,3.8\n'),
    ):
        assert client.post('/datasets-analysis/upload', data={'dataset_kinds': kind}, files={
            'dataset_files': (filename, BytesIO(content), 'text/csv'),
        }).status_code == 200

    def fail_render(*_args, **_kwargs):
        raise RuntimeError('Synthetic PowerPoint failure')

    monkeypatch.setattr(app_module, 'render_cdr_report', fail_render)
    response = client.post('/reporting/netcheck-cdr', data={
        'data_dataset_id': 1, 'voice_dataset_id': 2, 'speech_dataset_id': 3,
        'technology': 'nsa', 'report_scope': 'single', 'slides_templates': 'nsa:NSA Slide Template',
    })

    assert response.status_code == 202
    job = wait_for_report_job(client, response.json()['job_id'])
    assert job['status'] == 'failed'
    assert job['error'] == 'Synthetic PowerPoint failure'
    app_log = next(row for row in app_module.build_app_logs() if row['action'] == 'export_netcheck_cdr_report_failed')
    assert re.match(
        r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Report job 1 failed: Synthetic PowerPoint failure$',
        app_log['summary'],
    )
    assert 'Synthetic PowerPoint failure' in client.get('/reporting').text
    assert 'Report job 1 failed: Synthetic PowerPoint failure' in client.get('/app-logs').text


def test_reporting_concatenates_multiple_campaign_cdrs_per_source(client, monkeypatch) -> None:
    import src.DashboardAnalytic as app_module

    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploads = [
        ('data-q1.csv', 'data', b'RAT_A,Campaign,Operator,Data_Q1\nENDC,2026 Q1,EE,10\n'),
        ('data-q2.csv', 'data', b'RAT_A,Campaign,Operator,Data_Q2\nENDC,2026 Q2,EE,20\n'),
        ('voice-q2.csv', 'voice', b'RAT_A,Campaign,Operator,Call_Status\nENDC,2026 Q2,EE,Completed\n'),
        ('speech-q2.csv', 'speech', b'RAT_A,Campaign,Operator,LQ\nENDC,2026 Q2,EE,3.8\n'),
    ]
    for filename, kind, content in uploads:
        response = client.post(
            '/datasets-analysis/upload',
            data={'dataset_kinds': kind},
            files={'dataset_files': (filename, BytesIO(content), 'text/csv')},
        )
        assert response.status_code == 200

    captured: dict[str, pd.DataFrame] = {}

    def capture_report(destination, template, frames, technology, multivendor, catalog, **kwargs):
        frame_loader = kwargs.get('frame_loader')
        captured.update(frames or {kind: frame_loader(kind) for kind in ('data', 'voice', 'speech')})
        destination.write_bytes(b'PK')
        return destination

    monkeypatch.setattr(app_module, 'render_cdr_report', capture_report)
    payload = urlencode([
        ('data_dataset_id', '1'), ('data_dataset_id', '2'),
        ('voice_dataset_id', '3'), ('speech_dataset_id', '4'),
            ('technology', 'nsa'), ('report_scope', 'single'), ('slides_templates', 'nsa:NSA Slide Template'),
    ])
    response = client.post(
        '/reporting/netcheck-cdr',
        content=payload,
        headers={'content-type': 'application/x-www-form-urlencoded'},
    )

    assert response.status_code == 202
    job = wait_for_report_job(client, response.json()['job_id'])
    assert job['status'] == 'ready'
    assert captured['data']['Campaign'].tolist() == ['2026 Q1', '2026 Q2']
    # The shared CDR table and renderer materialise only fields required by
    # the chosen Slides Template; unrelated source metrics stay individual.
    assert not {'Data_Q1', 'Data_Q2'}.intersection(app_module.repository.list_reporting_row_columns('data'))
