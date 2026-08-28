from __future__ import annotations

import re
import pandas as pd
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from pptx import Presentation
from pptx.dml.color import RGBColor

from src.modules.cdr_reporting import CATALOG_HEADERS, _apply_catalog_filters, _apply_catalog_grouping, _render_failure_count, _render_status_100, assign_cdr_vendors, classify_sessions, convert_catalog_csv, ensure_report_vendor_group, enrich_multivendor, load_catalog_csv, parse_catalog_csv, parse_catalog_filters, parse_catalog_grouping, render_cdr_report, vendor_from_cells


def test_vendor_formula_keeps_vodafone_ericsson_null_exception_as_mixed() -> None:
    lookup = {'first': 'Ericsson'}

    assert vendor_from_cells('Vodafone UK', 'first -> unknown', lookup) == 'Vodafone_Mixed Vendor'
    assert vendor_from_cells('Vodafone UK', 'first -> first', lookup) == 'Vodafone_Ericsson'
    assert vendor_from_cells('3', 'first -> unknown', lookup) == '3_Mixed Vendor'
    assert vendor_from_cells('O2', 'first -> unknown', lookup) == 'O2'


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
    assert enrich_multivendor(nsa, vodafone_mapping, three_mapping)['report_vendor'].tolist() == ['Vodafone_Ericsson']
    assert enrich_multivendor(sa, vodafone_mapping, three_mapping)['report_vendor'].tolist() == ['3_Mixed Vendor']


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

    assert mapped['vendor'].tolist() == ['Vodafone_Ericsson', '3_Mixed Vendor', pd.NA]
    assert mapped['report_vendor'].tolist() == ['Vodafone_Ericsson', '3_Mixed Vendor', 'O2 (UK)']


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


def test_legacy_workspace_mapping_gets_the_report_group_without_writing_operator_as_vendor() -> None:
    frame = pd.DataFrame({'Operator': ['Vodafone UK', 'O2 (UK)'], 'vendor': ['Vodafone_Ericsson', pd.NA]})

    grouped = ensure_report_vendor_group(frame)

    assert grouped['report_vendor'].tolist() == ['Vodafone_Ericsson', 'O2 (UK)']


def test_vodafone_mapping_derives_gcid_from_4g_enodeb_and_local_cell() -> None:
    cdr = pd.DataFrame({'Operator': ['Vodafone UK'], 'Cell_IDs_A': ['3330049']})
    vodafone_mapping = pd.DataFrame({
        'source_sheet': ['4G'],
        'eNodeB ID': [13008],
        'Local Cell ID': [1],
        'OP/ Vendor': ['Samsung'],
    })
    three_mapping = pd.DataFrame({'Cid__ECI': [1], 'Vendor': ['Nokia']})

    assert enrich_multivendor(cdr, vodafone_mapping, three_mapping)['report_vendor'].tolist() == ['Vodafone_Samsung']


def test_catalogue_csv_requires_the_report_chart_contract_columns() -> None:
    catalogue = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,Voice quality,Title and 1 column + Comments,Completed call ratio,CDR-Voice,Call_Status,100% Stacked Vertical Bars,Completed/Dropped/Failed,Call Family = VoLTE,Operator,Campaign\n'
    ).encode('utf-8')

    entries = parse_catalog_csv(catalogue, 'nsa')

    assert entries[0].slide == 8
    assert entries[0].slide_title == 'Completed Call Ratio'
    assert entries[0].slide_subtitle == 'Voice quality'
    assert entries[0].chart_title == 'Completed call ratio'
    assert entries[0].legend == 'Completed/Dropped/Failed'
    assert entries[0].source_kind == 'voice'
    assert entries[0].chart_type == '100% Stacked Vertical Bars'


