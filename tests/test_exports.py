from __future__ import annotations

from src.modules import exports


def test_powerpoint_cdf_export_applies_default_x_range_before_downsampling(monkeypatch) -> None:
    recorded_labels: list[float] = []

    def capture_downsample(labels, series, limit=0):
        recorded_labels[:] = labels
        return labels, series

    monkeypatch.setattr(exports, "_downsample_series", capture_downsample)

    exports._draw_line_chart({
        "type": "line",
        "series_collection": [
            {"name": "A", "labels": [1.0, 2.0, 3.0, 4.0], "series": [0.25, 0.5, 0.75, 1.0]},
        ],
        "x_view_max_default": 2.5,
        "x_axis_label": "Latency (ms)",
        "y_axis_label": "Cumulative probability",
    })

    assert recorded_labels == [1.0, 2.0]


def test_powerpoint_bar_export_accepts_vertical_axis_label() -> None:
    image = exports._draw_bar_chart({
        "type": "bar",
        "labels": ["A", "B"],
        "series": [0.4, 0.8],
        "y_axis_label": "Mean metric",
    })

    assert image.getbuffer().nbytes > 0
