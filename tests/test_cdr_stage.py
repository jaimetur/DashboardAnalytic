"""Final and Daily CDRs: the stage suggested from the file name and the CDRs of the combined tables."""

from io import BytesIO
from pathlib import Path

import pandas as pd

import src.DriveTestAnalyzer as core
from conftest import wait_for_background_dataset_work
from src.modules.cdr_stage import combined_inclusion, infer_cdr_stage
from src.modules.repository import local_now_iso


def login(client, username='super', password='super123'):
    client.cookies.clear()
    response = client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    assert response.status_code == 303


def add_cdr(tmp_path: Path, name: str, kind: str, rows: pd.DataFrame, stage: str, nr_mode: str = 'SA') -> int:
    repository = core.repository
    source = tmp_path / name
    source.write_text('test source', encoding='utf-8')
    dataset_id, _created = repository.add_dataset(name, str(source), 'super')
    repository.replace_dataset_rows(dataset_id, rows)
    repository.update_dataset_profile(
        dataset_id, status='ready', progress=100, dataset_kind=kind, nr_mode=nr_mode, cdr_stage=stage,
        row_count=len(rows), column_count=len(rows.columns), processed_at=local_now_iso(),
    )
    repository.copy_dataset_rows_to_reporting(dataset_id, kind)
    return dataset_id


def voice(join_ids: list[str], day: str, campaign: str = 'UK_Q3_SA_2026') -> pd.DataFrame:
    return pd.DataFrame({
        'JOIN_ID': join_ids, 'Operator': ['Vodafone'] * len(join_ids), 'Campaign': [campaign] * len(join_ids),
        'Session_ID_A': list(range(1, len(join_ids) + 1)), 'Call_Status': ['Failed'] * len(join_ids),
        'status': ['Failed'] * len(join_ids), 'Call_Start_Time': [f'{day} 10:00:00'] * len(join_ids),
    })


def combined_ids(kind: str = 'voice') -> set[int]:
    with core.repository.connection() as connection:
        return {int(row[0]) for row in connection.execute(f'SELECT DISTINCT dataset_id FROM reporting_rows_{kind}')}


def test_stage_is_suggested_from_the_file_name():
    assert infer_cdr_stage('NetCheck_UK_CDR_Voice_2026_Q1.xlsm') == 'final'
    assert infer_cdr_stage('20251021_UK Q3 Voice CDR 20250903-20251011.xlsm') == 'final'
    assert infer_cdr_stage('UK Q3 Voice Final 20261010.xlsx') == 'final'
    assert infer_cdr_stage('20260921_UK_Voice.xlsx') == 'final'
    assert infer_cdr_stage('UK_Voice_CDR_20260921.xlsx') == 'daily'
    assert infer_cdr_stage('Voice_Daily_2026-09-21.csv') == 'daily'
    assert infer_cdr_stage('UK_Q3_SA_2026_Voice_DailyCDR.xlsx') == 'daily'


