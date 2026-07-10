from __future__ import annotations

from typing import Any


def build_chart_payload(sorted_pairs: list[tuple[float, float]]) -> dict[str, Any]:
    return {
        "labels": [round(pair[0], 4) for pair in sorted_pairs],
        "series": [round(pair[1], 4) for pair in sorted_pairs],
    }
