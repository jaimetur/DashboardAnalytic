import sqlite3
from pathlib import Path

import pandas as pd

from src.modules.column_names import (
    operator_vendor_filter_values, operator_vendor_value, vendor_filter_column, vendor_match_values,
)
from src.modules.ingestion import ensure_fixed_cdr_fields
from src.modules.report_layouts import rename_template_vendor_fields
from src.modules.repository import Repository


def test_source_vendor_becomes_operator_vendor_and_vendor_keeps_the_vendor_alone() -> None:
    frame = ensure_fixed_cdr_fields(pd.DataFrame({
        'Operator': ['Vodafone UK', 'EE', 'O2 (UK)', '3'],
        'Vendor': ['Vodafone_Ericsson', 'EE', '', 'Nokia'],
    }))

    assert frame['Operator_Vendor'].tolist() == ['Vodafone_Ericsson', 'EE - All', 'O2 (UK) - All', '3_Nokia']
    assert frame['Vendor'].tolist() == ['Ericsson', 'EE - All', 'O2 (UK) - All', 'Nokia']
    # Files exported with the former names keep their meaning.
    legacy = ensure_fixed_cdr_fields(pd.DataFrame({
        'Operator': ['Vodafone UK'], 'Vendor': ['Vodafone_Huawei'], 'Vendor_Only': ['Huawei'],
    }))
    assert legacy[['Operator_Vendor', 'Vendor']].values.tolist() == [['Vodafone_Huawei', 'Huawei']]
    assert 'Vendor_Only' not in legacy.columns


def test_vendor_filter_names_and_values() -> None:
    assert [vendor_filter_column(name) for name in ('Vendor', 'Vendor_Only', 'Vendor V3', 'OP_Vendor', 'Operator_Vendor', 'City')] == [
        'Vendor', 'Vendor', 'Vendor', 'Operator_Vendor', 'Operator_Vendor', 'City']
    assert operator_vendor_value('Ericsson', 'Vodafone UK') == 'Vodafone UK_Ericsson'
    assert operator_vendor_filter_values(['EE', 'VF_Ericsson'], ['EE']) == ['EE', 'EE - All', 'VF_Ericsson']
    assert vendor_match_values('Vendor', ['3_Ericsson'], ['3']) == ['Ericsson']
    assert vendor_match_values('Region', ['North'], []) == ['North']


def _legacy_workspace(path: Path) -> None:
    """A workspace written before Operator_Vendor: CDR Vendor composites and Vendor_Only."""
    Repository(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            DELETE FROM workspace_state WHERE key IN ('cdr_vendor_fields_operator_vendor_v1', 'report_template_vendor_fields_v1');
            CREATE TABLE dataset_rows_1 (Operator TEXT, Vendor TEXT, Vendor_Only TEXT, score REAL);
            CREATE INDEX idx_dataset_rows_1_vendor_norm ON dataset_rows_1 (LOWER(TRIM(CAST(Vendor AS TEXT))));
            CREATE TABLE reporting_rows_data (dataset_id INTEGER, source_row_id INTEGER, Operator TEXT, Vendor TEXT, Vendor_Only TEXT);
            CREATE TABLE dataset_rows_2 (Operator TEXT, Vendor TEXT, Vendor_Only TEXT);
        """)
        connection.execute("INSERT INTO datasets (id, file_name, stored_path, uploaded_by) VALUES (1, 'cdr.csv', 'cdr.csv', 'test'), (2, 'map.csv', 'map.csv', 'test')")
        connection.execute("INSERT OR REPLACE INTO dataset_profiles (dataset_id, status, dataset_kind) VALUES (1, 'ready', 'data'), (2, 'ready', 'mapping_three')")
        connection.executemany('INSERT INTO dataset_rows_1 VALUES (?, ?, ?, ?)', [
            ('Vodafone UK', 'Vodafone_Ericsson', 'Ericsson', 1.0), ('EE', 'EE', 'EE - All', 2.0),
        ])
        connection.execute("INSERT INTO reporting_rows_data VALUES (1, 2, 'EE', 'EE', 'EE - All')")
        connection.execute("INSERT INTO dataset_rows_2 VALUES ('', 'Ericsson', 'Ericsson')")
        connection.execute(
            "INSERT INTO report_templates (technology, name, content) VALUES ('nsa', 'Legacy', ?)",
            ('Slide,Layout,Filters,Rows Split,Legend\n1,x,Vendor IN (3_Ericsson); Vendor_Only = Huawei,Operator × Vendor,Vendor\n'.encode(),),
        )


def test_workspace_migration_renames_cdr_vendor_fields_once(tmp_path) -> None:
    database = tmp_path / 'legacy.db'
    _legacy_workspace(database)
    repository = Repository(database)
    repository.initialize()

    rows = repository.load_dataset_rows(1, ['Operator', 'Operator_Vendor', 'Vendor'], {})
    assert rows.to_dict('records') == [
        {'Operator': 'Vodafone UK', 'Operator_Vendor': 'Vodafone_Ericsson', 'Vendor': 'Ericsson'},
        {'Operator': 'EE', 'Operator_Vendor': 'EE - All', 'Vendor': 'EE - All'},
    ]
    assert repository.load_reporting_rows('data', [1], ['Operator_Vendor', 'Vendor']).values.tolist() == [['EE - All', 'EE - All']]
    # Vendor inventories keep their source columns.
    assert repository.list_dataset_row_columns(2) == ['Operator', 'Vendor', 'Vendor_Only']
    with repository.connection() as connection:
        indexes = {row[0] for row in connection.execute("SELECT sql FROM sqlite_master WHERE name = 'idx_dataset_rows_1_vendor_norm'")}
    assert indexes == set()
    template = repository.report_template_content('nsa', 'Legacy').decode('utf-8')
    assert 'Vendor IN (3_Ericsson); Vendor = Huawei,Operator × Operator_Vendor,Operator_Vendor' in template

    # A second start changes nothing, also in templates written with the new names.
    repository.set_report_template_content('nsa', 'Legacy', b'Slide,Layout,Filters,Rows Split,Legend\n1,x,,Vendor,Vendor\n')
    repository.initialize()
    assert repository.list_dataset_row_columns(1) == ['Operator', 'Operator_Vendor', 'Vendor', 'score']
    assert repository.report_template_content('nsa', 'Legacy').decode('utf-8').endswith('1,x,,Vendor,Vendor\n')


def test_template_conversion_keeps_vendor_filters_and_renames_aggregations() -> None:
    content = 'Slide,Layout,Filters,Dynamic Rows Field\n1,x,Vendor_Only NOT CONTAINS (Mixed),Vendor\n'.encode()
    assert rename_template_vendor_fields(content).decode() == (
        'Slide,Layout,Filters,Dynamic Rows Field\n1,x,Vendor NOT CONTAINS (Mixed),Operator_Vendor\n'
    )