def test_catalogue_filter_and_grouping_contract_is_parsed_and_applied() -> None:
    conditions = parse_catalog_filters('Session_Type IN (VoLTE, MultiRAB); LQ >= 1.6')
    grouping = parse_catalog_grouping('City × Operator × Campaign')
    assert [(item.column, item.operator, item.values) for item in conditions] == [
        ('Session_Type', 'IN', ('VoLTE', 'MultiRAB')), ('LQ', '>=', ('1.6',)),
    ]
    assert grouping.dimensions == ('City', 'Operator', 'Campaign')
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,Quality by city,CDR-Speech,LQ,Average Vertical Bars,,Session_Type IN (VoLTE); LQ >= 1.6,City,Operator × Campaign\n',
        'nsa',
    )[0]
    frame = pd.DataFrame({
        'Session_Type': ['VoLTE', 'WhatsApp'], 'LQ': [3.2, 4.0], 'City': ['London', 'Leeds'],
        'Operator': ['EE', 'O2'], 'Campaign': ['Q1', 'Q1'],
    })
    filtered = _apply_catalog_filters(frame, entry, False, 'LQ')
    grouped, primary, series = _apply_catalog_grouping(filtered, entry, False, 'LQ')
    assert len(grouped) == 1
    assert grouped[primary].tolist() == ['London']
    assert grouped[series].tolist() == ['EE · Q1']
    assert '__catalog_stack' not in grouped.columns


def test_rows_only_grouping_uses_one_all_series_without_repeating_the_category() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Speech,LQ,Average Vertical Bars,,,Operator,\n',
        'nsa',
    )[0]
    frame = pd.DataFrame({'Operator': ['EE', 'O2'], 'LQ': [3.2, 3.8]})

    grouped, primary, series = _apply_catalog_grouping(frame, entry, False, 'LQ')

    assert grouped[primary].tolist() == ['EE', 'O2']
    assert grouped[series].tolist() == ['(all)', '(all)']


def test_catalogue_filter_contract_supports_not_in_and_not_contains() -> None:
    conditions = parse_catalog_filters('Session_Type NOT IN (WhatsApp, SMS); Campaign NOT CONTAINS legacy')
    assert [(item.column, item.operator, item.values) for item in conditions] == [
        ('Session_Type', 'NOT IN', ('WhatsApp', 'SMS')),
        ('Campaign', 'NOT CONTAINS', ('legacy',)),
    ]
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,Quality,CDR-Speech,LQ,Average Vertical Bars,,Session_Type NOT IN (WhatsApp); Campaign NOT CONTAINS legacy,Operator,Campaign\n',
        'nsa',
    )[0]
    frame = pd.DataFrame({
        'Session_Type': ['VoLTE', 'WhatsApp', 'VoLTE'], 'Campaign': ['Q1', 'Q1', 'legacy-Q2'],
        'LQ': [3.2, 4.0, 3.8], 'Operator': ['EE', 'EE', 'O2'],
    })
    assert _apply_catalog_filters(frame, entry, False, 'LQ')['Operator'].tolist() == ['EE']


