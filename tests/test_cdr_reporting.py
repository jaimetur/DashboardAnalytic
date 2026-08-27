from __future__ import annotations

import re
import pandas as pd
from io import BytesIO
from pathlib import Path
from pptx import Presentation

from src.modules.cdr_reporting import CATALOG_HEADERS, _apply_catalog_filters, _apply_catalog_grouping, classify_sessions, enrich_multivendor, parse_catalog_csv, parse_catalog_filters, parse_catalog_grouping, render_cdr_report, vendor_from_cells


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
        + '\n8,Completed Call Ratio,Voice quality,Title and 1 column + Comments,CDR-Voice,Call_Status,100% Stacked Vertical Bars,Call Family = VoLTE,Operator × Campaign\n'
    ).encode('utf-8')

    entries = parse_catalog_csv(catalogue, 'nsa')

    assert entries[0].slide == 8
    assert entries[0].slide_title == 'Completed Call Ratio'
    assert entries[0].slide_subtitle == 'Voice quality'
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
        ','.join(CATALOG_HEADERS) + '\n8,Quality,,Title and 1 column + Comments,CDR-Speech,LQ,Average Vertical Bars,Session_Type IN (VoLTE); LQ >= 1.6,City × Operator × Campaign\n',
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
    assert grouped[series].tolist() == ['EE']
    assert grouped['__catalog_stack'].tolist() == ['Q1']


def test_catalogue_call_family_uses_documented_netcheck_session_values() -> None:
    entry = parse_catalog_csv(
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,,Title and 1 column + Comments,CDR-Voice,Call_Status,100% Stacked Vertical Bars,"Call Family IN (VoLTE, MultiRAB, WhatsApp)",Call Family × Operator × Campaign\n',
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
    grouped, primary, _ = _apply_catalog_grouping(filtered, entry, False, 'Call_Status')

    assert grouped[primary].tolist() == ['VoLTE', 'MultiRAB', 'WhatsApp']


def test_catalogue_rows_use_matching_master_image_placeholders(tmp_path) -> None:
    catalogue = (
        ','.join(CATALOG_HEADERS)
        + '\n8,Completed Call Ratio,Voice quality,Title and 2 columns + Comments,CDR-Voice,Call_Status,100% Stacked Vertical Bars,Call Family = VoLTE,Operator × Campaign'
        + '\n8,Completed Call Ratio,Voice quality,Title and 2 columns + Comments,CDR-Voice,Call_Setup_Time,Average Vertical Bars,Call Family = VoLTE,Operator × Campaign\n'
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
    assert any(getattr(shape, 'text', '') == 'Voice quality' for shape in slide.shapes)


def test_reporting_module_is_available_to_authenticated_users(client) -> None:
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert response.status_code == 303

    page = client.get('/reporting')

    assert page.status_code == 200
    assert 'NetCheck CDR Reports' in page.text
    assert 'Smart Orchestrator Logs Reports' in page.text
    assert 'Generate PowerPoint Report' in page.text
    assert 'data-mapping-selector hidden' in page.text
    assert 'name="vodafone_mapping_dataset_id"' in page.text
    assert 'name="three_mapping_dataset_id"' in page.text
    assert 'data-download-form="1"' in page.text


def test_reporting_mapping_selectors_show_only_matching_workspace_mapping_types(client) -> None:
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    uploads = [
        ('Multivendor_Mapping_VFUK.csv', 'mapping_vodafone', b'eNodeB ID,Local Cell ID,OP/ Vendor\n0,100,Ericsson\n'),
        ('Multivendor_Mapping_3UK.csv', 'mapping_three', b'Cid__ECI,Vendor\n100,Nokia\n'),
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
    vfuk_selector = page.text.split('name="vodafone_mapping_dataset_id"', 1)[1].split('</select>', 1)[0]
    three_selector = page.text.split('name="three_mapping_dataset_id"', 1)[1].split('</select>', 1)[0]
    assert 'VFUK Vendor Mapping' in page.text
    assert '3UK Vendor Mapping' in page.text
    assert 'Multivendor_Mapping_VFUK.csv' in vfuk_selector
    assert 'Multivendor_Mapping_3UK.csv' not in vfuk_selector
    assert 'Multivendor_Mapping_3UK.csv' in three_selector
    assert 'Multivendor_Mapping_VFUK.csv' not in three_selector


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
    })

    assert report.status_code == 200
    assert report.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.presentationml.presentation')
    assert report.content[:2] == b'PK'
    assert re.search(r'NetCheck_CDR_NSA_single_vendor_\d{8}-\d{4}\.pptx', report.headers['content-disposition'])