def test_upload_saves_the_cdr_type_and_existing_cdrs_are_final(client, tmp_path):
    login(client)
    response = client.post(
        '/datasets-analysis/upload',
        data={'dataset_kinds': ['voice', 'voice'], 'cdr_stages': ['daily', '']},
        files=[('dataset_files', ('UK_Voice_20260921.csv', BytesIO(b'Operator,Call_Status\nEE,Failed\n'), 'text/csv')),
               ('dataset_files', ('UK_Voice_Q3.csv', BytesIO(b'Operator,Call_Status\nEE,Failed\n'), 'text/csv'))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    stages = {row['file_name']: row['cdr_stage'] for row in core.repository.list_datasets()}
    assert stages == {'UK_Voice_20260921.csv': 'daily', 'UK_Voice_Q3.csv': 'final'}
    assert client.post('/datasets-analysis/upload', data={'dataset_kinds': 'voice', 'cdr_stages': 'weekly'},
                       files={'dataset_files': ('x.csv', BytesIO(b'a\n1\n'), 'text/csv')}).status_code == 422


def test_final_cdrs_replace_the_daily_cdrs_of_their_campaign_in_the_combined_tables(client, tmp_path):
    login(client)
    day_one = add_cdr(tmp_path, 'UK_Voice_20260921.xlsx', 'voice', voice(['0xA', '0xB'], '2026-09-21'), 'daily')
    day_two = add_cdr(tmp_path, 'UK_Voice_20260922.xlsx', 'voice', voice(['0xC'], '2026-09-22'), 'daily')
    core.sync_combined_cdr_inclusion()
    # Incremental Daily CDRs are all included until the Final CDR arrives.
    assert combined_ids() == {day_one, day_two}
    final = add_cdr(tmp_path, 'UK_Voice_Q3_Final.xlsx', 'voice', voice(['0xA', '0xC'], '2026-09-30'), 'final')
    core.sync_combined_cdr_inclusion()
    inclusion = combined_inclusion(core.repository)
    assert combined_ids() == {final}
    assert inclusion[day_one]['included'] is False and 'Final CDR' in inclusion[day_one]['reason']
    assert core.combined_cdr_integrity('voice')['has_missing_rows'] is False

    # A Daily CDR can still be included by hand, and the Final CDR excluded; the combined tables
    # follow in a background job of the CDR Tables Updates card.
    assert client.post(f'/workspace/datasets/{day_two}/in-combined', json={'in_combined': 'yes'}).status_code == 200
    jobs = [job for job in core.AUTO_CALCULATED_FIELD_JOBS.values() if job.get('operation') == 'combined_inclusion']
    assert jobs and core.repository.get_dataset(day_two)['in_combined'] == 'yes'
    wait_for_background_dataset_work()
    assert combined_ids() == {final, day_two}
    changed = client.post(f'/workspace/datasets/{final}/in-combined', json={'in_combined': 'no'}).json()
    assert changed['combined'][str(day_one)]['included'] is True and changed['combined'][str(final)]['in_combined'] == 'no'
    wait_for_background_dataset_work()
    assert combined_ids() == {day_one, day_two}
    finished = [job for job in core.AUTO_CALCULATED_FIELD_JOBS.values() if job.get('operation') == 'combined_inclusion']
    assert finished and all(job['status'] == 'ready' for job in finished)
    assert 'Combined CDR tables updated: 1 CDR added, 1 removed' in {job['message'] for job in finished}
    client.post(f'/workspace/datasets/{final}/in-combined', json={'in_combined': 'auto'})
    client.post(f'/workspace/datasets/{day_two}/in-combined', json={'in_combined': 'auto'})

    # Marking the Final CDR as Daily brings its Daily CDRs back; deleting it does too.
    moved = client.post(f'/workspace/datasets/{final}/cdr-stage', json={'cdr_stage': 'daily'})
    assert moved.status_code == 200 and moved.json()['combined'][str(day_one)]['included'] is True
    client.post(f'/workspace/datasets/{final}/cdr-stage', json={'cdr_stage': 'final'})
    wait_for_background_dataset_work()
    assert combined_ids() == {final}
    assert client.post(f'/datasets-analysis/delete/{final}', follow_redirects=False).status_code == 303
    wait_for_background_dataset_work()
    assert combined_ids() == {day_one, day_two}
    assert client.post(f'/workspace/datasets/{day_one}/cdr-stage', json={'cdr_stage': 'weekly'}).status_code == 422
    assert client.post(f'/workspace/datasets/{day_one}/in-combined', json={'in_combined': 'include'}).status_code == 422


def test_a_cumulative_daily_cdr_replaces_the_previous_ones_in_the_combined_tables(client, tmp_path):
    login(client)
    first = add_cdr(tmp_path, 'UK_Voice_20260921.xlsx', 'voice', voice(['0xA', '0xB'], '2026-09-21'), 'daily')
    second = add_cdr(tmp_path, 'UK_Voice_20260922.xlsx', 'voice', voice(['0xA', '0xB', '0xC'], '2026-09-22'), 'daily')
    core.sync_combined_cdr_inclusion()
    inclusion = combined_inclusion(core.repository)
    assert inclusion[first]['included'] is False and 'newer Daily CDR' in inclusion[first]['reason']
    assert combined_ids() == {second}


def test_workspace_shows_the_cdrs_in_cards_with_their_type_and_combined_state(client, tmp_path):
    login(client)
    daily = add_cdr(tmp_path, 'UK_Voice_20260921.xlsx', 'voice', voice(['0xA'], '2026-09-21'), 'daily')
    final = add_cdr(tmp_path, 'UK_Voice_Q3_Final.xlsx', 'voice', voice(['0xA'], '2026-09-30'), 'final')
    core.sync_combined_cdr_inclusion()
    page = client.get('/workspace').text
    final_card = page.split('data-dataset-card="cdr-final"', 1)[1].split('data-dataset-card="cdr-daily"', 1)[0]
    daily_card = page.split('data-dataset-card="cdr-daily"', 1)[1].split('data-dataset-card="network-inventory"', 1)[0]
    assert f'data-dataset-id="{final}"' in final_card and f'data-dataset-id="{daily}"' in daily_card
    assert 'data-dataset-cdr-stage-select' in final_card and 'data-dataset-combined-select' in daily_card
    assert 'Replaced by the Final CDR UK_Voice_Q3_Final.xlsx' in daily_card
    assert 'In Combined?' in final_card and '>Yes</span>' in final_card and 'Final CDRs are always included' in final_card
    assert '>No</span>' in daily_card
    assert 'Geographic Datasets' in page and 'Network Inventory &amp; Vendor Mappings' in page
    status = client.get('/api/datasets/status').json()['datasets']
    entry = next(item for item in status if item['id'] == daily)
    assert entry['cdr_stage'] == 'daily' and entry['combined_included'] is False


def test_combined_tables_read_updating_while_they_follow_an_in_combined_change(client, tmp_path):
    login(client)
    final = add_cdr(tmp_path, 'UK_Voice_Q3_Final.xlsx', 'voice', voice(['0xA'], '2026-09-30'), 'final')
    core.sync_combined_cdr_inclusion()
    core.repository.update_dataset_profile(final, in_combined='no')
    workspace_id = core.active_workspace.id
    # The rows still differ from the included CDRs until the background job removes them.
    with core.AUTO_CALCULATED_FIELD_JOBS_LOCK:
        core.AUTO_CALCULATED_FIELD_JOBS['pending-sync'] = {
            'id': 'pending-sync', 'workspace_id': workspace_id, 'operation': 'combined_inclusion',
            'status': 'queued', 'completed': 0, 'total': 3, 'created_at': 0,
        }
    try:
        table = next(item for item in core.workspace_combined_tables(workspace_id=workspace_id) if item['kind'] == 'voice')
        assert table['has_missing_rows'] and table['is_recalculating'] and table['recreation_label'] == 'Updating'
        page = client.get('/workspace').text
        assert 'queue-row-not-combined' in page and 'active-row' not in page
    finally:
        with core.AUTO_CALCULATED_FIELD_JOBS_LOCK:
            core.AUTO_CALCULATED_FIELD_JOBS.pop('pending-sync', None)
