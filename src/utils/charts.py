from __future__ import annotations

from typing import Any


def build_chart_payload(sorted_pairs: list[tuple[float, float]]) -> dict[str, Any]:
    return {
        "labels": [round(pair[0], 4) for pair in sorted_pairs],
        "series": [round(pair[1], 4) for pair in sorted_pairs],
        "type": "line",
    }


def build_multi_series_chart_payload(series_collection: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "line",
        "series_collection": [
            {
                "name": str(item.get("name") or "Series"),
                "labels": [round(float(value), 4) for value in item.get("labels", [])],
                "series": [round(float(value), 4) for value in item.get("series", [])],
            }
            for item in series_collection
            if item.get("labels") and item.get("series")
        ],
    }
