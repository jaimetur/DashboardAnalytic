"""The CDR Tables Updates card never shows an update that nobody runs."""
import time

import src.DriveTestAnalyzer as core


def test_a_pending_update_without_a_job_runs_instead_of_showing_forever(client):
    client.post('/login', data={'username': 'super', 'password': 'super123'})
    # As after the first Auto-calculated Fields of a new workspace without CDRs.
    core.repository.set_workspace_state('calculated_dimensions_need_materialization', '1')
    statuses = []
    for _ in range(40):
        status = client.get('/api/workspace/auto-calculated-fields/materialization').json()
        statuses.append(status['status'])
        if status['status'] not in {'queued', 'processing'}:
            break
        time.sleep(.25)
    assert statuses[-1] == 'ready'
    assert core.repository.get_workspace_state('calculated_dimensions_need_materialization') == '0'
