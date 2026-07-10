from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(slots=True)
class DatasetSummary:
    rows: int
    columns: list[str]
    numeric_columns: list[str]
    categorical_columns: list[str]


def load_dataset(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    raise ValueError(f"Unsupported file type: {suffix}")


def summarise_dataset(df: pd.DataFrame) -> DatasetSummary:
    numeric_columns = df.select_dtypes(include=["number"]).columns.tolist()
    categorical_columns = [column for column in df.columns.tolist() if column not in numeric_columns]
    return DatasetSummary(
        rows=len(df.index),
        columns=df.columns.tolist(),
        numeric_columns=numeric_columns,
        categorical_columns=categorical_columns,
    )
