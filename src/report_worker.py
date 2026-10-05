"""Run one Reporting Job execution of a workspace that is not open in the server.

The server process keeps the user's active workspace; this interpreter points
at the job's workspace, generates its artifacts and exits.
"""
from __future__ import annotations

import argparse
import os
from threading import Thread
from time import sleep
from pathlib import Path

import src.DashboardAnalytic as app_module
from src.dataset_worker import use_parent_databases


def main() -> None:
    try:
        os.nice(5)
    except OSError:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace-id', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--global-db', type=Path)
    parser.add_argument('--workspace-registry-db', type=Path)
    args = parser.parse_args()
    use_parent_databases(args)
    if args.parent_pid is not None:
        def stop_with_parent() -> None:
            while True:
                if os.getppid() != args.parent_pid:
                    os._exit(74)
                sleep(0.5)

        Thread(target=stop_with_parent, name='reporting-parent-watchdog', daemon=True).start()
    workspace = next((item for item in app_module.workspace_registry.list() if item.id == args.workspace_id), None)
    if workspace is None:
        raise SystemExit(f'Workspace {args.workspace_id} was not found.')
    app_module.use_workspace_for_background_job(workspace)
    app_module.execute_report_run(str(workspace.database_path.resolve()), args.run_id)


if __name__ == '__main__':
    main()
