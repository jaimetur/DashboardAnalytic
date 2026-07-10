from __future__ import annotations

from pathlib import Path
from typing import Iterable


def ensure_directories(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def safe_join(root: Path, filename: str) -> Path:
    candidate = (root / filename).resolve()
    root = root.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Invalid file path")
    return candidate
