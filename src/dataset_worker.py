"""Isolated worker for parsing large CDR source files.

This module deliberately runs outside the Uvicorn process so openpyxl and
pandas cannot make the interactive application unresponsive.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.DashboardAnalytic import (
    CDR_DATASET_KINDS,
    _process_dataset,
    process_region_mapping,
    process_vendor_mapping,
    repository,
    start_combined_cdr_recreation_job,
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
    parser.add_argument('--operation', choices=('process', 'vendor-mapping', 'region-mapping'), default='process')
    parser.add_argument('--dataset-path', type=Path, required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--workspace-db', type=Path, required=True)
    parser.add_argument('--vodafone-mapping-dataset-id', type=int)
    parser.add_argument('--three-mapping-dataset-id', type=int)
    parser.add_argument('--region-mapping-dataset-id', type=int)
    args = parser.parse_args()

    task_repository = Repository(
        args.workspace_db,
        global_db_path=repository.global_db_path,
        workspace_registry_db_path=workspace_registry.registry_path,
    )
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
    if args.operation == 'region-mapping':
        if args.region_mapping_dataset_id is None:
            raise ValueError('A Region Mapping dataset is required.')
        process_region_mapping(args.dataset_id, args.username, args.region_mapping_dataset_id, task_repository)
        return
    combined_kind = _process_dataset(
        args.dataset_id, args.dataset_path, args.username,
        args.vodafone_mapping_dataset_id, args.three_mapping_dataset_id,
        task_repository, workspace, args.region_mapping_dataset_id,
    )
    if workspace and combined_kind in CDR_DATASET_KINDS:
        start_combined_cdr_recreation_job(workspace, combined_kind, args.username, background=False)


if __name__ == '__main__':
    main()
