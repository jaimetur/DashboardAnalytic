"""Isolated worker for parsing large CDR source files.

This module deliberately runs outside the Uvicorn process so openpyxl and
pandas cannot make the interactive application unresponsive.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
from threading import Thread
from time import sleep
from pathlib import Path

from src.DashboardAnalytic import (
    _process_dataset,
    process_region_mapping,
    process_vendor_clearing,
    process_vendor_mapping,
    repository,
    workspace_registry,
)
from src.modules.repository import Repository


def main() -> None:
    # Keep interactive processes ahead of this optional background worker.
    try:
        os.nice(10)
    except OSError:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset-id', type=int, required=True)
    parser.add_argument('--operation', choices=('process', 'vendor-mapping', 'vendor-clearing', 'region-mapping'), default='process')
    parser.add_argument('--dataset-path', type=Path, required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--workspace-db', type=Path, required=True)
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--vodafone-mapping-dataset-id', type=int)
    parser.add_argument('--three-mapping-dataset-id', type=int)
    parser.add_argument('--region-mapping-dataset-id', type=int)
    args = parser.parse_args()
    if args.parent_pid is not None:
        def stop_with_parent() -> None:
            while True:
                if os.getppid() != args.parent_pid:
                    os._exit(74)
                sleep(0.5)

        Thread(target=stop_with_parent, name='dataset-parent-watchdog', daemon=True).start()

    task_repository = Repository(
        args.workspace_db,
        global_db_path=repository.global_db_path,
        workspace_registry_db_path=workspace_registry.registry_path,
    )
    lock_path = args.workspace_db.parent / f'.dataset-worker-{args.dataset_id}.lock'
    with lock_path.open('a+b') as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Another server process still owns this dataset. It will publish
            # the final state; this process must not overwrite its progress.
            sys.exit(75)
        try:
            run_dataset_operation(args, task_repository)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def run_dataset_operation(args: argparse.Namespace, task_repository: Repository) -> None:
    workspace = next(
        (item for item in workspace_registry.list() if item.database_path == args.workspace_db),
        None,
    )
    if args.operation == 'vendor-mapping':
        process_vendor_mapping(
            args.dataset_id, args.username, args.vodafone_mapping_dataset_id,
            args.three_mapping_dataset_id, task_repository,
        )
        return
    if args.operation == 'vendor-clearing':
        process_vendor_clearing(args.dataset_id, args.username, task_repository)
        return
    if args.operation == 'region-mapping':
        if args.region_mapping_dataset_id is None:
            raise ValueError('A Region Mapping dataset is required.')
        process_region_mapping(args.dataset_id, args.username, args.region_mapping_dataset_id, task_repository)
        return
    _process_dataset(
        args.dataset_id, args.dataset_path, args.username,
        args.vodafone_mapping_dataset_id, args.three_mapping_dataset_id,
        task_repository, workspace, args.region_mapping_dataset_id,
    )


if __name__ == '__main__':
    main()