def test_catalogue_call_family_uses_documented_netcheck_session_values() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,,Title and 1 column + Comments,,CDR-Voice,Call_Status,100% Stacked Vertical Bars,,"Call Family IN (VoLTE, MultiRAB, WhatsApp)",Call Family,Operator × Campaign\n',
        'nsa',
    )[0]
    frame = pd.DataFrame({
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


def test_failure_count_uses_row_and_column_hierarchies_without_flattening() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n9,Voice failures per Q/city,,Title and 1 column + Comments,Failures,CDR-Voice,Call_Status,Count Stacked Horizontal Bars,Failed/Dropped,,Call Family × G Level 4,Operator × Campaign\n',
        'nsa',
    )[0]
    frame = pd.DataFrame({
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


def test_nsa_catalogue_splits_template_screenshots_into_individual_charts() -> None:
    entries = load_catalog_csv(Path('assets/ppt-slides-catalog/nsa-slide-catalogue.csv'), 'nsa')
    slide_ten = [entry for entry in entries if entry.slide == 10]
    slide_thirteen = [entry for entry in entries if entry.slide == 13]

    assert len(slide_ten) == 2
    assert {entry.layout for entry in slide_ten} == {'Title and 2 rows + Comments right'}
    assert len(slide_thirteen) == 3
    assert {entry.layout for entry in slide_thirteen} == {'Title and 3 columns + Comments'}
    assert {slide: sum(entry.slide == slide for entry in entries) for slide in range(12, 22)} == {
        12: 2, 13: 3, 14: 2, 15: 2, 16: 2,
        17: 2, 18: 3, 19: 3, 20: 4, 21: 2,
    }


def test_catalogue_uses_one_preservation_type_and_records_nsa_conclusions_table() -> None:
    entries = load_catalog_csv(Path('assets/ppt-slides-catalog/nsa-slide-catalogue.csv'), 'nsa')
    preserved = [entry.chart_type for entry in entries if not entry.source_kind and entry.slide != 22]
    conclusions = next(entry for entry in entries if entry.slide == 22)

    assert set(preserved) == {'Not Automated (preserve)'}
    assert conclusions.chart_type == 'Table'


def test_catalogue_rows_use_matching_master_image_placeholders(tmp_path) -> None:
    catalogue = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,Voice quality,Title and 2 columns + Comments,Status ratio,CDR-Voice,Call_Status,100% Stacked Vertical Bars,Completed/Dropped/Failed,Call Family = VoLTE,Call Family,Operator × Campaign'
        + '\n8,Completed Call Ratio,Voice quality,Title and 2 columns + Comments,Setup time,CDR-Voice,Call_Setup_Time,Average Vertical Bars,,Call Family = VoLTE,Call Family,Operator × Campaign\n'
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
        Path('assets/templates/Template_CDR_NSA_analysis.pptx'),
        frames,
        'nsa',
        False,
        parse_catalog_csv(catalogue, 'nsa'),
    )

    slide = Presentation(destination).slides[7]
    assert sum(1 for shape in slide.shapes if hasattr(shape, 'image')) >= 2
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


def test_reporting_module_is_available_to_authenticated_users(client) -> None:
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert response.status_code == 303

    page = client.get('/reporting')

    assert page.status_code == 200
    assert 'NetCheck CDR Reports' in page.text
    assert 'Smart Orchestrator Logs Reports' in page.text
    assert 'Generate PowerPoint Report' in page.text
    assert 'name="vodafone_mapping_dataset_id"' not in page.text
    assert 'name="three_mapping_dataset_id"' not in page.text
    assert '<option value="multivendor" disabled>Multivendor</option>' in page.text
    assert 'name="slide_catalogue"' in page.text
    assert 'value="nsa:default"' in page.text
    assert 'data-download-form="1"' in page.text


def test_reporting_multivendor_requires_a_previously_mapped_selected_cdr(client) -> None:
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploads = [
        ('NetCheck_CDR_Data.csv', 'data', b'RAT,Operator,Mean_Data_Rate\nENDC,Vodafone UK,42\n'),
        ('NetCheck_CDR_Voice.csv', 'voice', b'RAT_A,Operator,Call_Duration\nENDC,Vodafone UK,60\n'),
        ('NetCheck_CDR_Speech.csv', 'speech', b'Sample_RAT_A,Operator,LQ\nENDC,Vodafone UK,3.8\n'),
    ]
    for filename, dataset_kind, content in uploads:
        response = client.post(
            '/dashboard/upload',
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
    assert 'requires at least one selected CDR with a Workspace Vendor mapping' in report.text


def test_netcheck_reporting_generates_template_backed_pptx(client) -> None:
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploads = [
        ('NetCheck_CDR_Data.csv', b'RAT,Operator,Mean_Data_Rate,Test_Result\nENDC,Vodafone UK,42,Success\n', 'text/csv'),
        ('NetCheck_CDR_Voice.csv', b'RAT_A,Operator,Call_Status,Call_Duration\nENDC,Vodafone UK,Completed,60\n', 'text/csv'),
        ('NetCheck_CDR_Speech.csv', b'Sample_RAT_A,Operator,LQ\nENDC,Vodafone UK,3.8\n', 'text/csv'),
    ]
    for filename, content, media_type in uploads:
        response = client.post('/dashboard/upload', files={'dataset_files': (filename, BytesIO(content), media_type)})
        assert response.status_code == 200

    report = client.post('/reporting/netcheck-cdr', data={
        'data_dataset_id': 1,
        'voice_dataset_id': 2,
        'speech_dataset_id': 3,
        'technology': 'nsa',
        'report_scope': 'single',
        'slide_catalogue': 'nsa:default',
    })

    assert report.status_code == 200
    assert report.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.presentationml.presentation')
    assert report.content[:2] == b'PK'
    assert re.search(r'NetCheck_CDR_NSA_single_vendor_\d{8}-\d{4}\.pptx', report.headers['content-disposition'])
